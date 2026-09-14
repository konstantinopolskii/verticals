"""Due acknowledgments (migration 011): verdicts on carry-over ghosts against real Postgres.

The refusal predicate in `core.due_ack.acknowledge` measures dueness against the REAL current
date (the same clock the live board uses), so every "is ghosting" fixture here anchors far in
the past (2020) and every "not overdue" fixture anchors inside the real current period.
Board reads still pin an explicit date where the assertion is about the ghost branch itself.
"""

from __future__ import annotations

from datetime import date

import psycopg
import pytest

from verticals.core import board, due_ack, goals, moves
from verticals.core.errors import NotFound, ValidationError
from verticals.core.vertical import descriptor

OWNER = "SYN-dueack-owner"
PAST_ANCHOR = date(2020, 1, 6)


def _create(conn: psycopg.Connection, title: str, anchor: date | None, vertical: str | None = "week"):
    return goals.create(
        conn,
        owner=OWNER,
        title=title,
        vertical=vertical,
        anchor_date=anchor,
    ).goal


def _week_ids(result) -> set[str]:
    column = next(column for column in result.columns if column.vertical == "week")
    return {goal.id for goal in column.goals}


def _board_today(conn: psycopg.Connection):
    return board.board(conn, owner=OWNER, date=date.today())


def test_overdue_verdict_removes_ghost_and_lands_in_history(db: psycopg.Connection) -> None:
    goal = _create(db, "SYN long overdue", PAST_ANCHOR)
    before = _board_today(db)
    assert goal.id in _week_ids(before)
    assert goal.id in before.ghosts

    ack = due_ack.acknowledge(db, owner=OWNER, id=goal.id, verdict="overdue")
    assert ack.goal_id == goal.id
    assert ack.verdict == "overdue"
    assert ack.vertical == "week"
    assert ack.period_key == goal.period_key
    assert ack.note is None

    after = _board_today(db)
    assert goal.id not in _week_ids(after)
    assert goal.id not in after.ghosts
    # The goal itself is untouched: still open, still anchored where it was.
    stored = goals.goal(db, owner=OWNER, id=goal.id).goal
    assert stored.done_at is None
    assert stored.anchor_date == PAST_ANCHOR

    rows = due_ack.history(db, owner=OWNER, id=goal.id)
    assert [row.verdict for row in rows] == ["overdue"]


def test_done_on_time_completes_goal_and_records_row(db: psycopg.Connection) -> None:
    goal = _create(db, "SYN done but unmarked", PAST_ANCHOR)

    ack = due_ack.acknowledge(
        db, owner=OWNER, id=goal.id, verdict="done_on_time", note="  finished in January  "
    )
    assert ack.verdict == "done_on_time"
    assert ack.note == "finished in January"

    stored = goals.goal(db, owner=OWNER, id=goal.id).goal
    assert stored.done_at is not None

    after = _board_today(db)
    assert goal.id not in after.ghosts

    rows = due_ack.history(db, owner=OWNER, id=goal.id)
    assert len(rows) == 1
    assert rows[0].verdict == "done_on_time"


def test_replay_is_idempotent_first_verdict_wins(db: psycopg.Connection) -> None:
    goal = _create(db, "SYN acked twice", PAST_ANCHOR)
    first = due_ack.acknowledge(db, owner=OWNER, id=goal.id, verdict="overdue")

    # Same verdict replay returns the stored row.
    replay = due_ack.acknowledge(db, owner=OWNER, id=goal.id, verdict="overdue")
    assert replay == first

    # A DIFFERENT verdict for the same missed period is also a replay: the stored verdict
    # wins and the completion side effect must NOT fire.
    conflicting = due_ack.acknowledge(db, owner=OWNER, id=goal.id, verdict="done_on_time")
    assert conflicting == first
    assert goals.goal(db, owner=OWNER, id=goal.id).goal.done_at is None
    assert len(due_ack.history(db, owner=OWNER, id=goal.id)) == 1


def test_done_on_time_replay_returns_stored_row(db: psycopg.Connection) -> None:
    goal = _create(db, "SYN done replay", PAST_ANCHOR)
    first = due_ack.acknowledge(db, owner=OWNER, id=goal.id, verdict="done_on_time")
    # Without the replay guard this would trip the "already completed" refusal.
    replay = due_ack.acknowledge(db, owner=OWNER, id=goal.id, verdict="done_on_time")
    assert replay == first


def test_not_overdue_refused(db: psycopg.Connection) -> None:
    current_week_start = descriptor("week").bounds_fn(date.today())[0]
    goal = _create(db, "SYN current week", current_week_start)
    with pytest.raises(ValidationError, match="not overdue"):
        due_ack.acknowledge(db, owner=OWNER, id=goal.id, verdict="overdue")


def test_completed_goal_refused(db: psycopg.Connection) -> None:
    goal = _create(db, "SYN already done", PAST_ANCHOR)
    goals.update(db, owner=OWNER, id=goal.id, done=True)
    with pytest.raises(ValidationError, match="already completed"):
        due_ack.acknowledge(db, owner=OWNER, id=goal.id, verdict="overdue")


def test_parked_goal_refused(db: psycopg.Connection) -> None:
    goal = _create(db, "SYN parked", PAST_ANCHOR)
    moves.park(db, owner=OWNER, id=goal.id)
    with pytest.raises(ValidationError, match="parked"):
        due_ack.acknowledge(db, owner=OWNER, id=goal.id, verdict="overdue")


def test_life_goal_refused(db: psycopg.Connection) -> None:
    goal = _create(db, "SYN life value", PAST_ANCHOR, vertical="life")
    with pytest.raises(ValidationError, match="never due"):
        due_ack.acknowledge(db, owner=OWNER, id=goal.id, verdict="overdue")


def test_bad_verdict_and_unknown_goal(db: psycopg.Connection) -> None:
    goal = _create(db, "SYN verdict guard", PAST_ANCHOR)
    with pytest.raises(ValidationError, match="verdict"):
        due_ack.acknowledge(db, owner=OWNER, id=goal.id, verdict="maybe")
    with pytest.raises(NotFound):
        due_ack.acknowledge(db, owner=OWNER, id="SYNMISSIN", verdict="overdue")
    with pytest.raises(NotFound):
        due_ack.history(db, owner=OWNER, id="SYNMISSIN")


def test_history_owner_scoped(db: psycopg.Connection) -> None:
    goal = _create(db, "SYN foreign read", PAST_ANCHOR)
    due_ack.acknowledge(db, owner=OWNER, id=goal.id, verdict="overdue")
    with pytest.raises(NotFound):
        due_ack.history(db, owner="SYN-other-owner", id=goal.id)


def test_reschedule_and_miss_again_ghosts_again(db: psycopg.Connection) -> None:
    goal = _create(db, "SYN misses twice", PAST_ANCHOR)
    due_ack.acknowledge(db, owner=OWNER, id=goal.id, verdict="overdue")
    assert goal.id not in _board_today(db).ghosts

    # New period, missed again: a NEW dueness, so it ghosts again and a second
    # acknowledgment lands as a second history row.
    moves.schedule(db, owner=OWNER, id=goal.id, vertical="week", anchor_date=date(2021, 3, 1))
    again = _board_today(db)
    assert goal.id in again.ghosts

    due_ack.acknowledge(db, owner=OWNER, id=goal.id, verdict="overdue")
    assert goal.id not in _board_today(db).ghosts
    assert len(due_ack.history(db, owner=OWNER, id=goal.id)) == 2
