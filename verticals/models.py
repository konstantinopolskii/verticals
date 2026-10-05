"""The read-model vocabulary — plain, frozen dataclasses. No behaviour, no validation, no
database access: `core/goals.py`, `core/board.py` and friends (later work packages) are the
only code that builds these from a row or a query, and the two transports are the only code
that serialises them outward. Keeping them dumb is what lets both transports share one shape
(ARCHITECTURE.md §4c's routes and §5's MCP tools return the same fields either way).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime


@dataclass(frozen=True)
class Goal:
    """One row of the `goals` table (ARCHITECTURE.md §3), field for field, in the table's own
    column order. Nothing here is derived — `vertical`/`anchor_date`/`period_key` are `None`
    together or not at all (`vertical_period_together`), enforced by the database, not by this
    dataclass. `vertical` and `origin` stay plain `str` on purpose: the closed set of valid
    `vertical` values is `core/vertical.py`'s alone to know (AC-012) — this module never imports
    it and never compares one of its values."""

    id: str
    owner: str
    parent_id: str | None
    path: str
    depth: int
    vertical: str | None
    anchor_date: date | None
    period_key: str | None
    title: str
    body: str
    color: str | None
    tags: tuple[str, ...]
    done_at: datetime | None
    position: int
    origin: str
    created_at: datetime
    updated_at: datetime
    repeat_rule: dict | None
    repeat_series_id: str | None
    repeat_index: int | None
    repeat_start_date: date | None
    parked_from_vertical: str | None
    foil: bool
    carryover_ignored_until: date | None
    size_expected: tuple[str, ...] | None
    size_actual: tuple[str, ...] | None
    private: bool


@dataclass(frozen=True)
class Ancestor:
    """One breadcrumb step on the path from a root to some other goal — id and title only,
    not a full `Goal`, so building a breadcrumb never costs a second full-row fetch per level.
    ARCHITECTURE.md §5: "ancestors are the breadcrumb, free from `path`"."""

    id: str
    title: str
    vertical: str | None


@dataclass(frozen=True)
class Progress:
    """A subtree's completion rollup, derived at read time from `path` and never stored
    (ARCHITECTURE.md §3: "Progress rolls up the full ancestor chain; completion never does").
    Always `0 <= done <= total`; a leaf with no children of its own is `Progress(0, 0)`."""

    done: int
    total: int


@dataclass(frozen=True)
class Column:
    """One rendered board column: a vertical scale's bucket for one period, or the Maybe inbox
    when `vertical` is `None` (ARCHITECTURE.md §4b). `label` is already resolved
    (`core/vertical.py`'s `menu_label`, or the literal "Maybe"), so nothing downstream
    re-derives display text from `vertical`. `goals` is flat, not nested: every `Goal` already
    carries its own `parent_id`/`depth`/`path`, which is enough for a renderer to group
    children under parents without a second, tree-shaped dataclass here."""

    vertical: str | None
    period_key: str | None
    label: str
    goals: tuple[Goal, ...]


@dataclass(frozen=True)
class Board:
    """The whole-board read model, assembled by one query (docs/IMPLEMENTATION.md IR-07) —
    `core/board.py` is the sole writer. `progress`, `ancestors` and `children` are all keyed by
    `Goal.id` rather than folded into `Goal` itself, because `Goal` mirrors the stored row
    exactly (§3) and none of the three is ever a stored column. `ancestors[id]` is the
    breadcrumb from root to (not including) `id`, root first; `children[id]` is direct children
    only, in `position` order — both derived from `path` in the same statement that built
    `columns`, never a second query (AC-040, S-23).

    `child_counts[id]` is `SELECT count(*) FROM goals WHERE parent_id = id` — AC-109's own
    criterion, carried for every node the board can draw: the cards, *and* the direct children
    it lists under them. `children` cannot answer it for that second level (it is keyed by
    cards), and a subgoal count that silently reads 0 one level down is worse than none, because
    it reads as authoritative (`docs/PENDING_DOC_FIXES.md` rows 93 and 116(a)). It is a count,
    not a nested `children` entry: the board draws one level of nesting, so the level below that
    needs its count, not its rows."""

    owner: str
    anchor_date: date
    columns: tuple[Column, ...]
    progress: dict[str, Progress]
    ancestors: dict[str, tuple[Ancestor, ...]]
    children: dict[str, tuple[Goal, ...]]
    child_counts: dict[str, int]
    # WP-33 (docs/EVIDENCE.md §6.1): the compact per-goal evidence summary — effective status,
    # verified_at, review_after, nothing more — keyed by id like its three siblings above, for
    # every card and every listed child. Computed in the same single statement (S-22's
    # execute-count contract); never the payload, which only the `goal` readers carry.
    evidence: dict[str, dict]
    # R10: overdue cards rendered in a current-period column without changing their stored
    # schedule. The value is that shown period's end, which Ignore writes back verbatim.
    ghosts: dict[str, date]
    # D239: the value's one-word menu label (nav row, D238), keyed by id like every sibling map
    # above and sparse — only value roots that actually carry one appear. Not folded into `Goal`
    # for the same §3 reason as the rest: `Goal` mirrors the stored row shape every core module
    # pins, and this is menu bookkeeping the board alone serves.
    short_labels: dict[str, str]
    # D240: the menu's own list — every value (parentless life goal), life-column order, and
    # NEVER narrowed by the value filter (the life *column* narrows with everything else; the
    # menu must keep offering the other values or the filter could never be left).
    values: tuple[Goal, ...]


# --- documents (D250, WP-1) -----------------------------------------------------------------
#
# `core/docs.py` is the sole writer of every dataclass below, mirroring `Goal`'s own contract
# above: dumb, frozen, one row (or one derived read) per instance, nothing computed here.


@dataclass(frozen=True)
class Doc:
    """One row of the `docs` table (`014_docs.sql`), field for field. `title` stays optional —
    the column carries no `NOT NULL`, on purpose: a doc's `path` is already a name (`title` is a
    convenience the folder tree can fall back to `path`'s own last segment without)."""

    id: str
    owner: str
    path: str
    title: str | None
    body: str
    revision: int
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class DocSummary:
    """`core.docs.tree()`'s own row shape — never `body` (the same "no card carries body" law
    `Goal`/`goal_to_card` follow, S-33's own reasoning: a whole-folder listing paying for every
    doc's full text would cost as much as reading every doc at once for no reader that asked)."""

    id: str
    path: str
    title: str | None
    updated_at: datetime
    revision: int


@dataclass(frozen=True)
class DocRevisionSummary:
    """`core.docs.history()`'s own row shape — `body_length`, never `body`: the revision list is
    a picker, not a diff viewer; a caller that wants one revision's full text follows up with
    `core.docs.get_revision()`."""

    revision: int
    path: str
    title: str | None
    saved_at: datetime
    body_length: int


@dataclass(frozen=True)
class DocRevision:
    """`core.docs.get_revision()`'s full row — the one shape in this family that does carry the
    real `body`, because reading one specific revision's text is the whole point of the call."""

    doc_id: str
    revision: int
    path: str
    title: str | None
    body: str
    saved_at: datetime


@dataclass(frozen=True)
class DocLinkAncestor:
    """`DocLink.inherited_from`'s shape (D251, KK 2026-08-20): the id and title of the ancestor
    goal whose own link this doc ghosts down from — deliberately not a full `Ancestor` (no
    `vertical`), since the only thing a ghosted chip ever needs is "via <title>"."""

    id: str
    title: str


@dataclass(frozen=True)
class DocLink:
    """One `goal_doc_links` row, the doc's own side: `core.docs.links_for_goal()`'s per-item
    shape. `source` names which side's text declared the link (`'doc'` or `'goal'`) — the two are
    independent facts, not duplicates, so a caller cannot assume only one is ever present for the
    same (goal, doc) pair.

    `inherited_from` (D251): `None` for every row `links_for_goal()` itself ever returns — that
    function is, and stays, OWN-only. `core.docs.links_for_goal_with_inherited()` is the one
    writer that ever sets it, to the NEAREST ancestor whose own link this doc ghosts down from."""

    doc_id: str
    path: str
    title: str | None
    source: str
    inherited_from: DocLinkAncestor | None = None


@dataclass(frozen=True)
class GoalLink:
    """The mirror of `DocLink`, from the goal's own side: `core.docs.links_for_doc()`'s
    per-item shape."""

    goal_id: str
    title: str
    source: str


# --- comments (KK decisions 2026-08-25, docs/COMMENTS_SPEC.md, WP-A) -------------------------
#
# `core/comments.py` is the sole writer of every dataclass below, mirroring the docs family's
# own contract above: dumb, frozen, one row (or one derived read) per instance.


@dataclass(frozen=True)
class CommentAnchor:
    """A thread's optional pointer at SELECTED TEXT within its target's body, kit-style (KK
    decision 2: "quote + prefix + suffix"). `None` on `CommentThread.anchor` means the thread
    comments on the whole card/doc, not on any particular span — `prefix`/`suffix` may
    legitimately be empty strings (a selection starting at the very top or ending at the very
    bottom of the body carries nothing to disambiguate on that side), but `quote` itself is
    never empty when an anchor exists at all (`core.comments.validate_anchor`'s own rule — there
    is no such thing as "selecting zero characters" on purpose)."""

    quote: str
    prefix: str
    suffix: str


@dataclass(frozen=True)
class CommentMessage:
    """One `comment_messages` row. `author` is `'human'` or `'agent'`, stamped by the transport
    that wrote it (web vs MCP) — never a caller-supplied field (docs/COMMENTS_SPEC.md decision
    4: "Transport decides authorship; no new auth"). No `thread_id`/`owner` here: both are
    context the caller already has (the thread it just fetched or wrote into), and every sibling
    read-model in this file omits the same kind of redundant parent key."""

    id: str
    author: str
    body: str
    created_at: datetime


@dataclass(frozen=True)
class CommentThread:
    """One `comment_threads` row plus its own messages, oldest first — the shape
    `core.comments.create_thread`/`add_message`/`set_resolved`/`list_for_goal`/`list_for_doc`
    all return, and the one both transports serialise identically (docs/COMMENTS_SPEC.md's own
    "Thread wire shape (API and MCP identical)"). `goal_id`/`doc_id` are `None`/not-`None` in
    exactly the XOR shape `comment_threads_one_target` enforces in the database — never both,
    never neither."""

    id: str
    owner: str
    goal_id: str | None
    doc_id: str | None
    anchor: CommentAnchor | None
    resolved_at: datetime | None
    created_at: datetime
    messages: tuple[CommentMessage, ...]


@dataclass(frozen=True)
class CommentTarget:
    """`core.comments.list_unresolved()`'s own per-thread descriptor of WHAT a thread is about —
    a goal's id/title, or a doc's id/path/title — so the agent worklist that call serves never
    needs a second call per row just to know what it is looking at. `path` stays `None` for a
    goal target (a goal has no path an agent orients by; `title` is the human-readable name
    either way) and carries the doc's own `path` for a doc target, mirroring `DocSummary`'s own
    field set one level up."""

    kind: str  # 'goal' | 'doc'
    id: str
    title: str | None
    path: str | None = None


@dataclass(frozen=True)
class UnresolvedThread:
    """One row of `list_unresolved()`'s own return — a `CommentThread` paired with the
    `CommentTarget` descriptor of what it anchors to. A plain tuple of two dataclasses rather
    than folding `target` fields into `CommentThread` itself, because every OTHER reader of a
    `CommentThread` (`list_for_goal`, `list_for_doc`, `create_thread`, `add_message`,
    `set_resolved`) already knows its target from its own call arguments and would carry the
    same three fields for nothing."""

    thread: CommentThread
    target: CommentTarget
