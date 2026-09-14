"""Corpus + server fixtures for suite F (`perf`). WP-20 (`docs/IMPLEMENTATION.md`).

`docs/E2E.md` section 8: "Corpora are built once per run into template databases and dropped at
the end of the run, not between scenarios — building F4-56700 twice would dominate the suite's
own runtime." Every `f4_*` fixture below is session-scoped for exactly that reason: built on
first use (a fresh `f0` clone, bulk-loaded), reused by every scenario in the same `pytest`
process that names it, dropped once when the session ends — `tests/conftest.py`'s own
`fresh_clone` contextmanager, normally auto-closed per test, held open here instead via an
`ExitStack` that lives as long as the session fixture does.

`docs/E2E.md` section 8 also states the suite "runs alone" — `tests/harness/runner.py`'s own
`SERIAL_SUITES` already enforces that at suite-dispatch time (no `-n auto` for `perf`), so
nothing in this file needs its own cross-worker lock.
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Iterator
from contextlib import ExitStack, contextmanager
from datetime import date
from pathlib import Path

import psycopg
import pytest

from tests.conftest import fresh_clone
from tests.fixtures import gen_corpus as G
from tests.harness import calibrate
from tests.harness.report import gate

REPO_ROOT = Path(__file__).resolve().parents[2]
ARTIFACTS_DIR = REPO_ROOT / "artifacts" / "perf"
WEB_DIR = REPO_ROOT / "web"

OWNER = "perf"
SEED = 20260808
ANCHOR = date(2026, 8, 8)  # tests/core/test_board.py's own ANCHOR — the established convention
# Never the shipped placeholder verticals/config.py refuses to boot on — any other non-empty
# string satisfies VERTICALS_TOKEN's contract.
SERVER_TOKEN = "perf-suite-token-not-a-secret"  # noqa: S105 — test fixture, not a real credential

_GOALS_COLUMNS = (
    "id", "owner", "parent_id", "path", "depth", "vertical", "anchor_date", "period_key",
    "title", "body", "color", "tags", "done_at", "position", "origin", "created_at", "updated_at",
    "parked_from_vertical",
)


def dsn(dbname: str) -> str:
    """Same PGHOST/PGPORT/PGUSER/PGPASSWORD convention every other harness file uses
    (`tests/conftest.py`'s own `_env_dsn`) — reimplemented in three lines here rather than
    imported across a file this work package does not own (that name is private there)."""
    host = os.environ.get("PGHOST", "127.0.0.1")
    port = os.environ.get("PGPORT", "55432")
    user = os.environ.get("PGUSER", "verticals")
    password = os.environ.get("PGPASSWORD", "verticals")
    return f"postgresql://{user}:{password}@{host}:{port}/{dbname}"


def _bulk_insert_goals(target_dsn: str, rows: list[dict]) -> None:
    """One `COPY`, not N `INSERT`s — this is the corpus-build step, never inside a scenario's own
    measured window. `ANALYZE` after loading: a plan assertion (or a realistic query plan of any
    kind) against a table the planner has no statistics for proves nothing (the same reasoning
    `tests/core/test_board.py`'s own `f2` fixture states for the same call)."""
    conn = psycopg.connect(target_dsn, autocommit=True)
    try:
        with conn.cursor() as cur, cur.copy(
            f"COPY goals ({', '.join(_GOALS_COLUMNS)}) FROM STDIN"
        ) as copy:
            for row in rows:
                copy.write_row(tuple(row[c] for c in _GOALS_COLUMNS))
        conn.execute("ANALYZE goals")
    finally:
        conn.close()


def _build_corpus_db(stack: ExitStack, n: int) -> str:
    name = stack.enter_context(fresh_clone("f0"))
    _bulk_insert_goals(dsn(name), G.generate_rows(n, SEED, owner=OWNER))
    return name


@pytest.fixture(scope="session")
def _corpus_stack() -> Iterator[ExitStack]:
    with ExitStack() as stack:
        yield stack


@pytest.fixture(scope="session")
def f4_567(_corpus_stack: ExitStack) -> str:
    """F4-567's database name — S-91 (`core.board()`), S-97 (UI paint, same corpus the board's
    own S-91 row uses), and the fallback corpus S-98's own E2E.md row names ("KK export or
    F4-567") — this package uses F4-567 unconditionally, never `seed/`, per the Zone 1 law and
    `docs/E2E.md`'s own "F4-567 is the stand-in for KK's board on any machine that does not hold
    F3"."""
    return _build_corpus_db(_corpus_stack, 567)


@pytest.fixture(scope="session")
def f4_5670(_corpus_stack: ExitStack) -> str:
    """F4-5670's database name — S-92, S-93, S-94, S-96 (S-95 GATEs: no MCP server exists yet)."""
    return _build_corpus_db(_corpus_stack, 5670)


@pytest.fixture(scope="session")
def f4_56700(_corpus_stack: ExitStack) -> str:
    """F4-56700's database name — S-99 alone, the non-gating headroom probe."""
    return _build_corpus_db(_corpus_stack, 56700)


@pytest.fixture(scope="session")
def export_rows_567() -> list[dict]:
    """S-98's corpus: planner-export-JSON-shaped, all `CLASS_AUTHORED`, zero drops on import
    (`tests/fixtures/gen_corpus.py`'s own guarantee — verified live against the real
    `tools/import_planner.py` importer while this package was built). Generated once per
    session; S-98 imports it fresh, into a fresh `f0` clone, on every iteration."""
    return G.generate_export_rows(567, SEED)


# --- server spawn: S-93 (steady state), S-96 (cold start) --------------------------------------


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class ServerBootError(RuntimeError):
    """The server subprocess exited, or never answered `/api/board` inside the timeout. Every
    caller in `test_perf_transport_import.py` converts this to `tests.harness.report.gate()` —
    a boot failure on `verticals/api/**` mid-flight (WP-15) is exactly the documented GATE case,
    never faked as a pass and never a bare pytest error that looks like this package's own bug."""


def spawn_server(target_dsn: str) -> tuple[subprocess.Popen, int]:
    """Starts `python -m verticals.api.app` against `target_dsn` on a fresh loopback port and
    returns immediately, unwaited — the caller decides whether time-to-ready counts towards a
    measurement (S-96) or must happen before one starts (S-93)."""
    port = _free_port()
    env = dict(os.environ)
    env["VERTICALS_DATABASE_URL"] = target_dsn
    env["VERTICALS_TOKEN"] = SERVER_TOKEN
    env["VERTICALS_OWNER"] = OWNER
    env["VERTICALS_BIND"] = f"127.0.0.1:{port}"
    proc = subprocess.Popen(
        [sys.executable, "-m", "verticals.api.app"],
        cwd=str(REPO_ROOT), env=env,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
    )
    return proc, port


def board_url(port: int, on: date = ANCHOR) -> str:
    return f"http://127.0.0.1:{port}/api/board?date={on.isoformat()}"


def poll_until_200(proc: subprocess.Popen, port: int, *, timeout_s: float, on: date = ANCHOR) -> float:
    """Polls `GET /api/board` — never `/healthz`; S-96 measures "first 200 on `/api/board`"
    literally (`docs/E2E.md` section 8) — as fast as the loop allows, timed from the moment this
    function is called. Returns the elapsed seconds to the first 200. Raises `ServerBootError`,
    with the process's own stdout/stderr tail attached, if the process exits first or the timeout
    elapses — exactly the detail a WP-15-mid-flight boot failure needs in a GATE reason to be
    actionable rather than a bare "GATE: timed out"."""
    req = urllib.request.Request(
        board_url(port, on), headers={"Authorization": f"Bearer {SERVER_TOKEN}"}
    )
    start = time.perf_counter()
    while True:
        if proc.poll() is not None:
            tail = proc.stdout.read().decode("utf-8", "replace")[-2000:] if proc.stdout else ""
            raise ServerBootError(
                f"server process exited with code {proc.returncode} before answering 200:\n{tail}"
            )
        try:
            with urllib.request.urlopen(req, timeout=1.0) as resp:
                if resp.status == 200:
                    return time.perf_counter() - start
        except (urllib.error.URLError, ConnectionError, TimeoutError):
            pass
        if time.perf_counter() - start > timeout_s:
            tail = proc.stdout.read1(4096).decode("utf-8", "replace") if proc.stdout else ""
            stop_server(proc)
            raise ServerBootError(f"no 200 from {board_url(port, on)} within {timeout_s}s:\n{tail}")
        time.sleep(0.01)


def stop_server(proc: subprocess.Popen) -> None:
    if proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)


def get_board_http(port: int, on: date = ANCHOR) -> tuple[int, dict]:
    """One `GET /api/board` call, already authenticated — returns `(query_count, response_json)`.
    `X-Query-Count` absence (a route that forgot to set it) surfaces as `int("")` raising, not as
    a silently-passed `0` — a missing header must be loud here, never read as "zero statements"."""
    req = urllib.request.Request(
        board_url(port, on), headers={"Authorization": f"Bearer {SERVER_TOKEN}"}
    )
    with urllib.request.urlopen(req, timeout=10.0) as resp:
        count = int(resp.headers["X-Query-Count"])
        body = json.loads(resp.read())
    return count, body


# --- S-97: production build + static server, mirroring tests/ui/conftest.py's shape -----------
#
# `docs/E2E.md` §1's own suite table describes suite `ui` as "production Vue build served by a
# real static server + real backend + real DB" — S-97's own row in §8 asks for exactly that same
# shape ("UI: navigation start -> last board card painted, production build, localhost"), just at
# F4-567 instead of F2. WP-22's `tests/ui/conftest.py` already built the shape once (`web_dist` +
# `_static_server`: `npm run build`, then `vite preview` with a same-origin `/api`+`/healthz`
# proxy onto a real backend). Duplicated here rather than imported — matching that file's own
# stated house convention for the identical situation (its `_free_port`/`f2_dsn` docstrings:
# "duplicated, not imported ... crossing a suite boundary this harness does not otherwise cross,"
# said there about `tests/http/conftest.py`; this package draws the same line against
# `tests/ui/conftest.py`).


@pytest.fixture(scope="session")
def web_dist_perf() -> None:
    """`npm --prefix web run build`, once per perf session — S-97's own precondition, built the
    same way `tests/ui/conftest.py::web_dist` builds it for suite `ui`, pinned to this package's
    own `SERVER_TOKEN` rather than the `ui` suite's `TEST_TOKEN` so the built bundle's baked-in
    `VITE_VERTICALS_TOKEN` matches what `spawn_server` hands the backend as `VERTICALS_TOKEN` (same
    contract `web/src/lib/api.ts`'s header comment states, cited in full over there).

    Left unguarded — a bare `RuntimeError` on failure, never a `gate()` — matching
    `tests/ui/conftest.py::web_dist`'s own choice: a production build that fails to compile is a
    build failure to fix, not an absent precondition to wait out.
    """
    env = dict(os.environ)
    env["VITE_VERTICALS_TOKEN"] = SERVER_TOKEN
    proc = subprocess.run(
        ["npm", "--prefix", "web", "run", "build"],
        cwd=REPO_ROOT, env=env, capture_output=True, text=True, timeout=180,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"npm run build failed (exit {proc.returncode}):\nstdout:\n{proc.stdout}\n"
            f"stderr:\n{proc.stderr}"
        )
    dist_index = WEB_DIR / "dist" / "index.html"
    if not dist_index.exists():
        raise RuntimeError(f"build reported success but {dist_index} does not exist")


def _wait_until_serving(url: str, proc: subprocess.Popen, log_path: Path, *, timeout_s: float) -> None:
    """`urllib`-based twin of `tests/ui/conftest.py::_wait_http_ok` — this file already avoids
    `httpx` everywhere else (`poll_until_200`, `get_board_http`), so the tool already in use here
    is reused rather than adding a second HTTP client to this package's own dependency footprint.

    Takes `log_path` rather than reading `proc.stdout` directly: the caller redirects the child's
    stdout straight to a log file on disk (`static_server_perf`, below) rather than to `PIPE`, so
    `proc.stdout` is `None` on this `Popen` object — the tail on a boot failure has to come from
    the file, exactly as `_wait_http_ok` reads `log_path.read_text()` rather than `proc.stdout`.

    Raises `ServerBootError` — this module's own class, already the uniform type every caller in
    `test_perf_transport_import.py` converts to `gate()` — never a bare timeout or a client
    exception."""
    deadline = time.monotonic() + timeout_s
    last_exc: Exception | None = None
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            tail = log_path.read_text()[-2000:] if log_path.exists() else "(no log)"
            raise ServerBootError(
                f"process exited (code {proc.returncode}) before serving {url}:\n{tail}"
            )
        try:
            with urllib.request.urlopen(url, timeout=1.0) as resp:
                if resp.status == 200:
                    return
        except (urllib.error.URLError, ConnectionError, TimeoutError) as exc:
            last_exc = exc
        time.sleep(0.05)
    raise ServerBootError(f"{url} never served 200 within {timeout_s}s (last error: {last_exc})")


@contextmanager
def static_server_perf(api_base_url: str, log_dir: Path, *, timeout_s: float = 15.0) -> Iterator[str]:
    """`vite preview` in front of the just-built `web/dist/`, same-origin `/api`+`/healthz` proxy
    onto `api_base_url` (`web/vite.config.ts`'s `preview.proxy`, driven by `VITE_API_PROXY_TARGET`
    — the identical mechanism `tests/ui/conftest.py::_static_server` uses, duplicated per this
    section's own header note). `log_dir` is caller-owned rather than a `tmp_path` fixture threaded
    in here: every scenario in this package spawns and stops its own servers inline inside the
    test function (`spawn_server`'s own callers, all in `test_perf_transport_import.py`), never
    via a fixture, and this context manager follows that same convention.
    """
    port = _free_port()
    log_path = log_dir / "static.log"
    env = dict(os.environ)
    env["VITE_API_PROXY_TARGET"] = api_base_url
    with open(log_path, "w") as logfile:
        proc = subprocess.Popen(
            ["npm", "run", "preview", "--", "--port", str(port), "--strictPort", "--host", "127.0.0.1"],
            cwd=WEB_DIR, env=env, stdout=logfile, stderr=subprocess.STDOUT, start_new_session=True,
        )
        base_url = f"http://127.0.0.1:{port}"
        try:
            _wait_until_serving(f"{base_url}/", proc, log_path, timeout_s=timeout_s)
            yield base_url
        finally:
            stop_server(proc)


# --- shared measurement loop --------------------------------------------------------------------


def time_iterations(fn: Callable[[], object], *, warmups: int, iterations: int) -> list[float]:
    """Runs `fn()` `warmups` times (discarded, cache-warming only) then `iterations` times,
    returning wall-clock milliseconds per timed call. A hard invariant `fn` itself must uphold on
    every measured call belongs inside `fn` (raise, or return a flag the caller checks after each
    call) — this loop only times, per `docs/E2E.md` section 8: "the row's hard invariant holds on
    every iteration, not on a sample," which a loop that only records durations cannot enforce for
    its caller silently."""
    for _ in range(warmups):
        fn()
    samples: list[float] = []
    for _ in range(iterations):
        t0 = time.perf_counter()
        fn()
        samples.append((time.perf_counter() - t0) * 1000.0)
    return samples


def loadavg1() -> float:
    """The 1-minute load average. Its own function because two callers need it for different
    reasons — the precondition gate below decides on it, every artifact records it — and a number
    that decides a verdict should be read the same way in both places."""
    return os.getloadavg()[0]


def gate_unless_quiet(load1: float, cores: int) -> None:
    """Raise `Gated` when `load1` on a `cores`-core box is too loud to measure on; return `None`
    when it is quiet enough.

    Takes its two readings as arguments instead of reading them itself, so both outcomes can be
    exercised with any box's numbers without arranging that box — a precondition check that can
    only be observed on whatever machine happens to be running it is one nobody can prove fires.
    The fixture below supplies the live values; this function is what actually decides and raises.
    """
    if (reason := calibrate.load_gate_reason(load1, cores)) is not None:
        gate(reason)


SETTLE_TIMEOUT_SECONDS = 180.0
SETTLE_POLL_SECONDS = 5.0


def wait_for_quiet_then_gate(cores: int, settle_timeout: float = SETTLE_TIMEOUT_SECONDS) -> None:
    """Give a hot box time to go quiet, then decide. GATEs only if it never does.

    The 1-minute load average is a *lagging* indicator, and that made the first version of this
    gate useless in the one place it matters most. `make test` runs the suites in sequence with
    `perf` last, so at the instant `perf` starts, the average still carries the six suites that
    just finished — observed at 6.45 against a 2.50 ceiling on a box that was genuinely idle by
    then. Every perf scenario GATEd, on a machine nothing was running on. A gate that cannot pass
    during a full run is not a precondition, it is an outage.

    So: poll until the average decays below the ceiling, up to `settle_timeout`. Decay is
    exponential with a 60s time constant, so falling from 6.45 to 2.50 takes about 57s of real
    quiet — 180s leaves room without waiting on a box that is genuinely busy. Costs nothing on an
    idle box (the first reading passes and the loop never runs).

    `settle_timeout=0` decides on the current reading with no waiting, which is what the tests of
    this rule use — otherwise proving the loud direction would take three minutes.
    """
    ceiling = calibrate.load_ceiling(cores)
    load1 = loadavg1()
    deadline = time.monotonic() + settle_timeout
    while load1 > ceiling and time.monotonic() < deadline:
        print(
            f"perf: waiting for the box to settle — load {load1:.2f} > {ceiling:.2f}, "
            f"{deadline - time.monotonic():.0f}s left before gating"
        )
        time.sleep(SETTLE_POLL_SECONDS)
        load1 = loadavg1()
    gate_unless_quiet(load1, cores)


@pytest.fixture(scope="session", autouse=True)
def _box_is_quiet_enough_to_measure_on() -> None:
    """`docs/E2E.md` section 8's stated measurement precondition, checked instead of assumed.

    The runner already enforces the section's third clause (`perf` runs alone, no sibling suite
    holding workers). Its second clause — "no other load" — had nothing behind it, and the gap is
    not theoretical: a stray `make test-perf` running beside two working agents put S-91 at p95
    10.03-11.19ms against a 10ms budget, a FAIL that says nothing about `core.board()` and
    everything about a contended run queue. Section 8 anticipates exactly this ("a p95 measured
    next to twelve parallel `core` workers is a number about the scheduler") without checking it.

    Autouse and session-scoped, so it decides once, before any corpus is built — an unquiet box
    should not spend a minute loading F4-56700 to produce a number that will be thrown away. GATE,
    never fail: an unmeasurable run is a refusal to certify, not a regression.
    """
    wait_for_quiet_then_gate(os.cpu_count() or 1)


def write_artifact(scenario_id: str, stats: dict, samples: list[float]) -> Path:
    """`artifacts/perf/<S-id>.json` — `docs/E2E.md` section 8's teardown rule, "write the
    distribution and the raw samples." Always includes raw samples, not only for the low-iteration
    rows the document calls out by name — strictly more information in the same one file.

    `loadavg1_at_write` rides along on every row: the gate above proves the box was quiet when the
    suite *started*, which is not the same claim as quiet when this particular scenario ran forty
    seconds later. Recording it costs nothing and makes a surprising number auditable after the
    fact instead of re-litigated from memory.

    **It is a forensic stamp, never a gate input, and it is expected to exceed the gate's own
    ceiling.** Nothing reads it back; no scenario passes or fails on it. Most of the load it
    records *is the measurement* — Postgres chewing this scenario's query plus the corpus build —
    which cannot be subtracted from a real measurement and is not what `docs/E2E.md` section 8
    means by "no other load" (that means foreign load: a sibling suite, another agent's build).
    A full run has stamped 2.58, 3.70, 4.04 and 7.84 against a documented ceiling of 2.50 with the
    gate working exactly as designed. Read it as evidence when a number looks wrong, not as a
    verdict: in that same run S-93 and S-94 were stamped at an identical 7.84, and S-94 came in at
    p95 0.77 ms against a 200 ms budget while S-93 missed a 300 ms p99 by 3x — same box, same
    instant, opposite outcomes, so load was not what made the slow row slow."""
    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    path = ARTIFACTS_DIR / f"{scenario_id}.json"
    path.write_text(json.dumps(
        {**stats, "loadavg1_at_write": round(loadavg1(), 2), "samples_ms": samples}, indent=2
    ))
    return path


def xact_commit_on(conn: psycopg.Connection, dbname: str) -> int:
    """`pg_stat_database.xact_commit` for `dbname`, read through a connection that is **already
    open** — the distinction S-98 turns on, and the reason this function exists separately from
    the one below.

    Opening a backend is itself a commit. PostgreSQL validates the session against the catalogs
    (`InitPostgres`, reading `pg_authid`/`pg_database`/role settings) inside a transaction that
    commits before the client can send its first statement, and `xact_commit` counts it. Measured
    on this cluster: a connection that sends *zero* SQL and closes moves the counter by exactly 1,
    every time; a connection that also does one real transaction moves it by exactly 2. So any
    reading taken with a fresh connection carries that connection's own bootstrap commit, and a
    window that opens before the workload's connection exists can never see a delta below 2.

    `pg_stat_clear_snapshot()` first, which a single-shot connection never needed: statistics are
    snapshotted per transaction, and a connection reused for two readings must not answer the
    second one out of the first one's snapshot.

    **This counter is database-wide, and that is a limit nothing here can remove.** It counts
    every transaction committed against `dbname` by *any* backend, not just the caller's. On a
    freshly created clone that the test alone connects to, the autovacuum launcher still visits —
    it connects (one bootstrap commit) and runs its check (another), and does so without leaving
    `last_autovacuum`/`last_autoanalyze` set, because finding no work to do is not a vacuum.
    Measured on this cluster over 25 runs of S-98's exact window: 23 read a delta of 1, one read
    3, one read 5 — even-numbered excesses, one visiting backend each, `autovacuum_ran=False` and
    `autoanalyze_ran=False` in both. So a delta of 1 is the common case, not a guaranteed one, and
    `docs/PENDING_DOC_FIXES.md` row 70 carries the direct replacement this asks for."""
    conn.execute("SELECT pg_stat_clear_snapshot()")
    (count,) = conn.execute(
        "SELECT xact_commit FROM pg_stat_database WHERE datname = %s", (dbname,)
    ).fetchone()
    return count


# --- baseline seeding: accumulated across the whole session, written once at the end -----------
#
# `tests/harness/calibrate.py::maybe_seed_baseline` takes one `{scenario_id: value_ms}` dict for
# the *whole run* and writes it at most once, only when this machine has no committed baseline
# yet. Nine scenario tests each measure one row; something has to collect the ones that actually
# passed their own absolute budget into one dict before that single call happens. A session-scoped
# `pytest.Config.stash` entry does that without this module importing anything back: the scenario
# files (`test_perf_core_queries.py`, `test_perf_transport_import.py`) need this module for their
# fixtures, same as before the split, and `judge.py` — where `record_passed_absolute`'s only
# caller lives now — needs it back for `REPO_ROOT`/`write_artifact` and to hand results to this
# function. Either of those importing this module *back* for results would be a real cycle, not
# a hypothetical one, which is exactly what the stash avoids, and without inventing a second file
# on disk just to pass nine numbers from "during the run" to "the end of the run".

_PASSED_ABSOLUTE_KEY = pytest.StashKey[dict]()


def record_passed_absolute(request: pytest.FixtureRequest, scenario_id: str, value_ms: float) -> None:
    """Called by `judge.py`'s `_judge`, once per scenario, only when that scenario's own gate
    statistic was `<= budget_ms` this run — never for a GATEd or FAILed scenario
    (`maybe_seed_baseline`'s own docstring: "a GATEd or FAILed scenario has no legitimate number
    to seed a future comparison with"). `pytest_sessionfinish` below reads back whatever every
    scenario's call to `_judge` produced."""
    request.config.stash.setdefault(_PASSED_ABSOLUTE_KEY, {})[scenario_id] = value_ms


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    """Fires once, after every test in the session — including a `--suite perf`-scoped run that
    only ever collects this one directory. Writes `tests/perf/baseline.<machine-id>.json` if and
    only if this machine has never had one (`maybe_seed_baseline`'s own guard); a machine that
    already has a committed baseline is never touched here, no matter what this run measured."""
    results = session.config.stash.get(_PASSED_ABSOLUTE_KEY, {})
    if results:
        calibrate.maybe_seed_baseline(results)
