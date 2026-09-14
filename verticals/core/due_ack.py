"""Due acknowledgments (KK ruling 2026-08-14, migration 011).

A carry-over ghost is dismissed with a VERDICT, never silently: either "yes, this was overdue"
(`overdue`) or "it was done on time, just never marked" (`done_on_time`, which also completes
the goal through the ordinary update path so repeat materialization and S-19 semantics hold).
Both verdicts leave one permanent row keyed to the exact missed period — the goal's own
(vertical, period_key) at acknowledgment time. The board's ghost branch (`core/board.py`)
excludes acknowledged pairs; rescheduling into a new period and missing again is a new dueness
and ghosts again.

Acknowledging the same missed period twice is idempotent by primary key: the first verdict
wins and replays get the stored row back, the same stance `client_token` idempotency (003)
takes for mutations.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date as _date
from datetime import datetime

import psycopg

from verticals.core import goals as core_goals
from verticals.core import vertical as vertical_mod
from verticals.core.errors import NotFound, ValidationError

VERDICTS = ("overdue", "done_on_time")
MAX_NOTE_CHARS = 2000

_COLUMNS = "goal_id, vertical, period_key, verdict, note, acknowledged_at"


@dataclass(frozen=True)
class DueAck:
    goal_id: str
    vertical: str
    period_key: str
    verdict: str
    note: str | None
    acknowledged_at: datetime


def _to_ack(row: tuple) -> DueAck:
    return DueAck(*row)


def _validate_note(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValidationError("note must be a string", field="note")
    note = value.strip()
    if not note:
        return None
    if len(note) > MAX_NOTE_CHARS:
        raise ValidationError(
            f"note exceeds {MAX_NOTE_CHARS} characters", field="note", length=len(note)
        )
    return note


def acknowledge(
    conn: psycopg.Connection,
    *,
    owner: str,
    id: str,
    verdict: str,
    note: object = None,
) -> DueAck:
    """Record a verdict for `id`'s CURRENT dueness and return the stored acknowledgment row.

    Refuses anything that is not actually ghosting right now — same predicate as the board's
    carry-over branch (open, dated, and anchored before the current period's start) — so an
    acknowledgment can never exist for a dueness the owner never saw."""
    if not isinstance(owner, str) or not owner:
        raise ValidationError("owner must be a non-empty string", field="owner")
    if not isinstance(id, str) or not id:
        raise ValidationError("id must be a non-empty string", field="id")
    if verdict not in VERDICTS:
        raise ValidationError(
            f"verdict must be one of {', '.join(VERDICTS)}", field="verdict"
        )
    clean_note = _validate_note(note)

    with conn.transaction():
        current = conn.execute(
            "SELECT vertical, period_key, anchor_date, done_at FROM goals"
            " WHERE owner = %(owner)s AND id = %(id)s FOR UPDATE",
            {"owner": owner, "id": id},
        ).fetchone()
        if current is None:
            raise NotFound(f"no goal {id!r} for owner {owner!r}", id=id, owner=owner)
        vertical, period_key, anchor_date, done_at = current

        # Replay guard BEFORE the refusal checks: once a verdict exists for this exact
        # (vertical, period_key) the call is a replay — return the stored row untouched.
        # A `done_on_time` verdict completes the goal, so without this ordering the replay
        # would trip the "already completed" refusal instead of being idempotent, and a
        # second, different verdict would still fire the completion side effect.
        if vertical is not None:
            existing = conn.execute(
                f"SELECT {_COLUMNS} FROM due_acknowledgements"
                " WHERE owner = %(owner)s AND goal_id = %(id)s"
                "   AND vertical = %(vertical)s AND period_key = %(period_key)s",
                {"owner": owner, "id": id, "vertical": vertical, "period_key": period_key},
            ).fetchone()
            if existing is not None:
                return _to_ack(existing)

        if done_at is not None:
            raise ValidationError(
                f"goal {id!r} is already completed — nothing is due", field="id", id=id
            )
        if vertical is None:
            raise ValidationError(
                f"goal {id!r} is parked and has no dueness", field="id", id=id
            )
        bounds = vertical_mod.descriptor(vertical).bounds_fn(_date.today())
        if bounds is None:
            raise ValidationError("a life value is never due", field="id", id=id)
        if anchor_date is None or anchor_date >= bounds[0]:
            raise ValidationError(
                f"goal {id!r} is not overdue in its current period", field="id", id=id
            )

        if verdict == "done_on_time":
            core_goals.update(conn, owner=owner, id=id, done=True)

        conn.execute(
            "INSERT INTO due_acknowledgements"
            " (goal_id, owner, vertical, period_key, verdict, note)"
            " VALUES (%(id)s, %(owner)s, %(vertical)s, %(period_key)s, %(verdict)s, %(note)s)"
            " ON CONFLICT (goal_id, owner, vertical, period_key) DO NOTHING",
            {
                "id": id,
                "owner": owner,
                "vertical": vertical,
                "period_key": period_key,
                "verdict": verdict,
                "note": clean_note,
            },
        )
        row = conn.execute(
            f"SELECT {_COLUMNS} FROM due_acknowledgements"
            " WHERE owner = %(owner)s AND goal_id = %(id)s"
            "   AND vertical = %(vertical)s AND period_key = %(period_key)s",
            {"owner": owner, "id": id, "vertical": vertical, "period_key": period_key},
        ).fetchone()

    return _to_ack(row)


def history(conn: psycopg.Connection, *, owner: str, id: str) -> tuple[DueAck, ...]:
    """Every acknowledgment ever recorded for one goal, newest first. Existence-oracle-safe the
    same way every reader is (S-41): an unknown or foreign id is the ordinary NotFound."""
    exists = conn.execute(
        "SELECT 1 FROM goals WHERE owner = %(owner)s AND id = %(id)s",
        {"owner": owner, "id": id},
    ).fetchone()
    if exists is None:
        raise NotFound(f"no goal {id!r} for owner {owner!r}", id=id, owner=owner)
    rows = conn.execute(
        f"SELECT {_COLUMNS} FROM due_acknowledgements"
        " WHERE owner = %(owner)s AND goal_id = %(id)s"
        " ORDER BY acknowledged_at DESC",
        {"owner": owner, "id": id},
    ).fetchall()
    return tuple(_to_ack(row) for row in rows)
