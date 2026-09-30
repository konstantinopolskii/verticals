"""The task that holds the plans carried over (docs/design-handoff S4.P1.008–.012, .017, .023, .029).

Once a day, the plans whose own period ended since the last run join the open "Replan carried-over plans" task in the
Inbox as rows of its table, or make a new task when none is open. The task is a usual Inbox goal written by the app
(`origin = 'app'`), never by an agent; its notes are a plain markdown table of links to the plans, not its steps. A
second run on one day does nothing, and a run after the app was closed for weeks gathers every turn that passed into
one task.

IR-02: takes an open connection, never commits.
"""

from __future__ import annotations

import re
from datetime import date, timedelta

import psycopg

from verticals.core import goals
from verticals.core import vertical

TITLE = "Replan carried-over plans"
# In the notes editor's own spelling (web `lib/bodyMarkdown.ts`), so editing a cell keeps every other byte (S4.P4.025).
HEADER = "| Goal | Summary | Next step | Your comment |\n| --- | --- | --- | --- |\n"
_LINKED = re.compile(r"\(goal:([A-Za-z0-9_-]+)\)")


def _period_end(scale: str, anchor: date) -> date:
    return vertical.descriptor(scale).bounds_fn(anchor)[1]


def _row(goal_id: str, title: str, scale: str, anchor: date) -> str:
    name = re.sub(r"([\\|\[\]])", r"\\\1", " ".join(title.split()))
    return f"| [{name}](goal:{goal_id}) |  | Planned {vertical.planned_label(scale, anchor)} |  |\n"


def run(conn: psycopg.Connection, *, owner: str, today: date) -> str | None:
    """The day's carry-over into the task. Returns the open task's id, or None when there is none
    and nothing was carried. The first run ever gathers every plan in a group today; later runs,
    the plans whose own period ended since the last one."""
    last = conn.execute(
        "SELECT last_run FROM carryover_runs WHERE owner = %(owner)s FOR UPDATE", {"owner": owner}
    ).fetchone()
    task = conn.execute(
        "SELECT id, body FROM goals WHERE owner = %(owner)s AND vertical IS NULL AND parent_id IS NULL"
        "   AND origin = 'app' AND title = %(title)s AND done_at IS NULL ORDER BY created_at DESC LIMIT 1",
        {"owner": owner, "title": TITLE},
    ).fetchone()
    if last is not None and last[0] >= today:
        return task[0] if task else None
    conn.execute(
        "INSERT INTO carryover_runs (owner, last_run) VALUES (%(owner)s, %(today)s)"
        " ON CONFLICT (owner) DO UPDATE SET last_run = EXCLUDED.last_run",
        {"owner": owner, "today": today},
    )
    # The plans the board puts in a group: undone, of a scale that rolls, from a period that has
    # ended, and not set aside by an ignore or an acknowledgement written before the roll.
    rows = conn.execute(
        "SELECT id, title, vertical::text, anchor_date FROM goals"
        " WHERE owner = %(owner)s AND done_at IS NULL AND anchor_date < %(today)s"
        "   AND vertical::text = ANY(%(ladder)s)"
        "   AND (carryover_ignored_until IS NULL OR carryover_ignored_until < %(today)s)"
        "   AND NOT EXISTS (SELECT 1 FROM due_acknowledgements da WHERE da.owner = goals.owner"
        "        AND da.goal_id = goals.id AND da.vertical = goals.vertical AND da.period_key = goals.period_key)"
        " ORDER BY anchor_date DESC, position, id",
        {"owner": owner, "today": today, "ladder": list(vertical.ROLL_LADDER)},
    ).fetchall()
    since = last[0] if last is not None else None
    carried = [r for r in rows if _period_end(r[2], r[3]) < today and (since is None or _period_end(r[2], r[3]) >= since)]
    listed = set(_LINKED.findall(task[1] or "")) if task else set()
    lines = "".join(_row(gid, title, scale, anchor) for gid, title, scale, anchor in carried if gid not in listed)
    if not lines:
        return task[0] if task else None
    if task is None:
        return goals.create(conn, owner=owner, title=TITLE, body=HEADER + lines, origin="app").goal.id
    goals.update(conn, owner=owner, id=task[0], body=_with_rows(task[1] or "", lines))
    return task[0]


def _with_rows(body: str, lines: str) -> str:
    """New rows at the end of the task's table, the rest of the notes byte for byte; a table
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
