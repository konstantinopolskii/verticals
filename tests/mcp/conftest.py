"""Shared fixtures and helpers for suite C (`mcp`, `docs/E2E.md` §5) — a real `mcp` Python SDK
client against a real `python -m verticals.mcp.server` subprocess, real Postgres, no mocks.

Layering, most specific last:

    db_dsn (tests/conftest.py)   a fresh F0 clone: migrations at head, zero rows
    f2_dsn (below)                the same clone with F2 loaded on top — tests/http/conftest.py's
                                   own f2_dsn() pattern, duplicated rather than imported across a
                                   suite boundary neither suite otherwise crosses (the same house
                                   convention `verticals/mcp/server.py` itself follows against
                                   `verticals/api/app.py`: small boot/lifecycle code is mirrored
                                   per suite, never shared)
    open_mcp_stdio (below)        an async contextmanager: a live stdio subprocess, a real
                                   `mcp.ClientSession` already initialized, and byte-exact access
                                   to the same stdout/stderr the session consumed
    mcp_http_server (below)       the streamable-http twin (S-60): a live `--transport http`
                                   subprocess on a free loopback port
    api_server_factory (below)    a live `python -m verticals.api.app` subprocess — only the
                                   cross-transport scenarios (S-57, S-58, S-59) need this; nothing
                                   else in this suite ever touches HTTP at all

**Capturing stdout without owning the subprocess.** `mcp.client.stdio.stdio_client` spawns and
owns the child process internally and never yields it, so there is no hook to tee its stdout by
hand. Proven live before being wired in here (no other suite in this repo needed the trick, so
there was no precedent to copy): point `StdioServerParameters` at `/bin/sh -c '<server> | tee
<path>'` instead of at the interpreter directly. `tee` passes every byte through unchanged on its
own stdout — which is what `stdio_client` actually reads, so the real protocol stream the SDK
parses is untouched — while also writing the identical bytes to `<path>` for this suite's own
byte-exact stream-rule assertions. `stdio_client`'s own `errlog=` parameter (a real, documented
argument, not a workaround) captures stderr the ordinary way: `sh`/`tee` write nothing there in
the success case, so what lands is exactly the server's own structured log lines. Shutdown is
`stdio_client`'s own (SIGTERM the process group, `start_new_session=True` puts `sh`, the server
and `tee` in one group together, escalate to SIGKILL) — verified live to leave no orphaned `tee`
or server process behind.
"""

from __future__ import annotations

import json
import os
import shlex
import socket
import subprocess
import sys
import time
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager, contextmanager
from dataclasses import dataclass
from pathlib import Path

import httpx2
import psycopg
import pytest
from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, get_default_environment, stdio_client
from mcp.client.streamable_http import streamable_http_client

REPO_ROOT = Path(__file__).resolve().parents[2]
F2_SQL = Path(__file__).resolve().parents[1] / "fixtures" / "f2_synth.sql"

# Test-only, never a placeholder `config.py` refuses to boot on and never a value that means
# anything outside this suite's own throwaway subprocesses (same convention as
# tests/http/conftest.py's TEST_TOKEN).
TEST_TOKEN = "mcp-suite-test-token-not-a-real-deployment"
TEST_OWNER = "t1"  # F2's primary owner (E2E.md §2); t2 lives in the same fixture, for S-133 step 3
TEST_OWNER_OTHER = "t2"


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


# --- execute-counter mechanism (S-48, S-133; docs/PENDING_DOC_FIXES.md row 53) ------------------

TXN_CONTROL_STATEMENTS = {"BEGIN", "COMMIT", "ROLLBACK"}


def full_table_digest(dsn: str) -> str:
    """Byte-for-byte `tests/core/test_tree.py::_digest`'s own SQL, opened on a plain connection
    rather than a fixture-managed one (every refusal test in this suite wants a before/after pair
    bracketing a whole live MCP session, not just one connection's view). A full-table
    fingerprint, order-independent: if a refused call wrote anything at all, anywhere, this
    changes — the strongest form of "the database digest is byte-identical after every refusal"
    (S-130, S-54)."""
    with psycopg.connect(dsn, autocommit=True) as conn:
        (value,) = conn.execute("SELECT md5(string_agg(goals::text, '|' ORDER BY id)) FROM goals").fetchone()
        return value


def business_statement_count(log: list[tuple[str, int]]) -> int:
    """`tests/harness/stmt.py::count()` sums *every* distinct statement text `pg_stat_statements`
    saw, and on this suite that includes `BEGIN`/`COMMIT`: `server.py`'s `_on_call_tool` acquires
    its connection through `pool.connection()`, which wraps each call in an explicit transaction
    (`server.py`'s own comment there: "matching `api/deps.py::get_conn`'s identical reasoning on
    the HTTP side"). The HTTP-side mechanism this project otherwise means by "execute counter"
    (`api/deps.py::CountingCursor`) never sees those two statements — it only bumps from
    `Cursor.execute()`/`executemany()`, and `conn.commit()`/`conn.rollback()` do not go through a
    cursor. Verified empirically before this helper was written: one MCP `board()` call produces
    exactly `{BEGIN: 1, COMMIT: 1, <the real SELECT>: 1}` in the raw log — three rows, not one —
    for a tool whose own `core/` implementation (`core/board.py`, IR-07) executes a single
    statement.

    Filtering the two transaction-control texts out of the raw log is what makes a
    `pg_stat_statements`-based count comparable to what "execute counter" means everywhere else
    in this project — the same move `tests/core/test_tree.py` already makes for its own
    text-filtered helpers (`_update_calls`, `_select_for_update_calls`), applied to the one
    filter this suite structurally needs. This is a decision, not a documented fact: neither
    `E2E.md` §1 nor `IMPLEMENTATION.md` IR-06 assigns a counting mechanism to the `mcp` suite at
    all — see docs/PENDING_DOC_FIXES.md row 53."""
    return sum(
        calls
        for text, calls in log
        if text.strip() not in TXN_CONTROL_STATEMENTS
        # Migration 012's change-feed trigger runs `SELECT pg_notify(...)` INSIDE the write
        # statement (plpgsql, same wire round trip — pg_stat_statements only lists it because
        # the test cluster tracks nested statements). It is infrastructure riding an existing
        # statement, never an extra round trip, which is the thing these counts guard.
        and "pg_notify" not in text
    )


@pytest.fixture
def f2_dsn(db_dsn: str) -> str:
    """`db_dsn` (tests/conftest.py) with F2 loaded on top, `ANALYZE`d for stable query plans —
    identical reasoning to tests/http/conftest.py's own f2_dsn()."""
    conn = psycopg.connect(db_dsn, autocommit=True)
    try:
        conn.execute(F2_SQL.read_text())
        conn.execute("ANALYZE goals")
    finally:
        conn.close()
    return db_dsn


# --- stdio transport -----------------------------------------------------------------------


def _mcp_env(f2_dsn: str, *, owner: str, token: str, extra: dict[str, str] | None = None) -> dict[str, str]:
    """The SDK's own safe-subset base (`get_default_environment()`: HOME/LOGNAME/PATH/SHELL/
    TERM/USER on POSIX), never the full parent shell — proves the server boots from exactly the
    variables it is actually given rather than whatever happens to be in the developer's own
    environment, and matches `StdioServerParameters.env`'s own documented "merged over
    get_default_environment()" contract."""
    env = get_default_environment() | {
        "VERTICALS_DATABASE_URL": f2_dsn,
        "VERTICALS_TOKEN": token,
        "VERTICALS_OWNER": owner,
        "VERTICALS_LOG_LEVEL": "info",
        "VERTICALS_POOL_MIN": "2",
        "VERTICALS_POOL_MAX": "10",
    }
    if extra:
        env |= extra
    return env


@dataclass(frozen=True)
class StdioStreams:
    """Byte-exact access to one session's stdout/stderr, for the mcp-suite teardown contract
    (`docs/E2E.md` §5, "The stream rule, corrected")."""

    stdout_path: Path
    stderr_path: Path

    def assert_hygiene(self, *, token: str | None) -> None:
        """stdout is nothing but complete JSON-RPC frames with zero trailing bytes; stderr
        carries at least one structured (`level=...`) line; the bearer token, if one is
        configured, appears in neither — the suite intro's own three clauses, in order."""
        raw = self.stdout_path.read_bytes()
        lines = raw.split(b"\n")
        trailing = lines.pop()
        assert trailing == b"", f"stdout has trailing bytes after the last newline: {trailing!r}"
        bad: list[tuple[bytes, str]] = []
        for ln in lines:
            if not ln:
                continue
            try:
                obj = json.loads(ln)
            except json.JSONDecodeError as exc:
                bad.append((ln[:120], str(exc)))
                continue
            if obj.get("jsonrpc") != "2.0":
                bad.append((ln[:120], "decoded but missing/wrong 'jsonrpc' member"))
        assert not bad, f"stdout carried something other than framed JSON-RPC: {bad}"

        stderr_text = self.stderr_path.read_text()
        assert stderr_text.strip(), "stderr must carry at least one structured log line (AC-139)"
        assert "level=" in stderr_text, f"stderr has content but no structured level= field: {stderr_text!r}"

        if token:
            assert token not in raw.decode("utf-8", "replace"), "bearer token leaked onto stdout"
            assert token not in stderr_text, "bearer token leaked onto stderr"


@asynccontextmanager
async def open_mcp_stdio(
    f2_dsn: str,
    tmp_path: Path,
    *,
    owner: str = TEST_OWNER,
    token: str = TEST_TOKEN,
    extra_env: dict[str, str] | None = None,
    label: str = "run",
    server_args: tuple[str, ...] = (),
) -> AsyncIterator[tuple[ClientSession, StdioStreams]]:
    """A real, already-`initialize()`d `ClientSession` against a real
    `python -m verticals.mcp.server` subprocess, plus byte-exact stdout/stderr capture (module
    docstring). `server_args` exists for exactly one caller — the stream-hygiene suite's stray-
    print plant, which needs to run a *different* command line than the shipped entrypoint
    without ever touching shipped source (`-c` inline script instead of `-m verticals.mcp.server`);
    every other caller leaves it empty.
    """
    stdout_path = tmp_path / f"{label}.stdout.raw"
    stderr_path = tmp_path / f"{label}.stderr.log"
    env = _mcp_env(f2_dsn, owner=owner, token=token, extra=extra_env)
    inner = " ".join([shlex.quote(sys.executable), *[shlex.quote(a) for a in (server_args or ("-m", "verticals.mcp.server"))]])
    shell_cmd = f"exec {inner} | tee {shlex.quote(str(stdout_path))}"
    params = StdioServerParameters(command="/bin/sh", args=["-c", shell_cmd], env=env, cwd=str(REPO_ROOT))
    with open(stderr_path, "w") as errlog:
        async with stdio_client(params, errlog=errlog) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                yield session, StdioStreams(stdout_path=stdout_path, stderr_path=stderr_path)


# --- streamable-http transport (S-60) -------------------------------------------------------


@dataclass(frozen=True)
class McpHttpServer:
    url: str  # includes the /mcp path
    token: str
    log_path: Path


def _wait_tcp(host: str, port: int, proc: subprocess.Popen, log_path: Path, timeout: float = 10.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            tail = log_path.read_text()[-2000:] if log_path.exists() else "(no log)"
            raise RuntimeError(f"server exited early (code {proc.returncode}); tail of log:\n{tail}")
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.2)
            if s.connect_ex((host, port)) == 0:
                return
        time.sleep(0.1)
    raise TimeoutError(f"nothing listening on {host}:{port} within {timeout}s")


def _terminate(proc: subprocess.Popen, port: int) -> None:
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


@contextmanager
def mcp_http_subprocess(
    f2_dsn: str, tmp_path: Path, *, owner: str = TEST_OWNER, token: str = TEST_TOKEN
) -> Iterator[McpHttpServer]:
    """A real `python -m verticals.mcp.server --transport http` subprocess. Full parent
    environment plus overrides (`dict(os.environ) | ...`), matching `tests/http/conftest.py`'s
    own `server_factory` — unlike `open_mcp_stdio` above, this does not go through the MCP SDK's
    own `StdioServerParameters.env` convention at all (there is no stdio session here), so that
    convention's safe-subset default does not apply; this is a plain `subprocess.Popen`, spawned
    the same way the http suite spawns `verticals.api.app`."""
    port = _free_port()
    log_path = tmp_path / "mcp-http-server.log"
    env = dict(os.environ)
    env.update(
        VERTICALS_DATABASE_URL=f2_dsn,
        VERTICALS_TOKEN=token,
        VERTICALS_OWNER=owner,
        VERTICALS_MCP_BIND=f"127.0.0.1:{port}",
        VERTICALS_POOL_MIN="2",
        VERTICALS_POOL_MAX="10",
        VERTICALS_LOG_LEVEL="info",
    )
    with open(log_path, "w") as logfile:
        proc = subprocess.Popen(
            [sys.executable, "-m", "verticals.mcp.server", "--transport", "http"],
            cwd=REPO_ROOT,
            env=env,
            stdout=logfile,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        try:
            _wait_tcp("127.0.0.1", port, proc, log_path)
            yield McpHttpServer(url=f"http://127.0.0.1:{port}/mcp", token=token, log_path=log_path)
        finally:
            _terminate(proc, port)


@asynccontextmanager
async def open_mcp_http_session(server: McpHttpServer) -> AsyncIterator[ClientSession]:
    """A real, already-`initialize()`d `ClientSession` over streamable-http, bearer-authed —
    `httpx2` (not plain `httpx`) because that is the concrete client type
    `mcp.client.streamable_http.streamable_http_client`'s own `http_client=` parameter is typed
    against (verified by reading that module's imports directly rather than assuming httpx and
    httpx2 share a client type by name alone).

    Yields a 2-tuple, not 3 — corrected against the installed `mcp==2.0.0` source
    (`streamable_http_client`'s own docstring there: "Tuple containing: read_stream,
    write_stream"), not against a remembered older SDK shape that also returned a
    `get_session_id` callable. Caught live: the first real exercise of this function (S-60)
    failed every call with `ValueError: not enough values to unpack (expected 3, got 2)` before
    this was fixed."""
    client = httpx2.AsyncClient(headers={"Authorization": f"Bearer {server.token}"}, timeout=10.0)
    async with client:
        async with streamable_http_client(server.url, http_client=client) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                yield session


# --- the HTTP api, for the three genuinely cross-transport scenarios (S-57, S-58, S-59) --------


@dataclass(frozen=True)
class ApiServer:
    base_url: str
    token: str
    dsn: str
    log_path: Path


def _wait_healthy(base_url: str, proc: subprocess.Popen, log_path: Path, timeout: float = 10.0) -> None:
    """Byte-for-byte `tests/http/conftest.py::_wait_healthy` — duplicated, not imported (module
    docstring). Needs `httpx2` here too: this file does not otherwise depend on plain `httpx`,
    and pulling in a second HTTP client library for one polling loop would be exactly the kind
    of unnecessary dependency this project's own engineering rules refuse."""
    deadline = time.monotonic() + timeout
    last_exc: Exception | None = None
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            tail = log_path.read_text()[-2000:] if log_path.exists() else "(no log)"
            raise RuntimeError(f"server exited early (code {proc.returncode}); tail of log:\n{tail}")
        try:
            with httpx2.Client(timeout=1.0) as probe:
                if probe.get(f"{base_url}/healthz").status_code == 200:
                    return
        except httpx2.HTTPError as exc:
            last_exc = exc
        time.sleep(0.1)
    raise TimeoutError(f"/healthz never returned 200 within {timeout}s (last error: {last_exc})")


@contextmanager
def api_server(f2_dsn: str, tmp_path: Path, *, owner: str = TEST_OWNER, token: str = TEST_TOKEN) -> Iterator[ApiServer]:
    """A real `python -m verticals.api.app` subprocess, for the scenarios that are genuinely about
    two transports sharing one core (S-57, S-58, S-59) — `verticals/api/**` is WP-15's own
    territory (read-only reference for this work package: run its shipped entrypoint unmodified,
    never edit its source), matching exactly how `tests/http/conftest.py`'s own `server_factory`
    already runs it."""
    port = _free_port()
    log_path = tmp_path / "api-server.log"
    env = dict(os.environ)
    env.update(
        VERTICALS_DATABASE_URL=f2_dsn,
        VERTICALS_TOKEN=token,
        VERTICALS_OWNER=owner,
        VERTICALS_BIND=f"127.0.0.1:{port}",
        VERTICALS_POOL_MIN="2",
        VERTICALS_POOL_MAX="10",
        VERTICALS_LOG_LEVEL="warning",
    )
    with open(log_path, "w") as logfile:
        proc = subprocess.Popen(
            [sys.executable, "-m", "verticals.api.app"],
            cwd=REPO_ROOT,
            env=env,
            stdout=logfile,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        base_url = f"http://127.0.0.1:{port}"
        try:
            _wait_healthy(base_url, proc, log_path)
            yield ApiServer(base_url=base_url, token=token, dsn=f2_dsn, log_path=log_path)
        finally:
            _terminate(proc, port)
