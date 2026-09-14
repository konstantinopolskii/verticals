"""R11 tag tools: shared read, agent-only project-setting write."""

from __future__ import annotations

from typing import Any

import psycopg
from mcp import types

from verticals.core import tag_meta
from verticals.core.idem import MAX_CLIENT_TOKEN_CHARS
from verticals.mcp.shapes import ok

TAGS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {},
    "required": [],
}

TAG_MARK_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "tag": {"type": "string", "minLength": 1, "maxLength": tag_meta.MAX_TAG_CHARS},
        "project": {"type": "boolean"},
        "client_token": {"type": ["string", "null"], "maxLength": MAX_CLIENT_TOKEN_CHARS},
    },
    "required": ["tag", "project"],
}

TOOLS: tuple[types.Tool, ...] = (
    types.Tool(name="tags", description="List literal tags with project metadata.", input_schema=TAGS_SCHEMA),
    types.Tool(name="tag_mark", description="Mark or unmark a literal tag as a project tag.", input_schema=TAG_MARK_SCHEMA),
)


def handle_tags(conn: psycopg.Connection, owner: str, _args: dict[str, Any]) -> types.CallToolResult:
    tags = list(tag_meta.list_tags(conn, owner=owner))
    return ok(f"{len(tags)} tag(s)", {"tags": tags})


def handle_tag_mark(conn: psycopg.Connection, owner: str, args: dict[str, Any]) -> types.CallToolResult:
    meta = tag_meta.mark(conn, owner=owner, tag=args["tag"], project=args["project"])
    return ok(f"Tag {meta['tag']!r}: project={str(meta['project']).lower()}", {"tag": meta})
