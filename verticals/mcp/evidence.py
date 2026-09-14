"""WP-33's two evidence tools (docs/EVIDENCE.md §6) — schemas, timestamp parsing and handlers,
in their own module because `tools.py` sat ten lines under S-90a's 750-line cap before WP-33
landed. Same seam rule (`tests/static/test_seam.py`): no raw SQL under `verticals/mcp/` — both
handlers below go through `core/evidence.py` and nothing else. `tools.py` splices `TOOLS` and
the two handlers into its own registry; nothing here imports `tools.py` back.

Surface note (owner-approved spec, docs/EVIDENCE.md §6/§9): evidence WRITES ship on MCP only —
the writer is the agent, by design. The HTTP side carries the read half (`board_to_json`'s
`evidence` map) for the UI indicator round; there is deliberately no HTTP write route, and
S-59's cross-transport audit (`tests/mcp/test_cross_transport.py`) names `evidence_update` in
its agent-only carve-out for exactly this reason.
"""

from __future__ import annotations

from datetime import datetime as _datetime
from typing import Any

import psycopg

from mcp import types

from verticals.core import evidence as core_evidence
from verticals.core.errors import ValidationError
from verticals.core.vertical import SCALE_KEYS
from verticals.core.idem import MAX_CLIENT_TOKEN_CHARS
from verticals.mcp.shapes import ok

_VERTICAL_ENUM = sorted(SCALE_KEYS)
_STATUS_ENUM = sorted(core_evidence.STORED_STATUSES)
_DUE_ENUM = sorted(core_evidence.DUE_STATUSES)

EVIDENCE_UPDATE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "goal_id": {"type": "string", "description": "8-character goal id."},
        "expected_content_revision": {
            "type": "integer",
            "minimum": 0,
            "description": "The goal's content_revision this verification was performed against. "
            "If the goal has since changed, the write is refused and the current revision returned — re-read, then retry.",
        },
        "expected_evidence_revision": {
            "type": ["integer", "null"],
            "minimum": 0,
            "description": "Optimistic lock on the evidence row itself, so two agents cannot "
            "silently overwrite each other's receipts. Omit on the first write for a goal.",
        },
        "status": {"type": "string", "enum": _STATUS_ENUM},
        "verified_at": {"type": ["string", "null"], "description": "ISO 8601 timestamp with offset. Required when status is 'verified'."},
        "source_cutoff_at": {"type": ["string", "null"], "description": "ISO 8601 timestamp with offset. Sources newer than this were not read."},
        "review_after": {"type": ["string", "null"], "description": "ISO 8601 timestamp with offset. After this instant a verified row reads as stale. Null means no expiry."},
        "payload": {
            "type": "object",
            "description": "identity / sources / claims / unresolved (docs/EVIDENCE.md §4). "
            "claims[].text is the agent's own short formulation — never a quotation or transcript excerpt.",
        },
        # REQUIRED here, unlike every other write tool (spec §6.2, D102): this surface is
        # agent-only, agents retry aggressively, and a retry without a token would bump
        # `evidence_revision` and then 409 its own second attempt — forcing the token turns
        # every retry into a clean replay. Non-null on purpose: a required-but-nullable
        # property would make the requirement hollow.
        "client_token": {
            "type": "string",
            "minLength": 1,
            "maxLength": MAX_CLIENT_TOKEN_CHARS,
            "description": "Idempotency key, REQUIRED for this tool. A replay within 24h of the "
            "first call with the same arguments returns the original result instead of writing again.",
        },
    },
    "required": ["goal_id", "expected_content_revision", "status", "payload", "client_token"],
}

EVIDENCE_DUE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "due_before": {
            "type": ["string", "null"],
            "description": "ISO 8601 timestamp with offset — the instant staleness is evaluated at. "
            "Omit for 'due now'; pass next Monday for 'what will be due by then'.",
        },
        "statuses": {
            "type": "array",
            "minItems": 1,
            "uniqueItems": True,
            "items": {"type": "string", "enum": _DUE_ENUM},
            "description": "Effective statuses to include. Defaults to all four ('verified' is never due).",
        },
        "verticals": {
            "type": "array",
            "minItems": 1,
            "uniqueItems": True,
            "items": {"type": "string", "enum": _VERTICAL_ENUM},
        },
        "limit": {"type": "integer", "minimum": 1, "maximum": core_evidence.DUE_MAX_LIMIT},
        "cursor": {"type": ["string", "null"], "description": "Opaque page token from a previous call's next_cursor."},
    },
    "required": [],
}

TOOLS: tuple[types.Tool, ...] = (
    types.Tool(name="evidence_update", description="Record how a goal's content was verified: sources, claims, unresolved questions and a review deadline. Optimistically locked against both the goal's content revision and the evidence row; never changes the goal itself.", input_schema=EVIDENCE_UPDATE_SCHEMA),
    types.Tool(name="evidence_due", description="The review worklist: goals whose evidence is unverified, partial, index-only or stale (computed against the goal's current content revision and review deadline). Slim rows only, keyset-paginated.", input_schema=EVIDENCE_DUE_SCHEMA),
)


def _parse_optional_ts(value: object, *, field: str) -> _datetime | None:
    """ISO 8601 timestamp WITH offset — `core/evidence.py`'s boundary refuses naive datetimes
    (its own reasoning: naive-vs-timestamptz comparison is a silent off-by-timezone bug), so
    the refusal happens here, where the caller's string is still in hand for the message."""
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValidationError(f"{field} must be an ISO 8601 timestamp string", field=field)
    try:
        parsed = _datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValidationError(f"{field} must be an ISO 8601 timestamp, got {value!r}", field=field) from exc
    if parsed.tzinfo is None:
        raise ValidationError(f"{field} must carry a UTC offset (e.g. ...Z or ...+04:00)", field=field)
    return parsed


def handle_evidence_update(conn: psycopg.Connection, owner: str, args: dict[str, Any]) -> types.CallToolResult:
    result = core_evidence.evidence_update(
        conn,
        owner=owner,
        goal_id=args["goal_id"],
        expected_content_revision=args["expected_content_revision"],
        expected_evidence_revision=args.get("expected_evidence_revision"),
        status=args["status"],
        verified_at=_parse_optional_ts(args.get("verified_at"), field="verified_at"),
        source_cutoff_at=_parse_optional_ts(args.get("source_cutoff_at"), field="source_cutoff_at"),
        review_after=_parse_optional_ts(args.get("review_after"), field="review_after"),
        payload=args["payload"],
        client_token=args.get("client_token"),
    )
    text = f"Evidence for [{args['goal_id']}]: {result.evidence['stored_status']}"
    if result.replayed:
        text += " (replayed)"
    return ok(text, {"evidence": result.evidence, "replayed": result.replayed})


def handle_evidence_due(conn: psycopg.Connection, owner: str, args: dict[str, Any]) -> types.CallToolResult:
    r = core_evidence.due(
        conn,
        owner=owner,
        due_before=_parse_optional_ts(args.get("due_before"), field="due_before"),
        statuses=args.get("statuses"),
        verticals=args.get("verticals"),
        limit=args.get("limit", core_evidence.DUE_DEFAULT_LIMIT),
        cursor=args.get("cursor"),
    )
    text = f"{len(r.items)} goal(s) due for review" + (" (more pages)" if r.next_cursor else "")
    return ok(text, {"items": list(r.items), "next_cursor": r.next_cursor})
