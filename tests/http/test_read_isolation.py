"""S-41 (no existence oracle across owners) and S-42 (ancestor chain), docs/E2E.md §4."""

from __future__ import annotations

import os
import statistics
import time

import httpx

from tests.harness import calibrate
from tests.harness.report import gate

ANCESTORS_ROOT_TO_PARENT = ["SYNLIF01", "SYNDEC01", "SYNYRR01", "SYNQ1R01", "SYNQ2R01", "SYNDAY01"]


def _measure_paired(client: httpx.Client, n: int = 200) -> tuple[float, float]:
    """`n` paired requests, interleaved A/B so machine drift (a GC pause, a scheduler quantum)
    hits both series roughly equally rather than accumulating in whichever ran second in a
    blocked-by-series design. Returns `(median_unknown, median_foreign)` in seconds."""
    unknown_times: list[float] = []
    foreign_times: list[float] = []
    for _ in range(n):
        t0 = time.perf_counter()
        client.get("/api/goals/ZZZZZZZZ")
        unknown_times.append(time.perf_counter() - t0)

        t0 = time.perf_counter()
        client.get("/api/goals/SYNOTH01")
        foreign_times.append(time.perf_counter() - t0)
    return statistics.median(unknown_times), statistics.median(foreign_times)


def test_s41_unknown_and_foreign_owner_id_both_404(client: httpx.Client) -> None:
    unknown = client.get("/api/goals/ZZZZZZZZ")
    foreign = client.get("/api/goals/SYNOTH01")  # exists, but under owner t2
    assert unknown.status_code == 404
    assert foreign.status_code == 404
    assert unknown.content == foreign.content, "404 bodies must be byte-identical — no oracle"

    # Everything above is the actual security contract and is asserted unconditionally: both ids
    # 404, and the two bodies are byte-identical. What follows is a MEASUREMENT, and §8's own rule
    # applies to it — "a p95 measured next to twelve parallel `core` workers is a number about the
    # scheduler". So it takes the same load gate the `perf` suite uses, for the same reason (D94):
    # in a full run this scenario executes beside S-112's nested second copy of this whole suite,
    # and it reported a 3.170 ms delta against a 2 ms bar there while passing on a quiet box. A
    # timing oracle that fails on the suite's own load teaches a reader to ignore it — which is
    # precisely how D90 stayed hidden. GATE is a refusal to certify in either direction, not a pass.
    if (reason := calibrate.load_gate_reason(os.getloadavg()[0], os.cpu_count() or 1)) is not None:
        gate(f"S-41's timing half cannot be measured here — {reason}")

    # §8's calibration rule, applied to a timing gate outside the `perf` suite (E2E.md §4's own
    # "timing assertions in this suite" note): a threshold breach is re-run once before being
    # reported, never reported cold off a single noisy sample.
    last_delta_ms: float = float("inf")
    for _attempt in range(2):
        med_unknown, med_foreign = _measure_paired(client)
        last_delta_ms = abs(med_unknown - med_foreign) * 1000
        if last_delta_ms < 2.0:
            break
    assert last_delta_ms < 2.0, f"median(unknown) - median(foreign) = {last_delta_ms:.3f} ms, >= 2ms twice"


def test_s42_goal_detail_carries_the_ancestor_chain(client: httpx.Client) -> None:
    resp = client.get("/api/goals/SYNSUB01")
    assert resp.status_code == 200
    body = resp.json()

    ancestors = body["ancestors"]
    assert [a["id"] for a in ancestors] == ANCESTORS_ROOT_TO_PARENT
    for a in ancestors:
        assert "title" in a and "vertical" in a

    assert body["children"] == []
    # D250/WP-1: the route now also reads `core.docs.links_for_goal()` for the response's `docs`
    # field (`routes_goals.py::get_goal`'s own docstring) — one more statement on top of
    # `core.goals.goal()`'s own two, deliberately a separate call rather than folded into that
    # query (the spec's own words: the field is populated "via links_for_goal", a `core/docs.py`
    # verb `core/goals.py` does not, and should not, inline SQL for). Budget raised from 2 to 3
    # to match, not silently widened — every request still costs exactly 3, asserted below.
    assert int(resp.headers["x-query-count"]) <= 3
