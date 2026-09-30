"""The whole board — eight columns, cards, direct children, ancestors and progress — in one
SQL statement (`docs/IMPLEMENTATION.md` WP-09; IR-07). S-22's execute-count delta of 1 is what
this module buys over `RESEARCH.md` §3's incumbent, "30+ round trips" for the same screen.

Payload note (ruling 1, owner, 2026-08-09): this module's own eight-column shape is unchanged —
the client is what narrows it now. `Maybe` stopped being a board *column* on screen (superseded
`ARCHITECTURE.md`:445's "an eighth column, pinned left of Day"; the unverticaled pile is reached
through the client's Inbox nav view instead), but nothing here moved: the wire response still
carries all eight `COLUMN_ORDER` buckets in one statement, `Maybe` included, because
`web/src/components/InboxView.vue` still needs exactly that bucket and reads it off the same
`GET /api/board` response every other column comes from. Splitting the transport in two (one call
for the board, a second for Inbox) would trade a client-side filter for a real second round trip
to save nothing — IR-07's whole point is one call for the whole screen, and "the whole screen" now
spans two views instead of one.

**Per-column branches, not one `OR`-joined `WHERE`.** A goal renders in exactly one column
(`ARCHITECTURE.md` §3, AC-042) — the eight buckets already partition the table, so `UNION ALL`
costs nothing in row count and buys something real: Postgres plans each branch against its own
index independently. The Maybe pile (`vertical IS NULL AND parent_id IS NULL AND done_at IS
NULL`) has `goals_inbox`, a partial index built for exactly that predicate; the seven dated
branches share `goals_column`. A single `OR`-chained `WHERE` would force one plan across all
eight branches, which is the failure mode S-25/AC-043's `EXPLAIN` assertions exist to catch —
see `tests/core/test_board.py` for what PostgreSQL 16 actually chooses at 49 rows (F2) versus
what the plan-shape assertion requires at F4-5670 scale, and why those are two different claims
on two different corpora, not one assertion weakened to fit.

The seven dated branches are generated from `core/vertical.py`'s own `VERTICALS` list, never a
per-scale `if`/`elif` (AC-012): an eighth scale is a change to that file alone, and this
module's branch count follows without being told about it twice.

`progress`, `ancestors` and `children` are three `LEFT JOIN LATERAL`s over the same `cards` CTE
— one call each, never a second statement per row (AC-041's flat-row-set uniqueness and S-23's
"no N+1" are the same property, read from two directions). `ancestors` walks `path`'s own
segments (`unnest(...) WITH ORDINALITY`, stopping short of the last one — the node itself);
`progress` is a `goals_path`-indexed prefix-range count excluding self (see the comment directly
above the `prog` lateral below — `starts_with(d.path, cards.path)` read correctly as *rows*, but
correlated to a LATERAL outer reference it seq-scans the whole table per card, which is exactly
the defect measured in S-92/S-93/S-99 and fixed post-HEAD-eb3e048); `children` is a plain
`parent_id = cards.id`. None of the three needs `core/tree.py` — F2's literal, already-correct
paths are enough to prove all three here, which is why this package is `tree.py`'s sibling and
not its successor (this WP's own card).

`models.Board` gained two fields for this module — `children` and `ancestors`, both keyed by
`Goal.id`, matching `progress`'s own established convention (`models.py`'s own docstring already
named `core/board.py` as `Board`'s sole writer, before this module existed to be it).

IR-02: `board()` takes an open connection, never commits, never opens a transaction of its own
— one `conn.execute` already reads a single MVCC snapshot, so the whole board is consistent
without one.
"""

from __future__ import annotations

from dataclasses import replace as _replace
from datetime import date as _date
from datetime import datetime as _datetime
from datetime import timezone as _timezone
from datetime import timedelta as _timedelta

import psycopg

from verticals.core import vertical
from verticals.core.evidence import effective_sql
from verticals.core.errors import NotFound, ValidationError
from verticals.models import Ancestor, Board, Column, Goal, Progress

# `Goal`'s fields, table order — byte-for-byte `core/search.py`'s own `COLUMNS`, duplicated
# rather than imported cross-module: the two files share no dependency today (neither WP names
# the other), and a duplicate constant cannot make a sibling WP's refactor break this one.
COLUMNS = (
    "id, owner, parent_id, path, depth, vertical, anchor_date, period_key, "
    "title, body, color, tags, done_at, position, origin, created_at, updated_at, "
    "repeat_rule, repeat_series_id, repeat_index, repeat_start_date, "
    "parked_from_vertical, foil, carryover_ignored_until, size_expected, size_actual"
)
_TAGS_INDEX = 11  # tags' position within COLUMNS above — `_to_goal` below relies on this
_QUALIFIED_COLUMNS = ", ".join(f"cards.{name.strip()}" for name in COLUMNS.split(","))

MAYBE_KEY = "maybe"
# S-22's own column keys, "maybe" first, then `vertical.VERTICALS`'s declared order (day..life) —
# never hand-listed, so an eighth scale extends this tuple by construction, not by memory.
COLUMN_ORDER: tuple[str, ...] = (MAYBE_KEY,) + tuple(h.key for h in vertical.VERTICALS)

# `goals_inbox`'s own partial-index predicate (ARCHITECTURE.md §3), owner-free — byte-for-byte
# what the index's `WHERE` clause says, so `tests/core/test_board.py`'s S-25 isolated-predicate
# plan assertion explains this constant directly rather than a copy typed into the test. Public
# for that reason, matching `core/search.py`'s own `TRIGRAM_PREDICATE`; `_build_statement` below
# ANDs `owner = %(owner)s` onto it the same way `search.build_statement` ANDs it onto that one.
MAYBE_PREDICATE = "vertical IS NULL AND parent_id IS NULL AND done_at IS NULL"

# `_build_statement`'s boundedness probe (R10 below): any fixed date works, because whether a
# scale has bounds at all never depends on the date probed — only `life` returns None, always.
# A constant rather than `date.today()` so importing this module never reads the wall clock.
_BOUNDS_PROBE = _date(2026, 1, 1)


def _validate_owner(owner: object) -> str:
    if not isinstance(owner, str) or not owner:
        raise ValidationError("owner is required and must be a non-empty string", field="owner")
    return owner


def _validate_date(value: object) -> _date:
    # A `datetime` is also an instance of `date` (it subclasses it) — rejected explicitly rather
    # than silently truncated to its own date part, matching `core/search.py`'s own precedent of
    # refusing a surprising subtype instead of coercing it (`limit`'s `bool`-is-an-`int` guard).
    if isinstance(value, _datetime) or not isinstance(value, _date):
        raise ValidationError(
            "date must be a date, not a datetime or any other type", field="date"
        )
    return value


def _ladder() -> tuple[vertical.VerticalDescriptor, ...]:
    return tuple(vertical.descriptor(key) for key in vertical.ROLL_LADDER)


def _roll_thresholds(today: _date) -> dict[str, _date]:
    """`roll_<own>_<k>`: a plan of scale `own` anchored before it has reached scale `k` by
    `today`. Reaching k means the (k-1)-period it arrived in has ended before the current
    k-period began; walking that back down the ladder gives one date per pair, so the statement
    compares anchors only."""
    ladder = _ladder()
    out: dict[str, _date] = {}
    for i, own in enumerate(ladder):
        for k in range(i + 1, len(ladder)):
            threshold = ladder[k].bounds_fn(today)[0]
            for m in range(k - 1, i, -1):
                threshold = ladder[m].bounds_fn(threshold - _timedelta(days=1))[0]
            out[f"roll_{own.key}_{ladder[k].key}"] = own.bounds_fn(threshold)[0]
    return out


def _build_statement() -> str:
    """Built once, at import time — the branches' `WHERE` text never depends on a call's
    own parameter *values* (only on `core/vertical.py`'s fixed scale list), so there is nothing
    to rebuild per call. Parameter values are bound at call time in `board()`.

    Each branch's `SELECT ... FROM goals WHERE ...` is assembled right here, inline, rather than
    through a shared per-branch helper taking an opaque `where: str` — a helper like that would
    put `"FROM goals"` in its own body and `"owner = %(owner)s"` in its caller's, two facts a
    reader (and `tests/core/test_owner_scoping.py`'s S-21 literal-scoping audit, which pools one
    function's own literals on purpose) can only join by tracing a call, not by reading either
    function alone. The small duplication buys back that legibility."""
    # WP-33: `content_revision` rides each branch beside COLUMNS rather than inside it —
    # COLUMNS is `Goal`'s fields byte-for-byte (shared shape with `core/search.py`), and the
    # revision is evidence bookkeeping, not part of the card; only `effective_sql`'s CASE below
    # reads `cards.content_revision`, it is never projected out of the outer statement.
    branches = [
        f"  SELECT '{MAYBE_KEY}' AS col_key, 0 AS col_ord, {COLUMNS}, content_revision, short_label,\n"
        f"         false AS is_ghost, NULL::date AS ghost_until\n"
        f"    FROM goals\n"
        f"   WHERE owner = %(owner)s AND {MAYBE_PREDICATE}"
    ]
    bounded = tuple(h for h in vertical.VERTICALS if h.bounds_fn(_BOUNDS_PROBE) is not None)
    own_start = "CASE vertical " + " ".join(
        f"WHEN %(vt_{h.key})s::vertical_scale THEN %(current_start_{h.key})s::date"
        for h in bounded
    ) + " END"
    # The roll (docs/design-handoff S4.P1): a missed plan stays in its own scale until the next
    # larger period turns, then falls one scale up, and so on to the ladder's top. `roll_<own>_<k>`
    # is the oldest anchor that has not yet reached scale k (see `board()`); scales past the
    # ladder stay in their own column.
    ladder = _ladder()
    landing = "CASE " + " ".join(
        f"WHEN vertical = %(vt_{own.key})s::vertical_scale AND anchor_date >= %(roll_{own.key}_{ladder[k].key})s::date "
        f"THEN '{ladder[k - 1].key}'"
        for i, own in enumerate(ladder) for k in range(i + 1, len(ladder))
    ) + f" WHEN vertical IN ({', '.join(f'%(vt_{h.key})s::vertical_scale' for h in ladder)}) THEN '{ladder[-1].key}'" \
        + " ELSE vertical::text END"
    for col_ord, h in enumerate(vertical.VERTICALS, start=1):
        if vertical.loads_legacy_period_keys(h.key):
            # R2 keeps legacy `2020s`/`2030s` rows byte-untouched. Their anchor dates still
            # identify the correct fixed triennium, so this branch can load both legacy and new
            # period-key formats without a data migration.
            where = (
                f"owner = %(owner)s AND vertical = %(vt_{h.key})s::vertical_scale "
                f"AND anchor_date BETWEEN %(start_{h.key})s AND %(end_{h.key})s"
            )
        else:
            where = (
                f"owner = %(owner)s AND vertical = %(vt_{h.key})s::vertical_scale "
                f"AND period_key = %(pk_{h.key})s"
            )
        branches.append(
            f"  SELECT '{h.key}' AS col_key, {col_ord} AS col_ord, {COLUMNS}, content_revision, short_label,\n"
            f"         false AS is_ghost, NULL::date AS ghost_until\n"
            f"    FROM goals\n"
            f"   WHERE {where}"
        )
        # R10: carry-over is another row source inside this statement, never another read. Life
        # has no bounded period and therefore no earlier/current distinction to carry over.
        # Boundedness is a property of the scale, not of any particular date, so the probe date
        # is an arbitrary constant — wall-clock time must not influence the statement's shape.
        if h.bounds_fn(_BOUNDS_PROBE) is not None:
            branches.append(
                f"  SELECT '{h.key}' AS col_key, {col_ord} AS col_ord, {COLUMNS}, content_revision, short_label,\n"
                f"         true AS is_ghost, %(end_{h.key})s::date AS ghost_until\n"
                f"    FROM goals\n"
                # Only the landing column's live gate applies. Browsing an old Day must not
                # hide an aged Day goal whose landing Month is still the current Month.
                f"   WHERE %(live_{h.key})s\n"
                f"     AND owner = %(owner)s\n"
                f"     AND vertical IN ({', '.join(f'%(vt_{source.key})s::vertical_scale' for source in bounded[:bounded.index(h) + 1])})\n"
                f"     AND anchor_date < ({own_start}) AND done_at IS NULL\n"
                f"     AND ({landing}) = '{h.key}'\n"
                f"     AND (carryover_ignored_until IS NULL\n"
                # An expired short-period ignore must not become active again on promotion.
                f"          OR carryover_ignored_until < %(today)s::date)\n"
                # 011: an acknowledged dueness (either verdict) stops ghosting. Keyed to the
                # goal's own missed period, so a reschedule that misses AGAIN ghosts again.
                f"     AND NOT EXISTS (SELECT 1 FROM due_acknowledgements da\n"
                f"          WHERE da.owner = goals.owner AND da.goal_id = goals.id\n"
                f"            AND da.vertical = goals.vertical AND da.period_key = goals.period_key)"
            )
    cards_cte = "WITH cards AS (\n" + "\n  UNION ALL\n".join(branches) + "\n)"
    return (
        f"{cards_cte}\n"
        f"SELECT\n"
        f"  cards.col_key, cards.col_ord,\n"
        f"  {_QUALIFIED_COLUMNS},\n"
        f"  COALESCE(prog.done, 0) AS progress_done,\n"
        f"  COALESCE(prog.total, 0) AS progress_total,\n"
        f"  COALESCE(anc.ancestors, '[]'::jsonb) AS ancestors_json,\n"
        f"  COALESCE(kids.children, '[]'::jsonb) AS children_json,\n"
        # WP-33 (docs/EVIDENCE.md §6.1): the card's evidence summary rides the SAME statement —
        # S-22's execute-count delta of 1 is a contract, so the summary could not be a second
        # query. `ev` is a PK lookup per card; the CASE is `core/evidence.py`'s own formula,
        # rendered from the one shared function so the board can never disagree with
        # `evidence_due` about what "stale" means.
        f"  {effective_sql('cards', 'ev')} AS evidence_status,\n"
        f"  ev.verified_at AS evidence_verified_at,\n"
        f"  ev.review_after AS evidence_review_after,\n"
        f"  cards.is_ghost, cards.ghost_until,\n"
        # D231's one derived field (see the `root` lateral below): the value's colour, or NULL
        # for a tree that has no life-vertical root. `_to_goal`'s caller substitutes this for the
        # stored `color` — the stored field never reaches a board card.
        f"  CASE WHEN root.vertical = 'life' THEN root.color END AS value_color,\n"
        # D239: the value's one-word menu label (App.vue's nav row). Ridden beside COLUMNS like
        # `content_revision` rather than inside it — `Goal` mirrors the stored row §3 shape every
        # sibling module pins, and the label is menu bookkeeping, not part of the card.
        f"  cards.short_label AS short_label\n"
        f"FROM cards\n"
        f"LEFT JOIN goal_evidence ev ON ev.goal_id = cards.id AND ev.owner = cards.owner\n"
        f"LEFT JOIN LATERAL (\n"
        # `prog` used to read `starts_with(d.path, cards.path)` — correct as *rows selected* (a
        # pure byte-prefix test, exactly what `starts_with()` is), wrong as a *plan*. A LATERAL
        # correlates `cards.path` per outer row, so it is a `Var`, never a plan-time `Const`, and
        # Postgres's own starts_with()-to-index-range rewrite (`indxpath.c`'s
        # `match_special_index_operator`, the thing that turns a *literal* prefix into a
        # `goals_path` bound) only fires for a `Const`/bind-parameter pattern, never a correlated
        # column reference. Measured on a real F4-5670 clone at HEAD (eb3e048), verbatim:
        # `Seq Scan on goals d (actual ... loops=1460) Filter: (starts_with(path, goals.path)
        # AND ...) Rows Removed by Filter: 5669` — once per rendered card, cards x rows work,
        # 186880 of the statement's 191141 total buffer hits from this one lateral alone. Matches
        # S-92/S-93's measured 29x/68x-over-budget blowup exactly (`docs/E2E.md` S-92, S-93).
        #
        # Two rewrites that *look* like fixes and are not — checked against a live plan on the
        # same corpus, not assumed, 2026-08-09:
        #   * `d.path >= cards.path AND d.path < <successor>` with the *plain* `>=`/`<`: still
        #     `Seq Scan on goals d`, `goals_path` untouched. Plain `>=`/`<` on `text` bind to the
        #     default, collation-aware opclass — a different operator family from `goals_path`'s
        #     own `text_pattern_ops` (`001_init.sql:58`) — so the planner cannot route them there
        #     no matter how the bounds are computed.
        #   * `d.path LIKE (cards.path || '%')`: also `Seq Scan on goals d`, `Filter: (... path
        #     ~~ (goals.path || '%'))`. LIKE's prefix-to-range optimisation only fires for a
        #     *constant* pattern extracted once at plan time; `cards.path || '%'` is built from a
        #     correlated `Var`, unknown until each outer row runs, so that path never triggers.
        #
        # The fix: `~>=~`/`~<~` are `text_pattern_ops`'s own operators (confirmed live against
        # `pg_amop`/`pg_opclass` on this database, and independently: they are exactly what
        # Postgres's own rewrite of a *literal* `starts_with()` call produces, read straight off
        # its `EXPLAIN` output). Being ordinary indexable operators rather than a plan-time
        # rewrite, they work correlated to an outer LATERAL row same as `anc`'s `a.id = seg.aid`
        # and `kids`'s `ch.parent_id = cards.id` below already do. `OPERATOR(pg_catalog.~>=~)`
        # spells the operator out by schema rather than trusting the bare symbol — the same
        # paranoia `core/tree.py`'s own `_escape_like` already applies to this same `path` column.
        #
        # The upper bound: every `path` this codebase writes ends in exactly one '/'
        # (`core/tree.py`: `f"/{id}/"` at the root, `f"{parent_path}{id}/"` for a child — no
        # other terminator), so `left(cards.path, -1)` (Postgres's "-1 = drop the last character"
        # form) strips exactly that trailing '/' (0x2F), and appending '0' (0x30, the next byte)
        # reproduces — byte for byte — the successor Postgres's own planner computed for the
        # literal case above. `[cards.path, successor)` is therefore exactly the set of strings
        # with `cards.path` as a byte-prefix: a real descendant's path is `cards.path` plus more
        # characters, which sorts strictly between the two bounds regardless of what those
        # further characters are — matching `starts_with()`'s own semantics exactly, not
        # approximately. Proved, not just argued: `tests/core/test_board.py`'s
        # `test_prog_predicate_matches_starts_with_oracle_row_for_row_f4_5670` runs both
        # predicates over a real 5670-row corpus and asserts the whole board result is
        # identical, row for row. `test_prog_lateral_plan_uses_goals_path_not_seq_scan_f4_5670`,
        # right beside it, is the planted-and-reverted plan-shape regression test.
        #
        # That "every path ends in exactly one '/'" used to be true only because `core/tree.py`
        # happens to write it that way — a convention, not a guarantee. It is now `path_well_
        # formed` (`db/migrations/004_path_format.sql`), a CHECK on `goals.path` itself (`LIKE
        # '/%/' AND NOT LIKE '%//%'`), so the bound above is sound against any writer, not only
        # this codebase's own. Without it: a row whose path lost its trailing '/' would not error
        # here or anywhere: `left(path, -1)` would strip some other byte instead, and since every
        # base62 id-byte sorts >= '0' (IR-05's alphabet), the computed "successor" would sort at
        # or below `cards.path` itself — an empty or inverted range — and that one card's
        # `progress` would silently read 0/0 forever: no exception, no log line, just a wrong
        # number on the board. Proved the same way as the plan and the row-for-row match above,
        # not only argued: `test_path_well_formed_constraint_exists_and_blocks_the_shape_the_
        # bound_assumes_away` is the tripwire — `path_well_formed` present in the catalogue, and
        # a live UPDATE stripping a real row's trailing '/' refused by the database itself, not
        # by application code a bypass writer would not be running. `test_successor_bound_is_
        # sound_and_complete_under_the_constraint_f4_5670` computes both bounds over a real
        # parent/child pair from this same corpus and shows the excluded-descendant failure mode
        # above happening to a real id, not a hypothetical one.
        f"  SELECT count(*) FILTER (WHERE d.done_at IS NOT NULL) AS done, count(*) AS total\n"
        f"    FROM goals d\n"
        f"   WHERE d.owner = cards.owner\n"
        f"     AND d.path OPERATOR(pg_catalog.~>=~) cards.path\n"
        f"     AND d.path OPERATOR(pg_catalog.~<~) (left(cards.path, -1) || '0')\n"
        f"     AND d.id <> cards.id\n"
        f") prog ON true\n"
        f"LEFT JOIN LATERAL (\n"
        f"  SELECT jsonb_agg(\n"
        f"           jsonb_build_object('id', a.id, 'title', a.title, 'vertical', a.vertical)\n"
        f"           ORDER BY seg.ord\n"
        f"         ) AS ancestors\n"
        f"    FROM unnest(string_to_array(btrim(cards.path, '/'), '/')) WITH ORDINALITY"
        f" AS seg(aid, ord)\n"
        f"    JOIN goals a ON a.owner = cards.owner AND a.id = seg.aid\n"
        f"   WHERE seg.ord <= cards.depth\n"
        f") anc ON true\n"
        # `child_count` on each child row is `docs/PENDING_DOC_FIXES.md` rows 93/116(a): the
        # `children` map is keyed by `cards`-CTE rows only, so a card rendered one level down by
        # `GoalCard.vue`'s recursive template used to report `subgoalCount = 0` however many
        # children it really had (measured on F3: one nested card with 5, one with 1). The ruling
        # is that the payload moves, not AC-109 — a count that silently vanishes one level down
        # reads as authoritative and is worse than no count.
        #
        # It is one nested LATERAL over `goals_parent` (001_init.sql:57) per already-fetched child
        # row, inside the statement that was already running — never a per-node query from the
        # application, which is the thing IR-07/ARCHITECTURE.md:486 exists to forbid ("the whole
        # board in one call"; the incumbent's 30+ round trips). The board stays exactly one
        # `conn.execute` (S-22's execute-count delta of 1 is unchanged), and the added work is an
        # index lookup keyed by a real id, not the correlated seq-scan shape `prog` above had to
        # be rewritten out of.
        f"LEFT JOIN LATERAL (\n"
        # Each child's own evidence summary rides inside the child jsonb, same reasoning as the
        # card-level `ev` join above: the board draws children, so they need the summary too,
        # and it must not cost a second statement. `kev` is one more PK lookup per child row.
        f"  SELECT jsonb_agg(\n"
        f"           to_jsonb(ch) || jsonb_build_object('child_count', kc.n,\n"
        f"             'evidence', jsonb_build_object(\n"
        f"               'status', {effective_sql('ch', 'kev')},\n"
        f"               'verified_at', kev.verified_at,\n"
        f"               'review_after', kev.review_after))\n"
        f"           ORDER BY ch.position\n"
        f"         ) AS children\n"
        f"    FROM goals ch\n"
        f"    LEFT JOIN goal_evidence kev ON kev.goal_id = ch.id AND kev.owner = ch.owner\n"
        f"    LEFT JOIN LATERAL (\n"
        f"      SELECT count(*) AS n FROM goals gc\n"
        f"       WHERE gc.owner = ch.owner AND gc.parent_id = ch.id\n"
        f"    ) kc ON true\n"
        f"   WHERE ch.owner = cards.owner AND ch.parent_id = cards.id\n"
        f") kids ON true\n"
        # D231 (KK, 2026-08-15): colour is DERIVED — a card's colour is its life-vertical root's
        # ("value's") colour, never its own stored one. `root` is the first `path` segment, a PK
        # lookup per card (same cost class as `ev` above); for a root card it resolves to itself.
        # A tree rooted anywhere but the life vertical has no value and therefore no colour.
        f"LEFT JOIN LATERAL (\n"
        f"  SELECT r.color, r.vertical, r.position\n"
        f"    FROM goals r\n"
        f"   WHERE r.owner = cards.owner\n"
        f"     AND r.id = split_part(btrim(cards.path, '/'), '/', 1)\n"
        f") root ON true\n"
        # D233 (KK, 2026-08-15): the value filter narrows the board to one value's subtree.
        # 'maybe' and 'life' are exempt HERE on purpose: Inbox keeps its pile under any filter,
        # and the life rows feed `Board.values` and `short_labels` — the menu's list, which must
        # survive any filter. The life COLUMN itself narrows too since D240, but in `board()`
        # below, after the value list is captured off these very rows — filtering it away in SQL
        # would take the menu's own buttons with it.
        f"WHERE %(value)s::text IS NULL\n"
        f"   OR cards.col_key IN ('{MAYBE_KEY}', 'life')\n"
        f"   OR split_part(btrim(cards.path, '/'), '/', 1) = %(value)s\n"
        # D232 (KK, 2026-08-15): columns band by value — every column lists Financial's goals,
        # then Social's, ... in the life column's own order, with unvalued trees last (ASC is
        # NULLS LAST). `position` is the tiebreak within a band, exactly what it was globally.
        f"ORDER BY cards.col_ord,\n"
        f"  (CASE WHEN root.vertical = 'life' THEN root.position END),\n"
        f"  cards.position, cards.id"
    )


STATEMENT = _build_statement()


def _to_goal(values: tuple) -> Goal:
    values = list(values)
    values[_TAGS_INDEX] = tuple(values[_TAGS_INDEX])  # psycopg hands back a list; `Goal` is frozen
    values[24] = tuple(values[24]) if values[24] is not None else None
    values[25] = tuple(values[25]) if values[25] is not None else None
    return Goal(*values)


def _goal_from_jsonb(d: dict) -> Goal:
    """`to_jsonb(ch)`'s own output, one child row — JSON has no date/timestamp type, so
    Postgres rendered `anchor_date`/`done_at`/`created_at`/`updated_at` as ISO 8601 text on the
    way out; this is the one place that text is turned back into `date`/`datetime`."""
    return Goal(
        id=d["id"],
        owner=d["owner"],
        parent_id=d["parent_id"],
        path=d["path"],
        depth=d["depth"],
        vertical=d["vertical"],
        anchor_date=_date.fromisoformat(d["anchor_date"]) if d["anchor_date"] else None,
        period_key=d["period_key"],
        title=d["title"],
        body=d["body"],
        color=d["color"],
        tags=tuple(d["tags"]),
        done_at=_datetime.fromisoformat(d["done_at"]) if d["done_at"] else None,
        position=d["position"],
        origin=d["origin"],
        created_at=_datetime.fromisoformat(d["created_at"]),
        updated_at=_datetime.fromisoformat(d["updated_at"]),
        repeat_rule=d["repeat_rule"],
        repeat_series_id=d["repeat_series_id"],
        repeat_index=d["repeat_index"],
        repeat_start_date=_date.fromisoformat(d["repeat_start_date"])
        if d["repeat_start_date"] else None,
        parked_from_vertical=d["parked_from_vertical"],
        foil=d["foil"],
        carryover_ignored_until=_date.fromisoformat(d["carryover_ignored_until"])
        if d["carryover_ignored_until"] else None,
        size_expected=tuple(d["size_expected"]) if d["size_expected"] is not None else None,
        size_actual=tuple(d["size_actual"]) if d["size_actual"] is not None else None,
    )


def _column_for(key: str, anchor: _date, goals: tuple[Goal, ...]) -> Column:
    if key == MAYBE_KEY:  # not a scale — the inbox bucket AC-012 has nothing to say about
        return Column(vertical=None, period_key=None, label="Maybe", goals=goals)
    return Column(
        vertical=key,
        period_key=vertical.period_key(key, anchor),
        label=vertical.menu_label(key),
        goals=goals,
    )


def board(
    conn: psycopg.Connection, *, owner: str, date: _date, value: str | None = None,
    today: _date | None = None,
) -> Board:
    """The whole board, one statement (IR-07): eight columns, every card's `progress`,
    `ancestors` and direct `children`. `date` is the anchor "today" the board renders against —
    `board`'s own parameter, distinct from any single `Goal.anchor_date` (`docs/E2E.md` S-20 and
    S-22 both call it `date`, and so does the `GET /api/board?date=` query parameter — this
    follows all three rather than the field name on `Goal`).

    `today` is the wall-clock date the ghosts and the live columns read. Leave it out: the
    default is the server's own date. Tests pass it to stand on a calendar edge without a mock
    (S-109 bans mocks and monkeypatch).

    IR-02: takes an open connection, never commits, never opens a transaction of its own.
    """
    owner = _validate_owner(owner)
    date = _validate_date(date)
    if value is not None and (not isinstance(value, str) or not value):
        raise ValidationError("value must be a non-empty string or None", field="value")

    params: dict[str, object] = {
        "owner": owner,
        "as_of": _datetime.now(_timezone.utc),
        "value": value,
    }
    # R10 (revised, KK ruling 2026-08-16): the one wall-clock read in this module (and `today`, when
    # a caller passes one, replaces it). Ghost rows
    # exist only where the requested period IS the current period for that scale — comparing
    # period keys is exactly "does this scale's requested period contain today".
    today = _date.today() if today is None else _validate_date(today)
    params["today"] = today
    for h in vertical.VERTICALS:
        params[f"vt_{h.key}"] = h.key
        params[f"pk_{h.key}"] = h.period_key_fn(date)
        bounds = h.bounds_fn(date)
        if bounds is not None:
            params[f"start_{h.key}"], params[f"end_{h.key}"] = bounds
            params[f"live_{h.key}"] = params[f"pk_{h.key}"] == h.period_key_fn(today)
            params[f"current_start_{h.key}"] = h.bounds_fn(today)[0]
    params.update(_roll_thresholds(today))

    rows = conn.execute(STATEMENT, params).fetchall()

    by_column: dict[str, list[Goal]] = {key: [] for key in COLUMN_ORDER}
    progress: dict[str, Progress] = {}
    ancestors: dict[str, tuple[Ancestor, ...]] = {}
    children: dict[str, tuple[Goal, ...]] = {}
    child_counts: dict[str, int] = {}
    evidence: dict[str, dict] = {}
    ghosts: dict[str, _date] = {}
    short_labels: dict[str, str] = {}

    for row in rows:
        col_key = row[0]
        # D231: the stored colour never reaches a card — every level the board draws (cards here,
        # children below) carries the derived value colour this row's `root` lateral resolved.
        value_color = row[37]
        goal = _replace(_to_goal(row[2:28]), color=value_color)
        for c in row[31]:
            c["color"] = value_color
        by_column[col_key].append(goal)
        progress[goal.id] = Progress(done=row[28], total=row[29])
        ancestors[goal.id] = tuple(
            Ancestor(id=a["id"], title=a["title"], vertical=a["vertical"]) for a in row[30]
        )
        children[goal.id] = tuple(_goal_from_jsonb(c) for c in row[31])
        # Two levels, both off the same rows: the card's own count is the length of the list the
        # statement already returned, and each *child*'s count is the `child_count` the `kids`
        # lateral computed for it (rows 93/116(a)). A nested card is exactly one level below a
        # card, because `children` is keyed by cards and nothing deeper is ever rendered — so
        # these two levels are every node the board can draw, not a sample of them.
        child_counts[goal.id] = len(row[31])
        # The same two levels carry the evidence summary (WP-33): the card's three fields off
        # this row's own columns, each child's off the jsonb the `kids` lateral packed. The
        # child's timestamps are already ISO text (jsonb has no timestamp type); the card's are
        # real datetimes — normalised here so the map holds one shape.
        evidence[goal.id] = {
            "status": row[32],
            "verified_at": row[33].isoformat() if row[33] else None,
            "review_after": row[34].isoformat() if row[34] else None,
        }
        if row[35]:
            ghosts[goal.id] = row[36]
        # D239: keyed like its sibling maps, kept sparse — NULL (the overwhelming case: only
        # value roots ever carry one) never lands a key.
        if row[38] is not None:
            short_labels[goal.id] = row[38]
        for c in row[31]:
            child_counts[c["id"]] = c["child_count"]
            evidence[c["id"]] = c["evidence"]

    # D233: the filter's target must be a real value — a parentless life-vertical goal. The life
    # rows are exempt from the SQL filter (see `_build_statement`), so the full value list is in
    # hand either way; an id that is not on it gets a clean NotFound, not a silently empty board
    # an MCP caller would misread as "no goals". Zero extra queries — S-22's execute-count
    # contract (exactly one statement per board) holds.
    values = tuple(g for g in by_column["life"] if g.parent_id is None)
    if value is not None and not any(g.id == value for g in values):
        raise NotFound(f"no value {value!r} for owner {owner!r}", id=value, owner=owner)

    # D240 (KK, 2026-08-15): a selected value filters the life column too — the other values
    # leave the BOARD, while `values` above (and the labels already collected) keep feeding the
    # MENU. Same subtree predicate the SQL applies to every dated column: root path segment.
    if value is not None:
        by_column["life"] = [
            g for g in by_column["life"] if g.path.strip("/").split("/", 1)[0] == value
        ]

    columns = tuple(_column_for(key, date, tuple(by_column[key])) for key in COLUMN_ORDER)
    return Board(
        owner=owner,
        anchor_date=date,
        columns=columns,
        progress=progress,
        ancestors=ancestors,
        children=children,
        child_counts=child_counts,
        evidence=evidence,
        ghosts=ghosts,
        short_labels=short_labels,
        values=values,
    )
