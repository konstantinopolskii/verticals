"""Subtree -> outline markdown, one renderer, two callers — WP-14.

`docs/IMPLEMENTATION.md` WP-14 card: "One outline format that serves both the agent's `outline`
tool and the file export." `docs/ACCEPTANCE.md` §3.5 pins the grammar (quoted below verbatim,
rule for rule); `docs/E2E.md` S-50 and `ARCHITECTURE.md` §5 are the two worked examples that
grammar was cross-checked against byte for byte before this file was written. AC-145 is the
reason there is exactly one function that turns a subtree into text (`outline`, below) rather
than one renderer per caller: the agent-facing MCP tool (WP-19, wave 4) and `export_owner` below
both call it, so the two surfaces cannot drift apart — there is nothing to keep in sync because
there is only one thing.

**The pinned grammar** (`docs/ACCEPTANCE.md` §3.5):

    # <title>   ·<scale> <period_key>· [id]

    <root body, verbatim, only when non-empty>

    - [ ] <title>   ·<scale> <period_key>· [id]
      - [x] <title> [id]
            <child body, verbatim, only when non-empty>

    1. The root is a level-1 heading; every descendant is a list item. No other heading level
       exists (keeps "every heading level <= 6" true by construction).
    2. Three spaces separate the title from the period chip. The chip is `·<scale>
       <period_key>·` and appears only when `vertical` is not null.
    3. The id is last, in square brackets, one space after whatever precedes it.
    4. `- [x] ` for a row with `done_at`, `- [ ] ` otherwise.
    5. Two spaces of indent per level below the root's direct children (verified against S-50
       and ARCHITECTURE.md §5 byte for byte: a direct child of the queried root carries zero
       indent; its own children carry one two-space unit; and so on).
    6. A non-empty body renders verbatim: for the root, after one blank line, flush left; for a
       descendant, indented to that node's content column (indent + 6, for the `- [ ] ` marker
       width), with no blank line before it. An empty body renders nothing at all — not a blank
       line. Consecutive blank lines inside a body collapse to one; leading/trailing blank lines
       inside a body are dropped (the docs say "verbatim" and "collapsed to one" but do not
       spell out the edges — this is the one place this file made a call the docs left open).
    7. Siblings are ordered by `(position, id)`.
    8. The document ends with exactly one newline.

**Escaping is what makes this a safe format to hand an agent** (AC-206, S-131, S-132; also
`docs/IMPLEMENTATION.md`'s own note on this card: "title is untrusted input to it"). `title` is
interpolated into a line-and-bracket grammar with no schema between the two. A title containing
a literal `[`, `]` or the chip's own `·` (U+00B7 MIDDLE DOT) is backslash-escaped so it cannot
forge a node id or a period chip that a parser — or an agent reading the raw text — would
mistake for a real one. The renderer never emits an id it did not read from `goals.id`; ids and
chips it generates itself are never escaped, because only user-supplied `title` text is untrusted
here. Refusing control characters in `title` before a row is ever written is a different layer's
job (validation on the write path — `core/goals.py`'s `create`, wave 3, not yet landed as this
file was written) and is explicitly out of scope for a read-only renderer: this module cannot
refuse a row that already exists.

**Read-only, on purpose** (`ARCHITECTURE.md` §5: "Writing structure back via markdown is
deliberately not in v1"). This file renders markdown; it does not parse it back into writes. A
test file may still contain a small one-off parser to check the renderer's output — that is not
the same thing as shipping a reverse parser in product code, and this module contains none.

IR-02: both public functions take an open connection, own no transaction and never commit —
each is one or two plain `SELECT`s, and a subtree read has nothing to roll back.
"""

from __future__ import annotations

import psycopg

from verticals.core import vertical
from verticals.core.errors import NotFound, ValidationError
from verticals.models import Goal

# `Goal`'s fields, table order — `core/board.py` and `core/tree.py` both pin the identical
# string for the identical reason (their own comments say so): the three modules share no
# dependency on one another, so a duplicate constant here cannot be broken by a sibling's
# refactor.
COLUMNS = (
    "id, owner, parent_id, path, depth, vertical, anchor_date, period_key, "
    "title, body, color, tags, done_at, position, origin, created_at, updated_at, "
    "repeat_rule, repeat_series_id, repeat_index, repeat_start_date, "
    "parked_from_vertical, foil, carryover_ignored_until, size_expected, size_actual, private"
)
_TAGS_INDEX = 11  # tags' position within COLUMNS above — psycopg hands back a list; Goal is frozen

# AC-206 / S-131 / S-132: the three characters a title can carry that would otherwise be
# indistinguishable, in the rendered text, from grammar this renderer itself generates.
_ESCAPE_CHARS: tuple[str, ...] = ("[", "]", "·")

# core/vertical.py's own docstring: "Declaration order doubles as AC-145's vertical descriptor
# rank." core/board.py's COLUMN_ORDER already reads it the same way (Maybe first, then
# day..life) for the board's eight columns. Reused here rather than re-decided — AC-145 never
# spells out a number for the rank, only that one exists, so this is the one prior reading of it
# already shipped and reviewed, not a fresh guess.
_VERTICAL_RANK: dict[str, int] = {h.key: i for i, h in enumerate(vertical.VERTICALS, start=1)}


def _validate_owner(owner: object) -> str:
    if not isinstance(owner, str) or not owner:
        raise ValidationError("owner is required and must be a non-empty string", field="owner")
    return owner


def _validate_id(value: object) -> str:
    if not isinstance(value, str) or not value:
        raise ValidationError("id is required and must be a non-empty string", field="id")
    return value


def _validate_depth(value: object) -> int:
    # bool is an int subtype in Python — rejected explicitly rather than silently accepted as
    # 0/1, matching core/board.py's own precedent for a surprising subtype (its _validate_date
    # docstring names the same reasoning for datetime-is-a-date).
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValidationError("depth must be a non-negative integer", field="depth")
    return value


def _to_goal(row: tuple) -> Goal:
    values = list(row)
    values[_TAGS_INDEX] = tuple(values[_TAGS_INDEX])
    values[24] = tuple(values[24]) if values[24] is not None else None
    values[25] = tuple(values[25]) if values[25] is not None else None
    return Goal(*values)


def _vertical_rank(h: str | None) -> int:
    return 0 if h is None else _VERTICAL_RANK[h]


def _escape_title(title: str) -> str:
    for ch in _ESCAPE_CHARS:
        title = title.replace(ch, "\\" + ch)
    return title


def _body_lines(body: str) -> list[str]:
    """Rule 6: verbatim, blank lines collapsed to one, leading/trailing blank lines dropped.
    `[]` (no body section at all) for a body that is empty or entirely whitespace — the schema
    stores `body` as `NOT NULL DEFAULT ''`, and a whitespace-only body is, for rendering
    purposes, the same as no body: opening a section with dead space serves nobody reading it."""
    if not body:
        return []
    lines = body.split("\n")

    start = 0
    while start < len(lines) and lines[start].strip() == "":
        start += 1
    end = len(lines)
    while end > start and lines[end - 1].strip() == "":
        end -= 1
    lines = lines[start:end]

    out: list[str] = []
    prev_blank = False
    for line in lines:
        blank = line.strip() == ""
        if blank and prev_blank:
            continue
        out.append("" if blank else line)
        prev_blank = blank
    return out


def _node_line(goal: Goal, *, is_root: bool, indent: str) -> str:
    escaped = _escape_title(goal.title)
    if is_root:
        line = f"# {escaped}"
    else:
        marker = "- [x] " if goal.done_at is not None else "- [ ] "
        line = f"{indent}{marker}{escaped}"
    if goal.vertical is not None:
        line += f"   ·{goal.vertical} {goal.period_key}·"
    line += f" [{goal.id}]"
    return line


def _render(
    goal: Goal,
    children_by_parent: dict[str | None, list[Goal]],
    *,
    is_root: bool,
    indent_level: int,
) -> list[str]:
    """One node plus everything under it, as a flat list of lines. `indent_level` is the number
    of two-space units on *this* node's own line — 0 for a direct child of the queried root, 1
    for its children, and so on (rule 5); meaningless for the root itself, which is never
    indented. Root and descendant diverge on exactly one thing: the root separates its body and
    its children with one blank line each (rule 6, and the ARCHITECTURE.md §5 example, which has
    both and shows two); a descendant runs straight into its own body and its own children with
    no blank line at all, because it is a list item, not a top-level block."""
    indent = "  " * indent_level
    lines = [_node_line(goal, is_root=is_root, indent=indent)]
    body_lines = _body_lines(goal.body)
    kids = children_by_parent.get(goal.id, [])

    if is_root:
        if body_lines:
            lines.append("")
            lines.extend(body_lines)
        if kids:
            lines.append("")
            for kid in kids:
                lines.extend(_render(kid, children_by_parent, is_root=False, indent_level=0))
    else:
        if body_lines:
            content_indent = indent + " " * 6
            lines.extend(content_indent + bl if bl else "" for bl in body_lines)
        for kid in kids:
            lines.extend(
                _render(kid, children_by_parent, is_root=False, indent_level=indent_level + 1)
            )
    return lines


def _fetch_root_row(conn: psycopg.Connection, *, owner: str, id: str) -> Goal:
    """The target row alone — the first of `outline()`'s original two `SELECT`s, pulled out so
    `goal_map` (D252, below) can share it without a raw-SQL duplicate of its own. Raises
    `NotFound` exactly as `outline()` always has."""
    row = conn.execute(
        f"SELECT {COLUMNS} FROM goals WHERE owner = %(owner)s AND id = %(id)s",
        {"owner": owner, "id": id},
    ).fetchone()
    if row is None:
        raise NotFound(f"no goal {id!r} for owner {owner!r}", id=id, owner=owner)
    return _to_goal(row)


def _fetch_descendants(
    conn: psycopg.Connection, *, owner: str, root: Goal, depth: int | None
) -> list[Goal]:
    """Every descendant of `root` (not `root` itself), `depth`-pruned exactly as `outline()`
    always has — the second of its original two `SELECT`s, pulled out for the same reason as
    `_fetch_root_row` above. `starts_with(path, root.path)` matches `root` itself (a string
    always starts with itself) and every descendant (a child's path always extends its parent's
    path exactly) — the same prefix technique `core/board.py`'s own progress rollup uses, and no
    LIKE-escaping to get right, because `starts_with` does no pattern interpretation at all."""
    desc_rows = conn.execute(
        f"SELECT {COLUMNS} FROM goals"
        f" WHERE owner = %(owner)s AND starts_with(path, %(prefix)s) AND id <> %(id)s",
        {"owner": owner, "prefix": root.path, "id": root.id},
    ).fetchall()
    descendants = [_to_goal(r) for r in desc_rows]
    if depth is not None:
        max_depth = root.depth + depth
        descendants = [g for g in descendants if g.depth <= max_depth]
    return descendants


def _group_children(descendants: list[Goal]) -> dict[str | None, list[Goal]]:
    """`{parent_id: [children...]}`, each list in `(position, id)` order — rule 7, shared by
    `outline()`'s rendering and `goal_map`'s (D252)."""
    children_by_parent: dict[str | None, list[Goal]] = {}
    for g in descendants:
        children_by_parent.setdefault(g.parent_id, []).append(g)
    for kids in children_by_parent.values():
        kids.sort(key=lambda g: (g.position, g.id))  # rule 7
    return children_by_parent


def _fetch_owner_roots(conn: psycopg.Connection, *, owner: str) -> list[Goal]:
    """Every root of `owner` (`parent_id IS NULL`), in `(vertical descriptor rank, period_key,
    position, id)` order — `export_owner`'s own root query, pulled out so `goal_map` (D252,
    below) can reuse the identical ordering for its own no-`id` "every top-level goal" case
    without a second raw SQL statement of its own (this module's seam: `verticals/mcp/` may never
    hold one, and the honest way to give it "the same core reads outline uses" is to make those
    reads callable, not to make it guess the SQL again)."""
    rows = conn.execute(
        f"SELECT {COLUMNS} FROM goals WHERE owner = %(owner)s AND parent_id IS NULL",
        {"owner": owner},
    ).fetchall()
    roots = [_to_goal(r) for r in rows]
    roots.sort(key=lambda g: (_vertical_rank(g.vertical), g.period_key or "", g.position, g.id))
    return roots


def outline(conn: psycopg.Connection, *, owner: str, id: str, depth: int | None = None) -> str:
    """Render the subtree rooted at `id` as one markdown document — the exact format
    `docs/ACCEPTANCE.md` §3.5 pins (module docstring, above). This is the one renderer AC-145
    requires: the agent-facing MCP `outline` tool (WP-19) is a thin wrapper around this same
    function, and `export_owner` below calls it once per root.

    `depth`, when given, caps how many levels *below* `id` are rendered: 0 renders `id` alone,
    1 renders `id` plus its direct children, and so on. This is unrelated to `core/tree.py`'s
    IR-11 absolute-depth bound — it only prunes what this one call shows, never what exists.

    Raises `NotFound` when `id` does not exist under `owner`, including when it exists under a
    different owner — `core/errors.py`'s own documented indistinguishability between the two.

    IR-02: takes an open connection, never commits, opens no transaction of its own. Two
    `SELECT`s (the root, then its subtree) share one connection but need no explicit transaction
    to be consistent for this module's purpose — nothing here writes, so the only exposure is a
    concurrent edit landing between the two reads, the same exposure every other read-only
    `core/` function already accepts without wrapping single reads in a transaction.
    """
    owner = _validate_owner(owner)
    id = _validate_id(id)
    if depth is not None:
        depth = _validate_depth(depth)

    root = _fetch_root_row(conn, owner=owner, id=id)
    descendants = _fetch_descendants(conn, owner=owner, root=root, depth=depth)
    children_by_parent = _group_children(descendants)

    lines = _render(root, children_by_parent, is_root=True, indent_level=0)
    return "\n".join(lines) + "\n"  # rule 8


def export_owner(conn: psycopg.Connection, *, owner: str) -> str:
    """Every root of `owner` (`parent_id IS NULL`), each rendered by `outline` and concatenated
    in `(vertical descriptor rank, period_key, position, id)` order, one blank line between
    documents — AC-145's own words for what the export is. Lives in `core/` rather than in
    `tools/export_markdown.py` itself so the tool stays a thin argv-to-stdout shell around one
    call (`ARCHITECTURE.md` §2's module boundary), and so a future MCP-side "export everything"
    path, if one is ever added, would not have to re-derive this ordering a second time.

    Each `outline()` call already ends in exactly one newline (rule 8) and starts with no blank
    line, so `"\\n".join(...)` inserts exactly one more newline between two documents — one
    blank line, matching AC-145 precisely — and the final document's own trailing newline is
    still the string's last character, so the whole export ends in exactly one newline too.

    Returns `""` for an owner with zero goals — not tested by any known fixture (F2's owners
    both have roots), but the honest answer for that input rather than an unhandled edge.

    IR-02: takes an open connection, never commits, opens no transaction of its own.
    """
    owner = _validate_owner(owner)
    roots = _fetch_owner_roots(conn, owner=owner)
    return "\n".join(outline(conn, owner=owner, id=r.id) for r in roots)


# --- goal_map: D252's fourth outline shape --------------------------------------------------
#
# KK's own sample, byte-level intent (the desk's hand-built goal map this mode replaces):
#
#     $20K family gross in one month via AI-native model [3 years]
#     └── $3K/quarter to Kosta via Jazzylea [Year]
#         ├── 1 paid Jazzylea SMB sale [Quarter]
#         └── 1 paid Jazzylea cycle through the operating system [Quarter]
#             ├── Jazzylea shared workspace ready [Week]
#             └── Add Lada to Jazzylea Revenue [Week]
#
# A DIFFERENT grammar from `outline()`'s (no headings, no checkboxes, no ids, no body text) —
# standard `tree(1)` box-drawing over one line per goal: title, then a bracketed scale label.
# Built from the exact same reads `outline()`/`export_owner()` use (`_fetch_root_row`,
# `_fetch_descendants`, `_group_children`, `_fetch_owner_roots`, all above) rather than a new
# raw SQL statement of its own — `verticals/mcp/`'s seam rule (no `SELECT`/etc. outside a
# docstring anywhere under that package, `tests/static/test_seam.py`) means the MCP `outline`
# tool's `map` mode can only ever be a thin caller into this function, never its own query.
#
# Connector grammar, `tree(1)`'s own: a non-last child gets `├── `, the last gets `└── `; the
# indent string one level down is `│   ` under a non-last ancestor (its siblings still to come
# need the vertical bar) and `    ` (four spaces, no bar) under a last ancestor (nothing more
# follows it, so there is nothing left to connect to). The root's own line carries neither —
# "root line unindented" is KK's own instruction.
#
# Label rule: every scale label is that scale's own `core/vertical.py::menu_label` — `"3 years"`,
# `"Year"`, `"Quarter"`, `"Week"`, `"Life"` byte-match KK's sample exactly — EXCEPT `month`
# (shows its month NAME, e.g. `[August]`, since the bare word "Month" says nothing about which
# one) and `day` (shows its ISO date, KK's own words: "days show the date") — both exceptions
# live in `vertical.map_label`, not here (AC-012: no scale-literal comparison outside that
# module). A goal with no vertical at all shows `[Maybe]`.
#
# Live-goals-only scope (KK's ruling, this WP): a done goal (`done_at IS NOT NULL`) or an
# unverticaled one is left off the map, subtree and all — "the map is a planning skeleton", not
# a full archive. Unverticaled covers BOTH what `park()` produces and a plain subtask that never
# had its own vertical in the first place: the schema does not — cannot — tell those two states
# apart (`vertical_parked_together`, `008_park_foil.sql`: `(vertical IS NULL) = (parked_from_
# vertical IS NOT NULL)` always, whether the row got there via `park()` or was simply born
# without a vertical). Rather than invent a heuristic the database itself refuses to support,
# this mode treats "no vertical" as one thing — off the dated world the map otherwise walks —
# for every node except one: the goal an explicit `id` argument names is ALWAYS rendered as the
# map's root, done or unverticaled or not, because "the subtree rooted there" is what the caller
# asked for by name; only ITS descendants are live-filtered. This is also the one place `[Maybe]`
# can appear on a real map: root a call at an actual Maybe-bucket goal and its own line still
# renders, labelled `[Maybe]`, exactly like any other unverticaled node would if reached.
#
# Rooting: with `id`, the subtree at `id` (root line unindented, per the sample above). Without
# `id`, every LIVE top-level goal (`parent_id IS NULL`, own vertical set, not done) becomes the
# root of its own tree, in `_fetch_owner_roots`'s own order, each tree separated from the next
# by one blank line (mirroring `export_owner`'s own separator). A parked-or-never-scheduled
# top-level goal (the Maybe pile) never appears here UNBIDDEN — `core/board.py::MAYBE_PREDICATE`
# is exactly this: "the board's own top level is the dated world" (KK's words) — reach a Maybe
# goal only by naming it directly.
#
# `depth` behaves exactly as it does for every other `outline` mode: it caps levels below EACH
# tree's own root independently, never a bound across the whole call.


def _map_is_live(g: Goal) -> bool:
    """A node belongs on the goal map: not done, and still carrying its own vertical (see the
    module comment above this section for why "still scheduled" doubles as this mode's stand-in
    for "not parked"). Never applied to the goal an explicit `id` names — see `goal_map`."""
    return g.done_at is None and g.vertical is not None


def _map_label(g: Goal) -> str:
    return "Maybe" if g.vertical is None else vertical.map_label(g.vertical, g.anchor_date)


def _map_node_text(g: Goal) -> str:
    # `_escape_title` (rule 3, `outline()`'s own grammar) applies identically here: a title
    # containing a literal `[` or `]` could otherwise forge a fake scale label.
    return f"{_escape_title(g.title)} [{_map_label(g)}]"


def _map_child_lines(
    kids: list[Goal], children_by_parent: dict[str | None, list[Goal]], *, prefix: str
) -> list[str]:
    lines: list[str] = []
    last_index = len(kids) - 1
    for i, kid in enumerate(kids):
        is_last = i == last_index
        connector = "└── " if is_last else "├── "
        lines.append(f"{prefix}{connector}{_map_node_text(kid)}")
        continuation = "    " if is_last else "│   "
        lines.extend(
            _map_child_lines(
                children_by_parent.get(kid.id, []), children_by_parent, prefix=prefix + continuation
            )
        )
    return lines


def _map_tree(root: Goal, children_by_parent: dict[str | None, list[Goal]]) -> str:
    lines = [_map_node_text(root)]
    lines.extend(_map_child_lines(children_by_parent.get(root.id, []), children_by_parent, prefix=""))
    return "\n".join(lines)


def goal_map(
    conn: psycopg.Connection, *, owner: str, id: str | None = None, depth: int | None = None
) -> str:
    """D252 — the fourth `outline` shape, `mode='map'`. See the module comment directly above
    this function for the full grammar, label, live-goal-scope and rooting rules; this docstring
    covers only the call contract.

    `id=None` renders every live top-level goal as its own tree, one call. `id` given renders
    the subtree at that goal alone, root line unindented, regardless of that root's own done/
    vertical state. `depth` caps each rendered tree independently, exactly like `outline()`'s own
    `depth`.

    Raises `NotFound` when a given `id` does not exist under `owner` — identical to `outline()`.
    Returns `""` for `id=None` when `owner` has no live top-level goal at all (an honest empty
    answer, not an error: an owner who parked or completed everything has planned nothing left
    to map).

    IR-02: takes an open connection, never commits, opens no transaction of its own — one
    `SELECT` per tree (root only when `id` is given; none extra when it is not, since
    `_fetch_owner_roots` already fetched full rows) plus one `SELECT` per tree's descendants,
    the same statement shape `outline()`/`export_owner()` already spend.
    """
    owner = _validate_owner(owner)
    if depth is not None:
        depth = _validate_depth(depth)

    if id is not None:
        id = _validate_id(id)
        roots = [_fetch_root_row(conn, owner=owner, id=id)]
    else:
        roots = [r for r in _fetch_owner_roots(conn, owner=owner) if _map_is_live(r)]

    trees: list[str] = []
    for root in roots:
        descendants = [
            g for g in _fetch_descendants(conn, owner=owner, root=root, depth=depth) if _map_is_live(g)
        ]
        children_by_parent = _group_children(descendants)
        trees.append(_map_tree(root, children_by_parent))

    return "\n\n".join(trees) + "\n" if trees else ""
