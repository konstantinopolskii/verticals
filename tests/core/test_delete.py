"""A direct probe of `goals.delete` — WP-13 — S-14, S-15, S-16. Real Postgres 16, real F2, no
mocks (`docs/BRIEF.md` rule 2).

Run directly:
    PGHOST=127.0.0.1 PGPORT=55432 PGUSER=verticals PGPASSWORD=verticals \\
        .venv/bin/python -m pytest tests/core/test_delete.py -v -s
"""

from __future__ import annotations

import threading
from collections.abc import Iterator
from pathlib import Path

import psycopg
import pytest

from verticals.core import goals
from verticals.core.errors import HasChildren, LockNotAvailable, NotFound
from tests.conftest import maintenance_dsn
from tests.harness import stmt

OWNER = "t1"

F2_SQL = Path(__file__).resolve().parents[1] / "fixtures" / "f2_synth.sql"

# G1's full nine ids — the ladder `delete`'s tests below cut into. Digests taken "excluding
# these" are S-15's "every other group untouched" check, without needing to enumerate G2-G8.
_G1_IDS = (
    "SYNLIF01", "SYNDEC01", "SYNYRR01", "SYNQ1R01", "SYNQ2R01", "SYNDAY01",
    "SYNSUB01", "SYNSUB02", "SYNSUB03",
)


@pytest.fixture
def f2(db: psycopg.Connection) -> Iterator[psycopg.Connection]:
    db.execute(F2_SQL.read_text())
    db.execute("ANALYZE goals")
    yield db


def _goal_count(conn: psycopg.Connection) -> int:
    return conn.execute("SELECT count(*) FROM goals").fetchone()[0]


def _digest_excluding(conn: psycopg.Connection, ids: tuple[str, ...]) -> str:
    (value,) = conn.execute(
        "SELECT md5(string_agg(goals::text, '|' ORDER BY id)) FROM goals WHERE id <> ALL(%s)",
        (list(ids),),
    ).fetchone()
    return value


# --- S-14 — delete with children is refused without cascade ---------------------------------------


def test_s14_delete_with_children_is_refused_without_cascade(f2: psycopg.Connection) -> None:
    with pytest.raises(HasChildren) as exc:
        goals.delete(f2, owner=OWNER, id="SYNDAY01", cascade=False)
    assert exc.value.detail["children"] == 3
    assert exc.value.detail["descendants"] == 3
    assert _goal_count(f2) == 49
    assert f2.execute("SELECT 1 FROM goals WHERE id = 'SYNDAY01'").fetchone() is not None

    (confdeltype,) = f2.execute(
        "SELECT confdeltype FROM pg_constraint WHERE conname LIKE 'goals_parent%'"
    ).fetchone()
    assert confdeltype == "r", "the FK must be ON DELETE RESTRICT — no ON DELETE CASCADE anywhere"


# --- S-15 — delete with cascade removes the exact subtree in one transaction -----------------------


def test_s15_delete_with_cascade_removes_the_exact_subtree_in_one_transaction(
    f2: psycopg.Connection, db_dsn: str
) -> None:
    """A second, real connection polls `pg_stat_activity.backend_xid` for the test connection's
    own backend pid while `delete(cascade=True)` runs, standing in for "a concurrent watcher
    connection". Zero observations is a possible, non-flaky outcome (the whole call may complete
    between polls) — what would actually violate S-15 is observing *two different* xids for the
    same call, proving the six-row removal was not one transaction; that is what is asserted."""
    digest_before = _digest_excluding(f2, _G1_IDS)
    pid = f2.info.backend_pid
    seen_xids: set[int] = set()
    stop = threading.Event()

    def watch() -> None:
        with psycopg.connect(db_dsn, autocommit=True) as watcher:
            while not stop.is_set():
                row = watcher.execute(
                    "SELECT backend_xid FROM pg_stat_activity WHERE pid = %s", (pid,)
                ).fetchone()
                if row and row[0] is not None:
                    seen_xids.add(row[0])

    watcher_thread = threading.Thread(target=watch)
    watcher_thread.start()
    try:
        removed = goals.delete(f2, owner=OWNER, id="SYNQ1R01", cascade=True)
    finally:
        stop.set()
        watcher_thread.join(timeout=2)

    assert removed == 6
    assert len(seen_xids) <= 1, f"cascade delete spanned more than one transaction: {seen_xids}"

    remaining = {r[0] for r in f2.execute("SELECT id FROM goals WHERE id = ANY(%s)", ([*_G1_IDS],)).fetchall()}
    assert remaining == {"SYNLIF01", "SYNDEC01", "SYNYRR01"}, "only the un-deleted G1 ancestors remain"
    assert _goal_count(f2) == 43
    assert _digest_excluding(f2, _G1_IDS) == digest_before, "G2-G8 must be byte-for-byte untouched"


# --- S-16 — a failed cascade delete leaves nothing partially deleted --------------------------------


def test_s16_a_failed_cascade_delete_leaves_nothing_partially_deleted(
    f2: psycopg.Connection, db_dsn: str
) -> None:
    """A second connection holds `SELECT ... FOR UPDATE` on `SYNSUB03` — deep inside the subtree
    the cascade is about to remove — without committing. `delete`'s own `SELECT ... FOR UPDATE`
    only names the root (`SYNQ1R01`); it is the final `DELETE ... WHERE id = ... OR path LIKE ...`
    whose row-level locking blocks on `SYNSUB03`, and `goals.delete` (unlike `tree.move`, which
    tests/core/test_tree.py's own equivalent exercises) converts the driver's raw
    `psycopg.errors.LockNotAvailable` into the closed taxonomy's own `LockNotAvailable` before it
    ever reaches a caller — this test asserts on that converted type, not the raw driver one."""
    blocker = psycopg.connect(db_dsn, autocommit=False)
    try:
        blocker.execute("SELECT 1 FROM goals WHERE id = 'SYNSUB03' FOR UPDATE")

        f2.execute("SET lock_timeout = '250ms'")
        with pytest.raises(LockNotAvailable):
            goals.delete(f2, owner=OWNER, id="SYNQ1R01", cascade=True)
    finally:
        blocker.rollback()
        blocker.close()

    assert _goal_count(f2) == 49
    present = {
        r[0]
        for r in f2.execute(
            "SELECT id FROM goals WHERE id IN ('SYNQ2R01','SYNDAY01','SYNSUB01')"
        ).fetchall()
    }
    assert present == {"SYNQ2R01", "SYNDAY01", "SYNSUB01"}, "nothing partially removed"

    # With the blocking lock released, the identical cascade now succeeds cleanly — `f2` is
    # immediately usable again, `delete`'s own `with conn.transaction()` having rolled back.
    f2.execute("SET lock_timeout = DEFAULT")
    removed = goals.delete(f2, owner=OWNER, id="SYNQ1R01", cascade=True)
    assert removed == 6
    assert _goal_count(f2) == 43


# --- delete(): bonus coverage, not claiming any scenario id -----------------------------------------


def test_delete_a_leaf_with_no_children_succeeds_without_cascade(f2: psycopg.Connection) -> None:
    removed = goals.delete(f2, owner=OWNER, id="SYNSUB01", cascade=False)
    assert removed == 1
    assert _goal_count(f2) == 48
    assert f2.execute("SELECT 1 FROM goals WHERE id = 'SYNSUB01'").fetchone() is None


def test_delete_notfound_for_missing_id(f2: psycopg.Connection) -> None:
    with pytest.raises(NotFound):
        goals.delete(f2, owner=OWNER, id="NOSUCHID1", cascade=False)
    assert _goal_count(f2) == 49


def test_delete_cascade_on_a_leaf_is_the_same_as_without(f2: psycopg.Connection) -> None:
    removed = goals.delete(f2, owner=OWNER, id="SYNSUB02", cascade=True)
    assert removed == 1
    assert _goal_count(f2) == 48
