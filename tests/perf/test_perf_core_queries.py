"""Suite F (`perf`) — core-query scenarios: S-91, S-92, S-94. `docs/E2E.md` section 8;
`docs/IMPLEMENTATION.md` WP-20 card. Runner: `make test-perf` (`python -m tests.harness.runner
--suite perf`, which never adds `-n auto` for this suite — `tests/harness/runner.py::SERIAL_SUITES`
— matching section 8's own "the perf suite runs alone"). Fixtures live in `tests/perf/conftest.py`.

Split out of `tests/perf/test_perf.py` on line-count grounds (`docs/PENDING_DOC_FIXES.md` row 76
— `ARCHITECTURE.md` §2's 750-line cap, `make lint` failing at 799 lines) — this file holds the
three scenarios that call `core.board()`/`core.search()` directly against an already-open
connection, no transport in between, mirroring `verticals/`'s own "the seam here is transport vs
logic: core/ never imports FastAPI or MCP" split (`ARCHITECTURE.md` §2). The transport- and
import-facing scenarios (S-93, S-95 through S-99) live in the sibling
`tests/perf/test_perf_transport_import.py`; the shared `_judge` teardown both files call lives in
`tests/perf/judge.py`.

**The execute-counter correction.** `tests/core/test_board.py`'s S-22 reads "exactly one
statement" from `tests/harness/stmt.py` (`pg_stat_statements`, scoped by `dbid`). S-91 and S-92
below do not — `docs/E2E.md` section 8 says so explicitly: "The invariant is read from the
application's own per-connection execute counter (section 1), which is exact per call and safe
under parallel workers, not from `pg_stat_statements` ... This is the same counter that produces
`X-Query-Count`, so S-91 and S-93 assert the same fact through the same mechanism at two layers."
That counter is `verticals.api.deps.CountingCursor` — a plain `psycopg.Cursor` subclass that only
ever touches `self.connection`, never `Request` or the connection pool (confirmed by reading it)
— so it is reusable standalone on a bare `psycopg.connect(...)` with no FastAPI app anywhere in
the loop: `conn.cursor_factory = CountingCursor; conn.query_count = 0`, call, read
`conn.query_count` back. Cheaper than the `stmt.py` mechanism here too — no extra database round
trip per reset/read, which matters at S-91's own 10ms budget.
"""

from __future__ import annotations

import psycopg
import pytest

from verticals.api import deps
from verticals.core import board as B
from verticals.core import vertical
from verticals.core import search as S
from tests.fixtures import gen_corpus as G
from tests.perf.conftest import ANCHOR, OWNER, dsn, time_iterations
from tests.perf.judge import _judge

# --- S-91 — core.board() at F4-567 -----------------------------------------------------------


def test_s91_core_board_f4_567(f4_567: str, request: pytest.FixtureRequest) -> None:
    """docs/E2E.md S-91 — `core.board()` at F4-567 (567 rows), 200 (+20) iterations, 10ms
    budget (p95). Hard invariant: the execute-counter delta is exactly 1 on every call — see
    this module's own docstring for why that is `verticals.api.deps.CountingCursor`, reused here
    directly on a plain connection, and not `tests/harness/stmt.py`. Resetting
    `conn.query_count = 0` between calls is a Python attribute write, not a database round trip,
    so it costs nothing inside the timed window.
    """
    conn = psycopg.connect(dsn(f4_567), autocommit=True)
    conn.cursor_factory = deps.CountingCursor
    exec_deltas: list[int] = []
    try:
        def call() -> None:
            conn.query_count = 0
            B.board(conn, owner=OWNER, date=ANCHOR)
            exec_deltas.append(conn.query_count)

        samples = time_iterations(call, warmups=20, iterations=200)
    finally:
        conn.close()

    bad = sorted({d for d in exec_deltas if d != 1})
    _judge(
        request, scenario_id="S-91", samples=samples, budget_ms=10.0, stat_name="p95",
        checks=(
            (
                "execute-counter delta == 1 on every call",
                not bad,
                f"saw delta values {bad or '(none)'} among {len(exec_deltas)} calls "
                f"({sum(1 for d in exec_deltas if d != 1)} violation(s)).",
            ),
        ),
    )


# --- S-92 — core.board() at F4-5670, dense column (AC-190) -----------------------------------


def test_s92_core_board_f4_5670_dense_column(f4_5670: str, request: pytest.FixtureRequest) -> None:
    """docs/E2E.md S-92 — `core.board()` at F4-5670 (5670 rows), anchored on
    `gen_corpus.DENSE_COLUMN_DATE` so every call also renders the deliberately dense
    `(month, 2026-03)` column that module forces (`_force_dense_column`'s own docstring names
    this exact test as its consumer). 200 (+20) iterations, 25ms budget (p95). Two hard
    invariants, both checked every call: the same execute-counter-delta-1 as S-91, and AC-190's
    own dense-column check — the returned column's row count must equal a live
    `SELECT count(*)` against the same predicate, "no cap, no truncation, no 'show more' gate" —
    read from the board itself, never hand-derived from `shape.json`'s target count, so an
    incidental RNG collision from an independently-rolled row landing in the same period is
    still accounted for correctly.
    """
    dense_period_key = vertical.period_key(G.DENSE_COLUMN_VERTICAL, G.DENSE_COLUMN_DATE)
    conn = psycopg.connect(dsn(f4_5670), autocommit=True)
    try:
        (stored_count,) = conn.execute(
            "SELECT count(*) FROM goals"
            "  WHERE owner = %(owner)s AND vertical = %(vertical)s::vertical_scale"
            "    AND period_key = %(period_key)s",
            {"owner": OWNER, "vertical": G.DENSE_COLUMN_VERTICAL, "period_key": dense_period_key},
        ).fetchone()

        conn.cursor_factory = deps.CountingCursor
        exec_deltas: list[int] = []
        returned_counts: list[int] = []

        def call() -> None:
            conn.query_count = 0
            b = B.board(conn, owner=OWNER, date=G.DENSE_COLUMN_DATE)
            exec_deltas.append(conn.query_count)
            col = next(
                c for c in b.columns
                if c.vertical == G.DENSE_COLUMN_VERTICAL and c.period_key == dense_period_key
            )
            returned_counts.append(len(col.goals))

        samples = time_iterations(call, warmups=20, iterations=200)
    finally:
        conn.close()

    bad_exec = sorted({d for d in exec_deltas if d != 1})
    bad_count = sorted({c for c in returned_counts if c != stored_count})
    _judge(
        request, scenario_id="S-92", samples=samples, budget_ms=25.0, stat_name="p95",
        checks=(
            (
                "execute-counter delta == 1 on every call",
                not bad_exec,
                f"saw delta values {bad_exec or '(none)'} among {len(exec_deltas)} calls.",
            ),
            (
                "returned dense-column row count == live stored count (AC-190)",
                not bad_count,
                f"stored count is {stored_count}; saw returned counts {bad_count or '(none)'} "
                f"among {len(returned_counts)} calls (no cap, no truncation permitted).",
            ),
        ),
        extra_artifact={"dense_column_stored_count": stored_count},
    )


# --- S-94 — core.search(q='cycl') --------------------------------------------------------------


def test_s94_core_search_f4_5670(f4_5670: str, request: pytest.FixtureRequest) -> None:
    """docs/E2E.md S-94 — `core.search(q='cycl')` at F4-5670, 200 (+20) iterations, 200ms
    budget (J6's own verbatim number). Hard invariant: exact recall, not sampled — the generator
    plants exactly 40 rows whose title contains the needle
    (`tests/fixtures/gen_corpus.py::_plant_search_matches`), and this scenario asks for all 200
    (`search.MAX_LIMIT`) slots so a coincidentally-sufficient default limit can never be the
    reason the count comes out right — `truncated` must also read False every time, and every
    returned row's own title must actually carry the needle, not just the count.
    """
    conn = psycopg.connect(dsn(f4_5670), autocommit=True)
    try:
        counts: list[int] = []
        recall_ok: list[bool] = []

        def call() -> None:
            result = S.search(conn, owner=OWNER, q="cycl", limit=S.MAX_LIMIT)
            counts.append(len(result.goals))
            recall_ok.append(
                len(result.goals) == 40
                and result.truncated is False
                and all("cycl" in g.title for g in result.goals)
            )

        samples = time_iterations(call, warmups=20, iterations=200)
    finally:
        conn.close()

    bad = sorted({c for c in counts if c != 40})
    _judge(
        request, scenario_id="S-94", samples=samples, budget_ms=200.0, stat_name="p95",
        checks=(
            (
                "exactly 40 planted matches return, untruncated, every call",
                all(recall_ok),
                f"expected count 40 every time; saw {bad or '(none)'} among {len(counts)} calls.",
            ),
        ),
    )
