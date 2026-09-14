"""Suite F (`perf`) — transport and import scenarios: S-93, S-95 through S-99. `docs/E2E.md`
section 8; `docs/IMPLEMENTATION.md` WP-20 card. Runner: `make test-perf` (`python -m
tests.harness.runner --suite perf`, which never adds `-n auto` for this suite —
`tests/harness/runner.py::SERIAL_SUITES` — matching section 8's own "the perf suite runs alone").
Fixtures live in `tests/perf/conftest.py`.

Split out of `tests/perf/test_perf.py` on line-count grounds (`docs/PENDING_DOC_FIXES.md` row 76
— `ARCHITECTURE.md` §2's 750-line cap, `make lint` failing at 799 lines) — this file holds the
scenarios that cross a boundary (HTTP, MCP stdio, a fresh process, a real browser, or the import
CLI) rather than calling `core.board()`/`core.search()` directly; those three (S-91, S-92, S-94)
live in the sibling `tests/perf/test_perf_core_queries.py`. The shared `_judge` teardown both
files call lives in `tests/perf/judge.py`.

**GATE vs FAIL, restated for this suite specifically.** A GATE is reserved for a genuinely
absent precondition: a `ServerBootError` from `spawn_server`/`poll_until_200`/`static_server_perf`
(`tests/perf/conftest.py`). **S-97 no longer gates unconditionally**: its prior reason ("no
shared UI-serving harness exists yet") went stale the moment WP-22 landed `tests/ui/` (commit
c05bd91, checked live against this checkout, not assumed) — WP-22's `vite preview` shape is
`docs/E2E.md` section 1's own documented shape for suite `ui`, not a workaround, so S-97 now
duplicates it at F4-567 scale and gates only on `ServerBootError`, same as every other scenario
here. A real, measured over-budget result is reported as FAIL, in full, with the actual numbers —
never disguised as a GATE. S-95 is expected to genuinely FAIL this run; see its own docstring for
the numbers and root cause (belongs to `verticals/mcp/tools.py`, WP-19's file, not this package's).

**S-95's async/sync split.** Verified live (a throwaway scratchpad script, never shipped) that an
exception raised from inside `mcp.client.stdio.stdio_client(...)` / `mcp.ClientSession(...)`'s
own `async with` blocks arrives at the caller wrapped in nested `ExceptionGroup`s from anyio's
TaskGroup — which would bury `tests/harness/report.py::fail()`'s fixed-shape block inside a
traceback dump instead of printing it verbatim. `_mcp_board_round_trips` below only ever measures
and returns plain data; `test_s95_mcp_board_f4_5670` calls `fail()` afterward, in ordinary
synchronous code, with no anyio TaskGroup anywhere on the stack.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from pathlib import Path

import psycopg
import pytest
from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

from verticals.core import board as B
from verticals.core import search as S
from tests.conftest import fresh_clone, maintenance_dsn
from tests.harness import calibrate
from tests.harness.report import artifact, gate
from tests.perf.conftest import (
    ANCHOR,
    ARTIFACTS_DIR,
    OWNER,
    REPO_ROOT,
    SERVER_TOKEN,
    ServerBootError,
    dsn,
    get_board_http,
    poll_until_200,
    spawn_server,
    static_server_perf,
    stop_server,
    time_iterations,
    xact_commit_on,
)
from tests.perf.judge import _judge
from tests.perf.s97_ui_paint import (
    ITERATIONS,
    WARMUPS,
    build_checks,
    count_dom_goal_nodes,
    measure_ui_paint,
)
from tools.import_planner import DEFAULT_POLICY, run_import

# `web_dist_perf` (tests/perf/conftest.py, session-scoped) is used below as a bare parameter name
# on test_s97_ui_navigation_paint — pytest resolves fixtures by name, no import needed.

# --- boot-failure -> GATE conversion --------------------------------------------------------
#
# `_judge` (the percentile/budget/relative-drift teardown every scenario below calls) and its
# `_location` helper now live in `tests/perf/judge.py`, imported by both this file and
# `tests/perf/test_perf_core_queries.py` — kept in one place rather than duplicated. Only
# `_poll_or_gate` stays here: every one of its callers (S-93, S-96, S-97, S-99) is in this file.


def _poll_or_gate(proc, port: int, *, scenario_id: str, timeout_s: float) -> float:
    """`tests/perf/conftest.py::ServerBootError`'s own documented contract: every caller in this
    file converts it to `gate()` — a boot failure on `verticals/api/**` mid-flight is the
    documented GATE case, never a bare pytest error that looks like this package's own bug."""
    try:
        return poll_until_200(proc, port, timeout_s=timeout_s)
    except ServerBootError as exc:
        gate(f"{scenario_id}: server failed to boot within {timeout_s}s: {exc}")


# --- S-93 — GET /api/board end to end ---------------------------------------------------------


def test_s93_http_board_f4_5670(f4_5670: str, request: pytest.FixtureRequest) -> None:
    """docs/E2E.md S-93 — `GET /api/board` end to end over loopback HTTP, F4-5670, 200 (+20)
    iterations. Two budgets on the same distribution (E2E.md's own table row): p95 <= 150ms
    (the gate `_judge` checks) and p99 <= 300ms (a secondary check folded in as a `checks`
    entry, since it is a per-run statistic rather than a per-call invariant, but still a hard
    "no" if violated, same as everywhere else in this suite). Hard invariant: `X-Query-Count: 1`
    on every call — the same counter S-91/S-92 read directly, reached here through the real HTTP
    header instead (E2E.md section 8: "the same counter that produces X-Query-Count, so S-91 and
    S-93 assert the same fact through the same mechanism at two layers"). The server is spawned
    once, polled to its first 200 *outside* the timed window (S-96 owns cold start; this
    scenario measures steady state), then every iteration is one more request against the same
    warm process.
    """
    proc, port = spawn_server(dsn(f4_5670))
    try:
        _poll_or_gate(proc, port, scenario_id="S-93", timeout_s=30.0)

        query_counts: list[int] = []

        def call() -> None:
            count, _body = get_board_http(port)
            query_counts.append(count)

        samples = time_iterations(call, warmups=20, iterations=200)
    finally:
        stop_server(proc)

    stats = calibrate.percentiles(samples)
    bad_count = sorted({c for c in query_counts if c != 1})
    p99_ok = stats["p99"] <= 300.0

    _judge(
        request, scenario_id="S-93", samples=samples, budget_ms=150.0, stat_name="p95",
        checks=(
            (
                "X-Query-Count == 1 on every call",
                not bad_count,
                f"saw X-Query-Count values {bad_count or '(none)'} among {len(query_counts)} "
                f"calls.",
            ),
            (
                "p99 <= 300ms",
                p99_ok,
                f"measured p99={stats['p99']:.2f}ms over {stats['count']} samples.",
            ),
        ),
    )


# --- S-95 — MCP board tool, stdio round trip ---------------------------------------------------


async def _mcp_board_round_trips(
    target_dsn: str, *, warmups: int, iterations: int
) -> tuple[list[float], list[int], list[bool]]:
    """One stdio server, spawned once; one session, initialized once; then `warmups +
    iterations` sequential `board` tool calls over it — mirrors `time_iterations`'s own
    warmup/discard shape, just async because the `mcp` SDK's stdio transport is.

    Returns plain lists, never raises for a per-call problem, and is never the thing that calls
    `pytest.fail`/`tests.harness.report.fail` — see this module's own docstring for why. This
    function only measures and returns; the caller judges, in plain synchronous code, after
    `asyncio.run` has already returned normally.
    """
    env = dict(os.environ)
    env["VERTICALS_DATABASE_URL"] = target_dsn
    env["VERTICALS_TOKEN"] = SERVER_TOKEN
    env["VERTICALS_OWNER"] = OWNER
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "verticals.mcp.server", "--transport", "stdio"],
        env=env,
        cwd=REPO_ROOT,
    )

    latencies_ms: list[float] = []
    payload_bytes: list[int] = []
    is_error_flags: list[bool] = []

    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            async def one_call() -> tuple[float, int, bool]:
                t0 = time.perf_counter()
                result = await session.call_tool("board", {"date": ANCHOR.isoformat()})
                elapsed_ms = (time.perf_counter() - t0) * 1000.0
                size = len(json.dumps(result.structured_content).encode("utf-8"))
                return elapsed_ms, size, bool(result.is_error)

            for _ in range(warmups):
                await one_call()
            for _ in range(iterations):
                elapsed_ms, size, is_err = await one_call()
                latencies_ms.append(elapsed_ms)
                payload_bytes.append(size)
                is_error_flags.append(is_err)

    return latencies_ms, payload_bytes, is_error_flags


_MCP_PAYLOAD_BUDGET_BYTES = 512 * 1024  # E2E.md S-95's own F4-5670 figure ("512 KB at F4-5670")


def test_s95_mcp_board_f4_5670(f4_5670: str, request: pytest.FixtureRequest) -> None:
    """docs/E2E.md S-95 — MCP `board` tool, real stdio round trip (the official `mcp` SDK client
    against a real `python -m verticals.mcp.server --transport stdio` subprocess, per this
    suite's own intro), F4-5670, 200 (+20) iterations, 200ms budget, payload <= 512KB.

    **Still failing the size check, for a different reason than it first did.** The original
    diagnosis was a transport contract drift: `verticals/mcp/tools.py::_goal_dict()` sent the
    literal `body` field on every goal where `verticals/api/schemas.py::goal_to_card()` correctly
    sent `body_chars`, against D9's "No `body`; a `body_chars` integer instead, and one 128 KB
    budget on both transports". That was real and is fixed (bea2e72). It was not, however, what
    breaks this budget: the payload moved only 781316 -> 771197 bytes, about 1.3%.

    What remains is card volume, and it is not an MCP problem at all. Running the same F4-5670
    corpus through the *untouched* HTTP serialiser — `api/schemas.py::board_to_json()`, called
    directly, no server, no MCP — yields 756921 bytes with no `body` key present anywhere. Same
    overage, on the transport this fix never touched. So the bytes live in what a board *is*: the
    F4-5670 board is roughly 2100 cards, of which the Maybe column alone is 1149, and no document
    specifies a per-column cap, a limit, or pagination for it. `board_to_json` additionally emits
    every card's children as full cards, so a goal with a parent is serialised twice — once in its
    own column, once inside its parent's `children` list.

    Left as a measured FAIL rather than converted to a GATE: the transport answers correctly
    (`is_error` is False, the board renders), it simply carries more than its budget allows, and
    that is a real result about the product rather than a missing precondition. Whether the
    budget, the duplication, or the absent column cap is the thing to change is a ruling, not a
    patch — `docs/PENDING_DOC_FIXES.md` row 64 lays out the three readings and the evidence that
    does not yet separate them. Note also that S-92 misses its own latency budget on the same
    corpus for what is plausibly the same underlying reason (card count), which is worth weighing
    when that ruling is made.
    """
    latencies_ms, payload_bytes, is_error_flags = asyncio.run(
        _mcp_board_round_trips(dsn(f4_5670), warmups=20, iterations=200)
    )

    bad_errors = [i for i, is_err in enumerate(is_error_flags) if is_err]
    bad_size = [b for b in payload_bytes if b > _MCP_PAYLOAD_BUDGET_BYTES]

    _judge(
        request, scenario_id="S-95", samples=latencies_ms, budget_ms=200.0, stat_name="p95",
        checks=(
            (
                "result.is_error is False on every call",
                not bad_errors,
                f"{len(bad_errors)}/{len(is_error_flags)} call(s) returned is_error=True "
                f"(indices {bad_errors[:10]}).",
            ),
            (
                f"serialised structured_content <= {_MCP_PAYLOAD_BUDGET_BYTES} bytes (512KB) "
                f"at F4-5670, every call",
                not bad_size,
                (
                    f"{len(bad_size)}/{len(payload_bytes)} call(s) exceeded 512KB; observed "
                    f"{min(payload_bytes)}-{max(payload_bytes)} bytes over {len(payload_bytes)} "
                    f"calls. Not a body/body_chars drift — that was real, is fixed (bea2e72), and "
                    f"moved this only 781316 -> 771197 bytes. The remainder is card volume and is "
                    f"transport-independent: the same corpus through the untouched HTTP "
                    f"serialiser (api/schemas.py::board_to_json, called directly) is 756921 bytes "
                    f"with no `body` key anywhere. The F4-5670 board is ~2100 cards, 1149 of them "
                    f"in an uncapped Maybe column, and every card's children ship as full cards "
                    f"too. Needs a ruling, not a patch: docs/PENDING_DOC_FIXES.md row 64."
                ),
            ),
        ),
        extra_artifact={
            "payload_bytes_min": min(payload_bytes) if payload_bytes else None,
            "payload_bytes_max": max(payload_bytes) if payload_bytes else None,
            "payload_bytes_budget": _MCP_PAYLOAD_BUDGET_BYTES,
        },
    )


# --- S-96 — cold start: exec -> first 200 on /api/board -----------------------------------------


def test_s96_http_cold_start_f4_5670(f4_5670: str, request: pytest.FixtureRequest) -> None:
    """docs/E2E.md S-96 — cold start, `exec` to first 200 on `/api/board`, F4-5670, 10 (+3),
    3000ms budget, gated on `max` (section 8: "for S-96, S-97, S-98 and S-99 ... the gate is
    `max <= budget` rather than `p95 <= budget`, because with ten samples the 95th percentile
    *is* the maximum"). A cold start cannot be warmed up without contradiction — "warmups" here
    means the first 3 (of 13 total) fresh-process measurements are taken and discarded, same
    intent as `time_iterations`'s own warmup/discard split, just applied at the process level
    since each sample needs its own fresh `exec`, not a repeated call over one warm process.
    """
    target = dsn(f4_5670)
    warmups, iterations = 3, 10
    all_samples: list[float] = []
    for _ in range(warmups + iterations):
        proc, port = spawn_server(target)
        try:
            elapsed_s = _poll_or_gate(proc, port, scenario_id="S-96", timeout_s=30.0)
            all_samples.append(elapsed_s * 1000.0)
        finally:
            stop_server(proc)

    measured = all_samples[warmups:]
    assert len(measured) == iterations, (measured, all_samples)

    _judge(request, scenario_id="S-96", samples=measured, budget_ms=3000.0, stat_name="max")


# --- S-97 — UI navigation start -> last card painted ---------------------------------------------
#
# Measurement machinery (Playwright orchestration, paint/CLS detection, the DOM-node-count
# formula) lives in tests/perf/s97_ui_paint.py — split out on line-count grounds (see that
# module's own docstring). This is the thin pytest wiring only.


def test_s97_ui_navigation_paint(
    f4_567: str, web_dist_perf: None, tmp_path: Path, request: pytest.FixtureRequest
) -> None:
    """docs/E2E.md S-97 — UI: navigation start to last board card painted, production build,
    localhost, F4-567, 20 (+3), 1500ms budget, gated on `max` (S-96 groups S-96/S-97/S-98/S-99
    under "gate is max <= budget"). Beyond the budget: zero console errors, zero layout shifts
    after paint (CLS = 0, AC-123), rendered `[data-goal-id]` count == `count_dom_goal_nodes`'s
    prediction exactly — a live cross-check of that formula, not just an assumption.

    Formerly gated unconditionally — see this module's docstring, "GATE vs FAIL, restated for
    this suite specifically," for why. `verticals/api/app.py` still mounts no `StaticFiles` route
    (checked again against this checkout) — irrelevant: `vite preview` serves the UI here, never
    the API server (WP-22's own division for suite `ui`).

    Backend spawned once at F4-567; `get_board_http` reads the board once, before any browser
    opens, only to compute `target_count`, not part of the timed window — see `measure_ui_paint`.
    """
    proc, port = spawn_server(dsn(f4_567))
    try:
        _poll_or_gate(proc, port, scenario_id="S-97", timeout_s=30.0)
        _query_count, board_json = get_board_http(port)
        target_count = count_dom_goal_nodes(board_json)
        assert target_count > 0, (
            f"F4-567 board rendered 0 [data-goal-id] nodes — nothing for S-97 to time the "
            f"painting of; columns={[c['vertical'] for c in board_json['columns']]}"
        )

        backend_base_url = f"http://127.0.0.1:{port}"
        try:
            with static_server_perf(backend_base_url, tmp_path) as static_base_url:
                (
                    paint_samples, rendered_counts, console_errors, layout_shifts_after_paint,
                    timeouts,
                ) = measure_ui_paint(
                    static_base_url, target_count, warmups=WARMUPS, iterations=ITERATIONS
                )
        except ServerBootError as exc:
            gate(f"S-97: static server failed to boot within 15s: {exc}")
    finally:
        stop_server(proc)

    _judge(
        request, scenario_id="S-97", samples=paint_samples, budget_ms=1500.0, stat_name="max",
        checks=build_checks(
            target_count=target_count, timeouts=timeouts, rendered_counts=rendered_counts,
            console_errors=console_errors, layout_shifts_after_paint=layout_shifts_after_paint,
        ),
        extra_artifact={"target_dom_node_count": target_count},
    )


# --- S-98 — import 567 rows end to end -----------------------------------------------------------


def test_s98_import_567_end_to_end(export_rows_567: list[dict], request: pytest.FixtureRequest) -> None:
    """docs/E2E.md S-98 — import 567 rows end to end, `tools/import_planner.py::run_import`
    against a synthetic planner-shaped export (`generate_export_rows`'s own guarantee: every
    row classifies `CLASS_AUTHORED`, so a default-policy import keeps all 567 rows, zero drops),
    10 (+3) iterations, 10 000ms budget, gated on `max` (see S-96's docstring for why). Hard
    invariants, both checked every iteration: exactly one committed transaction
    (`pg_stat_database.xact_commit` delta — the CLI's own pattern: `autocommit=True` connection,
    one explicit `with conn.transaction():` wrapping the whole `run_import` call), and 567 rows
    imported with zero drops.

    **Where the two readings are taken, and why not the obvious places.** Opening a backend is
    itself a commit — PostgreSQL validates the session against the catalogs in a transaction that
    commits before the client can send anything, and `xact_commit` counts it (`xact_commit_on`'s
    own docstring carries the measurements). This scenario originally read `before` above
    `psycopg.connect`, which put that bootstrap commit inside the window and made `delta == 1`
    unreachable: the floor is 2 for any workload that opens its own connection, so the check
    reported FAIL — the verdict that claims the code is broken — against an import that commits
    exactly once. It does: verified independently three times over, by server-side
    `log_statement=all` capture (one literal `BEGIN`, one literal `COMMIT`, N matched
    SAVEPOINT/RELEASE pairs) and by zero-SQL connection probes.

    So `before` is read *after* `conn` exists, leaving the bootstrap commit outside the window and
    restoring the assertion's plain meaning: one commit by the workload. Both readings go through
    one `monitor` connection opened before the clock starts, never a fresh connection per reading —
    a new backend taken for the `before` reading would contribute its own bootstrap commit to the
    very counter being read. The cost of reading `before` does land inside the timed region,
    unavoidably: the clock must start before `psycopg.connect` because connecting is part of
    importing, and the reading must follow it. On a warm connection that is one indexed catalog
    lookup, sub-millisecond against a 10 000 ms budget.

    **A residue this check cannot remove, recorded so a rare red is not mistaken for a
    regression.** `xact_commit` is per *database*, not per backend, so any other process that
    connects to the clone inflates it — in practice the autovacuum launcher, which visits a newly
    created database, pays its own bootstrap commit and runs a check transaction, and leaves
    `last_autovacuum`/`last_autoanalyze` NULL because finding nothing to do is not a vacuum.
    Measured over 25 runs of this exact window: 23 read 1, one read 3, one read 5 — even excesses,
    one visiting backend apiece. This fix took the scenario from 10/10 wrong to roughly 1/10, and
    the remainder is the instrument rather than the importer. `docs/PENDING_DOC_FIXES.md` row 70
    proposes the replacement that removes it: observe atomicity directly, by polling row visibility
    from a second connection during the import and requiring every sample to be 0 or 567 and never
    a partial count — a claim about what a concurrent reader can see, which no background worker
    can perturb.

    Not solved by asserting `delta == 2` — that pins a backend-startup detail into a product test
    and would break the day this runs on a pooled connection. Not solved by reading through the
    import's own connection either: the bootstrap commit precedes any statement that connection
    can issue. And not provable from `xmin` diversity, which looks like a cleaner direct test of
    "one transaction" and is wrong here — subtransactions take their own xids when they write, and
    this import uses SAVEPOINTs, so correct code shows several distinct `xmin` values.

    Each iteration gets its own fresh `f0` clone — import is a write; replaying it against an
    already-populated database would time a degenerate no-op (`attach`'s own `ON CONFLICT (id)
    DO NOTHING`), not a real import. `path` is a placeholder `Path` that is never opened —
    confirmed by reading `run_import`/`validate_rows`: `path` is used only inside f-string error
    messages, never `path.read_text()`'d (this scenario hands rows in directly via `rows=`,
    matching `run_import`'s own parameter, not the CLI's file-reading wrapper). Timed end to
    end, literally: from `psycopg.connect` through the transaction's own commit (on the `with
    conn.transaction():` block's clean exit) to `conn.close()` returning — the clone/drop
    overhead around that is excluded, since building or discarding a database is not part of
    "importing," but connecting to one is.
    """
    warmups, iterations = 3, 10
    placeholder_path = Path("S-98-synthetic-export.json")  # never opened — see docstring
    samples: list[float] = []
    single_txn_ok: list[bool] = []
    clean_imports: list[bool] = []

    for i in range(warmups + iterations):
        with fresh_clone("f0") as clone_name, \
                psycopg.connect(maintenance_dsn(), autocommit=True) as monitor:
            target = dsn(clone_name)

            t0 = time.perf_counter()
            conn = psycopg.connect(target, autocommit=True)
            before = xact_commit_on(monitor, clone_name)  # after connect — see docstring
            try:
                with conn.transaction():
                    result = run_import(
                        conn, owner=OWNER, path=placeholder_path,
                        rows=export_rows_567, policy=DEFAULT_POLICY,
                    )
            finally:
                conn.close()
            elapsed_ms = (time.perf_counter() - t0) * 1000.0

            after = xact_commit_on(monitor, clone_name)

        if i >= warmups:
            samples.append(elapsed_ms)
            single_txn_ok.append(after - before == 1)
            clean_imports.append(result.imported == 567 and sum(result.dropped.values()) == 0)

    bad_txn = sum(1 for ok in single_txn_ok if not ok)
    bad_import = sum(1 for ok in clean_imports if not ok)
    _judge(
        request, scenario_id="S-98", samples=samples, budget_ms=10_000.0, stat_name="max",
        checks=(
            (
                "pg_stat_database.xact_commit delta == 1 (single transaction), every iteration",
                bad_txn == 0,
                f"{bad_txn}/{len(single_txn_ok)} iteration(s) committed a delta other than 1.",
            ),
            (
                "all 567 rows imported, zero drops, every iteration",
                bad_import == 0,
                f"{bad_import}/{len(clean_imports)} iteration(s) diverged from 567 imported / "
                f"0 dropped.",
            ),
        ),
    )


# --- S-99 — non-gating headroom probe --------------------------------------------------------
#
# Grouped with the transport family, not with S-91/S-92/S-94 in the sibling file, even though it
# also calls core.board()/core.search() directly (same shape as S-91/S-94) — its cold-start leg
# reuses _poll_or_gate/spawn_server/stop_server, the mechanism every other scenario in this file
# already needs, so this is the placement that avoids a second cross-file import for one row.


def _write_multi_artifact(scenario_id: str, distributions: dict[str, list[float]]) -> Path:
    """S-99's own shape: one scenario id, three named distributions (board/search/cold_start),
    where every other row in this suite has exactly one. Mirrors `write_artifact`'s own idiom
    (same directory, same `samples_ms` key, same `indent=2`) for the one row that does not fit
    its single-distribution signature, rather than bending that shared helper to a shape only
    this row needs.
    """
    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    path = ARTIFACTS_DIR / f"{scenario_id}.json"
    payload = {
        label: {**calibrate.percentiles(samples), "samples_ms": samples}
        for label, samples in distributions.items()
    }
    path.write_text(json.dumps(payload, indent=2))
    return path


def test_s99_headroom_probe_f4_56700(f4_56700: str, request: pytest.FixtureRequest) -> None:
    """docs/E2E.md S-99 — non-gating headroom probe, F4-56700 (10x F4-5670), 3 (+0) iterations
    (section 8's own "3 (+0)" — zero warmups: a cold start cannot be warmed up without
    contradiction, and this row exists to know where the suite's own budgets stop applying, not
    to re-measure a steady state the other eight rows already cover). Records p50/p95/p99/max
    for `core.board()`, `core.search(q='cycl')` (same call shape as S-91/S-94, just at 10x
    scale) and one HTTP cold start per iteration (S-96's own mechanism, same scale jump).
    Deliberately never asserts a budget (`docs/E2E.md`: "must complete; records..."); a
    `ServerBootError` from the cold-start leg still converts to `gate()` (this module's own
    uniform rule for that specific, documented failure mode — a harness/boot problem, not a
    product-scale breaking point), but nothing else here catches an exception: a `core.board()`
    or `core.search()` call breaking down at 56700 rows is itself the finding this row exists to
    surface, not a bug in the row.
    """
    conn = psycopg.connect(dsn(f4_56700), autocommit=True)
    try:
        board_samples = time_iterations(
            lambda: B.board(conn, owner=OWNER, date=ANCHOR), warmups=0, iterations=3
        )
        search_samples = time_iterations(
            lambda: S.search(conn, owner=OWNER, q="cycl", limit=S.MAX_LIMIT),
            warmups=0, iterations=3,
        )
    finally:
        conn.close()

    cold_start_samples: list[float] = []
    target = dsn(f4_56700)
    for _ in range(3):
        proc, port = spawn_server(target)
        try:
            elapsed_s = _poll_or_gate(proc, port, scenario_id="S-99", timeout_s=60.0)
            cold_start_samples.append(elapsed_s * 1000.0)
        finally:
            stop_server(proc)

    distributions = {
        "board": board_samples, "search": search_samples, "cold_start": cold_start_samples,
    }
    for label, samples in distributions.items():
        stats = calibrate.percentiles(samples)
        print(
            f"S-99[{label}]: p50={stats['p50']:.2f}ms p95={stats['p95']:.2f}ms "
            f"p99={stats['p99']:.2f}ms max={stats['max']:.2f}ms n={stats['count']}"
        )

    path = _write_multi_artifact("S-99", distributions)
    artifact(request, str(path.relative_to(REPO_ROOT)))
