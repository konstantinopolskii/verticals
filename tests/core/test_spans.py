"""One vertical's periods in a row (docs/design-handoff S5.P1.030) against real Postgres."""

from __future__ import annotations

from datetime import date

import psycopg
import pytest

from verticals.core import board, goals, spans
from verticals.core.errors import ValidationError

OWNER = "SYN-spans-owner"
MONDAY = date(2026, 9, 28)


def _plan(conn: psycopg.Connection, title: str, anchor: date, scale: str = "week", parent: str | None = None) -> str:
    return goals.create(conn, owner=OWNER, title=title, vertical=scale, anchor_date=anchor, parent_id=parent).goal.id


def test_weeks_in_a_row_each_as_the_board_draws_it(db: psycopg.Connection) -> None:
    """S5.P1.004: each span works as the board does, with its goals and steps; this week keeps its carried group."""
    this = _plan(db, "SYN this week", MONDAY)
    step = _plan(db, "SYN its step", MONDAY, parent=this)
    later = _plan(db, "SYN in two weeks", date(2026, 10, 14))
    carried = _plan(db, "SYN carried", date(2026, 9, 21))
    result = spans.spans(db, owner=OWNER, scale="week", start=date(2026, 10, 1), count=4, today=MONDAY)

    assert [c.period_key for c in result.columns] == ["2026-W40", "2026-W41", "2026-W42", "2026-W43"]
    assert {c.vertical for c in result.columns} == {"week"}
    # A step of the same week rides the column too; the client draws it under its parent, as on the board.
    assert [g.id for g in result.columns[0].goals if g.id != carried] == [this, step]
    assert carried in {g.id for g in result.columns[0].goals} and carried in result.ghosts
    assert [g.id for g in result.columns[2].goals] == [later]
    assert [g.id for g in result.children[this]] == [step]
    alone = board.board(db, owner=OWNER, date=date(2026, 10, 14), today=MONDAY)
    assert next(c for c in alone.columns if c.vertical == "week").goals == result.columns[2].goals


def test_months_and_the_limits(db: psycopg.Connection) -> None:
    """S5.P1.034: every vertical but Life opens its spans."""
    result = spans.spans(db, owner=OWNER, scale="month", start=date(2026, 11, 20), count=3, today=MONDAY)
    assert [c.period_key for c in result.columns] == ["2026-11", "2026-12", "2027-01"]
    with pytest.raises(ValidationError):
        spans.spans(db, owner=OWNER, scale="life", start=MONDAY, count=2, today=MONDAY)
    with pytest.raises(ValidationError):
        spans.spans(db, owner=OWNER, scale="week", start=MONDAY, count=spans.MAX_SPANS + 1, today=MONDAY)
