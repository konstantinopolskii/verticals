"""A direct probe of the progress rollup — WP-13 — S-17, S-18, S-19, driven through `goals.update`
and read back through `core/board.py`'s frozen `board()` (progress is derived at read time, never
stored — `ARCHITECTURE.md` §3). Real Postgres 16, real F2, no mocks (`docs/BRIEF.md` rule 2).

Run directly:
    PGHOST=127.0.0.1 PGPORT=55432 PGUSER=verticals PGPASSWORD=verticals \\
        .venv/bin/python -m pytest tests/core/test_progress.py -v -s
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date
from pathlib import Path

import psycopg
import pytest

from verticals.core import board, goals
from tests.conftest import maintenance_dsn
from tests.harness import stmt

OWNER = "t1"
BOARD_DATE = date(2026, 8, 8)

F2_SQL = Path(__file__).resolve().parents[1] / "fixtures" / "f2_synth.sql"

# The G1 ladder, root to leaf-parent — `descendants` per S-17's own table.
_LADDER = (
    ("SYNLIF01", 8), ("SYNDEC01", 7), ("SYNYRR01", 6),
    ("SYNQ1R01", 5), ("SYNQ2R01", 4), ("SYNDAY01", 3),
)


@pytest.fixture
def f2(db: psycopg.Connection) -> Iterator[psycopg.Connection]:
    db.execute(F2_SQL.read_text())
    db.execute("ANALYZE goals")
    yield db


def _digest_excluding_completion_fields(conn: psycopg.Connection) -> str:
    """Every stored column except `done_at`/`updated_at` — S-17's "no stored column changed
    except the leaf's own completion stamp and its own `updated_at`"."""
    (value,) = conn.execute(
        "SELECT md5(string_agg("
        "  ROW(id, owner, parent_id, path, depth, vertical, anchor_date, period_key, title, body,"
        "      color, tags, position, origin, created_at)::text,"
        "  '|' ORDER BY id"
        ")) FROM goals"
    ).fetchone()
    return value


def _card(b: board.Board, goal_id: str):  # noqa: ANN201 — returns models.Goal, avoiding the import just for a hint
    for column in b.columns:
        for g in column.goals:
            if g.id == goal_id:
                return g
    return None


def _require_stmt_counter(dsn: str) -> None:
    if not stmt.available(dsn):
        from tests.harness.report import gate

        gate("pg_stat_statements unavailable — statement-count assertion cannot run")


# --- S-17 — progress rolls up a 6-deep chain when one leaf closes -----------------------------------


def test_s17_progress_rolls_up_a_6_deep_chain_when_one_leaf_closes(f2: psycopg.Connection) -> None:
    before = board.board(f2, owner=OWNER, date=BOARD_DATE)
    for goal_id, descendants in _LADDER:
        prog = before.progress[goal_id]
        assert (prog.done, prog.total) == (0, descendants), f"{goal_id} before"

    digest_before = _digest_excluding_completion_fields(f2)

    goals.update(f2, owner=OWNER, id="SYNSUB01", done=True)

    dsn = maintenance_dsn()
    _require_stmt_counter(dsn)
    dbname = stmt.current_dbname(f2)
    stmt.reset(dsn, dbname)
    after = board.board(f2, owner=OWNER, date=BOARD_DATE)
    ran = stmt.count(dsn, dbname)
    assert ran == 1, "progress must ride the same board statement, not a second round trip"

    for goal_id, descendants in _LADDER:
        prog = after.progress[goal_id]
        assert (prog.done, prog.total) == (1, descendants), f"{goal_id} after"

    assert _digest_excluding_completion_fields(f2) == digest_before

    (sub01_done_at,) = f2.execute("SELECT done_at FROM goals WHERE id = 'SYNSUB01'").fetchone()
    assert sub01_done_at is not None
    ancestor_ids = [gid for gid, _ in _LADDER]
    still_open = f2.execute(
        "SELECT count(*) FROM goals WHERE id = ANY(%s) AND done_at IS NOT NULL", (ancestor_ids,)
    ).fetchone()[0]
    assert still_open == 0, "completion must never propagate onto the ancestors themselves"


# --- S-18 — completion never propagates -------------------------------------------------------------


def test_s18_completion_never_propagates(f2: psycopg.Connection) -> None:
    for child_id in ("SYNSUB01", "SYNSUB02", "SYNSUB03"):
        goals.update(f2, owner=OWNER, id=child_id, done=True)

    (day_done_at,) = f2.execute("SELECT done_at FROM goals WHERE id = 'SYNDAY01'").fetchone()
    assert day_done_at is None

    ancestor_ids = ["SYNQ2R01", "SYNQ1R01", "SYNYRR01", "SYNDEC01", "SYNLIF01"]
    open_ancestors = f2.execute(
        "SELECT count(*) FROM goals WHERE id = ANY(%s) AND done_at IS NULL", (ancestor_ids,)
    ).fetchone()[0]
    assert open_ancestors == 5, "all five further ancestors stay open"

    b = board.board(f2, owner=OWNER, date=BOARD_DATE)
    prog = b.progress["SYNDAY01"]
    assert (prog.done, prog.total) == (3, 3)

    card = _card(b, "SYNDAY01")
    assert card is not None, "SYNDAY01 must still render as a card on the board"
    assert card.done_at is None, "the board still renders SYNDAY01 as an open card"


# --- S-19 — closing a parent with open descendants is allowed and reported --------------------------


def test_s19_closing_a_parent_with_open_descendants_is_allowed_and_reported(
    f2: psycopg.Connection,
) -> None:
    updated = goals.update(f2, owner=OWNER, id="SYNDAY01", done=True)

    assert updated.goal.done_at is not None
    assert updated.open_descendants == 3

    children_done_at = f2.execute(
        "SELECT done_at FROM goals WHERE id IN ('SYNSUB01','SYNSUB02','SYNSUB03')"
    ).fetchall()
    assert all(done_at is None for (done_at,) in children_done_at), "children keep done_at IS NULL"
