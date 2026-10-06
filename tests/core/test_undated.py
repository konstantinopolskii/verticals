"""The Inbox (Inbox and Documents redesign, round 7): everything with no date, the goals under a parent included, with
the goal each sits under, its value's colour and the column it left, newest first."""

from __future__ import annotations

from datetime import date

import psycopg

from verticals.core import goals, moves, undated

OWNER = "SYN-undated-owner"
DAY = date(2026, 10, 7)


def test_every_undated_open_goal_with_its_goal_and_value(db: psycopg.Connection) -> None:
    value = goals.create(db, owner=OWNER, title="SYN value", vertical="life", anchor_date=DAY, color="#92ce14").goal.id
    month = goals.create(db, owner=OWNER, title="SYN month", vertical="month", anchor_date=DAY, parent_id=value).goal.id
    loose = goals.create(db, owner=OWNER, title="SYN loose thought").goal.id
    idea = goals.create(db, owner=OWNER, title="SYN idea under the month", parent_id=month).goal.id
    done = goals.create(db, owner=OWNER, title="SYN done thought").goal.id
    goals.update(db, owner=OWNER, id=done, done=True)

    rows = {row.id: row for row in undated.undated(db, owner=OWNER)}
    assert set(rows) == {loose, idea}
    assert (rows[idea].parent_id, rows[idea].parent_title, rows[idea].value_color) == (month, "SYN month", "#92ce14")
    assert rows[idea].parked_from_vertical == "month"
    assert (rows[loose].parent_id, rows[loose].value_color, rows[loose].parked_from_vertical) == (None, None, "life")


def test_a_parked_task_keeps_the_column_it_left(db: psycopg.Connection) -> None:
    month = goals.create(db, owner=OWNER, title="SYN month", vertical="month", anchor_date=DAY).goal.id
    week = goals.create(db, owner=OWNER, title="SYN week task", vertical="week", anchor_date=DAY, parent_id=month).goal.id
    moves.park(db, owner=OWNER, id=week)
    (row,) = undated.undated(db, owner=OWNER)
    assert (row.id, row.parked_from_vertical, row.parent_title) == (week, "week", "SYN month")


def test_a_thought_filed_under_a_goal_takes_its_column(db: psycopg.Connection) -> None:
    """The warm-up files a thought written in the Inbox under the goal it belongs to: it shelves by that goal's
    column from then on, as a goal made under it would."""
    quarter = goals.create(db, owner=OWNER, title="SYN quarter", vertical="quarter", anchor_date=DAY).goal.id
    thought = goals.create(db, owner=OWNER, title="SYN thought").goal.id
    moves.reparent(db, owner=OWNER, id=thought, parent_id=quarter)
    (row,) = undated.undated(db, owner=OWNER)
    assert (row.id, row.parent_title, row.parked_from_vertical) == (thought, "SYN quarter", "quarter")
