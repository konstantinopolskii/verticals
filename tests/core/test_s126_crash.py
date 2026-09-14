"""S-126 — the database dies in the middle of the one dangerous write. `docs/E2E.md` S-126
(§3, "Suite A — `core`"); `docs/ACCEPTANCE.md` AC-203; `verticals/core/tree.py`'s own R1 risk
("Path/depth recomputation on reparent of a deep subtree ... the product's one dangerous write").

This is the project's own founding question — "what happens when the database vanishes?" — asked
of the one write that can silently corrupt the tree: the prefix `UPDATE` `_rewrite_subtree`
(`core/tree.py`) runs inside `move`/`detach`, and the multi-`INSERT` transaction `create`
(`core/goals.py`) runs for a nested plan. Both wrap their work in one transaction (IR-02); this
scenario proves that promise against a real backend kill, not against a mocked one — there are no
mocks anywhere in this file, or this suite (`docs/BRIEF.md` rule 2, `tests/static/test_no_mocks.py`).

**Own cluster, per `docs/E2E.md` §2 "Scenarios that own the server, and the serialized tail".**
`pg_terminate_backend` on the shared cluster would be visible to (and could hit) every other
parallel worker's connection; the catalogue's own fix is for S-126 to `initdb`/`pg_ctl` a private,
throwaway cluster reachable only over a unix socket, exactly like S-45
(`tests/http/test_availability.py`) already does for the same structural reason (§2 lists S-45,
S-89 and S-126 together as the three scenarios that "own the server"). `_private_cluster` below
duplicates S-45's own recipe rather than importing across a suite boundary — matching that file's
own stated philosophy ("this file owns its whole stack independently, on purpose") and this
codebase's established convention of small, duplicated, per-module machinery over a shared import
(`core/moves.py`'s docstring makes the identical call for `_validate_schedule`). It also carries
forward S-45's own two corrections to §2's literal setup recipe, found by that WP by running it,
not by inspection: `-p 0` is not a valid Postgres port (bind port 0, read back what the OS
assigned, hand that concrete number to `-p`); a scenario-test path under pytest's own `tmp_path`
is too long for a unix-socket directory specifically (over 103/108 bytes on macOS/Linux), so only
`unix_socket_directories` moves to a short-prefixed `tempfile.mkdtemp()`, never `PGDATA` itself.

**No scenario-level "serialized tail" scheduler exists in the harness today — checked, not
assumed.** `tests/harness/runner.py`'s only granularity is per-*suite*: `SERIAL_SUITES = {"perf",
"ui", "uidiff"}` runs a suite without `-n auto`; `core` is not in that set, so `make test-core`
always runs this file under `pytest-xdist` parallel workers. There is no marker, no
`xdist_group`, no scenario allowlist anywhere that holds `core`'s three "own cluster" scenarios
back to run last or alone — and S-45, the one other already-built member of this same group, was
never given one either; it simply relies on the fact that a fully private cluster on a random
free port and a `tempfile.mkdtemp()` socket directory cannot collide with any sibling worker's
state no matter when it runs. The two tests below follow the identical reasoning and are
therefore safe under `-n auto` as shipped. Per this task's own instruction not to invent a
scheduler: this is reported as a gap, not silently worked around with a new mechanism. If the
literal "runs last, alone" placement `docs/E2E.md` §2 describes is wanted, `runner.py` needs a
scenario-level allowlist (mirroring `SERIAL_SUITES` but by scenario id, subtracted from the
xdist-eligible set and re-run single-threaded afterward) — a `tests/harness/runner.py` change,
out of this scenario's own remit.

**Second half's blocking point, and why it cannot be any deeper.** The catalogue asks to kill the
backend "mid-`create`" with S-52's nested payload (root + 3 children, one with 2 grandchildren = 6
rows). An external connection can only ever contend with `create()` on an object that exists
*before* `create()`'s own transaction opened: every row the nested call itself inserts is, by
ordinary MVCC visibility, invisible to every other session until that whole transaction commits —
which, if this scenario's premise is true, never happens. So no external lock can ever be
positioned to fire *after* some of `create()`'s own inserts have landed and *before* others —
there is no "later" row for a second connection to grab a hold of. This is proved directly below
(`mid_flight_count == before_count`, read from an independent connection while A sits blocked),
not asserted on faith. Given that ceiling, the deepest reachable, deterministic (not a race)
external block is: connection B pre-locks `SYNQ1R01`, an existing F2 row in the `(t1, quarter,
2026-Q3)` sibling group — the same group S-52's second child ("Fold into next quarter's plan",
`vertical:'quarter'`, `anchor_date:'2026-08-10'` → `period_key` `2026-Q3`, confirmed via
`vertical.period_key`) renumbers into (`core/tree.py`'s own module docstring: a board column's
sibling group is `(owner, vertical, period_key)` regardless of `parent_id`, so newly-created
descendants sharing that vertical/period share the *existing* group too). `_create_children`
(`core/goals.py`) walks depth-first, so by the time `create()` reaches that second child, the
root, the first child and both of the first child's own children — 4 of the 6 eventual rows —
are already inserted, uncommitted, inside A's own open transaction; `tree.renumber`'s own
`SELECT ... FOR UPDATE` over that sibling group (`core/tree.py`) then blocks on B's held lock.
Verified against a live run before being committed to this file (not merely reasoned about):
the watcher's own captured `query` text at the moment of the kill was the literal renumber
`SELECT ... FOR UPDATE` this paragraph names.

**Reuses `tests/core/test_tree.py`'s own AC-203 sweep and digest helper, does not re-derive
them.** `_tree_invariant_violations` and `_digest` are plain module-level functions there (no
`__init__.py` anywhere under `tests/`, `pyproject.toml`'s `pythonpath = ["."]` makes every
directory an importable namespace package — the same cross-file pattern `tests/core/test_board.py`
already uses for `tests.conftest`) — confirmed importable by running it, not assumed. Copying the
five SQL statements a second time here was rejected on exactly the same grounds `test_tree.py`
itself rejects re-deriving AC-203's own literal wording (its own docstring: scoped to
`vertical IS NOT NULL` for clause 5, the only reading consistent with F2 as shipped) — one
definition, referenced, not two definitions that can quietly drift apart.
"""

from __future__ import annotations

import re
import shutil
import socket
import subprocess
import tempfile
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date
from pathlib import Path

import psycopg
import pytest

from verticals.core import board as board_mod
from verticals.core import goals, moves
from verticals.db import runner as migration_runner
from tests.core.test_tree import _digest
from tests.harness.tree_invariant import violations as _tree_invariant_violations
from tests.harness.report import gate

REPO_ROOT = Path(__file__).resolve().parents[2]
F2_SQL = REPO_ROOT / "tests" / "fixtures" / "f2_synth.sql"
REQUIRED_PG_MAJOR = "16"  # matches docker-compose.test.yml's postgres:16-alpine pin
OWNER = "t1"
BOARD_DATE = date(2026, 8, 8)  # F2's own reference board date, used throughout the suite

_LOCK_WAIT_DEADLINE_S = 10.0  # generous but bounded — a private, single-purpose cluster, no
# reason a real lock wait should ever take more than milliseconds to become observable
_POLL_INTERVAL_S = 0.05  # a real sleep between polls; never a busy-spin

# S-52's own literal payload (docs/E2E.md lines 1329-1339; also driven at the MCP layer by
# tests/mcp/test_create.py and at the core layer, without a kill, by
# tests/core/test_goals.py::test_create_nested_plan_is_one_call_flattened) — redefined locally
# rather than imported across a suite boundary, matching this codebase's own convention
# (core/moves.py's docstring: "small, duplicated, per-module ... rather than importing").
_S52_BODY = ("The retro surfaced three carry-forward items. " * 9)[:400]
assert len(_S52_BODY) == 400, len(_S52_BODY)
_S52_CHILDREN = [
    {
        "title": "Write up the sources",
        "vertical": "day",
        "anchor_date": date(2026, 8, 10),
        "children": [
            {"title": "Pull the raw notes"},
            {"title": "Tag the quotes"},
        ],
    },
    # This child's (owner='t1', vertical='quarter', period_key='2026-Q3') group already holds
    # SYNQ1R01/SYNQ2R01 in F2 — the deliberate blocking point; see module docstring.
    {"title": "Fold into next quarter's plan", "vertical": "quarter", "anchor_date": date(2026, 8, 10)},
    {"title": "Someday, no promise", "vertical": None},
]


# --- private-cluster machinery (mirrors tests/http/test_availability.py's S-45 recipe) ----------


def _require_pg_binaries() -> tuple[str, str]:
    """`initdb`/`pg_ctl` resolved off `PATH`. A missing binary or a present-but-wrong-major
    install is an environment precondition this scenario cannot satisfy — GATE, never
    `pytest.skip` (`tests/harness/report.py`'s own rule: a skip is always a FAIL under AC-089's
    `skip == 0`; `pytest.skip` would silently violate that, the way S-45 itself currently does —
    see this task's report for that finding)."""
    initdb = shutil.which("initdb")
    pg_ctl = shutil.which("pg_ctl")
    if not (initdb and pg_ctl):
        missing = [n for n, p in (("initdb", initdb), ("pg_ctl", pg_ctl)) if not p]
        gate(f"S-126 needs a local Postgres {REQUIRED_PG_MAJOR} install on PATH (missing: {', '.join(missing)})")
    version_out = subprocess.run([pg_ctl, "--version"], capture_output=True, text=True).stdout
    match = re.search(r"PostgreSQL\)?\s+(\d+)\.", version_out)
    major = match.group(1) if match else None
    if major != REQUIRED_PG_MAJOR:
        gate(
            f"S-126 needs Postgres {REQUIRED_PG_MAJOR} on PATH to match docker-compose.test.yml's "
            f"own pin; found {version_out.strip() or '(unreadable version string)'}"
        )
    return initdb, pg_ctl


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _run(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(args, capture_output=True, text=True)


@contextmanager
def _private_cluster(tmp_path: Path, *, label: str) -> Iterator[str]:
    """Boots a throwaway, single-purpose Postgres cluster reachable only over a unix socket,
    migrates it to head, and yields its DSN (the default `postgres` database — a private cluster
    needs no separate app database, matching S-45's own choice). Teardown stops it, removes its
    data and socket directories, and asserts the postmaster is actually gone and nothing leaked —
    the same three checks S-45 makes at its own teardown."""
    initdb, pg_ctl = _require_pg_binaries()
    pgdata = tmp_path / f"pg126{label}"
    pg_log = tmp_path / f"pg126{label}.log"
    sock_dir = Path(tempfile.mkdtemp(prefix=f"hzpg126{label}-"))  # short prefix: see module docstring
    port = _free_port()
    dsn = f"postgresql://s126@/postgres?host={sock_dir}&port={port}"
    started = False
    try:
        r = _run([initdb, "-D", str(pgdata), "--auth=trust", "-U", "s126"])
        assert r.returncode == 0, f"initdb failed:\n{r.stdout}\n{r.stderr}"
        r = _run(
            [pg_ctl, "-D", str(pgdata), "-o", f"-p {port} -k {sock_dir} -h ''", "-l", str(pg_log), "-w", "start"]
        )
        assert r.returncode == 0, f"pg_ctl start failed:\n{r.stdout}\n{r.stderr}\nlog:\n{pg_log.read_text()}"
        started = True
        migration_runner.run_up(dsn)
        yield dsn
    finally:
        if started:
            _run([pg_ctl, "-D", str(pgdata), "-m", "fast", "-t", "30", "-w", "stop"])
        pg_pid_survives = bool(_run(["pgrep", "-f", str(pgdata)]).stdout.strip())
        shutil.rmtree(pgdata, ignore_errors=True)
        shutil.rmtree(sock_dir, ignore_errors=True)
        assert not pg_pid_survives, f"a postgres process for the {label!r} private cluster is still running"
        assert not pgdata.exists(), f"the {label!r} private cluster's data directory was not removed"


def _wait_for_lock_wait(
    watcher: psycopg.Connection, pid: int, *, deadline_s: float = _LOCK_WAIT_DEADLINE_S
) -> tuple[str | None, str | None, str | None] | None:
    """Poll `pg_stat_activity` for `pid` until `wait_event_type = 'Lock'`, bounded by
    `deadline_s`, sleeping `_POLL_INTERVAL_S` between polls — never a busy-spin, never a single
    fixed-guess sleep. Returns the last observed `(wait_event_type, state, query)` row (`None`
    only if `pid` never appeared in `pg_stat_activity` at all); the caller decides pass/GATE."""
    deadline = time.monotonic() + deadline_s
    observed = None
    while time.monotonic() < deadline:
        observed = watcher.execute(
            "SELECT wait_event_type, state, query FROM pg_stat_activity WHERE pid = %s", (pid,)
        ).fetchone()
        if observed is not None and observed[0] == "Lock":
            return observed
        time.sleep(_POLL_INTERVAL_S)
    return observed


# --- S-126, half 1: the prefix UPDATE (AC-028's own rewrite, R1's "one dangerous write") --------


def test_s126a_reparent_backend_killed_mid_prefix_update_leaves_digest_byte_identical(
    tmp_path: Path,
) -> None:
    """Steps 1-6 of `docs/E2E.md` S-126's own text, literally: digest; B locks `SYNSUB02` FOR
    UPDATE (one of the six rows `reparent('SYNQ1R01','SYNDEC01')` rewrites — AC-028's own table,
    `tests/core/test_tree.py::test_s10_...`); A starts `reparent`; a watcher polls for A's
    `wait_event_type='Lock'` then `pg_terminate_backend`s it; B releases; re-read everything."""
    with _private_cluster(tmp_path, label="a") as dsn:
        with psycopg.connect(dsn, autocommit=True) as setup:
            setup.execute(F2_SQL.read_text())
            setup.execute("ANALYZE goals")

        with psycopg.connect(dsn, autocommit=True) as baseline:
            digest_before = _digest(baseline)
            assert _tree_invariant_violations(baseline, OWNER) == []
            assert baseline.execute("SELECT count(*) FROM goals").fetchone()[0] == 49

        conn_b = psycopg.connect(dsn, autocommit=False)
        conn_a = psycopg.connect(dsn, autocommit=True)
        a_outcome: dict[str, object] = {}
        try:
            # Step 2: B locks a row inside the six-row subtree the rewrite below will touch.
            conn_b.execute("SELECT id FROM goals WHERE id = 'SYNSUB02' FOR UPDATE")

            # pg_backend_pid() from A itself — the reliable way to know which backend is A's,
            # rather than matching on query text (module docstring's own warning: matching the
            # wrong backend would produce a green run that proves nothing).
            (a_pid,) = conn_a.execute("SELECT pg_backend_pid()").fetchone()
            assert a_pid == conn_a.info.backend_pid, "conn.info.backend_pid disagrees with pg_backend_pid()"

            def _run_a() -> None:
                # Broad catch is deliberate: the whole point is to inspect the *real* exception
                # type below, not to pre-judge it with pytest.raises (which cannot straddle a
                # second thread — A must run concurrently with the watcher's poll loop).
                try:
                    moves.reparent(conn_a, owner=OWNER, id="SYNQ1R01", parent_id="SYNDEC01")
                    a_outcome["raised"] = None
                except Exception as exc:  # noqa: BLE001 — inspected via isinstance() below
                    a_outcome["raised"] = exc

            # Step 3: A starts reparent(), in its own thread — it will block inside the prefix
            # UPDATE and must not stall the watcher below.
            a_thread = threading.Thread(target=_run_a, daemon=True)
            a_thread.start()

            # Step 4: watch for A's wait state, then terminate it.
            with psycopg.connect(dsn, autocommit=True) as watcher:
                observed = _wait_for_lock_wait(watcher, a_pid)
                if observed is None or observed[0] != "Lock":
                    gate(
                        "connection A never showed wait_event_type='Lock' on the prefix UPDATE "
                        f"within {_LOCK_WAIT_DEADLINE_S}s (last observed wait_event_type="
                        f"{observed[0] if observed else None!r}, state={observed[1] if observed else None!r})"
                    )
                assert "UPDATE goals" in (observed[2] or ""), (
                    f"A was blocked, but not inside the prefix UPDATE — observed query: {observed[2]!r}"
                )
                watcher.execute("SELECT pg_terminate_backend(%s)", (a_pid,))

            a_thread.join(timeout=_LOCK_WAIT_DEADLINE_S)
            assert not a_thread.is_alive(), "connection A's reparent() never returned after the kill"

            # Step 5: release B's lock.
            conn_b.rollback()
        finally:
            conn_b.close()
            conn_a.close()  # safe on an already-severed connection — verified directly, no-op

        raised = a_outcome.get("raised")
        assert isinstance(raised, psycopg.OperationalError), (
            f"expected the client to raise psycopg.OperationalError, not a silent success; got {raised!r}"
        )

        # Step 6: re-read everything, on fresh connections — "the pool survives" reads, at this
        # layer with no pool object to inspect (IR-01: pooling is api/'s concern), as "a fresh
        # connection serves the database normally."
        with psycopg.connect(dsn, autocommit=True) as fresh:
            digest_after = _digest(fresh)
            assert digest_after == digest_before, (
                "full-table digest changed after a mid-UPDATE backend kill — the prefix UPDATE "
                "half-committed instead of rolling back atomically"
            )
            assert _tree_invariant_violations(fresh, OWNER) == []
            assert fresh.execute("SELECT count(*) FROM goals").fetchone()[0] == 49

        with psycopg.connect(dsn, autocommit=True) as fresh2:
            result = board_mod.board(fresh2, owner=OWNER, date=BOARD_DATE)
            assert len(result.columns) == 8, "a fresh connection did not get a normal board response"


# --- S-126, half 2: create() with S-52's nested payload, same shape -----------------------------


def test_s126b_create_backend_killed_mid_nested_plan_leaves_row_count_exact(tmp_path: Path) -> None:
    """`docs/E2E.md` S-126's second half: "kill the backend mid-`create` with nested `children`
    (S-52's payload) and assert row count is exactly the pre-call value — a partially landed plan
    is the agent-era version of the same defect." See module docstring for the blocking-point
    design (connection B pre-locks `SYNQ1R01`, forcing the block inside the *second* top-level
    child's own position-renumber, four rows into the six-row plan)."""
    with _private_cluster(tmp_path, label="b") as dsn:
        with psycopg.connect(dsn, autocommit=True) as setup:
            setup.execute(F2_SQL.read_text())
            setup.execute("ANALYZE goals")
            before_count = setup.execute("SELECT count(*) FROM goals").fetchone()[0]
        assert before_count == 49

        conn_b = psycopg.connect(dsn, autocommit=False)
        conn_a = psycopg.connect(dsn, autocommit=True)
        a_outcome: dict[str, object] = {}
        try:
            conn_b.execute("SELECT id FROM goals WHERE id = 'SYNQ1R01' FOR UPDATE")

            (a_pid,) = conn_a.execute("SELECT pg_backend_pid()").fetchone()
            assert a_pid == conn_a.info.backend_pid, "conn.info.backend_pid disagrees with pg_backend_pid()"

            def _run_a() -> None:
                try:
                    goals.create(
                        conn_a,
                        owner=OWNER,
                        title="Retro carry-forward",
                        tags=["retro"],
                        vertical="week",
                        anchor_date=date(2026, 8, 10),
                        body=_S52_BODY,
                        children=_S52_CHILDREN,
                    )
                    a_outcome["raised"] = None
                except Exception as exc:  # noqa: BLE001 — inspected via isinstance() below
                    a_outcome["raised"] = exc

            a_thread = threading.Thread(target=_run_a, daemon=True)
            a_thread.start()

            with psycopg.connect(dsn, autocommit=True) as watcher:
                observed = _wait_for_lock_wait(watcher, a_pid)
                if observed is None or observed[0] != "Lock":
                    gate(
                        "connection A never showed wait_event_type='Lock' inside create() within "
                        f"{_LOCK_WAIT_DEADLINE_S}s (last observed wait_event_type="
                        f"{observed[0] if observed else None!r}, state={observed[1] if observed else None!r})"
                    )
                assert "FOR UPDATE" in (observed[2] or "").upper(), (
                    f"A was blocked, but not inside the sibling-group renumber lock — observed "
                    f"query: {observed[2]!r}"
                )

                # Proof this is genuinely a *mid*-flight kill, not a before-the-first-write one:
                # an independent, ordinary connection must still see exactly the pre-call count —
                # A's own root + first child + two grandchildren (4 rows) are inserted by now,
                # inside A's still-open transaction, and MUST be invisible to everyone else.
                (mid_flight_count,) = watcher.execute("SELECT count(*) FROM goals").fetchone()
                assert mid_flight_count == before_count, (
                    f"watcher saw {mid_flight_count} rows while A was blocked inside create(), "
                    f"expected exactly the pre-call {before_count} — A's uncommitted inserts "
                    f"leaked to another session"
                )

                watcher.execute("SELECT pg_terminate_backend(%s)", (a_pid,))

            a_thread.join(timeout=_LOCK_WAIT_DEADLINE_S)
            assert not a_thread.is_alive(), "connection A's create() never returned after the kill"

            conn_b.rollback()
        finally:
            conn_b.close()
            conn_a.close()

        raised = a_outcome.get("raised")
        assert isinstance(raised, psycopg.OperationalError), (
            f"expected the client to raise psycopg.OperationalError, not a silent success; got {raised!r}"
        )

        with psycopg.connect(dsn, autocommit=True) as fresh:
            after_count = fresh.execute("SELECT count(*) FROM goals").fetchone()[0]
            assert after_count == before_count, (
                f"row count after the killed create() is {after_count}, expected exactly the "
                f"pre-call {before_count} — a partially landed plan survived the crash"
            )
            leftover = fresh.execute(
                "SELECT id, title FROM goals WHERE title IN "
                "('Retro carry-forward', 'Write up the sources', 'Pull the raw notes', "
                "'Tag the quotes', %s, 'Someday, no promise')",
                (_S52_CHILDREN[1]["title"],),
            ).fetchall()
            assert leftover == [], f"rows from the killed create() survived: {leftover}"
            assert _tree_invariant_violations(fresh, OWNER) == []
