#!/bin/sh
# Verticals container entrypoint. docs/ACCEPTANCE.md AC-158, docs/E2E.md S-117.
#
# The order below is the contract, not a preference:
#
#   1. mint or read back VERTICALS_TOKEN  — BEFORE the server exists, because the server refuses
#      to boot without a real one (AC-081/S-113) and never generates one itself. One actor
#      provisions, the other refuses; this is the provisioning actor, and the only one.
#   2. wait for the database
#   3. apply migrations
#   4. load the sample board, but only into an empty instance
#   5. write nginx's runtime config and start it
#   6. exec the server as PID 1
#
# Idempotent by construction. A second boot of the same instance re-reads the token from the
# state file, prints nothing about it, applies zero migrations, and seeds nothing.
#
# POSIX sh, no bashisms: this runs on whatever `/bin/sh` the base image ships.

set -eu

ENV_FILE="${VERTICALS_ENV_FILE:-/state/.env}"
STATE_DIR=$(dirname "$ENV_FILE")
RUN_DIR=/run/verticals
NGINX_TEMPLATE=/opt/verticals/nginx.conf.template
NGINX_CONF="$RUN_DIR/nginx.conf"

# The literal value shipped in .env.example. verticals/config.py refuses to boot on it, on
# purpose — a placeholder that quietly authenticated would be worse than no default at all.
PLACEHOLDER=REPLACE_ME_THIS_VALUE_NEVER_AUTHENTICATES

log() {
    echo "entrypoint: $*" >&2
}

die() {
    log "$*"
    exit 1
}

# ----------------------------------------------------------------------------------------------
# 1. The token.
# ----------------------------------------------------------------------------------------------

mkdir -p "$STATE_DIR"
if [ ! -e "$ENV_FILE" ]; then
    # Create it empty and lock it down before anything is written into it — a file that is
    # world-readable for even one instant has been world-readable.
    (umask 077; : > "$ENV_FILE")
fi
[ -f "$ENV_FILE" ] || die "$ENV_FILE exists but is not a regular file"
chmod 0600 "$ENV_FILE"

existing=$(sed -n 's/^VERTICALS_TOKEN=//p' "$ENV_FILE" | head -n 1)

if [ -z "$existing" ] || [ "$existing" = "$PLACEHOLDER" ]; then
    minted=yes
    VERTICALS_TOKEN=$(python -c 'import secrets; print(secrets.token_urlsafe(32))')

    # Rewrite in place through a temporary file in the same directory, so a crash mid-write
    # leaves the old file rather than half a file. `sed -i` is avoided on purpose: it renames
    # over the target, which would break a single-file bind mount.
    tmp="$ENV_FILE.tmp.$$"
    (umask 077; : > "$tmp")
    if grep -q '^VERTICALS_TOKEN=' "$ENV_FILE"; then
        # Replaces the placeholder line wherever it sits, keeping every other line — including
        # the comments .env.example ships — exactly as the operator left them.
        VERTICALS_TOKEN="$VERTICALS_TOKEN" awk '
            /^VERTICALS_TOKEN=/ { print "VERTICALS_TOKEN=" ENVIRON["VERTICALS_TOKEN"]; next }
            { print }
        ' "$ENV_FILE" > "$tmp"
    else
        cat "$ENV_FILE" > "$tmp"
        printf 'VERTICALS_TOKEN=%s\n' "$VERTICALS_TOKEN" >> "$tmp"
    fi
    mv "$tmp" "$ENV_FILE"
    chmod 0600 "$ENV_FILE"
else
    minted=no
    VERTICALS_TOKEN="$existing"
fi
export VERTICALS_TOKEN

if [ "$minted" = yes ]; then
    # Printed exactly once, on the boot that generated it, and never again by anything in this
    # image. Copy it now — an instance that loses it mints nothing new; you edit the state file.
    cat >&2 <<BANNER

  ─────────────────────────────────────────────────────────────────────────────
  A bearer token was generated for this instance and written to $ENV_FILE
  (mode 0600). This is the only time it is printed.

    export VERTICALS_TOKEN=$VERTICALS_TOKEN

  The web UI needs nothing from you — this container already carries the token.
  The line above is for an agent over MCP, or for curl against the API.
  ─────────────────────────────────────────────────────────────────────────────

BANNER
fi

# ----------------------------------------------------------------------------------------------
# 2. The database.
# ----------------------------------------------------------------------------------------------

: "${VERTICALS_DATABASE_URL:?VERTICALS_DATABASE_URL is required — docker-compose.yml sets it}"

log "waiting for the database"
waited=0
until python - <<'PY'
import os
import sys

import psycopg

try:
    with psycopg.connect(os.environ["VERTICALS_DATABASE_URL"], connect_timeout=3):
        pass
except Exception:
    sys.exit(1)
PY
do
    waited=$((waited + 1))
    [ "$waited" -lt 60 ] || die "database did not accept a connection within 60 attempts"
    sleep 1
done
log "database is up"

# ----------------------------------------------------------------------------------------------
# 3. Migrations. Forward-only, one transaction, a no-op when there is nothing outstanding.
# ----------------------------------------------------------------------------------------------

log "applying migrations"
python -m verticals.db.runner up

# ----------------------------------------------------------------------------------------------
# 4. The sample board — only into an instance that holds nothing.
#
# Six synthetic goals tagged `sample`, one life-to-day chain plus one leaf subgoal
# (verticals/db/seed_sample.sql). This is the tutorial, and a stranger with an empty board has no
# way to tell a working install from a broken one. Skipped the moment the owner has any row of
# their own, so it never reappears after somebody clears it.
# ----------------------------------------------------------------------------------------------

if [ "${VERTICALS_SEED_SAMPLE:-1}" = "1" ]; then
    VERTICALS_SEED_FILE=/app/verticals/db/seed_sample.sql python - <<'PY'
import os
import pathlib

import psycopg

owner = os.environ.get("VERTICALS_OWNER", "local")
sql = pathlib.Path(os.environ["VERTICALS_SEED_FILE"]).read_text(encoding="utf-8")

with psycopg.connect(os.environ["VERTICALS_DATABASE_URL"]) as conn:
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM goals WHERE owner = %s", (owner,))
        (count,) = cur.fetchone()
        if count:
            print(f"entrypoint: {count} goals already present, sample not loaded", flush=True)
        else:
            cur.execute(sql)
            print("entrypoint: sample board loaded (six goals tagged 'sample')", flush=True)
PY
fi

# ----------------------------------------------------------------------------------------------
# 5. nginx — static bundle plus the same-origin proxy that carries the token.
# ----------------------------------------------------------------------------------------------

mkdir -p "$RUN_DIR"
chmod 0700 "$RUN_DIR"
[ -f "$NGINX_TEMPLATE" ] || die "missing $NGINX_TEMPLATE"

# The token is passed through the environment, never as a command-line argument: an argument is
# readable in /proc by anything else in this namespace for as long as the process lives.
(
    umask 077
    awk '
        { gsub(/__VERTICALS_TOKEN__/, ENVIRON["VERTICALS_TOKEN"]); print }
    ' "$NGINX_TEMPLATE" > "$NGINX_CONF"
)
chmod 0600 "$NGINX_CONF"

nginx -c "$NGINX_CONF" -t >/dev/null 2>&1 || die "generated nginx config is invalid"
nginx -c "$NGINX_CONF"
log "nginx serving /srv/verticals on :80"

# ----------------------------------------------------------------------------------------------
# 6. The server, as PID 1, so a crash stops the container instead of leaving a husk.
# ----------------------------------------------------------------------------------------------

log "starting verticals.api.app on ${VERTICALS_BIND:-127.0.0.1:8080}"
exec python -m verticals.api.app
