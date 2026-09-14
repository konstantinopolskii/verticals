"""The `1.5 x baseline` rule — `docs/E2E.md` section 8 "Calibration rule"; `docs/IMPLEMENTATION.md`
WP-20 card, "The baseline is tracked, per machine, and is not an artifact."

**Where the baseline lives, and why not where the other two documents say.** `docs/E2E.md`
section 8 and `ACCEPTANCE.md` AC-097 both write it to `artifacts/perf/baseline.json` — but
AC-152 gitignores `artifacts/**`, so under both rules at once the relative gate would compare
every run against a file created that same run, which can never regress. The WP-20 card resolves
this: the baseline is COMMITTED, at `tests/perf/baseline.<machine-id>.json`, where `<machine-id>`
is `platform.machine() + '-' + platform.system()` — literally that concatenation, no separator
logic beyond the one hyphen. Per-run distributions still go to `artifacts/perf/<S-id>.json`,
gitignored, exactly as both other documents say — only the baseline's own location moves.

**Never silently re-cut.** A committed baseline file is never written to by this module once it
exists — re-cutting one is a deliberate commit whose message says so (a human action), not a side
effect of a green test run. The one exception, matching the WP-20 card's own "Done when" clause
("the baseline file is written by the first green run"), is a machine with no committed baseline
at all: `maybe_seed_baseline` writes a brand new file, once, seeded with whatever this run
actually measured. A machine that already has one is never touched by this module again.

A run on a machine with no committed baseline reports GATE on the relative half and PASS on the
absolute budget alone — never silently treated as either an automatic pass or an automatic fail.
"""

from __future__ import annotations

import json
import math
import platform
from dataclasses import dataclass
from pathlib import Path

PERF_DIR = Path(__file__).resolve().parents[1] / "perf"
RELATIVE_FACTOR = 1.5  # docs/E2E.md section 8's own number, named, never inlined a second time

# `docs/E2E.md` section 8 states the measurement precondition — "Page cache warm, no other load,
# and the `perf` suite runs **alone**" — and gives its own reason: "a p95 measured next to twelve
# parallel `core` workers is a number about the scheduler." The runner enforces the third clause
# (no sibling suite holds workers). Nothing enforced the second, which is the one that actually
# bit: a `make test-perf` left running beside two working agents reported S-91 at p95 10.03-11.19ms
# against a 10ms budget at load average 3.4+ on this 10-core box — roughly 10% inflation, enough to
# turn a passing budget into a FAIL that is, in the spec's own words, a number about the scheduler.
#
# So this fraction is a heuristic with a stated basis, not a measured constant: 0.25 x cores admits
# a box carrying the suite itself plus its Postgres and little else (2.5 on the 10-core machine
# section 8 names), and refuses the 3.4 that demonstrably inflated a real measurement. It gates,
# never fails — an unquiet box means the number was not taken under the stated conditions, which
# is a refusal to certify in either direction, not evidence of a regression.
LOAD_FRACTION = 0.25


def machine_id() -> str:
    """`platform.machine() + '-' + platform.system()` — the WP-20 card's own exact formula.
    Deliberately coarser than a full machine description (no CPU model, no OS version): the
    baseline is meant to survive an OS point upgrade on the same box, and a mismatch there is
    the relative gate's job to catch via drift, not this function's job to detect by naming it."""
    return f"{platform.machine()}-{platform.system()}"


def load_ceiling(cores: int) -> float:
    """The 1-minute load average at or below which this box is quiet enough to measure on.
    One function so the fixture that waits for the box to settle and the check that refuses to
    measure cannot drift apart on what "quiet" means."""
    return LOAD_FRACTION * max(1, cores)


def load_gate_reason(load1: float, cores: int) -> str | None:
    """The sentence to GATE a perf run with, or `None` when the box is quiet enough to measure on.

    Pure, so both directions are provable without arranging real machine load: a test can hand it
    a saturated box and see it refuse, and hand it an idle one and see it stay silent. That matters
    more here than in most rules — a precondition check only ever observed passing is
    indistinguishable from one that cannot fire, and this one is *meant* to fire rarely.

    `cores < 1` is treated as one core rather than raised on: `os.cpu_count()` is documented to
    return `None` when it cannot tell, and a callable precondition check that explodes on an
    unusual host is worse than one that reads that host as a single-core box and gates sooner.
    """
    ceiling = load_ceiling(cores)
    if load1 <= ceiling:
        return None
    return (
        f"box is not quiet enough to measure on: 1-minute load average {load1:.2f} exceeds "
        f"{LOAD_FRACTION} x {max(1, cores)} cores = {ceiling:.2f}. docs/E2E.md section 8 measures "
        f"under 'no other load'; a p95 taken here is, in that section's own words, a number about "
        f"the scheduler. This is not a regression signal in either direction — no measurement was "
        f"taken. To certify: run on a host with no interactive desktop session (log out, or use a "
        f"headless box) and re-run `make test-perf` alone. On a workstation with the GUI live the "
        f"idle load average alone can exceed this ceiling, so closing individual applications is "
        f"usually not enough. Do not raise LOAD_FRACTION to get past this: see section 8, "
        f"'No other load means no desktop session'."
    )


def baseline_path(machine: str | None = None) -> Path:
    return PERF_DIR / f"baseline.{machine or machine_id()}.json"


def load_baseline(machine: str | None = None) -> dict[str, float] | None:
    """`{scenario_id: gate-statistic in ms}` read from the committed file for this machine, or
    `None` when this machine has never had one committed. Never raises on a missing file — every
    caller must treat that as the GATE case (`evaluate` below), not an error."""
    path = baseline_path(machine)
    if not path.is_file():
        return None
    return json.loads(path.read_text())


def percentiles(samples: list[float]) -> dict[str, float]:
    """p50/p95/p99/max plus the sample count (`docs/E2E.md` section 8: "write p50/p95/p99/max
    plus the sample count"). Nearest-rank: the smallest sample whose rank covers the requested
    fraction — simple, deterministic, no interpolation to explain. `samples` need not be sorted."""
    if not samples:
        raise ValueError("percentiles: samples must be non-empty")
    ordered = sorted(samples)
    n = len(ordered)

    def _rank(p: float) -> float:
        idx = max(0, min(n - 1, math.ceil(p * n) - 1))
        return ordered[idx]

    return {
        "p50": _rank(0.50), "p95": _rank(0.95), "p99": _rank(0.99),
        "max": ordered[-1], "min": ordered[0], "count": n,
    }


@dataclass(frozen=True)
class Verdict:
    """One scenario row's calibration result. `passed` folds both gates per the WP-20 card's own
    rule: the absolute budget always gates; the relative 1.5x check gates too, but only counts
    against `passed` when a baseline actually exists to compare against — its absence is recorded
    (`gate_reason`) and left out of the pass/fail decision, never silently read either way."""

    scenario_id: str
    stat_name: str  # "p95" or "max" — which statistic gates this row (docs/E2E.md section 8)
    value_ms: float
    budget_ms: float
    baseline_ms: float | None
    within_budget: bool
    within_relative: bool | None  # None when baseline_ms is None — nothing to compare
    gate_reason: str | None

    @property
    def passed(self) -> bool:
        return self.within_budget and self.within_relative is not False

    def render(self) -> str:
        rel = (
            "no committed baseline" if self.baseline_ms is None
            else f"{self.value_ms:.2f}ms <= {RELATIVE_FACTOR}x{self.baseline_ms:.2f}ms = "
                 f"{RELATIVE_FACTOR * self.baseline_ms:.2f}ms: {self.within_relative}"
        )
        return (
            f"{self.scenario_id}: {self.stat_name}={self.value_ms:.2f}ms  "
            f"budget<= {self.budget_ms:.2f}ms: {self.within_budget}  relative: {rel}"
        )


def evaluate(
    scenario_id: str, *, stat_name: str, value_ms: float, budget_ms: float,
    baseline: dict[str, float] | None,
) -> Verdict:
    """`baseline` is the whole-file dict `load_baseline` returned (or `None`) — passed in rather
    than re-read per scenario, so one file read serves every row in a suite run."""
    within_budget = value_ms <= budget_ms
    prior = baseline.get(scenario_id) if baseline is not None else None
    if prior is None:
        return Verdict(
            scenario_id, stat_name, value_ms, budget_ms, None, within_budget, None,
            gate_reason=(
                f"no committed baseline for {scenario_id} on {machine_id()} at "
                f"{baseline_path()} — relative gate cannot run; write one via "
                f"maybe_seed_baseline after a green absolute-budget run"
            ),
        )
    within_relative = value_ms <= RELATIVE_FACTOR * prior
    return Verdict(scenario_id, stat_name, value_ms, budget_ms, prior, within_budget, within_relative, None)


def maybe_seed_baseline(results: dict[str, float], *, machine: str | None = None) -> Path | None:
    """Write `tests/perf/baseline.<machine-id>.json` if and only if it does not already exist —
    "the baseline file is written by the first green run" (WP-20 card's own done-when clause),
    and never again after that: an existing file is never opened for writing by this function,
    which is what "never silently re-cut" means in code rather than in prose. `results` should
    hold only scenarios that actually measured and passed their absolute budget this run — a
    GATEd or FAILed scenario has no legitimate number to seed a future comparison with.

    Returns the path written, or `None` when a baseline already existed and nothing was touched.
    Written but never committed by this module — `git add`/`git commit` is a human action
    (house law: no autosave-by-side-effect on a file meant to be reviewed before it binds)."""
    path = baseline_path(machine)
    if path.is_file():
        return None
    if not results:
        return None
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(dict(sorted(results.items())), indent=2) + "\n")
    return path
