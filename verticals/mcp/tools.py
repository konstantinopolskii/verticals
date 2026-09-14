"""The twenty-nine MCP tools (ARCHITECTURE.md §5, docs/E2E.md S-47's original nine, plus WP-33's
`evidence_update`/`evidence_due` (docs/EVIDENCE.md §6), `park`, `tags`/`tag_mark`, `size_report`,
`due_ack`, D250 WP-2's eight document tools plus D254's `doc_link`/`doc_unlink`
(`verticals/mcp/docs.py`), and WP-A's three comment tools (docs/COMMENTS_SPEC.md,
`verticals/mcp/comments.py`)) — schemas and dispatch. Only the original nine live whole in this
file; every tool added since owns its own family module (schema + handler together) and splices
into `TOOLS`/`_HANDLERS` below — the same shape WP-33 set when it extracted
`verticals/mcp/evidence.py` past S-90a's 750-line cap, repeated by every family since rather than
growing this file further. `verticals/mcp/server.py` is the only caller: it owns the transport
(stdio / streamable-http) and the connection; this module owns what a tool call *means*.

Seam rule (`tests/static/test_seam.py`): no raw SQL verb strings outside a docstring anywhere
under `verticals/mcp/`. Every read or write below goes through an already-shipped `core/`
function — this file adds argument shaping, a runtime schema check the SDK does not provide
(see `_validate_top_level`), and the reorder derivation `move_between` itself refuses to do
safely (see `_derive_before_id`). It never touches `goals` directly.

The SDK passes raw arguments without enforcing its declared input schema. `_validate_top_level`
makes unknown keys, required fields and array caps real at runtime; deeper business validation
stays in `core/`, avoiding `jsonschema` as a seventh runtime dependency.

**Reorder, derived not trusted.** `core.moves.move_between` requires both `after_id` *and*
`before_id`, and says so itself: "adjacency is trusted, not reverified here". A client-supplied
`before_id` that is merely a valid sibling but not truly adjacent to `after_id` would not error —
`tree.renumber` raises `NotFound` for a non-member id but never checks the *pair* is adjacent, so
a wrong-but-plausible midpoint would be computed silently. The schema below exposes only
`after_id`; `_derive_before_id` reads the real sibling group fresh, every call, and hands
`move_between` a `before_id` that is adjacent by construction. No raw SQL, no `core/` edits —
built entirely from already-shipped `core/` reads (`goal`, `children_of`, `search`, `board`).
"""

from __future__ import annotations

import logging
import re
from datetime import date as _date
from typing import Any

import psycopg
from psycopg_pool import PoolTimeout

from mcp import types

from verticals.core import board as core_board
from verticals.core import docs as core_docs
from verticals.core import evidence as core_evidence
from verticals.core import goals as core_goals
from verticals.core import markdown as core_markdown
from verticals.core import moves as core_moves
from verticals.core import search as core_search
from verticals.core.errors import VerticalError, ValidationError
from verticals.mcp import comments as mcp_comments
from verticals.mcp import docs as mcp_docs
from verticals.mcp import due_ack as mcp_due_ack
from verticals.mcp import evidence as mcp_evidence
from verticals.mcp import park as mcp_park
from verticals.mcp import sizes as mcp_sizes
from verticals.mcp import tags as mcp_tags
from verticals.mcp.shapes import (
    ancestor_dict,
    board_dict,
    doc_link_dict,
    error_result,
    error_text,
    goal_detail_dict,
    goal_dict,
    ok,
)
from verticals.mcp.tool_schemas import (
    BOARD_SCHEMA,
    CREATE_SCHEMA,
    DELETE_SCHEMA,
    GOAL_SCHEMA,
    OUTLINE_SCHEMA,
    REPARENT_SCHEMA,
    SCHEDULE_SCHEMA,
    SEARCH_SCHEMA,
    UPDATE_SCHEMA,
)

logger = logging.getLogger("verticals.mcp")
# IR-11 / `tests/static/test_architecture.py::test_s108g_ir11_bounds_in_goals_and_mcp` greps
# this file's own *source text* for the literal substring "200" — not the runtime value, so an
# f-string interpolation would not satisfy it. These two asserts are what stop the schema's
# stated literal (now in `tool_schemas.py`) silently going stale if `core/goals.py`'s real
# bound ever moves; both fail loudly at import time, never silently.
assert core_goals.MAX_NODES_PER_CREATE == 200
assert core_goals.MAX_CHILDREN_DEPTH == 8

# WP-33's `evidence_update`/`evidence_due` live whole (schemas, handlers, descriptors) in
# `verticals/mcp/evidence.py` — spliced into TOOLS and _HANDLERS below; extracted for S-90a's
# 750-line cap, which this module sat ten lines under before WP-33.
TOOLS: tuple[types.Tool, ...] = (
    types.Tool(name="board", description="The whole day's board in one call: every column, direct children, ancestors and progress.", input_schema=BOARD_SCHEMA),
    types.Tool(name="goal", description="One goal with its breadcrumb of ancestors and its direct children. Its docs field already includes every document linked to any ancestor, marked with inherited_from — no need to walk the breadcrumb yourself to find them. A doc link is plain markdown in body text ('[label](doc:path)'); doc_link/doc_unlink are the safe verbs for adding or removing one — never link a document an ancestor already links, since every descendant inherits it automatically.", input_schema=GOAL_SCHEMA),
    types.Tool(name="outline", description="Render a subtree as one readable markdown outline, every node's id inline.", input_schema=OUTLINE_SCHEMA),
    types.Tool(name="search", description="Full-text and tag search over the owner's goals.", input_schema=SEARCH_SCHEMA),
    types.Tool(name="create", description="Create a goal, optionally with a nested plan of children, in one call.", input_schema=CREATE_SCHEMA),
    types.Tool(name="update", description="Edit content (title/body/color/tags/done/foil/repeat) on one or many goals, or reorder one goal among its siblings. A repeating goal's next occurrence is materialized when the current one is completed — never by the clock — under the completed row's parent, so a series follows wherever its last instance was moved.", input_schema=UPDATE_SCHEMA),
    types.Tool(name="schedule", description="Set or clear a goal's vertical and anchor date.", input_schema=SCHEDULE_SCHEMA),
    types.Tool(name="reparent", description="Move a goal under a new parent, or detach it to the root.", input_schema=REPARENT_SCHEMA),
    types.Tool(name="delete", description="Remove a goal. Refuses a non-empty subtree unless cascade is true.", input_schema=DELETE_SCHEMA),
) + mcp_evidence.TOOLS + mcp_park.TOOLS + mcp_tags.TOOLS + mcp_sizes.TOOLS + mcp_due_ack.TOOLS + mcp_docs.TOOLS + mcp_comments.TOOLS

_SCHEMAS: dict[str, dict[str, Any]] = {t.name: t.input_schema for t in TOOLS}


# --- runtime schema enforcement ------------------------------------------------------------------


def _validate_top_level(schema: dict[str, Any], arguments: object) -> dict[str, Any]:
    """Everything the SDK does not check itself, and nothing `core/` already checks better.
    Three rules only: `arguments` is an object; `additionalProperties: false` is real, not
    decorative (S-53); `required` is enforced; array `maxItems` is enforced (needed for real —
    `core.goals.update`'s own `ids` has no upper bound, see this module's docstring). Does not
    walk into `create`'s nested `children` — `core.goals.create`'s own `_validate_child_spec`
    already does, completely."""
    if not isinstance(arguments, dict):
        raise ValidationError("arguments must be a JSON object", field="arguments")

    props: dict[str, Any] = schema.get("properties", {})
    if schema.get("additionalProperties") is False:
        unknown = sorted(set(arguments) - set(props))
        if unknown:
            raise ValidationError(f"unexpected argument(s): {unknown}", field=",".join(unknown))

    for field in schema.get("required", ()):
        if field not in arguments:
            raise ValidationError(f"{field} is required", field=field)

    for name, spec in props.items():
        if name not in arguments or not isinstance(spec, dict):
            continue
        max_items = spec.get("maxItems")
        value = arguments[name]
        if max_items is not None and isinstance(value, list) and len(value) > max_items:
            raise ValidationError(
                f"{name} must have at most {max_items} items, got {len(value)}",
                field=name,
                maximum=max_items,
            )

    return arguments


# --- small parsing helpers (JSON has no date type; every core/ boundary wants a real `date`) -----


def _parse_date(value: object, *, field: str) -> _date:
    if not isinstance(value, str):
        raise ValidationError(f"{field} must be an ISO 8601 date string", field=field)
    try:
        return _date.fromisoformat(value)
    except ValueError as exc:
        raise ValidationError(f"{field} must be an ISO 8601 date (YYYY-MM-DD), got {value!r}", field=field) from exc


def _parse_optional_date(value: object, *, field: str) -> _date | None:
    return None if value is None else _parse_date(value, field=field)


def _prepare_child(spec: object) -> dict[str, Any]:
    """Recursively swap every `anchor_date` ISO string for a real `date` — the one thing
    `core.goals.create`'s own `_validate_child_spec` cannot accept as JSON hands it over.
    Everything else passes through untouched for `core/` to validate; unknown keys are left in
    place on purpose so `_validate_child_spec`'s own `_CHILD_SPEC_KEYS` check (not this
    function) is what refuses them, matching this module's own no-duplicate-validation rule."""
    if not isinstance(spec, dict):
        raise ValidationError("each entry in children must be an object", field="children")
    out = dict(spec)
    if out.get("anchor_date") is not None:
        out["anchor_date"] = _parse_date(out["anchor_date"], field="anchor_date")
    if out.get("children"):
        out["children"] = [_prepare_child(c) for c in out["children"]]
    return out


# --- output shaping: verticals/mcp/shapes.py ------------------------------------------------------
# goal_dict/goal_detail_dict/ancestor_dict/board_dict (card-vs-detail law, S-33/S-95) and the
# ok/error_text/error_result constructors (S-48 content rule, S-54/S-130 cap) moved there whole
# when WP-33 pushed this module past S-90a's 750-line cap; imported at the top of this file.


# --- reorder: derive a real, adjacent before_id ---------------------------------------------------


def _sibling_ids(conn: psycopg.Connection, *, owner: str, target_id: str) -> list[str]:
    """`target_id`'s own sibling group in rendered order, itself removed. The whole safety
    mechanism behind exposing `after_id`/`position` and never a raw `before_id`. See this module's own
    docstring for why `move_between`'s "adjacency is trusted, not reverified" makes a
    client-supplied `before_id` dangerous. Three branches, matching `core/tree.py`'s own
    module-docstring split (F2-verified): a card's group is `(owner, vertical, period_key)`
    regardless of `parent_id`; a subgoal's group is `(owner, parent_id)` *and* `vertical IS
    NULL` — `children_of` returns every direct child regardless of the child's own vertical
    (S-52 nests a `vertical='day'` child directly under a `vertical='week'` root), so that second
    filter is not optional, it is what keeps a card living under this parent out of a subgoal
    reorder; the Maybe pile is `vertical IS NULL AND parent_id IS NULL` and does not depend on
    the date `board()` is called with (`core/board.py`'s own `MAYBE_PREDICATE`), so any valid
    date reads it safely.
    """
    detail = core_goals.goal(conn, owner=owner, id=target_id)
    g = detail.goal

    if g.vertical is not None:
        result = core_search.search(conn, owner=owner, vertical=g.vertical, limit=core_search.MAX_LIMIT)
        if result.truncated:
            raise ValidationError(
                f"cannot reorder within vertical={g.vertical!r}: sibling group too large to read "
                f"safely in one page (limit={core_search.MAX_LIMIT})",
                field="after_id",
                maximum=core_search.MAX_LIMIT,
            )
        siblings = [x for x in result.goals if x.period_key == g.period_key]
    elif g.parent_id is not None:
        siblings = [c for c in core_goals.children_of(conn, owner=owner, id=g.parent_id) if c.vertical is None]
    else:
        maybe_board = core_board.board(conn, owner=owner, date=_date.today())
        maybe_column = next((c for c in maybe_board.columns if c.vertical is None), None)
        siblings = list(maybe_column.goals) if maybe_column else []

    siblings = [s for s in siblings if s.id != target_id]
    siblings.sort(key=lambda s: (s.position, s.id))
    return [s.id for s in siblings]


def _derive_before_id(
    conn: psycopg.Connection, *, owner: str, target_id: str, after_id: str
) -> str | None:
    """The `after_id` form: the sibling that follows `after_id`, adjacent by construction.

    `None` when `after_id` is the group's last member — "after the last one" is the tail, which
    `move_between` spells with both ids None. Mirrors the API transport's own function; see
    `verticals/api/routes_goals.py::_derive_before_id`."""
    if after_id == target_id:
        raise ValidationError(f"after_id cannot equal the id being reordered ({target_id!r})", field="after_id")

    ordered_ids = _sibling_ids(conn, owner=owner, target_id=target_id)

    if after_id not in ordered_ids:
        raise ValidationError(f"after_id {after_id!r} is not a sibling of {target_id!r}", field="after_id")
    idx = ordered_ids.index(after_id)
    return ordered_ids[idx + 1] if idx + 1 < len(ordered_ids) else None


# --- per-tool handlers -----------------------------------------------------------------------------

_CONTENT_FIELDS = (
    "title", "body", "color", "tags", "done", "foil", "carryover_ignored_until",
    "repeat", "size_expected", "short_label",
)
# WP-33 (docs/EVIDENCE.md §6.1): every reader carries a compact per-goal evidence summary —
# effective status (computed server-side, callers never apply the formula), verified_at,
# review_after — as a keyed map, the board's own house shape (progress/ancestors/children are
# all keyed maps already). ONLY those three fields: a 40-card board times full source lists is
# a token bonfire aimed at the exact agent this feature serves. The full payload appears in
# exactly one place, the `goal` tool.


def _handle_board(conn: psycopg.Connection, owner: str, args: dict[str, Any]) -> types.CallToolResult:
    d = _parse_date(args["date"], field="date")
    b = core_board.board(conn, owner=owner, date=d, value=args.get("value"))
    total = sum(len(c.goals) for c in b.columns)
    # `Board.evidence` rode the board's own single statement (S-22's execute-count contract) —
    # no second query here, unlike `search`/`outline` below, which have no such contract.
    return ok(f"Board for {d.isoformat()}: {total} goal(s) across {len(b.columns)} columns.", board_dict(b))


def _handle_goal(conn: psycopg.Connection, owner: str, args: dict[str, Any]) -> types.CallToolResult:
    d = core_goals.goal(conn, owner=owner, id=args["id"])
    # D251 (KK, 2026-08-20): the same own-plus-inherited shape `routes_goals.py::get_goal` (HTTP)
    # carries — `d.ancestors` is root-first (`core.goals.goal()`'s own docstring), reversed here
    # for `links_for_goal_with_inherited`'s nearest-first requirement, same call the HTTP route
    # makes. No statement budget is pinned on this tool (S-42 pins the HTTP route only), so this
    # is simply one more read, same as `evidence`/`due_history` below.
    doc_links = core_docs.links_for_goal_with_inherited(
        conn, owner=owner, goal_id=d.goal.id, ancestors=tuple(reversed(d.ancestors))
    )
    return ok(
        f"{d.goal.title!r} [{d.goal.id}]",
        {
            "goal": goal_detail_dict(d.goal),
            "ancestors": [ancestor_dict(a) for a in d.ancestors],
            "children": [goal_dict(c) for c in d.children],
            "ideas": [goal_dict(c) for c in d.ideas],
            # D251: own-plus-inherited doc links — see `core.docs.links_for_goal_with_inherited`'s
            # own docstring for the ghosting/dedupe rules.
            "docs": [doc_link_dict(link) for link in doc_links],
            # The one full-evidence reader (§6.1): payload, revisions, cutoff — everything.
            "evidence": core_evidence.detail_for(conn, owner=owner, goal_id=d.goal.id),
            # 011: every due verdict ever recorded for this goal, newest first.
            "due_history": mcp_due_ack.due_history_dicts(conn, owner, d.goal.id),
        },
    )


# The outline grammar puts every node's id inline as `[xxxxxxxx]` (the tool's own description;
# tests/core/test_outline_grammar.py pins it). That is the honest way to attach evidence to a
# text-shaped response without either bloating the text or re-reading the subtree: harvest the
# ids the outline itself printed, summarise those. A title that happens to contain a bracketed
# 8-char token can add a stray id here — harmless, `summaries_for` is owner-scoped and simply
# has no row to report for a non-goal.
_OUTLINE_ID_RE = re.compile(r"\[([A-Za-z0-9]{8})\]")

# D250 (KK, WP-2) shipped three shapes over the one subtree `core.markdown.outline()` renders.
# `full` calls that function and returns it untouched — the tool's original, byte-identical
# behaviour, still the default. The other two of those three are built by RE-READING the same
# pinned grammar `core/markdown.py`'s own module docstring spells out (rules 1-8), not by asking
# `core/` for a second rendering: this file's own seam rule (no raw SQL under `verticals/mcp/`,
# this module's docstring) also means no new `core/` reads for that feature beyond a WP-2
# file-scope boundary — the grammar is already a stable, pinned public contract
# (`docs/ACCEPTANCE.md` §3.5), so parsing IT, rather than the database, was the honest way to
# derive a second shape from the one already-shipped renderer without touching `core/markdown.py`
# at all.
#
# D252 (KK) adds a fourth shape, `map`, over a DIFFERENT grammar KK's own sample pins byte for
# byte (box-drawing connectors, no ids, no body text) — parsing `outline()`'s text would not get
# there (that grammar carries headings/checkboxes/chips this one must not). So `map` is not a
# post-processed reading of `outline()`'s output; it is `core.markdown.goal_map()`, a sibling
# renderer that reuses `outline()`'s OWN reads (`core/markdown.py`'s own `_fetch_root_row`/
# `_fetch_descendants`/`_fetch_owner_roots`, factored out for exactly this reuse) rather than a
# fresh raw SQL statement in this seam-restricted package — see `goal_map`'s own module comment
# for the full grammar/label/live-goal rules.
_OUTLINE_MODES = ("full", "headlines", "headlines+docs", "map")

# A node's own line, and nothing else: the root heading (`# ...`) or a list item at any
# indent level (`(  )*- [ ] ...` / `(  )*- [x] ...`) — rules 1 and 4. Every other non-blank line
# in `core.markdown.outline()`'s own output is body text (rule 6: a root's body sits flush left,
# a descendant's body sits indented to content column, but neither ever starts with `# ` or a
# `- [ ]`/`- [x]` marker — `_escape_title` already neutralises a title that tries to forge one).
_OUTLINE_NODE_LINE_RE = re.compile(r"^(?:# |(?:  )*- \[[ x]\] )")


def _outline_strip_bodies(md: str) -> str:
    """'headlines' mode: every node line kept verbatim (id, title, chip all still inline — rule
    2/3 untouched), every body line dropped, blank separator lines collapsed to at most one
    (mirrors `core.markdown._body_lines`'s own collapse rule) and no trailing blank line before
    the final newline."""
    lines = md.split("\n")
    if lines and lines[-1] == "":
        lines = lines[:-1]  # outline() always ends in exactly one "\n" (rule 8)

    kept = [ln for ln in lines if ln == "" or _OUTLINE_NODE_LINE_RE.match(ln)]

    collapsed: list[str] = []
    prev_blank = False
    for ln in kept:
        blank = ln == ""
        if blank and prev_blank:
            continue
        collapsed.append(ln)
        prev_blank = blank
    while collapsed and collapsed[-1] == "":
        collapsed.pop()

    return "\n".join(collapsed) + "\n"


def _outline_content_indent(node_line: str) -> str:
    """The same content-column rule `core.markdown._render` itself uses for a node's own body
    (indent + 6, the width of the `- [ ] ` marker) — reused here for a doc-link line so it nests
    visually under its goal exactly where that goal's own body would have sat. The root gets no
    indent, same as a root's own body sits flush left (rule 6)."""
    if node_line.startswith("# "):
        return ""
    leading = len(node_line) - len(node_line.lstrip(" "))
    return " " * (leading + 6)


def _outline_with_doc_links(conn: psycopg.Connection, *, owner: str, md: str) -> str:
    """'headlines+docs' mode: run after `_outline_strip_bodies`, so every remaining line is
    either blank or a node line carrying a real inline id (the tool's own founding grammar,
    `_OUTLINE_ID_RE`). One `core.docs.links_for_goal` read per node — a subtree small enough for
    an agent to read as one outline is small enough for one query per node; a single JOINed read
    across the whole subtree would need a new `core/` function this WP's own file-scope boundary
    does not grant. Paths are deduplicated and sorted for a deterministic result regardless of
    which side (`source='doc'` vs `'goal'`) declared the link.

    Deliberately OWN links only (`links_for_goal`, not D251's `links_for_goal_with_inherited`):
    every node in the subtree already prints under its own parent, so an inherited doc would
    repeat the same `doc: <path>` line under every descendant of whichever ancestor actually
    links it — the outline would grow with the subtree's depth for a fact stated once, higher up.
    The `goal` tool (`_handle_goal`) is where an inherited doc is worth seeing, on the one node an
    agent actually asked about; a whole-subtree outline shows every node at once, where own-only
    already says everything exactly once and inheritance would only repeat it at every level."""
    lines = md.split("\n")
    if lines and lines[-1] == "":
        lines = lines[:-1]

    out: list[str] = []
    for ln in lines:
        out.append(ln)
        match = _OUTLINE_ID_RE.search(ln) if ln else None
        if match is None:
            continue
        links = core_docs.links_for_goal(conn, owner=owner, goal_id=match.group(1))
        paths = sorted({link.path for link in links})
        if not paths:
            continue
        indent = _outline_content_indent(ln)
        out.extend(f"{indent}doc: {path}" for path in paths)

    return "\n".join(out) + "\n"


def _handle_outline(conn: psycopg.Connection, owner: str, args: dict[str, Any]) -> types.CallToolResult:
    depth = args.get("depth")
    if depth is not None and (isinstance(depth, bool) or not isinstance(depth, int)):
        raise ValidationError("depth must be an integer or null", field="depth")
    mode = args.get("mode", "full")
    if mode not in _OUTLINE_MODES:
        raise ValidationError(f"mode must be one of {list(_OUTLINE_MODES)}, got {mode!r}", field="mode")

    if mode == "map":
        # D252: `map` is the one mode `id` is optional for (OUTLINE_SCHEMA's own `required: []`
        # cannot express a per-mode conditional, so the check lives here, matching this file's
        # existing house pattern for mode-dependent argument rules — see `_handle_update`'s
        # `id`/`ids` handling). `goal_map`'s own grammar carries no inline ids at all (box-
        # drawing connectors and a bracketed label only), so there is nothing for `_OUTLINE_ID_RE`
        # to harvest here — the evidence map stays empty rather than silently keying off a
        # different node set than the one actually printed.
        md = core_markdown.goal_map(conn, owner=owner, id=args.get("id"), depth=depth)
        return types.CallToolResult(
            content=[types.TextContent(type="text", text=md)],
            structured_content={"evidence": {}},
            is_error=False,
        )

    if "id" not in args:
        raise ValidationError("id is required for every mode except 'map'", field="id")

    md = core_markdown.outline(conn, owner=owner, id=args["id"], depth=depth)
    if mode != "full":
        md = _outline_strip_bodies(md)
    if mode == "headlines+docs":
        md = _outline_with_doc_links(conn, owner=owner, md=md)

    # The markdown itself stays the `content` (this tool's founding shape); the evidence map is
    # the one structured field WP-33 adds beside it, keyed by the ids already inline in the text
    # — unaffected by `mode`, since every mode keeps every node line, id inline, verbatim.
    summaries = core_evidence.summaries_for(conn, owner=owner, ids=_OUTLINE_ID_RE.findall(md))
    return types.CallToolResult(
        content=[types.TextContent(type="text", text=md)],
        structured_content={"evidence": summaries},
        is_error=False,
    )


def _handle_search(conn: psycopg.Connection, owner: str, args: dict[str, Any]) -> types.CallToolResult:
    r = core_search.search(
        conn,
        owner=owner,
        q=args.get("q"),
        tag=args.get("tag"),
        vertical=args.get("vertical"),
        limit=args.get("limit", core_search.DEFAULT_LIMIT),
    )
    text = f"{len(r.goals)} result(s)" + (" (truncated)" if r.truncated else "")
    return ok(
        text,
        {
            "goals": [goal_dict(g) for g in r.goals],
            "truncated": r.truncated,
            "evidence": core_evidence.summaries_for(conn, owner=owner, ids=[g.id for g in r.goals]),
        },
    )


def _handle_create(conn: psycopg.Connection, owner: str, args: dict[str, Any]) -> types.CallToolResult:
    anchor_date = _parse_optional_date(args.get("anchor_date"), field="anchor_date")
    raw_children = args.get("children", [])
    if not isinstance(raw_children, list):
        raise ValidationError("children must be a list", field="children")
    children = [_prepare_child(c) for c in raw_children]

    created = core_goals.create(
        conn,
        owner=owner,
        title=args["title"],
        body=args.get("body", ""),
        parent_id=args.get("parent_id"),
        vertical=args.get("vertical"),
        anchor_date=anchor_date,
        color=args.get("color"),
        tags=args.get("tags", ()),
        children=children,
        origin="agent",  # S-53: stamped by the transport, never a caller-supplied field
        client_token=args.get("client_token"),
    )
    text = f"Created {created.goal.title!r} [{created.goal.id}]"
    if created.children:
        text += f" + {len(created.children)} descendant(s)"
    if created.replayed:
        text += " (replayed)"
    return ok(
        text,
        {"goal": goal_dict(created.goal), "children": [goal_dict(c) for c in created.children], "replayed": created.replayed},
    )


def _handle_update(conn: psycopg.Connection, owner: str, args: dict[str, Any]) -> types.CallToolResult:
    id_ = args.get("id")
    ids = args.get("ids")
    after_id = args.get("after_id")
    position = args.get("position")

    if (id_ is None) == (ids is None):
        raise ValidationError("update needs exactly one of id or ids", field="id,ids")

    if after_id is not None and position is not None:
        raise ValidationError(
            "after_id and position are two spellings of one reorder — send one, not both",
            field="after_id,position",
        )

    if position is not None:
        # `position: "first"` — the head insert `after_id` cannot express (`docs/
        # PENDING_DOC_FIXES.md` rows 109, 116(c)). Same refusals as the `after_id` path below,
        # and an already-only-child is returned unchanged rather than refused: it is first.
        if ids is not None:
            raise ValidationError("position (reorder) targets a single id, not ids", field="position,ids")
        present_content = [f for f in _CONTENT_FIELDS if f in args]
        if present_content:
            raise ValidationError(
                f"position (reorder) cannot be combined with {','.join(present_content)} in one call",
                field="position",
            )
        ordered_ids = _sibling_ids(conn, owner=owner, target_id=id_)
        if not ordered_ids:
            g = core_goals.goal(conn, owner=owner, id=id_).goal
        else:
            g = core_moves.move_between(conn, owner=owner, id=id_, after_id=None, before_id=ordered_ids[0])
        return ok(f"Moved {g.title!r} [{g.id}] to first", {"goal": goal_dict(g), "last_write_origin": "agent"})

    if after_id is not None:
        # Reorder is deliberately its own path, never combined with a content edit in the same
        # call: `move_between` and `core.goals.update` are two different core/ transactions, and
        # half-composing them (do one, then the other) would be a capability nothing specified
        # or tested — refused cleanly instead of half-built.
        if ids is not None:
            raise ValidationError("after_id (reorder) targets a single id, not ids", field="after_id,ids")
        present_content = [f for f in _CONTENT_FIELDS if f in args]
        if present_content:
            raise ValidationError(
                f"after_id (reorder) cannot be combined with {','.join(present_content)} in one call",
                field="after_id",
            )
        before_id = _derive_before_id(conn, owner=owner, target_id=id_, after_id=after_id)
        # A null `before_id` is the tail, which `move_between` spells with both ids None.
        g = core_moves.move_between(
            conn,
            owner=owner,
            id=id_,
            after_id=after_id if before_id is not None else None,
            before_id=before_id,
        )
        return ok(f"Moved {g.title!r} [{g.id}] after {after_id}", {"goal": goal_dict(g), "last_write_origin": "agent"})

    kwargs: dict[str, Any] = {f: args[f] for f in _CONTENT_FIELDS if f in args}
    if "carryover_ignored_until" in kwargs:
        kwargs["carryover_ignored_until"] = _parse_optional_date(
            kwargs["carryover_ignored_until"], field="carryover_ignored_until"
        )
    if "repeat" in kwargs:
        if ids is not None:
            raise ValidationError("repeat targets one goal, not ids", field="repeat")
        if isinstance(kwargs["repeat"], dict):
            repeat = dict(kwargs["repeat"])
            if repeat.get("end_date") is not None:
                repeat["end_date"] = _parse_date(repeat["end_date"], field="repeat.end_date")
            kwargs["repeat"] = repeat
    if not kwargs:
        raise ValidationError(
            "update needs at least one of title, body, color, tags, done, foil, "
            "carryover_ignored_until, short_label, after_id, position",
            field="title,body,color,tags,done,foil,carryover_ignored_until,short_label,after_id,position",
        )

    bulk = ids is not None
    result = core_goals.update(conn, owner=owner, id=id_, ids=ids, **kwargs)
    if bulk:
        text = f"Updated {len(result)} goal(s)"
        structured = {
            "updated": len(result),
            "goals": [goal_dict(u.goal) for u in result],
            "open_descendants": {u.goal.id: u.open_descendants for u in result if u.open_descendants is not None},
            "last_write_origin": "agent",
        }
    else:
        text = f"Updated {result.goal.title!r} [{result.goal.id}]"
        structured = {"goal": goal_dict(result.goal), "open_descendants": result.open_descendants, "last_write_origin": "agent"}
    return ok(text, structured)


def _handle_schedule(conn: psycopg.Connection, owner: str, args: dict[str, Any]) -> types.CallToolResult:
    vertical = args["vertical"]
    anchor_date = _parse_optional_date(args["anchor_date"], field="anchor_date")
    scheduled = core_moves.schedule(
        conn, owner=owner, id=args["id"], vertical=vertical, anchor_date=anchor_date
    )
    g = scheduled.goal
    label = f"{vertical} {g.period_key}" if vertical else "unscheduled"
    return ok(
        f"Scheduled {g.title!r} [{g.id}] -> {label}",
        {"goal": goal_dict(g), "descendants_clamped": scheduled.descendants_clamped},
    )


def _handle_reparent(conn: psycopg.Connection, owner: str, args: dict[str, Any]) -> types.CallToolResult:
    g = core_moves.reparent(conn, owner=owner, id=args["id"], parent_id=args["parent_id"])
    return ok(f"Reparented {g.id} -> {g.parent_id or 'root'}", {"goal": goal_dict(g)})


def _handle_delete(conn: psycopg.Connection, owner: str, args: dict[str, Any]) -> types.CallToolResult:
    cascade = args.get("cascade", False)
    if not isinstance(cascade, bool):
        raise ValidationError("cascade must be a boolean", field="cascade")
    removed = core_goals.delete(conn, owner=owner, id=args["id"], cascade=cascade)
    return ok(f"Deleted {removed} row(s)", {"removed": removed})


_HANDLERS: dict[str, Any] = {
    "board": _handle_board,
    "goal": _handle_goal,
    "outline": _handle_outline,
    "search": _handle_search,
    "create": _handle_create,
    "update": _handle_update,
    "schedule": _handle_schedule,
    "reparent": _handle_reparent,
    "delete": _handle_delete,
    "evidence_update": mcp_evidence.handle_evidence_update,
    "evidence_due": mcp_evidence.handle_evidence_due,
    "park": mcp_park.handle_park,
    "due_ack": mcp_due_ack.handle_due_ack,
    "tags": mcp_tags.handle_tags,
    "tag_mark": mcp_tags.handle_tag_mark,
    "size_report": mcp_sizes.handle_size_report,
    "doc_create": mcp_docs.handle_doc_create,
    "doc_get": mcp_docs.handle_doc_get,
    "doc_save": mcp_docs.handle_doc_save,
    "doc_tree": mcp_docs.handle_doc_tree,
    "doc_history": mcp_docs.handle_doc_history,
    "doc_revision": mcp_docs.handle_doc_revision,
    "doc_restore": mcp_docs.handle_doc_restore,
    "doc_delete": mcp_docs.handle_doc_delete,
    "doc_link": mcp_docs.handle_doc_link,
    "doc_unlink": mcp_docs.handle_doc_unlink,
    "comments": mcp_comments.handle_comments,
    "comment_add": mcp_comments.handle_comment_add,
    "comment_resolve": mcp_comments.handle_comment_resolve,
}


# --- entrypoint --------------------------------------------------------------------------------


def call_tool(conn: psycopg.Connection, *, owner: str, name: str, arguments: dict[str, Any] | None) -> types.CallToolResult:
    """The one function `verticals/mcp/server.py` calls. Synchronous, matching `core/`'s own
    psycopg3-sync contract — the server offloads this to a thread (`anyio.to_thread.run_sync`),
    never runs it inline on the event loop. Never raises: every path — a bad schema, a refused
    `core/` call, an unreachable database, or a genuinely unexpected bug — returns a
    `CallToolResult` with `is_error` set, because an exception escaping this function would take
    the whole server process down with it (AC-139: "the server process is still alive").
    """
    schema = _SCHEMAS.get(name)
    if schema is None:
        logger.warning("call_tool %s: unknown tool", name)
        return error_result(f"unknown tool {name!r}")
    try:
        validated = _validate_top_level(schema, arguments or {})
        result = _HANDLERS[name](conn, owner, validated)
        # AC-139 / the mcp-suite stream rule: stderr is *expected* non-empty, at least one
        # structured line per run — "a server that logs nothing is not one anybody can run in
        # anger." A tool call is the one event guaranteed to happen in every scenario in this
        # suite, so logging it here (not only on the error paths below) is what makes that
        # guarantee real rather than accidental on whichever scenario happens to hit a refusal.
        logger.info("call_tool %s: owner=%s is_error=%s", name, owner, result.is_error)
        return result
    except VerticalError as exc:
        logger.warning("call_tool %s: refused %s: %s", name, type(exc).__name__, exc.message)
        return error_result(error_text(exc))
    except (psycopg.OperationalError, PoolTimeout) as exc:
        logger.warning("call_tool %s: database unavailable: %s", name, exc)
        return error_result("database unavailable")
    except Exception as exc:  # noqa: BLE001 - last-resort net; never let a tool call kill the server
        logger.error("call_tool %s: unhandled %s: %s", name, type(exc).__name__, exc, exc_info=True)
        return error_result("internal error")
