"""The second agent's verdict becomes the report's check (docs/design/morning-quality.md).

The second agent (the gateway runs it, desktop/chat/morning_flow.py) reads the report against the raw sources and answers the ten
checks by key, each as pass, fail or gap. It only reads: this module is what writes. It puts the verdict into the report under
the red block, and puts the server's own floor under the checks the server can decide without a model, so the second agent's
"pass" never outvotes a count that does not add up:

  * **Every source read:** each source has its row in the last section, and a source that is red or waiting for the owner's
    Approve is named in the red block at the top. With no sources at all (the app's own Connections is not one) the report has
    no Sources section, and nothing is held against it for that.
  * **Every message placed:** in each row, what was read is what was placed, to the last message.
  * **Continues the last report:** each window starts no later than the last report's window for that source ended, and no window
    ends before it starts.
  * **Current state:** no row is a task that is closed.
  * **Hierarchy and dates:** a row set under a parent (after a dash) is a child of the row above it on the board.
  * **Where each item went:** each row links a task.
  * **Published copy:** the title is the day's, and the document is linked to the Morning report task.

The worse of the two answers stands, and a check the second agent did not answer is a gap, never a pass. A fail is what sends
the report back for one fixing turn; a gap is shown and does not hold the report.

IR-02: takes an open connection, never commits.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime

import psycopg

from verticals.core import docs as core_docs
from verticals.core import morning_report as report
from verticals.core import morning_windows as windows
from verticals.core import sources as core_sources
from verticals.core.errors import RevisionMismatch, ValidationError
from verticals.core.field_rules import validate_owner
from verticals.core.morning_report import FAIL, GAP, PASS, Outcome

TITLE = "Morning report"
_MONTHS = ("January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December")


def report_title(day: date) -> str:
    """The report's title as the app asks for it (`MORNING_TITLE — longDay(today)` in web `lib/morning.ts`)."""
    return f"{TITLE} — {day.day} {_MONTHS[day.month - 1]} {day.year}"


@dataclass(frozen=True)
class Applied:
    """What was written: every check's final outcome, the keys that failed and the keys that are gaps, in the order of the checks."""

    doc_id: str
    revision: int
    outcomes: Mapping[str, Outcome]
    failed: tuple[str, ...]
    gaps: tuple[str, ...]
    state: str  # "checked", "pending" or "unchecked"

    def as_dict(self) -> dict[str, object]:
        return {
            "doc_id": self.doc_id, "revision": self.revision, "state": self.state, "failed": list(self.failed),
            "gaps": list(self.gaps),
            "checks": {key: {"result": o.result, "note": o.note, "label": report.LABEL[key]} for key, o in self.outcomes.items()},
        }


def _when(moment: datetime) -> str:
    return moment.strftime("%Y-%m-%d %H:%M")


def _list(names: list[str]) -> str:
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]


def floor(conn: psycopg.Connection, *, owner: str, doc: core_docs.Doc, day: date, now: datetime) -> dict[str, Outcome]:
    """The checks the server can fail by itself, as fails with their reasons. A check it finds nothing wrong with is not here:
    it is the second agent's to pass."""
    body = doc.body
    found: dict[str, list[str]] = {}

    def problem(key: str, text: str) -> None:
        found.setdefault(key, []).append(text)

    sections = report.parse_sources(body)
    sources = windows.real_sources(conn, owner=owner)
    # With no sources there is nothing to list, and the report says so in one line at the top instead of a Sources section.
    if sources:
        for text in sections.problems:
            problem("sources", text)
    top = " ".join(report.unread(body) or []).lower()

    # Every source read: a row for each, and the red ones at the top.
    rows_of = {s.id: windows.row_for(s, sections.rows) for s in sources}
    if sections.found:
        missing = [s.title or s.path for s in sources if rows_of[s.id] is None]
        if missing:
            problem("sources", f"No row in Sources for {_list(missing)}.")
    views = {v.id: v for v in core_sources.views(conn, owner=owner, now=now, excerpt=False)}
    cannot_be_read = [s for s in sources if views[s.id].status == core_sources.RED or views[s.id].why == core_sources.WAITING]
    silent = [s.title or s.path for s in cannot_be_read if (s.title or s.path).lower() not in top]
    if silent:
        problem("sources", f"{_list(silent)} cannot be read now and is not named in the red block at the top.")

    # Every message placed, and the windows, row by row.
    for row in sections.rows:
        for text in row.problems:
            problem("sources", f"{row.name}: {text}.")
        if row.read is None or row.placed is None:
            problem("inputs", f"{row.name}: not every count is a number.")
        elif row.read != row.placed:
            problem("inputs", f"{row.name}: {row.read} read, {row.placed} placed.")
        if row.start is not None and row.end is not None and row.end < row.start:
            problem("continuity", f"{row.name}: the window ends before it starts.")

    # Continues the last report: nothing between the last report's end and this window's start.
    last = windows.last_report(conn, owner=owner, before=day)
    if last is not None:
        for source in sources:
            row, before = rows_of[source.id], windows.row_for(source, last.sources.rows)
            if row is None or before is None or before.end is None or row.start is None:
                continue
            if row.start > before.end:
                problem("continuity", f"{row.name}: starts {_when(row.start)}, but the last report stopped at {_when(before.end)}.")
            if row.end is not None and row.end < before.end:
                problem("continuity", f"{row.name}: ends {_when(row.end)}, before the last report's {_when(before.end)}.")

    # The rows against the board.
    task_rows = report.task_rows(body)
    linked = [r.goal for r in task_rows if r.goal]
    state = {}
    if linked:
        state = {
            gid: (parent, done is not None)
            for gid, parent, done in conn.execute(
                "SELECT id, parent_id, done_at FROM goals WHERE owner = %(owner)s AND id = ANY(%(ids)s)",
                {"owner": owner, "ids": linked},
            ).fetchall()
        }
    # A row that links nothing is a proposal, named by its result (the contract's rows part): the second agent judges those. A link
    # to a task that is not on the board is a row pointing at nothing.
    unlinked = [r.title or "a row" for r in task_rows if r.goal is not None and r.goal not in state]
    if unlinked:
        problem("where", f"No task on the board behind {_list(unlinked[:6])}.")
    closed = [r.title for r in task_rows if r.goal in state and state[r.goal][1]]
    if closed:
        problem("state", f"{_list(closed[:6])} {'is' if len(closed) == 1 else 'are'} closed and still in the table.")
    parent_row: report.TaskRow | None = None
    for row in task_rows:
        if not row.child:
            parent_row = row
            continue
        want = state.get(row.goal, (None, False))[0] if row.goal else None
        if parent_row is None or parent_row.goal is None or want != parent_row.goal:
            problem("hierarchy", f"{row.title} is set under a task that is not its parent.")

    # The published copy.
    if doc.title != report_title(day):
        problem("copy", f"The title is {doc.title!r}, not {report_title(day)!r}.")
    if not any(link.title == TITLE for link in core_docs.links_for_doc(conn, owner=owner, doc_id=doc.id)):
        problem("copy", f"The document is not linked to its {TITLE} task.")

    return {key: Outcome(FAIL, " ".join(texts[:4])) for key, texts in found.items()}


def _combine(asked: Outcome, floored: Outcome | None) -> Outcome:
    """The worse of the second agent's outcome and the floor's. When both fail, both reasons are shown."""
    if floored is None:
        return asked
    if asked.result == FAIL and asked.note and floored.note and floored.note not in asked.note:
        return Outcome(FAIL, f"{asked.note} {floored.note}")
    return report.worse(asked, floored)


def answers(raw: object) -> dict[str, Outcome]:
    """The second agent's answers as outcomes. A check it did not answer, or answered with something that is not pass, fail or
    gap, is a gap: nothing is passed on its silence."""
    given = raw if isinstance(raw, Mapping) else {}
    out = {}
    for key in report.KEYS:
        item = given.get(key)
        if isinstance(item, Mapping):
            result, note = item.get("result"), item.get("note", "")
        else:
            result, note = item, ""
        if result in (PASS, FAIL, GAP):
            out[key] = Outcome(result, report.one_line(note) if result != PASS else "")
        elif item is None:
            out[key] = Outcome(GAP, "The second agent gave no answer to this check.")
        else:
            out[key] = Outcome(GAP, f"The second agent answered {report.one_line(result, 40)!r}, which is not pass, fail or gap.")
    return out


def _write(conn: psycopg.Connection, *, owner: str, path: str, block: str) -> core_docs.Doc:
    """Put `block` in as the report's check. A document saved in between (the owner's hand, the agent's fixing turn) is read again
    and the block put in that: the check is the one part of it nobody else writes."""
    for attempt in range(3):
        doc = core_docs.get_by_path(conn, owner=owner, path=path)
        body = report.set_check(doc.body, block)
        if body == doc.body:
            return doc
        try:
            with conn.transaction():
                return core_docs.save(conn, owner=owner, id=doc.id, expected_revision=doc.revision, body=body).doc
        except RevisionMismatch:
            if attempt == 2:
                raise
    raise AssertionError("unreachable")


def _day(path: str) -> date:
    day = report.day_of(path)
    if day is None:
        raise ValidationError(f"{path!r} is not a morning report's path ({report.FOLDER}/<YYYY-MM-DD>.md)", field="path")
    return day


def apply(
    conn: psycopg.Connection, *, owner: str, path: str, asked: object, first: Mapping[str, Outcome] | None = None, now: datetime
) -> Applied:
    """Write the second agent's verdict into the report at `path`. `asked` is what it answered, by check key. `first` is the
    outcomes of the check before the fixing turn, when this is the check after it: a check that failed then and passes now is
    shown as fixed."""
    owner = validate_owner(owner)
    day = _day(path)
    doc = core_docs.get_by_path(conn, owner=owner, path=path)
    asked_outcomes = answers(asked)
    floored = floor(conn, owner=owner, doc=doc, day=day, now=now)
    final = {key: _combine(asked_outcomes[key], floored.get(key)) for key in report.KEYS}
    fixed = {key: first[key].note for key in report.KEYS if first and key in first and first[key].result == FAIL and final[key].result == PASS}
    saved = _write(conn, owner=owner, path=path, block=report.render_verdict(final, fixed))
    return Applied(
        doc_id=saved.id, revision=saved.revision, outcomes=final,
        failed=tuple(key for key in report.KEYS if final[key].result == FAIL),
        gaps=tuple(key for key in report.KEYS if final[key].result == GAP), state="checked",
    )


def mark(conn: psycopg.Connection, *, owner: str, path: str, state: str, reason: str = "") -> Applied:
    """Put the report's check at "pending" (a second agent is reading it) or "unchecked" (it did not finish, and `reason` says
    why): the two states a report is in without a verdict. A report is never left saying it was checked when it was not."""
    owner = validate_owner(owner)
    _day(path)
    if state not in ("pending", "unchecked"):
        raise ValidationError("state must be pending or unchecked", field="state")
    block = report.PENDING if state == "pending" else report.render_unchecked(reason)
    saved = _write(conn, owner=owner, path=path, block=block)
    return Applied(doc_id=saved.id, revision=saved.revision, outcomes={}, failed=(), gaps=(), state=state)
