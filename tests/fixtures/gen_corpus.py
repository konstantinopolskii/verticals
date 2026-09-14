"""F4 — the shape-matched synthetic corpus generator. WP-20 (`docs/IMPLEMENTATION.md`).

`docs/E2E.md` section 2 "F4 — shape-matched synthetic corpora" / section 0's C7 correction;
`docs/IMPLEMENTATION.md` WP-20 card. Consumes `tests/fixtures/shape.json` — numbers copied by
hand from `ARCHITECTURE.md` section 0 and corrected by `docs/E2E.md` section 0 — and emits N rows
of synthetic tree at a fixed RNG seed. `shape.json` mirrors `census.raw` (the RAW 567-row export),
so this is a stand-in for the export, not for the import.

**Zone 1 law** (`wealthy/CLAUDE.md`; this repo's own `docs/BRIEF.md` rule 9): this file must never
open `seed/`. Every statistic it consumes was already published in a committed document before
this file existed — nothing here is derived from the real export at generation time.

Two output shapes, one internal tree (`_build_tree`), so both shapes always agree on structure:

  * `generate_rows()` — full `goals`-table rows (id/path/depth/position precomputed), for bulk
    loading a template database directly. `tests/perf/conftest.py`'s corpus fixtures call this.
  * `generate_export_rows()` — `tools/import_planner.py`'s own expected export-JSON field
    names, every row `CLASS_AUTHORED` (no calendar-batch timestamp, no `bucket_id`), so a
    default-policy import keeps all N rows with zero drops. S-98 calls this.

Determinism: everything below flows from one `random.Random(seed)`, seeded once at the top of
`_build_tree` and threaded explicitly — no module-level RNG, no `random.seed()` global mutation,
so two calls in the same process with different seeds never cross-contaminate.

Counts the source documents state as exact raw-567 figures (depth histogram, the dense column,
body presence, the creation-burst histogram) are scaled by exact integer multiplication — every
canonical N this suite uses (567, 5670, 56700) is an integer multiple of 567, so this scaling is
exact, never rounded. Counts the source states as a *rate* (the per-vertical mix, per-vertical
completion, color presence) are applied as independent per-row probabilities instead, which is
the honest treatment of a rate and does not pretend to reproduce an exact bucket size.

CLI: `python -m tests.fixtures.gen_corpus --n 5670 --seed 20260808` (`docs/E2E.md` section 2's
own citation of this exact command).
"""

from __future__ import annotations

import argparse
import json
import random
import string
import sys
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from verticals.core.vertical import VERTICALS, period_key

SHAPE_PATH = Path(__file__).resolve().parent / "shape.json"
DEFAULT_SEED = 20260808
DEFAULT_OWNER = "perf"
POSITION_GAP = 1024  # verticals/core/tree.py's own constant, duplicated for the reason that
# module's own docstring gives for tools/import_planner.py doing the same: no shared call site
# to hang one import off, and the value is public (ARCHITECTURE.md section 3).

_ID_ALPHABET = string.ascii_letters + string.digits  # base62, matching core/goals.py's own shape

# Lorem word bank — generic, invented, nothing derived from any real person's data. Checked to
# contain no substring "cycl" so the S-94 plant (see `_plant_search_matches`) is exactly 40
# matches, never 41+ from an accidental hit here.
_WORDS = (
    "plan review draft outline sketch align align check verify confirm ship land close open "
    "start finish revisit reschedule notes summary followup prep brief scope budget timeline "
    "roadmap backlog triage cleanup audit sync standup retro handoff draft memo agenda minutes "
    "goal target milestone checkpoint baseline metric report dashboard board column card task "
    "errand call email doc slide deck demo pitch proposal contract invoice renewal onboarding "
    "training workshop session interview feedback survey research spike prototype mockup build "
    "deploy release rollback monitor alert incident postmortem backup migrate archive"
).split()
assert not any("cycl" in w for w in _WORDS), "word bank must never contain the S-94 plant needle"

_VERTICAL_KEYS = tuple(h.key for h in VERTICALS)  # day..life, core/vertical.py's declared order

# The forced dense column's own coordinates (`_force_dense_column` below) — public so a caller
# (`tests/perf/test_perf_core_queries.py`'s S-92/AC-190 check) can query `core.board(date=DENSE_COLUMN_DATE)`
# and know in advance which rendered column will be the deliberately dense one, rather than
# scanning all eight guessing which is densest.
DENSE_COLUMN_VERTICAL = "month"
DENSE_COLUMN_DATE = date(2026, 3, 15)


def load_shape(path: Path = SHAPE_PATH) -> dict:
    return json.loads(path.read_text())


# --- internal tree node -------------------------------------------------------------------------


@dataclass
class _Node:
    id: str
    parent_id: str | None
    depth: int
    vertical: str | None = None
    anchor_date: date | None = None
    period_key: str | None = None
    title: str = ""
    body: str = ""
    color: str | None = None
    done_at: datetime | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    position: int = POSITION_GAP
    path: str = ""


def _new_id(rng: random.Random, taken: set[str]) -> str:
    while True:
        candidate = "".join(rng.choices(_ID_ALPHABET, k=8))
        if candidate not in taken:
            taken.add(candidate)
            return candidate


def _level_counts(shape: dict, n: int) -> list[int]:
    """Rows per tree depth, scaled from `shape["depth_histogram"]`'s raw-567 counts. Exact for
    every N this suite actually uses (all multiples of 567); the rounding-remainder correction on
    the root bucket only matters for an off-catalogue `--n` a developer passes by hand."""
    hist = shape["depth_histogram"]
    raw_total = shape["source_raw_n"]
    depths = sorted(int(k) for k in hist if k.isdigit())
    scaled = [round(hist[str(d)] * n / raw_total) for d in depths]
    scaled[0] += n - sum(scaled)
    return scaled


def _build_skeleton(rng: random.Random, shape: dict, n: int) -> list[_Node]:
    """Ids, `parent_id`, `depth` only — every other field is filled in by later passes. Built
    level by level (root first) so a child's parent always already exists, matching
    `core/tree.py`'s own depth rule (`new_depth = parent_depth + 1`, never assigned any other
    way). Fanout is capped at `shape["fanout"]["max"]` (a hard rule — IR-11's bound the schema
    itself enforces) via random assignment among not-yet-full parents; it is not tuned to hit the
    documented mean/median exactly, which the module docstring already states as a deliberate
    simplification not asserted by any scenario this package owns."""
    taken: set[str] = set()
    counts = _level_counts(shape, n)
    max_fanout = shape["fanout"]["max"]

    nodes: list[_Node] = []
    levels: list[list[_Node]] = []
    for depth, count in enumerate(counts):
        level: list[_Node] = []
        if depth == 0:
            for _ in range(count):
                level.append(_Node(id=_new_id(rng, taken), parent_id=None, depth=0))
        else:
            parents = levels[depth - 1]
            fanout_left = {p.id: max_fanout for p in parents}
            for _ in range(count):
                candidates = [pid for pid, left in fanout_left.items() if left > 0]
                if not candidates:  # exhausted every parent's cap — should not happen at these
                    candidates = [p.id for p in parents]  # N/depth ratios, kept as a safety valve
                parent_id = rng.choice(candidates)
                fanout_left[parent_id] = fanout_left.get(parent_id, 1) - 1
                level.append(_Node(id=_new_id(rng, taken), parent_id=parent_id, depth=depth))
        levels.append(level)
        nodes.extend(level)
    return nodes


# --- content passes -------------------------------------------------------------------------


def _lorem_title(rng: random.Random) -> str:
    """Median ~25 chars, ~4 words (`shape.json["title"]`) — 3..5 words drawn from `_WORDS`,
    capitalised as a title, never a newline (`shape.json`'s own `multiline: false`)."""
    n_words = rng.choice((3, 3, 4, 4, 4, 5))
    words = [rng.choice(_WORDS) for _ in range(n_words)]
    words[0] = words[0].capitalize()
    return " ".join(words)


def _lorem_body(rng: random.Random) -> str:
    """Median ~218 chars (`shape.json["body"]["median_chars"]`) — 2..5 short sentences, comfortably
    under the observed 3453-char maximum and nowhere near `core/goals.py`'s 64 KB bound."""
    n_sentences = rng.choice((1, 2, 2, 3, 3, 4))
    sentences = []
    for _ in range(n_sentences):
        n_words = rng.randint(6, 14)
        words = [rng.choice(_WORDS) for _ in range(n_words)]
        words[0] = words[0].capitalize()
        sentences.append(" ".join(words) + ".")
    return " ".join(sentences)


def _weighted_choice(rng: random.Random, weights: dict[str, float]) -> str:
    keys = list(weights)
    return rng.choices(keys, weights=[weights[k] for k in keys], k=1)[0]


_BURST_MONTHS = {  # "YYYY-MM" -> (year, month); shape.json's created_at_burst keys, parsed once
    key: (int(key[:4]), int(key[5:7])) for key in ("2024-11", "2024-12", "2025-01", "2025-02")
}


def _burst_created_at(rng: random.Random, shape: dict, n: int) -> list[datetime]:
    """One `created_at` per row, drawn from `shape["created_at_burst"]`'s four-month histogram,
    scaled exactly (every canonical N is a multiple of 567). 2024-12-16 is excluded from that
    month's day pool — see `shape.json`'s own comment — so no result can literally equal
    `tools/import_planner.py`'s `CALENDAR_BATCH_CREATED_AT` sentinel."""
    raw_total = shape["source_raw_n"]
    burst = shape["created_at_burst"]
    out: list[datetime] = []
    for key, raw_count in burst.items():
        year, month = _BURST_MONTHS[key]
        count = round(raw_count * n / raw_total)
        days_in_month = (date(year + (month == 12), month % 12 + 1, 1) - timedelta(days=1)).day
        valid_days = [d for d in range(1, days_in_month + 1) if not (year, month, d) == (2024, 12, 16)]
        for _ in range(count):
            d = rng.choice(valid_days)
            hh, mm, ss = rng.randint(0, 23), rng.randint(0, 59), rng.randint(0, 59)
            out.append(datetime(year, month, d, hh, mm, ss, tzinfo=timezone.utc))
    # Exact-multiple Ns give len(out) == n already; the remainder guard only fires for an
    # off-catalogue --n, padding or trimming against the same distribution's last bucket.
    while len(out) < n:
        out.append(out[-1] if out else datetime(2024, 12, 1, tzinfo=timezone.utc))
    return out[:n]


def _assign_content(rng: random.Random, shape: dict, nodes: list[_Node]) -> None:
    n = len(nodes)
    vertical_weights = shape["vertical_weight_source"]
    completion = shape["completion_by_vertical"]
    color_pct = shape["field_usage_pct_raw"]["color"] / 100.0
    body_count = round(shape["body"]["present_count_raw"] * n / shape["source_raw_n"])
    body_indices = set(rng.sample(range(n), min(body_count, n)))
    created_ats = _burst_created_at(rng, shape, n)

    for i, node in enumerate(nodes):
        node.created_at = created_ats[i]
        node.title = _lorem_title(rng)
        if i in body_indices:
            node.body = _lorem_body(rng)

        choice = _weighted_choice(rng, vertical_weights)
        if choice != "none":
            node.vertical = choice
            node.anchor_date = _random_anchor_date(rng, node.created_at.date())
            node.period_key = period_key(choice, node.anchor_date)
            if rng.random() < completion.get(choice, 0.0):
                delta_days = rng.randint(0, 400)
                node.done_at = node.created_at + timedelta(days=delta_days)
        # vertical is None: a Maybe-pile candidate when also root (checked structurally by
        # goals_inbox's own predicate — parent_id IS NULL AND done_at IS NULL), or a plain
        # vertical-less subgoal otherwise. Left `done_at = None` either way (module docstring).

        if rng.random() < color_pct:
            node.color = rng.choice(shape["canon_colors"])


def _random_anchor_date(rng: random.Random, created: date) -> date:
    """A wide spread — roughly two and a half years back to a year forward from the export's own
    published date (`ARCHITECTURE.md` section 0: 'exported ... on 2026-08-08', already a public
    aggregate fact, not Zone 1 content) — so the seven vertical scales' period keys naturally
    produce well over `shape.json`'s documented 183 distinct pairs at N=567 rather than clustering
    near `created`, which real reference-planner rows do not do either (goals are dated far from when
    they were authored — the whole point of a vertical board)."""
    reference = date(2026, 8, 8)
    start = reference - timedelta(days=900)
    end = reference + timedelta(days=400)
    span = (end - start).days
    return start + timedelta(days=rng.randint(0, span))


def _force_dense_column(rng: random.Random, shape: dict, nodes: list[_Node]) -> None:
    """AC-190 (ridden by S-92): the densest `(vertical, period_key)` pair in the real export holds
    14 rows, ~140 at F4-5670 (`docs/E2E.md` section 4's limits table). Without a deliberately dense
    column, "no cap, no truncation" is a vacuous assertion — every column would be small enough
    that any reasonable implementation passes by accident. Forces exactly
    `round(14 * N / source_raw_n)` depth-0 nodes into one shared, fixed `(month, period)` column;
    depth-0 so the tree's fanout/depth shape from `_build_skeleton` is untouched."""
    n = len(nodes)
    target = round(shape["densest_column_raw"]["count"] * n / shape["source_raw_n"])
    roots = [node for node in nodes if node.depth == 0]
    chosen = roots[:target] if len(roots) >= target else roots
    dense_key = period_key(DENSE_COLUMN_VERTICAL, DENSE_COLUMN_DATE)
    for node in chosen:
        node.vertical = DENSE_COLUMN_VERTICAL
        node.anchor_date = DENSE_COLUMN_DATE
        node.period_key = dense_key
        # Done-state redrawn against month's own completion rate, not left at whatever the
        # node's prior (possibly different-vertical) roll produced.
        node.done_at = None
        if rng.random() < shape["completion_by_vertical"].get(DENSE_COLUMN_VERTICAL, 0.0):
            node.done_at = node.created_at + timedelta(days=rng.randint(0, 400))


def _plant_search_matches(rng: random.Random, shape: dict, nodes: list[_Node]) -> None:
    """S-94 / AC-094: exactly 40 rows whose `title || ' ' || body` contains the needle `cycl`
    (`core/search.py`'s `TRIGRAM_PREDICATE` is a plain substring `ILIKE`, so any word containing
    the substring matches — L7's whole point: `cycl` must find `bicycles`). Fixed count, not
    scaled — S-94 only ever runs at F4-5670, and both source documents state the literal number
    40. Titled distinctly (`"Recycle the "` prefix) rather than appended to body, so the match is
    findable by a human skimming a manual run's output too."""
    count = shape["search_plant"]["planted_count"]
    needle_word = "recycle"  # contains "cycl"; see module-level word-bank assertion
    assert needle_word.count(shape["search_plant"]["needle"]) >= 1
    chosen = rng.sample(nodes, min(count, len(nodes)))
    for node in chosen:
        node.title = f"Recycle the {node.title[0].lower()}{node.title[1:]}"


# --- position + path, last (need final parent/vertical assignment) --------------------------------


def _assign_positions(nodes: list[_Node]) -> None:
    """One `position` per row, grouped exactly as `core/tree.py`'s own sibling-group rule
    (`(vertical, period_key)` when vertical is set, `(None, parent_id)` otherwise) — the same rule
    `tools/import_planner.py#compute_positions` already applies, reimplemented here rather than
    imported (that function is private to a sibling work package's module, not a shared library
    call). Within a group, ascending `created_at` then `id`, matching that same precedent."""
    groups: dict[tuple, list[_Node]] = {}
    for node in nodes:
        key = (node.vertical, node.period_key) if node.vertical is not None else (None, node.parent_id)
        groups.setdefault(key, []).append(node)
    for members in groups.values():
        members.sort(key=lambda nd: (nd.created_at, nd.id))
        for rank, node in enumerate(members):
            node.position = (rank + 1) * POSITION_GAP


def _assign_paths(nodes: list[_Node]) -> None:
    """`path = '/id1/.../idN/'`, `core/tree.py#attach`'s own convention. Nodes are already in
    parent-before-child order (`_build_skeleton` appends level by level), so one forward pass with
    a dict of already-computed paths suffices — no recursion needed."""
    path_by_id: dict[str, str] = {}
    for node in nodes:
        if node.parent_id is None:
            node.path = f"/{node.id}/"
        else:
            node.path = f"{path_by_id[node.parent_id]}{node.id}/"
        path_by_id[node.id] = node.path


def _build_tree(n: int, seed: int, shape: dict) -> list[_Node]:
    rng = random.Random(seed)
    nodes = _build_skeleton(rng, shape, n)
    _assign_content(rng, shape, nodes)
    _force_dense_column(rng, shape, nodes)
    _plant_search_matches(rng, shape, nodes)
    _assign_positions(nodes)
    _assign_paths(nodes)
    return nodes


# --- public API: two serializations of the same tree ----------------------------------------


def generate_rows(n: int, seed: int = DEFAULT_SEED, *, owner: str = DEFAULT_OWNER,
                   shape: dict | None = None) -> list[dict]:
    """Full `goals`-table rows, column names matching `verticals/db/migrations/001_init.sql`
    exactly, ready for a bulk `COPY`/`executemany` insert into a migrated, empty database."""
    shape = shape or load_shape()
    nodes = _build_tree(n, seed, shape)
    return [
        {
            "id": nd.id, "owner": owner, "parent_id": nd.parent_id, "path": nd.path,
            "depth": nd.depth, "vertical": nd.vertical, "anchor_date": nd.anchor_date,
            "period_key": nd.period_key, "title": nd.title, "body": nd.body, "color": nd.color,
            "tags": [], "done_at": nd.done_at, "position": nd.position, "origin": "human",
            "created_at": nd.created_at, "updated_at": nd.created_at,
            "parked_from_vertical": "life" if nd.vertical is None else None,
        }
        for nd in nodes
    ]


def generate_export_rows(n: int, seed: int = DEFAULT_SEED, *, shape: dict | None = None) -> list[dict]:
    """`tools/import_planner.py`'s expected export-JSON row shape (`ARCHITECTURE.md` section 7's
    field map). No `bucket_id`, no `start_time`, and `created_datetime` never equals
    `CALENDAR_BATCH_CREATED_AT` (`_burst_created_at`'s own guarantee) — every row therefore
    classifies `CLASS_AUTHORED` and a default-policy import keeps all N rows, zero drops, which is
    what S-98 needs to time a clean end-to-end import."""
    shape = shape or load_shape()
    nodes = _build_tree(n, seed, shape)
    return [
        {
            "id": nd.id,
            "parent_id": nd.parent_id,
            "vertical": nd.vertical,
            "date": nd.anchor_date.isoformat() if nd.anchor_date else None,
            "name": nd.title,
            "description": nd.body,
            "color": nd.color,
            "checked": nd.done_at is not None,
            "created_datetime": nd.created_at.isoformat(),
        }
        for nd in nodes
    ]


# --- CLI ---------------------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m tests.fixtures.gen_corpus")
    parser.add_argument("--n", required=True, type=int, help="row count, e.g. 567 / 5670 / 56700")
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--owner", default=DEFAULT_OWNER)
    parser.add_argument("--format", choices=("goals", "export"), default="goals")
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args(argv)

    if args.format == "goals":
        rows = generate_rows(args.n, args.seed, owner=args.owner)
    else:
        rows = generate_export_rows(args.n, args.seed)

    out = args.out
    if out is None:
        out_dir = Path(__file__).resolve().parent / "gen_corpus_output"
        out_dir.mkdir(exist_ok=True)
        out = out_dir / f"{args.format}-{args.n}-{args.seed}.json"
    out.write_text(json.dumps(rows, default=str, indent=None))
    print(f"wrote {len(rows)} {args.format} rows to {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
