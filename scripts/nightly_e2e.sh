#!/bin/bash
# Nightly full-E2E regression (KK ruling 2026-08-25: deliveries gate on the
# targeted subset only; the full sweep runs here instead, at 03:30 on the Air
# via launchd com.kk.verticals-nightly).
#
# One job: run `make test` (every suite runnable on this box, harness excluded
# — the Makefile's own definition), keep a dated log, and append a one-line
# verdict to verdicts.log so a session can read the latest state in one glance.
# Nothing here deploys, pushes, or touches prod.
set -u

REPO="$(cd "$(dirname "$0")/.." && pwd)"
OUT="$REPO/artifacts/nightly"
DATE="$(date +%F)"
LOG="$OUT/$DATE.log"
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"

mkdir -p "$OUT"
cd "$REPO" || exit 1

# Docker must be up for the test Postgres; a box asleep on Docker is a fact
# worth its own verdict line, not a mystery inside a make error.
if ! docker info >/dev/null 2>&1; then
  echo "$DATE FAIL docker-unavailable" >> "$OUT/verdicts.log"
  echo "docker unavailable at $(date)" > "$LOG"
  exit 1
fi

make db-up >> "$LOG" 2>&1
make test >> "$LOG" 2>&1
CODE=$?

# The suite prints one VERDICT line per suite; the last TOTAL table is the
# overall picture. Grab every verdict for the one-line summary.
SUMMARY="$(grep -E '^VERDICT' "$LOG" | sort | uniq -c | tr -s ' ' | tr '\n' ';')"
if [ "$CODE" -eq 0 ]; then
  echo "$DATE PASS $SUMMARY" >> "$OUT/verdicts.log"
else
  echo "$DATE FAIL exit=$CODE $SUMMARY" >> "$OUT/verdicts.log"
fi

# Keep two weeks of dated logs — same retention the prod pg_dump uses.
ls -1t "$OUT"/????-??-??.log 2>/dev/null | tail -n +15 | xargs rm -f --

exit "$CODE"
