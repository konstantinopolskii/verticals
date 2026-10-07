"""Structure and timing verbs — `schedule`, `reparent`, `move_between` — plus the one primitive
`core/goals.py`'s `create` also needs: a concurrency-safe position allocator (`docs/IMPLEMENTATION.md`
WP-13 card, file table: "schedule, reparent, bulk patch, position renumber").

**Why this file exists at all, given `core/tree.py` already has `renumber`.** `tree.renumber`
computes the *value* to use but is honest about what it cannot promise (its own module
docstring): its `SELECT ... FOR UPDATE` locks only *existing* sibling rows, so two concurrent
callers targeting the *same empty group*, or racing a brand-new `INSERT` neither can see yet,
can compute the same position — "a brand new concurrent INSERT has no existing row here to
lock". AC-204 closes that gap with one transaction-scoped advisory lock per sibling group,
taken *before* `renumber` runs, so only one transaction at a time is ever inside a given group's
critical section regardless of whether that group has zero rows, one row, or fifty. `_lock_key`
below and `allocate_position` are that lock; every code path that hands a row a `position` —
`create` (WP-13's own goals.py), `move_between`, `schedule` below — goes through it. Nothing in
this file re-implements what `tree.renumber` already does correctly; this file only adds the one
serialisation primitive around it.

**AC-204's own key text is `hashtext(owner || vertical || period_key)`** — written for the board
column case alone. Followed literally it breaks two ways this module cannot accept: (1) `vertical
|| period_key` is `NULL` whenever `vertical IS NULL` (a subgoal list or the Maybe pile), and `||`
with a `NULL` operand is `NULL` — `hashtext(NULL)` is `NULL`, and `pg_advisory_xact_lock(NULL)`
takes no lock at all (a strict function silently no-ops on `NULL` input), which would leave every
subgoal/Maybe insert completely unserialised, the exact bug AC-204 exists to close, just moved
one bucket over; (2) `tree.py`'s own module docstring — verified against a loaded F2 clone, see
that file — establishes that a board column's sibling group is `(owner, vertical, period_key)`
**regardless of `parent_id`**, so a key that also folds in `parent_id` for that case would let two
creates with different parents into the *same* column take two different locks and race past each
other, reintroducing AC-204's own failure mode. `_lock_key` below is the same two-case split
`tree.renumber` already uses for exactly this reason, built in Python (never `NULL`, so the lock
is always actually taken) and hashed the same way (`hashtext`, named in the code, over a string
that determines the same group `tree.renumber` would compute from the same arguments). This is a
documented deviation from the criterion's literal SQL text, not an oversight — flagged in this
work package's own result.

IR-02: every function here takes an open connection and never commits; `owner` is keyword-only
with no default on every one (AC-013).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date as _date
from datetime import datetime as _datetime

import psycopg

from verticals.core import vertical as vertical_mod
from verticals.core import placement, tree
from verticals.core.errors import NotFound, ValidationError
from verticals.models import Goal

# `Goal`'s fields, table order — the same constant every sibling core module pins locally
# (`core/tree.py`, `core/search.py`, `core/board.py`) rather than importing one another's copy.
COLUMNS = (
    "id, owner, parent_id, path, depth, vertical, anchor_date, period_key, "
    "title, body, color, tags, done_at, position, origin, created_at, updated_at, "
    "repeat_rule, repeat_series_id, repeat_index, repeat_start_date, "
    "parked_from_vertical, foil, carryover_ignored_until, size_expected, size_actual, private"
)


@dataclass(frozen=True)
class Scheduled:
    """One schedule write's row plus its server-side subtree reconciliation count.

    `Goal` stays the stored-row vocabulary. The count is call metadata, like
    `core/goals.py::Updated.open_descendants`, so it belongs in this small verb result instead
    of becoming a field every board/search/detail card would have to pretend was stored.
    """

    goal: Goal
    descendants_clamped: int


def _to_goal(row: tuple) -> Goal:
    values = list(row)
    values[11] = tuple(values[11])  # tags: psycopg hands back a list, `Goal` is frozen
    values[24] = tuple(values[24]) if values[24] is not None else None
    values[25] = tuple(values[25]) if values[25] is not None else None
    return Goal(*values)


def _require_str(value: object, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValidationError(f"{field} is required and must be a non-empty string", field=field)
    return value


def _validate_vertical(value: object) -> str:
    """Membership against `core/vertical.py`'s own set (AC-012: no module outside that file may
    compare a value against one of the seven scale strings) — the same guard
    `core/search.py`'s `_validate_vertical` and `core/board.py`'s date guard both apply locally
    rather than importing a shared validator, matching this codebase's own established
    convention of small, duplicated, per-module input guards."""
    if not isinstance(value, str) or value not in vertical_mod.SCALE_KEYS:
        raise ValidationError(
            f"vertical must be one of {sorted(vertical_mod.SCALE_KEYS)}, got {value!r}",
            field="vertical",
        )
    return value


def _validate_anchor_date(value: object) -> _date:
    if isinstance(value, _datetime) or not isinstance(value, _date):
        raise ValidationError(
            "anchor_date must be a date, not a datetime or any other type", field="anchor_date"
        )
    return value


def _validate_schedule(
    vertical: object, anchor_date: object
) -> tuple[str | None, _date | None, str | None]:
    """`vertical`/`anchor_date` together, or both `None` (clearing a schedule — S-38's second
    step). Mirrors `core/goals.py`'s own `_validate_schedule_fields` rule (duplicated, not
    imported: `goals.py` already imports this module, so the reverse import would cycle)."""
    if vertical is None:
        if anchor_date is not None:
            raise ValidationError("anchor_date requires vertical to be set", field="vertical,anchor_date")
        return None, None, None
    vertical = _validate_vertical(vertical)
    anchor_date = _validate_anchor_date(anchor_date)
    return vertical, anchor_date, vertical_mod.period_key(vertical, anchor_date)


# --- AC-204: the position-allocation lock -------------------------------------------------------


def _lock_key(
    *, owner: str, vertical: str | None, period_key: str | None, parent_id: str | None
) -> str:
    """One string per sibling group, matching `tree.renumber`'s own two-case split exactly (see
    module docstring for why AC-204's literal `owner || vertical || period_key` cannot be used
    unmodified). `\\x1f` (ASCII unit separator) joins the parts: ids are base62 (IR-05) and
    owners are opaque strings with no pinned alphabet, so a join character outside every value's
    own character set is the only safe way to guarantee `("ab", "c")` and `("a", "bc")` never
    collide. A literal tag (`"column"` / `"siblings"`) is the first segment so the two cases can
    never collide with each other either, even in the unlikely event owner/parent_id values
    happened to coincide across them."""
    if vertical is not None:
        return f"column\x1f{owner}\x1f{vertical}\x1f{period_key}"
    return f"siblings\x1f{owner}\x1f{parent_id or ''}"


def allocate_position(
    conn: psycopg.Connection,
    *,
    owner: str,
    vertical: str | None,
    period_key: str | None,
    parent_id: str | None,
    after_id: str | None = None,
    before_id: str | None = None,
) -> int:
    """AC-204, in full: take the group's advisory lock, *then* ask `tree.renumber` for the
    position — never the other way round, and never a read-then-write of `max(position)+1024`
    computed without the lock held. Transaction-scoped (`pg_advisory_xact_lock`, not the
    session-scoped `pg_advisory_lock`): released automatically at commit or rollback, so it can
    never leak under IR-02's caller-owns-the-transaction rule the way a session lock would if a
    caller forgot to release it explicitly.

    Public — `core/goals.py`'s `create` calls this directly for the node it creates at the root
    of a call (module docstring: children of a *brand new* parent need no lock at all, since no
    other transaction can know that parent's id before this one commits).
    """
    owner = _require_str(owner, "owner")
    conn.execute(
        "SELECT pg_advisory_xact_lock(hashtext(%(key)s))",
        {"key": _lock_key(owner=owner, vertical=vertical, period_key=period_key, parent_id=parent_id)},
    )
    return tree.renumber(
        conn,
        owner=owner,
        vertical=vertical,
        period_key=period_key,
        parent_id=parent_id,
        after_id=after_id,
        before_id=before_id,
    )


# --- move_between -------------------------------------------------------------------------------


def move_between(
    conn: psycopg.Connection, *, owner: str, id: str, after_id: str | None, before_id: str | None
) -> Goal:
    """The explicit reorder verb S-12's own steps name: "move_between SYNORD01 and SYNORD02" —
    distinct from `reparent`, which changes structure, not position. `id`'s own current sibling
    group (read and row-locked in the same statement, so no other writer can change which group
    `id` belongs to between this read and the renumber below) determines which group's lock
    `allocate_position` takes; `after_id`/`before_id` must already be members of that same group
    (`tree.renumber`'s own contract — adjacency is trusted, not reverified here).

    `after_id=None` is the head insert: "put `id` immediately before `before_id`", the only form
    that can express "move this to the top" (`docs/PENDING_DOC_FIXES.md` rows 109, 116(c)). The
    caller must have established that `before_id` is the group's current first member — this
    function trusts that exactly as far as it already trusts adjacency, and for the same reason:
    it is the caller that read the group.

    `before_id=None` with `after_id=None` is the mirror of that: the TAIL append, "put `id` last".
    It existed in `tree.renumber` from the start (both-None = `max(position) + 1024`) but had no
    way through this verb, so dropping a card at the very END of a column was unreachable and the
    transports raised "after_id ... has no following sibling — it is already last" at the user —
    an error for a perfectly ordinary gesture (owner report 2026-08-10). Head and tail are now
    both expressible, which is what a reorder verb owes its callers.
    """
    owner = _require_str(owner, "owner")
    id = _require_str(id, "id")
    if after_id is not None:
        after_id = _require_str(after_id, "after_id")
    if before_id is not None:
        before_id = _require_str(before_id, "before_id")
    if after_id is not None and before_id is None:
        # `renumber` refuses this pair for its own documented reason (the row after `after_id`
        # bounds the midpoint and only the caller that read the group knows it). Callers wanting
        # the tail say so with both None.
        raise ValidationError(
            "move_between needs both after_id and before_id, or before_id alone (head insert), "
            "or neither (tail append)",
            field="before_id",
        )

    with conn.transaction():
        row = conn.execute(
            "SELECT vertical, period_key, parent_id FROM goals"
            " WHERE owner = %(owner)s AND id = %(id)s FOR UPDATE",
            {"owner": owner, "id": id},
        ).fetchone()
        if row is None:
            raise NotFound(f"no goal {id!r} for owner {owner!r}", id=id, owner=owner)
        vertical, period_key, parent_id = row

        position = allocate_position(
            conn,
            owner=owner,
            vertical=vertical,
            period_key=period_key,
            parent_id=parent_id,
            after_id=after_id,
            before_id=before_id,
        )

        # `clock_timestamp()`, never `now()`, for `updated_at` — `core/goals.py#update` carries
        # the reasoning (transaction-start time runs backwards for a concurrent reader; AC-135).
        updated = conn.execute(
            f"""
            UPDATE goals SET position = %(position)s, updated_at = clock_timestamp()
             WHERE owner = %(owner)s AND id = %(id)s
             RETURNING {COLUMNS}
            """,
            {"owner": owner, "id": id, "position": position},
        ).fetchone()

    return _to_goal(updated)


# --- reparent -------------------------------------------------------------------------------------


def reparent(conn: psycopg.Connection, *, owner: str, id: str, parent_id: str | None) -> Goal:
    """Dispatches to `tree.move` (a real new parent) or `tree.detach` (`parent_id=None`) —
    S-11's own boundary between the two, restated at the public-verb layer. `NotFound` and
    `CycleRefused` both come straight from `tree.py`'s own guard; nothing here second-guesses
    them. The one thing this wrapper adds is the full `Goal` row: `tree.move`/`tree.detach`
    return `RewrittenRow` (id/path/depth only, `tree.py`'s own call envelope, not the read-model
    `Goal`), so the caller here re-reads the single row it just changed. That extra `SELECT` runs
    *after* `tree.py`'s own transaction has already closed (`with conn.transaction()` inside
    `tree.move`/`tree.detach` exits before this function's own body continues), so it changes
    nothing about S-09's "zero `UPDATE`" or S-10's "exactly one `UPDATE`" — both are asserted
    against the statement log of the call to `tree.move` alone, not this wrapper.
    """
    owner = _require_str(owner, "owner")
    id = _require_str(id, "id")

    # D241 (KK, 2026-08-16) supersedes D179's block half: the same-vertical refusal that stood
    # here ("same-vertical subgoal must stay under its parent") is gone. D236's combine gesture
    # made same-vertical subtasks the ordinary product of a two-second drag, and this refusal
    # made that a one-way door — easy in, no way out (KK report: drag-out and drag-to-another-
    # parent silently dead). An explicit reparent — detach or a new parent — is now always
    # legal; the cycle guard and depth clamp below in `tree.py` still judge the destination.
    current = conn.execute(
        "SELECT vertical IS NULL FROM goals WHERE owner = %(owner)s AND id = %(id)s",
        {"owner": owner, "id": id},
    ).fetchone()
    if current is None:
        raise NotFound(f"no goal {id!r} for owner {owner!r}", id=id, owner=owner)
    undated = bool(current[0])

    if parent_id is None:
        tree.detach(conn, owner=owner, id=id)
    else:
        tree.move(conn, owner=owner, id=id, new_parent_id=parent_id)
    if parent_id is not None and undated:
        # An undated goal takes the column of the goal it now sits under, as a new one does (`tree.attach`): the Inbox
        # shelves it there (`core/undated.py`). A dated goal keeps no such column (008_park_foil.sql's CHECK), so S-10's
        # dated move stays one UPDATE.
        conn.execute(
            """
            UPDATE goals g
               SET parked_from_vertical = COALESCE(p.vertical::text, p.parked_from_vertical, g.parked_from_vertical)
              FROM goals p
             WHERE g.owner = %(owner)s AND g.id = %(id)s AND g.vertical IS NULL
               AND p.owner = g.owner AND p.id = %(parent_id)s
            """,
            {"owner": owner, "id": id, "parent_id": parent_id},
        )

    row = conn.execute(
        f"SELECT {COLUMNS} FROM goals WHERE owner = %(owner)s AND id = %(id)s", {"owner": owner, "id": id}
    ).fetchone()
    return _to_goal(row)


# --- schedule -------------------------------------------------------------------------------------


def schedule(
    conn: psycopg.Connection, *, owner: str, id: str, vertical: str | None, anchor_date: _date | None
) -> Scheduled:
    """Recompute `period_key` from `vertical`/`anchor_date` (the one place `core/vertical.py`'s
    `period_key` is called from a write path — AC-012, never reimplemented here) and land the
    goal at the tail of its *new* group. A fresh tail position, not the row's old one: the old
    position was only ever unique within the old group, and carrying it into a different one
    could collide with whatever already sits there — AC-203's own invariant would then be
    violated by the write this function just made. Structure (`parent_id`/`path`/`depth`) is
    untouched: scheduling is a timing change, not a move — `reparent` above is the structure
    verb, and the two compose (S-04's own step 2 calls both in sequence and expects each to
    touch only its own columns).

    `vertical=None, anchor_date=None` clears a schedule (S-38's second step): the row keeps its
    real `parent_id` (a subgoal that loses its vertical stays that parent's subgoal, unscheduled
    — it lands in the Maybe pile only if its own `parent_id` already happens to be `None`, since
    Maybe additionally requires that, `core/board.py`'s own `MAYBE_PREDICATE`), so the position
    lock/renumber scope for a *clear* is `(owner, parent_id)` — the row's own current parent,
    read under `FOR UPDATE` first since it decides which group's lock to take — never a
    hard-coded `parent_id=None`, which is only correct for the *set* path below (a vertical-set
    group is `(owner, vertical, period_key)` regardless of `parent_id`, `tree.py`'s own
    docstring), not the clear path.

    D108's set-path reconciliation is deliberately asymmetric: the row must still fit under its
    own parent, but scheduled descendants above the new vertical are clamped to this row's exact
    destination. The path-prefix bulk write reaches the whole subtree; parked descendants remain
    untouched.

    D109 widens the same bulk write into a family move: descendants sitting in the row's OLD
    `(vertical, period_key)` group travel to the destination too, in every direction. They are
    the rows the board renders NESTED inside this card (`boardProjection.ts`'s R7 rule — same
    vertical, same column), so the card and its inline children are one visual unit and the
    owner's gesture moves the unit (owner report 2026-08-12: "when u move it up, the child
    moves together with her. Thought that's obvious"). Descendants at other verticals/periods
    keep their own schedule exactly as before; on a down-move an old-group member is also a
    rank violator, so the two predicates land on the same destination and the union stays one
    statement. Known edge, accepted in D109: legacy decade-keyed rows nest by column bounds,
    not by equal `period_key`, so they do not family-follow.
    """
    owner = _require_str(owner, "owner")
    id = _require_str(id, "id")
    vertical, anchor_date, period_key = _validate_schedule(vertical, anchor_date)

    if vertical is None:
        return Scheduled(park(conn, owner=owner, id=id), 0)

    with conn.transaction():
        current = conn.execute(
            "SELECT parent_id, path, vertical, period_key FROM goals"
            " WHERE owner = %(owner)s AND id = %(id)s FOR UPDATE",
            {"owner": owner, "id": id},
        ).fetchone()
        if current is None:
            raise NotFound(f"no goal {id!r} for owner {owner!r}", id=id, owner=owner)
        parent_id, path, old_vertical, old_period_key = current

        if parent_id is not None:
            parent = conn.execute(
                "SELECT vertical FROM goals"
                " WHERE owner = %(owner)s AND id = %(parent_id)s FOR SHARE",
                {"owner": owner, "parent_id": parent_id},
            ).fetchone()
            if parent is None:
                raise NotFound(
                    f"no goal {parent_id!r} for owner {owner!r}", id=parent_id, owner=owner
                )
            placement.validate_child_vertical(
                child_vertical=vertical,
                parent_vertical=parent[0],
                child_id=id,
                parent_id=parent_id,
            )
            # A nested row may leave its parent's rendered group by changing schedule; structure
            # remains intact because this verb never writes parent_id/path/depth. D179 blocks
            # detach/reparent, not this Things-style drag from an expanded parent into a column.

        position = allocate_position(
            conn, owner=owner, vertical=vertical, period_key=period_key, parent_id=None
        )
        # `clock_timestamp()`, never `now()`, for `updated_at` — see `core/goals.py#update`.
        row = conn.execute(
            f"""
            UPDATE goals
               SET vertical = %(vertical)s::vertical_scale, anchor_date = %(anchor_date)s,
                   period_key = %(period_key)s, parked_from_vertical = NULL,
                   position = %(position)s, updated_at = clock_timestamp()
             WHERE owner = %(owner)s AND id = %(id)s
             RETURNING {COLUMNS}
            """,
            {
                "owner": owner,
                "id": id,
                "vertical": vertical,
                "anchor_date": anchor_date,
                "period_key": period_key,
                "position": position,
            },
        ).fetchone()

        # vertical.py declaration order is the one placement rank law. SQL receives only the
        # enum values that violate it; no second rank mapping is reimplemented in the database.
        violating_verticals = [
            descriptor.key
            for descriptor in vertical_mod.VERTICALS
            if vertical_mod.rank(descriptor.key) > vertical_mod.rank(vertical)
        ]
        clamped_rows: list[tuple[str]] = []
        # D109: the family predicate compares against the row's OLD group. A parked or
        # never-scheduled row has old_vertical NULL, which matches no descendant (SQL equality),
        # so only the violator half can fire there.
        moved_out_of_old_group = old_vertical is not None and (
            old_vertical != vertical or old_period_key != period_key
        )
        if violating_verticals or moved_out_of_old_group:
            # The primary allocation already locked this destination group. Re-enter the same
            # transaction-scoped lock through the existing allocator for the clamp set after the
            # primary has landed, making this returned position the next real tail slot.
            clamp_position = allocate_position(
                conn, owner=owner, vertical=vertical, period_key=period_key, parent_id=None
            )
            pattern = (
                path.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
            )
            clamped_rows = conn.execute(
                """
                WITH clamp_rows AS (
                    SELECT id, row_number() OVER (ORDER BY depth, path, id) AS position_offset
                      FROM goals
                     WHERE owner = %(owner)s
                       AND path LIKE %(pattern)s ESCAPE '\\'
                       AND id <> %(id)s
                       AND (
                           vertical = ANY(%(violating_verticals)s::vertical_scale[])
                           OR (
                               vertical = %(old_vertical)s::vertical_scale
                               AND period_key = %(old_period_key)s
                           )
                       )
                )
                UPDATE goals AS g
                   SET vertical = %(vertical)s::vertical_scale,
                       anchor_date = %(anchor_date)s,
                       period_key = %(period_key)s,
                       parked_from_vertical = NULL,
                       position = (
                           %(clamp_position)s
                           + (clamp_rows.position_offset - 1) * %(position_gap)s
                       )::integer,
                       updated_at = clock_timestamp()
                  FROM clamp_rows
                 WHERE g.owner = %(owner)s AND g.id = clamp_rows.id
                RETURNING g.id
                """,
                {
                    "owner": owner,
                    "id": id,
                    "pattern": pattern,
                    "violating_verticals": violating_verticals,
                    "old_vertical": old_vertical,
                    "old_period_key": old_period_key,
                    "vertical": vertical,
                    "anchor_date": anchor_date,
                    "period_key": period_key,
                    "clamp_position": clamp_position,
                    "position_gap": tree.POSITION_GAP,
                },
            ).fetchall()

    if row is None:
        raise NotFound(f"no goal {id!r} for owner {owner!r}", id=id, owner=owner)
    return Scheduled(_to_goal(row), len(clamped_rows))


def park(conn: psycopg.Connection, *, owner: str, id: str) -> Goal:
    """Unset one goal's vertical without moving any tree or ordering field. One UPDATE records
    the old scale and clears only vertical/period_key; anchor_date remains restore-friendly.
    Unknown and foreign ids share the ordinary owner-scoped `NotFound` shape."""
    owner = _require_str(owner, "owner")
    id = _require_str(id, "id")

    with conn.transaction():
        current = conn.execute(
            "SELECT vertical, anchor_date, parent_id, repeat_rule FROM goals"
            " WHERE owner = %(owner)s AND id = %(id)s FOR UPDATE",
            {"owner": owner, "id": id},
        ).fetchone()
        if current is None:
            raise NotFound(f"no goal {id!r} for owner {owner!r}", id=id, owner=owner)
        old_vertical, anchor_date, parent_id, repeat_rule = current
        if old_vertical is None:
            raise ValidationError(f"goal {id!r} is already parked", field="id", id=id)
        if parent_id is None and vertical_mod.descriptor(old_vertical).bounds_fn(anchor_date) is None:
            raise ValidationError("a life value cannot be parked", field="id", id=id)
        if repeat_rule is not None:
            raise ValidationError(
                "a repeating goal cannot be parked; clear repeat first", field="repeat"
            )

        row = conn.execute(
            f"""
            UPDATE goals
               SET vertical = NULL, period_key = NULL, parked_from_vertical = %(old_vertical)s,
                   updated_at = clock_timestamp()
             WHERE owner = %(owner)s AND id = %(id)s
             RETURNING {COLUMNS}
            """,
            {"owner": owner, "id": id, "old_vertical": old_vertical},
        ).fetchone()

    return _to_goal(row)
