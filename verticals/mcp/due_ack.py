"""MCP due_ack mutation (migration 011), split from tools.py to preserve S-90a's module cap."""

from __future__ import annotations

from typing import Any

import psycopg
from mcp import types

from verticals.core import due_ack as core_due_ack
from verticals.core.idem import MAX_CLIENT_TOKEN_CHARS
from verticals.mcp.shapes import ok

DUE_ACK_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "id": {"type": "string", "description": "8-character goal id."},
        "verdict": {
            "type": "string",
            "enum": list(core_due_ack.VERDICTS),
            "description": (
                "'overdue' records that the goal really was due; 'done_on_time' records that it "
                "was finished before the deadline but never marked, and completes the goal."
            ),
        },
        "note": {
            "type": ["string", "null"],
            "maxLength": core_due_ack.MAX_NOTE_CHARS,
            "description": "Optional free-text context stored with the verdict.",
        },
        "client_token": {
            "type": ["string", "null"],
            "maxLength": MAX_CLIENT_TOKEN_CHARS,
            "description": "Optional idempotency key, matching the existing mutation surface.",
        },
    },
    "required": ["id", "verdict"],
}

TOOLS: tuple[types.Tool, ...] = (
    types.Tool(
        name="due_ack",
        description=(
            "Acknowledge a carry-over ('Due') goal with a verdict: 'overdue' (it really was "
            "due) or 'done_on_time' (finished before the deadline, just never marked — this "
            "also completes the goal). Either way the ghost leaves the board and the verdict "
            "joins the goal's permanent due history, keyed to the exact missed period. "
            "Acknowledging the same missed period twice is idempotent; the first verdict wins."
        ),
        input_schema=DUE_ACK_SCHEMA,
    ),
)


def _ack_dict(ack: core_due_ack.DueAck) -> dict[str, Any]:
    return {
        "goal_id": ack.goal_id,
        "vertical": ack.vertical,
        "period_key": ack.period_key,
        "verdict": ack.verdict,
        "note": ack.note,
        "acknowledged_at": ack.acknowledged_at.isoformat(),
    }


def handle_due_ack(
    conn: psycopg.Connection, owner: str, args: dict[str, Any]
) -> types.CallToolResult:
    ack = core_due_ack.acknowledge(
        conn, owner=owner, id=args["id"], verdict=args["verdict"], note=args.get("note")
    )
    return ok(
        f"Acknowledged {ack.goal_id} as {ack.verdict} for {ack.vertical} {ack.period_key}",
        {"acknowledgement": _ack_dict(ack)},
    )


def due_history_dicts(
    conn: psycopg.Connection, owner: str, id: str
) -> list[dict[str, Any]]:
    """The goal reader's due-history block — newest first, same dict shape as the mutation."""
    return [_ack_dict(a) for a in core_due_ack.history(conn, owner=owner, id=id)]
