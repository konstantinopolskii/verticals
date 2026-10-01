"""S-22 through S-25 — `core/board.py` against real Postgres 16 and the real F2 fixture. No
mocks, no stubs, no fakes (`docs/BRIEF.md` rule 2): every assertion below runs against a freshly
migrated clone with `tests/fixtures/f2_synth.sql` loaded.

**Statement counting: `tests/harness/stmt.py`, direct — matching `tests/core/test_tree.py`
(WP-08), not inventing a second mechanism.** `docs/E2E.md` §1 names the general-case mechanism
as an application-level per-connection execute counter feeding `X-Query-Count` ("product code...
exact per call... safe under parallel workers"). `core/` has no HTTP request to carry that
header, and nothing under `verticals/` builds the counter yet, for any module — `docs/
PENDING_DOC_FIXES.md` #12 already tracks this exact three-way tension (IR-06 says every
statement-count assertion goes through `stmt.py`; §1 and `stmt.py`'s own docstring both scope
`pg_stat_statements` to exactly S-25 and S-27) and records `stmt.py` direct, against `core/`, as
what WP-08 already shipped for precisely this reason ("`core/`-only package with no HTTP request
... `stmt.py` direct is the only mechanism available there"). `board()` is the same shape, so
S-22's "exactly 1 statement executed" is read the same way here.

Measured, not assumed: this cluster's `pg_stat_statements` sits at capacity under concurrent
multi-agent load (4923/5000 entries, 221 evictions already, observed live while this file was
being written) — a bare reset-then-read with any extra round trip in between lost the captured
row outright. A tight reset -> one call -> read, with nothing else on the connection in between
(`test_tree.py`'s own shape), came back correct across five repeated trials. The assertions below
keep to that shape rather than adding a retry loop the shipped precedent does not have.

**The EXPLAIN half needs no capture-and-rehydrate.** `tests/core/test_search.py`'s own
`_explain_forced` goes through `PREPARE`/`EXECUTE`/`ClientCursor` because it explains a statement
captured from `pg_stat_statements` — normalized, `$n`-renumbered, needing rehydration before it
is executable again. Nothing here is captured: `board.STATEMENT` and `board.MAYBE_PREDICATE` are
this module's own named-parameter (or parameter-free) source, already in hand, so `EXPLAIN`ing
either is a direct, ordinary `conn.execute` call.

**S-25's two claims, on two corpora, per `ACCEPTANCE.md` AC-043 — and the F2 half is asserted in
the form that is true, not the form that reads well.** Measured directly: under the whole
statement, `owner = %(owner)s` in every branch's predicate makes `goals_column`'s `(owner,
vertical)` leading columns dominate `goals_inbox` even with `enable_seqscan` forced off — the same
sibling-index phenomenon `core/search.py`'s own S-26 plan docstring already names for
`goals_path` beating `goals_search`. The *selection* claim ("the plan actually lands on
`goals_inbox`") is F4-5670's alone (`test_s25b`, GATE today); F2's own half is the narrower
"not structurally broken" claim S-25's text itself draws: no `Seq Scan` on the whole statement,
and the partial index's own predicate, explained in isolation and owner-free, still has a usable
path onto `goals_inbox`. Verified live (`board.STATEMENT` and `board.MAYBE_PREDICATE`, this
database, this run) before being written down here.

Run standalone:
    PGHOST=127.0.0.1 PGPORT=55432 PGUSER=verticals PGPASSWORD=verticals \
        .venv/bin/python -m pytest tests/core/test_board.py -v -s
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import psycopg
import pytest

from verticals.core import board as B
from verticals.core import goals
from verticals.core import vertical
from verticals.models import Board, Column, Goal
from tests.core.test_ghosts import _rolled
from tests.conftest import fresh_clone, maintenance_dsn
from tests.harness import stmt
from tests.harness.report import gate

F2_SQL = Path(__file__).resolve().parents[1] / "fixtures" / "f2_synth.sql"
# Owned by `docs/IMPLEMENTATION.md`'s WP-20 card, "Perf suite + corpus generator". `test_search.py`
# used to cite WP-06 for the same file; that was stale and has been corrected there, so both gate
# messages now name the same package and the verdict block collapses them into one reason.
GEN_CORPUS = Path(__file__).resolve().parents[1] / "fixtures" / "gen_corpus.py"

ANCHOR = date(2026, 8, 8)

# Fixed stored-period membership; runtime carryover projections are asserted separately.
CENSUS = {
    "maybe": 5, "day": 10, "week": 4, "month": 6,
    "quarter": 2, "year": 1, "decade": 0, "life": 1,
}


@pytest.fixture
def f2(db: psycopg.Connection) -> Iterator[psycopg.Connection]:
    """F2 on a fresh clone — the same idiom `tests/core/test_search.py` and
    `tests/core/test_tree.py` both already use. `ANALYZE` so the plan assertions below read real
    statistics rather than the planner's default guesses; a plan asserted against absent stats
    proves nothing."""
    db.execute(F2_SQL.read_text())
    db.execute("ANALYZE goals")
    yield db


def _dsn(dbname: str) -> str:
    """Same PGHOST/PGPORT/PGUSER/PGPASSWORD convention `tests/conftest.py`'s own (private)
    `_env_dsn` uses — reimplemented here rather than imported across files, matching this
    module's own `F2_SQL`/`GEN_CORPUS` precedent of a small constant duplicated per file rather
    than shared through a new cross-suite import."""
    host = os.environ.get("PGHOST", "127.0.0.1")
    port = os.environ.get("PGPORT", "55432")
    user = os.environ.get("PGUSER", "verticals")
    password = os.environ.get("PGPASSWORD", "verticals")
    return f"postgresql://{user}:{password}@{host}:{port}/{dbname}"


_GOALS_COLUMNS = (
    "id", "owner", "parent_id", "path", "depth", "vertical", "anchor_date", "period_key",
    "title", "body", "color", "tags", "done_at", "position", "origin", "created_at", "updated_at",
    "parked_from_vertical",
)


@pytest.fixture(scope="module")
def f4_5670() -> Iterator[psycopg.Connection]:
    """A real F4-5670 clone (`tests/fixtures/gen_corpus.py`, WP-20), built once for the whole
    file — the corpus itself is not under test here, only the plan it produces, so every
    F4-5670-scale assertion in this module shares one build. `owner="t1"` matches this file's
    own synthetic-owner convention (`_board_params("t1", ...)`, `B.board(f2, owner="t1", ...)`)
    rather than `tests/perf/`'s `"perf"` owner, so a plan assertion here binds the same owner
    value the real call does. `ANALYZE` for the same reason `f2` runs it: a plan asserted
    against absent statistics proves nothing.

    Verified live (this database, this run, 2026-08-09) before being written down: at 5670 rows
    with `owner="t1"`, the Maybe-pile predicate matches 1149 rows and the full `board.STATEMENT`
    plans `Bitmap Index Scan` on `goals_inbox` with zero `Seq Scan` on `goals`, `enable_seqscan`
    forced off — the exact claim `test_s25b` below asserts."""
    from tests.fixtures import gen_corpus as G

    with fresh_clone("f0") as name:
        target = _dsn(name)
        rows = G.generate_rows(5670, G.DEFAULT_SEED, owner="t1")
        conn = psycopg.connect(target, autocommit=True)
        try:
            with conn.cursor() as cur, cur.copy(
                f"COPY goals ({', '.join(_GOALS_COLUMNS)}) FROM STDIN"
            ) as copy:
                for row in rows:
                    copy.write_row(tuple(row[c] for c in _GOALS_COLUMNS))
            conn.execute("ANALYZE goals")
            yield conn
        finally:
            conn.close()


# --- shared helpers -----------------------------------------------------------------------------


def _dbname(conn: psycopg.Connection) -> str:
    return stmt.current_dbname(conn)


def _require_stmt_counter(dsn: str) -> None:
    """IR-06 / `tests/harness/stmt.py`'s own contract, matching `test_tree.py`'s helper of the
    same name and purpose: a statement-count or plan-text assertion that finds the extension
    unavailable reports GATE, never a silent pass or a hard failure unrelated to the thing being
    tested."""
    if not stmt.available(dsn):
        gate("pg_stat_statements unavailable — statement-count assertion cannot run")


def _column(b: Board, key: str) -> Column:
    """`key` is `"maybe"` or one of `core/vertical.py`'s seven scale keys — `board()`'s own
    `by_column` dict is seeded from `COLUMN_ORDER` before any row is read, so all eight keys
    always exist and this lookup cannot raise for a key this file actually passes."""
    return next(c for c in b.columns if (c.vertical or B.MAYBE_KEY) == key)


def _flat_rows(b: Board) -> list[Goal]:
    """The union of every card (`columns`) and every child (`children`), deduplicated by id —
    S-23's own "flat row set". The response hands the two back separately on purpose (`columns`
    is cards only, `children` is direct children only; nothing downstream needs card-vs-child
    blurred), so this is how a test recovers S-22/S-23's deduplicated row count
    claim both name. `SYNQ2R01` is both a `quarter` card and `SYNQ1R01`'s child — present once
    here, which is the property S-23 asserts."""
    seen: dict[str, Goal] = {}
    for column in b.columns:
        for g in column.goals:
            seen[g.id] = g
    for kids in b.children.values():
        for g in kids:
            seen.setdefault(g.id, g)
    return list(seen.values())


def _plan_nodes(plan: dict, acc: list[tuple] | None = None) -> list[tuple]:
    acc = [] if acc is None else acc
    acc.append((plan.get("Node Type"), plan.get("Index Name"), plan.get("Relation Name")))
    for child in plan.get("Plans", []):
        _plan_nodes(child, acc)
    return acc


def _explain_forced(
    conn: psycopg.Connection, text: str, params: dict[str, object] | None = None
) -> list[tuple]:
    """`SET LOCAL enable_seqscan = off` + `EXPLAIN (FORMAT JSON)` of `text`, bound the ordinary
    psycopg way — see the module docstring for why this needs none of
    `test_search.py`'s own `_explain_forced`'s `PREPARE`/`EXECUTE`/`ClientCursor` machinery."""
    with conn.transaction():
        conn.execute("SET LOCAL enable_seqscan = off")
        row = conn.execute(f"EXPLAIN (FORMAT JSON) {text}", params or {}).fetchone()
        return _plan_nodes(row[0][0]["Plan"])


def _board_params(owner: str, anchor: date) -> dict[str, object]:
    """`board()`'s own parameter set, rebuilt here rather than imported: `board()` builds it
    inline and does not expose the step as a function, and a plan assertion needs the exact
    values the real call would bind, not a test-invented stand-in."""
    # `value` joined the set with D233 (the board's server-side value filter); the plan tests
    # bind its unfiltered shape, NULL, same as every real `board()` call without a filter.
    params: dict[str, object] = {"owner": owner, "as_of": datetime.now(timezone.utc), "value": None}
    # R10 revised: `live_*` mirrors board()'s own per-call gate — "requested period == today's
    # period" per scale — so the plans explained here bind exactly what a real call binds.
    today = date.today()
    params["today"] = today
    for h in vertical.VERTICALS:
        params[f"vt_{h.key}"] = h.key
        params[f"pk_{h.key}"] = h.period_key_fn(anchor)
        bounds = h.bounds_fn(anchor)
        if bounds is not None:
            params[f"start_{h.key}"], params[f"end_{h.key}"] = bounds
            params[f"live_{h.key}"] = params[f"pk_{h.key}"] == h.period_key_fn(today)
            params[f"current_start_{h.key}"] = h.bounds_fn(today)[0]
    params.update(B._roll_thresholds(today))
    return params


# --- S-22 — the whole board in exactly one statement ---------------------------------------------


def test_s22_whole_board_in_exactly_one_statement(f2: psycopg.Connection) -> None:
    """`docs/E2E.md` S-22, steps 1-3 literally: reset the counter, make the one `board()` call,
    read it back. `RESEARCH.md` §3's incumbent is "30+ round trips" for this screen — this is
    `IR-07`'s entire reason to exist."""
    dsn = maintenance_dsn()
    _require_stmt_counter(dsn)
    dbname = _dbname(f2)

    stmt.reset(dsn, dbname)
    b = B.board(f2, owner="t1", date=ANCHOR)
    log = stmt.read(dsn, dbname)
    total = sum(calls for _, calls in log)

    print("S-22 captured statement log:")
    for text, calls in log:
        print(f"    calls={calls}  {text.splitlines()[0][:100]!r}")

    assert total == 1, log

    assert [c.vertical or B.MAYBE_KEY for c in b.columns] == list(B.COLUMN_ORDER)
    # Age-based carryover can add live Quarter/Year/3-year projections even while the frozen
    # Day/Week are historical. Keep this fixture census about stored membership; runtime
    # projection membership and both transport decorations are covered by test_ghosts.py.
    normal = {
        c.vertical or B.MAYBE_KEY: [g for g in c.goals if (
            c.vertical is None or (g.vertical == c.vertical and g.period_key == c.period_key)
        )]
        for c in b.columns
    }
    assert {key: len(cards) for key, cards in normal.items()} == CENSUS
    normal_ids = {g.id for cards in normal.values() for g in cards}
    normal_flat_ids = normal_ids | {g.id for gid in normal_ids for g in b.children[gid]}
    # The legacy decade row remains a direct child of Life even when not itself a card.
    assert len(normal_flat_ids) == 33

    card_ids = {g.id for c in b.columns for g in c.goals}
    assert len(normal_ids) == 29
    assert card_ids == normal_ids | set(b.ghosts)
    assert set(b.progress) == card_ids, "every card, and only cards, carries progress"
    assert set(b.ancestors) == card_ids, "every card, and only cards, carries ancestors"
    assert set(b.children) == card_ids, "every card, and only cards, carries children"
    for gid in card_ids:
        p = b.progress[gid]
        assert 0 <= p.done <= p.total


# --- S-23 — board children are included, no N+1 ---------------------------------------------------


def test_s23_children_included_no_n_plus_1(f2: psycopg.Connection) -> None:
    """S-23's own three checks: `SYNDAY01`'s three children, `SYNQ1R01`'s one, and `SYNQ2R01`
    counted once in the flat row set despite appearing twice in the response tree (once as a
    `quarter` card, once as `SYNQ1R01`'s child) — proof the dedup is real, not merely that the
    numbers happen to match."""
    b = B.board(f2, owner="t1", date=ANCHOR)

    assert [g.id for g in b.children["SYNDAY01"]] == ["SYNSUB01", "SYNSUB02", "SYNSUB03"]
    assert [g.id for g in b.children["SYNQ1R01"]] == ["SYNQ2R01"]

    quarter_ids = {g.id for g in _column(b, "quarter").goals}
    assert "SYNQ2R01" in quarter_ids  # once as a card ...
    assert "SYNQ2R01" in {g.id for g in b.children["SYNQ1R01"]}  # ... and once as a child

    rows = _flat_rows(b)
    source_ids = {
        g.id for c in b.columns for g in c.goals
        if c.vertical is None or (g.vertical == c.vertical and g.period_key == c.period_key)
    }
    source_flat_ids = source_ids | {g.id for gid in source_ids for g in b.children[gid]}
    assert len(source_ids) == 29
    assert len(source_flat_ids) == 33
    expected_ids = source_flat_ids | set(b.ghosts) | {
        g.id for gid in b.ghosts for g in b.children[gid]
    }
    assert len(rows) == len({r.id for r in rows})
    assert {r.id for r in rows} == expected_ids


def test_r7_children_keep_verticals_and_lower_child_has_own_column(
    db: psycopg.Connection,
) -> None:
    owner = "SYN-r7-owner"
    parent = goals.create(
        db, owner=owner, title="SYN month parent", vertical="month", anchor_date=ANCHOR
    ).goal
    same = goals.create(
        db, owner=owner, title="SYN same child", parent_id=parent.id,
        vertical="month", anchor_date=ANCHOR,
    ).goal
    lower = goals.create(
        db, owner=owner, title="SYN lower child", parent_id=parent.id,
        vertical="week", anchor_date=ANCHOR,
    ).goal
    parked = goals.create(
        db, owner=owner, title="SYN parked child", parent_id=parent.id,
    ).goal

    result = B.board(db, owner=owner, date=ANCHOR)
    children = {child.id: child for child in result.children[parent.id]}

    assert children[same.id].vertical == "month"
    assert children[lower.id].vertical == "week"
    assert children[parked.id].vertical is None
    assert lower.id in {goal.id for goal in _column(result, "week").goals}
    assert parked.id not in {goal.id for column in result.columns for goal in column.goals}


# --- S-24 — exclusive buckets -----------------------------------------------------------------


def test_s24_exclusive_buckets(f2: psycopg.Connection) -> None:
    """Stored membership is exclusive; a historical source may also have one live landing."""
    b = B.board(f2, owner="t1", date=ANCHOR)
    sources: dict[str, list[Goal]] = {}
    landings: dict[str, list[tuple[Column, Goal]]] = {}
    for column in b.columns:
        key = column.vertical or B.MAYBE_KEY
        sources[key] = []
        for goal in column.goals:
            if column.vertical is None or (
                goal.vertical == column.vertical and goal.period_key == column.period_key
            ):
                sources[key].append(goal)
            else:
                landings.setdefault(goal.id, []).append((column, goal))

    assert {key: len(cards) for key, cards in sources.items()} == CENSUS
    source_ids = [g.id for cards in sources.values() for g in cards]
    assert len(source_ids) == len(set(source_ids)) == 29
    assert set(landings) == set(b.ghosts)
    today = date.today()
    bounded = [h for h in vertical.VERTICALS if h.bounds_fn(today) is not None]
    keys = [h.key for h in bounded]
    for gid, copies in landings.items():
        assert len(copies) == 1, f"{gid} must have exactly one carryover landing"
        column, goal = copies[0]
        own = bounded[keys.index(goal.vertical)]
        assert goal.done_at is None
        assert goal.anchor_date < own.bounds_fn(today)[0]
        expected = vertical.descriptor(_rolled(goal.vertical, goal.anchor_date, today))
        assert column.vertical == expected.key
        assert column.period_key == expected.period_key_fn(today)
        assert b.ghosts[gid] == expected.bounds_fn(today)[1]
        all_copies = [g for c in b.columns for g in c.goals if g.id == gid]
        assert len(all_copies) == 1 + int(gid in source_ids)

    assert "SYNDAY01" not in {g.id for g in sources["week"]}
    assert [key for key, cards in sources.items() if any(
        g.id == "SYNQ2R01" for g in cards
    )] == ["quarter"]


# --- S-25 — the Maybe pile is exactly the partial index -----------------------------------------


def test_s25a_maybe_pile_and_f2_plan_usability(f2: psycopg.Connection) -> None:
    """Content, plus `ACCEPTANCE.md` AC-043's F2 half — see the module docstring for why the F2
    plan claim is the narrower "not structurally broken" one, and what was measured to weaken
    it from "the plan lands on `goals_inbox`" (false at 49 rows, verified) to this."""
    dsn = maintenance_dsn()
    _require_stmt_counter(dsn)

    b = B.board(f2, owner="t1", date=ANCHOR)
    maybe_ids = [g.id for g in _column(b, "maybe").goals]
    assert maybe_ids == ["SYNMAY01", "SYNMAY02", "SYNMAY03", "SYNMAY04", "SYNMAY05"]
    assert "SYNMAY06" not in maybe_ids, "SYNMAY06 is done and must not appear in Maybe"

    subs = {"SYNSUB01", "SYNSUB02", "SYNSUB03"}
    all_card_ids = {g.id for c in b.columns for g in c.goals}
    assert not (subs & all_card_ids), "SYNSUB01..03 have a parent and must not render as cards"
    assert subs == {g.id for g in b.children["SYNDAY01"]}, "...and must render as children"

    nodes = _explain_forced(f2, B.STATEMENT, _board_params("t1", ANCHOR))
    assert not any(n[0] == "Seq Scan" and n[2] == "goals" for n in nodes), nodes

    isolated = _explain_forced(f2, f"SELECT id FROM goals WHERE {B.MAYBE_PREDICATE}")
    assert any(n[1] == "goals_inbox" for n in isolated), isolated


def test_s25b_f4_5670_plan_shape(f4_5670: psycopg.Connection) -> None:
    """The selection claim: at least one node names `goals_inbox` and none is a `Seq Scan` on
    `goals`, on an F4-5670 clone where the planner cannot fall back on "the whole table is one
    heap page" the way it does on F2. `tests/fixtures/gen_corpus.py` (WP-20) is what supplies
    that scale now — the defensive check below is a pure safety net for a checkout that is
    somehow missing the file it just imported through the `f4_5670` fixture, not a live gate."""
    if not GEN_CORPUS.exists():
        gate(f"F4-5670 absent: {GEN_CORPUS} (WP-20) does not exist")

    nodes = _explain_forced(f4_5670, B.STATEMENT, _board_params("t1", ANCHOR))
    assert not any(n[0] == "Seq Scan" and n[2] == "goals" for n in nodes), nodes
    assert any(n[1] == "goals_inbox" for n in nodes), nodes


# --- prog lateral — `goals_path` plan shape + row-for-row correctness ---------------------------
#
# Not an `E2E.md` scenario id: S-91/S-92/S-93/S-99 (the perf suite) are what *measured* this
# defect (10ms/25ms/300ms-p99/GATE budgets blown, `tests/perf/test_perf_core_queries.py` +
# `tests/perf/test_perf_transport_import.py`), but E2E.md defines
# those scenarios' own steps as wall-clock measurement on a quiet box, not plan-shape or
# correctness assertions — so per the test-naming law (`tests/harness/report.py`'s
# `scenario_id_of`) these two get descriptive names, not `test_s9x_*`. They land as an
# unattributed "naming notice" in the harness output, which is the mechanism working as designed,
# not an error — see `tests/harness/runner.py`'s `_naming_violations` handling.
#
# The defect, measured live on this same F4-5670 corpus before the fix (`core/board.py`'s own
# comment above the `prog` lateral carries the full plan): `starts_with(d.path, cards.path)`,
# correlated to a LATERAL outer row, is a `Var`-argument function call the planner never rewrites
# into an indexable range — `Seq Scan on goals d ... loops=1460, Rows Removed by Filter: 5669`,
# 186,880 of the query's 191,141 total buffer hits, 623.6ms of 623.6ms total. The fix rewrites the
# same predicate as an explicit `text_pattern_ops` range (`~>=~` / `~<~`) the `goals_path` index
# (`goals (owner, path text_pattern_ops)`, `001_init.sql:58`) can serve directly under
# correlation: `Index Scan using goals_path ... loops=1460`, 13.4ms total on the same corpus.


def _oracle_statement() -> str:
    """`B.STATEMENT` with the `prog` lateral's own `WHERE` clause replaced by the predicate
    `core/board.py` shipped through `eb3e048`, before this fix — `starts_with(d.path,
    cards.path) AND d.id <> cards.id`. `starts_with()` is a trusted Postgres builtin that reads
    directly as "rows selected"; S-91/S-92/S-93/S-99 measured *why* it is nonetheless the wrong
    plan under a correlated LATERAL, which is a planner fact, not a correctness one, so it
    remains a valid independent oracle for what the right rows *are*.

    Sliced out structurally — between the lateral's own `FROM goals d` and its closing
    `) prog ON true`, wherever those land — rather than matched against the current predicate's
    exact text, so this oracle keeps comparing something even if the shipped predicate's own
    formatting drifts later; the two `assert`s below are what turn a silent no-op slice into a
    loud failure instead, if the anchors themselves ever move.
    """
    assert B.STATEMENT.count("    FROM goals d\n") == 1, B.STATEMENT
    assert B.STATEMENT.count(") prog ON true\n") == 1, B.STATEMENT
    before, rest = B.STATEMENT.split("    FROM goals d\n", 1)
    _current_where, after = rest.split(") prog ON true\n", 1)
    oracle = (
        f"{before}    FROM goals d\n"
        f"   WHERE d.owner = cards.owner AND starts_with(d.path, cards.path)"
        f" AND d.id <> cards.id\n"
        f") prog ON true\n{after}"
    )
    assert oracle != B.STATEMENT, "oracle collapsed onto the live statement — board.py reverted?"
    return oracle


def test_prog_lateral_plan_uses_goals_path_not_seq_scan_f4_5670(
    f4_5670: psycopg.Connection,
) -> None:
    """Plan-shape regression test, same idiom as `test_s25b_f4_5670_plan_shape` immediately
    above: at least one node names `goals_path` and none is a `Seq Scan` on `goals`. Planted and
    watched fail before this fix landed — restoring `starts_with(d.path, cards.path)` in
    `core/board.py` and re-running just this test reproduces a real `AssertionError` on the first
    assertion (`Seq Scan` on `goals` present, `loops=1460`), not a tautology that can only pass;
    see the fix's own report for the verbatim failure text."""
    if not GEN_CORPUS.exists():
        gate(f"F4-5670 absent: {GEN_CORPUS} (WP-20) does not exist")

    nodes = _explain_forced(f4_5670, B.STATEMENT, _board_params("t1", ANCHOR))
    assert not any(n[0] == "Seq Scan" and n[2] == "goals" for n in nodes), nodes
    assert any(n[1] == "goals_path" for n in nodes), nodes


def test_prog_predicate_matches_starts_with_oracle_row_for_row_f4_5670(
    f4_5670: psycopg.Connection,
) -> None:
    """Correctness proof for the same fix: the rewritten predicate must select exactly the same
    descendant rows as `starts_with(d.path, cards.path) AND d.id <> cards.id` on every card, not
    merely run faster. Runs the live `board.STATEMENT` and the `starts_with()` oracle
    (`_oracle_statement`, above) over the same real F4-5670 corpus and diffs the *entire* board
    result — every column, every one of the ~1460 rendered cards — rather than sampling one
    card's `progress`, since a bound that is off by one row could easily be right for most cards
    and wrong only at a tree edge (a leaf, a root, or a card with exactly one descendant).
    `ORDER BY cards.col_ord, cards.position, cards.id` never depends on this predicate, so a
    positional (not set) comparison also proves row *order* survived untouched."""
    if not GEN_CORPUS.exists():
        gate(f"F4-5670 absent: {GEN_CORPUS} (WP-20) does not exist")

    params = _board_params("t1", ANCHOR)
    live_rows = f4_5670.execute(B.STATEMENT, params).fetchall()
    oracle_rows = f4_5670.execute(_oracle_statement(), params).fetchall()

    assert len(live_rows) == len(oracle_rows) > 0
    assert live_rows == oracle_rows, (
        f"{sum(1 for a, b in zip(live_rows, oracle_rows) if a != b)} of {len(live_rows)} rows "
        f"differ between the live predicate and the starts_with() oracle"
    )


# --- path_well_formed -- the CHECK that makes the successor bound above sound -------------------
#
# `004_path_format.sql`'s `CHECK (path LIKE '/%/' AND path NOT LIKE '%//%')`, named
# `path_well_formed`, is what turns `core/tree.py`'s own writing convention ("every path ends in
# exactly one '/'") into a fact the database refuses to let go false. `core/board.py`'s own
# comment above the `prog` lateral names it as what makes the range bound below sound; that
# comment is the argument in prose, `004_path_format.sql`'s own comment is the argument for why
# this shape and no other, and `tests/core/test_constraints.py`'s
# `test_path_well_formed_fires_on_bad_shapes_and_stays_silent_on_good_ones` is the constraint's
# own mechanics in isolation (which shapes it refuses, which it admits). The two tests below are
# this file's half: the connection between that constraint and *this module's* successor bound
# specifically -- not an `E2E.md` scenario id, same reasoning as the `prog` lateral tests above.


def test_path_well_formed_constraint_exists_and_blocks_the_shape_the_bound_assumes_away(
    f4_5670: psycopg.Connection,
) -> None:
    """The tripwire: if `path_well_formed` is ever dropped from the migration set while the
    successor bound above stays as it is, this test fails two different ways -- the catalogue
    read finds no such constraint, and the UPDATE this test expects to be refused instead
    succeeds. Either failure is the signal "the bound's own assumption is no longer guaranteed,"
    which is the entire reason this constraint exists.

    Uses a real id and a real path already sitting in this corpus, not a placeholder string --
    corrupting it to exactly the shape `core/board.py`'s own comment warns about (the trailing
    '/' stripped) must be refused by the database itself, not merely by application code a bypass
    writer would not be running.
    """
    row = f4_5670.execute(
        "SELECT conname, pg_get_constraintdef(oid) FROM pg_constraint"
        " WHERE conrelid = 'goals'::regclass AND conname = 'path_well_formed'"
    ).fetchone()
    assert row is not None, "path_well_formed is missing from goals -- the bound is now unguarded"
    _conname, condef = row
    assert condef == "CHECK (((path ~~ '/%/'::text) AND (path !~~ '%//%'::text)))", condef

    victim_id, victim_path = f4_5670.execute(
        "SELECT id, path FROM goals WHERE owner = 't1' ORDER BY id LIMIT 1"
    ).fetchone()
    with pytest.raises(psycopg.errors.CheckViolation) as excinfo:
        with f4_5670.transaction():
            f4_5670.execute(
                "UPDATE goals SET path = %(bad)s WHERE id = %(id)s AND owner = 't1'",
                {"bad": victim_path[:-1], "id": victim_id},
            )
    assert excinfo.value.diag.constraint_name == "path_well_formed"

    # Shared, module-scoped connection -- later tests in this file read this same corpus, so the
    # refused UPDATE above must have left this row exactly as it was.
    (unchanged,) = f4_5670.execute(
        "SELECT path FROM goals WHERE id = %(id)s", {"id": victim_id}
    ).fetchone()
    assert unchanged == victim_path


def test_successor_bound_is_sound_and_complete_under_the_constraint_f4_5670(
    f4_5670: psycopg.Connection,
) -> None:
    """The soundness argument for `left(path, -1) || '0'` as `prog`'s exclusive upper bound
    (`core/board.py`'s own comment above the lateral, and `004_path_format.sql`'s comment),
    encoded as a check against real ids from this corpus rather than only argued in prose.

    Picks a real parent with at least one real child already in `f4_5670`. Evaluates the bound
    three ways, using the exact `OPERATOR(pg_catalog.~>=~)` / `OPERATOR(pg_catalog.~<~)`
    operators `B.STATEMENT` itself uses -- never the plain `>=`/`<` the module docstring already
    names as a different, non-indexable comparison:

      1. against the real (well-formed) parent path -- the real child is IN range, agreeing with
         `starts_with`, which is format-agnostic and always correct.
      2. against that same parent path with its trailing '/' stripped -- exactly the shape
         `path_well_formed` exists to refuse -- the same real child falls OUT of range, while
         `starts_with` still says (correctly) that it is a descendant. That gap is the bug this
         constraint exists to prevent: a silent undercount, not an error.
      3. the malformed path against its own successor -- empty range, so the row would not even
         match itself: the literal "upper bound sorts below the lower bound" failure mode
         `004_path_format.sql`'s own comment names.

    Nothing here writes to the table -- every comparison is a `SELECT` over literals bound from a
    row already in `f4_5670`, so `path_well_formed` (which only guards writes) never stands in
    the way of demonstrating what it exists to prevent. This is also why the proof holds for
    *any* real parent/child pair, not a cherry-picked one: a real child's path is always the
    parent's path plus more characters starting with '/', and a real id's last byte is always
    base62 (`>= '0'`, IR-05's alphabet) -- both are true of whichever row this query happens to
    pick, which is the general argument, not a special case of it.
    """
    parent_id, parent_path = f4_5670.execute(
        "SELECT g.id, g.path FROM goals g"
        " WHERE g.owner = 't1' AND EXISTS ("
        "   SELECT 1 FROM goals c WHERE c.owner = 't1' AND c.parent_id = g.id"
        " ) ORDER BY g.id LIMIT 1"
    ).fetchone()
    child_id, child_path = f4_5670.execute(
        "SELECT id, path FROM goals WHERE owner = 't1' AND parent_id = %(pid)s ORDER BY id LIMIT 1",
        {"pid": parent_id},
    ).fetchone()
    assert child_path.startswith(parent_path)  # ground truth, sanity on the fixture itself
    assert parent_path.endswith("/")  # path_well_formed's own guarantee, about to be violated

    malformed_parent_path = parent_path[:-1]  # exactly path_well_formed's own refused shape

    def in_range(bound_path: str, candidate_path: str) -> bool:
        (result,) = f4_5670.execute(
            "SELECT %(cand)s OPERATOR(pg_catalog.~>=~) %(p)s"
            " AND %(cand)s OPERATOR(pg_catalog.~<~) (left(%(p)s, -1) || '0')",
            {"cand": candidate_path, "p": bound_path},
        ).fetchone()
        return result

    def starts_with(prefix_path: str, candidate_path: str) -> bool:
        (result,) = f4_5670.execute(
            "SELECT starts_with(%(cand)s, %(p)s)",
            {"cand": candidate_path, "p": prefix_path},
        ).fetchone()
        return result

    # 1. well-formed parent path: the bound agrees with ground truth.
    assert starts_with(parent_path, child_path) is True
    assert in_range(parent_path, child_path) is True

    # 2. malformed (trailing slash stripped -- path_well_formed's own refused shape): ground
    #    truth is unchanged, starts_with is format-agnostic -- but the range now excludes it.
    assert starts_with(malformed_parent_path, child_path) is True
    assert in_range(malformed_parent_path, child_path) is False, (
        f"child {child_id!r} (path={child_path!r}) fell outside the successor bound computed "
        f"from parent {parent_id!r}'s path with its trailing slash stripped "
        f"({malformed_parent_path!r}) -- this is the silent undercount path_well_formed exists "
        f"to prevent"
    )

    # 3. the malformed path is not even in its own range -- "the upper bound sorts below the
    #    lower bound, the range would be empty" (004_path_format.sql's own claim, checked here
    #    rather than only argued).
    assert in_range(malformed_parent_path, malformed_parent_path) is False
