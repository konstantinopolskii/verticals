"""R5 foil update and migration-008 trigger exclusions against real Postgres."""

from __future__ import annotations

from datetime import date

import psycopg

from verticals.core import goals

OWNER = "SYN-foil-owner"


def _revision(conn: psycopg.Connection, goal_id: str) -> int:
    return conn.execute(
        "SELECT content_revision FROM goals WHERE id = %s", (goal_id,)
    ).fetchone()[0]


def test_foil_sets_and_clears_without_bumping_content_revision(db: psycopg.Connection) -> None:
    target = goals.create(conn=db, owner=OWNER, title="SYN foil target").goal
    assert target.foil is False
    assert _revision(db, target.id) == 0

    set_result = goals.update(db, owner=OWNER, id=target.id, foil=True)
    assert set_result.goal.foil is True
    assert _revision(db, target.id) == 0

    clear_result = goals.update(db, owner=OWNER, id=target.id, foil=False)
    assert clear_result.goal.foil is False
    assert _revision(db, target.id) == 0

    goals.update(db, owner=OWNER, id=target.id, title="SYN foil target changed")
    assert _revision(db, target.id) == 1


def test_all_migration_008_bookkeeping_fields_are_trigger_exclusions(
    db: psycopg.Connection,
) -> None:
    target = goals.create(conn=db, owner=OWNER, title="SYN trigger exclusions").goal
    db.execute(
        "UPDATE goals SET foil = true, carryover_ignored_until = %s, "
        "parked_from_vertical = 'year' WHERE id = %s",
        (date(2026, 8, 31), target.id),
    )
    assert _revision(db, target.id) == 0
