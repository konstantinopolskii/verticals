"""The eight `/api/goals*` and `/api/search` routes (§4's route table, rows 2-9) — everything
`routes_board.py` does not front. One router, `verify_bearer_token` at the router level (deps.py's
own reasoning: checked before any route body ever calls `get_conn`), `owner` always read from
`request.app.state.config.owner`, never from the request — this deployment serves exactly one
owner (`routes_board.py`'s own docstring; F2's second owner `t2` exists to prove isolation holds,
S-41, not because a real boot chooses between owners per call).

Every route sets `X-Query-Count` from `conn.query_count` before returning, for the same reason
`routes_board.py` does: IR-06's application-owned counter, not `pg_stat_statements`, and a caller
should be able to assert the N+1 property without touching Postgres at all.

This module maps; it does not decide. Every `ValidationError`/`NotFound`/`CycleRefused`/
`HasChildren`/`IdempotencyConflict`/`LockNotAvailable` a `core/` call raises propagates straight
out of the route body — `api/errors.py`'s registered handlers turn it into the right HTTP shape
before the caller ever sees it. Nothing here re-checks a bound `core/` already enforces (schemas.py
carries the one exception this module needs to know about: `CreateGoalRequest` does not re-walk
`children` for depth/node-count — `core.goals.create()` already does, see that module's docstring).

**One deliberate exception to "this module maps, it does not decide": reorder.** `patch_goal`
below raises `ValidationError` itself, twice — "cannot combine `after_id` with a content field"
and (in `patch_goals_bulk`) "`after_id` targets a single id, not `ids`" — because that rule is
not `core.moves.move_between`'s to enforce (it takes `after_id`/`before_id` as two required
keywords with no opinion on what else a caller sent in the same HTTP body) and not
`core.goals.update()`'s either (it has never heard of `after_id`). `verticals/mcp/tools.py`'s
`update` tool made the identical call for the identical reason (its own module docstring:
"Reorder is deliberately its own path, never combined with a content edit in the same call") —
this file mirrors it rather than inventing a second rule for the same capability.
"""

from __future__ import annotations

from datetime import date as _date

from fastapi import APIRouter, Depends, Header, Request, Response

from verticals.api.deps import get_conn, verify_bearer_token
from verticals.api.schemas import (
    BulkPatchRequest,
    CreateGoalRequest,
    DueAckRequest,
    ReparentRequest,
    ScheduleRequest,
    UpdatePatch,
    goal_to_card,
    goal_to_detail,
    search_to_json,
)
from verticals.core import board as core_board
from verticals.core import docs as core_docs
from verticals.core import due_ack as core_due_ack
from verticals.core import goals as core_goals
from verticals.core import moves as core_moves
from verticals.core import search as core_search
from verticals.core.errors import ValidationError
from verticals.core.search import DEFAULT_LIMIT

router = APIRouter(dependencies=[Depends(verify_bearer_token)])


# --- search ---------------------------------------------------------------------------------


@router.get("/api/search")
def search_goals(
    request: Request,
    response: Response,
    q: str | None = None,
    tag: str | None = None,
    vertical: str | None = None,
    limit: int = DEFAULT_LIMIT,
) -> dict:
    """S-134 plus P-01's recent-default search surface.

    Filtered requests retain `core.search.search`; the explicit no-filter HTTP mode returns a
    bounded recent list. Other transports still cannot turn an omitted filter into a table read.
    """
    owner = request.app.state.config.owner
    with get_conn(request) as conn:
        if q is None and tag is None and vertical is None:
            result = core_search.recent(conn, owner=owner, limit=limit)
        else:
            result = core_search.search(conn, owner=owner, q=q, tag=tag, vertical=vertical, limit=limit)
        response.headers["X-Query-Count"] = str(conn.query_count)
    return search_to_json(result)


# --- create -----------------------------------------------------------------------------------


def _to_child_spec(node: CreateGoalRequest) -> dict:
    """`CreateGoalRequest` (pydantic, nested) -> the plain-`Mapping` shape
    `core.goals.create()`'s own `children` parameter takes (`_CHILD_SPEC_KEYS` there), recursively.
    `anchor_date` stays a `datetime.date` — `create()` takes the real type, not an ISO string;
    only `idem.digest`'s own JSON payload (built inside `create()`, not here) needs the string
    form."""
    return {
        "title": node.title,
        "body": node.body,
        "color": node.color,
        "tags": node.tags,
        "vertical": node.vertical,
        "anchor_date": node.anchor_date,
        "children": [_to_child_spec(c) for c in node.children],
    }


@router.post("/api/goals", status_code=201)
def create_goal(
    request: Request,
    response: Response,
    payload: CreateGoalRequest,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> dict:
    """S-34, S-43. `Idempotency-Key` maps straight to `client_token` — absent means `create()`
    never touches the idempotency table at all (its own `if client_token is not None:` guard).
    `Created.replayed` (added to `core.goals.py` for exactly this) is what lets 201-vs-200 and
    the `Idempotent-Replay` header be told apart from the caller's side; seeing this flag is the
    only way to do it — nothing else on `Created` differs between a fresh write and a replay."""
    owner = request.app.state.config.owner
    with get_conn(request) as conn:
        created = core_goals.create(
            conn,
            owner=owner,
            title=payload.title,
            body=payload.body,
            parent_id=payload.parent_id,
            vertical=payload.vertical,
            anchor_date=payload.anchor_date,
            color=payload.color,
            tags=payload.tags,
            children=[_to_child_spec(c) for c in payload.children],
            client_token=idempotency_key,
        )
        response.headers["X-Query-Count"] = str(conn.query_count)
    response.headers["Location"] = f"/api/goals/{created.goal.id}"
    if created.replayed:
        response.status_code = 200
        response.headers["Idempotent-Replay"] = "true"
    body = goal_to_card(created.goal)
    body["children"] = [goal_to_card(c) for c in created.children]
    return body


# --- read one -----------------------------------------------------------------------------------


@router.get("/api/goals/{id}")
def get_goal(request: Request, response: Response, id: str) -> dict:
    """S-42. Unknown id and another owner's id both surface as `NotFound` from `core.goals.goal`
    — `api/errors.py`'s own `NotFound` branch is what keeps the two 404 bodies byte-identical
    (S-41); nothing in this route treats them differently."""
    owner = request.app.state.config.owner
    with get_conn(request) as conn:
        detail = core_goals.goal(conn, owner=owner, id=id)
        # D250 (WP-1) / D251 (KK, 2026-08-20): the linked-docs list rides the same connection/
        # transaction as the goal read above — one more statement, same S-42 "server statement
        # delta" accounting the rest of this route already does, just not folded into
        # `core.goals.goal()`'s own query (that module never imports `core.docs`, by the seam
        # `core/docs.py`'s own docstring states). D251 widened this single call from own-only to
        # own-plus-inherited (docs ghosted down from every ancestor) WITHOUT adding a fourth
        # statement — `links_for_goal_with_inherited` replaces the plain `links_for_goal` call
        # this line used to make; the budget stays 3, not 4. `detail.ancestors` is root-first
        # (`core.goals.goal()`'s own docstring); `links_for_goal_with_inherited` needs nearest-
        # first for its own nearest-ancestor-wins dedupe, hence the `reversed()`.
        doc_links = core_docs.links_for_goal_with_inherited(
            conn, owner=owner, goal_id=id, ancestors=tuple(reversed(detail.ancestors))
        )
        response.headers["X-Query-Count"] = str(conn.query_count)
    return goal_to_detail(
        detail.goal,
        ancestors=detail.ancestors,
        children=detail.children,
        ideas=detail.ideas,
        docs=doc_links,
    )


# --- update: single and bulk ---------------------------------------------------------------------

# `core.goals.update()`'s own content fields (goals.py's `update` signature) — the set
# `after_id` (reorder) must never be combined with in one call. Named identically to
# `verticals/mcp/tools.py`'s `_CONTENT_FIELDS`, deliberately: same rule, same shape, two transports.
_CONTENT_FIELDS = (
    "title", "body", "color", "tags", "done", "foil", "carryover_ignored_until",
    "repeat", "size_expected",
)


# --- reorder: derive a real, adjacent before_id ---------------------------------------------------
#
# `core.moves.move_between` requires both `after_id` *and* `before_id`, and says so itself:
# "adjacency is trusted, not reverified here". A caller-supplied `before_id` that is merely a
# valid sibling but not truly adjacent to `after_id` would not error — `tree.renumber` raises
# `NotFound` for a non-member id but never checks the *pair* is adjacent, so a wrong-but-plausible
# midpoint would be computed silently. §4's capability table (line 1416) exposes only `after_id`
# on the wire for exactly this reason; `_derive_before_id` below reads the real sibling group
# fresh, every call, and hands `move_between` a `before_id` that is adjacent by construction.
#
# Duplicated from `verticals/mcp/tools.py::_derive_before_id` rather than imported (never
# `verticals.api` -> `verticals.mcp` — that would make one transport depend on another) and rather
# than relocated into `core/` — `core/goals.py` already imports `core/moves.py` (its own
# idempotency/child-creation plumbing), so a `core/moves.py` function that itself called
# `core_goals.goal`/`children_of` the way this one does would be a straight import cycle. Built
# entirely from already-shipped `core/` reads (`goal`, `search`, `children_of`, `board`), same as
# the MCP original: no raw SQL, no `core/` edits. See `docs/PENDING_DOC_FIXES.md` row 32.


def _sibling_ids(conn, *, owner: str, target_id: str) -> list[str]:
    """`target_id`'s own sibling group, in rendered order, `target_id` itself removed.

    Three branches, matching `core/tree.py`'s own module-docstring split (F2-verified): a
    card's group is `(owner, vertical, period_key)` regardless of `parent_id`; a subgoal's group
    is `(owner, parent_id)` *and* `vertical IS NULL` (`children_of` returns every direct child
    regardless of the child's own vertical, so that second filter is not optional); the Maybe
    pile is `vertical IS NULL AND parent_id IS NULL` and does not depend on the date `board()` is
    called with (`core/board.py`'s own `MAYBE_PREDICATE`).

    Split out of `_derive_before_id` (below) when `position: "first"` landed — both forms need
    exactly this list and neither should read the group its own way (`docs/PENDING_DOC_FIXES.md`
    rows 109, 116(c))."""
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


def _derive_before_id(conn, *, owner: str, target_id: str, after_id: str) -> str | None:
    """The `after_id` form: the sibling that follows `after_id`, so `core.moves.move_between`
    gets a pair that is adjacent by construction (see the section comment above).

    Returns `None` when `after_id` is the group's LAST member — "after the last one" is the tail,
    which `move_between` expresses as both ids None. It used to raise instead, which turned the
    most ordinary drag there is (drop a card at the bottom of a column) into an error toast in
    the user's face (owner report 2026-08-10)."""
    if after_id == target_id:
        raise ValidationError(
            f"after_id cannot equal the id being reordered ({target_id!r})", field="after_id"
        )

    ordered_ids = _sibling_ids(conn, owner=owner, target_id=target_id)

    if after_id not in ordered_ids:
        raise ValidationError(f"after_id {after_id!r} is not a sibling of {target_id!r}", field="after_id")
    idx = ordered_ids.index(after_id)
    return ordered_ids[idx + 1] if idx + 1 < len(ordered_ids) else None


@router.patch("/api/goals/{id}")
def patch_goal(request: Request, response: Response, id: str, patch: UpdatePatch) -> dict:
    """S-36, S-37. `exclude_unset=True` is the whole mechanism: a field the caller never sent is
    absent from `fields` entirely, so `core.goals.update()`'s own `_UNSET` sentinel default
    applies to it unchanged — "omitted" and "sent as `null`" reach `update()` as two genuinely
    different calls, which is what makes `color`'s own null-clears-itself case (and any future
    nullable field) work without this route special-casing a single one of them.

    `after_id` (reorder, §4 route table line 913 / capability table line 1416) is its own path,
    dispatched to `core.moves.move_between` before `update()` is ever called, and refused if any
    content field rode along in the same request — mirroring `verticals/mcp/tools.py`'s `update`
    tool, which refuses the identical combination for the identical reason. Was unbuilt on this
    transport until now: `docs/PENDING_DOC_FIXES.md` row 32."""
    owner = request.app.state.config.owner
    fields = patch.model_dump(exclude_unset=True)
    after_id = fields.pop("after_id", None)
    position = fields.pop("position", None)

    if after_id is not None and position is not None:
        raise ValidationError(
            "after_id and position are two spellings of one reorder — send one, not both",
            field="after_id,position",
        )

    if after_id is not None or position is not None:
        ordering_field = "after_id" if after_id is not None else "position"
        present_content = [f for f in _CONTENT_FIELDS if f in fields]
        if present_content:
            raise ValidationError(
                f"{ordering_field} (reorder) cannot be combined with "
                f"{','.join(present_content)} in one call",
                field=ordering_field,
            )
        with get_conn(request) as conn:
            if position is not None:
                # `position: "first"` — read the group, take its current head, and insert before
                # it (`docs/PENDING_DOC_FIXES.md` rows 109, 116(c)). An empty group means this row
                # is the only member and is therefore already first: returned unchanged rather
                # than refused, because "move to top" asked for a state, and the state holds.
                ordered_ids = _sibling_ids(conn, owner=owner, target_id=id)
                if not ordered_ids:
                    goal = core_goals.goal(conn, owner=owner, id=id).goal
                else:
                    goal = core_moves.move_between(
                        conn, owner=owner, id=id, after_id=None, before_id=ordered_ids[0]
                    )
            else:
                before_id = _derive_before_id(conn, owner=owner, target_id=id, after_id=after_id)
                # `before_id is None` = "after the last one" = the tail, which `move_between`
                # spells with BOTH ids None (its own docstring). Passing `after_id` alongside a
                # null `before_id` is the one pair it refuses.
                goal = core_moves.move_between(
                    conn,
                    owner=owner,
                    id=id,
                    after_id=after_id if before_id is not None else None,
                    before_id=before_id,
                )
            response.headers["X-Query-Count"] = str(conn.query_count)
        return goal_to_card(goal)

    with get_conn(request) as conn:
        updated = core_goals.update(conn, owner=owner, id=id, **fields)
        response.headers["X-Query-Count"] = str(conn.query_count)
    body = goal_to_card(updated.goal)
    body["open_descendants"] = updated.open_descendants
    return body


@router.patch("/api/goals")
def patch_goals_bulk(request: Request, response: Response, body: BulkPatchRequest) -> dict:
    """S-44. Same `update()` call as the single-id route above, `ids=` instead of `id=` — the
    route table's own "`update` (list form)" phrasing for why this is one function, not two.
    All-or-nothing is `update()`'s own transaction, not a loop this route writes: one missing id
    rolls the whole bulk write back (`NotFound`, propagated, nothing written for any of the ids).

    `after_id` is refused here, before any connection is opened: reorder targets exactly one id
    (`core.moves.move_between`'s own signature — one `id`, not a list), matching
    `verticals/mcp/tools.py`'s `update` tool ("after_id (reorder) targets a single id, not ids")."""
    owner = request.app.state.config.owner
    fields = body.patch.model_dump(exclude_unset=True)
    if "repeat" in fields:
        raise ValidationError("repeat targets one goal, not ids", field="repeat")
    for ordering_field in ("after_id", "position"):
        if ordering_field in fields:
            raise ValidationError(
                f"{ordering_field} (reorder) targets a single id, not ids", field=ordering_field
            )
    with get_conn(request) as conn:
        updated = core_goals.update(conn, owner=owner, ids=body.ids, **fields)
        response.headers["X-Query-Count"] = str(conn.query_count)
    return {"updated": len(updated), "goals": [goal_to_card(u.goal) for u in updated]}


# --- structure and timing: schedule, reparent -----------------------------------------------------


@router.put("/api/goals/{id}/schedule")
def schedule_goal(request: Request, response: Response, id: str, body: ScheduleRequest) -> dict:
    """S-38. Both fields set schedules; both `null` clears one (`core.moves.schedule()`'s own
    `vertical=None, anchor_date=None` contract, added for exactly this route) — one set and one
    `null` is `schedule()`'s own `ValidationError` on `vertical,anchor_date`, propagated as a 422,
    not a rule this route pre-empts."""
    owner = request.app.state.config.owner
    if body.after_id is not None and body.position is not None:
        raise ValidationError(
            "after_id and position are two spellings of one reorder — send one, not both",
            field="after_id,position",
        )
    with get_conn(request) as conn:
        scheduled = core_moves.schedule(
            conn, owner=owner, id=id, vertical=body.vertical, anchor_date=body.anchor_date
        )
        goal = scheduled.goal
        # The ordered slot, applied inside the group the schedule just moved the row INTO — the
        # sibling reads below run after `schedule`, in this same transaction, so they see the new
        # group and never the old one. Ordering the row within the column it just left would be
        # worse than not ordering it at all.
        if body.position is not None:
            ordered_ids = [x for x in _sibling_ids(conn, owner=owner, target_id=id) if x != id]
            if ordered_ids:
                goal = core_moves.move_between(
                    conn, owner=owner, id=id, after_id=None, before_id=ordered_ids[0]
                )
        elif body.after_id is not None:
            before_id = _derive_before_id(conn, owner=owner, target_id=id, after_id=body.after_id)
            # See the PATCH route: a null `before_id` means the tail, spelled with both ids None.
            goal = core_moves.move_between(
                conn,
                owner=owner,
                id=id,
                after_id=body.after_id if before_id is not None else None,
                before_id=before_id,
            )
        response.headers["X-Query-Count"] = str(conn.query_count)
    result = goal_to_card(goal)
    result["descendants_clamped"] = scheduled.descendants_clamped
    return result


@router.put("/api/goals/{id}/parent")
def reparent_goal(request: Request, response: Response, id: str, body: ReparentRequest) -> dict:
    """S-39. `parent_id=None` detaches to root; a real id that would create a cycle is
    `core.moves.reparent`'s own `CycleRefused` (from `tree.move`'s guard), propagated as a 409
    naming `reason` — never a 500, and nothing here second-guesses which cycle case it is."""
    owner = request.app.state.config.owner
    with get_conn(request) as conn:
        goal = core_moves.reparent(conn, owner=owner, id=id, parent_id=body.parent_id)
        response.headers["X-Query-Count"] = str(conn.query_count)
    return goal_to_card(goal)


@router.post("/api/goals/{id}/park")
def park_goal(request: Request, response: Response, id: str) -> dict:
    """Remove one owned goal from its vertical without moving its tree. Unknown and foreign ids
    both remain `core.moves.park`'s ordinary byte-identical 404 at the HTTP boundary."""
    owner = request.app.state.config.owner
    with get_conn(request) as conn:
        goal = core_moves.park(conn, owner=owner, id=id)
        response.headers["X-Query-Count"] = str(conn.query_count)
    return goal_to_card(goal)


@router.post("/api/goals/{id}/due_ack")
def due_ack_goal(request: Request, response: Response, id: str, body: DueAckRequest) -> dict:
    """011: acknowledge one goal's current dueness with a verdict. `done_on_time` also completes
    the goal (through `core.goals.update`, so repeat materialization holds). Unknown and foreign
    ids both remain core's ordinary byte-identical 404."""
    owner = request.app.state.config.owner
    with get_conn(request) as conn:
        ack = core_due_ack.acknowledge(
            conn, owner=owner, id=id, verdict=body.verdict, note=body.note
        )
        response.headers["X-Query-Count"] = str(conn.query_count)
    return {
        "goal_id": ack.goal_id,
        "vertical": ack.vertical,
        "period_key": ack.period_key,
        "verdict": ack.verdict,
        "note": ack.note,
        "acknowledged_at": ack.acknowledged_at.isoformat(),
    }


# --- delete -----------------------------------------------------------------------------------


@router.delete("/api/goals/{id}", status_code=204)
def delete_goal(request: Request, response: Response, id: str, cascade: bool = False) -> None:
    """S-40. A non-empty subtree without `?cascade=true` is `core.goals.delete`'s own
    `HasChildren`, naming `children`/`descendants` — a caller retries the same request with the
    query flag set, not a different endpoint. 204 carries no body either way; `X-Query-Count`
    still reports (headers are independent of an empty body)."""
    owner = request.app.state.config.owner
    with get_conn(request) as conn:
        core_goals.delete(conn, owner=owner, id=id, cascade=cascade)
        response.headers["X-Query-Count"] = str(conn.query_count)
    return None
