"""Import KK's real reference-planner export into `goals` — WP-16 (`docs/IMPLEMENTATION.md`).

    python tools/import_planner.py --input seed/planner-export.json --owner kk \
        [--drop timed|calendar|calendar+onboarding]

Reads `VERTICALS_DATABASE_URL` from the environment, the same contract `verticals/db/runner.py`
uses (`docs/IMPLEMENTATION.md` §6.3) — this tool invents no other variable and assumes the
target database is already migrated to head.

`ARCHITECTURE.md` §7's field map, verbatim:

    their field                            ours                    note
    id                                     id                      preserved verbatim
    parent_id                              parent_id               path/depth derived (core/tree.py)
    vertical, date                          vertical, anchor_date    period_key computed, never copied
    name, description                      title, body
    color                                  color                   CHECK passes it through as-is
    checked                                done_at                 true -> created_datetime, else NULL
    created_datetime                       created_at              copied, parsed as UTC (§10-D7),
                                                                    never `now()`
    --                                     origin                  'import'
    --                                     owner                   from --owner
    space_id, bucket_id, assignee_id,
    start_time, end_time, url              (dropped — no column)

Four row classes (`ARCHITECTURE.md` §0/§7; `docs/E2E.md` C1/C2/C5):

    calendar_timed    the 2024-12-16T17:29:22+03:00 Google Calendar sync batch, `start_time` set
                      (140 rows on the 2026-08-08 export). Published in `ARCHITECTURE.md` §0 as
                      an aggregate fact, not personal content — safe to pin below as a literal.
    calendar_allday   same batch, `start_time` absent — all-day holiday rows (107 rows). The
                      naive `start_time IS NOT NULL` rule alone misses these entirely; the batch
                      timestamp, not `start_time`, is the real drop key for both calendar classes.
    onboarding        the demo cards the reference planner seeds a fresh account with (12 rows). Identified
                      by `bucket_id IS NOT NULL` — `ARCHITECTURE.md` §0's own field-usage table
                      ("`bucket_id` (Boards) | 2% | and those 12 are onboarding demo cards") —
                      rather than a second magic timestamp: the onboarding batch's own
                      `created_datetime` is not published anywhere in the docs, so it stays out
                      of this file. Grouping by the field the architecture doc already names
                      keeps every literal here either already public (the one timestamp below) or
                      derived at runtime from the gitignored export.
    authored          everything else — the 308 rows this tool exists to import.

Three named drop policies (`docs/E2E.md` §10-D5, S-80): `timed` drops `calendar_timed` alone;
`calendar` adds `calendar_allday`; `calendar+onboarding` (the default, D5) adds `onboarding` too.
A kept row whose original parent fell in the active drop set is re-rooted — `parent_id := NULL`,
`vertical`/`anchor_date`/`period_key`/`title` untouched, counted as `reparented_orphans` (C5) —
never dropped, never left dangling.

One transaction, insert-only, idempotent on id. `core/tree.py#attach` derives `path`/`depth` and
returns `None` on an id collision instead of raising (`ON CONFLICT (id) DO NOTHING`) — a second
run against a database already holding a row touches it zero times, by construction, which is
what makes `updated` always `0` here rather than a comparison this module has to compute. A row
is inserted only once its own parent already exists as a row, walked via memoized recursion over
`parent_id` rather than file order (S-85: input order does not matter). `attach` has no
`created_at`/`done_at` parameter — frozen, WP-08's alone to change — so both are backfilled by one
bulk `UPDATE ... FROM (VALUES ...)` immediately after, over exactly the rows this run itself
inserted, matching `core/tree.py#renumber`'s own bulk-update idiom. `position` is precomputed for
the whole kept set before any statement runs (grouped exactly as `core/tree.py`'s own sibling-
group rule) and handed to `attach` explicitly — never left for `attach`'s own tail-append
`renumber` call, which would mean each row's position depends on read-then-write over a group
that is still growing mid-import.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import date, datetime, timezone
from pathlib import Path

import psycopg

from verticals.core import tree
from verticals.core.errors import VerticalError
from verticals.core.vertical import VERTICALS, SCALE_KEYS, period_key, rank

# ARCHITECTURE.md §0/§7: "the Google Calendar sync wrote 247 rows in a single second —
# created_datetime is byte-identical 2024-12-16T17:29:22+03:00 on all of them." Published there
# as an aggregate fact, not personal content — unlike the onboarding batch's own timestamp (see
# module docstring), which stays out of every file in this repository.
CALENDAR_BATCH_CREATED_AT = "2024-12-16T17:29:22+03:00"

CLASS_CALENDAR_TIMED = "calendar_timed"
CLASS_CALENDAR_ALLDAY = "calendar_allday"
CLASS_ONBOARDING = "onboarding"
CLASS_AUTHORED = "authored"

# Nested by construction (docs/E2E.md §2: "timed ⊆ calendar ⊆ calendar+onboarding" — S-80 asserts
# this rather than assuming it).
DROP_POLICIES: dict[str, frozenset[str]] = {
    "timed": frozenset({CLASS_CALENDAR_TIMED}),
    "calendar": frozenset({CLASS_CALENDAR_TIMED, CLASS_CALENDAR_ALLDAY}),
    "calendar+onboarding": frozenset(
        {CLASS_CALENDAR_TIMED, CLASS_CALENDAR_ALLDAY, CLASS_ONBOARDING}
    ),
}
DEFAULT_POLICY = "calendar+onboarding"  # docs/E2E.md §10-D5

# ARCHITECTURE.md §7 / core/tree.py's own POSITION_GAP — same constant, duplicated rather than
# imported: this module never calls core/tree.py#renumber (positions are precomputed offline),
# so there is no shared call site to hang a single import off of, and the value is public.
POSITION_GAP = 1024


class BadInput(Exception):
    """The export file itself is malformed — refused before any statement runs. `str(exc)`
    names the file and, for every case where one exists, the row index and the field
    (`docs/E2E.md` S-86)."""


def classify_row(row: dict) -> str:
    """One of the four classes above. `bucket_id` over a second batch timestamp — see the
    module docstring for why."""
    if row.get("created_datetime") == CALENDAR_BATCH_CREATED_AT:
        return CLASS_CALENDAR_TIMED if row.get("start_time") is not None else CLASS_CALENDAR_ALLDAY
    if row.get("bucket_id") is not None:
        return CLASS_ONBOARDING
    return CLASS_AUTHORED


def _parse_datetime_utc(value: str) -> datetime:
    """`created_datetime` is always offset-aware in the export (verified: every row carries a
    25-character ISO string with a numeric UTC offset). §10-D7: stored as the same instant,
    normalised to UTC for a stable, predictable representation — not left in the source's own
    offset, and never `now()`."""
    return datetime.fromisoformat(value).astimezone(timezone.utc)


# --- loading and validation ----------------------------------------------------------------


def load_rows(path: Path) -> list[dict]:
    """Parse `path` as a JSON array of goal rows. Raises `BadInput` naming the file for every
    way the file itself can be wrong (S-86 a/b) — never a raw `json.JSONDecodeError` or
    `TypeError` reaching `main`."""
    try:
        text = path.read_text()
    except OSError as exc:
        raise BadInput(f"{path}: cannot read: {exc}") from None
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise BadInput(f"{path}: not valid JSON: {exc}") from None
    if not isinstance(data, list):
        raise BadInput(f"{path}: expected a JSON array of goal rows, got {type(data).__name__}")
    return data


def validate_rows(path: Path, rows: list[dict], *, known_ids: frozenset[str]) -> None:
    """Per-row shape (S-86 c/d) plus the dangling-`parent_id` check (S-86 e), against the union
    of every id in this file and `known_ids` (rows a prior run already committed — a re-run
    against a database that does not hold this file's own parents a second time). Raises
    `BadInput` naming the file, the row index (0-based, this file's own array position) and the
    field on the first violation — refused loudly, not corrected, not partially applied.
    """
    file_ids = {row["id"] for row in rows if isinstance(row, dict) and isinstance(row.get("id"), str) and row.get("id")}
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise BadInput(f"{path}: row {index}: expected an object, got {type(row).__name__}")
        row_id = row.get("id")
        if not isinstance(row_id, str) or not row_id:
            raise BadInput(f"{path}: row {index}: id: required, must be a non-empty string")
        vertical = row.get("vertical")
        if vertical is not None and vertical not in SCALE_KEYS:
            raise BadInput(
                f"{path}: row {index}: vertical: {vertical!r} is not one of {sorted(SCALE_KEYS)}"
            )
        if vertical is not None and not row.get("date"):
            raise BadInput(f"{path}: row {index}: date: required when vertical is set")
        if not isinstance(row.get("created_datetime"), str) or not row["created_datetime"]:
            raise BadInput(f"{path}: row {index}: created_datetime: required, must be a string")
        parent_id = row.get("parent_id")
        if parent_id is not None and parent_id not in file_ids and parent_id not in known_ids:
            raise BadInput(
                f"{path}: row {index}: parent_id: {parent_id!r} is not in this file and was "
                f"not previously imported"
            )


# --- classify, drop, re-root --------------------------------------------------------------


@dataclass(frozen=True)
class _Kept:
    id: str
    parent_id: str | None  # already resolved: None for a re-rooted orphan, unchanged otherwise
    title: str
    body: str
    vertical: str | None
    anchor_date: date | None
    period_key: str | None
    color: str | None
    created_at: datetime
    done_at: datetime | None


def plan_import(
    rows: list[dict],
    *,
    policy: str,
    existing_verticals: Mapping[str, str | None] | None = None,
    existing_anchor_dates: Mapping[str, date | None] | None = None,
) -> tuple[dict[str, _Kept], dict[str, int], list[str], list[str]]:
    """Classify every row, apply `policy`'s drop set, re-root any kept row whose original parent
    was dropped, then clamp a legacy child above its parent to the parent's final placement. Returns
    `(kept_by_id, dropped_counts, orphan_ids, clamped_ids)` — `kept_by_id` values already carry
    the resolved parent and placement, so nothing downstream re-derives either reconciliation.
    `tests/fixtures/census.py` calls this directly (not a reimplementation) so `census.authored`
    is re-rooted "exactly as the importer does" by construction, not by two copies of the same
    logic staying in sync by hand.
    """
    drop_set = DROP_POLICIES[policy]
    dropped_counts = {c: 0 for c in (CLASS_CALENDAR_TIMED, CLASS_CALENDAR_ALLDAY, CLASS_ONBOARDING)}
    classes = {row["id"]: classify_row(row) for row in rows}

    kept_by_id: dict[str, _Kept] = {}
    orphan_ids: list[str] = []
    for row in rows:
        row_id = row["id"]
        cls = classes[row_id]
        if cls in drop_set:
            dropped_counts[cls] += 1
            continue
        parent_id = row.get("parent_id")
        if parent_id is not None and classes.get(parent_id) in drop_set:
            orphan_ids.append(row_id)
            parent_id = None
        vertical = row.get("vertical")
        anchor_date = date.fromisoformat(row["date"]) if row.get("date") else None
        pk = period_key(vertical, anchor_date) if vertical is not None else None
        created_at = _parse_datetime_utc(row["created_datetime"])
        kept_by_id[row_id] = _Kept(
            id=row_id,
            parent_id=parent_id,
            title=row.get("name") or "",
            body=row.get("description") or "",
            vertical=vertical,
            anchor_date=anchor_date,
            period_key=pk,
            color=row.get("color"),
            created_at=created_at,
            done_at=created_at if row.get("checked") else None,
        )
    # v1 exports allowed a child to sit above its parent. Interactive writes still refuse that
    # shape in core/placement.py; import alone reconciles legacy rows by snapping the child to the
    # parent's final vertical and anchor. Every class/drop/re-root decision above is already final;
    # only survivors reach this pass. Resolve parent-first so a chain of violations uses the
    # already-clamped parent, independent of input order.
    existing_verticals = existing_verticals or {}
    existing_anchor_dates = existing_anchor_dates or {}
    clamped_ids: list[str] = []
    reconciled: set[str] = set()
    visiting: set[str] = set()

    def reconcile(row_id: str) -> None:
        if row_id in reconciled:
            return
        if row_id in visiting:
            raise BadInput(f"parent_id cycle detected at {row_id!r}")
        visiting.add(row_id)
        child = kept_by_id[row_id]
        parent_vertical: str | None
        parent_anchor_date: date | None
        if child.parent_id in kept_by_id:
            reconcile(child.parent_id)
            parent = kept_by_id[child.parent_id]
            parent_vertical = parent.vertical
            parent_anchor_date = parent.anchor_date
        elif child.parent_id is not None and child.parent_id in existing_verticals:
            parent_vertical = existing_verticals[child.parent_id]
            parent_anchor_date = existing_anchor_dates.get(child.parent_id, child.anchor_date)
        else:
            parent_vertical = None
            parent_anchor_date = None

        if child.parent_id is not None and child.vertical is not None and (
            parent_vertical is None or rank(child.vertical) > rank(parent_vertical)
        ):
            kept_by_id[row_id] = replace(
                child,
                vertical=parent_vertical,
                anchor_date=parent_anchor_date,
                period_key=(
                    period_key(parent_vertical, parent_anchor_date)
                    if parent_vertical is not None
                    else None
                ),
            )
            clamped_ids.append(row_id)
        visiting.remove(row_id)
        reconciled.add(row_id)

    for row_id in kept_by_id:
        reconcile(row_id)
    return kept_by_id, dropped_counts, orphan_ids, clamped_ids


def compute_positions(kept: dict[str, _Kept]) -> dict[str, int]:
    """`position` for every kept row, grouped exactly as `core/tree.py`'s own sibling-group rule
    (module docstring there): `(vertical, period_key)` when vertical is set — a board column,
    regardless of parent — or `(None, parent_id)` when it is not. Within a group, ascending
    `created_at`, tie-broken by `id` (`core/tree.py#renumber`'s own tie-break for the same reason:
    `position` alone is not total). Computed once, offline, over the whole kept set, and handed
    to `core/tree.py#attach` explicitly — D11: no read-then-write position allocation, because
    nothing here calls `attach` with `position=None` and therefore nothing calls `renumber` at
    all. There is no concurrent writer during an import; nothing here needs `renumber`'s locking,
    only its arithmetic.
    """
    groups: dict[tuple[str | None, str | None], list[_Kept]] = {}
    for k in kept.values():
        key = (k.vertical, k.period_key) if k.vertical is not None else (None, k.parent_id)
        groups.setdefault(key, []).append(k)
    positions: dict[str, int] = {}
    for members in groups.values():
        members.sort(key=lambda k: (k.created_at, k.id))
        for rank, k in enumerate(members):
            positions[k.id] = (rank + 1) * POSITION_GAP
    return positions


def insert_kept_rows(
    conn: psycopg.Connection, *, owner: str, kept: dict[str, _Kept], positions: dict[str, int]
) -> tuple[list[str], int]:
    """Insert every kept row via `core/tree.py#attach`, a row's own parent always inserted first
    regardless of file order (S-85) — memoized recursion over `parent_id`, not a pre-sort, so the
    guarantee holds for any order the caller iterates `kept` in. Returns `(inserted_ids,
    unchanged)`; `attach`'s own `ON CONFLICT (id) DO NOTHING` is what makes a second run touch
    zero existing rows (S-83) — `unchanged` counts exactly those.
    """
    inserted: list[str] = []
    unchanged = 0
    done: set[str] = set()
    visiting: set[str] = set()

    def ensure(row_id: str) -> None:
        nonlocal unchanged
        if row_id in done:
            return
        if row_id in visiting:
            raise BadInput(f"parent_id cycle detected at {row_id!r}")
        visiting.add(row_id)
        k = kept[row_id]
        if k.parent_id is not None and k.parent_id in kept:
            ensure(k.parent_id)
        goal = tree.attach(
            conn,
            owner=owner,
            id=k.id,
            parent_id=k.parent_id,
            title=k.title,
            body=k.body,
            vertical=k.vertical,
            anchor_date=k.anchor_date,
            period_key=k.period_key,
            color=k.color,
            origin="import",
            position=positions[k.id],
        )
        if goal is not None:
            inserted.append(row_id)
        else:
            unchanged += 1
        visiting.discard(row_id)
        done.add(row_id)

    for row_id in kept:
        ensure(row_id)
    return inserted, unchanged


def backfill_timestamps(
    conn: psycopg.Connection, *, owner: str, kept: dict[str, _Kept], inserted_ids: list[str]
) -> None:
    """`core/tree.py#attach` has no `created_at`/`done_at` parameter — frozen, WP-08's alone to
    change. One bulk `UPDATE ... FROM (VALUES ...)` backfills both, over exactly the rows this
    run inserted — never a row `attach` skipped on conflict, which already carries whatever an
    earlier run wrote and must stay untouched (S-83: "created_at unchanged on every row"). Same
    idiom `core/tree.py#renumber`'s own bulk reassignment already uses.
    """
    if not inserted_ids:
        return
    placeholders = ", ".join(["(%s, %s::timestamptz, %s::timestamptz)"] * len(inserted_ids))
    params: list[object] = []
    for row_id in inserted_ids:
        k = kept[row_id]
        params.extend([row_id, k.created_at, k.done_at])
    conn.execute(
        f"""
        UPDATE goals AS g
           SET created_at = v.created_at, done_at = v.done_at
          FROM (VALUES {placeholders}) AS v(id, created_at, done_at)
         WHERE g.owner = %s AND g.id = v.id
        """,
        [*params, owner],
    )


# --- reconciliation --------------------------------------------------------------------------

# core/vertical.py's own declared order (day..life), plus "none" for vertical-less rows — never
# hand-listed, matching board.py's own COLUMN_ORDER convention for the same reason.
_VERTICAL_ORDER: tuple[str, ...] = tuple(h.key for h in VERTICALS) + ("none",)


@dataclass(frozen=True)
class Reconciliation:
    read: int
    dropped: dict[str, int]
    reparented_orphans: int
    clamped_to_parent: int
    imported: int
    inserted: int
    updated: int
    unchanged: int
    by_vertical: dict[str, int]

    def render(self) -> str:
        """S-79's exact row set, in order — every row is a count, nothing here is a title, a
        body or any other string the export supplied, so the redaction pass this suite runs over
        it (docs/E2E.md's suite-E teardown rule) always finds zero strings to strip."""
        lines = [
            f"read {self.read}",
            f"dropped:{CLASS_CALENDAR_TIMED} {self.dropped.get(CLASS_CALENDAR_TIMED, 0)}",
            f"dropped:{CLASS_CALENDAR_ALLDAY} {self.dropped.get(CLASS_CALENDAR_ALLDAY, 0)}",
            f"dropped:{CLASS_ONBOARDING} {self.dropped.get(CLASS_ONBOARDING, 0)}",
            f"reparented_orphans {self.reparented_orphans}",
            f"clamped_to_parent {self.clamped_to_parent}",
            f"imported {self.imported}",
            f"inserted {self.inserted}",
            f"updated {self.updated}",
            f"unchanged {self.unchanged}",
        ]
        for key in _VERTICAL_ORDER:
            lines.append(f"by_vertical:{key} {self.by_vertical.get(key, 0)}")
        return "\n".join(lines)


def run_import(
    conn: psycopg.Connection, *, owner: str, path: Path, rows: list[dict], policy: str
) -> Reconciliation:
    existing_rows = conn.execute(
        "SELECT id, vertical, anchor_date FROM goals WHERE owner = %s", (owner,)
    ).fetchall()
    existing_verticals = {row_id: vertical for row_id, vertical, _anchor in existing_rows}
    existing_anchor_dates = {row_id: anchor for row_id, _vertical, anchor in existing_rows}
    existing = frozenset(existing_verticals)
    validate_rows(path, rows, known_ids=existing)
    kept, dropped_counts, orphan_ids, clamped_ids = plan_import(
        rows,
        policy=policy,
        existing_verticals=existing_verticals,
        existing_anchor_dates=existing_anchor_dates,
    )
    positions = compute_positions(kept)
    inserted_ids, unchanged = insert_kept_rows(conn, owner=owner, kept=kept, positions=positions)
    backfill_timestamps(conn, owner=owner, kept=kept, inserted_ids=inserted_ids)

    by_vertical: dict[str, int] = {}
    for k in kept.values():
        key = k.vertical or "none"
        by_vertical[key] = by_vertical.get(key, 0) + 1

    return Reconciliation(
        read=len(rows),
        dropped=dropped_counts,
        reparented_orphans=len(orphan_ids),
        clamped_to_parent=len(clamped_ids),
        imported=len(kept),
        inserted=len(inserted_ids),
        updated=0,  # attach's ON CONFLICT DO NOTHING means an existing row is never rewritten
        unchanged=unchanged,
        by_vertical=by_vertical,
    )


# --- CLI ---------------------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python tools/import_planner.py")
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--owner", required=True)
    parser.add_argument("--drop", choices=sorted(DROP_POLICIES), default=DEFAULT_POLICY)
    args = parser.parse_args(argv)

    dsn = os.environ.get("VERTICALS_DATABASE_URL")
    if not dsn:
        print("VERTICALS_DATABASE_URL is not set", file=sys.stderr)
        return 2

    try:
        rows = load_rows(args.input)
    except BadInput as exc:
        print(str(exc), file=sys.stderr)
        return 2

    try:
        # autocommit=True, matching verticals/db/runner.py#_connect: the explicit
        # `with conn.transaction():` below is what actually opens the one top-level transaction
        # this whole invocation runs inside — every `attach()` call's own `with
        # conn.transaction():` then joins it as a SAVEPOINT (core/tree.py's own module
        # docstring), never a second top-level commit.
        conn = psycopg.connect(dsn, autocommit=True)
    except psycopg.OperationalError as exc:
        print(f"cannot connect to database: {exc}", file=sys.stderr)
        return 2

    try:
        with conn.transaction():
            result = run_import(conn, owner=args.owner, path=args.input, rows=rows, policy=args.drop)
    except BadInput as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except VerticalError as exc:
        print(f"import refused: {exc}", file=sys.stderr)
        return 2
    except psycopg.Error as exc:
        print(f"import failed, nothing committed: {exc}", file=sys.stderr)
        return 2
    finally:
        conn.close()

    print(result.render())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
