"""Shared judging machinery for suite F (`perf`) — every `test_s9X_...` scenario in this
package's scenario files calls `_judge` at teardown (percentiles, write the artifact, evaluate
against the committed baseline and the row's own hard invariants; see `_judge`'s own docstring
below for the exact order and why). Split out of `tests/perf/test_perf.py` on line-count grounds
(`docs/PENDING_DOC_FIXES.md` row 76 — `ARCHITECTURE.md` §2's 750-line cap, `make lint` failing at
799 lines) alongside the two scenario files that both call it, `tests/perf/test_perf_core_queries.py`
and `tests/perf/test_perf_transport_import.py`: kept in one place here rather than duplicated into
each, matching this package's existing precedent for a split-out shared module
(`tests/perf/s97_ui_paint.py`, split out of the same original file for the same reason before this
one existed).
"""

from __future__ import annotations

import pytest

from tests.harness import calibrate
from tests.harness.report import FailDetail, artifact, fail
from tests.perf.conftest import REPO_ROOT, record_passed_absolute, write_artifact


def _location(request: pytest.FixtureRequest) -> str:
    """`tests/conftest.py`'s own `pytest_runtest_makereport` idiom, reused verbatim: pytest's
    `location` is 0-indexed, `FailDetail.file` wants a human line number."""
    file, lineno, _ = request.node.location
    line = lineno + 1 if lineno is not None else 0
    return f"{file}:{line}"


def _judge(
    request: pytest.FixtureRequest,
    *,
    scenario_id: str,
    samples: list[float],
    budget_ms: float,
    stat_name: str,
    checks: tuple[tuple[str, bool, str], ...] = (),
    extra_artifact: dict | None = None,
) -> calibrate.Verdict:
    """Every gating scenario's shared teardown (`docs/E2E.md` section 8's own "steps for every
    row"): percentiles, write the artifact, evaluate against the committed baseline, assert the
    row's own extra hard invariants first (a wrong or partial answer matters more than a slow
    one), then the absolute budget, then the relative-drift gate — in that order, because
    `fail()` raises on the first one it reaches and a reader should see the most fundamental
    problem, not whichever happened to be checked last. A pass — including a pass with no
    committed baseline yet, `calibrate.py`'s own "GATE on the relative half, PASS on the
    absolute half alone" case — records this scenario's value into the whole-session dict
    `pytest_sessionfinish` seeds a first-ever baseline from.
    """
    name = request.node.name
    file = _location(request)
    stats = calibrate.percentiles(samples)
    value_ms = stats[stat_name]

    baseline = calibrate.load_baseline()
    verdict = calibrate.evaluate(
        scenario_id, stat_name=stat_name, value_ms=value_ms, budget_ms=budget_ms, baseline=baseline
    )

    artifact_payload = {
        **stats,
        "stat_name": stat_name,
        "budget_ms": budget_ms,
        "within_budget": verdict.within_budget,
        "within_relative": verdict.within_relative,
        "baseline_ms": verdict.baseline_ms,
        "gate_reason": verdict.gate_reason,
        "machine_id": calibrate.machine_id(),
        **(extra_artifact or {}),
    }
    path = write_artifact(scenario_id, artifact_payload, samples)
    artifact(request, str(path.relative_to(REPO_ROOT)))
    print(verdict.render())
    if verdict.gate_reason:
        print(f"{scenario_id}: {verdict.gate_reason}")

    for expr, ok, detail in checks:
        if not ok:
            fail(FailDetail(
                scenario_id=scenario_id, suite="perf", name=name, file=file,
                assert_expr=expr, expected="true on every iteration",
                actual="false on at least one iteration", detail=detail,
                artifact=str(path.relative_to(REPO_ROOT)),
            ))

    if not verdict.within_budget:
        fail(FailDetail(
            scenario_id=scenario_id, suite="perf", name=name, file=file,
            assert_expr=f"{stat_name} <= budget_ms",
            expected=f"<= {budget_ms:.2f}ms", actual=f"{value_ms:.2f}ms",
            detail=(
                f"absolute budget exceeded on {calibrate.machine_id()}; full distribution "
                f"(n={stats['count']}) in the artifact."
            ),
            artifact=str(path.relative_to(REPO_ROOT)),
        ))

    if verdict.within_relative is False:
        fail(FailDetail(
            scenario_id=scenario_id, suite="perf", name=name, file=file,
            assert_expr=f"{stat_name} <= 1.5 x baseline_{stat_name}",
            expected=(
                f"<= {calibrate.RELATIVE_FACTOR * verdict.baseline_ms:.2f}ms "
                f"(1.5x baseline {verdict.baseline_ms:.2f}ms)"
            ),
            actual=f"{value_ms:.2f}ms",
            detail=(
                f"relative-drift gate failed against the committed baseline for "
                f"{calibrate.machine_id()} (docs/E2E.md section 8's calibration rule)."
            ),
            artifact=str(path.relative_to(REPO_ROOT)),
        ))

    if verdict.within_budget:
        record_passed_absolute(request, scenario_id, value_ms)

    return verdict
