"""Materialised path, depth, the cycle guard and integer gap ordering — WP-08.

`docs/IMPLEMENTATION.md` WP-08 card; `docs/E2E.md` S-06 through S-16; IR-11 (§0.3). The WP-08
card calls this "the riskiest package in the build" and names three traps, each already written
as an assertion in the catalogue:

  1. **The cycle guard must be evaluated inside the transaction that would do the write** (S-09):
     a check-then-write implementation passes a naive test and loses the race. `move` below locks
     both rows in one `SELECT ... FOR UPDATE`, evaluates the guard against that lock, and either
     raises with zero further statements or proceeds to the rewrite — never a separate check
     followed by a separate write.
  2. **The subtree rewrite is one prefix `UPDATE` over `path LIKE`, not a walk** (S-10): every
     naive implementation is a recursive per-row walk that passes the value assertions and fails
     the statement-count one. `_rewrite_subtree` is that one statement, shared by `move` and
     `detach`.
  3. **The renumber is one `UPDATE ... FROM (VALUES ...)`, not fourteen** (S-13): `renumber`'s
     exhaustion path reassigns the whole sibling group's positions in one bulk statement built
     from a single prior read, not one `UPDATE` per row.

Plus IR-11's bound: a `move` (or `attach`) that would put any affected row past depth 32 raises
`ValidationError` naming `depth`, before any `UPDATE`/`INSERT` runs.

**Owner scoping** (`ARCHITECTURE.md` §3b): every statement below carries `owner = %(owner)s`; no
function here has a default for it. **IR-02**: every function takes an open connection and never
commits. The multi-statement bodies below (`attach`, `move`, `detach`, `renumber`) each wrap their
own sequence in `with conn.transaction()` — on a connection already inside a transaction (the
production path: the transport opens one per request and every `core/` call simply joins it) this
is a `SAVEPOINT`, never a second top-level commit; called directly against an autocommit
connection with nothing open yet (this package's own tests do exactly that) it becomes the
top-level transaction itself. Either way the guard's lock and the write it gates always share one
atomic unit, which is S-09's whole point and the reason this module does not leave "wrap me in a
transaction" as an unenforced instruction to every future caller.

**What this module deliberately does not do.** It does not derive `period_key` from
`vertical`/`anchor_date` (AC-012: that arithmetic is `core/vertical.py`'s alone; the caller derives
it and hands the result through) and it does not validate `vertical` against the seven scale
strings (same reason — `core/tree.py` never imports `core/vertical.py`). It does not retry an id
collision (IR-05 frames that retry loop as the id generator's job, in `core/goals.py`; `attach`
returns `None` on a collision rather than raising, so that loop can be built on top). It does not
validate `tags` cardinality or a nested `create` call's node count (IR-11 splits those two bounds
to `core/goals.py`; only `depth` is this module's bound to enforce). It takes no position on
concurrent structural writes to the *same* subtree from two different connections beyond what a
row lock on the two rows the guard touches buys for free — `docs/E2E.md`'s S-127/S-128 (an
advisory lock keyed on `hashtext(owner || vertical || period_key)`, AC-204) is `core/moves.py`'s
job, wave 3.

**A decision the documents leave implicit, resolved here and checked against real data**: what
scopes one "sibling group" for gap ordering. `AC-203`'s tree invariant polices a duplicate
`(owner, vertical, period_key, position)` — but F2 itself, as shipped, has three such literal
duplicates (`SYNMAY01`/`SYNSUB01` both at position 1024, `SYNMAY02`/`SYNSUB02` at 2048,
`SYNMAY03`/`SYNSUB03` at 3072 — verified directly against a loaded F2 clone), which is only
consistent if that invariant — and the sibling-group concept generally — applies to board columns
(`vertical IS NOT NULL`) alone. So: a card's (`vertical` set) sibling group is `(owner, vertical,
period_key)`, matching every "the column" reference in `ARCHITECTURE.md` §3, AC-018/AC-019 and
AC-204's own lock key, regardless of `parent_id` (confirmed by F2's own comment on `SYNQ2R01`:
two rows with *different* parents still share one column and must not collide there). A subgoal's
or Maybe candidate's (`vertical IS NULL`) sibling group is `(owner, parent_id)` instead — the only
remaining dimension that actually distinguishes one NULL-vertical group from another.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date

import psycopg
from psycopg.types.json import Jsonb

from verticals.core import vertical as vertical_mod
from verticals.core import placement
from verticals.core.errors import CycleRefused, NotFound, ValidationError
from verticals.models import Goal

# IR-11: depth <= 32 is legal, 33 is not. `depth_bounded` in 001_init.sql is the DB-level
# backstop at the same number — never the declared limit itself, this module is.
MAX_DEPTH = 32

# ARCHITECTURE.md §3's own number: gaps of 1024, never a float. The first row in an empty
# sibling group lands here; a renumber reassigns the whole group to strict multiples of it.
POSITION_GAP = 1024

# `Goal`'s fields are the table's columns in the table's own order (`core/search.py` pins the
# same list for the same reason) — one constant serves both `attach`'s RETURNING and `_to_goal`.
COLUMNS = (
    "id, owner, parent_id, path, depth, vertical, anchor_date, period_key, "
    "title, body, color, tags, done_at, position, origin, created_at, updated_at, "
    "repeat_rule, repeat_series_id, repeat_index, repeat_start_date, "
    "parked_from_vertical, foil, carryover_ignored_until, size_expected, size_actual"
)


@dataclass(frozen=True)
class RewrittenRow:
    """One row's new `path`/`depth` after a `move` or `detach` rewrite — `id` plus exactly the
    two columns the rewrite touches, for every row the prefix `UPDATE` matched (the moved/
    detached node itself, plus every descendant). Deliberately not `verticals/models.py`: that
    module is the read-model vocabulary, and this is a call envelope — the same reasoning
    `core/search.py`'s own `SearchResult` is not there either."""

    id: str
    path: str
    depth: int


def _require_str(value: object, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValidationError(f"{field} is required and must be a non-empty string", field=field)
    return value


def _escape_like(text: str) -> str:
    """Defence in depth, not a response to a real attack surface: every path prefix this module
    builds a `LIKE` pattern from was itself read back from `goals.path` a moment earlier inside
    the same transaction, not typed by a caller, and IR-05's id alphabet (base62) contains no
    `%`, `_` or `\\`. Escaped anyway, because correctness here should not rest on an assumption
    this module cannot see enforced — `id TEXT PRIMARY KEY` carries no CHECK pinning that
    alphabet (`ARCHITECTURE.md` §3). One copy of `core/search.py`'s `escape_like`, kept local:
    the two modules are wave-2 siblings with no dependency between them, and this is three lines.
    """
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _to_goal(row: tuple) -> Goal:
    values = list(row)
    values[11] = tuple(values[11])  # tags: psycopg hands back a list, `Goal` is frozen
    values[24] = tuple(values[24]) if values[24] is not None else None
    values[25] = tuple(values[25]) if values[25] is not None else None
    return Goal(*values)


def _fetch_locked(
    conn: psycopg.Connection, *, owner: str, ids: Sequence[str]
) -> dict[str, tuple[str | None, str, int, str | None, str | None]]:
    """`{id: (parent_id, path, depth, vertical, parked_from_vertical)}` for every id in `ids`
    that exists under `owner`, row-
    locked in **one** statement regardless of how many distinct ids are asked for — the shape
    S-09 measures: whether `id` and `new_parent_id` name the same row or two, this is always
    exactly one `SELECT ... FOR UPDATE`."""
    unique_ids = list(dict.fromkeys(ids))
    rows = conn.execute(
        "SELECT id, parent_id, path, depth, vertical, parked_from_vertical FROM goals"
        " WHERE owner = %(owner)s AND id = ANY(%(ids)s)"
        " FOR UPDATE",
        {"owner": owner, "ids": unique_ids},
    ).fetchall()
    return {r[0]: (r[1], r[2], r[3], r[4], r[5]) for r in rows}


def _rewrite_subtree(
    conn: psycopg.Connection,
    *,
    owner: str,
    id: str,
    old_path: str,
    old_depth: int,
    new_parent_id: str | None,
    new_path: str,
    new_depth: int,
) -> tuple[RewrittenRow, ...]:
    """The one prefix `UPDATE` that `move` and `detach` both are — R1's whole risk (§5), in one
    place. `path LIKE old_path || '%'` matches `id` itself (an exact match: `%` may match zero
    characters) and every descendant, because a descendant's path always extends `old_path`
    exactly — materialised paths are anchored on whole `/id/` segments, so this can never match
    an unrelated row whose *own* id merely shares a substring with `id` (`docs/IMPLEMENTATION.md`
    line 1329's named risk: the match is against the full ancestor-chain prefix, not a bare id
    substring, so a collision would need another row's entire chain-so-far to equal `old_path`,
    which — ids being the primary key — cannot happen while `old_path` itself remains assigned to
    `id`). `substring(path from len(old_path)+1)` peels off exactly the ancestor chain being
    replaced and keeps whatever a descendant's own path added past it. Only `id`'s own
    `parent_id` changes — a descendant's `parent_id` is a direct pointer to its own immediate
    parent, which an ancestor's move never touches — hence the `CASE WHEN`."""
    depth_delta = new_depth - old_depth
    cut = len(old_path) + 1
    # `clock_timestamp()` below, not `now()`: `now()` is transaction-start time, so a writer that
    # opens earlier and commits later stamps an older `updated_at` than a concurrent reader has
    # already seen on that row (AC-135 / docs/E2E.md S-58). Argument in full: `core/goals.py`'s
    # own `update()`, above its `set_clauses`.
    rows = conn.execute(
        """
        UPDATE goals
           SET parent_id = CASE WHEN id = %(id)s THEN %(new_parent_id)s ELSE parent_id END,
               path = %(new_path)s || substring(path from %(cut)s),
               depth = depth + %(depth_delta)s,
               updated_at = clock_timestamp()
         WHERE owner = %(owner)s AND path LIKE %(pattern)s ESCAPE '\\'
         RETURNING id, path, depth
        """,
        {
            "id": id,
            "new_parent_id": new_parent_id,
            "new_path": new_path,
            "cut": cut,
            "depth_delta": depth_delta,
            "owner": owner,
            "pattern": _escape_like(old_path) + "%",
        },
    ).fetchall()
    return tuple(RewrittenRow(*r) for r in rows)


def _check_depth(new_depth: int, *, verb: str, id: str) -> None:
    if new_depth > MAX_DEPTH:
        raise ValidationError(
            f"{verb} would put {id!r} at depth {new_depth}, exceeding the maximum of {MAX_DEPTH}",
            field="depth",
            maximum=MAX_DEPTH,
            attempted=new_depth,
        )


# --- attach -----------------------------------------------------------------------------------


def attach(
    conn: psycopg.Connection,
    *,
    owner: str,
    id: str,
    parent_id: str | None,
    title: str,
    body: str = "",
    vertical: str | None = None,
    anchor_date: date | None = None,
    period_key: str | None = None,
    color: str | None = None,
    tags: Sequence[str] = (),
    origin: str = "human",
    position: int | None = None,
    repeat_rule: dict | None = None,
    repeat_series_id: str | None = None,
    repeat_index: int | None = None,
    repeat_start_date: date | None = None,
    parked_from_vertical: str | None = None,
) -> Goal | None:
    """Insert one new row as a child of `parent_id` (root, when `parent_id` is `None`).

    `path`/`depth` are computed from the parent's own row, read and locked `FOR UPDATE` in the
    same transaction as the `INSERT` (S-06, S-07). `position` defaults to a tail append via
    `renumber` when not given explicitly. `vertical`/`anchor_date`/`period_key` are stored exactly
    as given — already derived and validated by the caller (S-04's "period_key is derived, never
    accepted" is `core/goals.py`'s public-input boundary, not this internal primitive's).

    Returns `None`, not an exception, on a unique-key collision. The ordinary path is an `id`
    collision (IR-05); repeat materialisation can also race on its series/index unique key.
    """
    owner = _require_str(owner, "owner")
    id = _require_str(id, "id")
    if not isinstance(title, str):
        raise ValidationError("title must be a string", field="title")

    with conn.transaction():
        if parent_id is None:
            new_path = f"/{id}/"
            new_depth = 0
            parent_vertical = None
            parent_parked_from = None
        else:
            locked = _fetch_locked(conn, owner=owner, ids=[parent_id])
            if parent_id not in locked:
                raise NotFound(
                    f"no goal {parent_id!r} for owner {owner!r}", id=parent_id, owner=owner
                )
            _, parent_path, parent_depth, parent_vertical, parent_parked_from = locked[parent_id]
            new_depth = parent_depth + 1
            new_path = f"{parent_path}{id}/"
            placement.validate_child_vertical(
                child_vertical=vertical,
                parent_vertical=parent_vertical,
                child_id=id,
                parent_id=parent_id,
            )

        if vertical is None and parked_from_vertical is None:
            parked_from_vertical = (
                parent_vertical
                or parent_parked_from
                or vertical_mod.VERTICALS[-1].key
            )

        _check_depth(new_depth, verb="attach", id=id)

        if position is None:
            position = renumber(
                conn, owner=owner, vertical=vertical, period_key=period_key, parent_id=parent_id
            )

        row = conn.execute(
            f"""
            INSERT INTO goals
              (id, owner, parent_id, path, depth, vertical, anchor_date, period_key,
               title, body, color, tags, position, origin, repeat_rule, repeat_series_id,
               repeat_index, repeat_start_date, parked_from_vertical)
            VALUES
              (%(id)s, %(owner)s, %(parent_id)s, %(path)s, %(depth)s,
               %(vertical)s::vertical_scale, %(anchor_date)s, %(period_key)s,
               %(title)s, %(body)s, %(color)s, %(tags)s, %(position)s, %(origin)s::goal_origin,
               %(repeat_rule)s::jsonb, %(repeat_series_id)s, %(repeat_index)s,
               %(repeat_start_date)s, %(parked_from_vertical)s)
            ON CONFLICT DO NOTHING
            RETURNING {COLUMNS}
            """,
            {
                "id": id,
                "owner": owner,
                "parent_id": parent_id,
                "path": new_path,
                "depth": new_depth,
                "vertical": vertical,
                "anchor_date": anchor_date,
                "period_key": period_key,
                "title": title,
                "body": body,
                "color": color,
                "tags": list(tags),
                "position": position,
                "origin": origin,
                "repeat_rule": Jsonb(repeat_rule) if repeat_rule is not None else None,
                "repeat_series_id": repeat_series_id,
                "repeat_index": repeat_index,
                "repeat_start_date": repeat_start_date,
                "parked_from_vertical": parked_from_vertical,
            },
        ).fetchone()

    return _to_goal(row) if row is not None else None


# --- move -------------------------------------------------------------------------------------


def move(
    conn: psycopg.Connection, *, owner: str, id: str, new_parent_id: str
) -> tuple[RewrittenRow, ...]:
    """Reparent `id` under `new_parent_id`, rewriting `id`'s own subtree in one `UPDATE`.

    Trap 1 (S-09): both rows are locked in one `SELECT ... FOR UPDATE`, the cycle guard is
    evaluated against that lock, and a refusal issues zero further statements. Trap 2 (S-10): the
    rewrite is `_rewrite_subtree`'s one prefix `UPDATE`. IR-11: refused with `ValidationError`
    naming `depth` when the *deepest* existing descendant — not just `id` itself — would land
    past 32.

    `new_parent_id` must be a real id — reparenting to root is `detach`, not `move(...,
    new_parent_id=None)`, matching S-11's own boundary between the two verbs.
    """
    owner = _require_str(owner, "owner")
    id = _require_str(id, "id")
    new_parent_id = _require_str(new_parent_id, "new_parent_id")

    with conn.transaction():
        locked = _fetch_locked(conn, owner=owner, ids=[id, new_parent_id])
        if id not in locked:
            raise NotFound(f"no goal {id!r} for owner {owner!r}", id=id, owner=owner)
        if new_parent_id not in locked:
            raise NotFound(
                f"no goal {new_parent_id!r} for owner {owner!r}", id=new_parent_id, owner=owner
            )

        _, this_path, this_depth, this_vertical, _ = locked[id]
        _, new_parent_path, new_parent_depth, new_parent_vertical, _ = locked[new_parent_id]

        # The guard, evaluated on the same row lock this transaction already holds — S-09's
        # whole point. `new_parent.path LIKE this.path || '%'` is true both when `new_parent`
        # *is* `this` (S-08's trivial case: any string starts with itself) and when it is one of
        # `this`'s descendants (S-09) — one check serves both, no special case needed.
        if new_parent_path == this_path or new_parent_path.startswith(this_path):
            reason = "self" if new_parent_id == id else "target_is_descendant"
            raise CycleRefused(
                f"cannot move {id!r} under {new_parent_id!r}: {reason}",
                reason=reason,
                id=id,
                new_parent_id=new_parent_id,
            )

        placement.validate_child_vertical(
            child_vertical=this_vertical,
            parent_vertical=new_parent_vertical,
            child_id=id,
            parent_id=new_parent_id,
        )

        new_depth = new_parent_depth + 1
        (subtree_max_depth,) = conn.execute(
            "SELECT max(depth) FROM goals WHERE owner = %(owner)s AND path LIKE %(pattern)s"
            " ESCAPE '\\'",
            {"owner": owner, "pattern": _escape_like(this_path) + "%"},
        ).fetchone()
        depth_delta = new_depth - this_depth
        _check_depth(subtree_max_depth + depth_delta, verb="move", id=id)

        new_path = f"{new_parent_path}{id}/"
        rewritten = _rewrite_subtree(
            conn,
            owner=owner,
            id=id,
            old_path=this_path,
            old_depth=this_depth,
            new_parent_id=new_parent_id,
            new_path=new_path,
            new_depth=new_depth,
        )

    return rewritten


# --- detach -----------------------------------------------------------------------------------


def detach(conn: psycopg.Connection, *, owner: str, id: str) -> tuple[RewrittenRow, ...]:
    """Reparent `id` to root — `path = '/' || id || '/'`, `depth = 0` (S-11). Shares
    `_rewrite_subtree` with `move`, so the whole subtree still moves in one `UPDATE`. Detaching
    never increases depth, so — unlike `move` — there is no bound to check. `vertical`/
    `anchor_date`/`period_key` are untouched: a detached card stays a card (S-11's own point —
    Maybe requires `vertical IS NULL`, which this never sets)."""
    owner = _require_str(owner, "owner")
    id = _require_str(id, "id")

    with conn.transaction():
        locked = _fetch_locked(conn, owner=owner, ids=[id])
        if id not in locked:
            raise NotFound(f"no goal {id!r} for owner {owner!r}", id=id, owner=owner)
        _, this_path, this_depth, _, _ = locked[id]

        rewritten = _rewrite_subtree(
            conn,
            owner=owner,
            id=id,
            old_path=this_path,
            old_depth=this_depth,
            new_parent_id=None,
            new_path=f"/{id}/",
            new_depth=0,
        )

    return rewritten


# --- renumber -----------------------------------------------------------------------------------


def renumber(
    conn: psycopg.Connection,
    *,
    owner: str,
    vertical: str | None,
    period_key: str | None,
    parent_id: str | None,
    after_id: str | None = None,
    before_id: str | None = None,
) -> int:
    """Allocate the `position` for one row entering a sibling group — the gap-ordering entry
    point `attach` (tail append) and `core/moves.py`'s future `move_between` (a midpoint) both
    call, renumbering the whole group first, in one statement, if the requested gap is exhausted
    (S-12, S-13). Returns the position to use; does not itself write it onto any row — `attach`'s
    own `INSERT` and `move_between`'s own single-row `UPDATE` are the caller's job.

    A sibling group is identified by `vertical`: `(owner, vertical, period_key)` when set (a board
    column, regardless of `parent_id` — see the module docstring's F2-verified reasoning), or
    `(owner, parent_id)` when `vertical` is `None` (a subgoal list, or the Maybe pile when
    `parent_id` is also `None`).

    `after_id`/`before_id` name two *adjacent* existing siblings for a midpoint insert — both
    `None` means "append at the tail" (`max(position) + 1024`, or `1024` for an empty group).
    Adjacency itself is trusted, not verified: a non-adjacent pair produces a midpoint that may
    collide with a row already between them, which is `move_between`'s contract to uphold, not
    this primitive's to police.

    **`before_id` alone means "immediately before that row"** — the head insert (`docs/
    PENDING_DOC_FIXES.md` rows 109, 116(c)). Until it existed, `after_id` was the only ordering
    argument on either transport and the first position of every list was unreachable: "move this
    to the top" had no encoding at all, and the shipped UI marked its up control `aria-disabled`
    at index 1 as the honest consequence. It lives here rather than in a transport because the
    gap arithmetic and the exhausted-group renumber below are this primitive's, taken under the
    same `FOR UPDATE` and the same advisory lock as every other insert — a transport computing
    `position // 2` for itself would be doing that arithmetic outside the lock.

    `after_id` alone stays refused: "after X" needs the row that follows X to bound the midpoint,
    and only the caller that read the group knows which that is. The head has no such ambiguity —
    there is nothing before `before_id` by definition — which is exactly why this one direction
    can be expressed with a single id and the other cannot.
    """
    owner = _require_str(owner, "owner")
    if after_id is not None and before_id is None:
        raise ValidationError(
            "renumber needs both after_id and before_id, or before_id alone (insert before it), "
            "or neither (tail append)",
            field="after_id,before_id",
        )

    with conn.transaction():
        if vertical is not None:
            where = "vertical = %(vertical)s::vertical_scale AND period_key = %(period_key)s"
        else:
            where = "vertical IS NULL AND parent_id IS NOT DISTINCT FROM %(parent_id)s"

        # FOR UPDATE: two concurrent renumbers (or a renumber racing a move_between reading the
        # same group) serialise on these rows rather than both computing from the same stale
        # snapshot. It does not close the whole gap named at IMPLEMENTATION.md:1330 — a brand
        # new concurrent INSERT has no existing row here to lock — that is what AC-204's
        # transaction-scoped advisory lock on hashtext(owner || vertical || period_key) is for,
        # core/moves.py's job at wave 3, not this primitive's.
        rows = conn.execute(
            f"SELECT id, position FROM goals"
            f" WHERE owner = %(owner)s AND {where}"
            f" ORDER BY position, id"
            f" FOR UPDATE",
            {"owner": owner, "vertical": vertical, "period_key": period_key, "parent_id": parent_id},
        ).fetchall()

        if after_id is None and before_id is None:
            return rows[-1][1] + POSITION_GAP if rows else POSITION_GAP

        positions = dict(rows)
        if after_id is not None and after_id not in positions:
            raise NotFound(f"no goal {after_id!r} for owner {owner!r}", id=after_id, owner=owner)
        if before_id not in positions:
            raise NotFound(f"no goal {before_id!r} for owner {owner!r}", id=before_id, owner=owner)
        before_pos = positions[before_id]

        if after_id is None:
            # Head insert. The floor of half the head's own position is strictly below it and
            # strictly above nothing (there is nothing below the head), so it is free by
            # construction — for any `before_pos >= 2`. `before_pos <= 1` is the head-side form of
            # the same exhaustion the midpoint branch below hits, and takes the same cure.
            if before_pos >= 2:
                return before_pos // 2
        else:
            after_pos = positions[after_id]
            if before_pos - after_pos > 1:
                return (after_pos + before_pos) // 2

        # Exhausted (trap 3, S-13): renumber the whole group to strict 1024-multiples, in its
        # own current relative order, in one statement — "not fourteen".
        # `clock_timestamp()` in the statement below — see `core/goals.py#update` on why never
        # `now()` for an `updated_at` write.
        ordered_ids = [gid for gid, _ in rows]
        placeholders = ", ".join(["(%s, %s)"] * len(ordered_ids))
        values_params: list[object] = []
        for rank, gid in enumerate(ordered_ids):
            values_params.extend([gid, (rank + 1) * POSITION_GAP])
        conn.execute(
            f"""
            UPDATE goals AS g
               SET position = v.new_position, updated_at = clock_timestamp()
              FROM (VALUES {placeholders}) AS v(id, new_position)
             WHERE g.owner = %s AND g.id = v.id
            """,
            [*values_params, owner],
        )

        rank_of = {gid: rank for rank, gid in enumerate(ordered_ids)}
        new_before = (rank_of[before_id] + 1) * POSITION_GAP
        if after_id is None:
            return new_before // 2  # head insert: half of the renumbered head's own gap
        new_after = (rank_of[after_id] + 1) * POSITION_GAP
        return (new_after + new_before) // 2
