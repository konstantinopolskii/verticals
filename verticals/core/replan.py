"""The task that holds the plans carried over (docs/design-handoff S4.P1.008–.012, .017, .023, .029), as a task in this
week with its document (Inbox and Documents redesign, round 5; KK 7 Oct 2026: "okay reapln do best" — the same task
and page as the morning report).

Once a day, the plans whose own period ended since the last run join the open "Replan carried-over plans" task as rows
of its document's table, or make a new task and document when none is open. The task is a usual goal written by the app
(`origin = 'app'`), never by an agent, planned for the week it is in: when the week turns and it is still open, it moves
into the new week, so it never carries itself. Its document holds a plain markdown table of links to the plans; the task's
own notes link the document. A task from before the redesign, in the Inbox with the table in its notes, becomes the same
on its next run: the table moves into a new document, word for word. A second run on one day does nothing, and a run
after the app was closed for weeks gathers every turn that passed into one task.

IR-02: takes an open connection, never commits.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

import psycopg

from verticals.core import docs as docs_mod
from verticals.core import goals
from verticals.core import moves
from verticals.core import vertical

TITLE = "Replan carried-over plans"
# In the notes editor's own spelling (web `lib/bodyMarkdown.ts`), so editing a cell keeps every other byte (S4.P4.025).
HEADER = "| Goal | Summary | Next step | Your comment |\n| --- | --- | --- | --- |\n"
_LINKED = re.compile(r"\(goal:([A-Za-z0-9_-]+)\)")
MONTHS = ("January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November",
          "December")


@dataclass(frozen=True)
class OpenTask:
    task_id: str
    vertical: str | None
    anchor_date: date | None
    task_body: str
    doc_id: str | None
    doc_path: str | None
    doc_title: str | None
    doc_body: str
    doc_revision: int
    rows: int


def doc_path(day: date) -> str:
    return f"replan/{day.isoformat()}.md"


def doc_title(day: date) -> str:
    return f"Replan — {day.day} {MONTHS[day.month - 1]} {day.year}"


def open_task(conn: psycopg.Connection, *, owner: str) -> OpenTask | None:
    """The open task and its document (the first `replan/` one it links), or None."""
    task = conn.execute(
        "SELECT id, vertical::text, anchor_date, body FROM goals WHERE owner = %(owner)s AND origin = 'app'"
        "   AND title = %(title)s AND done_at IS NULL ORDER BY created_at DESC LIMIT 1",
        {"owner": owner, "title": TITLE},
    ).fetchone()
    if task is None:
        return None
    doc = conn.execute(
        "SELECT d.id, d.path, d.title, d.body, d.revision FROM goal_doc_links l JOIN docs d ON d.owner = l.owner AND d.id = l.doc_id"
        " WHERE l.owner = %(owner)s AND l.goal_id = %(task)s AND d.path LIKE 'replan/%%' ORDER BY d.created_at DESC LIMIT 1",
        {"owner": owner, "task": task[0]},
    ).fetchone()
    table = doc[3] if doc else (task[3] or "")
    return OpenTask(
        task_id=task[0], vertical=task[1], anchor_date=task[2], task_body=task[3] or "",
        doc_id=doc[0] if doc else None, doc_path=doc[1] if doc else None, doc_title=doc[2] if doc else None,
        doc_body=doc[3] if doc else "", doc_revision=doc[4] if doc else 0, rows=len(_LINKED.findall(table)),
    )


def _period_end(scale: str, anchor: date) -> date:
    return vertical.descriptor(scale).bounds_fn(anchor)[1]


def _row(goal_id: str, title: str, scale: str, anchor: date) -> str:
    name = re.sub(r"([\\|\[\]])", r"\\\1", " ".join(title.split()))
    return f"| [{name}](goal:{goal_id}) |  | Planned {vertical.planned_label(scale, anchor)} |  |\n"


def _make(conn: psycopg.Connection, *, owner: str, today: date, table: str, task_id: str | None) -> str:
    """The document for an open task (or a new task): its table under its title, the task planned this week and
    linking it."""
    path, title = doc_path(today), doc_title(today)
    taken = conn.execute(
        "SELECT 1 FROM docs WHERE owner = %(owner)s AND path = %(path)s", {"owner": owner, "path": path}
    ).fetchone()
    if taken is not None:
        n = 2
        while conn.execute("SELECT 1 FROM docs WHERE owner = %(owner)s AND path = %(path)s",
                           {"owner": owner, "path": f"replan/{today.isoformat()}-{n}.md"}).fetchone():
            n += 1
        path = f"replan/{today.isoformat()}-{n}.md"
    docs_mod.create(conn, owner=owner, path=path, title=title, body=f"# {title}\n\n{table}")
    link = f"[{title}](doc:{path})"
    if task_id is None:
        return goals.create(conn, owner=owner, title=TITLE, body=link, vertical=vertical.WEEK, anchor_date=today,
                            origin="app").goal.id
    goals.update(conn, owner=owner, id=task_id, body=link)
    moves.schedule(conn, owner=owner, id=task_id, vertical=vertical.WEEK, anchor_date=today)
    return task_id


def run(conn: psycopg.Connection, *, owner: str, today: date) -> str | None:
    """The day's carry-over into the task. Returns the open task's id, or None when there is none
    and nothing was carried. The first run ever gathers every plan in a group today; later runs,
    the plans whose own period ended since the last one."""
    last = conn.execute(
        "SELECT last_run FROM carryover_runs WHERE owner = %(owner)s FOR UPDATE", {"owner": owner}
    ).fetchone()
    task = open_task(conn, owner=owner)
    if task is not None and task.doc_id is None:
        # From before the redesign: the table moves from the task's notes into its document, word for word.
        _make(conn, owner=owner, today=today, table=task.task_body, task_id=task.task_id)
        task = open_task(conn, owner=owner)
    elif task is not None and (task.vertical != vertical.WEEK or task.anchor_date is None
                               or _period_end(vertical.WEEK, task.anchor_date) < today):
        # The week turned with the task open: it moves into this week.
        moves.schedule(conn, owner=owner, id=task.task_id, vertical=vertical.WEEK, anchor_date=today)
    if last is not None and last[0] >= today:
        return task.task_id if task else None
    conn.execute(
        "INSERT INTO carryover_runs (owner, last_run) VALUES (%(owner)s, %(today)s)"
        " ON CONFLICT (owner) DO UPDATE SET last_run = EXCLUDED.last_run",
        {"owner": owner, "today": today},
    )
    # The plans the board puts in a group: undone, of a scale that rolls, from a period that has
    # ended, and not set aside by an ignore or an acknowledgement written before the roll. The app's
    # own tasks (this one, the morning reports) are never carried.
    rows = conn.execute(
        "SELECT id, title, vertical::text, anchor_date FROM goals"
        " WHERE owner = %(owner)s AND done_at IS NULL AND anchor_date < %(today)s AND origin <> 'app'"
        "   AND vertical::text = ANY(%(ladder)s)"
        "   AND (carryover_ignored_until IS NULL OR carryover_ignored_until < %(today)s)"
        "   AND NOT EXISTS (SELECT 1 FROM due_acknowledgements da WHERE da.owner = goals.owner"
        "        AND da.goal_id = goals.id AND da.vertical = goals.vertical AND da.period_key = goals.period_key)"
        " ORDER BY anchor_date DESC, position, id",
        {"owner": owner, "today": today, "ladder": list(vertical.ROLL_LADDER)},
    ).fetchall()
    since = last[0] if last is not None else None
    carried = [r for r in rows if _period_end(r[2], r[3]) < today and (since is None or _period_end(r[2], r[3]) >= since)]
    listed = set(_LINKED.findall(task.doc_body)) if task else set()
    lines = "".join(_row(gid, title, scale, anchor) for gid, title, scale, anchor in carried if gid not in listed)
    if not lines:
        return task.task_id if task else None
    if task is None:
        return _make(conn, owner=owner, today=today, table=HEADER + lines, task_id=None)
    docs_mod.save(conn, owner=owner, id=task.doc_id, expected_revision=task.doc_revision,
                  body=_with_rows(task.doc_body, lines))
    return task.task_id


def _with_rows(body: str, lines: str) -> str:
    """New rows at the end of the document's table, the rest of the text byte for byte; a table
    that was deleted comes back at the end."""
    at = body.find(HEADER.split("\n", 1)[0])
    if at < 0:
        text = body.rstrip("\n")
        return text + ("\n\n" if text.strip() else "") + HEADER + lines
    rest = body[at:].splitlines(keepends=True)
    n = 0
    while n < len(rest) and rest[n].lstrip().startswith("|"):
        n += 1
    table = "".join(rest[:n])
    return body[:at] + table + ("" if table.endswith("\n") else "\n") + lines + "".join(rest[n:])
