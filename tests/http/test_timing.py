"""The two empirical proofs behind S-113 that S-113's own catalogued steps do not ask for.

Split out of `test_security.py`, which reached 755 lines — over the 750 the project rules set for
any module. The split is along the seam the code already had: `test_security.py` holds the three
tests that *claim* scenario ids (S-112, S-113, S-114) and do exactly what `E2E.md`'s "Steps:"
lists for them; this file holds the two that claim nothing and exist because
`IMPLEMENTATION.md` §4.1's WP-21 adversarial-review row asks for more rigor than the catalogue
does — "does the 401 body differ by token length" and "time 1000 wrong-token requests against
1000 right ones".

Neither test here may ever be renamed to `test_sNN_*`. `tests/harness/report.py::scenario_id_of`
turns the name into an acceptance claim, and what these assert is deliberately *beyond* AC-082's
literal assert column (a static check plus a log grep). They still run, still count toward the
suite verdict, and still print a naming notice — which is the mechanism working, not noise.
"""

from __future__ import annotations

import json
import os
import random
import secrets
import statistics
import subprocess
import sys
import time

import httpx
import pytest

from tests.harness.report import FailDetail, artifact, fail, gate
from tests.http.conftest import REPO_ROOT, TEST_OWNER, _free_port


def test_security_401_body_is_identical_regardless_of_presented_token_length(server) -> None:
    """"Check whether the 401 body differs by token length" (the reviewer's own hint). Every
    length below presents a well-formed but wrong bearer token — always the "invalid bearer
    token" branch, never the separate "missing bearer token" branch a fully-absent header would
    hit (a different message, unrelated to a length leak, that would break a naive "all
    identical" assertion for the wrong reason).

    `n=0` is not in the sweep: `Authorization: Bearer ` (nothing after the trailing space) is a
    value httpx/h11 itself refuses to put on the wire (`LocalProtocolError: Illegal header value
    b'Bearer '`, checked by hand) — a client-library strictness about trailing whitespace, not a
    server behaviour. `n=1` already stands in for "about as short as a wrong token gets".
    """
    raw = httpx.Client(base_url=server.base_url, timeout=10.0)
    try:
        bodies: set[bytes] = set()
        statuses: set[int] = set()
        for n in (1, 8, 63, 64, 65, 200, 4000):
            resp = raw.get(
                "/api/board",
                params={"date": "2026-08-08"},
                headers={"Authorization": "Bearer " + ("x" * n)},
            )
            statuses.add(resp.status_code)
            bodies.add(resp.content)
    finally:
        raw.close()
    assert statuses == {401}, f"expected every presented length to 401, got {statuses}"
    assert len(bodies) == 1, f"401 body varies by presented token length: {bodies}"


def _wrong_token(live: str, prefix_len: int, rng: random.Random) -> str:
    """Same length as `live`; identical for the first `prefix_len` characters, guaranteed to
    differ at position `prefix_len`, randomized after that. Isolates exactly one variable —
    how much of the true prefix a guess shares before diverging — from everything else that
    could make two requests take different amounts of time."""
    alphabet = "0123456789abcdef"
    chars = list(live[:prefix_len])
    for i in range(prefix_len, len(live)):
        original = live[i]
        pool = [c for c in alphabet if c != original] if i == prefix_len else alphabet
        chars.append(rng.choice(pool))
    return "".join(chars)


def _permutation_p_value(a: list[float], b: list[float], rng: random.Random, iterations: int = 2000) -> tuple[float, float]:
    """Two-sided Monte Carlo permutation test on the difference of medians. Stdlib-only —
    `DEPENDENCIES.md`'s allowlist has neither scipy nor numpy, and a permutation test needs
    nothing but reshuffling, unlike a t-test, which assumes a normal distribution that loopback
    HTTP latency never has (long right tail from GC pauses, scheduler noise, the odd xdist
    worker context switch)."""
    observed = statistics.median(a) - statistics.median(b)
    pooled = a + b
    na = len(a)
    at_least_as_extreme = 0
    for _ in range(iterations):
        rng.shuffle(pooled)
        shuffled = statistics.median(pooled[:na]) - statistics.median(pooled[na:])
        if abs(shuffled) >= abs(observed):
            at_least_as_extreme += 1
    return observed, at_least_as_extreme / iterations


def test_security_token_comparison_time_does_not_leak_prefix_length(
    request: pytest.FixtureRequest, f2_dsn: str
) -> None:
    """The empirical half of AC-082 ("constant-time"): S-113's static check proves
    `compare_digest` is *called*, not that its timing holds up from outside the process. ~1000
    wrong-token requests, bucketed by how much of the real token's prefix they share before
    diverging, interleaved in random order against ~1000 correct ones so time-of-run drift
    (thermal, GC, a neighbor agent's load) cannot correlate with bucket identity.

    Two comparisons, not one: every successful request also runs a real `core/board.py` query
    the rejected ones never reach, so right-vs-wrong latency is *expected* to differ for reasons
    that have nothing to do with `compare_digest`. That expected gap is the **positive control**
    — if this setup cannot detect "does a DB round trip" vs "does not", it has no business
    claiming it detected the *absence* of a far smaller gap, and the real question (wrong-token
    latency by prefix length, all rejected before any DB call) is gated rather than answered.
    """
    live_token = secrets.token_hex(32)
    port = _free_port()
    tmp_dir = REPO_ROOT / "artifacts" / "http" / "S-113"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    log_path = tmp_dir / "timing_server.log"
    env = dict(os.environ)
    env.update(
        VERTICALS_DATABASE_URL=f2_dsn,
        VERTICALS_TOKEN=live_token,
        VERTICALS_OWNER=TEST_OWNER,
        VERTICALS_BIND=f"127.0.0.1:{port}",
        VERTICALS_POOL_MIN="2",
        VERTICALS_POOL_MAX="10",
        VERTICALS_LOG_LEVEL="warning",
    )
    base_url = f"http://127.0.0.1:{port}"
    with open(log_path, "w") as logfile:
        proc = subprocess.Popen(
            [sys.executable, "-m", "verticals.api.app"],
            cwd=REPO_ROOT,
            env=env,
            stdout=logfile,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    try:
        deadline = time.monotonic() + 10.0
        healthy = False
        while time.monotonic() < deadline:
            if proc.poll() is not None:
                gate(f"timing server exited early; log tail:\n{log_path.read_text()[-1000:]}")
            try:
                if httpx.get(f"{base_url}/healthz", timeout=1.0).status_code == 200:
                    healthy = True
                    break
            except httpx.HTTPError:
                pass
            time.sleep(0.1)
        if not healthy:
            gate("timing server never became healthy within 10s")

        rng = random.Random(20260808)
        token_len = len(live_token)
        buckets = [0, token_len // 4, token_len // 2, (3 * token_len) // 4, token_len - 1]
        per_bucket = 200
        n_right = 1000

        plan: list[tuple[str, str]] = []  # (label, token)
        for prefix_len in buckets:
            wrong = _wrong_token(live_token, prefix_len, rng)
            plan += [(f"wrong_p{prefix_len}", wrong)] * per_bucket
        plan += [("right", live_token)] * n_right
        rng.shuffle(plan)

        client = httpx.Client(base_url=base_url, timeout=10.0)
        timings: dict[str, list[float]] = {}
        try:
            for label, token in plan:
                t0 = time.perf_counter()
                client.get(
                    "/api/board",
                    params={"date": "2026-08-08"},
                    headers={"Authorization": f"Bearer {token}"},
                )
                elapsed = time.perf_counter() - t0
                timings.setdefault(label, []).append(elapsed)
        finally:
            client.close()
    finally:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5.0)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=5.0)

    # S-113's own step 5 greps three boot-*refusal* runs, none of which ever holds a genuine
    # working secret (unset/empty/placeholder cannot leak what was never valid). This server is
    # the one place in this suite that boots successfully with a real, freshly-generated token
    # and serves ~2000 requests against it — the one path actually capable of demonstrating "the
    # token never appears in stdout/stderr/log/error body on any path including failures" for a
    # token that *is* live, not just refused. `live_token` never appears in this file's own
    # requests either — it rides in the `Authorization` header, which httpx does not log.
    server_log = log_path.read_text()
    assert live_token not in server_log, (
        f"the live token leaked into the server's own captured stdout/stderr — see {log_path}"
    )

    right = timings["right"]
    all_wrong = [t for label, ts in timings.items() if label != "right" for t in ts]
    zero_overlap = timings[f"wrong_p{buckets[0]}"]
    high_overlap = timings[f"wrong_p{buckets[-1]}"]

    rng2 = random.Random(9)
    control_diff, control_p = _permutation_p_value(right, all_wrong, rng2)
    experiment_diff, experiment_p = _permutation_p_value(high_overlap, zero_overlap, rng2)

    summary = {
        "buckets_us": {
            label: {
                "median_us": round(statistics.median(ts) * 1e6, 1),
                "mean_us": round(statistics.mean(ts) * 1e6, 1),
                "stdev_us": round(statistics.stdev(ts) * 1e6, 1) if len(ts) > 1 else 0.0,
                "n": len(ts),
            }
            for label, ts in sorted(timings.items())
        },
        "positive_control_right_vs_wrong": {
            "median_diff_us": round(control_diff * 1e6, 1),
            "p_value": control_p,
        },
        "experiment_high_vs_zero_prefix_overlap": {
            "median_diff_us": round(experiment_diff * 1e6, 1),
            "p_value": experiment_p,
        },
    }
    summary_path = tmp_dir / "timing_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2))
    artifact(request, str(summary_path.relative_to(REPO_ROOT)))
    print(f"\ntiming summary ({summary_path}):\n{json.dumps(summary, indent=2)}")

    # Negligible in absolute terms regardless of statistical significance: at high sample counts
    # a permutation test can call a real but microscopic difference "significant" while it is
    # still far below anything exploitable one HTTP round trip at a time over a network. 300us
    # is comfortably above this box's measured jitter floor and comfortably below "attacker can
    # use this" — see the reported numbers for the actual figures, this constant only decides
    # PASS/FAIL/GATE, never what gets printed.
    negligible_us = 300.0

    if abs(control_diff * 1e6) < negligible_us or control_p > 0.05:
        gate(
            "positive control (real DB round trip vs rejected-before-DB) did not show a clear "
            f"latency gap on this run — the measurement is not sensitive enough right now to "
            f"trust its negative result either. {summary}"
        )

    if abs(experiment_diff * 1e6) >= negligible_us and experiment_p < 0.01:
        fail(
            FailDetail(
                scenario_id="S-113",  # informational only — this test's own name claims no id
                suite="http",
                name="token_comparison_time_does_not_leak_prefix_length",
                file=str(THIS_FILE),
                assert_expr="median(high-prefix-overlap wrong) - median(zero-overlap wrong) ~ 0",
                expected=f"< {negligible_us}us or p > 0.01",
                actual=f"{experiment_diff * 1e6:.1f}us, p={experiment_p}",
                detail=str(summary),
                artifact=str(summary_path.relative_to(REPO_ROOT)),
            )
        )
