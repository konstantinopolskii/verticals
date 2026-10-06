"""The morning report made by a rule (Inbox and Documents redesign, round 5): once a day a document written from the
board and the task "Morning report" in that day, linked to it, under the blue value when there is exactly one."""

from __future__ import annotations

from datetime import date

import psycopg

from verticals.core import docs, goals, morning

OWNER = "SYN-morning-owner"
DAY = date(2026, 10, 7)


def test_the_first_ask_makes_the_report_and_its_task_a_second_returns_them(db: psycopg.Connection) -> None:
    blue = goals.create(db, owner=OWNER, title="SYN organised life", vertical="life", anchor_date=DAY, color="#278dea").goal.id
    today = goals.create(db, owner=OWNER, title="SYN call the bank", vertical="day", anchor_date=DAY, parent_id=blue).goal.id
    thought = goals.create(db, owner=OWNER, title="SYN a thought | with a bar [and brackets]").goal.id

    made = morning.run(db, owner=OWNER, today=DAY)
    task = goals.goal(db, owner=OWNER, id=made.task_id).goal
    assert (task.title, task.vertical, task.anchor_date, task.parent_id, task.origin) == ("Morning report", "day", DAY, blue, "app")
    assert task.body == "[Morning report — 7 October 2026](doc:reports/morning/2026-10-07.md)"
    doc = docs.get(db, owner=OWNER, id=made.doc_id)
    assert (doc.path, doc.title) == ("reports/morning/2026-10-07.md", "Morning report — 7 October 2026")
    assert "## Inbox — decisions needed" in doc.body and "## Today" in doc.body
    assert f"| [SYN a thought \\| with a bar (and brackets)](goal:{thought}) |" in doc.body
    assert f"| [SYN call the bank](goal:{today}) | SYN organised life | Today |  |" in doc.body
    assert f"(goal:{made.task_id})" not in doc.body

    again = morning.run(db, owner=OWNER, today=DAY)
    assert again == made


def test_with_no_blue_value_the_task_stands_on_its_own(db: psycopg.Connection) -> None:
    made = morning.run(db, owner=OWNER, today=DAY)
    assert goals.goal(db, owner=OWNER, id=made.task_id).goal.parent_id is None
    assert "Nothing new on the board since the last report." in docs.get(db, owner=OWNER, id=made.doc_id).body
