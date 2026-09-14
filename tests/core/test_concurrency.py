"""A direct probe of AC-204 — WP-13 — real concurrent connections racing `goals.create` into one
board column, proving `core/moves.py`'s advisory-lock serialisation: no collision, no deadlock,
existing order preserved across a renumber forced mid-flight. Real Postgres 16, real F2, real
threads with real separate connections — no mocks (`docs/BRIEF.md` rule 2).

Deliberately not named `test_s127_*` / `test_s128_*`: both scenario ids belong to the `http`
suite (`docs/E2E.md` line 667: S-127 is "50 simultaneous `POST /api/goals`" — a server-level
scenario `tests/harness/report.py`'s suite-boundary rule keeps out of `core`, and this WP's own
naming rule claims an id only when that scenario's own steps ran through its own entry point).
What is proven here is the same underlying invariant, AC-204 itself, at the one layer this WP
owns: the `pg_advisory_xact_lock` in `core/moves.py`'s `allocate_position`. The WP-13 card's own
file table names this file `test_concurrency.py` for exactly S-127/S-128 — the filename is kept,
the scenario-claiming test names are not.

Run directly:
    PGHOST=127.0.0.1 PGPORT=55432 PGUSER=verticals PGPASSWORD=verticals \\
        .venv/bin/python -m pytest tests/core/test_concurrency.py -v -s
"""

from __future__ import annotations

import threading
from collections.abc import Iterator
from datetime import date
from pathlib import Path

import psycopg
import pytest

from verticals.core import goals
from tests.conftest import maintenance_dsn

OWNER = "t1"
CONCURRENT_WORKERS = 20

F2_SQL = Path(__file__).resolve().parents[1] / "fixtures" / "f2_synth.sql"


@pytest.fixture
def f2(db: psycopg.Connection) -> Iterator[psycopg.Connection]:
    db.execute(F2_SQL.read_text())
    db.execute("ANALYZE goals")
    yield db


def _group_state(conn: psycopg.Connection) -> list[tuple[str, int]]:
    return conn.execute(
        "SELECT id, position FROM goals"
        " WHERE owner = 't1' AND vertical = 'week' AND period_key = '2026-W32' ORDER BY position"
    ).fetchall()


def _deadlock_count(dsn: str, dbname: str) -> int:
    with psycopg.connect(dsn, autocommit=True) as watcher:
        (value,) = watcher.execute(
            "SELECT deadlocks FROM pg_stat_database WHERE datname = %s", (dbname,)
        ).fetchone()
    return value


def _run_concurrently(targets: list) -> list[BaseException]:
    """`targets`: one zero-arg callable per thread. A `Barrier` holds every thread at the
    starting line so they fire as close to simultaneously as the OS scheduler allows — the point
    is real contention on `allocate_position`'s advisory lock, not a staggered sequence that
    would never actually race."""
    barrier = threading.Barrier(len(targets))
    errors: list[BaseException] = []
    errors_lock = threading.Lock()

    def run(fn) -> None:  # noqa: ANN001 — zero-arg callable, typed at the call site
        try:
            barrier.wait(timeout=10)
            fn()
        except BaseException as exc:  # noqa: BLE001 — collected, asserted on below, never swallowed
            with errors_lock:
                errors.append(exc)

    threads = [threading.Thread(target=run, args=(fn,)) for fn in targets]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    return errors


# --- AC-204 — concurrent tail appends into one column never collide (baseline, no renumber) --------


def test_ac204_concurrent_tail_appends_never_collide(f2: psycopg.Connection, db_dsn: str) -> None:
    """The simplest real race, isolated from any renumber: twenty threads, twenty connections,
    all appending to `(t1, week, 2026-W32)`'s tail at the same instant."""

    def append(i: int):  # noqa: ANN202
        def go() -> None:
            conn = psycopg.connect(db_dsn, autocommit=True)
            try:
                goals.create(
                    conn, owner=OWNER, title=f"tail {i}", vertical="week", anchor_date=date(2026, 8, 5),
                )
            finally:
                conn.close()

        return go

    errors = _run_concurrently([append(i) for i in range(CONCURRENT_WORKERS)])
    assert errors == [], f"{len(errors)} of {CONCURRENT_WORKERS} concurrent creates raised: {errors!r}"

    state = _group_state(f2)
    assert len(state) == 4 + CONCURRENT_WORKERS
    positions = [p for _, p in state]
    assert len(set(positions)) == len(positions), "every position must be distinct"
    assert positions == sorted(positions)


# --- AC-204 — a renumber forced mid-flight does not collide, deadlock, or reorder ------------------


def test_ac204_concurrent_position_allocation_survives_a_mid_flight_renumber(
    f2: psycopg.Connection, db_dsn: str
) -> None:
    """Setup (sequential, S-13's own proven sequence): exhaust the gap between `SYNORD01` and
    `SYNORD02` down to a single integer unit, so the next insert there has no room left and must
    renumber. Then twenty real threads fire at once: one targets the now-exhausted gap directly
    (forcing the renumber inside a transaction racing the other nineteen), the rest append to the
    same column's tail — many users, one board column, not many callers naming the identical
    interior gap (which would violate `move_between`'s own documented adjacency contract the
    instant the first of them committed and moved it)."""
    dsn = maintenance_dsn()
    (dbname,) = f2.execute("SELECT current_database()").fetchone()

    before_id = "SYNORD02"
    for i in range(10):
        created = goals.create(
            f2, owner=OWNER, title=f"setup {i}", vertical="week", anchor_date=date(2026, 8, 5),
            after_id="SYNORD01", before_id=before_id,
        )
        before_id = created.goal.id
    exhausted_neighbor = before_id  # position 1025, adjacent to SYNORD01 at 1024 — no gap left

    state_before = _group_state(f2)
    assert len(state_before) == 14
    ids_before_ordered = [gid for gid, _ in state_before]
    deadlocks_before = _deadlock_count(dsn, dbname)

    def renumbering_insert():  # noqa: ANN202
        def go() -> None:
            conn = psycopg.connect(db_dsn, autocommit=True)
            try:
                goals.create(
                    conn, owner=OWNER, title="forces the renumber", vertical="week",
                    anchor_date=date(2026, 8, 5), after_id="SYNORD01", before_id=exhausted_neighbor,
                )
            finally:
                conn.close()

        return go

    def tail_append(i: int):  # noqa: ANN202
        def go() -> None:
            conn = psycopg.connect(db_dsn, autocommit=True)
            try:
                goals.create(
                    conn, owner=OWNER, title=f"tail {i}", vertical="week", anchor_date=date(2026, 8, 5),
                )
            finally:
                conn.close()

        return go

    targets = [renumbering_insert()] + [tail_append(i) for i in range(1, CONCURRENT_WORKERS)]
    errors = _run_concurrently(targets)
    assert errors == [], f"{len(errors)} of {CONCURRENT_WORKERS} concurrent creates raised: {errors!r}"

    state_after = _group_state(f2)
    assert len(state_after) == 14 + CONCURRENT_WORKERS
    positions_after = [p for _, p in state_after]
    assert len(set(positions_after)) == len(positions_after), "every position must be distinct"
    assert positions_after == sorted(positions_after)

    deadlocks_after = _deadlock_count(dsn, dbname)
    assert deadlocks_after == deadlocks_before, "zero deadlocks"

    # The fourteen pre-existing ids, relative to each other, survive the renumber unmoved —
    # concurrent tail appends land after all of them regardless of exactly how the twenty threads
    # happened to interleave, so this holds independent of scheduling.
    ids_after_ordered = [gid for gid, _ in state_after]
    surviving_in_order = [gid for gid in ids_after_ordered if gid in set(ids_before_ordered)]
    assert surviving_in_order == ids_before_ordered
