"""Output shaping for the MCP tools — extracted verbatim from `verticals/mcp/tools.py` when
WP-33 pushed that module past S-90a's 750-line cap. Same seam rule applies (no raw SQL under
`verticals/mcp/`); this module holds no SQL and no handlers, only dataclass-to-dict serializers
and the two result constructors. `tools.py` (and `mcp/evidence.py`) import from here; nothing
here imports back — one direction, no cycle.

`content` is a short human-readable line, never a duplicate of `structured_content` — S-48's
128KB board budget is the reason: the MCP envelope already wraps the same JSON as the larger
wire, and mirroring the full payload into `content` too would roughly double it for no reader.
`outline` is the one exception: its natural shape is text, so the markdown itself is the
`content`, with no separate `structured_content` invented for it.

Card vs detail, matching `api/schemas.py::goal_to_card()` / `goal_to_detail()` field for field
(§10-D9, S-33: "No card in the response carries `body`; each carries `body_chars`"). A card
never carries `body`, only `body_chars` — the 64 KB per-goal cap would otherwise let one goal's
body cost as much as fifty board payloads (S-95). `goal_dict()` below is the card; it is what
every list- or mutation-shaped response uses: `board`'s columns/children, `search`'s results,
`create`/`update`'s goal(s) and `create`'s children, `schedule`/`reparent`'s goal — read
straight off `verticals/api/routes_goals.py`, every one of those HTTP routes returns
`goal_to_card()` too, never `goal_to_detail()`. `goal_detail_dict()` is the one exception,
mirroring HTTP's own single exception: `GET /api/goals/{id}` is the only route that calls
`goal_to_detail()`, and the `goal` tool (`tools._handle_goal`) is that route's MCP twin — its
own `children` stay cards (`goal_to_detail()`'s own behaviour: children are always cards, even
nested inside a detail response), only the top-level goal gets the real `body`.
"""

from __future__ import annotations

from typing import Any

from mcp import types

from verticals.core.errors import HasChildren, VerticalError
from verticals.models import Board, DocLink, Goal


def goal_dict(g: Goal) -> dict[str, Any]:
    """The card shape — never `body`, `body_chars` instead. See the module note above for which
    tool responses use this versus `goal_detail_dict()`."""
    return {
        "id": g.id,
        "parent_id": g.parent_id,
        "path": g.path,
        "depth": g.depth,
        "vertical": g.vertical,
        "anchor_date": g.anchor_date.isoformat() if g.anchor_date else None,
        "period_key": g.period_key,
        "title": g.title,
        "body_chars": len(g.body),
        "color": g.color,
        "tags": list(g.tags),
        "done_at": g.done_at.isoformat() if g.done_at else None,
        "position": g.position,
        "origin": g.origin,
        "created_at": g.created_at.isoformat(),
        "updated_at": g.updated_at.isoformat(),
        "repeat": g.repeat_rule,
        "parked_from_vertical": g.parked_from_vertical,
        "foil": g.foil,
        "private": g.private,
        "carryover_ignored_until": g.carryover_ignored_until.isoformat()
        if g.carryover_ignored_until else None,
        "size_expected": list(g.size_expected) if g.size_expected is not None else None,
        "size_actual": list(g.size_actual) if g.size_actual is not None else None,
    }


def goal_detail_dict(g: Goal) -> dict[str, Any]:
    """The one shape that carries the real `body` — a card plus `body` on top, mirroring
    `api/schemas.py::goal_to_detail()`'s own `card = goal_to_card(goal); card["body"] = goal.body`
    exactly. Used only for the `goal` tool's own top-level goal (`tools._handle_goal`), MCP's twin
    of `GET /api/goals/{id}` — never for a nested card."""
    d = goal_dict(g)
    d["body"] = g.body
    return d


def ancestor_dict(a: Any) -> dict[str, Any]:
    return {"id": a.id, "title": a.title, "vertical": a.vertical}


def doc_link_dict(link: DocLink) -> dict[str, Any]:
    """The `goal` tool's own mirror of `api/schemas.py::goal_to_detail()`'s `docs` entries (D251,
    KK 2026-08-20): `inherited_from` is `null` for a doc `link`'s own goal links directly, or
    `{id, title}` for the nearest ancestor it ghosts down from — see
    `core.docs.links_for_goal_with_inherited()`'s own docstring for the dedupe rules."""
    return {
        "id": link.doc_id,
        "path": link.path,
        "title": link.title,
        "source": link.source,
        "inherited_from": (
            {"id": link.inherited_from.id, "title": link.inherited_from.title}
            if link.inherited_from else None
        ),
    }


def board_dict(b: Board) -> dict[str, Any]:
    return {
        "date": b.anchor_date.isoformat(),
        "columns": [
            {
                "vertical": c.vertical,
                "period_key": c.period_key,
                "label": c.label,
                "goals": [
                    {
                        **goal_dict(g),
                        "ghost": (is_ghost := g.id in b.ghosts and not (
                            g.vertical == c.vertical and g.period_key == c.period_key
                        )),
                        "ghost_until": b.ghosts[g.id].isoformat() if is_ghost else None,
                    }
                    for g in c.goals
                ],
            }
            for c in b.columns
        ],
        "progress": {gid: {"done": p.done, "total": p.total} for gid, p in b.progress.items()},
        "ancestors": {gid: [ancestor_dict(a) for a in chain] for gid, chain in b.ancestors.items()},
        "children": {gid: [goal_dict(g) for g in kids] for gid, kids in b.children.items()},
        "evidence": b.evidence,
        # D239: the value menu's one-word labels, sparse — `api/schemas.py::board_to_json`'s own
        # `short_labels` field, mirrored for the cross-transport parity S-59 audits.
        "short_labels": dict(b.short_labels),
        # D240: the unfiltered value list, same mirror.
        "values": [goal_dict(g) for g in b.values],
    }


def ok(text: str, structured: Any) -> types.CallToolResult:
    return types.CallToolResult(
        content=[types.TextContent(type="text", text=text)], structured_content=structured, is_error=False
    )


def error_text(exc: VerticalError) -> str:
    """`.message` alone, for seven of the eight types — already short and already names the field
    (`core/`'s own validators build it that way). `HasChildren` is the one exception: S-55 needs
    the literal substring `children=3` in the text, and the raw message reads "has 3 direct
    children" instead — close, but not the substring asserted, so this type gets custom text."""
    if isinstance(exc, HasChildren):
        return (
            f"cannot delete {exc.detail.get('id')!r}: children={exc.detail.get('children')} "
            f"descendants={exc.detail.get('descendants')}; pass cascade=true to remove the subtree"
        )
    return exc.message


def error_result(text: str) -> types.CallToolResult:
    """S-54/S-130: under 200 characters, always — core/'s own messages measure well under this
    in every case seen while building this module; the cap below is a hard backstop, not the
    normal path, so a real truncation here is itself worth a second look if one ever fires."""
    if len(text) >= 200:
        text = text[:196] + "..."
    return types.CallToolResult(content=[types.TextContent(type="text", text=text)], is_error=True)
