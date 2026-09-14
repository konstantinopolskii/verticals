"""Reads `seed/planner-export.json` (F3, Zone 1, gitignored) and writes `artifacts/census.json`
— `docs/E2E.md` §2's F3 section. The **script** is in git; its **output** is not
(`artifacts/` is gitignored wholesale). `tests/pipeline/test_import.py` reads the written file
back rather than a literal — S-79's own rule, "the assertion compares against the census file,
never against a number typed into this document" — applied to every F3 scenario, not only S-79.

Two blocks, because the export and the import are two different populations (§2's own framing):
`census.raw` is measured over all 567 rows exactly as `seed/planner-export.json` holds them,
before any drop policy runs; `census.authored` is measured over the rows the **default** policy
(`calendar+onboarding`) keeps, with orphans re-rooted and legacy child verticals clamped.
`census.authored` calls
`tools.import_planner.plan_import` directly rather than re-deriving the same classify/drop/
re-root logic a second time — "re-rooted exactly as the importer does" (S-84's own words) is true
by construction that way, not by two implementations staying in sync by hand. `census.orphans` is
built the same way, once per named policy, so the three id sets S-80 checks for nesting
(`timed ⊆ calendar ⊆ calendar+onboarding`) come from three real `plan_import` calls, not from one
run's result sliced three ways by guesswork.

No name or description or body ever enters this file's output — every field below is an id, a
count, a timestamp or a class label. `census.raw.batches` groups by `(created_datetime, class)`
only; nothing here reads `row["name"]` or `row["description"]` at all.

Run standalone to regenerate `artifacts/census.json` by hand:
    .venv/bin/python -m tests.fixtures.census
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from datetime import date
from pathlib import Path

from verticals.core.vertical import VERTICALS
from tools.import_planner import DROP_POLICIES, classify_row, period_key, plan_import

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_EXPORT_PATH = REPO_ROOT / "seed" / "planner-export.json"
DEFAULT_OUTPUT_PATH = REPO_ROOT / "artifacts" / "census.json"
DEFAULT_POLICY = "calendar+onboarding"

# core/vertical.py's own declared order plus "none" — never hand-listed (same reasoning as
# core/board.py's COLUMN_ORDER), and load-bearing here: both `by_vertical` and `done_by_vertical`
# are seeded with every key up front so a vertical with zero rows still reads back as `0`, never
# a missing key a caller's plain `[...]` access would KeyError on.
_VERTICAL_KEYS: tuple[str, ...] = tuple(h.key for h in VERTICALS) + ("none",)


def _walk_graph(parent_of: dict[str, str | None]) -> tuple[dict[str, int], dict[str, int]]:
    """`(depth_by_id, fanout_by_id)` over `parent_of` — memoized recursion. A `parent_id`
    pointing outside `parent_of`'s own keys is treated as a root rather than raising: this module
    is diagnostic, not the gate — `tools.import_planner.validate_rows` is what actually refuses
    a dangling reference, and the real export has none (verified directly against the file)."""
    ids = set(parent_of)
    depth: dict[str, int] = {}

    def get_depth(cid: str, seen: frozenset[str]) -> int:
        if cid in depth:
            return depth[cid]
        if cid in seen:
            raise ValueError(f"parent_id cycle detected at {cid!r}")
        parent = parent_of.get(cid)
        d = 0 if parent is None or parent not in ids else get_depth(parent, seen | {cid}) + 1
        depth[cid] = d
        return d

    for cid in parent_of:
        get_depth(cid, frozenset())

    fanout: dict[str, int] = {}
    for cid, parent in parent_of.items():
        if parent is not None and parent in ids:
            fanout[parent] = fanout.get(parent, 0) + 1
    return depth, fanout


def _deepest_chain(parent_of: dict[str, str | None], depth_by_id: dict[str, int]) -> list[str]:
    """Root-to-leaf ids for one deepest node — ties broken by id, so the choice is deterministic
    across runs rather than dependent on dict iteration order."""
    deepest = max(sorted(depth_by_id), key=lambda k: depth_by_id[k])
    chain = []
    cur: str | None = deepest
    while cur is not None:
        chain.append(cur)
        cur = parent_of.get(cur)
    chain.reverse()
    return chain


def _raw_block(rows: list[dict]) -> dict:
    parent_of = {r["id"]: r.get("parent_id") for r in rows}
    depth_by_id, fanout_by_id = _walk_graph(parent_of)
    classes = {r["id"]: classify_row(r) for r in rows}

    period_pairs = {
        (r["vertical"], period_key(r["vertical"], date.fromisoformat(r["date"])))
        for r in rows
        if r.get("vertical") is not None
    }

    batch_sizes: Counter[tuple[str, str]] = Counter(
        (r["created_datetime"], classes[r["id"]]) for r in rows
    )
    batches = [
        {"created_datetime": ts, "class": cls, "size": size}
        for (ts, cls), size in sorted(batch_sizes.items())
    ]

    return {
        "count": len(rows),
        "depth_histogram": dict(sorted(Counter(depth_by_id.values()).items())),
        "max_depth": max(depth_by_id.values()),
        "max_fanout": max(fanout_by_id.values()) if fanout_by_id else 0,
        "parent_count": len(fanout_by_id),
        "distinct_period_pairs": len(period_pairs),
        "batches": batches,
    }


def _authored_block(rows: list[dict]) -> dict:
    kept, _dropped, _orphan_ids, clamped_ids = plan_import(rows, policy=DEFAULT_POLICY)
    parent_of = {k.id: k.parent_id for k in kept.values()}
    depth_by_id, fanout_by_id = _walk_graph(parent_of)

    by_vertical: Counter[str] = Counter({key: 0 for key in _VERTICAL_KEYS})
    done_by_vertical: Counter[str] = Counter({key: 0 for key in _VERTICAL_KEYS})
    by_vertical_date: dict[str, Counter[str]] = {}
    created_counts: Counter[str] = Counter()
    color_count = 0

    for k in kept.values():
        key = k.vertical or "none"
        by_vertical[key] += 1
        if k.done_at is not None:
            done_by_vertical[key] += 1
        if k.anchor_date is not None:
            by_vertical_date.setdefault(key, Counter())[k.anchor_date.isoformat()] += 1
        if k.color:
            color_count += 1
        created_counts[k.created_at.isoformat()] += 1

    return {
        "count": len(kept),
        "by_vertical": dict(by_vertical),
        "done_by_vertical": dict(done_by_vertical),
        "by_vertical_date": {h: dict(c) for h, c in by_vertical_date.items()},
        "depth_histogram": dict(sorted(Counter(depth_by_id.values()).items())),
        "max_depth": max(depth_by_id.values()),
        "max_fanout": max(fanout_by_id.values()) if fanout_by_id else 0,
        "parent_count": len(fanout_by_id),
        "max_batch_size": max(created_counts.values()),
        "distinct_created_at": len(created_counts),
        # docs/E2E.md §2 names no dedicated `root_id` field even though S-84's own text reads
        # `census.authored.root_id` — see docs/PENDING_DOC_FIXES.md. `deepest_chain[0]` is a
        # real, surviving, root-level id and proves the same "ids preserved verbatim" property
        # S-84 wants, so `test_import.py` reads it from here rather than a field this shape does
        # not declare.
        "deepest_chain": _deepest_chain(parent_of, depth_by_id),
        "color_count": color_count,
        "clamped_to_parent": len(clamped_ids),
    }


def _orphans_block(rows: list[dict]) -> dict:
    classes = {r["id"]: classify_row(r) for r in rows}
    raw_parent_of = {r["id"]: r.get("parent_id") for r in rows}

    result: dict[str, dict] = {}
    for policy in DROP_POLICIES:
        _kept, _dropped, orphan_ids, _clamped_ids = plan_import(rows, policy=policy)
        ordered = sorted(orphan_ids)
        orphan_rows = [
            {
                "goal_id": oid,
                "parent_id": raw_parent_of[oid],
                "parent_class": classes.get(raw_parent_of[oid]),
            }
            for oid in ordered
        ]
        result[policy] = {"count": len(ordered), "ids": ordered, "rows": orphan_rows}
    return result


def build_census(export_path: Path = DEFAULT_EXPORT_PATH) -> dict:
    """The whole `census.json` shape (`docs/E2E.md` §2), computed once from `export_path`. Pure —
    no file written. `write_census` below is the version a fixture or a human calls."""
    rows = json.loads(export_path.read_text())
    if not isinstance(rows, list):
        raise ValueError(f"{export_path}: expected a JSON array of goal rows")
    return {
        "raw": _raw_block(rows),
        "authored": _authored_block(rows),
        "orphans": _orphans_block(rows),
    }


def write_census(
    export_path: Path = DEFAULT_EXPORT_PATH, output_path: Path = DEFAULT_OUTPUT_PATH
) -> dict:
    """`build_census`, then written to `output_path` (parents created as needed) — always
    overwritten, never merged with a stale prior run, so a run against a changed export can never
    be shadowed by yesterday's numbers."""
    census = build_census(export_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(census, indent=2, sort_keys=True) + "\n")
    return census


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(prog="python -m tests.fixtures.census")
    parser.add_argument("--input", type=Path, default=DEFAULT_EXPORT_PATH)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH)
    args = parser.parse_args(argv)

    if not args.input.exists():
        print(f"{args.input}: absent (F3 not present on this machine)", file=sys.stderr)
        return 2
    census = write_census(args.input, args.output)
    print(f"wrote {args.output} (raw={census['raw']['count']}, authored={census['authored']['count']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
