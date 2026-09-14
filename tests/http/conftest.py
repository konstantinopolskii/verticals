"""Shared fixtures for suite B (`http`, docs/E2E.md §4) — a real uvicorn subprocess, real TCP
sockets over loopback, no mocks (E2E.md §1's house rule: FastAPI's TestClient/ASGITransport
never opens a socket and appears nowhere in this suite).

Layering, most specific last:

    db_dsn (tests/conftest.py)   a fresh F0 clone: migrations at head, zero rows
    f2_dsn (below)                the same clone with F2 loaded on top — tests/core/test_search.py's
                                   own f2() pattern, repeated here rather than imported across a
                                   suite boundary the harness does not otherwise cross
    server (below)                a live `python -m verticals.api.app` subprocess pointed at
                                   f2_dsn, owner t1, bound to a free loopback port
    client (below)                an httpx.Client against that subprocess, bearer token preset

S-45 (docs/E2E.md: "owns its server... excluded from worker parallelism... never touches the
shared cluster") deliberately does not use any fixture here — it builds its own private Postgres
cluster from scratch in its own test file, which is the whole point of it.
"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

import httpx
import psycopg
import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
F2_SQL = Path(__file__).resolve().parents[1] / "fixtures" / "f2_synth.sql"

# Test-only. Never the placeholder `config.py` refuses to boot on, never a value that means
# anything outside this suite's own throwaway subprocesses.
TEST_TOKEN = "http-suite-test-token-not-a-real-deployment"
TEST_OWNER = "t1"  # F2's primary owner (E2E.md §2); t2 lives in the same fixture, for S-41

# Stamped onto every connection the server-under-test's pool opens (via `PGAPPNAME` in the server
# subprocess env), so S-46 can identify the pool's own connections *positively* instead of by
# subtracting the one intruder it happened to think of. Not a DSN parameter: appending
# `application_name=` to the DSN would collide with `_ConnectionSampler`'s own appended copy, and
# duplicate keys in a libpq URI are resolved last-one-wins — a rule this suite should not be
# betting a verdict on.
SERVER_APP_NAME = "verticals_api_under_test"


def _free_port() -> int:
    """Ask the OS for an ephemeral port, release it immediately, and let uvicorn bind it a
    moment later. A TOCTOU race against something else grabbing the same port in between is
    possible in principle and has not fired in any manual run of this fixture; `server` below
    surfaces it as a fast, clearly-labelled failure (the child exits immediately) rather than a
    10s hang, which is the cheap mitigation this risk actually calls for."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def f2_dsn(db_dsn: str) -> str:
    """`db_dsn` (tests/conftest.py) with F2 loaded on top, `ANALYZE`d for stable query plans —
    identical reasoning to tests/core/test_search.py's own f2(), duplicated rather than shared
    because the two suites do not import each other's conftest."""
    conn = psycopg.connect(db_dsn, autocommit=True)
    try:
        conn.execute(F2_SQL.read_text())
        conn.execute("ANALYZE goals")
    finally:
        conn.close()
    return db_dsn


@dataclass(frozen=True)
class Server:
    base_url: str
    token: str
    dsn: str
    log_path: Path


def _wait_healthy(base_url: str, proc: subprocess.Popen, log_path: Path, timeout: float = 10.0) -> None:
    """S-31's own steps: poll `/healthz` until 200, max 10s. A process that has already exited
    is a clearer failure than a client timeout thirty seconds later, so `poll()` is checked on
    every loop turn, not just at the end."""
    deadline = time.monotonic() + timeout
    last_exc: Exception | None = None
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            tail = log_path.read_text()[-2000:] if log_path.exists() else "(no log)"
            raise RuntimeError(f"server exited early (code {proc.returncode}); tail of log:\n{tail}")
        try:
            if httpx.get(f"{base_url}/healthz", timeout=1.0).status_code == 200:
                return
        except httpx.HTTPError as exc:
            last_exc = exc
        time.sleep(0.1)
    raise TimeoutError(f"/healthz never returned 200 within {timeout}s (last error: {last_exc})")


def _shutdown(proc: subprocess.Popen, port: int) -> None:
    """E2E.md §4's own teardown for every scenario in this suite: SIGTERM, wait up to 5s,
    SIGKILL if still alive, then assert the port was actually released — a scenario that leaves
    a listening socket behind fails even if its own asserts passed."""
    if proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=5.0)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5.0)
    time.sleep(0.1)
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        released = s.connect_ex(("127.0.0.1", port)) != 0
    assert released, f"port {port} still accepting connections after teardown"


@pytest.fixture
def server_factory(f2_dsn: str, tmp_path: Path):
    """A factory, not a single server: S-134's cross-owner row needs a *second* process against
    the same F2 database, configured with `VERTICALS_OWNER=t2` — the API takes its owner from
    config, never from the request (`routes_board.py`'s own docstring), so there is no way to
    ask one running server to answer as a different owner. Returns a context manager factory;
    `server` below is just `server_factory()` under the hood, so the two can never drift apart.

    Each call is a real `python -m verticals.api.app` subprocess: F2-loaded database, a free
    loopback port. `cwd=REPO_ROOT` (not a `sys.path` hack) is what lets `-m` resolve the
    `verticals` package with no editable install — the same invocation, from this same directory,
    was proven interactively before this fixture was written: it boots clean against a migrated
    clone and refuses clean against an unmigrated one (`api/app.py`'s own boot-refusal path).
    stdout/stderr go to a file, not a `PIPE` — 500 concurrent requests (S-46) can write enough
    log output to deadlock an unread pipe, and a file survives the process for `_wait_healthy`'s
    own diagnostics either way."""
    counter = 0

    @contextmanager
    def _make(owner: str = TEST_OWNER) -> Iterator[Server]:
        nonlocal counter
        counter += 1
        port = _free_port()
        log_path = tmp_path / f"server-{counter}.log"
        env = dict(os.environ)
        env.update(
            VERTICALS_DATABASE_URL=f2_dsn,
            VERTICALS_TOKEN=TEST_TOKEN,
            VERTICALS_OWNER=owner,
            VERTICALS_BIND=f"127.0.0.1:{port}",
            VERTICALS_POOL_MIN="2",
            VERTICALS_POOL_MAX="10",
            VERTICALS_LOG_LEVEL="warning",
            # libpq reads PGAPPNAME, so every connection this server's pool opens is stamped with
            # a name no other client on the cluster uses. S-46 samples `pg_stat_activity` to prove
            # the pool never exceeds `pool_max`, and it needs to count *the pool*, not "backends on
            # this database": those are different sets, and the difference is a false FAIL. See
            # SERVER_APP_NAME below.
            PGAPPNAME=SERVER_APP_NAME,
        )
        with open(log_path, "w") as logfile:
            proc = subprocess.Popen(
                [sys.executable, "-m", "verticals.api.app"],
                cwd=REPO_ROOT,
                env=env,
                stdout=logfile,
                stderr=subprocess.STDOUT,
                start_new_session=True,  # its own process group; a signal meant for pytest
            )                            # must never reach this child by accident under -n auto
            base_url = f"http://127.0.0.1:{port}"
            try:
                _wait_healthy(base_url, proc, log_path)
                yield Server(base_url=base_url, token=TEST_TOKEN, dsn=f2_dsn, log_path=log_path)
            finally:
                _shutdown(proc, port)

    return _make


@pytest.fixture
def server(server_factory) -> Iterator[Server]:
    """The common case: one server, owner t1. See `server_factory` for the cross-owner case."""
    with server_factory(TEST_OWNER) as s:
        yield s


@pytest.fixture
def client(server: Server) -> Iterator[httpx.Client]:
    """Pre-authed: the common case is a valid bearer token on every request. The one scenario
    that manipulates the header itself (S-32) builds its own request from `server.base_url` /
    `server.token` rather than fighting this fixture's default."""
    #
    # 30 s, not 10 (D93). This is a TRANSPORT budget, never an assertion — no scenario here claims
    # anything about latency (S-14 owns timing, with its own client). S-112 runs the entire `tests/
    # http` suite a second time INSIDE the first to watch the process's sockets, so every other
    # http scenario can be executing under roughly double load, and S-128's 1.5 MB body POST hit
    # `httpx.ReadTimeout` at 10 s in a full run while passing in 1.7 s on its own. A transport
    # budget that fails under the load the suite creates for itself reports the box, not the app.
    with httpx.Client(
        base_url=server.base_url,
        headers={"Authorization": f"Bearer {server.token}"},
        timeout=30.0,
    ) as c:
        yield c
