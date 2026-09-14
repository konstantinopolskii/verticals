"""R6 park and child-not-above-parent invariants against real Postgres."""

from __future__ import annotations

from datetime import date

import psycopg
import pytest

from verticals.core import goals, moves
from verticals.core.errors import ValidationError

OWNER = "SYN-park-owner"
ANCHOR = date(2026, 8, 12)


def _create(
    conn: psycopg.Connection,
    title: str,
    vertical: str | None,
    *,
    parent_id: str | None = None,
):
    return goals.create(
        conn,
        owner=OWNER,
        title=title,
        parent_id=parent_id,
        vertical=vertical,
        anchor_date=ANCHOR if vertical is not None else None,
    ).goal


def test_park_records_scale_and_preserves_anchor_tree_and_order(db: psycopg.Connection) -> None:
    parent = _create(db, "SYN park parent", "year")
    target = _create(db, "SYN park target", "month", parent_id=parent.id)
    child = _create(db, "SYN parked child", None, parent_id=target.id)
    before = db.execute(
        "SELECT parent_id, path, depth, anchor_date, position FROM goals WHERE id = %s",
        (target.id,),
    ).fetchone()
    subtree_before = db.execute(
        "SELECT id, parent_id, path, depth, position FROM goals "
        "WHERE path LIKE %s ORDER BY id",
        (target.path + "%",),
    ).fetchall()

    parked = moves.park(db, owner=OWNER, id=target.id)

    assert parked.vertical is None
    assert parked.period_key is None
    assert parked.parked_from_vertical == "month"
    assert (parked.parent_id, parked.path, parked.depth, parked.anchor_date, parked.position) == before
    assert db.execute(
        "SELECT id, parent_id, path, depth, position FROM goals "
        "WHERE path LIKE %s ORDER BY id",
        (target.path + "%",),
    ).fetchall() == subtree_before
    assert goals.goal(db, owner=OWNER, id=child.id).goal.parent_id == target.id


def test_park_refuses_double_park_and_a_root_life_value(db: psycopg.Connection) -> None:
    target = _create(db, "SYN park once", "week")
    moves.park(db, owner=OWNER, id=target.id)
    with pytest.raises(ValidationError, match="already parked"):
        moves.park(db, owner=OWNER, id=target.id)

    value = _create(db, "SYN life value", "life")
    with pytest.raises(ValidationError, match="life value"):
        moves.park(db, owner=OWNER, id=value.id)
    assert goals.goal(db, owner=OWNER, id=value.id).goal.vertical == "life"


def test_schedule_unparks_and_clears_parked_rank(db: psycopg.Connection) -> None:
    target = _create(db, "SYN recommit", "month")
    original_anchor = target.anchor_date
    parked = moves.park(db, owner=OWNER, id=target.id)
    assert parked.anchor_date == original_anchor

    scheduled = moves.schedule(
        db, owner=OWNER, id=target.id, vertical="week", anchor_date=ANCHOR
    ).goal
    assert scheduled.vertical == "week"
    assert scheduled.parked_from_vertical is None
    assert scheduled.period_key == "2026-W33"


def test_database_check_holds_in_both_directions(db: psycopg.Connection) -> None:
    scheduled = _create(db, "SYN checked schedule", "week")
    with pytest.raises(psycopg.errors.CheckViolation) as scheduled_exc:
        with db.transaction():
            db.execute(
                "UPDATE goals SET parked_from_vertical = 'week' WHERE id = %s", (scheduled.id,)
            )
    assert scheduled_exc.value.diag.constraint_name == "vertical_parked_together"

    parked = _create(db, "SYN checked park", None)
    with pytest.raises(psycopg.errors.CheckViolation) as parked_exc:
        with db.transaction():
            db.execute("UPDATE goals SET parked_from_vertical = NULL WHERE id = %s", (parked.id,))
    assert parked_exc.value.diag.constraint_name == "vertical_parked_together"


def test_create_schedule_and_reparent_enforce_child_not_above_parent(
    db: psycopg.Connection,
) -> None:
    month_parent = _create(db, "SYN month parent", "month")
    with pytest.raises(ValidationError, match="cannot be placed above parent"):
        _create(db, "SYN invalid year child", "year", parent_id=month_parent.id)

    parked_child = _create(db, "SYN parked exempt child", None, parent_id=month_parent.id)
    with pytest.raises(ValidationError, match="cannot be placed above parent"):
        moves.schedule(
            db, owner=OWNER, id=parked_child.id, vertical="year", anchor_date=ANCHOR
        )
    same = moves.schedule(
        db, owner=OWNER, id=parked_child.id, vertical="month", anchor_date=ANCHOR
    ).goal
    assert same.vertical == "month"
    below = moves.schedule(
        db, owner=OWNER, id=parked_child.id, vertical="week", anchor_date=ANCHOR
    ).goal
    assert below.vertical == "week"

    year_root = _create(db, "SYN year root", "year")
    with pytest.raises(ValidationError, match="cannot be placed above parent"):
        moves.reparent(db, owner=OWNER, id=year_root.id, parent_id=month_parent.id)

    # NULL is below every scale: a parked child can be created and reparented anywhere.
    exempt = _create(db, "SYN null exempt", None)
    moved = moves.reparent(db, owner=OWNER, id=exempt.id, parent_id=month_parent.id)
    assert moved.parent_id == month_parent.id


def test_child_day_to_week_under_day_parent_stays_refused(db: psycopg.Connection) -> None:
    parent = _create(db, "SYN day parent", "day")
    child = _create(db, "SYN day child", "day", parent_id=parent.id)
    with pytest.raises(ValidationError, match="cannot be placed above parent") as exc:
        moves.schedule(db, owner=OWNER, id=child.id, vertical="week", anchor_date=ANCHOR)
    assert exc.value.detail == {
        "field": "vertical",
        "child_id": child.id,
        "child_vertical": "week",
        "parent_id": parent.id,
        "parent_vertical": "day",
    }


def test_schedule_clear_never_cascades_to_descendants(db: psycopg.Connection) -> None:
    parent = _create(db, "SYN clear parent", "week")
    child = _create(db, "SYN clear child", "week", parent_id=parent.id)
    child_before = db.execute(
        "SELECT vertical, anchor_date, period_key, parked_from_vertical, position, updated_at "
        "FROM goals WHERE id = %s",
        (child.id,),
    ).fetchone()

    cleared = moves.schedule(
        db, owner=OWNER, id=parent.id, vertical=None, anchor_date=None
    )

    assert cleared.goal.vertical is None
    assert cleared.descendants_clamped == 0
    assert db.execute(
        "SELECT vertical, anchor_date, period_key, parked_from_vertical, position, updated_at "
        "FROM goals WHERE id = %s",
        (child.id,),
    ).fetchone() == child_before
