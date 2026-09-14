"""R12 agent-only actual shot-size reporting tool."""

from __future__ import annotations

from typing import Any

import psycopg
from mcp import types

from verticals.core import sizes
from verticals.core.idem import MAX_CLIENT_TOKEN_CHARS
from verticals.mcp.shapes import goal_dict, ok

_SHOT_ARRAY = {
    "type": "array",
    "minItems": 1,
    "items": {"type": "string", "enum": list(sizes.SHOT_TOKENS)},
}

SIZE_REPORT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "goal_id": {"type": "string"},
        "size_actual": {
            "oneOf": [
                _SHOT_ARRAY,
                {"type": "string", "minLength": 1},
                {"type": "null"},
            ]
        },
        "client_token": {"type": ["string", "null"], "maxLength": MAX_CLIENT_TOKEN_CHARS},
    },
    "required": ["goal_id", "size_actual"],
}

TOOLS: tuple[types.Tool, ...] = (
    types.Tool(
        name="size_report",
        description="Report or clear actual shot sizes for a week or day goal.",
        input_schema=SIZE_REPORT_SCHEMA,
    ),
)


def handle_size_report(conn: psycopg.Connection, owner: str, args: dict[str, Any]) -> types.CallToolResult:
    goal = sizes.report(conn, owner=owner, goal_id=args["goal_id"], size_actual=args["size_actual"])
    return ok(f"Actual size reported for {goal.title!r} [{goal.id}]", {"goal": goal_dict(goal)})
