"""The perf suite's "no other load" precondition, proved to fire and proved to stay silent.

`docs/E2E.md` §8 states the conditions its budgets are meaningful under — "Page cache warm, no
other load, and the `perf` suite runs **alone**" — and gives the reason in its own words: "a p95
measured next to twelve parallel `core` workers is a number about the scheduler." The runner
enforced the third clause and nothing enforced the second, which is the one that bit: S-91 was
reported at p95 10.03-11.19ms against a 10ms budget on a box at load average 3.4+, a FAIL that
described the run queue rather than `core/board.py`.

**Why this file is in `static` and not in `perf`.** It verifies a gate that blocks the `perf`
suite. Living inside that suite, it would be held out by the very check it exists to test — the
run where the gate fires is exactly the run where these assertions would never execute, so the
rule could only ever be observed passing. `tests/harness/report.py::suite_of` derives the suite
from the path segment after `tests/`, so this file attributes to `static`, which needs no database
and no quiet machine. It reads a module and calls a pure function: squarely that suite's shape.

No test here claims a scenario id. §8's nine rows (S-91..S-99) are the measurements; this is the
precondition beneath them, which the catalogue names in prose and gives no id of its own.
"""

from __future__ import annotations

import ast
import inspect
import os
import textwrap

import pytest

import tests.perf.conftest as perf_conftest
from tests.harness import calibrate
from tests.harness.report import Gated, gate


def _raw(fixture) -> object:
    """The undecorated function behind a `@pytest.fixture`. `__wrapped__` is the stdlib
    convention and is what `inspect` itself follows, so it is tried first; `_get_wrapped_function`
    is pytest 8.4's own accessor and stands behind it for the case where that convention changes.
    Failing loudly beats silently testing nothing if a future pytest drops both."""
    if hasattr(fixture, "__wrapped__"):
        return fixture.__wrapped__
    if hasattr(fixture, "_get_wrapped_function"):
        return fixture._get_wrapped_function()
    raise AssertionError(
        f"cannot reach the function behind {fixture!r} — this file's wiring proof would "
        f"otherwise pass without executing the gate it claims to test"
    )


# --- the decision itself: both directions -----------------------------------------------------


def test_load_gate_stays_silent_on_a_quiet_box() -> None:
    """The false-positive guard. A gate that fires on an idle machine would make the perf suite
    unrunnable and would be discovered as noise, not as a bug — so the silent direction is
    asserted as deliberately as the loud one."""
    assert calibrate.load_gate_reason(0.0, 10) is None
    assert calibrate.load_gate_reason(1.0, 10) is None
    # Exactly at the ceiling: `load1 <= ceiling` is the comparison, so the boundary is quiet.
    # Pinned because an off-by-one here turns a documented threshold into a different one.
    assert calibrate.load_gate_reason(calibrate.LOAD_FRACTION * 10, 10) is None


def test_load_gate_refuses_the_load_that_actually_corrupted_a_measurement() -> None:
    """The planted violation, using the real numbers rather than an invented pair: load average
    3.4 on the 10-core box §8 names is what produced S-91's 10.03-11.19ms against a 10ms budget.
    The reason string must name both the observed load and the ceiling it broke — a gate that
    says only "too noisy" sends the reader back to guess what it measured."""
    reason = calibrate.load_gate_reason(3.4, 10)
    assert reason is not None, "the load that inflated a real p95 by ~10% must not read as quiet"
    assert "3.40" in reason and "2.50" in reason, reason
    assert "docs/E2E.md" in reason, "a gate should cite the rule it enforces"


def test_load_gate_reads_an_unknowable_core_count_as_a_single_core() -> None:
    """`os.cpu_count()` is documented to return `None`, and the caller passes `or 1`; this covers
    the other direction — a hostile or nonsensical value reaching the function directly. Gating
    sooner on a host whose size cannot be established is the safe way to be wrong."""
    assert calibrate.load_gate_reason(0.1, 1) is None
    for cores in (0, -4):
        assert calibrate.load_gate_reason(0.1, cores) is None, cores
        reason = calibrate.load_gate_reason(5.0, cores)
        assert reason is not None and "1 cores" in reason, f"cores={cores}: {reason}"


# --- the wiring: the decision is connected to the suite it guards -------------------------------


def test_perf_suite_gate_is_session_scoped_and_autouse() -> None:
    """A correct decision behind a fixture nothing requests protects nothing. Session scope is
    load-bearing beyond tidiness: it decides once, before the first corpus is built, so an unquiet
    box does not spend a minute loading F4-56700 to produce a number that gets thrown away."""
    marker = perf_conftest._box_is_quiet_enough_to_measure_on._fixture_function_marker
    assert marker.autouse is True
    assert marker.scope == "session"


def test_perf_suite_gate_raises_gated_when_the_box_is_loud() -> None:
    """The loud direction, through the real function the fixture calls, with real arguments — no
    stand-in for any component (AC-085, and `tests/static/test_no_mocks.py` enforces it; an
    earlier draft of this file reached for `monkeypatch` and that rule correctly refused it).

    `Gated` specifically, not any exception: `tests/conftest.py`'s report hook keys on that type
    to turn the outcome into GATE, and anything else surfaces as an ERROR the runner counts under
    `fail` — the exact confusion this mechanism exists to prevent."""
    with pytest.raises(Gated) as excinfo:
        perf_conftest.gate_unless_quiet(3.4, 10)
    assert "3.40" in excinfo.value.reason and "2.50" in excinfo.value.reason


def test_perf_suite_gate_lets_a_quiet_box_through() -> None:
    """The silent direction through the same path — otherwise the test above is equally satisfied
    by a function that raises unconditionally, which would block the suite forever."""
    assert perf_conftest.gate_unless_quiet(0.5, 10) is None


def test_perf_suite_gate_actually_calls_the_decision() -> None:
    """That the fixture *consults* the rule, asserted structurally rather than behaviourally.

    Behaviour alone cannot establish this on a quiet box: a correct gate staying silent and a
    fixture that does nothing at all are the same observation. Found the hard way — a planted
    no-op fixture passed every behavioural check in this file, because the machine happened to be
    below the ceiling at the time. So the connection is read out of the function's own body: it
    must contain a call to `gate_unless_quiet`, and must obtain both arguments from the live
    machine (`loadavg1()` and `os.cpu_count()`) rather than from constants that would make the
    gate decorative on every box but the one it was written on.
    """
    tree = ast.parse(textwrap.dedent(inspect.getsource(_raw(perf_conftest._box_is_quiet_enough_to_measure_on))))
    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)]
    called = {n.func.id for n in calls if isinstance(n.func, ast.Name)}
    attr_called = {n.func.attr for n in calls if isinstance(n.func, ast.Attribute)}

    assert "wait_for_quiet_then_gate" in called, (
        f"the perf gate fixture never calls wait_for_quiet_then_gate; it calls {called | attr_called}"
    )
    assert "cpu_count" in attr_called, "the gate must read this machine's core count, not a constant"

    # And that the thing it calls does reach the decision, rather than being a well-named no-op.
    waiter = ast.parse(textwrap.dedent(inspect.getsource(perf_conftest.wait_for_quiet_then_gate)))
    waiter_calls = {n.func.id for n in ast.walk(waiter) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    assert "gate_unless_quiet" in waiter_calls, waiter_calls
    assert "loadavg1" in waiter_calls, "the gate must read this machine's load, not a constant"


def test_perf_suite_gate_reads_this_machine_and_agrees_with_its_own_rule() -> None:
    """The remaining link: the fixture asks about *this* box rather than deciding on constants.
    Executed against the live machine, so the expected outcome is computed from the same readings
    rather than asserted as a literal — on a quiet box the fixture must return, on a loud one it
    must raise, and which of those is correct depends on the machine running this file.

    Load moves between the two samples, so a run sitting within 10% of the ceiling proves nothing
    either way and says so instead of flipping a coin — a flaky assertion here would be read as a
    broken gate and eventually deleted.

    That undecidable case GATEs rather than skips, and the difference is not cosmetic. This
    harness has no notion of a legitimate skip: `tests/harness/runner.py` fails the whole verdict
    on one ("the catalogue has no skippable scenarios"), which is right — a skipped scenario is a
    scenario nobody checked, wearing green. A GATE says the same thing the skip meant, in the
    vocabulary the runner actually has: this run refused to certify, and that is not a pass.
    Found by running it — the full suite at `764fded` reported `VERDICT: FAIL (skip=1)` with
    every other check green, on a box whose load happened to sit at 2.48 against a 2.50 ceiling.
    """
    cores = os.cpu_count() or 1
    ceiling = calibrate.load_ceiling(cores)
    load1 = perf_conftest.loadavg1()
    assert load1 >= 0.0, f"loadavg1() returned something impossible: {load1}"

    if abs(load1 - ceiling) < 0.1 * ceiling:
        gate(
            f"load {load1:.2f} sits within 10% of the {ceiling:.2f} ceiling, so this machine "
            f"cannot decide the question either way right now — the reading the fixture takes "
            f"would be a different sample from this one. Not a regression signal; re-run when "
            f"the box is clearly idle or clearly busy."
        )

    # `settle_timeout=0`: decide on the current reading. The shipped default waits up to three
    # minutes for a hot box to go quiet, which is right for a real run and would make this
    # assertion a three-minute hang on any loaded machine.
    if load1 > ceiling:
        with pytest.raises(Gated):
            perf_conftest.wait_for_quiet_then_gate(cores, settle_timeout=0.0)
    else:
        assert perf_conftest.wait_for_quiet_then_gate(cores, settle_timeout=0.0) is None
