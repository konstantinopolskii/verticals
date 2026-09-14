"""R9 value ideas through the real detail read and real Postgres."""

from __future__ import annotations

from datetime import date

import psycopg

from verticals.core import goals, moves

ANCHOR = date(2026, 8, 12)
OWNER = "SYN-ideas-owner"


def _create(
    conn: psycopg.Connection,
    owner: str,
    title: str,
    vertical: str,
    parent_id: str | None = None,
):
    return goals.create(
        conn,
        owner=owner,
        title=title,
        vertical=vertical,
        anchor_date=ANCHOR,
        parent_id=parent_id,
    ).goal


def test_value_ideas_include_all_descendants_sort_and_exclude_principles(
    db: psycopg.Connection,
) -> None:
    value = _create(db, OWNER, "SYN value", "life")
    principle = _create(db, OWNER, "SYN principle", "life", value.id)
    year_idea = _create(db, OWNER, "SYN year idea", "year", value.id)
    month_context = _create(db, OWNER, "SYN context principle", "life", value.id)
    month_idea = _create(db, OWNER, "SYN month idea", "month", month_context.id)
    moves.park(db, owner=OWNER, id=month_idea.id)
    moves.park(db, owner=OWNER, id=year_idea.id)

    detail = goals.goal(db, owner=OWNER, id=value.id)

    assert [g.id for g in detail.children] == [principle.id, month_context.id]
    assert [g.id for g in detail.ideas] == [year_idea.id, month_idea.id]
    assert detail.ideas[0].parked_from_vertical == "year"
    assert detail.ideas[1].parked_from_vertical == "month"
    assert month_idea.parent_id != value.id, "fixture must prove descendant, not direct-child only"
    assert principle.id not in {g.id for g in detail.ideas}


def test_value_ideas_are_owner_scoped(db: psycopg.Connection) -> None:
    value = _create(db, OWNER, "SYN scoped value", "life")
    own = _create(db, OWNER, "SYN own idea", "week", value.id)
    moves.park(db, owner=OWNER, id=own.id)

    other_owner = "SYN-other-ideas-owner"
    other_value = _create(db, other_owner, "SYN other value", "life")
    other = _create(db, other_owner, "SYN foreign idea", "year", other_value.id)
    moves.park(db, owner=other_owner, id=other.id)

    detail = goals.goal(db, owner=OWNER, id=value.id)
    assert [g.id for g in detail.ideas] == [own.id]
    assert other.id not in {g.id for g in detail.ideas}
