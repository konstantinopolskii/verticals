"""Suite orchestration, the verdict block, and `artifacts/results.jsonl`. `docs/E2E.md` §12
"The runner"; `docs/IMPLEMENTATION.md` WP-06 card. What `make test` and every `make test-<suite>`
target actually run (`Makefile`): `python -m tests.harness.runner [--suite NAME] [--scenario
S-17,S-22] [--tier ci|full] [--milestone M0|M1|M2|all]`.

This module is two things in one file, on purpose — a CLI entrypoint and, loaded into a child
pytest process via `-p tests.harness.runner`, a plugin:

  * As a CLI (the `main()`/`if __name__` block at the bottom): for each suite in scope, spawns
    `python -m pytest <suite dir> -p tests.harness.runner ...` as its own subprocess — a fresh
    interpreter, fresh `conftest.py` load, fresh connection pool, so one suite's crash cannot
    corrupt another's. `docs/ARCHITECTURE.md`'s "boring, predictable" over one long-lived
    in-process `pytest.main()` loop, which pytest's own docs warn leaks state across calls.
  * As a plugin (the module-level `pytest_*` hook functions): runs *inside* that child process,
    watches every test via `pytest_runtest_logreport`, and streams one PASS/FAIL/GATE line per
    scenario plus one JSON record per scenario to a side-channel file named by the
    `_VERTICALS_RUNNER_OUT` env var the parent set before spawning it. The parent reads that file
    back once the subprocess exits. This is the only reason `tests/harness/` does not need a
    seventh file for "collect results out of a subprocess": the orchestrator plugin *is* the
    collector, in the process where the reports are already being generated.

`docs/IMPLEMENTATION.md` §0.3 IR-06 note, restated because it is the reason this file never reads
`pg_stat_statements` itself: `X-Query-Count` and this runner's own pass/fail bookkeeping are two
unrelated counters. This file counts pytest reports. `tests/harness/stmt.py` counts SQL
statement text, scoped by `dbid`, for the two scenarios that need it.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import re
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SUITE_NAMES = ("static", "core", "http", "mcp", "ui", "pipeline", "perf", "uidiff")
SUITE_DIRS = {name: REPO_ROOT / "tests" / name for name in SUITE_NAMES}

# perf measures wall-clock time on purpose (`time.perf_counter`, docs/E2E.md §1) — a sibling
# xdist worker hammering the same box would be measurement noise, not a bug in the product. ui
# and uidiff drive a real Chromium; xdist-parallel browser instances are a resource-contention
# risk this WP has no way to load-test, so they get the conservative default until whichever
# work package builds them says otherwise.
SERIAL_SUITES = {"perf", "ui", "uidiff"}

EXIT_OK = 0
EXIT_FAIL = 1
EXIT_HARNESS_ERROR = 2

_OUT_ENV = "_VERTICALS_RUNNER_OUT"
_SCENARIO_FILTER_ENV = "VERTICALS_SCENARIO_FILTER"
_SCENARIO_ID_RE = re.compile(r"^S-\d+$")
_RANK = {"pass": 0, "gate": 1, "skip": 2, "fail": 3}  # higher wins when a scenario has >1 test


@dataclass
class _SuiteRow:
    suite: str
    total: int = 0
    passed: int = 0
    failed: int = 0
    skipped: int = 0
    gated: int = 0
    seconds: float = 0.0


# =================================================================================================
# Plugin half — runs inside the child `pytest` subprocess only (loaded via `-p
# tests.harness.runner`). Every function below is a no-op import when this module is used as a
# library or run as `__main__`; pytest is what calls them.
# =================================================================================================

_phases: dict[str, dict[str, object]] = {}
_collect_errors: list[str] = []
_naming_violations: list[str] = []
_silenced_sink = None


def pytest_sessionstart(session) -> None:
    """Silence pytest's own terminal output without unregistering the plugin that produces it.

    This runner prints one PASS/FAIL/GATE line per scenario itself (`pytest_runtest_logreport`
    above), so pytest's dots-and-summary output is duplicate noise. The obvious way to remove it
    — `-p no:terminalreporter` on the child command line — is a trap, and cost this repo every
    failing comparison assert's message: `_pytest/assertion/util.py`'s `assertrepr_compare`, the
    function that builds the "assert 3 < 1" explanation, reaches for `config.get_terminal_writer()`
    to get a highlighter, and that method is `assert terminalreporter is not None`. With the plugin
    gone the explanation path raises, and a bare `AssertionError` carrying no message replaces the
    descriptive one — in a project whose testing posture is that a result must be readable from a
    log, a failure that cannot say what went wrong is not a result.

    So the plugin stays registered and only its *destination* changes: its `TerminalWriter` keeps
    working (`_highlight`, `fullwidth`, markup) but writes into `os.devnull`. Nothing pytest emits
    reaches the log; everything pytest *computes* for a failure report still does, because the
    explanation is built as strings and handed back through `longrepr`, never written to the
    writer. Under `-n auto` this runs in each xdist worker too — the worker is where a test's
    `longrepr` is actually built, so silencing the controller alone would not be enough, and
    fixing only the controller would leave the bug in the parallel suites.

    It hangs off `pytest_sessionstart` rather than `pytest_configure` for a concrete ordering
    reason, found by running it the other way first: this module is loaded with `-p`, so it is
    registered *before* `_pytest.terminal`, and pluggy calls hooks last-registered-first — our
    `pytest_configure` would run before the terminal plugin's, find no `terminalreporter` yet, and
    silently no-op, leaking pytest's dots and FAILURES section into the log. Every configure hook
    has run by the time the session starts, so by here the reporter always exists.
    """
    global _silenced_sink

    reporter = session.config.pluginmanager.get_plugin("terminalreporter")
    if reporter is None:  # -p no:terminalreporter passed by someone else; nothing to silence
        return
    _silenced_sink = open(os.devnull, "w")
    reporter._tw._file = _silenced_sink


def pytest_unconfigure(config) -> None:
    global _silenced_sink

    if _silenced_sink is not None:
        _silenced_sink.close()
        _silenced_sink = None


def pytest_collection_modifyitems(config, items):
    """`SCENARIO=S-17,S-22` support (`docs/E2E.md` §12). Deselects rather than skips — a
    deselected item never generates a report at all, which is what keeps a filtered run's
    `results.jsonl` "a smaller report, not a different shape" instead of full of fake skips the
    no-skip rule would then have to explain away."""
    wanted_raw = os.environ.get(_SCENARIO_FILTER_ENV)
    if not wanted_raw:
        return
    wanted = set(wanted_raw.split(","))
    from tests.harness.report import scenario_id_of  # local import: plugin mode only

    keep, deselected = [], []
    for item in items:
        (keep if scenario_id_of(item.name) in wanted else deselected).append(item)
    if deselected:
        config.hook.pytest_deselected(items=deselected)
        items[:] = keep


def pytest_collectreport(report) -> None:
    if report.failed:
        _collect_errors.append(str(report.longrepr))


def pytest_runtest_logreport(report) -> None:
    from tests.harness.report import scenario_id_of, suite_of  # local import: plugin mode only

    slot = _phases.setdefault(report.nodeid, {})
    slot[report.when] = report
    if report.when != "teardown":
        return

    name = report.nodeid.rsplit("::", 1)[-1]
    suite = suite_of(report.nodeid)
    sid = scenario_id_of(name)
    if sid is None:
        _naming_violations.append(
            f"{report.nodeid}: test name does not match test_s<NN>[<letter>]_... "
            f"(tests/harness/report.py scenario_id_of) — cannot attribute it to a catalogue id"
        )
        sid = f"UNRECOGNIZED:{name}"

    status = "pass"
    seconds = 0.0
    artifacts: list[str] = []
    detail = None
    for when in ("setup", "call", "teardown"):
        r = slot.get(when)
        if r is None:
            continue
        seconds += r.duration
        got = getattr(r, "artifacts", None)
        if got:
            artifacts = got
        outcome = getattr(r, "outcome", None)
        if outcome == "failed" and _RANK["fail"] > _RANK[status]:
            status = "fail"
            detail = str(r.longrepr) if r.longrepr else detail
        elif outcome == "gate" and _RANK["gate"] > _RANK[status]:
            status = "gate"
            detail = getattr(r, "gate_reason", None) or "gated"
        elif outcome == "skipped" and _RANK["skip"] > _RANK[status]:
            status = "skip"
            detail = str(r.longrepr) if r.longrepr else detail

    # `sid` (used below for the tally and results.jsonl) stays the full "UNRECOGNIZED:<name>" so
    # several unattributed tests never collapse into one record; the printed line shows "-"
    # instead, since repeating the whole name here would run straight into the suite column.
    display_id = "-" if sid.startswith("UNRECOGNIZED:") else sid
    line = f"{status.upper():<5}{display_id:<8}{suite:<9} {name:<44}{seconds:6.2f}s"
    if status == "gate":
        line += f"  ({detail})"
    print(line, flush=True)
    if status == "fail" and detail:
        # `detail` is already the exact E2E.md §12 FAIL block when the scenario used
        # `tests/harness/report.fail()`. A bare `assert` never built that shape — pytest's own
        # longrepr prints instead, which is a real traceback rather than a swallowed one, just
        # not the fixed block verbatim.
        print(detail, flush=True)

    record = {
        "id": sid,
        "suite": suite,
        "status": status,
        "duration_s": round(seconds, 3),
        "artifacts": artifacts,
    }
    if detail and status in ("fail", "gate"):
        record["detail"] = detail[:500]
    out_path = os.environ.get(_OUT_ENV)
    if out_path:
        with open(out_path, "a") as f:
            f.write(json.dumps(record) + "\n")


def pytest_sessionfinish(session, exitstatus) -> None:
    """Two side-channel files, two severities. A collection error means the tree itself is
    broken — nothing ran, so nothing that did run can be trusted either — and blocks the verdict.
    A naming violation (`tests/harness/report.py`'s `test_s<NN>_...` convention not matched)
    means one test cannot be tied to a catalogue id; its pass/fail/gate outcome still reaches
    the tally under a synthetic `UNRECOGNIZED:<name>` id (`pytest_runtest_logreport` above), so a
    real failure there still fails the run — this file only decides that the *naming* gap alone
    is a printed notice, not a reason to block every other suite's PASS. This work package does
    not own every test file under `tests/`, and cannot rename another WP's tests to fix it."""
    out_path = os.environ.get(_OUT_ENV)
    if not out_path:
        return
    if _collect_errors:
        Path(f"{out_path}.harness_errors").write_text("\n---\n".join(_collect_errors))
    if _naming_violations:
        Path(f"{out_path}.notices").write_text("\n---\n".join(_naming_violations))


# =================================================================================================
# CLI half — the parent process. Spawns one subprocess per suite, reads each one's side-channel
# file back, tallies, and prints the one verdict block a run ends with.
# =================================================================================================


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="python -m tests.harness.runner")
    p.add_argument("--suite", choices=SUITE_NAMES, default=None)
    p.add_argument("--scenario", default=None, help="S-17 or S-17,S-22,S-108 (no spaces)")
    p.add_argument("--tier", choices=("ci", "full"), default="ci")
    p.add_argument("--milestone", choices=("M0", "M1", "M2", "all"), default="all")
    args = p.parse_args(argv)

    if args.scenario is not None:
        ids = args.scenario.split(",")
        if any(not sid for sid in ids):
            p.error("--scenario: empty element in a comma-separated list")
        if len(ids) != len(set(ids)):
            p.error("--scenario: duplicate id in a comma-separated list")
        bad = [sid for sid in ids if not _SCENARIO_ID_RE.match(sid)]
        if bad:
            p.error(f"--scenario: not shaped like S-17: {bad}")
        args.scenario = ids
    return args


def _read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def _merge_by_scenario(records: list[dict]) -> list[dict]:
    """Collapses `S-111a`/`S-111b`/`S-111c` (several test functions, one catalogue scenario —
    `tests/harness/report.py`'s naming convention) into one `S-111` record: worst status wins
    (fail > skip > gate > pass), durations sum, artifact lists union. This is also what makes
    `results.jsonl` hold "one object per registered *scenario*" rather than one per test
    function, which is the shape S-124 and this file's own done-when both assume."""
    best: dict[str, dict] = {}
    for rec in records:
        prior = best.get(rec["id"])
        if prior is None:
            best[rec["id"]] = rec
            continue
        if _RANK[rec["status"]] > _RANK[prior["status"]]:
            winner, loser = rec, prior
        else:
            winner, loser = prior, rec
        merged = dict(winner)
        merged["duration_s"] = round(prior["duration_s"] + rec["duration_s"], 3)
        merged["artifacts"] = list(dict.fromkeys(prior["artifacts"] + rec["artifacts"]))
        best[rec["id"]] = merged
    return list(best.values())


def _tally(suite: str, merged: list[dict]) -> _SuiteRow:
    row = _SuiteRow(suite)
    for rec in merged:
        row.total += 1
        row.seconds += rec["duration_s"]
        if rec["status"] == "pass":
            row.passed += 1
        elif rec["status"] == "fail":
            row.failed += 1
        elif rec["status"] == "gate":
            row.gated += 1
        elif rec["status"] == "skip":
            row.skipped += 1
    return row


def _run_suite(suite: str, args: argparse.Namespace) -> tuple[_SuiteRow, list[dict], bool]:
    suite_dir = SUITE_DIRS[suite]
    if not suite_dir.exists() or not any(suite_dir.rglob("test_*.py")):
        # Discovered, not enumerated: a suite this wave has not built yet contributes zero
        # rows, not a crash — required for `make test` to mean anything before wave 1 finishes.
        return _SuiteRow(suite), [], False

    fd, out_name = tempfile.mkstemp(prefix=f"verticals-{suite}-", suffix=".jsonl")
    os.close(fd)
    out_path = Path(out_name)
    out_path.unlink()  # only wanted a name nothing else will collide with

    cmd = [
        sys.executable, "-m", "pytest", str(suite_dir),
        # The terminal reporter stays registered on purpose — see this module's own
        # `pytest_configure`, which redirects its writer to os.devnull instead. Unregistering it
        # here is what silently stripped the message off every failing comparison assert.
        "-p", "tests.harness.runner",
        "-q", "--no-header",
    ]
    if suite not in SERIAL_SUITES:
        cmd += ["-n", "auto"]

    env = dict(os.environ)
    env[_OUT_ENV] = str(out_path)
    if args.scenario:
        env[_SCENARIO_FILTER_ENV] = ",".join(args.scenario)

    wall_start = time.perf_counter()
    proc = subprocess.run(cmd, cwd=str(REPO_ROOT), env=env)
    wall_seconds = time.perf_counter() - wall_start

    records = _read_jsonl(out_path)
    harness_err = False
    err_path = Path(f"{out_path}.harness_errors")
    if err_path.exists():
        text = err_path.read_text().strip()
        if text:
            print(f"--- suite {suite}: collection errors, block the verdict ---", file=sys.stderr)
            print(text, file=sys.stderr)
            harness_err = True
        err_path.unlink()
    notice_path = Path(f"{out_path}.notices")
    if notice_path.exists():
        text = notice_path.read_text().strip()
        if text:
            print(f"--- suite {suite}: naming notices, do not block the verdict ---",
                  file=sys.stderr)
            print(text, file=sys.stderr)
        notice_path.unlink()
    out_path.unlink(missing_ok=True)

    if proc.returncode not in (0, 1, 5):
        harness_err = True
        print(
            f"tests.harness.runner: suite {suite!r} pytest exited {proc.returncode} "
            f"(expected 0 all-pass, 1 some-fail, or 5 no-tests-collected) — treating this as a "
            f"harness error, not a scenario failure",
            file=sys.stderr,
        )

    merged = _merge_by_scenario(records)
    row = _tally(suite, merged)
    # The table's "seconds" column is wall clock, not summed test durations — inside a suite
    # this WP runs under `-n auto`, several tests' durations overlap in real time, and a sum
    # would overstate the suite's true cost (and stop summing to the run's total elapsed, which
    # docs/E2E.md §12's own sample table does: 1.9+13.5+...+0.0 == 414.5).
    row.seconds = wall_seconds
    return row, merged, harness_err


def _gate_note(records: list[dict]) -> str:
    reasons = sorted({rec.get("detail") or "reason not given" for rec in records if rec["status"] == "gate"})
    return "; ".join(reasons) if reasons else "no reason given"


def _decide(
    rows: list[_SuiteRow], records: list[dict], args: argparse.Namespace, harness_error: bool
) -> tuple[str, str]:
    """`docs/E2E.md` §12 "How an agent decides pass or fail", rules 2 and 4 — this function is
    both. Rule 1 (a `VERDICT:` line must exist) and rule 3 (exit code must agree) are satisfied
    structurally by `main()` always printing exactly one block built from this return value and
    deriving the exit code from the same two values, never a second, independent computation."""
    total_failed = sum(r.failed for r in rows)
    total_skipped = sum(r.skipped for r in rows)
    total_gated = sum(r.gated for r in rows)

    if harness_error:
        return "FAIL", "harness error — see stderr above"
    if total_skipped > 0:
        return "FAIL", f"skip={total_skipped} (the catalogue has no skippable scenarios)"
    if total_failed > 0:
        return "FAIL", f"{total_failed} scenario(s) failed"
    if total_gated > 0:
        reason = _gate_note(records)
        if args.tier == "full":
            return "FAIL", f"gated={total_gated} under TIER=full: {reason}"
        return "PASS", f"gated={total_gated}: {reason}"
    return "PASS", ""


def _new_run_id() -> str:
    import secrets

    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return f"{ts}-{secrets.token_hex(2)}"


def _total_ram_gib() -> float | None:
    try:
        return os.sysconf("SC_PHYS_PAGES") * os.sysconf("SC_PAGE_SIZE") / (1024**3)
    except (ValueError, OSError, AttributeError):
        pass
    if sys.platform == "darwin":
        try:
            out = subprocess.run(
                ["sysctl", "-n", "hw.memsize"], capture_output=True, text=True, timeout=5, check=True
            )
            return int(out.stdout.strip()) / (1024**3)
        except (OSError, subprocess.SubprocessError, ValueError):
            return None
    return None


def _machine_line() -> str:
    ram = _total_ram_gib()
    ram_part = f" / {ram:.0f} GiB" if ram else ""
    return f"{platform.system()} {platform.machine()} / {os.cpu_count()} cpu{ram_part}"


def _postgres_line() -> str:
    import tests.conftest as conftest  # local import: avoids a hard psycopg dependency for --help

    host = os.environ.get("PGHOST", "127.0.0.1")
    port = os.environ.get("PGPORT", "55432")
    try:
        import psycopg

        with psycopg.connect(conftest.maintenance_dsn(), autocommit=True, connect_timeout=3) as c:
            (version,) = c.execute("SHOW server_version").fetchone()
        return f"{version} (docker {host}:{port})"
    except Exception:
        return f"unreachable (target {host}:{port})"


def _fixtures_line() -> str:
    # This work package only knows how to build F0. F1-F5 belong to other work packages' fixture
    # loaders; reporting them as present would be a guess this file has no basis for. What it can
    # say honestly: F0 always (pytest_configure builds it before any suite runs), and whether the
    # Zone-1 path some suites gate on is present on this machine.
    #
    # F3 (the raw reference-planner export) is genuinely Zone 1 and genuinely absent on a stranger's
    # machine, so it stays a gate. The uidiff reference is NOT: WP-04's sanitizer strips it hard
    # enough to commit, so it lives in git at tests/uidiff/reference/ and is present wherever the
    # repo is. Reporting "seed/reference absent" was naming a path that no longer exists and
    # printing a missing fixture that is in fact checked in — the verdict block's job is to say
    # what is true about this machine, so it now reports the reference as the present fixture it is.
    present = ["F0"]
    absent = []
    if (REPO_ROOT / "seed" / "planner-export.json").exists():
        present.append("F3")
    else:
        absent.append("F3 absent")
    if (REPO_ROOT / "tests" / "uidiff" / "reference").exists():
        present.append("uiref")
    else:
        absent.append("tests/uidiff/reference absent")
    line = " ".join(present)
    if absent:
        line += "   (" + ", ".join(absent) + ")"
    return line


def _row_line(name: str, total, passed, failed, skipped, gated, seconds) -> str:
    return f"{name:<9}{total!s:>10}{passed!s:>6}{failed!s:>6}{skipped!s:>6}{gated!s:>6}{seconds!s:>10}"


def _format_verdict_block(
    run_id: str,
    args: argparse.Namespace,
    rows: list[_SuiteRow],
    elapsed: float,
    verdict: str,
    note: str,
) -> str:
    lines = ["=== VERTICALS E2E ==="]
    for key, value in (
        ("run_id", run_id),
        ("tier", args.tier),
        ("milestone", args.milestone),
        ("machine", _machine_line()),
        ("postgres", _postgres_line()),
        ("fixtures", _fixtures_line()),
    ):
        lines.append(f"{key:<12}{value}")

    sep = "-" * 64
    lines.append(sep)
    lines.append(_row_line("suite", "total", "pass", "fail", "skip", "gate", "seconds"))
    for row in rows:
        lines.append(
            _row_line(row.suite, row.total, row.passed, row.failed, row.skipped, row.gated,
                      f"{row.seconds:.1f}")
        )
    lines.append(sep)
    lines.append(
        _row_line(
            "TOTAL",
            sum(r.total for r in rows),
            sum(r.passed for r in rows),
            sum(r.failed for r in rows),
            sum(r.skipped for r in rows),
            sum(r.gated for r in rows),
            f"{elapsed:.1f}",
        )
    )
    verdict_line = f"VERDICT: {verdict}"
    if note:
        verdict_line += f" ({note})"
    lines.append(verdict_line)
    return "\n".join(lines)


def _write_results(path: Path, records: list[dict]) -> None:
    """Always a fresh write, full run or single-suite: `results.jsonl` reflects the run that
    just happened, not a growing log that would otherwise accumulate a stale duplicate `id` for
    every scenario a developer's second `make test-core` in a row re-covers."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        for rec in records:
            f.write(
                json.dumps(
                    {k: rec[k] for k in ("id", "suite", "status", "duration_s", "artifacts")}
                )
                + "\n"
            )


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    suites = [args.suite] if args.suite else list(SUITE_NAMES)
    run_id = _new_run_id()
    started = time.perf_counter()

    rows: list[_SuiteRow] = []
    all_records: list[dict] = []
    harness_error = False

    for suite in suites:
        row, merged, suite_harness_error = _run_suite(suite, args)
        rows.append(row)
        all_records.extend(merged)
        harness_error = harness_error or suite_harness_error

    if args.scenario:
        missing = sorted(set(args.scenario) - {rec["id"] for rec in all_records})
        if missing:
            print(
                f"tests.harness.runner: --scenario named {missing} but no suite ran a test for "
                f"them — typo, or the id is not in a suite this wave built",
                file=sys.stderr,
            )
            harness_error = True

    _write_results(REPO_ROOT / "artifacts" / "results.jsonl", all_records)

    elapsed = time.perf_counter() - started
    verdict, note = _decide(rows, all_records, args, harness_error)
    print(_format_verdict_block(run_id, args, rows, elapsed, verdict, note))

    if args.suite is None:
        import tests.conftest as conftest

        try:
            dropped = conftest.drop_leaked_clones()
            print(f"# cleanup: dropped {dropped} leaked clone database(s)", file=sys.stderr)
        except Exception as exc:  # cleanup failing must not mask the verdict already printed
            print(f"# cleanup: failed to sweep leaked clones: {exc}", file=sys.stderr)

    if harness_error:
        return EXIT_HARNESS_ERROR
    return EXIT_OK if verdict == "PASS" else EXIT_FAIL


if __name__ == "__main__":
    sys.exit(main())
