"""S-124 — the runner judges its own run. `docs/E2E.md` §7c; run by `make test-harness`
(`Makefile`: plain `pytest tests/harness -q`, never through `tests.harness.runner` itself, which
is what keeps this from recursing into the thing it is testing).

Two unrelated jobs live in this one file, both assigned to WP-06 by the IMPLEMENTATION.md card:

  * `test_s124_runner_output_is_self_consistent` runs `make test` for real, as a subprocess, and
    applies `docs/E2E.md` §12 "How an agent decides pass or fail" to its own output — the same
    four rules a human or agent would apply reading the same transcript by hand.
  * `test_catalogue_index` delegates to `tests/harness/catalogue_index.py`, which WP-02 owns
    (`docs/IMPLEMENTATION.md`'s shared-file rule). This file imports and asserts it, never
    reimplements it. `run_all()` returns one `(name, ok, message)` triple per check — one more
    field than the `(ok, message)` pair this file was originally briefed to expect — so the
    unpacking below is `name, ok, m`, not the briefed `ok, m`; kept here rather than silently
    matching the brief because the extra name is what makes a failure here namable at all.

`test_stmt_scoping_has_no_cross_worker_talk` is this WP's own done-when, not part of S-124's own
Assert list — kept as a separate test so a future failure names the invariant that actually broke
(IR-06's dbid scoping) rather than landing inside S-124's already-large blast radius.
"""

from __future__ import annotations

import concurrent.futures
import json
import subprocess
from pathlib import Path

import psycopg

from tests import conftest
from tests.harness import stmt
from tests.harness.catalogue_index import run_all
from tests.harness.report import gate

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_s124_runner_output_is_self_consistent():
    """Required by AC-088, AC-089, AC-090, AC-091. Runs the real `make test`, cwd repo root, and
    reads its stdout/exit code exactly as printed — no re-parsing a second, private code path."""
    proc = subprocess.run(
        ["make", "test"], cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=900
    )
    out = proc.stdout
    lines = out.splitlines()

    # Rule 1: a VERDICT: line exists, and there is exactly one.
    verdict_lines = [ln for ln in lines if ln.startswith("VERDICT:")]
    assert len(verdict_lines) == 1, (
        f"expected exactly one VERDICT: line, found {len(verdict_lines)}\n--- stdout ---\n{out}"
        f"\n--- stderr ---\n{proc.stderr}"
    )
    verdict_pass = verdict_lines[0].startswith("VERDICT: PASS")

    # Rule 3: exit code must agree with the verdict (0 PASS / 1 FAIL / 2 harness error).
    if verdict_pass:
        assert proc.returncode == 0, f"VERDICT: PASS but exit={proc.returncode}, not 0\n{out}"
    else:
        assert proc.returncode in (1, 2), (
            f"verdict not PASS but exit={proc.returncode}, not 1 or 2\n{out}"
        )

    # The suite table: header, N suite rows, a TOTAL row. Parsed from the literal columns
    # tests/harness/runner.py prints — this test reads the same block a human would.
    header_idx = next(i for i, ln in enumerate(lines) if ln.strip().startswith("suite "))
    total_idx = next(i for i, ln in enumerate(lines) if ln.startswith("TOTAL"))
    suite_rows = [
        ln.split() for ln in lines[header_idx + 1 : total_idx] if ln.strip() and not ln.startswith("-")
    ]
    total_fields = lines[total_idx].split()
    total, passed, failed, skipped, gated = (int(x) for x in total_fields[1:6])

    # Rule 4: skip > 0 is always a FAIL — the catalogue has no skippable scenarios.
    if skipped > 0:
        assert not verdict_pass, f"skip={skipped} but VERDICT: PASS\n{out}"

    # AC-088/AC-089: the printed suite rows sum to the printed TOTAL row — self-consistency
    # between the table and results.jsonl, not literal agreement with docs/E2E.md §1's final
    # 134-scenario catalogue, which this wave has not finished building.
    summed = [0, 0, 0, 0, 0]
    for row in suite_rows:
        for i in range(5):
            summed[i] += int(row[i + 1])
    assert summed == [total, passed, failed, skipped, gated], (
        f"suite rows sum to {summed}, TOTAL row says {[total, passed, failed, skipped, gated]}\n{out}"
    )

    # artifacts/results.jsonl: one object per registered scenario, no duplicate ids, count
    # agrees with the printed TOTAL, and every record has exactly the fields this run promises.
    results_path = REPO_ROOT / "artifacts" / "results.jsonl"
    assert results_path.exists(), f"{results_path} was not written by the run above"
    records = [json.loads(ln) for ln in results_path.read_text().splitlines() if ln.strip()]
    ids = [r["id"] for r in records]
    dupes = sorted({i for i in ids if ids.count(i) > 1})
    assert not dupes, f"duplicate scenario id(s) in results.jsonl: {dupes}"
    assert len(records) == total, f"results.jsonl has {len(records)} record(s), TOTAL says {total}"
    for r in records:
        assert set(r) == {"id", "suite", "status", "duration_s", "artifacts"}, r
        assert r["status"] in ("pass", "fail", "gate", "skip"), r

    # This WP's own leak audit: a full run must not leave a clone behind. Templates
    # (verticals_tmpl_*) are infrastructure and are expected to survive — see
    # tests/conftest.py's drop_leaked_clones().
    leaked = [n for n in conftest.list_test_databases() if n.startswith(f"{conftest.TEST_DB_PREFIX}_")]
    assert not leaked, f"clone database(s) leaked past the run's own cleanup sweep: {leaked}"


def test_catalogue_index():
    failures = [f"{name}: {m}" for name, ok, m in run_all() if not ok]
    assert not failures, "\n".join(failures)


def test_stmt_scoping_has_no_cross_worker_talk():
    """This WP's own done-when: "a two-worker probe shows no statement-counter cross-talk —
    two workers reset and read concurrently against their own clones and each sees only its own
    statements." Two real clones, two real threads: psycopg releases the GIL on the network
    round-trip to Postgres, so this is genuine concurrent SQL traffic, not a Python-level
    illusion of it — the same race a real pair of pytest-xdist workers would produce. If
    `stmt.reset()` were ever the bare, unscoped form IR-06 bans, whichever thread's reset lands
    last would zero the other one's counters and one of the two assertions below would see the
    wrong count.
    """
    dsn = conftest.maintenance_dsn()
    if not stmt.available(dsn):
        gate("pg_stat_statements not available on this cluster")

    def _drive(name: str, n: int) -> tuple[str, int, int]:
        with psycopg.connect(conftest._env_dsn(name), autocommit=True) as conn:
            stmt.reset(dsn, name)
            for i in range(n):
                conn.execute("SELECT %s", (i,))
            return name, n, stmt.count(dsn, name)

    with conftest.fresh_clone() as name_a, conftest.fresh_clone() as name_b:
        assert name_a != name_b, "the two clones were not actually distinct databases"
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            fut_a = pool.submit(_drive, name_a, 7)
            fut_b = pool.submit(_drive, name_b, 13)
            got_name_a, want_a, got_a = fut_a.result(timeout=30)
            got_name_b, want_b, got_b = fut_b.result(timeout=30)

        assert got_a == want_a, (
            f"{got_name_a}: expected {want_a} statements since reset, saw {got_a} — a sibling "
            f"clone's reset() call crossed into this database's counters"
        )
        assert got_b == want_b, (
            f"{got_name_b}: expected {want_b} statements since reset, saw {got_b} — a sibling "
            f"clone's reset() call crossed into this database's counters"
        )
