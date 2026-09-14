#!/usr/bin/env bash
# The perf suite, run when nobody is at the machine.
#
# Why this exists: `tests/perf` refuses to report a number measured on a loaded box — above
# 0.25 x cores of 1-minute load average it records "no measurement taken" rather than publish a
# figure about the scheduler. During a working day this Mac never drops under that ceiling, so
# every interactive run gates all nine scenarios and the perf column stays unmeasured
# (KK ruling 2026-08-11: backlog it to the night, do not block a deploy on it).
#
# Driven by ~/Library/LaunchAgents/consulting.kk.verticals-perf.plist at 03:00. launchd fires a
# missed calendar job on the next wake, so a sleeping machine delays the run rather than skipping
# it. Nothing here changes power settings — that is the operator's call, not a script's.
#
# It goes through scripts/e2e-run.sh like every other suite run: that wrapper is the ONLY
# sanctioned holder of the app-stack/test-cluster container swap and the machine-wide suite lock.
# If a suite is already running (or a Luna queued one), this blocks on the lock instead of
# fighting it for the `verticals-postgres-1` container name.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LOG_DIR="$ROOT/measure/perf-night"     # measure/ is gitignored Zone-1 evidence — logs stay there
mkdir -p "$LOG_DIR"
STAMP="$(date -u +%Y-%m-%dT%H%M%SZ)"
LOG="$LOG_DIR/$STAMP.log"

{
  echo "=== verticals perf, unattended run $STAMP ==="
  echo "load at start: $(uptime)"
  echo "cores: $(sysctl -n hw.ncpu)"
  echo
} > "$LOG"

# The load gate is the whole point of running at night — record what it saw, pass or gate, so a
# morning read can tell "measured and slow" from "still too loaded to measure".
#
# `PYTEST=` rather than a make target: e2e-run.sh appends its arguments to `make test`, so there
# is no way to select one suite through it. This is the same command the runner builds for itself
# (`python -m pytest <suite dir> -p tests.harness.runner`), which is why the PASS/FAIL/GATE lines
# come out identical to a full run's perf column.
#
# `tests/http/test_read_isolation.py` rides along because S-41's timing half takes the same load
# gate as of D94, and this is the only window in which it can be certified: on a workstation with
# a live desktop session the idle load average alone sits above the ceiling, so an interactive run
# can only ever GATE it. The security half of that scenario (both ids 404, byte-identical bodies)
# is asserted on every run regardless — this is about the 2 ms oracle, nothing else.
PYTEST="tests/perf tests/http/test_read_isolation.py -p tests.harness.runner" "$ROOT/scripts/e2e-run.sh" >> "$LOG" 2>&1 || true

{
  echo
  echo "load at end: $(uptime)"
} >> "$LOG"

ln -sfn "$LOG" "$LOG_DIR/latest.log"
