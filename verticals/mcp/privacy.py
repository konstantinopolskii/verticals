"""`privacy`: the owner's privacy mode and rules. Goals are flagged with `update`'s `private`."""

from __future__ import annotations

from typing import Any

import psycopg
from mcp import types

from verticals.core import privacy
from verticals.core.idem import MAX_CLIENT_TOKEN_CHARS
from verticals.mcp.shapes import ok

PRIVACY_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "on": {"type": "boolean", "description": "Turn privacy mode on or off. Omit to leave it."},
        "rules": {
            "type": "string",
            "maxLength": privacy.MAX_RULES_CHARS,
            "description": "Replace the owner's rules for what to hide, in their words. Omit to leave them.",
        },
        "client_token": {"type": ["string", "null"], "maxLength": MAX_CLIENT_TOKEN_CHARS},
    },
    "required": [],
}

TOOLS: tuple[types.Tool, ...] = (
    types.Tool(
        name="privacy",
        description=(
            "Privacy mode for screenshots. Returns whether it is on, the owner's rules for what to "
            "hide and the goals flagged private; `on` and `rules` change them. Hide goals with "
            "`update` and `private: true` (bulk ids work): a private goal and its whole subtree "
            "blur while the mode is on, so flag the highest goal that fully matches. When the "
            "owner asks to hide something, save their words as rules. When they ask to turn the "
            "mode on, first check the board against the rules and offer to flag new matches."
        ),
        input_schema=PRIVACY_SCHEMA,
    ),
)


def handle_privacy(conn: psycopg.Connection, owner: str, args: dict[str, Any]) -> types.CallToolResult:
    if "rules" in args:
        privacy.set_rules(conn, owner=owner, rules=args["rules"])
    if "on" in args:
        privacy.set_mode(conn, owner=owner, mode=args["on"])
    state = privacy.status(conn, owner=owner)
    mode = "on" if state["mode"] else "off"
    return ok(f"Privacy mode {mode}; {len(state['private'])} goal(s) private", state)
