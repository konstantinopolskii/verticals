"""The carry-over task (docs/design-handoff S4.P1.008-.012, .017, .023, .029, .033, .035) against real Postgres."""

from __future__ import annotations

from datetime import date, timedelta

import psycopg

from verticals.core import board, goals, replan

OWNER = "SYN-replan-owner"
MONDAY = date(2026, 9, 28)


def _plan(conn: psycopg.Connection, title: str, anchor: date, scale: str = "day") -> str:
    return goals.create(conn, owner=OWNER, title=title, vertical=scale, anchor_date=anchor).goal.id


def _task(conn: psycopg.Connection, task_id: str):
    return goals.goal(conn, owner=OWNER, id=task_id).goal


def _rows(body: str) -> list[str]:
    return [line for line in body.splitlines() if line.startswith("| [")]


def test_nothing_carried_makes_no_task(db: psycopg.Connection) -> None:
    """S4.P1.022."""
    _plan(db, "SYN today", MONDAY)
    assert replan.run(db, owner=OWNER, today=MONDAY) is None
    inbox = next(c for c in board.board(db, owner=OWNER, date=MONDAY, today=MONDAY).columns if c.vertical is None)
    assert not inbox.goals


def test_the_first_run_holds_every_carried_plan_in_one_inbox_task(db: psycopg.Connection) -> None:
    """S4.P1.008-.012, .015, .029: a usual Inbox task by the app, a plain table of links, newest plan first."""
    friday = _plan(db, "SYN Friday call", date(2026, 9, 25))
    week = _plan(db, "SYN week | with a bar", date(2026, 9, 21), "week")
    august = _plan(db, "SYN August plan", date(2026, 8, 1), "month")
    done = _plan(db, "SYN done plan", date(2026, 9, 24))
    goals.update(db, owner=OWNER, id=done, done=True)

    task_id = replan.run(db, owner=OWNER, today=MONDAY)
    assert task_id is not None
    task = _task(db, task_id)
    assert (task.title, task.vertical, task.parent_id, task.origin) == ("Replan carried-over plans", None, None, "app")
    assert task.body.startswith("| Goal | Summary | Next step | Your comment |\n| --- | --- | --- | --- |\n")
    assert _rows(task.body) == [
        f"| [SYN Friday call](goal:{friday}) |  | Planned Fri 25 Sep |  |",
        f"| [SYN week \\| with a bar](goal:{week}) |  | Planned 21–27 Sep |  |",
        f"| [SYN August plan](goal:{august}) |  | Planned August |  |",
    ]
    inbox = next(c for c in board.board(db, owner=OWNER, date=MONDAY, today=MONDAY).columns if c.vertical is None)
    assert [g.id for g in inbox.goals] == [task_id]


def test_a_second_run_on_one_day_writes_nothing(db: psycopg.Connection) -> None:
    """S4.P1.029."""
    _plan(db, "SYN missed", MONDAY - timedelta(days=1))
    task_id = replan.run(db, owner=OWNER, today=MONDAY)
    before = _task(db, task_id)
    _plan(db, "SYN made later, already missed", MONDAY - timedelta(days=3))
    assert replan.run(db, owner=OWNER, today=MONDAY) == task_id
    assert _task(db, task_id) == before


def test_each_day_adds_only_the_newly_carried_to_the_open_task(db: psycopg.Connection) -> None:
    """S4.P1.011, .035, S4.P4.022: the next day's carry-over joins the table under the rows already there, the
    rest of the notes kept byte for byte."""
    first = _plan(db, "SYN Sunday", MONDAY - timedelta(days=1))
    task_id = replan.run(db, owner=OWNER, today=MONDAY)
    edited = _task(db, task_id).body.replace("|  | Planned Sun 27 Sep |  |", "| A summary | Planned Sun 27 Sep | Next week |")
    goals.update(db, owner=OWNER, id=task_id, body="Sort these by Friday.\n\n" + edited + "\nA note under the table.\n")
    second = _plan(db, "SYN Monday", MONDAY)
    tuesday = MONDAY + timedelta(days=1)
    assert replan.run(db, owner=OWNER, today=tuesday) == task_id
    body = _task(db, task_id).body
    assert _rows(body) == [
        f"| [SYN Sunday](goal:{first}) | A summary | Planned Sun 27 Sep | Next week |",
        f"| [SYN Monday](goal:{second}) |  | Planned Mon 28 Sep |  |",
    ]
    assert body.startswith("Sort these by Friday.\n\n| Goal |")
    assert body.endswith("|  |\n\nA note under the table.\n")


def test_a_closed_task_is_never_reopened_the_next_carry_over_makes_a_new_one(db: psycopg.Connection) -> None:
    """S4.P1.011, S4.P4.031."""
    _plan(db, "SYN Sunday", MONDAY - timedelta(days=1))
    old = replan.run(db, owner=OWNER, today=MONDAY)
    goals.update(db, owner=OWNER, id=old, done=True)
    later = _plan(db, "SYN Monday", MONDAY)
    new = replan.run(db, owner=OWNER, today=MONDAY + timedelta(days=1))
    assert new not in (None, old)
    assert _rows(_task(db, new).body) == [f"| [SYN Monday](goal:{later}) |  | Planned Mon 28 Sep |  |"]
    assert _task(db, old).done_at is not None


def test_days_away_gather_every_turn_into_one_task(db: psycopg.Connection) -> None:
    """S4.P1.023: the app closed for two weeks, one task holds everything that carried over meanwhile."""
    _plan(db, "SYN before", MONDAY - timedelta(days=1))
    task_id = replan.run(db, owner=OWNER, today=MONDAY)
    missed = [_plan(db, f"SYN away {n}", MONDAY + timedelta(days=n)) for n in range(0, 14, 3)]
    week = _plan(db, "SYN week away", MONDAY + timedelta(days=7), "week")
    back = MONDAY + timedelta(days=15)
    assert replan.run(db, owner=OWNER, today=back) == task_id
    listed = _task(db, task_id).body
    for plan in [*missed, week]:
        assert f"(goal:{plan})" in listed
    assert len(_rows(listed)) == 1 + len(missed) + 1
