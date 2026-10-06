"""The Documents desk (Inbox and Documents redesign, rounds 2–7): stacks by goal under each value, a value never a stack
of its own, a big branch split into its sub-goals, every document in one stack only, and the documents no goal holds
apart, newest first."""

from __future__ import annotations

from datetime import date

import psycopg

from verticals.core import docs, docs_desk, goals

OWNER = "SYN-desk-owner"
DAY = date(2026, 10, 7)


def _doc(conn: psycopg.Connection, path: str) -> str:
    return docs.create(conn, owner=OWNER, path=path, title=path, body=f"# {path}\n\nText.").doc.id


def _link(conn: psycopg.Connection, goal: str, *paths: str) -> None:
    goals.update(conn, owner=OWNER, id=goal, body="\n".join(f"[{p}](doc:{p})" for p in paths))


def test_stacks_by_goal_under_values_and_no_goal_apart(db: psycopg.Connection) -> None:
    value = goals.create(db, owner=OWNER, title="SYN value", vertical="life", anchor_date=DAY, color="#278dea").goal.id
    year = goals.create(db, owner=OWNER, title="SYN year", vertical="year", anchor_date=DAY, parent_id=value).goal.id
    quarter = goals.create(db, owner=OWNER, title="SYN quarter", vertical="quarter", anchor_date=DAY, parent_id=year).goal.id
    for path in ("a.md", "b.md", "loose-1.md", "loose-2.md"):
        _doc(db, path)
    _link(db, quarter, "a.md")
    _link(db, year, "b.md")

    desk = docs_desk.desk(db, owner=OWNER)
    assert {desk.docs[d].path for d in desk.no_goal} == {"loose-1.md", "loose-2.md"}
    (group,) = desk.values
    assert (group.id, group.title, group.color) == (value, "SYN value", "#278dea")
    # The value is the group's heading; its year goal holds both documents, the quarter's included.
    assert [(s.goal_title, sorted(desk.docs[d].path for d in s.docs)) for s in group.stacks] == [("SYN year", ["a.md", "b.md"])]


def test_a_big_branch_splits_into_its_sub_goals(db: psycopg.Connection) -> None:
    value = goals.create(db, owner=OWNER, title="SYN value", vertical="life", anchor_date=DAY).goal.id
    year = goals.create(db, owner=OWNER, title="SYN year", vertical="year", anchor_date=DAY, parent_id=value).goal.id
    left = goals.create(db, owner=OWNER, title="SYN left", vertical="quarter", anchor_date=DAY, parent_id=year).goal.id
    right = goals.create(db, owner=OWNER, title="SYN right", vertical="quarter", anchor_date=DAY, parent_id=year).goal.id
    many = [f"l{n}.md" for n in range(docs_desk.CAP)] + ["r.md"]
    for path in many:
        _doc(db, path)
    _link(db, left, *many[:-1])
    _link(db, right, "r.md")
    (group,) = docs_desk.desk(db, owner=OWNER).values
    assert [(s.goal_title, len(s.docs)) for s in group.stacks] == [("SYN left", docs_desk.CAP), ("SYN right", 1)]
