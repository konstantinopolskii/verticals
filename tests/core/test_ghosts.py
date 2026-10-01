"""R10 carry-over ghosts and the roll (docs/design-handoff S4.P1) against real Postgres.

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
import pytest

from verticals.core import board, due_ack, goals, vertical
from tests.conftest import maintenance_dsn
from tests.harness import stmt

OWNER = "SYN-ghost-owner"


def _create(conn: psycopg.Connection, title: str, anchor: date, scale: str = "week"):
    return goals.create(
        conn,
        owner=OWNER,
        title=title,
        vertical=scale,
        anchor_date=anchor,
    ).goal


def _week(result):
    return next(column for column in result.columns if column.vertical == "week")


def _week_bounds(today: date) -> tuple[date, date]:
    start = today - timedelta(days=today.isoweekday() - 1)
    return start, start + timedelta(days=6)


def test_overdue_undone_ghost_ignore_and_expired_ignore_return(db: psycopg.Connection) -> None:
    today = date.today()
    # A week's plan from last week stays in Week unless a month turned since (S4.P1.004): stand mid-month.
    month_start = vertical.descriptor("month").bounds_fn(today)[0]
    today = month_start + timedelta(days=14 + (2 - (month_start + timedelta(days=14)).weekday()) % 7)
    week_start, week_end = _week_bounds(today)
    last_week = today - timedelta(days=7)

    overdue = _create(db, "SYN overdue", last_week)
    done = _create(db, "SYN done overdue", last_week)
    goals.update(db, owner=OWNER, id=done.id, done=True)
    original_anchor = overdue.anchor_date

    current = board.board(db, owner=OWNER, date=today, today=today)
    assert overdue.id in {goal.id for goal in _week(current).goals}
    assert current.ghosts[overdue.id] == week_end
    assert done.id not in {goal.id for goal in _week(current).goals}

    # R10 revised: time travel carries no ghosts. On its own week the goal is a plain row
    # (its anchor lives there); one week further back it is nowhere at all.
    own_week = board.board(db, owner=OWNER, date=last_week, today=today)
    assert overdue.id in {goal.id for goal in _week(own_week).goals}
    assert overdue.id not in own_week.ghosts
    earlier = board.board(db, owner=OWNER, date=last_week - timedelta(days=7), today=today)
    assert overdue.id not in {goal.id for goal in _week(earlier).goals}
    future = board.board(db, owner=OWNER, date=today + timedelta(days=7), today=today)
    assert overdue.id not in {goal.id for goal in _week(future).goals}

    goals.update(
        db,
        owner=OWNER,
        id=overdue.id,
        carryover_ignored_until=week_end,
    )
    ignored = board.board(db, owner=OWNER, date=today, today=today)
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
    returned = board.board(db, owner=OWNER, date=today, today=today)
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


LADDER = tuple(vertical.descriptor(key) for key in vertical.ROLL_LADDER)
# A Wednesday in the middle of a month, a Monday and the first of a month (docs/design-handoff S4.P1.031, .032).
MIDMONTH = date(2026, 9, 16)
MONDAY = date(2026, 9, 28)
FIRST = date(2026, 10, 1)


def _rolled(own: str, anchor: date, today: date) -> str:
    """The roll walked forward turn by turn, the long way round from `board.py`'s thresholds: a missed plan stays in
    its scale until the next larger period turns after it arrived there, then falls one scale up (S4.P1.003-.007)."""
    keys = [h.key for h in LADDER]
    if own not in keys:
        return own
    level = keys.index(own)
    arrived = LADDER[level].bounds_fn(anchor)[1]
    while level + 1 < len(LADDER):
        turn = LADDER[level + 1].bounds_fn(arrived)[1] + timedelta(days=1)
        if turn > today:
            break
        level, arrived = level + 1, turn
    return keys[level]


def _locations(result, goal_id: str) -> list[str]:
    return [column.vertical for column in result.columns if any(g.id == goal_id for g in column.goals)]


def test_on_a_monday_last_weeks_day_and_week_plans_are_in_week(db) -> None:
    """S4.P1.031."""
    days = [_create(db, f"SYN day {n}", MONDAY - timedelta(days=n), "day") for n in range(1, 8)]
    week = _create(db, "SYN last week", MONDAY - timedelta(days=7), "week")
    result = board.board(db, owner=OWNER, date=MONDAY, today=MONDAY)
    for goal in [*days, week]:
        assert _locations(result, goal.id) == ["week"], goal.title
        assert result.ghosts[goal.id] == MONDAY + timedelta(days=6)


def test_on_the_first_of_a_month_the_weeks_carried_plans_fall_into_month(db) -> None:
    """S4.P1.032, .021: the weeks' plans fall into Month; a plan still in its week's days does not climb two at once."""
    weeks = [_create(db, f"SYN week {n}", FIRST - timedelta(days=7 * n + 3), "week") for n in (1, 2)]
    carried_day = _create(db, "SYN day carried in weeks", date(2026, 9, 22), "day")
    this_week_day = _create(db, "SYN day this week", date(2026, 9, 29), "day")
    straddling = _create(db, "SYN week across the turn", date(2026, 9, 28), "week")
    result = board.board(db, owner=OWNER, date=FIRST, today=FIRST)
    for goal in [*weeks, carried_day]:
        assert _locations(result, goal.id) == ["month"], goal.title
    assert _locations(result, this_week_day.id) == ["day"]
    assert _locations(result, straddling.id) == ["week"]
    assert straddling.id not in result.ghosts


def test_no_plan_climbs_after_one_missed_day(db) -> None:
    """S4.P1.034: a day's plan moves day to day until the week turns (S4.P1.003)."""
    friday = date(2026, 9, 25)
    plans = [_create(db, f"SYN missed {n}", friday - timedelta(days=n), "day") for n in (1, 2, 4)]
    result = board.board(db, owner=OWNER, date=friday, today=friday)
    for goal in plans:
        assert _locations(result, goal.id) == ["day"], goal.title
        assert result.ghosts[goal.id] == friday


@pytest.mark.parametrize("own", [h.key for h in LADDER])
def test_the_board_follows_the_roll_every_day_without_writing_the_goal(db, own: str) -> None:
    """S4.P1.002-.007, .021: day after day across month, quarter and year turns, each plan stands where the roll puts
    it, never climbs two scales in one day, and the goal itself is never written."""
    anchors = [date(2025, 11, 30), date(2026, 3, 31), date(2026, 6, 28), date(2026, 8, 31), date(2026, 9, 6)]
    plans = [(_create(db, f"SYN {own} {a}", a, own), a) for a in anchors]
    stored = {goal.id: goals.goal(db, owner=OWNER, id=goal.id).goal for goal, _ in plans}
    rank = {h.key: i for i, h in enumerate(vertical.VERTICALS)}
    last: dict[str, str] = {}
    today = date(2026, 9, 1)
    while today <= date(2027, 1, 12):
        result = board.board(db, owner=OWNER, date=today, today=today)
        for goal, anchor in plans:
            if anchor >= vertical.descriptor(own).bounds_fn(today)[0]:
                continue
            landing = _rolled(own, anchor, today)
            assert _locations(result, goal.id) == [landing], (goal.title, today)
            assert result.ghosts[goal.id] == vertical.descriptor(landing).bounds_fn(today)[1]
            assert rank[landing] - rank[last.get(goal.id, landing)] in (0, 1), (goal.title, today)
            last[goal.id] = landing
        today += timedelta(days=3)
    for goal, _ in plans:
        assert goals.goal(db, owner=OWNER, id=goal.id).goal == stored[goal.id]


def test_scales_past_the_ladder_move_on_in_their_own_column(db) -> None:
    """S4.P1.007: a year's plans stay in Year; so do the three years' in theirs; Life is never carried."""
    year = _create(db, "SYN last year", date(2023, 5, 1), "year")
    three = _create(db, "SYN three years ago", date(2021, 5, 1), "decade")
    life = _create(db, "SYN timeless value", date(2021, 5, 1), "life")
    result = board.board(db, owner=OWNER, date=MIDMONTH, today=MIDMONTH)
    assert _locations(result, year.id) == ["year"]
    assert _locations(result, three.id) == ["decade"]
    assert life.id not in result.ghosts


@pytest.mark.parametrize("own", [h.key for h in vertical.VERTICALS if h.bounds_fn(MIDMONTH) is not None])
def test_current_period_is_not_due_merely_because_anchor_is_before_today(db, own: str) -> None:
    start, end = vertical.descriptor(own).bounds_fn(MIDMONTH)
    current = _create(db, "SYN current own vertical", start, own)
    future = _create(db, "SYN future own vertical", end + timedelta(days=1), own)
    result = board.board(db, owner=OWNER, date=MIDMONTH, today=MIDMONTH)
    assert _locations(result, current.id) == [own]
    assert current.id not in result.ghosts
    assert future.id not in result.ghosts


def test_past_ignores_and_acknowledgements_still_hold(db) -> None:
    """S4.P1.027: the menu no longer writes them, but those already written keep the plan out of its group."""
    anchor = date(2026, 8, 3)
    goal = _create(db, "SYN rolled day", anchor, "day")
    result = board.board(db, owner=OWNER, date=MIDMONTH, today=MIDMONTH)
    assert _locations(result, goal.id) == ["month"]
    goals.update(db, owner=OWNER, id=goal.id, carryover_ignored_until=result.ghosts[goal.id])
    assert goal.id not in board.board(db, owner=OWNER, date=MIDMONTH, today=MIDMONTH).ghosts
    goals.update(db, owner=OWNER, id=goal.id, carryover_ignored_until=MIDMONTH - timedelta(days=1))
    assert _locations(board.board(db, owner=OWNER, date=MIDMONTH, today=MIDMONTH), goal.id) == ["month"]
    ack = due_ack.acknowledge(db, owner=OWNER, id=goal.id, verdict="overdue")
    assert (ack.vertical, ack.period_key) == (goal.vertical, goal.period_key)
    assert goal.id not in board.board(db, owner=OWNER, date=MIDMONTH, today=MIDMONTH).ghosts
    done = _create(db, "SYN completed rolled day", anchor, "day")
    goals.update(db, owner=OWNER, id=done.id, done=True)
    assert done.id not in board.board(db, owner=OWNER, date=MIDMONTH, today=MIDMONTH).ghosts


def test_only_the_landing_columns_live_gate_applies(db) -> None:
    """Browsing another day must not hide a plan whose landing Week is still the current week; its own day shows it
    as a plain row, and a later week shows it nowhere."""
    friday = date(2026, 9, 25)
    anchor = date(2026, 9, 15)
    goal = _create(db, "SYN day carried into the week", anchor, "day")
    other_day = board.board(db, owner=OWNER, date=friday - timedelta(days=1), today=friday)
    assert _locations(other_day, goal.id) == ["week"]
    own_day = board.board(db, owner=OWNER, date=anchor, today=friday)
    assert _locations(own_day, goal.id) == ["day"]

    from verticals.api.schemas import board_to_json
    from verticals.mcp.shapes import board_dict

    for result, column, ghost, until in ((other_day, "week", True, "2026-09-27"), (own_day, "day", False, None)):
        for serialized in (board_to_json(result), board_dict(result)):
            copy = next(g for c in serialized["columns"] if c["vertical"] == column for g in c["goals"] if g["id"] == goal.id)
            assert copy["ghost"] is ghost
            assert (None if copy["ghost_until"] is None else str(copy["ghost_until"])) == until

    next_week = board.board(db, owner=OWNER, date=friday + timedelta(days=7), today=friday)
    assert goal.id not in next_week.ghosts
    assert _locations(next_week, goal.id) == []
