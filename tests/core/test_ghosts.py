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


BOUNDED = tuple(h for h in vertical.VERTICALS if h.bounds_fn(date.today()) is not None)


def _previous_start(scale: str, today: date) -> date:
    descriptor = vertical.descriptor(scale)
    current_start, _ = descriptor.bounds_fn(today)
    return descriptor.bounds_fn(current_start - timedelta(days=1))[0]


def _locations(result, goal_id: str) -> list[str]:
    return [column.vertical for column in result.columns if any(g.id == goal_id for g in column.goals)]


def _expected_landing(own: str, anchor: date, today: date):
    # Adjacent calendar thresholds can coincide; the first eligible scale wins that tie.
    return next((h for h in BOUNDED[vertical.rank(own):] if anchor >= _previous_start(h.key, today)), BOUNDED[-1])


def _pin_today(monkeypatch: pytest.MonkeyPatch, value: date) -> date:
    class ClockDate(date):
        @classmethod
        def today(cls):
            return cls.fromordinal(value.toordinal())

    monkeypatch.setattr(board, "_date", ClockDate)
    return ClockDate.today()


@pytest.mark.parametrize("own", [h.key for h in BOUNDED])
def test_carryover_ages_up_from_own_vertical_without_writing_goal(db, own: str) -> None:
    today = date.today()
    for landing in BOUNDED[vertical.rank(own):]:
        anchor = _previous_start(landing.key, today)
        goal = _create(db, f"SYN {own} lands {landing.key}", anchor, own)
        before = goals.goal(db, owner=OWNER, id=goal.id).goal

        result = board.board(db, owner=OWNER, date=today)

        expected = _expected_landing(own, anchor, today)
        assert _locations(result, goal.id) == [expected.key]
        assert result.ghosts[goal.id] == expected.bounds_fn(today)[1]
        shown = next(g for c in result.columns for g in c.goals if g.id == goal.id)
        assert (shown.vertical, shown.anchor_date, shown.period_key) == (
            own, before.anchor_date, before.period_key,
        )
        assert goals.goal(db, owner=OWNER, id=goal.id).goal == before

    # Nothing ages into Life, even before the previous complete three-year period.
    ancient = _create(db, "SYN oldest bounded fallback", _previous_start(BOUNDED[-1].key, today) - timedelta(days=1), own)
    assert _locations(board.board(db, owner=OWNER, date=today), ancient.id) == [BOUNDED[-1].key]


@pytest.mark.parametrize("own", [h.key for h in BOUNDED])
def test_current_period_is_not_due_merely_because_anchor_is_before_today(db, own: str) -> None:
    today = date.today()
    start, end = vertical.descriptor(own).bounds_fn(today)
    current = _create(db, "SYN current own vertical", start, own)
    future = _create(db, "SYN future own vertical", end + timedelta(days=1), own)
    result = board.board(db, owner=OWNER, date=today)
    assert _locations(result, current.id) == [own]
    assert current.id not in result.ghosts
    assert future.id not in result.ghosts


@pytest.mark.parametrize("boundary", ["month-start", "month-end", "quarter-start", "quarter-end"])
def test_calendar_edges_use_previous_calendar_periods(db, monkeypatch, boundary: str) -> None:
    scale, edge = boundary.split("-")
    bounds = vertical.descriptor(scale).bounds_fn(date.today())
    today = _pin_today(monkeypatch, bounds[0 if edge == "start" else 1])
    for landing in BOUNDED[:-1]:
        threshold = _previous_start(landing.key, today)
        exact = _create(db, "SYN exact calendar threshold", threshold, "day")
        older = _create(db, "SYN one day before threshold", threshold - timedelta(days=1), "day")
        result = board.board(db, owner=OWNER, date=today)
        assert _locations(result, exact.id) == [_expected_landing("day", threshold, today).key]
        # Calendar boundaries, including ISO-week/year edges, are inclusive at the start.
        assert _locations(result, older.id) == [_expected_landing("day", older.anchor_date, today).key]


def test_named_day_and_week_ages_use_runtime_calendar(db, monkeypatch) -> None:
    month_start = vertical.descriptor("month").bounds_fn(date.today())[0]
    midmonth = month_start + timedelta(days=14)
    # A runtime-relative Saturday makes all named "earlier this week/month" cases possible.
    today = _pin_today(monkeypatch, midmonth + timedelta(days=(5 - midmonth.weekday()) % 7))
    week_start = vertical.descriptor("week").bounds_fn(today)[0]
    last_week = week_start - timedelta(days=7)
    cases = [
        ("yesterday", "day", today - timedelta(days=1), "day"),
        ("earlier this week", "day", week_start, "week"),
        ("last week", "day", last_week, "week"),
        ("earlier this month", "day", month_start, "month"),
        ("last month", "day", _previous_start("month", today), "month"),
        ("Week last week", "week", last_week, "week"),
        ("Week two weeks old", "week", last_week - timedelta(days=7), "month"),
    ]
    created = [(_create(db, f"SYN {name}", anchor, own), target) for name, own, anchor, target in cases]
    result = board.board(db, owner=OWNER, date=today)
    for goal, target in created:
        assert _locations(result, goal.id) == [target], goal.title


def test_promoted_ignore_expires_by_today_and_ack_keeps_original_key(db) -> None:
    today = date.today()
    anchor = _previous_start("month", today)
    goal = _create(db, "SYN promoted day", anchor, "day")
    result = board.board(db, owner=OWNER, date=today)
    assert _locations(result, goal.id) == ["month"]
    until = result.ghosts[goal.id]
    goals.update(db, owner=OWNER, id=goal.id, carryover_ignored_until=until)
    assert goal.id not in board.board(db, owner=OWNER, date=today).ghosts
    goals.update(db, owner=OWNER, id=goal.id, carryover_ignored_until=today)
    assert goal.id not in board.board(db, owner=OWNER, date=today).ghosts
    goals.update(db, owner=OWNER, id=goal.id, carryover_ignored_until=today - timedelta(days=1))
    assert _locations(board.board(db, owner=OWNER, date=today), goal.id) == ["month"]
    ack = due_ack.acknowledge(db, owner=OWNER, id=goal.id, verdict="overdue")
    assert (ack.vertical, ack.period_key) == (goal.vertical, goal.period_key)
    assert goal.id not in board.board(db, owner=OWNER, date=today).ghosts
    done = _create(db, "SYN completed promoted day", anchor, "day")
    goals.update(db, owner=OWNER, id=done.id, done=True)
    assert done.id not in board.board(db, owner=OWNER, date=today).ghosts
    life = _create(db, "SYN timeless value", anchor, "life")
    assert life.id not in board.board(db, owner=OWNER, date=today).ghosts


def test_only_landing_live_gate_applies_and_historical_copy_is_not_a_ghost(db, monkeypatch) -> None:
    # Use the end of the runtime month so its first day necessarily ages past the Week window.
    start, end = vertical.descriptor("month").bounds_fn(date.today())
    today = _pin_today(monkeypatch, end)
    goal = _create(db, "SYN historical day plus current landing month", start, "day")
    requested = type(today).fromordinal(start.toordinal())
    historical = board.board(db, owner=OWNER, date=requested)
    assert _locations(historical, goal.id) == ["day", "month"]

    from verticals.api.schemas import board_to_json
    from verticals.mcp.shapes import board_dict

    for serialized in (board_to_json(historical), board_dict(historical)):
        copies = {column["vertical"]: next((g for g in column["goals"] if g["id"] == goal.id), None) for column in serialized["columns"]}
        assert copies["day"]["ghost"] is False
        assert copies["day"]["ghost_until"] is None
        assert copies["month"]["ghost"] is True
        assert str(copies["month"]["ghost_until"]) == str(end)

    other_day = board.board(db, owner=OWNER, date=requested + timedelta(days=1))
    assert _locations(other_day, goal.id) == ["month"]
    # A non-live landing column suppresses the ghost; it does not promote it again to Year.
    next_month = board.board(db, owner=OWNER, date=today + timedelta(days=1))
    assert goal.id not in next_month.ghosts
    assert _locations(next_month, goal.id) == []
