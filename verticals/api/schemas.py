"""Wire shapes, both directions. `docs/E2E.md` §4's input-limits table, enforced here as
pydantic (`extra='forbid'` on every request model — S-35's `{"title":"ok","nonsense":1}` case),
plus the small set of output-shaping functions that turn a `core/` dataclass into the JSON this
transport promises (never the reverse — nothing here writes to the database or calls `core/`).

Two request-side rules IR-11 and §4 both state and this module is the one place they are code
rather than prose:

  * `body`'s 64 KB cap is **bytes of UTF-8**, not Python string length — a `max_length` on a
    pydantic `str` field counts characters, which is the wrong unit for a multi-byte alphabet,
    so this is a hand-written validator, not a field constraint.
  * `title`'s control-character ban is title-only. `body` is free text (`ARCHITECTURE.md`'s own
    markdown body, S-131's outline-grammar concern) — a newline in a title breaks the outline
    format it would be forged into; a newline in a body is a paragraph break.

Every bound below is imported from the `core/` module that owns it where one exists (`search.py`
for `q`/`limit`/`tag`) rather than hand-copied — a transport that copies a number `core/` already
declares is the exact drift `docs/PENDING_DOC_FIXES.md` rows 5/9/11 are the fossil record of.
`title`/`body`/`tags`/`children`/node-count/bulk-`ids` have no `core/` module yet (WP-13's), so
those five are hand-pinned against `docs/E2E.md` §4 directly, cited inline.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt, field_validator

from verticals.core.comments import (
    MAX_ANCHOR_PREFIX_CHARS,
    MAX_ANCHOR_QUOTE_CHARS,
    MAX_ANCHOR_SUFFIX_CHARS,
)
from verticals.core.docs import MAX_DOC_BODY_BYTES, MAX_DOC_TITLE_CHARS, MAX_PATH_CHARS
from verticals.core.goals import MAX_BODY_BYTES, MAX_TAG_CHARS, MAX_TAGS, MAX_TITLE_CHARS
from verticals.core.search import (
    DEFAULT_LIMIT,
    MAX_LIMIT,
    MAX_QUERY_CHARS,
    MIN_LIMIT,
    MIN_QUERY_CHARS,
    SearchResult,
)
from verticals.models import (
    Ancestor,
    Board,
    CommentMessage,
    CommentThread,
    Doc,
    DocLink,
    DocRevision,
    DocRevisionSummary,
    DocSummary,
    Goal,
    GoalLink,
)

# --- §4's limits table ---------------------------------------------------------------------
#
# title/body/tags now come from `core.goals` (landed after this module was first written —
# see the drift warning above) rather than a hand-pinned copy. `children` nesting depth and
# total node count are checked once, inside `core.goals.create()` itself (§10-D2's own field
# names come back on the 422 either way); this module does not duplicate that cross-node walk
# — a transport re-deriving a bound `core/` already enforces is the exact drift this docstring
# warns about, not a safety margin. `ids` has no `core/` module of its own: `update()` takes
# `ids: Sequence[str]` with no upper bound at all, so this is the *only* place the 500 cap is
# enforced (not defense in depth — the one enforcement there is).
MAX_BULK_IDS = 500

# `db/migrations/001_init.sql`'s `color_is_canon` CHECK, copied verbatim (the constraint is the
# only authoritative source for these six strings — nothing in the documents spells them out).
CANON_COLORS = (
    "#ecce32",
    "#df496d",
    "#92ce14",
    "#278dea",
    "#955be0",
    "#f2713a",
)

# C0 (0x00-0x1F) and C1 (0x7F, 0x80-0x9F) control characters — CR/LF/TAB included, exactly what
# §4's `title` row bans and what would let a stored title forge an outline/export grammar token
# (S-131's concern, one layer up from this one).
_CONTROL_CHARS_RE = re.compile(r"[\x00-\x1f\x7f-\x9f]")

# No whitespace, no control characters — §4's `tags` row and `core/search.py`'s own `_validate_tag`
# agree on the shape; duplicated here (rather than imported) because `core/search.py` validates a
# single `tag` *filter* argument, not a stored list, and the two are different call sites with no
# shared function to import.
_TAG_BAD_CHARS_RE = re.compile(r"\s|[\x00-\x1f\x7f-\x9f]")


class _ForbidExtra(BaseModel):
    """Every request model's base. `extra='forbid'` is S-35's `{"title":"ok","nonsense":1}` ->
    422 test, and the reason a caller's typo surfaces immediately instead of being silently
    dropped (§10-D2's "refused, not silently corrected", the same house rule `core/search.py`
    and `core/idem.py` both cite for their own inputs)."""

    model_config = ConfigDict(extra="forbid")


def _check_title(title: str) -> str:
    stripped = title.strip()
    if not stripped:
        raise ValueError("title must be non-blank after strip")
    if len(stripped) > MAX_TITLE_CHARS:
        raise ValueError(f"title must be at most {MAX_TITLE_CHARS} characters")
    if _CONTROL_CHARS_RE.search(stripped):
        raise ValueError("title must carry no control characters")
    return stripped


def _check_body(body: str) -> str:
    if len(body.encode("utf-8")) > MAX_BODY_BYTES:
        raise ValueError(f"body must be at most {MAX_BODY_BYTES} bytes of UTF-8")
    return body


def _check_color(color: str | None) -> str | None:
    if color is not None and color not in CANON_COLORS:
        raise ValueError(f"color must be one of {CANON_COLORS}")
    return color


def _check_tags(tags: list[str]) -> list[str]:
    if len(tags) > MAX_TAGS:
        raise ValueError(f"tags must have at most {MAX_TAGS} elements")
    for tag in tags:
        if not 1 <= len(tag) <= MAX_TAG_CHARS:
            raise ValueError(f"each tag must be 1..{MAX_TAG_CHARS} characters")
        if _TAG_BAD_CHARS_RE.search(tag):
            raise ValueError("tags must carry no whitespace and no control characters")
    return tags


class CreateGoalRequest(_ForbidExtra):
    """`POST /api/goals`. Recursive: `children` is a list of the same shape, which is what lets
    one call land a whole plan (S-52's MCP twin; here it is S-34/S-128) in one `core.goals.create`
    call — this model's job stops at wire shape (types, per-field bounds, `extra='forbid'`).
    Nesting depth and total node count are cross-node checks `core.goals.create()` already makes
    itself (§10-D2's field names come back on its `ValidationError` the same way either path
    gets there), so the route does not re-walk the tree to check them a second time before
    calling in — a transport re-deriving a bound `core/` already enforces is drift waiting to
    happen, not a safety margin (see the module docstring)."""

    title: str
    vertical: str | None = None
    anchor_date: date | None = None
    parent_id: str | None = None
    body: str = ""
    color: str | None = None
    tags: list[str] = Field(default_factory=list)
    children: list["CreateGoalRequest"] = Field(default_factory=list)

    _v_title = field_validator("title")(_check_title)
    _v_body = field_validator("body")(_check_body)
    _v_color = field_validator("color")(_check_color)
    _v_tags = field_validator("tags")(_check_tags)


CreateGoalRequest.model_rebuild()


class RepeatRuleRequest(_ForbidExtra):
    """Measured recurrence option space; cross-field combinations are owned by core.repeat."""

    frequency: Literal["daily", "weekly", "monthly", "quarterly", "yearly", "every_decade"]
    interval: StrictInt = Field(default=1, ge=1, le=10)
    weekdays: list[StrictInt] | None = None
    month_days: list[StrictInt] | None = None
    months: list[StrictInt] | None = None
    quarters: list[StrictInt] | None = None
    end_date: date | None = None


class UpdatePatch(_ForbidExtra):
    """The body of `PATCH /api/goals/{id}` — and, unchanged, the `"patch"` half of the bulk
    form's `{"ids": [...], "patch": {...}}` (§4's route table: `update`, list form, is the same
    call). Every field is optional; `PATCH updates only what is sent` (S-36) means the route
    must be able to tell "omitted" from "sent as null" (`color`'s own legal way to clear
    itself), which is `model_dump(exclude_unset=True)` at the call site, not anything expressed
    in this class's field defaults.

    No `vertical`/`anchor_date` here, on purpose: `core.goals.update()`'s own docstring is
    explicit — "this never touches parent_id, path, depth, vertical, anchor_date, period_key or
    position." Scheduling is `PUT /api/goals/{id}/schedule` (`core.moves.schedule`), a distinct
    route (S-38), not a PATCH field this model could accept without a request this transport
    could never actually fulfil. (An earlier draft of this docstring cited S-38 here — wrong;
    S-38's own steps are `PUT .../schedule`, not `PATCH`, confirmed against `docs/E2E.md`.)

    `after_id` is the one field here `core.goals.update()` does not take at all — reorder (§4's
    route table line 913, capability table line 1416: `{id, after_id}`) is
    `core.moves.move_between`'s own verb, dispatched separately by `routes_goals.py::patch_goal`
    *before* `update()` is ever called, and refused if combined with any content field in the
    same request (`docs/PENDING_DOC_FIXES.md` row 32 — the capability was specified on both
    transports and, until now, built on neither). No `before_id` field exists on this model, on
    purpose: `move_between` trusts adjacency without reverifying it, so a client-supplied
    `before_id` would reopen exactly the hole `routes_goals.py::_derive_before_id` exists to
    close — the same reason `verticals/mcp/tools.py`'s `update` tool exposes `after_id` alone.

    `position` is the one ordering form `after_id` cannot express: `"first"`, move this row to
    the top of its own sibling group (`docs/PENDING_DOC_FIXES.md` rows 109, 116(c) — "after X"
    has no X to name at index 0, so the first position of every list used to be unreachable by
    the only shipped gesture, and the UI marked its up control `aria-disabled` at index 1 to say
    so). An enum of one, not a free integer and not an id: a caller-supplied *position* would
    let a client write a `goals.position` this transport never validated, and a caller-supplied
    `before_id` reopens the adjacency hole above. The route reads the group itself, exactly as
    the `after_id` path already does. `"last"` is deliberately absent — the tail is already
    reachable (`after_id` = the current last row), so an enum member for it would be a second
    spelling of a gesture that works, and this enum grows only when a real gesture cannot be
    expressed without it."""

    title: str | None = None
    body: str | None = None
    color: str | None = None
    tags: list[str] | None = None
    done: bool | None = None
    foil: bool | None = None
    carryover_ignored_until: date | None = None
    repeat: RepeatRuleRequest | None = None
    size_expected: str | list[str] | None = None
    short_label: str | None = None
    after_id: str | None = None
    position: Literal["first"] | None = None

    _v_title = field_validator("title")(lambda v: _check_title(v) if v is not None else v)
    _v_body = field_validator("body")(lambda v: _check_body(v) if v is not None else v)
    _v_color = field_validator("color")(_check_color)
    _v_tags = field_validator("tags")(lambda v: _check_tags(v) if v is not None else v)


class BulkPatchRequest(_ForbidExtra):
    """`PATCH /api/goals`, the list form (L10). `ids` at `MAX_BULK_IDS` is `core/search.py`'s
    own generosity-by-measurement pattern repeated: §4 cites "the densest single column...
    ~140 at F4-5670; 500 covers select-the-whole-column at 3.5x"."""

    ids: list[str] = Field(min_length=1, max_length=MAX_BULK_IDS)
    patch: UpdatePatch


class ScheduleRequest(_ForbidExtra):
    """`PUT /api/goals/{id}/schedule`. Both fields together or both `null` — `core/`'s own
    `vertical_needs_anchor` CHECK is the backstop; this model does not pre-empt it with a
    cross-field rule of its own, since `schedule(vertical=None, anchor_date=<not None>)` is a
    question for `core/moves.py` to answer, not this transport to guess at."""

    vertical: str | None = None
    anchor_date: date | None = None
    # A cross-column drag is ONE act: it names a destination column *and* a slot inside it. With
    # neither field the route could only append, so a card dropped above the first card of another
    # column landed at the bottom instead (owner report 2026-08-10). Same two spellings, and the
    # same "send one, not both" rule, as `UpdatePatch` — applied inside the DESTINATION group once
    # the schedule has landed. Deliberately not a second request: a second round-trip sits inside
    # the drop tail that `docs/parity/FIDELITY.md` dimension 8 measures.
    after_id: str | None = None
    position: Literal["first"] | None = None


class ReparentRequest(_ForbidExtra):
    """`PUT /api/goals/{id}/parent`. `parent_id=None` detaches to root (S-11's HTTP face)."""

    parent_id: str | None = None


class DueAckRequest(_ForbidExtra):
    """`POST /api/goals/{id}/due_ack` (011). Verdict values are `core.due_ack.VERDICTS`;
    validation stays in core so the two transports cannot drift."""

    verdict: str
    note: str | None = None


# --- output shaping ---------------------------------------------------------------------------
#
# Plain dict builders, not pydantic response models: FastAPI runs every returned value through
# `jsonable_encoder` regardless of whether a `response_model` is declared, so a `date`/`datetime`
# inside a plain dict already serialises correctly, and hand-built dicts are one obvious shape
# to read rather than a second parallel model family that must be kept in sync with `models.py`.


def goal_to_card(goal: Goal) -> dict:
    """A board column entry or a `children` entry — everywhere a goal appears *inside* a bigger
    response. `body` is never here (S-33: "No card in the response carries `body`; each carries
    `body_chars`") — the 64 KB cap makes a card's worst case cost as much as fifty boards without
    it, and nothing renders a card's full body without a follow-up `GET /api/goals/{id}`."""
    return {
        "id": goal.id,
        "owner": goal.owner,
        "parent_id": goal.parent_id,
        "depth": goal.depth,
        "vertical": goal.vertical,
        "anchor_date": goal.anchor_date,
        "period_key": goal.period_key,
        "title": goal.title,
        "body_chars": len(goal.body),
        "color": goal.color,
        "tags": list(goal.tags),
        "done_at": goal.done_at,
        "position": goal.position,
        "origin": goal.origin,
        "created_at": goal.created_at,
        "updated_at": goal.updated_at,
        "repeat": goal.repeat_rule,
        "parked_from_vertical": goal.parked_from_vertical,
        "foil": goal.foil,
        "carryover_ignored_until": goal.carryover_ignored_until,
        "size_expected": list(goal.size_expected) if goal.size_expected is not None else None,
        "size_actual": list(goal.size_actual) if goal.size_actual is not None else None,
    }


def goal_to_detail(
    goal: Goal,
    *,
    ancestors: tuple[Ancestor, ...] = (),
    children: tuple[Goal, ...] = (),
    ideas: tuple[Goal, ...] = (),
    docs: tuple[DocLink, ...] = (),
) -> dict:
    """`GET /api/goals/{id}` — the one response shape that carries the real `body` (S-33's own
    contrast: cards never do, a follow-up detail call always does). `ancestors` is the
    breadcrumb, root first (S-42); `children` are cards, not detail — a detail response nested
    inside another detail response is a shape nothing in `docs/E2E.md` asks for.

    `docs` (D250, WP-1; D251, KK 2026-08-20): the compact link list `core.docs.links_for_goal_
    with_inherited()` returns — id, path, title, source — never a doc's own body; a caller that
    wants a linked doc's text follows up with `GET /api/docs/{id}`, same "no nested detail" rule
    the rest of this function follows. `inherited_from` (D251) is `null` for a doc this goal
    links directly and `{id, title}` for a doc "ghosted" down from an ancestor's own link — own
    entries sort first (`links_for_goal_with_inherited`'s own return order), inherited after, so
    a renderer can draw the ghosted chips last without re-sorting."""
    card = goal_to_card(goal)
    card["body"] = goal.body
    card["ancestors"] = [
        {"id": a.id, "title": a.title, "vertical": a.vertical} for a in ancestors
    ]
    card["children"] = [goal_to_card(c) for c in children]
    card["ideas"] = [goal_to_card(c) for c in ideas]
    card["docs"] = [
        {
            "id": d.doc_id,
            "path": d.path,
            "title": d.title,
            "source": d.source,
            "inherited_from": (
                {"id": d.inherited_from.id, "title": d.inherited_from.title}
                if d.inherited_from else None
            ),
        }
        for d in docs
    ]
    return card


def board_to_json(board: Board) -> dict:
    """`GET /api/board` — mirrors `models.Board` field for field (`columns`, `progress`,
    `ancestors`, `children` all top-level, exactly as the dataclass carries them) rather than
    denormalising progress/ancestors/children into each card: `models.py`'s own docstring is
    explicit that the three are deliberately not folded into `Goal`, and re-nesting them here
    would be this transport inventing a shape `core/board.py` did not build."""
    return {
        "owner": board.owner,
        "anchor_date": board.anchor_date,
        "columns": [
            {
                "vertical": col.vertical,
                "period_key": col.period_key,
                "label": col.label,
                "goals": [
                    {
                        **goal_to_card(g),
                        # Time travel can show the historical source and its live, broader
                        # landing column together. Only the latter is a carried-over card.
                        "ghost": (is_ghost := g.id in board.ghosts and not (
                            g.vertical == col.vertical and g.period_key == col.period_key
                        )),
                        "ghost_until": board.ghosts.get(g.id) if is_ghost else None,
                    }
                    for g in col.goals
                ],
            }
            for col in board.columns
        ],
        "progress": {
            goal_id: {"done": p.done, "total": p.total} for goal_id, p in board.progress.items()
        },
        "ancestors": {
            goal_id: [{"id": a.id, "title": a.title, "vertical": a.vertical} for a in chain]
            for goal_id, chain in board.ancestors.items()
        },
        "children": {
            goal_id: [goal_to_card(g) for g in kids] for goal_id, kids in board.children.items()
        },
        # Keyed over *both* levels the board draws — cards and the children listed under them —
        # so a nested card's subgoal count is a real number rather than the 0 a missing
        # `children` entry used to imply (`docs/PENDING_DOC_FIXES.md` rows 93, 116(a); AC-109).
        # Top-level like `progress`/`ancestors`/`children`, for the same reason they are: this
        # transport mirrors `models.Board` field for field and denormalises nothing into a card.
        "child_counts": dict(board.child_counts),
        # D239: the value menu's one-word labels, sparse (only value roots that carry one).
        "short_labels": dict(board.short_labels),
        # D240: the menu's list of values, unfiltered under any `value=` — the life COLUMN
        # narrows with the rest of the board, this list is what keeps the menu whole.
        "values": [goal_to_card(g) for g in board.values],
        # WP-33: the compact evidence summary map, same both-levels keying as child_counts and
        # for the same mirror-the-dataclass reason. Three fields per id, never the payload —
        # the UI round that renders it comes later; the field costs nothing to carry now and
        # keeps the two transports telling one story.
        "evidence": dict(board.evidence),
    }


def search_to_json(result: SearchResult) -> dict:
    """`GET /api/search` — cards, not details (same "no `body` outside a detail call" rule as
    every other list-shaped response), plus the `truncated` flag AC-202 requires (S-129, proved
    over this route by S-134's own `limit=201` row)."""
    body: dict = {
        "goals": [goal_to_card(g) for g in result.goals],
        "truncated": result.truncated,
    }
    if result.parents is not None:
        body["parents"] = {
            goal_id: [
                {"id": a.id, "parent_id": a.parent_id, "title": a.title, "vertical": a.vertical, "anchor_date": a.anchor_date,
                 "period_key": a.period_key, "done_at": a.done_at, "position": a.position}
                for a in chain
            ]
            for goal_id, chain in result.parents.items()
        }
    return body


# --- documents (D250, WP-1) ---------------------------------------------------------------------
#
# Bounds come from `core.docs` (`MAX_PATH_CHARS`, `MAX_DOC_TITLE_CHARS`, `MAX_DOC_BODY_BYTES`) the
# same way `title`/`body` above come from `core.goals` — never hand-copied, for the drift reason
# the module docstring already states once.


class CreateDocRequest(_ForbidExtra):
    """`POST /api/docs`. `title` accepts `null` (the column itself carries no `NOT NULL` —
    `core.docs.validate_doc_title`'s own docstring); a *given* title still refuses blank/too-long/
    control-character shapes, same enforcement point as `core.docs.create()` itself — this model
    only narrows the wire *type* (`str | None`, not `object`), the actual bound is checked once,
    in `core/`, not duplicated here as a second copy of the same rule."""

    path: str = Field(min_length=1, max_length=MAX_PATH_CHARS)
    title: str | None = None
    body: str = ""


class SaveDocRequest(_ForbidExtra):
    """`PATCH /api/docs/{id}`. `expected_revision` is required — there is no way to PATCH a doc
    without naming the revision being built on, which is the whole optimistic-lock contract
    (`core.docs.save()`'s own docstring). `title`/`body`/`path` stay `None` by default, meaning
    omitted — the same "None is enough, no `_UNSET` needed" reasoning `core.docs.save()` itself
    documents, carried through to the wire model rather than re-invented here."""

    expected_revision: int = Field(ge=1)
    title: str | None = None
    body: str | None = None
    path: str | None = Field(default=None, max_length=MAX_PATH_CHARS)


class RestoreDocRequest(_ForbidExtra):
    """`POST /api/docs/{id}/restore`. Both `revision` (which old revision to copy forward) and
    `expected_revision` (the optimistic-lock guard on the doc's *current* state) are required —
    a restore is a save whose text happens to come from history, not from the request body
    (`core.docs.restore()`'s own docstring)."""

    revision: int = Field(ge=1)
    expected_revision: int = Field(ge=1)


def doc_to_summary(doc: DocSummary) -> dict:
    """`GET /api/docs` (the folder tree) — never `body` (`DocSummary`'s own docstring: the same
    "no card carries body" law `goal_to_card` follows)."""
    return {
        "id": doc.id,
        "path": doc.path,
        "title": doc.title,
        "updated_at": doc.updated_at,
        "revision": doc.revision,
    }


def doc_to_detail(doc: Doc, *, links: tuple[GoalLink, ...] = ()) -> dict:
    """Every other doc route (`POST`, `GET` one, `PATCH`, `POST .../restore`) — the one shape
    that carries the real `body`, because a doc's whole point is its text (unlike a goal card,
    there is no cheaper "doc without its body" response worth having here). `links` is
    `core.docs.links_for_doc()`'s own return — goal id, title, and which side's text declared
    the link, same shape as `goal_to_detail`'s own `docs` field, mirrored the other way."""
    return {
        "id": doc.id,
        "owner": doc.owner,
        "path": doc.path,
        "title": doc.title,
        "body": doc.body,
        "revision": doc.revision,
        "created_at": doc.created_at,
        "updated_at": doc.updated_at,
        "linked_goals": [
            {"goal_id": g.goal_id, "title": g.title, "source": g.source} for g in links
        ],
    }


def doc_revision_to_json(rev: DocRevisionSummary) -> dict:
    """One row of `GET /api/docs/{id}/history` — never `body` (`DocRevisionSummary`'s own
    docstring: `body_length` is the picker's own field, not a preview of the text)."""
    return {
        "revision": rev.revision,
        "path": rev.path,
        "title": rev.title,
        "saved_at": rev.saved_at,
        "body_length": rev.body_length,
    }


def doc_revision_detail_to_json(rev: DocRevision) -> dict:
    """`GET /api/docs/{id}/history/{revision}` — the one history-shaped response that does carry
    `body`, because reading one specific revision's text is the entire point of the call."""
    return {
        "doc_id": rev.doc_id,
        "revision": rev.revision,
        "path": rev.path,
        "title": rev.title,
        "body": rev.body,
        "saved_at": rev.saved_at,
    }


# --- comments (KK decisions 2026-08-25, docs/COMMENTS_SPEC.md, WP-A) ---------------------------
#
# `body`'s own bound (`core.comments.MAX_MESSAGE_BODY_BYTES`) is a UTF-8 byte cap, the same unit
# mismatch this module's own docstring already flags for a goal's `body` — left unconstrained
# here (no `Field(max_length=...)`) and enforced once, in `core.comments.validate_message_body`,
# exactly the way `CreateDocRequest.body` above leaves `core.docs.validate_doc_body` as the sole
# enforcement point. The anchor's three char-counted fields are genuine character caps, so
# `Field(max_length=...)` on them is safe the same way `CreateDocRequest.path` applies
# `MAX_PATH_CHARS` directly. The exactly-one-of-`goal_id`/`doc_id` rule and "quote required
# non-empty when an anchor is given" are both `core.comments.create_thread`/`validate_anchor`'s
# own refusals (this module's own docstring: re-deriving a bound `core/` already enforces is
# drift waiting to happen) — neither request model below adds a cross-field check of its own.


class CommentAnchorRequest(_ForbidExtra):
    """The wire shape of an anchor — quote + prefix + suffix, kit-style (docs/COMMENTS_SPEC.md
    decision 2). `prefix`/`suffix` default to `""`, matching
    `core.comments.validate_anchor`'s own default for an omitted side."""

    quote: str = Field(min_length=1, max_length=MAX_ANCHOR_QUOTE_CHARS)
    prefix: str = Field(default="", max_length=MAX_ANCHOR_PREFIX_CHARS)
    suffix: str = Field(default="", max_length=MAX_ANCHOR_SUFFIX_CHARS)


class CreateCommentRequest(_ForbidExtra):
    """`POST /api/comments`. `author` is never a field here — the route always writes
    `author='human'` (docs/COMMENTS_SPEC.md decision 4: "Transport decides authorship")."""

    goal_id: str | None = None
    doc_id: str | None = None
    body: str
    anchor: CommentAnchorRequest | None = None


class AddCommentMessageRequest(_ForbidExtra):
    """`POST /api/comments/{thread_id}/messages`."""

    body: str


class ResolveCommentRequest(_ForbidExtra):
    """`POST /api/comments/{thread_id}/resolve`."""

    resolved: bool


def comment_message_to_json(m: CommentMessage) -> dict:
    return {"id": m.id, "author": m.author, "body": m.body, "created_at": m.created_at}


def comment_thread_to_json(t: CommentThread) -> dict:
    """The one thread shape every comment route returns — API and MCP identical
    (docs/COMMENTS_SPEC.md's own "Thread wire shape (API and MCP identical)"),
    `mcp/comments.py::_thread_dict` is this function's MCP-side twin."""
    return {
        "id": t.id,
        "goal_id": t.goal_id,
        "doc_id": t.doc_id,
        "anchor": (
            {"quote": t.anchor.quote, "prefix": t.anchor.prefix, "suffix": t.anchor.suffix}
            if t.anchor else None
        ),
        "resolved_at": t.resolved_at,
        "created_at": t.created_at,
        "messages": [comment_message_to_json(m) for m in t.messages],
    }


__all__ = [
    "MIN_QUERY_CHARS",
    "MAX_QUERY_CHARS",
    "MIN_LIMIT",
    "MAX_LIMIT",
    "DEFAULT_LIMIT",
    "MAX_TITLE_CHARS",
    "MAX_BODY_BYTES",
    "MAX_TAGS",
    "MAX_TAG_CHARS",
    "MAX_BULK_IDS",
    "CANON_COLORS",
    "CreateGoalRequest",
    "UpdatePatch",
    "RepeatRuleRequest",
    "BulkPatchRequest",
    "ScheduleRequest",
    "ReparentRequest",
    "goal_to_card",
    "goal_to_detail",
    "board_to_json",
    "search_to_json",
    "CreateDocRequest",
    "SaveDocRequest",
    "RestoreDocRequest",
    "doc_to_summary",
    "doc_to_detail",
    "doc_revision_to_json",
    "doc_revision_detail_to_json",
    "CommentAnchorRequest",
    "CreateCommentRequest",
    "AddCommentMessageRequest",
    "ResolveCommentRequest",
    "comment_message_to_json",
    "comment_thread_to_json",
]
