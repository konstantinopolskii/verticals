"""The morning report, made by a rule (KK, 6 Oct 2026: "Morning report это просто один из таких автоматизированных
документов который генерится просто по утрам по правилам неким и идёт в инбокс"; round 5: "the morning report is a
simple task that should behave as others. It should be blue by default").

Once a day the app asks (`POST /api/morning`, after the morning hour in the owner's own clock); the first ask makes the
day's document, `reports/morning/<date>.md`, and the task "Morning report" in that day, linked to it. The document is
written from the board alone, so it is there with or without an agent: what was done since the last report, what was
written into the Inbox, what today holds and what the week holds, each row linked to its goal, with "Your comment" last
(the report contract of `.agents/skills/verticals-morning-report`). An agent may enrich it later; the rule never waits
for one. The task sits under the owner's blue value when there is exactly one, so it is blue as asked; with none it is
a plain task. A second ask on the same day returns what the first made.

IR-02: takes an open connection, never commits.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

import psycopg

from verticals.core import docs as docs_mod
from verticals.core import goals
from verticals.core import replan
from verticals.core import vertical

TITLE = "Morning report"
BLUE = "#278dea"
HEADER = "| Goal | Under | When | Your comment |\n| --- | --- | --- | --- |\n"
MONTHS = ("January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November",
          "December")


@dataclass(frozen=True)
class Made:
    task_id: str
    doc_id: str


def doc_path(day: date) -> str:
    return f"reports/morning/{day.isoformat()}.md"


def doc_title(day: date) -> str:
    return f"Morning report — {day.day} {MONTHS[day.month - 1]} {day.year}"


def _cell(text: str) -> str:
    """One line for a table cell: a pipe escaped, and square brackets made round, since the app's notes parser reads
    an escaped bracket inside a link's words as the end of the link."""
    line = " ".join((text or "").split()).replace("[", "(").replace("]", ")")
    return re.sub(r"([\\|])", r"\\\1", line)


def _row(goal_id: str, title: str, under: str | None, when: str) -> str:
    return f"| [{_cell(title)}](goal:{goal_id}) | {_cell(under or '')} | {_cell(when)} |  |\n"


def _short(d: date | datetime) -> str:
    return f"{d.strftime('%a')} {d.day} {MONTHS[d.month - 1][:3]}"


def run(conn: psycopg.Connection, *, owner: str, today: date) -> Made:
    path = doc_path(today)
    found = conn.execute(
        "SELECT id FROM docs WHERE owner = %(owner)s AND path = %(path)s", {"owner": owner, "path": path}
    ).fetchone()
    if found is not None:
        task = conn.execute(
            "SELECT g.goal_id FROM goal_doc_links g JOIN goals t ON t.owner = g.owner AND t.id = g.goal_id"
            " WHERE g.owner = %(owner)s AND g.doc_id = %(doc)s AND t.title = %(title)s ORDER BY t.created_at LIMIT 1",
            {"owner": owner, "doc": found[0], "title": TITLE},
        ).fetchone()
        if task is not None:
            return Made(task_id=task[0], doc_id=found[0])

    # Since the last report, or since yesterday's start for the first one.
    last = conn.execute(
        "SELECT max(created_at) FROM docs WHERE owner = %(owner)s AND path LIKE 'reports/morning/%%' AND path < %(path)s",
        {"owner": owner, "path": path},
    ).fetchone()[0]
    since = last or datetime.combine(today - timedelta(days=1), time.min).astimezone()

    done = conn.execute(
        "SELECT g.id, g.title, p.title FROM goals g LEFT JOIN goals p ON p.owner = g.owner AND p.id = g.parent_id"
        " WHERE g.owner = %(owner)s AND g.done_at >= %(since)s AND g.origin <> 'app' ORDER BY g.done_at DESC LIMIT 40",
        {"owner": owner, "since": since},
    ).fetchall()
    written = conn.execute(
        "SELECT g.id, g.title, p.title, g.created_at FROM goals g LEFT JOIN goals p ON p.owner = g.owner AND p.id = g.parent_id"
        " WHERE g.owner = %(owner)s AND g.vertical IS NULL AND g.done_at IS NULL AND g.created_at >= %(since)s"
        "   AND g.origin <> 'app' ORDER BY g.created_at DESC LIMIT 60",
        {"owner": owner, "since": since},
    ).fetchall()
    week_start, week_end = vertical.descriptor("week").bounds_fn(today)
    planned = conn.execute(
        "SELECT g.id, g.title, p.title, g.vertical::text, g.anchor_date FROM goals g"
        "  LEFT JOIN goals p ON p.owner = g.owner AND p.id = g.parent_id"
        " WHERE g.owner = %(owner)s AND g.done_at IS NULL AND g.origin <> 'app'"
        "   AND ((g.vertical = 'day' AND g.anchor_date = %(today)s)"
        "     OR (g.vertical = 'week' AND g.anchor_date BETWEEN %(ws)s AND %(we)s))"
        " ORDER BY g.vertical, g.position, g.id",
        {"owner": owner, "today": today, "ws": week_start, "we": week_end},
    ).fetchall()

    title = doc_title(today)
    lines = [f"# {title}", "",
             f"Made by the morning rule from the board, for {_short(today)}. Write in Your comment and press Go: "
             "the agent puts each comment on its goal and clears the cell.", ""]
    if done:
        lines += ["## What changed", ""] + [f"- Done: [{_cell(t)}](goal:{i})" + (f", under {_cell(u)}" if u else "")
                                            for i, t, u in done] + [""]
    if written:
        lines += ["## Inbox — decisions needed", "", HEADER.rstrip("\n")]
        lines += [_row(i, t, u, f"Written {_short(c)}").rstrip("\n") for i, t, u, c in written] + [""]
    today_rows = [r for r in planned if r[3] == "day"]
    week_rows = [r for r in planned if r[3] == "week"]
    if today_rows:
        lines += ["## Today", "", HEADER.rstrip("\n")]
        lines += [_row(i, t, u, "Today").rstrip("\n") for i, t, u, _, _ in today_rows] + [""]
    if week_rows:
        lines += ["## This week — keep in mind", "", HEADER.rstrip("\n")]
        lines += [_row(i, t, u, f"This week, from {_short(week_start)}").rstrip("\n") for i, t, u, _, _ in week_rows] + [""]
    carried = replan.open_task(conn, owner=owner)
    if carried is not None and carried.rows:
        lines += ["## Carried over", "", f"{carried.rows} plans wait in [{_cell(carried.doc_title)}](doc:{carried.doc_path}) to be sorted.", ""]
    if not (done or written or today_rows or week_rows):
        lines += ["Nothing new on the board since the last report.", ""]
    body = "\n".join(lines).rstrip("\n") + "\n"

    if found is None:
        doc_id = docs_mod.create(conn, owner=owner, path=path, title=title, body=body).doc.id
    else:
        doc_id = found[0]
    blue = conn.execute(
        "SELECT id FROM goals WHERE owner = %(owner)s AND parent_id IS NULL AND vertical = 'life' AND color = %(blue)s",
        {"owner": owner, "blue": BLUE},
    ).fetchall()
    task = goals.create(
        conn, owner=owner, title=TITLE, body=f"[{title}](doc:{path})", vertical="day", anchor_date=today,
        parent_id=blue[0][0] if len(blue) == 1 else None, origin="app",
    ).goal
    return Made(task_id=task.id, doc_id=doc_id)
