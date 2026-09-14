"""S-45 — the API survives losing its database. docs/E2E.md §4, and its setup recipe in §2's
"Scenarios that own the server, and the serialized tail".

Owns its server *and* its own Postgres cluster, built from scratch in this file alone — no
fixture from `conftest.py` (see that file's own docstring: "S-45 ... deliberately does not use
any fixture here"). Never touches the shared F2 cluster on :55432, never the CI container:
`pg_ctl stop` on a shared cluster destroys every concurrent worker's database, and inside
`postgres:16-alpine` the harness has neither the `initdb`/`pg_ctl` binaries nor the permission to
run them (E2E.md's own reasoning for why these three scenarios exist at all).

**Two fixes to E2E.md §2's literal setup recipe, found by running it, not by inspection.**

1. `initdb -D $TMP/pg<id>` then `pg_ctl -D $TMP/pg<id> -o "-p 0 -k $TMP" start` — `-p 0` is not a
   valid Postgres port. Verified against the installed Postgres 16.13: the server refuses to
   start at all, `FATAL: 0 is outside the valid range for parameter "port" (1 .. 65535)`. Fixed
   here the same way `tests/http/conftest.py::_free_port` picks uvicorn's own port: bind to port
   0, read back what the OS actually assigned, close, hand that concrete number to `-p`. `-h ''`
   (empty `listen_addresses`, not in the literal recipe) is what actually delivers "a unix socket
   nobody else knows about" rather than merely an obscure port number — confirmed with `lsof
   -p <pid> -iTCP` against the running postmaster: zero TCP file descriptors, one unix-socket fd.

2. `$TMP` in the recipe reads as pytest's own `tmp_path` fixture, and that is unusable for the
   *socket directory* specifically, independent of fix 1: a realistic scenario-test path under
   this project's `tmp_path` (measured directly: `.../pytest-of-<user>/pytest-<n>/<test name><m>`)
   comes to 148 bytes once `/pg45/.s.PGSQL.<port>` is appended, and Postgres refuses any
   unix-socket path over 103 bytes on macOS (108 on Linux) — confirmed by running it: `could not
   create any Unix-domain sockets ... path "..." is too long (maximum 103 bytes)`. `PGDATA`
   itself carries no such limit (an ordinary directory, not a socket path) and stays under
   pytest's own `tmp_path`; only `unix_socket_directories` moves to a short-prefixed
   `tempfile.mkdtemp()` under the system temp root — measured at 79 bytes end-to-end in the
   confirming run, comfortably under the ceiling.

Both are reported in this WP's result rather than silently patched around — the recipe lives in
E2E.md §2, a file this package does not own.

**`--auth=trust`, deliberately, unlike the shared cluster's real password
(`docker-compose.test.yml`'s `POSTGRES_PASSWORD`).** This cluster never opens a TCP port at all
(fix 1 above); the only path to it is the unix socket, inside a `tempfile.mkdtemp()` directory,
mode `0700` by construction — reachable by this OS user alone. A password would protect nothing
a filesystem permission does not already protect, and manufacturing and rotating one for a
cluster that is `initdb`'d and dropped inside the same test would be ceremony, not defense.
"""

from __future__ import annotations

import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx
import pytest

from tests.harness.report import gate

REPO_ROOT = Path(__file__).resolve().parents[2]
TEST_TOKEN = "s45-availability-test-token-not-a-real-deployment"
TEST_OWNER = "t1"
REQUIRED_PG_MAJOR = "16"  # docker-compose.test.yml pins postgres:16-alpine; match it here too.


def _require_pg_binaries() -> tuple[str, str, str]:
    """`initdb`/`pg_ctl`/`pg_isready` resolved off `PATH`, not a hard-coded Homebrew prefix —
    this scenario runs wherever a developer's or CI runner's local Postgres 16 happens to live,
    not only on this machine's Apple Silicon Homebrew layout. A missing binary or a present-but-
    wrong-major-version one is an environment precondition this scenario cannot satisfy, not a
    product defect — GATE with a specific, actionable reason, never `pytest.skip`
    (`tests/harness/report.py`'s own rule: a skip is always a FAIL under AC-089's `skip == 0`;
    an earlier version of this function used `pytest.skip` here, which would have silently
    flipped the whole `http` suite to FAIL on exactly the documented CI path — `docs/E2E.md` §2
    says the CI container has neither the `initdb`/`pg_ctl` binaries nor the permission to run
    them — caught by wp-s126 while building S-126, fixed here)."""
    initdb = shutil.which("initdb")
    pg_ctl = shutil.which("pg_ctl")
    pg_isready = shutil.which("pg_isready")
    if not (initdb and pg_ctl and pg_isready):
        missing = [
            name
            for name, path in (("initdb", initdb), ("pg_ctl", pg_ctl), ("pg_isready", pg_isready))
            if not path
        ]
        gate(
            f"S-45 needs a local Postgres {REQUIRED_PG_MAJOR} install on PATH "
            f"(missing: {', '.join(missing)}) — it owns a private cluster and cannot use the "
            f"shared CI container (postgres:16-alpine has neither the binary nor the permission)"
        )
    # "pg_ctl (PostgreSQL) 16.13" on Homebrew, "pg_ctl (PostgreSQL) 16.4 (Debian ...)" elsewhere
    # — the closing paren sits between the product name and the version number, so a fixed
    # substring check for "PostgreSQL 16." never matches on any real install (confirmed the hard
    # way: an earlier version of this check skipped every correct, present Postgres 16). Anchored
    # on "PostgreSQL" instead, tolerating an optional ")" and whitespace before the version.
    version_out = subprocess.run([pg_ctl, "--version"], capture_output=True, text=True).stdout
    match = re.search(r"PostgreSQL\)?\s+(\d+)\.", version_out)
    major = match.group(1) if match else None
    if major != REQUIRED_PG_MAJOR:
        gate(
            f"S-45 needs Postgres {REQUIRED_PG_MAJOR} on PATH to match docker-compose.test.yml's "
            f"own pin; found {version_out.strip() or '(unreadable version string)'}"
        )
    return initdb, pg_ctl, pg_isready


def _free_port() -> int:
    """Same TOCTOU-tolerant technique as `conftest.py::_free_port`, duplicated rather than
    imported — this file owns its whole stack independently, on purpose (module docstring)."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _run(args: list[str], **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run(args, capture_output=True, text=True, **kwargs)


def test_s45_the_api_survives_losing_its_database(tmp_path: Path) -> None:
    initdb, pg_ctl, pg_isready = _require_pg_binaries()

    pgdata = tmp_path / "pg45"
    pg_log = tmp_path / "pg45.log"
    api_log = tmp_path / "api45.log"
    # Not tmp_path (see module docstring, fix 2) — a short-prefixed dir under the system temp
    # root, mode 0700 by construction (tempfile.mkdtemp's own default).
    sock_dir = Path(tempfile.mkdtemp(prefix="hzpg45-"))
    pg_port = _free_port()
    api_port = _free_port()
    api_base_url = f"http://127.0.0.1:{api_port}"
    pg_dsn = f"postgresql://s45@/postgres?host={sock_dir}&port={pg_port}"

    api_proc: subprocess.Popen | None = None
    pg_started = False

    def _stop_pg(timeout: float = 30.0) -> subprocess.CompletedProcess:
        return _run([pg_ctl, "-D", str(pgdata), "-m", "fast", "-t", str(int(timeout)), "-w", "stop"])

    def _pg_pid() -> str:
        return _run(["pgrep", "-f", str(pgdata)]).stdout.strip()

    try:
        # --- build the private cluster --------------------------------------------------------
        r = _run([initdb, "-D", str(pgdata), "--auth=trust", "-U", "s45"])
        assert r.returncode == 0, f"initdb failed:\n{r.stdout}\n{r.stderr}"

        r = _run(
            [
                pg_ctl, "-D", str(pgdata),
                "-o", f"-p {pg_port} -k {sock_dir} -h ''",
                "-l", str(pg_log),
                "-w", "start",
            ]
        )
        assert r.returncode == 0, f"pg_ctl start failed:\n{r.stdout}\n{r.stderr}\nlog:\n{pg_log.read_text()}"
        pg_started = True

        migrate_env = dict(os.environ)
        migrate_env["VERTICALS_DATABASE_URL"] = pg_dsn
        r = _run(
            [sys.executable, "-m", "verticals.db.runner", "up"],
            cwd=REPO_ROOT,
            env=migrate_env,
        )
        assert r.returncode == 0, f"migration runner failed:\n{r.stdout}\n{r.stderr}"

        # --- boot the real API against this private cluster -----------------------------------
        # Full parent environment, not a hand-picked subset (tests/http/conftest.py's own
        # server_factory does the same) — verified against a minimal PATH-only environment
        # first and kept only the tested form; the app needs nothing beyond the VERTICALS_* keys
        # below, but there is no reason to diverge from the suite's own proven convention here.
        env = dict(os.environ)
        env.update(
            VERTICALS_DATABASE_URL=pg_dsn,
            VERTICALS_TOKEN=TEST_TOKEN,
            VERTICALS_OWNER=TEST_OWNER,
            VERTICALS_BIND=f"127.0.0.1:{api_port}",
            VERTICALS_POOL_MIN="2",
            VERTICALS_POOL_MAX="10",
            VERTICALS_LOG_LEVEL="warning",
        )
        with open(api_log, "w") as logfile:
            api_proc = subprocess.Popen(
                [sys.executable, "-m", "verticals.api.app"],
                cwd=REPO_ROOT,
                env=env,
                stdout=logfile,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
        deadline = time.monotonic() + 10.0
        healthy = False
        while time.monotonic() < deadline:
            if api_proc.poll() is not None:
                pytest.fail(
                    f"API exited early (code {api_proc.returncode}); log:\n"
                    f"{api_log.read_text()[-2000:]}"
                )
            try:
                if httpx.get(f"{api_base_url}/healthz", timeout=1.0).status_code == 200:
                    healthy = True
                    break
            except httpx.HTTPError:
                pass
            time.sleep(0.1)
        assert healthy, "API never became healthy against the private cluster"

        client = httpx.Client(
            base_url=api_base_url,
            headers={"Authorization": f"Bearer {TEST_TOKEN}"},
            timeout=10.0,
        )

        # --- Step 1: GET /api/board -> 200, database up ---------------------------------------
        step1 = client.get("/api/board", params={"date": "2026-08-08"})
        assert step1.status_code == 200

        # --- Step 2: pg_ctl stop -m fast -------------------------------------------------------
        stop_result = _stop_pg()
        assert stop_result.returncode == 0, f"pg_ctl stop failed:\n{stop_result.stdout}\n{stop_result.stderr}"
        pg_started = False

        # --- Step 3: GET /api/board -> 503 within 5s, database_unavailable, no traceback, no hang
        t0 = time.monotonic()
        step3 = client.get("/api/board", params={"date": "2026-08-08"})
        elapsed = time.monotonic() - t0
        assert elapsed < 5.0, f"step 3 took {elapsed:.2f}s, over the 5s ceiling"
        assert step3.status_code == 503
        assert step3.json() == {"error": "database_unavailable"}
        assert "Traceback" not in step3.text and "traceback" not in step3.text.lower()

        # uvicorn itself must still be alive — the database dying must not take the process down.
        assert api_proc.poll() is None, "API process exited when the database went away"

        # /healthz during the outage: 503, db: down (api/app.py's own OperationalError/PoolTimeout
        # branch, distinct from its UndefinedTable/"not_migrated" branch — this is a live database
        # that vanished, not one that was never migrated).
        healthz_down = client.get("/healthz")
        assert healthz_down.status_code == 503
        assert healthz_down.json()["db"] == "down"
        assert "Traceback" not in healthz_down.text

        log_text = api_log.read_text()
        assert "Traceback" not in log_text, f"a traceback reached the API's own log:\n{log_text[-2000:]}"

        # --- Step 4: pg_ctl start, wait for pg_isready -----------------------------------------
        r = _run(
            [
                pg_ctl, "-D", str(pgdata),
                "-o", f"-p {pg_port} -k {sock_dir} -h ''",
                "-l", str(pg_log),
                "-w", "start",
            ]
        )
        assert r.returncode == 0, f"pg_ctl restart failed:\n{r.stdout}\n{r.stderr}"
        pg_started = True

        ready_deadline = time.monotonic() + 10.0
        ready = False
        while time.monotonic() < ready_deadline:
            if _run([pg_isready, "-h", str(sock_dir), "-p", str(pg_port)]).returncode == 0:
                ready = True
                break
            time.sleep(0.1)
        assert ready, "pg_isready never reported ready after restart"

        # --- Step 5: GET /api/board -> 200, no API restart -------------------------------------
        step5 = client.get("/api/board", params={"date": "2026-08-08"})
        assert step5.status_code == 200
        # Same OS process throughout steps 1, 3 and 5 — "the pool reconnects," not "a fresh pool
        # after a fresh boot." api_proc was never terminated or replaced at any point above.
        assert api_proc.poll() is None, "API process was not the same one throughout"

        client.close()

    finally:
        # --- teardown: stop the API, stop the cluster, remove its data, assert nothing survives
        api_port_released = True
        if api_proc is not None:
            if api_proc.poll() is None:
                api_proc.terminate()
                try:
                    api_proc.wait(timeout=5.0)
                except subprocess.TimeoutExpired:
                    api_proc.kill()
                    api_proc.wait(timeout=5.0)
            time.sleep(0.1)
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(0.5)
                api_port_released = s.connect_ex(("127.0.0.1", api_port)) != 0

        if pg_started:
            _stop_pg()

        pg_pid_survives = bool(_pg_pid())

        shutil.rmtree(pgdata, ignore_errors=True)
        shutil.rmtree(sock_dir, ignore_errors=True)

    assert api_port_released, f"port {api_port} still accepting connections after teardown"
    assert not pg_pid_survives, "a postgres process for this private cluster is still running"
    assert not pgdata.exists(), "the private cluster's data directory was not removed"
