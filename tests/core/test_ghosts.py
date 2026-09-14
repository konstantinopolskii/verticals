"""R10 carry-over ghosts and expiry against real Postgres.

R10 (revised, KK ruling 2026-08-16): a ghost exists only on the CURRENT period — the column
whose period contains wall-clock today. A time-traveled board shows a goal solely at its own
anchor. So every scenario here anchors its fixtures RELATIVE TO RUNTIME TODAY (previous ISO
week, current ISO week) and renders the board AT today — the one date ghosts can appear on.
The data is born fresh each run, so the calendar can never rot these tests (the F4 perf corpus
stays frozen for exactly the mirror-image reason: it only ever views frozen past dates, where
the revised rule guarantees zero ghosts)."""

from __future__ import annotations

from datetime import date, timedelta

import psycopg

from verticals.core import board, goals
from tests.conftest import maintenance_dsn
from tests.harness import stmt

OWNER = "SYN-ghost-owner"


def _create(conn: psycopg.Connection, title: str, anchor: date):
    return goals.create(
        conn,
        owner=OWNER,
        title=title,
        vertical="week",
        anchor_date=anchor,
    ).goal


def _week(result):
    return next(column for column in result.columns if column.vertical == "week")


def _week_bounds(today: date) -> tuple[date, date]:
    start = today - timedelta(days=today.isoweekday() - 1)
    return start, start + timedelta(days=6)


def test_overdue_undone_ghost_ignore_and_expired_ignore_return(db: psycopg.Connection) -> None:
    today = date.today()
    week_start, week_end = _week_bounds(today)
    last_week = today - timedelta(days=7)

    overdue = _create(db, "SYN overdue", last_week)
    done = _create(db, "SYN done overdue", last_week)
    goals.update(db, owner=OWNER, id=done.id, done=True)
    original_anchor = overdue.anchor_date

    current = board.board(db, owner=OWNER, date=today)
    assert overdue.id in {goal.id for goal in _week(current).goals}
    assert current.ghosts[overdue.id] == week_end
    assert done.id not in {goal.id for goal in _week(current).goals}

    # R10 revised: time travel carries no ghosts. On its own week the goal is a plain row
    # (its anchor lives there); one week further back it is nowhere at all.
    own_week = board.board(db, owner=OWNER, date=last_week)
    assert overdue.id in {goal.id for goal in _week(own_week).goals}
    assert overdue.id not in own_week.ghosts
    earlier = board.board(db, owner=OWNER, date=last_week - timedelta(days=7))
    assert overdue.id not in {goal.id for goal in _week(earlier).goals}
    future = board.board(db, owner=OWNER, date=today + timedelta(days=7))
    assert overdue.id not in {goal.id for goal in _week(future).goals}

    goals.update(
        db,
        owner=OWNER,
        id=overdue.id,
        carryover_ignored_until=week_end,
    )
    ignored = board.board(db, owner=OWNER, date=today)
    assert overdue.id not in {goal.id for goal in _week(ignored).goals}
    assert goals.goal(db, owner=OWNER, id=overdue.id).goal.done_at is None
    assert goals.goal(db, owner=OWNER, id=overdue.id).goal.anchor_date == original_anchor

    # The "returns next period" half of the old scenario, restated without a time machine:
    # an ignore that expired BEFORE the current period's start no longer suppresses — exactly
    # the state a live board wakes up to when the ignored week rolls over.
    goals.update(
        db,
        owner=OWNER,
        id=overdue.id,
        carryover_ignored_until=week_start - timedelta(days=1),
    )
    returned = board.board(db, owner=OWNER, date=today)
    assert overdue.id in {goal.id for goal in _week(returned).goals}
    assert returned.ghosts[overdue.id] == week_end


def test_ghost_board_read_stays_one_statement(db: psycopg.Connection) -> None:
    today = date.today()
    _create(db, "SYN counted overdue", today - timedelta(days=7))
    dsn = maintenance_dsn()
    dbname = stmt.current_dbname(db)
    stmt.reset(dsn, dbname)

    result = board.board(db, owner=OWNER, date=today)

    assert result.ghosts
    assert stmt.count(dsn, dbname) == 1
