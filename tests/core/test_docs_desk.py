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


def test_the_agents_memory_is_a_group_of_its_own_and_in_no_stack(db: psycopg.Connection) -> None:
    """docs/design/agent-memory.md: the memory documents are their own group at the end of the desk, even when a goal links one."""
    goal = goals.create(db, owner=OWNER, title="SYN goal", vertical="year", anchor_date=DAY).goal.id
    for path in ("memory/morning-report.md", "memory/AGENTS.md", "memories.md"):
        _doc(db, path)
    _link(db, goal, "memory/AGENTS.md")
    desk = docs_desk.desk(db, owner=OWNER)
    assert [desk.docs[d].path for d in desk.memory] == ["memory/AGENTS.md", "memory/morning-report.md"]
    assert [desk.docs[d].path for d in desk.no_goal] == ["memories.md"] and not desk.values


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


# A picture is a data URL inside the body (a report's screenshots): cut at a fixed length it would print as base64 on the
# page a document chip draws (docs/design/bug-reports.md). The preview is made without it. Sample bytes only.
PNG = "iVBORw0KGgo" + "AAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==" * 40
JPG = "/9j/4AAQSkZJRgABAQAAAQABAAD/" + "2wBDAAMCAgICAgMCAgIDAwMDBAYEBAQEBAgGBgUGCQgKCgkICQkKDA8MCgsOCwkJDRENDg8QEBEQCgwSExIQEw8QEBD" * 30


def _desk_excerpt(conn: psycopg.Connection, body: str) -> str:
    created = docs.create(conn, owner=OWNER, path="reports/bugs/2026-10-12-120000.md", title="Report", body=body).doc
    return docs_desk.desk(conn, owner=OWNER).docs[created.id].excerpt


def test_the_preview_of_a_report_has_its_words_and_no_picture(db: psycopg.Connection) -> None:
    body = (f"I dragged the card to Friday and it jumped back\n\n![Picture 1](data:image/jpeg;base64,{JPG})\n"
            f"![Picture 2](data:image/png;base64,{PNG})\n\nVerticals 0.4, macOS 27 (arm64)\n\n## App log\n`app: up`")
    assert len(body) > 4000, "the pictures push the rest of the report far past the preview's length"
    excerpt = _desk_excerpt(db, body)
    assert excerpt.startswith("I dragged the card to Friday and it jumped back")
    assert "Verticals 0.4, macOS 27 (arm64)" in excerpt and "## App log" in excerpt, "the words after the pictures come into view"
    assert "data:image" not in excerpt and "base64" not in excerpt and "![" not in excerpt
    assert len(excerpt) <= docs_desk.EXCERPT


def test_a_picture_with_a_long_alt_text_does_not_dangle_at_the_end_of_the_preview(db: psycopg.Connection) -> None:
    words = "Words. " * 210
    alt = "a screenshot of the board " * 8
    excerpt = _desk_excerpt(db, f"{words}![{alt}](data:image/png;base64,{PNG})\n\nAfter.")
    assert "![" not in excerpt and "data:image" not in excerpt and excerpt.rstrip().endswith("After.")


def test_a_body_without_a_picture_is_its_own_prefix_and_other_images_stay(db: psycopg.Connection) -> None:
    plain = "# Title\n\n" + "Text. " * 500
    assert _desk_excerpt(db, plain) == plain[:docs_desk.EXCERPT]
    web = "A [link](https://example.com) and ![a web picture](https://example.com/a.png) in it."
    other = docs.create(db, owner=OWNER, path="web.md", title="Web", body=web).doc
    assert docs_desk.desk(db, owner=OWNER).docs[other.id].excerpt == web, "only a data URL is left out, not every image"
