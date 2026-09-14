"""Input JSON Schemas for the nine original MCP tools — extracted verbatim from
`verticals/mcp/tools.py` when D239's `short_label` property pushed that module past S-90a's
750-line cap (the third such split there: `shapes.py` took output shaping and `evidence.py`
its two whole tools at WP-33). Same seam rule (no raw SQL under `verticals/mcp/`); this module
holds no SQL and no handlers, only the input contracts. `tools.py` imports from here; nothing
here imports back — one direction, no cycle. The later tool families (`evidence`/`park`/
`tags`/`sizes`/`due_ack`) already keep their schemas beside their own handlers in their own
modules; these nine live here only because their handlers' module is the one at the cap.

Every one of the nine: `additionalProperties: false` (S-47). None names `origin` (S-53) — the
transport stamps it, a caller never supplies it. Every mutator (create/update/schedule/
reparent/delete) declares an optional, nullable `client_token`.
"""

from __future__ import annotations

from typing import Any

from verticals.core import goals as core_goals
from verticals.core import search as core_search
from verticals.core import sizes as sizes_mod
from verticals.core.vertical import SCALE_KEYS
from verticals.core.idem import MAX_CLIENT_TOKEN_CHARS

# S-47's own maxItems for `update`'s bulk `ids`. `core.goals.update`'s `ids` parameter has no
# upper bound at all (confirmed by reading it in full) — `api/schemas.py`'s `MAX_BULK_IDS` is,
# by its own docstring, "the *only* place the 500 cap is enforced" on the HTTP side. This is
# this transport's independent twin of that same number, matching house convention (duplicated
# per-transport validation, never cross-imported between api/ and mcp/) — not a drift risk
# against a single shared source, since neither transport had one to begin with.
MAX_BULK_IDS = 500

_VERTICAL_ENUM = sorted(SCALE_KEYS)
_COLOR_ENUM = sorted(core_goals.CANON_COLORS)

_CLIENT_TOKEN_PROP = {
    "type": ["string", "null"],
    "maxLength": MAX_CLIENT_TOKEN_CHARS,
    "description": "Idempotency key. A replay within 24h of the first call with the same "
    "arguments returns the original result instead of writing again.",
}

_CHILD_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "title": {"type": "string", "minLength": core_goals.MIN_TITLE_CHARS, "maxLength": core_goals.MAX_TITLE_CHARS},
        "body": {"type": "string"},
        "color": {"type": ["string", "null"], "enum": [*_COLOR_ENUM, None]},
        "tags": {"type": "array", "items": {"type": "string", "maxLength": core_goals.MAX_TAG_CHARS}, "maxItems": core_goals.MAX_TAGS},
        "vertical": {"type": ["string", "null"], "enum": [*_VERTICAL_ENUM, None]},
        "anchor_date": {"type": ["string", "null"], "description": "ISO 8601 date; required together with vertical."},
        "children": {"type": "array", "items": {"$ref": "#/$defs/child"}},
    },
    "required": ["title"],
}

BOARD_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "date": {"type": "string", "description": "ISO 8601 date (YYYY-MM-DD). The board's anchor 'today'."},
        "value": {
            "type": "string",
            "description": (
                "Value filter (D233): id of a parentless life-vertical goal. Narrows every "
                "column to that value's subtree (the life column included since D240 — the "
                "top-level `values` list stays full either way); only maybe keeps its pile."
            ),
        },
    },
    "required": ["date"],
}

GOAL_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {"id": {"type": "string", "description": "8-character goal id."}},
    "required": ["id"],
}

OUTLINE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "id": {
            "type": "string",
            "description": (
                "Subtree root id. Required for every mode except 'map', where it is optional — "
                "omit it there to render every top-level goal as its own tree."
            ),
        },
        "depth": {
            "type": ["integer", "null"],
            "description": "Levels below the root to render. Omit or null for the whole subtree.",
        },
        # D250 (KK, WP-2) shipped the first three shapes over the same subtree, chosen per call
        # rather than forcing every caller to pay for bodies it does not want. `full` stays the
        # tool's original, byte-identical behaviour — the default, so an existing caller that
        # never sends `mode` sees nothing change. D252 (KK) adds a fourth, `map`, a compact
        # box-drawing tree for the desk's own goal-map view — it is the one mode `id` is
        # optional for (`_handle_outline`, mcp/tools.py, enforces the id-required rule for every
        # other mode; this schema cannot, since a per-mode conditional required field is not
        # expressible in one JSON Schema `required` array without a second unconditional check).
        "mode": {
            "type": "string",
            "enum": ["full", "headlines", "headlines+docs", "map"],
            "description": (
                "'full' (default): every node's body text, exactly today's outline. "
                "'headlines': node lines only (title, scale/period chip, id) — no body text "
                "anywhere. 'headlines+docs': headlines plus, under each goal that has one or "
                "more linked documents, that goal's own linked document path(s). "
                "'map': a compact tree — box-drawing connectors, one line per goal, title then "
                "a bracketed vertical label (day shows its date, month shows its month name); "
                "no ids, no body text; done and parked goals are left off. `id` is optional "
                "only in this mode — omit it to render every top-level goal as its own tree."
            ),
        },
    },
    "required": [],
}

SEARCH_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "q": {
            "type": "string",
            "minLength": core_search.MIN_QUERY_CHARS,
            "maxLength": core_search.MAX_QUERY_CHARS,
            "description": "Substring match over title and body.",
        },
        "tag": {"type": "string", "minLength": 1, "maxLength": core_search.MAX_TAG_CHARS},
        "vertical": {"type": "string", "enum": _VERTICAL_ENUM},
        "limit": {"type": "integer", "minimum": core_search.MIN_LIMIT, "maximum": core_search.MAX_LIMIT},
    },
    "required": [],
}

CREATE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "title": {"type": "string", "minLength": core_goals.MIN_TITLE_CHARS, "maxLength": core_goals.MAX_TITLE_CHARS},
        "body": {"type": "string", "description": f"Markdown, at most {core_goals.MAX_BODY_BYTES} UTF-8 bytes."},
        "parent_id": {"type": ["string", "null"]},
        "vertical": {"type": ["string", "null"], "enum": [*_VERTICAL_ENUM, None]},
        "anchor_date": {"type": ["string", "null"], "description": "ISO 8601 date; required together with vertical."},
        "color": {"type": ["string", "null"], "enum": [*_COLOR_ENUM, None]},
        "tags": {"type": "array", "items": {"type": "string", "maxLength": core_goals.MAX_TAG_CHARS}, "maxItems": core_goals.MAX_TAGS},
        "children": {
            "type": "array",
            "items": {"$ref": "#/$defs/child"},
            "description": (
                "Nested plan nodes, one whole tree in one call. At most 200 nodes total "
                "(this root plus every descendant, IR-11) and at most 8 levels of nesting "
                "below the root."
            ),
        },
        "client_token": _CLIENT_TOKEN_PROP,
    },
    "required": ["title"],
    "$defs": {"child": _CHILD_SCHEMA},
}

UPDATE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "id": {"type": "string", "description": "One target. Mutually exclusive with ids."},
        "ids": {
            "type": "array",
            "items": {"type": "string"},
            "minItems": 1,
            "maxItems": MAX_BULK_IDS,
            "description": "Bulk targets, all-or-nothing in one transaction. Mutually exclusive with id.",
        },
        "title": {"type": "string", "minLength": core_goals.MIN_TITLE_CHARS, "maxLength": core_goals.MAX_TITLE_CHARS},
        "body": {"type": "string"},
        "color": {"type": ["string", "null"], "enum": [*_COLOR_ENUM, None]},
        "tags": {"type": "array", "items": {"type": "string", "maxLength": core_goals.MAX_TAG_CHARS}, "maxItems": core_goals.MAX_TAGS},
        "done": {"type": "boolean"},
        "foil": {"type": "boolean"},
        "short_label": {
            "type": ["string", "null"],
            "maxLength": core_goals.MAX_SHORT_LABEL_CHARS,
            "description": "One-word menu label for a value (parentless life goal); refused anywhere else. Null clears.",
        },
        "carryover_ignored_until": {"type": ["string", "null"], "format": "date"},
        "repeat": {
            "type": ["object", "null"],
            "additionalProperties": False,
            "properties": {
                "frequency": {
                    "type": "string",
                    "enum": ["daily", "weekly", "monthly", "quarterly", "yearly", "every_decade"],
                },
                "interval": {"type": "integer", "minimum": 1, "maximum": 10},
                "weekdays": {
                    "type": "array", "minItems": 1, "uniqueItems": True,
                    "items": {"type": "integer", "minimum": 1, "maximum": 7},
                },
                "month_days": {
                    "type": "array", "minItems": 1, "uniqueItems": True,
                    "items": {"type": "integer", "minimum": 1, "maximum": 31},
                },
                "months": {
                    "type": "array", "minItems": 1, "uniqueItems": True,
                    "items": {"type": "integer", "minimum": 1, "maximum": 12},
                },
                "quarters": {
                    "type": "array", "minItems": 1, "uniqueItems": True,
                    "items": {"type": "integer", "minimum": 1, "maximum": 4},
                },
                "end_date": {"type": ["string", "null"], "format": "date"},
            },
            "required": ["frequency"],
            "description": "Structured repeat rule. Null clears recurrence. Targets one id only, which must be scheduled and childless. `end_date` is the only end condition — there is no occurrence count.",
        },
        "size_expected": {
            "oneOf": [
                {
                    "type": "array",
                    "minItems": 1,
                    "items": {"type": "string", "enum": list(sizes_mod.SHOT_TOKENS)},
                },
                {"type": "string", "minLength": 1},
                {"type": "null"},
            ]
        },
        "after_id": {
            "type": ["string", "null"],
            "description": (
                "Reorder: place id directly after this sibling within its own group. Targets "
                "a single id only (not valid with ids); not valid combined with title/body/"
                "color/tags/done in the same call."
            ),
        },
        "position": {
            "type": ["string", "null"],
            "enum": ["first", None],
            "description": (
                "Reorder: 'first' moves id to the top of its own sibling group — the one place "
                "after_id cannot name, since index 0 has no row before it. Same rules as "
                "after_id (single id, no content fields), and not valid together with it."
            ),
        },
        "client_token": _CLIENT_TOKEN_PROP,
    },
    "required": [],
}

SCHEDULE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "id": {"type": "string"},
        "vertical": {"type": ["string", "null"], "enum": [*_VERTICAL_ENUM, None]},
        "anchor_date": {"type": ["string", "null"], "description": "ISO 8601 date. Both null clears the schedule."},
        "client_token": _CLIENT_TOKEN_PROP,
    },
    "required": ["id", "vertical", "anchor_date"],
}

REPARENT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "id": {"type": "string"},
        "parent_id": {"type": ["string", "null"], "description": "New parent. Null detaches to root."},
        "client_token": _CLIENT_TOKEN_PROP,
    },
    "required": ["id", "parent_id"],
}

DELETE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "id": {"type": "string"},
        "cascade": {
            "type": "boolean",
            "default": False,
            "description": "Required true to remove a non-empty subtree. Never destructive by omission.",
        },
        "client_token": _CLIENT_TOKEN_PROP,
    },
    "required": ["id"],
}
