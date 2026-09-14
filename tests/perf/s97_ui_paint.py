"""S-97's own measurement machinery — `docs/E2E.md` S-97 (UI: navigation start to last board card
painted). Split out of `tests/perf/test_perf.py` on line-count grounds (that file was already at
698/750 lines before S-97 existed; this scenario's Playwright orchestration, paint-detection and
CLS instrumentation cannot fit the remainder without breaching the house 750-line-per-module cap)
— same reason `calibrate.py`, `report.py` and `stmt.py` already live apart from the test files
that call them (`tests/harness/`). `test_s97_ui_navigation_paint` (in
`test_perf_transport_import.py`) is the only caller; nothing else in this suite depends on this
file, and this file owns no fixtures itself.

`PINNED_CLOCK_ISO`/`UI_VIEWPORT` duplicate `tests/ui/conftest.py`'s own constants — this package's
stated "duplicate, don't cross a suite boundary" convention (`tests/perf/conftest.py`'s own
`web_dist_perf` docstring). The clock must be pinned: `store.ts::todayIso()` reads the real wall
clock unless pinned, and F4-567 is anchored on 2026-08-08 (`tests/perf/conftest.py::ANCHOR`).
"""

from __future__ import annotations

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

from tests.perf.conftest import time_iterations

PINNED_CLOCK_ISO = "2026-08-08T09:00:00+03:00"
UI_VIEWPORT = {"width": 1458, "height": 779}
# A navigation this slow is FAIL/GATE material regardless of the exact number — see
# measure_ui_paint's docstring for why timing it via time_iterations anyway is still correct.
PAINT_TIMEOUT_MS = 10_000.0
# docs/E2E.md S-97's own row: "20 (+3)". One source of truth — test_perf_transport_import.py's
# call site and build_checks' own count-of-navigations message below both read these, not a literal.
WARMUPS = 3
ITERATIONS = 20


def count_dom_goal_nodes(board_json: dict) -> int:
    """How many `[data-goal-id]` nodes the board must paint — mirrors
    `web/src/store.ts::toCardData`'s own recursive rule: every card in every column renders once,
    recursing into `board_json["children"][card_id]`, nesting only `vertical is None` children
    (store.ts's own "SYNQ2R01 appears twice" comment is why — a scheduled child already owns its
    own column card).

    Verified live against a real F4-567 corpus (throwaway scratchpad probe, not shipped):
    `core/board.py`'s `children` dict only ever holds entries for goals that are themselves cards,
    capping real recursion at one hop past any card today (567 rows, 147 cards, 155 rendered
    nodes, max depth 2 — independently corroborated by `docs/E2E.md` S-61's own worked example,
    the same one-hop shape). Not baked in as an assumption, though — this runs the same walk
    `toCardData` runs, so it stays correct even if that ceiling changes.
    """
    children_by_id: dict[str, list[dict]] = board_json["children"]

    def count_subtree(goal_id: str) -> int:
        kids = children_by_id.get(goal_id, [])
        unscheduled = [k for k in kids if k["vertical"] is None]
        return 1 + sum(count_subtree(k["id"]) for k in unscheduled)

    # The unverticaled column is in the payload and is not on the board. Owner ruling 1 of
    # 2026-08-09 ("no need to show Maybe as a left column, make it same tab as Inbox") moved those
    # goals to the Inbox nav view, which is mutually exclusive on screen with the board
    # (`App.vue`'s `v-if`/`v-else`) — so `Board.vue` never paints them and a count that includes
    # them is a target the DOM cannot reach. It did not: all 20 navigations of the run of
    # 2026-08-09 timed out at the 10s probe ceiling waiting for 155 nodes, which is what turned a
    # 1500ms budget into a flat 10035ms max.
    #
    # Deliberately filtered here rather than fixed in `core/board.py`: the API still returns the
    # column, on purpose (`tests/mcp/test_reads.py` and `test_transport_http.py` both assert it and
    # both still pass). The ruling changed where the UI draws unverticaled goals, not what the board
    # payload contains, and this function's job is to predict the DOM, not the payload.
    #
    # Same defect family as the S-117a and S-118 fixes of the same day; this instance stayed
    # invisible because the perf suite gates on machine load and had not taken a real measurement
    # since the ruling landed. A gated suite hides regressions as effectively as a missing one.
    painted = [col for col in board_json["columns"] if col.get("vertical") is not None]
    return sum(count_subtree(g["id"]) for col in painted for g in col["goals"])


# A fourth instrumentation mechanism, outside E2E.md section 1's three-entry list: a buffered
# `layout-shift` PerformanceObserver feeding S-97's own CLS-after-paint check (AC-123). "Painted"
# itself is detected in measure_ui_paint via `page.wait_for_function` against a DOM node count,
# not this script — S-61's own shipped `wait_for_selector('[data-goal-id="SAMPLE01"]')` is the
# simpler precedent for that half; this scenario needs the *last* card via a computed count, not a
# known static id.
_LAYOUT_SHIFT_RECORDER_SCRIPT = """
(function () {
  window.__s97LayoutShifts = [];
  try {
    var po = new PerformanceObserver(function (list) {
      list.getEntries().forEach(function (entry) {
        window.__s97LayoutShifts.push({ startTime: entry.startTime, value: entry.value });
      });
    });
    po.observe({ type: 'layout-shift', buffered: true });
  } catch (e) {
    // Unsupported would read as "no shifts observed", not a crash -- moot: Chromium (this
    // suite's only browser) supports it.
  }
})();
"""


def measure_ui_paint(
    static_base_url: str, target_count: int, *, warmups: int, iterations: int
) -> tuple[list[float], list[int], list[str], list[dict], int]:
    """One browser/context/page, launched once, then `warmups + iterations` repeated `page.goto`
    navigations — mirrors `test_perf_transport_import.py`'s own S-95 shape
    (`_mcp_board_round_trips`): measures and
    returns plain data only, never calls `fail`/`gate` itself, and needs no pytest fixture in its
    own signature (independently callable — verified live via a throwaway scratchpad script that
    imported and called this function directly, bypassing `make test-perf`'s own load gate, to
    prove this scenario reaches a real browser without certifying a number on a loaded box).

    Each call: pin the clock (re-applied every iteration, not trusted to persist across
    `page.goto`), `page.goto(..., wait_until="commit")`, then `wait_for_function` polls (raf
    cadence, Playwright's own default) for >= `target_count` `[data-goal-id]` nodes.

    Returns `(paint_samples_ms, rendered_counts, console_errors, layout_shifts_after_paint,
    timeout_count)`. The first is `time_iterations`'s own wall-clock return value — every other
    row across this package's scenario files (S-91 through S-99, split between
    `test_perf_core_queries.py` and `test_perf_transport_import.py`) times the same way, never an
    in-page timestamp. The other four accumulate across *every* call including warmups, unsliced
    — S-91's own `exec_deltas` precedent: only the timing itself is warmup-discarded.
    """
    console_errors: list[str] = []
    rendered_counts: list[int] = []
    layout_shifts_after_paint: list[dict] = []
    timeouts = 0

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            context = browser.new_context(viewport=UI_VIEWPORT, reduced_motion="reduce")
            context.add_init_script(script=_LAYOUT_SHIFT_RECORDER_SCRIPT)
            page = context.new_page()
            page.on(
                "console",
                lambda msg: (
                    console_errors.append(f"[{msg.type}] {msg.text}")
                    if msg.type == "error" else None
                ),
            )

            def call() -> None:
                nonlocal timeouts
                page.clock.set_fixed_time(PINNED_CLOCK_ISO)
                page.goto(static_base_url, wait_until="commit")
                try:
                    page.wait_for_function(
                        "(n) => document.querySelectorAll('[data-goal-id]').length >= n",
                        arg=target_count, timeout=PAINT_TIMEOUT_MS,
                    )
                except PlaywrightTimeoutError:
                    # Not re-raised: time_iterations has no per-call exception handling (an
                    # uncaught exception here would abort the scenario with a bare traceback
                    # instead of a FAIL through _judge). This iteration's own wall-clock already
                    # reads ~10000ms by now, which alone correctly blows the 1500ms budget.
                    timeouts += 1
                    rendered_counts.append(
                        page.evaluate("document.querySelectorAll('[data-goal-id]').length")
                    )
                    return
                rendered_counts.append(
                    page.evaluate("document.querySelectorAll('[data-goal-id]').length")
                )
                paint_ref_ms = page.evaluate("performance.now()")
                shifts = page.evaluate("window.__s97LayoutShifts")
                layout_shifts_after_paint.extend(
                    s for s in shifts if s["startTime"] >= paint_ref_ms and s["value"] > 0
                )

            paint_samples = time_iterations(call, warmups=warmups, iterations=iterations)
        finally:
            browser.close()

    return paint_samples, rendered_counts, console_errors, layout_shifts_after_paint, timeouts


def build_checks(
    *,
    target_count: int,
    timeouts: int,
    rendered_counts: list[int],
    console_errors: list[str],
    layout_shifts_after_paint: list[dict],
) -> tuple[tuple[str, bool, str], ...]:
    """The four `_judge(..., checks=...)` entries S-97's own `docs/E2E.md` row requires beyond
    the budget: paint success within the probe timeout, exact rendered node count (a live
    cross-check of `count_dom_goal_nodes`), zero console errors, and zero layout shifts after
    paint (CLS = 0, AC-123). Kept alongside the measurement code it grades, not in
    test_perf_transport_import.py, for the same line-count reason this whole module exists —
    see the module docstring.
    """
    bad_counts = sorted({c for c in rendered_counts if c != target_count})
    total_calls = WARMUPS + ITERATIONS
    return (
        (
            f"last card painted (>= {target_count} nodes) within {PAINT_TIMEOUT_MS:.0f}ms, "
            f"every navigation",
            timeouts == 0,
            f"{timeouts}/{total_calls} navigation(s) never reached {target_count} "
            f"[data-goal-id] nodes within {PAINT_TIMEOUT_MS:.0f}ms.",
        ),
        (
            f"rendered [data-goal-id] count == {target_count} exactly, every navigation",
            not bad_counts,
            f"saw counts {bad_counts or '(none)'} among {len(rendered_counts)} navigations; "
            f"expected exactly {target_count} on every one.",
        ),
        (
            "zero console errors, every navigation",
            not console_errors,
            f"{len(console_errors)} console error(s) observed: {console_errors[:5]}",
        ),
        (
            "zero layout shifts after paint, every navigation (CLS = 0, AC-123)",
            not layout_shifts_after_paint,
            f"{len(layout_shifts_after_paint)} post-paint layout-shift entrie(s): "
            f"{layout_shifts_after_paint[:5]}",
        ),
    )
