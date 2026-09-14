"""MCP park mutation, split from tools.py to preserve S-90a's module cap."""

from __future__ import annotations

from typing import Any

import psycopg
from mcp import types

from verticals.core import moves as core_moves
from verticals.core.idem import MAX_CLIENT_TOKEN_CHARS
from verticals.mcp.shapes import goal_dict, ok

PARK_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "id": {"type": "string", "description": "8-character goal id."},
        "client_token": {
            "type": ["string", "null"],
            "maxLength": MAX_CLIENT_TOKEN_CHARS,
            "description": "Optional idempotency key, matching the existing mutation surface.",
        },
    },
    "required": ["id"],
}

TOOLS: tuple[types.Tool, ...] = (
    types.Tool(
        name="park",
        description="Remove a goal from its vertical while preserving its anchor, parent, position and subtree.",
        input_schema=PARK_SCHEMA,
    ),
)


def handle_park(
    conn: psycopg.Connection, owner: str, args: dict[str, Any]
) -> types.CallToolResult:
    goal = core_moves.park(conn, owner=owner, id=args["id"])
    return ok(f"Parked {goal.title!r} [{goal.id}]", {"goal": goal_dict(goal)})
