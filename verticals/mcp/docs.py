"""D250 WP-2's eight document tools, plus D254's `doc_link`/`doc_unlink` — schemas and handlers,
whole in one module, mirroring `verticals/mcp/evidence.py`'s own shape (WP-33's precedent: a later
tool family keeps its schema beside its own handler in its own module rather than growing
`tools.py`/`tool_schemas.py` further past S-90a's cap). `tools.py` splices `TOOLS` and the ten
handlers below into its own registry; nothing here imports `tools.py` back.

Same seam rule as everywhere else under `verticals/mcp/` (`tests/static/test_seam.py`): no raw
SQL. Every handler below is a thin argument-shaping wrapper around an already-shipped
`verticals/core/docs.py` verb (`create`/`get`/`get_by_path`/`save`/`tree`/`history`/
`get_revision`/`restore`/`delete`/`links_for_doc`/`links_for_goal`/`links_for_goal_with_inherited`)
or, for `doc_link`/`doc_unlink`, `verticals/core/goals.py::update` (see the D254 section near the
bottom of this file) — this module owns argument shaping and output dict serialisation, `core/`
owns every rule and every statement.

Every write here (`doc_create`, `doc_save`, `doc_restore`, `doc_delete`, `doc_link`, `doc_unlink`)
declares the same optional `client_token` property every other mutating tool in this project
declares (S-47) — for schema uniformity across the whole tool surface, exactly like
`verticals/mcp/park.py`'s own `client_token` (see that module's comment: "matching the existing
mutation surface"). `core/docs.py` itself has no idempotency-replay machinery (unlike
`core/goals.py`'s `create`/`update`), so, same as `park`, the value is accepted and never read —
a caller that already sends a token to every mutator can keep doing so here without a special
case, and a real replay ledger can be added to `core/docs.py` later without a second schema
change. `doc_link`/`doc_unlink` are themselves already idempotent by construction (D254's table
below) without needing that token at all — checked-before-write, not replay-ledgered.

Error mapping needs no custom table here, unlike nothing at all: every `core/docs.py` refusal is
already one of the eight closed `VerticalError` types (`NotFound`/`ValidationError`/
`RevisionMismatch`), and `tools.py::call_tool`'s own `except VerticalError` catches and renders
every one of them the same way it renders every other tool's refusal — `doc_delete`'s refusal
while linked is `core.docs.delete()`'s own `ValidationError`, whose `.message` already names
every linked goal id (`verticals/core/docs.py::delete`'s own docstring), so `shapes.error_text`
needs no `doc`-specific branch the way it needed one for `HasChildren`.
"""

from __future__ import annotations

import re
from typing import Any

import psycopg
from mcp import types

from verticals.core import docs as core_docs
from verticals.core import goals as core_goals
from verticals.core.docs import MAX_DOC_BODY_BYTES, MAX_DOC_TITLE_CHARS, MAX_PATH_CHARS
from verticals.core.errors import ValidationError
from verticals.core.idem import MAX_CLIENT_TOKEN_CHARS
from verticals.models import Doc, DocRevision, DocRevisionSummary, DocSummary, GoalLink
from verticals.mcp.shapes import ok

_CLIENT_TOKEN_PROP: dict[str, Any] = {
    "type": ["string", "null"],
    "maxLength": MAX_CLIENT_TOKEN_CHARS,
    "description": "Optional idempotency key, matching the existing mutation surface.",
}

_TITLE_PROP: dict[str, Any] = {"type": ["string", "null"], "maxLength": MAX_DOC_TITLE_CHARS}
_PATH_PROP: dict[str, Any] = {
    "type": "string",
    "minLength": 1,
    "maxLength": MAX_PATH_CHARS,
    "description": "Relative, '/'-separated, every segment non-empty, must end '.md'.",
}
_BODY_PROP: dict[str, Any] = {
    "type": "string",
    "description": f"Markdown, at most {MAX_DOC_BODY_BYTES} UTF-8 bytes.",
}

# --- schemas ------------------------------------------------------------------------------------

DOC_CREATE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "path": _PATH_PROP,
        "title": _TITLE_PROP,
        "body": _BODY_PROP,
        "client_token": _CLIENT_TOKEN_PROP,
    },
    "required": ["path"],
}

DOC_GET_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "id": {"type": "string", "description": "Exactly one of id or path is required."},
        "path": {"type": "string", "maxLength": MAX_PATH_CHARS, "description": "Exactly one of id or path is required."},
    },
    "required": [],
}

DOC_SAVE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "id": {"type": "string"},
        "expected_revision": {
            "type": "integer",
            "minimum": 1,
            "description": "Optimistic lock — the doc's current revision. A mismatch is refused, naming the current revision.",
        },
        "title": _TITLE_PROP,
        "body": {"type": ["string", "null"], "description": _BODY_PROP["description"]},
        "path": {"type": ["string", "null"], "maxLength": MAX_PATH_CHARS},
        "client_token": _CLIENT_TOKEN_PROP,
    },
    "required": ["id", "expected_revision"],
}

DOC_TREE_SCHEMA: dict[str, Any] = {"type": "object", "additionalProperties": False, "properties": {}, "required": []}

DOC_HISTORY_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {"id": {"type": "string"}},
    "required": ["id"],
}

DOC_REVISION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "id": {"type": "string"},
        "revision": {"type": "integer", "minimum": 1},
    },
    "required": ["id", "revision"],
}

DOC_RESTORE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "id": {"type": "string"},
        "revision": {"type": "integer", "minimum": 1, "description": "Which past revision's text to copy forward."},
        "expected_revision": {
            "type": "integer",
            "minimum": 1,
            "description": "Optimistic lock on the doc's current state (not on the revision being restored).",
        },
        "client_token": _CLIENT_TOKEN_PROP,
    },
    "required": ["id", "revision", "expected_revision"],
}

DOC_DELETE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "id": {"type": "string"},
        "client_token": _CLIENT_TOKEN_PROP,
    },
    "required": ["id"],
}

_DOC_REF_PROP: dict[str, Any] = {
    "type": "string",
    "maxLength": MAX_PATH_CHARS,
    "description": "A document's id or its path — a trailing '.md' is read as a path, anything else as an id.",
}

# D254 (KK, 2026-08-24): the verb gap a desk agent found (goal card xMSR1MXF) — D250 made links
# text-derived ("links live in the text and only in the text") but never gave an agent a verb to
# attach or detach one; an agent looks for a tool, not a text convention. `doc_link`/`doc_unlink`
# are GOAL-BODY text edits through `core.goals.update` (which already reruns
# `core.docs.rewrite_goal_links` on every body write) — never a direct `goal_doc_links` row. See
# `handle_doc_link`/`handle_doc_unlink` below and `docs/parity/DECISIONS.md` D254 for the full
# idempotency table and the goal-side-append design (a link living in the goal's own body survives
# any `doc_save`, unlike a doc-side link, which is only as current as that document's last save).
DOC_LINK_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "goal_id": {"type": "string"},
        "doc": _DOC_REF_PROP,
        "client_token": _CLIENT_TOKEN_PROP,
    },
    "required": ["goal_id", "doc"],
}

DOC_UNLINK_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "goal_id": {"type": "string"},
        "doc": _DOC_REF_PROP,
        "client_token": _CLIENT_TOKEN_PROP,
    },
    "required": ["goal_id", "doc"],
}

TOOLS: tuple[types.Tool, ...] = (
    types.Tool(name="doc_create", description="Create a document at a given path, revision 1. A duplicate path for this owner is refused, never silently overwritten. Links between goals and documents live as plain markdown in text — '[label](doc:path)' in a goal's body, '[label](goal:id)' in a document's body — but doc_link/doc_unlink are the safe verbs for editing a goal's side; use them instead of hand-writing the link. A goal already inherits every document its ancestors link (see the goal tool's inherited_from) — do not link the same document again on a descendant goal.", input_schema=DOC_CREATE_SCHEMA),
    types.Tool(name="doc_get", description="Read one document in full, by id or by path, including every goal it links to or is linked from. linked_goals is derived from '[label](goal:id)' markdown links in this document's own body — doc_link/doc_unlink manage the same relationship from a goal's side, safely, without hand-editing text.", input_schema=DOC_GET_SCHEMA),
    types.Tool(name="doc_save", description="Edit a document's title, body or path. Optimistically locked on expected_revision; every save appends a new revision, nothing is ever rewritten in place. A link a goal holds to this document lives in the GOAL's own body, not here, so it survives any doc_save untouched. A goal already inherits every document its ancestors link — do not link the same document again on a descendant goal.", input_schema=DOC_SAVE_SCHEMA),
    types.Tool(name="doc_tree", description="Every document for this owner, flat and path-ordered — derive your own folder grouping from the '/' separators yourself.", input_schema=DOC_TREE_SCHEMA),
    types.Tool(name="doc_history", description="A document's revision list, oldest first: revision number, path, title and body length per revision — never the body text itself.", input_schema=DOC_HISTORY_SCHEMA),
    types.Tool(name="doc_revision", description="One past revision of a document in full, including its body text.", input_schema=DOC_REVISION_SCHEMA),
    types.Tool(name="doc_restore", description="Copy a past revision's title and body forward as a brand new revision. The current path is left untouched; optimistically locked on expected_revision.", input_schema=DOC_RESTORE_SCHEMA),
    types.Tool(name="doc_delete", description="Remove a document. Refused while any goal still links it, naming every linked goal id — remove the link(s) first (doc_unlink, on each linking goal).", input_schema=DOC_DELETE_SCHEMA),
    types.Tool(name="doc_link", description="Attach an existing document to a goal by appending '[title](doc:path)' to the goal's own body — the safe verb for what would otherwise be a hand-written text edit; retry-safe, since re-linking an already-linked document succeeds without writing again. Refused, naming the ancestor, when the goal already inherits this document from an ancestor (every descendant inherits every ancestor-linked document automatically — see the goal tool's inherited_from — so linking it again here would be redundant).", input_schema=DOC_LINK_SCHEMA),
    types.Tool(name="doc_unlink", description="Remove every '[label](doc:path)' link to a document from a goal's own body — the safe verb for the same text, never touching the document or any of its revisions. A no-op success when the goal did not link it directly. If the document's own body still names this goal back ('[label](goal:id)'), that link is reported but left standing — unlink it from the document's own side (doc_save) to remove it too.", input_schema=DOC_UNLINK_SCHEMA),
)


# --- output shaping -------------------------------------------------------------------------------
# Field-for-field mirrors of `verticals/api/schemas.py`'s own `doc_to_summary`/`doc_to_detail`/
# `doc_revision_to_json`/`doc_revision_detail_to_json` (S-33's own reasoning, carried over from
# goals to docs by WP-1: a card never carries `body`; the one detail shape does). Datetimes go
# through `.isoformat()`, matching `verticals/mcp/shapes.py::goal_dict` — JSON has no datetime
# type, and the MCP wire is JSON same as HTTP's.


def _doc_summary_dict(d: DocSummary) -> dict[str, Any]:
    return {"id": d.id, "path": d.path, "title": d.title, "updated_at": d.updated_at.isoformat(), "revision": d.revision}


def _doc_detail_dict(d: Doc, *, links: tuple[GoalLink, ...] = ()) -> dict[str, Any]:
    return {
        "id": d.id,
        "path": d.path,
        "title": d.title,
        "body": d.body,
        "revision": d.revision,
        "created_at": d.created_at.isoformat(),
        "updated_at": d.updated_at.isoformat(),
        "linked_goals": [{"goal_id": g.goal_id, "title": g.title, "source": g.source} for g in links],
    }


def _doc_revision_summary_dict(r: DocRevisionSummary) -> dict[str, Any]:
    return {"revision": r.revision, "path": r.path, "title": r.title, "saved_at": r.saved_at.isoformat(), "body_length": r.body_length}


def _doc_revision_detail_dict(r: DocRevision) -> dict[str, Any]:
    return {"doc_id": r.doc_id, "revision": r.revision, "path": r.path, "title": r.title, "body": r.body, "saved_at": r.saved_at.isoformat()}


# --- handlers -----------------------------------------------------------------------------------


def handle_doc_create(conn: psycopg.Connection, owner: str, args: dict[str, Any]) -> types.CallToolResult:
    created = core_docs.create(conn, owner=owner, path=args["path"], title=args.get("title"), body=args.get("body", ""))
    return ok(f"Created doc {created.doc.path!r} [{created.doc.id}]", {"doc": _doc_detail_dict(created.doc)})


def handle_doc_get(conn: psycopg.Connection, owner: str, args: dict[str, Any]) -> types.CallToolResult:
    id_ = args.get("id")
    path = args.get("path")
    if (id_ is None) == (path is None):
        raise ValidationError("doc_get needs exactly one of id or path", field="id,path")
    doc = core_docs.get(conn, owner=owner, id=id_) if id_ is not None else core_docs.get_by_path(conn, owner=owner, path=path)
    links = core_docs.links_for_doc(conn, owner=owner, doc_id=doc.id)
    return ok(f"{doc.path!r} [{doc.id}]", {"doc": _doc_detail_dict(doc, links=links)})


def handle_doc_save(conn: psycopg.Connection, owner: str, args: dict[str, Any]) -> types.CallToolResult:
    updated = core_docs.save(
        conn,
        owner=owner,
        id=args["id"],
        expected_revision=args["expected_revision"],
        title=args.get("title"),
        body=args.get("body"),
        path=args.get("path"),
    )
    return ok(f"Saved doc [{updated.doc.id}] as revision {updated.doc.revision}", {"doc": _doc_detail_dict(updated.doc)})


def handle_doc_tree(conn: psycopg.Connection, owner: str, args: dict[str, Any]) -> types.CallToolResult:
    summaries = core_docs.tree(conn, owner=owner)
    return ok(f"{len(summaries)} doc(s)", {"docs": [_doc_summary_dict(s) for s in summaries]})


def handle_doc_history(conn: psycopg.Connection, owner: str, args: dict[str, Any]) -> types.CallToolResult:
    revisions = core_docs.history(conn, owner=owner, id=args["id"])
    return ok(f"{len(revisions)} revision(s) for doc [{args['id']}]", {"revisions": [_doc_revision_summary_dict(r) for r in revisions]})


def handle_doc_revision(conn: psycopg.Connection, owner: str, args: dict[str, Any]) -> types.CallToolResult:
    rev = core_docs.get_revision(conn, owner=owner, id=args["id"], revision=args["revision"])
    return ok(f"doc [{rev.doc_id}] revision {rev.revision}", {"revision": _doc_revision_detail_dict(rev)})


def handle_doc_restore(conn: psycopg.Connection, owner: str, args: dict[str, Any]) -> types.CallToolResult:
    updated = core_docs.restore(
        conn, owner=owner, id=args["id"], revision=args["revision"], expected_revision=args["expected_revision"]
    )
    return ok(
        f"Restored doc [{updated.doc.id}] revision {args['revision']} forward as revision {updated.doc.revision}",
        {"doc": _doc_detail_dict(updated.doc)},
    )


def handle_doc_delete(conn: psycopg.Connection, owner: str, args: dict[str, Any]) -> types.CallToolResult:
    core_docs.delete(conn, owner=owner, id=args["id"])
    return ok(f"Deleted doc [{args['id']}]", {"deleted": True, "id": args["id"]})


# --- doc_link / doc_unlink (D254) ----------------------------------------------------------------
#
# Both verbs edit the GOAL's own body text through `core.goals.update` — never a direct write into
# `goal_doc_links` — because `update()` already reruns `core.docs.rewrite_goal_links` on every
# body write (`core/goals.py::update`'s own comment), so the derived cache can never drift from
# what these two verbs actually changed. See `docs/parity/DECISIONS.md` D254 for why the link is
# appended to the GOAL's body rather than the document's: it survives any later `doc_save`,
# whereas a doc-side link is only as current as that document's own last save.

_DOC_LINK_MARKDOWN_RE_TEMPLATE = r"\[[^\]]*\]\(\s*doc:{path}\s*\)"


def _resolve_doc(conn: psycopg.Connection, *, owner: str, ref: str) -> Doc:
    """`doc` is one field accepting either an id or a path — unambiguous by construction:
    `core.docs.validate_path` requires a path to end `.md`, and `core.field_rules.generate_id`'s
    alphabet (letters and digits only, 8 chars) can never produce a string ending `.md`."""
    if ref.endswith(".md"):
        return core_docs.get_by_path(conn, owner=owner, path=ref)
    return core_docs.get(conn, owner=owner, id=ref)


def _append_link_line(body: str, link_line: str) -> str:
    """The link lands on its own line at the END of the body, blank-line-separated from whatever
    came before (never touching existing text) — an empty body just becomes the link line."""
    body = body or ""
    if not body:
        return link_line
    if not body.endswith("\n"):
        body += "\n"
    if not body.endswith("\n\n"):
        body += "\n"
    return body + link_line


def _strip_doc_links(body: str, doc_path: str) -> str:
    """Removes every `[label](doc:<doc_path>)` occurrence from `body`'s text, then drops any line
    that removal left with nothing but whitespace on it (D254: "tidy up a line left empty by the
    removal") — a line that still carries other text around the removed link is left as-is.
    Consecutive blank lines left behind collapse to at most one, and trailing blank lines are
    trimmed, mirroring `core.markdown._body_lines`'s own collapse rule elsewhere in this codebase.
    Returns `body` byte-identical when there was nothing to remove, which is what makes the
    caller's idempotent no-op check (`new_body == original_body`) correct."""
    pattern = re.compile(_DOC_LINK_MARKDOWN_RE_TEMPLATE.format(path=re.escape(doc_path)))
    lines = (body or "").split("\n")

    kept: list[str] = []
    for line in lines:
        stripped = pattern.sub("", line)
        if stripped != line and stripped.strip() == "":
            continue  # the removal left nothing (or only whitespace) on this line — drop it
        kept.append(stripped)

    collapsed: list[str] = []
    prev_blank = False
    for line in kept:
        blank = line.strip() == ""
        if blank and prev_blank:
            continue
        collapsed.append(line)
        prev_blank = blank
    while collapsed and collapsed[-1].strip() == "":
        collapsed.pop()

    return "\n".join(collapsed)


def handle_doc_link(conn: psycopg.Connection, owner: str, args: dict[str, Any]) -> types.CallToolResult:
    goal_id = args["goal_id"]
    doc = _resolve_doc(conn, owner=owner, ref=args["doc"])
    detail = core_goals.goal(conn, owner=owner, id=goal_id)  # NotFound for an unknown goal

    existing = core_docs.links_for_goal_with_inherited(
        conn, owner=owner, goal_id=goal_id, ancestors=tuple(reversed(detail.ancestors))
    )
    for link in existing:
        if link.doc_id != doc.id:
            continue
        if link.inherited_from is None:
            # (a) already OWN-linked — success, no write, retry-safe.
            return ok(
                f"{doc.path!r} is already linked to {goal_id!r} — nothing written",
                {
                    "goal_id": goal_id, "doc_id": doc.id, "doc_path": doc.path,
                    "already_linked": True, "inherited_from": None,
                },
            )
        # (b) already INHERITED from an ancestor — refused, naming that ancestor, never
        # silently collapsed into a redundant own link.
        raise ValidationError(
            f"{doc.path!r} already reaches {goal_id!r} by inheritance from ancestor "
            f"{link.inherited_from.title!r} [{link.inherited_from.id}] — linking it again here "
            f"would be redundant; every descendant already inherits it",
            field="doc",
            inherited_from={"id": link.inherited_from.id, "title": link.inherited_from.title},
        )

    label = doc.title or doc.path
    new_body = _append_link_line(detail.goal.body, f"[{label}](doc:{doc.path})")
    core_goals.update(conn, owner=owner, id=goal_id, body=new_body)
    return ok(
        f"Linked {doc.path!r} to {goal_id!r}",
        {
            "goal_id": goal_id, "doc_id": doc.id, "doc_path": doc.path,
            "already_linked": False, "inherited_from": None,
        },
    )


def handle_doc_unlink(conn: psycopg.Connection, owner: str, args: dict[str, Any]) -> types.CallToolResult:
    goal_id = args["goal_id"]
    doc = _resolve_doc(conn, owner=owner, ref=args["doc"])
    detail = core_goals.goal(conn, owner=owner, id=goal_id)  # NotFound for an unknown goal

    original_body = detail.goal.body or ""
    new_body = _strip_doc_links(original_body, doc.path)

    # A DOC-side link (the document's own body naming this goal, source='doc') is never touched
    # by this verb — reported so the caller knows the relationship persists from the other side.
    doc_side_remains = any(
        link.doc_id == doc.id and link.source == "doc"
        for link in core_docs.links_for_goal(conn, owner=owner, goal_id=goal_id)
    )

    if new_body == original_body:
        return ok(
            f"{doc.path!r} was not linked from {goal_id!r}'s own body — nothing to remove",
            {
                "goal_id": goal_id, "doc_id": doc.id, "doc_path": doc.path,
                "removed": False, "doc_side_link_remains": doc_side_remains,
            },
        )

    core_goals.update(conn, owner=owner, id=goal_id, body=new_body)
    text = f"Unlinked {doc.path!r} from {goal_id!r}"
    if doc_side_remains:
        text += " (the document's own body still links this goal back — unchanged)"
    return ok(
        text,
        {
            "goal_id": goal_id, "doc_id": doc.id, "doc_path": doc.path,
            "removed": True, "doc_side_link_remains": doc_side_remains,
        },
    )
