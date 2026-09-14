"""WP-A's three comment tools (KK decisions 2026-08-25, docs/COMMENTS_SPEC.md) — schemas and
handlers, whole in one module, mirroring `verticals/mcp/evidence.py`'s/`verticals/mcp/docs.py`'s
own shape (a later tool family keeps its schema beside its own handler in its own module rather
than growing `tools.py`/`tool_schemas.py` further past S-90a's cap). `tools.py` splices `TOOLS`
and the three handlers below into its own registry; nothing here imports `tools.py` back.

Same seam rule as everywhere else under `verticals/mcp/` (`tests/static/test_seam.py`): no raw
SQL. Every handler below is a thin argument-shaping wrapper around an already-shipped
`verticals/core/comments.py` verb (`create_thread`/`add_message`/`set_resolved`/`list_for_goal`/
`list_for_doc`/`list_unresolved`) — this module owns argument shaping, the `doc` id-or-path
convention, and output dict serialisation; `core/` owns every rule and every statement.

**Why this module exists at all.** Comments are the return channel between KK (web UI, `author=
'human'`) and his agents (MCP, `author='agent'`) — docs/COMMENTS_SPEC.md decision 4: "Transport
decides authorship; no new auth." Every write below is therefore hard-coded `author='agent'`,
never a caller-supplied field; there is no argument on any schema here that could set it to
anything else.

**`comment_add`'s two shapes, one tool.** `thread_id` given means "reply" — `goal_id`/`doc`/
`anchor` are refused alongside it (`handle_comment_add`'s own check), because those three only
mean something when a NEW thread is being anchored; a reply already belongs to the thread it is
replying into. `thread_id` absent means "new thread" — exactly one of `goal_id`/`doc` is then
`core.comments.create_thread`'s own refusal to enforce, not re-checked here.

**`doc` accepts an id or a path**, trailing `.md` read as a path — byte-for-byte the same
convention `verticals/mcp/docs.py::doc_link`/`doc_unlink` already established (`_resolve_doc`
below is a deliberate small duplicate of that module's own helper, not an import across it — see
`_resolve_doc`'s own docstring for why every `mcp/*.py` family module stays self-contained rather
than reaching into a sibling's private names).

**Idempotency mirrors `core/comments.py` exactly**: `comment_add` carries the same optional
`client_token` every mutating tool in this project declares, and it is REAL here — wired through
to `core.comments.create_thread`/`add_message`, unlike `verticals/mcp/docs.py`'s own `client_token`
(accepted, never read, by that module's own admission). `comment_resolve` also carries the field,
for S-47's schema-uniformity rule across the whole tool surface, but — matching
`core.comments.set_resolved`'s own signature, which takes no `client_token` at all (resolving is
idempotent by construction, module docstring) — the value is accepted and never read, the exact
stance `verticals/mcp/docs.py`'s own `doc_delete` already takes for the same reason.

Error mapping needs no custom table here: every `core/comments.py` refusal is already one of the
closed `VerticalError` types (`NotFound`/`ValidationError`), and `tools.py::call_tool`'s own
`except VerticalError` renders every one of them the same way it renders every other tool's
refusal.
"""

from __future__ import annotations

from typing import Any

import psycopg
from mcp import types

from verticals.core import comments as core_comments
from verticals.core import docs as core_docs
from verticals.core.comments import (
    MAX_ANCHOR_PREFIX_CHARS,
    MAX_ANCHOR_QUOTE_CHARS,
    MAX_ANCHOR_SUFFIX_CHARS,
    MAX_MESSAGE_BODY_BYTES,
)
from verticals.core.docs import MAX_PATH_CHARS
from verticals.core.errors import ValidationError
from verticals.core.idem import MAX_CLIENT_TOKEN_CHARS
from verticals.models import CommentMessage, CommentTarget, CommentThread, Doc, UnresolvedThread
from verticals.mcp.shapes import ok

_CLIENT_TOKEN_PROP: dict[str, Any] = {
    "type": ["string", "null"],
    "maxLength": MAX_CLIENT_TOKEN_CHARS,
    "description": "Optional idempotency key, matching the existing mutation surface.",
}

_BODY_PROP: dict[str, Any] = {
    "type": "string",
    "description": f"Plain text, at most {MAX_MESSAGE_BODY_BYTES} UTF-8 bytes, non-blank after strip.",
}

_DOC_REF_PROP: dict[str, Any] = {
    "type": "string",
    "maxLength": MAX_PATH_CHARS,
    "description": "A document's id or its path — a trailing '.md' is read as a path, anything else as an id.",
}

_ANCHOR_PROP: dict[str, Any] = {
    "type": ["object", "null"],
    "additionalProperties": False,
    "properties": {
        "quote": {"type": "string", "minLength": 1, "maxLength": MAX_ANCHOR_QUOTE_CHARS},
        "prefix": {"type": "string", "maxLength": MAX_ANCHOR_PREFIX_CHARS},
        "suffix": {"type": "string", "maxLength": MAX_ANCHOR_SUFFIX_CHARS},
    },
    "required": ["quote"],
    "description": "Selected-text anchor, kit-style: quote required, non-empty; prefix/suffix "
    "default to \"\" and may legitimately stay empty. Omit (or null) for a whole-card/whole-doc "
    "thread. Only meaningful when starting a new thread — refused together with thread_id.",
}

# --- schemas ------------------------------------------------------------------------------------

COMMENTS_LIST_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "goal_id": {
            "type": "string",
            "description": "List threads anchored to this goal. At most one of goal_id/doc.",
        },
        "doc": _DOC_REF_PROP,
    },
    "required": [],
}

COMMENT_ADD_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "goal_id": {
            "type": "string",
            "description": "New thread on a goal. Refused together with thread_id.",
        },
        "doc": _DOC_REF_PROP,
        "body": _BODY_PROP,
        "thread_id": {
            "type": "string",
            "description": "Reply into an existing thread instead of starting a new one. "
            "goal_id/doc/anchor are refused when this is given.",
        },
        "anchor": _ANCHOR_PROP,
        "client_token": _CLIENT_TOKEN_PROP,
    },
    "required": ["body"],
}

COMMENT_RESOLVE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "thread_id": {"type": "string"},
        "resolved": {"type": "boolean", "description": "Defaults to true; pass false to reopen."},
        "client_token": _CLIENT_TOKEN_PROP,
    },
    "required": ["thread_id"],
}

TOOLS: tuple[types.Tool, ...] = (
    types.Tool(
        name="comments",
        description="List comment threads. goal_id or doc (id or path, trailing '.md' read as a path) scopes to one target's own threads. With neither: every unresolved thread for the owner — the agent worklist — each carrying a target descriptor (what goal or doc it is about) so you never need a second call to orient yourself.",
        input_schema=COMMENTS_LIST_SCHEMA,
    ),
    types.Tool(
        name="comment_add",
        description="Start a new thread (goal_id or doc, optionally an anchor selecting text within the body) or reply into an existing one (thread_id — goal_id/doc/anchor are refused together with it, since a reply already belongs to its own thread). Every message this tool writes is stamped author='agent'.",
        input_schema=COMMENT_ADD_SCHEMA,
    ),
    types.Tool(
        name="comment_resolve",
        description="Mark a thread resolved, or reopen it with resolved:false.",
        input_schema=COMMENT_RESOLVE_SCHEMA,
    ),
)


# --- output shaping -------------------------------------------------------------------------------
# Field-for-field mirrors of `verticals/api/schemas.py`'s own `comment_message_to_json`/
# `comment_thread_to_json` (S-33's own reasoning, carried over from docs to comments): the same
# thread shape either transport returns (docs/COMMENTS_SPEC.md's own "API and MCP identical").
# Datetimes go through `.isoformat()`, matching `verticals/mcp/docs.py`'s own output shaping —
# JSON has no datetime type, and the MCP wire is JSON same as HTTP's.


def _message_dict(m: CommentMessage) -> dict[str, Any]:
    return {"id": m.id, "author": m.author, "body": m.body, "created_at": m.created_at.isoformat()}


def _thread_dict(t: CommentThread) -> dict[str, Any]:
    return {
        "id": t.id,
        "goal_id": t.goal_id,
        "doc_id": t.doc_id,
        "anchor": (
            {"quote": t.anchor.quote, "prefix": t.anchor.prefix, "suffix": t.anchor.suffix}
            if t.anchor else None
        ),
        "resolved_at": t.resolved_at.isoformat() if t.resolved_at else None,
        "created_at": t.created_at.isoformat(),
        "messages": [_message_dict(m) for m in t.messages],
    }


def _target_dict(target: CommentTarget) -> dict[str, Any]:
    return {"kind": target.kind, "id": target.id, "title": target.title, "path": target.path}


def _unresolved_dict(u: UnresolvedThread) -> dict[str, Any]:
    """The worklist row shape: a thread plus WHAT it is about, in one dict — the module
    docstring's own "never a second call to orient yourself"."""
    return {**_thread_dict(u.thread), "target": _target_dict(u.target)}


def _resolve_doc(conn: psycopg.Connection, *, owner: str, ref: str) -> Doc:
    """Byte-for-byte the same id-or-path convention `verticals/mcp/docs.py::_resolve_doc`
    already established for `doc_link`/`doc_unlink` — duplicated rather than imported so this
    module stays self-contained, the same discipline every other `mcp/*.py` family module
    (`park.py`, `evidence.py`, `due_ack.py`) already follows: no `mcp/*.py` module reaches into
    a sibling's private (underscore-prefixed) names, each owns its own small helpers."""
    if ref.endswith(".md"):
        return core_docs.get_by_path(conn, owner=owner, path=ref)
    return core_docs.get(conn, owner=owner, id=ref)


# --- handlers -----------------------------------------------------------------------------------


def handle_comments(conn: psycopg.Connection, owner: str, args: dict[str, Any]) -> types.CallToolResult:
    goal_id = args.get("goal_id")
    doc_ref = args.get("doc")
    if goal_id is not None and doc_ref is not None:
        raise ValidationError("comments accepts at most one of goal_id or doc", field="goal_id,doc")

    if goal_id is not None:
        threads = core_comments.list_for_goal(conn, owner=owner, goal_id=goal_id)
        return ok(
            f"{len(threads)} thread(s) for goal [{goal_id}]",
            {"threads": [_thread_dict(t) for t in threads]},
        )
    if doc_ref is not None:
        doc = _resolve_doc(conn, owner=owner, ref=doc_ref)
        threads = core_comments.list_for_doc(conn, owner=owner, doc_id=doc.id)
        return ok(
            f"{len(threads)} thread(s) for doc {doc.path!r} [{doc.id}]",
            {"threads": [_thread_dict(t) for t in threads]},
        )

    unresolved = core_comments.list_unresolved(conn, owner=owner)
    return ok(f"{len(unresolved)} unresolved thread(s)", {"threads": [_unresolved_dict(u) for u in unresolved]})


def handle_comment_add(conn: psycopg.Connection, owner: str, args: dict[str, Any]) -> types.CallToolResult:
    thread_id = args.get("thread_id")
    goal_id = args.get("goal_id")
    doc_ref = args.get("doc")
    anchor = args.get("anchor")
    body = args["body"]
    client_token = args.get("client_token")

    if thread_id is not None:
        if goal_id is not None or doc_ref is not None or anchor is not None:
            raise ValidationError(
                "comment_add with thread_id is a reply — goal_id/doc/anchor belong to starting a "
                "NEW thread and are refused alongside it",
                field="thread_id",
            )
        added = core_comments.add_message(
            conn, owner=owner, thread_id=thread_id, body=body, author="agent", client_token=client_token
        )
        text = f"Replied in thread [{thread_id}]"
        if added.replayed:
            text += " (replayed)"
        return ok(
            text,
            {"message": _message_dict(added.message), "thread_id": thread_id, "replayed": added.replayed},
        )

    doc_id = _resolve_doc(conn, owner=owner, ref=doc_ref).id if doc_ref is not None else None
    created = core_comments.create_thread(
        conn,
        owner=owner,
        goal_id=goal_id,
        doc_id=doc_id,
        body=body,
        author="agent",
        anchor=anchor,
        client_token=client_token,
    )
    text = f"Created thread [{created.thread.id}]"
    if created.replayed:
        text += " (replayed)"
    return ok(text, {"thread": _thread_dict(created.thread), "replayed": created.replayed})


def handle_comment_resolve(conn: psycopg.Connection, owner: str, args: dict[str, Any]) -> types.CallToolResult:
    thread_id = args["thread_id"]
    resolved = args.get("resolved", True)
    if not isinstance(resolved, bool):
        raise ValidationError("resolved must be a boolean", field="resolved")
    thread = core_comments.set_resolved(conn, owner=owner, thread_id=thread_id, resolved=resolved)
    verb = "Resolved" if resolved else "Reopened"
    return ok(f"{verb} thread [{thread_id}]", {"thread": _thread_dict(thread)})
