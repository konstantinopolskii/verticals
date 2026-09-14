"""V2 R2: fixed 3-year windows while the persisted scale key stays ``decade``."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import psycopg

from verticals.core import board as board_core
from verticals.core.vertical import descriptor, period_key


F2_SQL = Path(__file__).resolve().parents[1] / "fixtures" / "f2_synth.sql"


def test_decade_uses_fixed_trienniums_anchored_at_2026() -> None:
    assert period_key("decade", date(2027, 5, 1)) == "2026–2028"
    assert period_key("decade", date(2028, 12, 31)) == "2026–2028"
    assert period_key("decade", date(2029, 1, 1)) == "2029–2031"
    assert period_key("decade", date(2020, 1, 1)) == "2020–2022"


def test_decade_bounds_match_triennium_boundaries() -> None:
    bounds = descriptor("decade").bounds_fn(date(2027, 5, 1))
    assert bounds == (date(2026, 1, 1), date(2028, 12, 31))
    assert descriptor("decade").bounds_fn(date(2029, 1, 1)) == (
        date(2029, 1, 1),
        date(2031, 12, 31),
    )


def test_board_decade_column_keeps_key_and_exposes_new_label(db: psycopg.Connection) -> None:
    board = board_core.board(db, owner="SYNOWNER", date=date(2027, 5, 1))
    column = next(column for column in board.columns if column.vertical == "decade")
    assert column.vertical == "decade"
    assert column.label == "3 years"
    assert column.period_key == "2026–2028"


def test_existing_decade_rows_load_without_rewrite_or_census_change(
    db: psycopg.Connection,
) -> None:
    db.execute(F2_SQL.read_text())
    before = db.execute(
        "SELECT id, period_key FROM goals WHERE vertical = 'decade' ORDER BY id"
    ).fetchall()
    census_before = db.execute("SELECT count(*) FROM goals").fetchone()[0]

    loaded_board = board_core.board(db, owner="t1", date=date(2029, 12, 31))
    loaded_decade = next(
        column for column in loaded_board.columns if column.vertical == "decade"
    )

    after = db.execute(
        "SELECT id, period_key FROM goals WHERE vertical = 'decade' ORDER BY id"
    ).fetchall()
    census_after = db.execute("SELECT count(*) FROM goals").fetchone()[0]
    assert loaded_decade.period_key == "2029–2031"
    # R10 legitimately adds overdue decade rows to the shown column as ghosts; this test is
    # about the NATIVE members of the 2029–2031 window, so ghosts are filtered out.
    native = [goal for goal in loaded_decade.goals if goal.id not in loaded_board.ghosts]
    assert {goal.id for goal in native} == {"SYNEDG05", "SYNEDG06"}
    assert {goal.period_key for goal in native} == {"2020s", "2030s"}
    assert before == after
    assert census_before == census_after == 49
    assert {key for _id, key in after} == {"2020s", "2030s"}
