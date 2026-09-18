# Verticals

Private development repository: Vue UI, Python API/MCP and PostgreSQL 16.
Initial snapshot: local revision `820a94e`, without its history.

## Native local startup

Requires Python 3.12, Node 22+ with npm, PostgreSQL 16 including pg_trgm.
No system database service needed. Homebrew/Linux binaries are detected; override
with VERTICALS_PG_BIN pointing to the PostgreSQL bin directory.

```sh
python3 tools/local.py setup
python3 tools/local.py start
```

Open http://127.0.0.1:8088. First start creates an isolated sample database.
Ctrl-C stops services; edits persist in ignored `.local-verticals/`. Never delete that
directory merely to stop the app. API: loopback 8099; PostgreSQL: loopback 55439.
Occupied ports fail without killing anything. No production credentials needed.

Setup verifies bundled UI archives against the lockfile, installs dependencies,
typechecks and builds. Start migrates and rebuilds with the local instance's token.
This is a local preview, not a public server. Never publish its generated bundle:
it contains the local token. MCP is not started by the UI launcher. Docker is optional.

## Collaboration

Use this repository's main branch as shared upstream; submit changes through PRs.
Edit web/src for UI, verticals/core for domain behavior, verticals/db/migrations for schema.
Do not edit generated bundles or vendor archives. Do not commit secrets or real user data.
The bundled private UI packages remain UNLICENSED. No public redistribution rights or
open-source license are granted by this private snapshot.

## Agent skills

The portable, repository-owned skill pack lives in `.agents/skills/`:

- `verticals-planning` maps evidence-backed commitments onto the Life-to-Day ladder and
  requires an approved mutation diff before writes.
- `verticals-operator` uses the live MCP catalog, applies approved writes idempotently,
  and verifies raw and rendered state afterward.
- `verticals-morning-report` reconciles current work and configured sources into one
  daily review report, then updates that same report after the reader's feedback.

Claude discovers the same sources through relative links in `.claude/skills/`; Codex reads
`.agents/skills/` directly. The skills contain no personal routes, local paths, account names,
or mandatory external-app dependencies. Messaging, calendar, meeting, repository, payment,
and time-tracking sources are optional evidence inputs when configured and authorized.
For the report skill, set the reader's timezone, report destination, available sources,
and optional cadence in the owner's local workspace instructions; see its
`references/setup.md`. No personal path, account, or schedule is baked into the pack.

## Verification

Run `npm --prefix web run typecheck` and `npm --prefix web run build`.
Browser smoke: create/complete a task, reload, navigate Inbox/Verticals, stop/restart,
verify persistence. Database regression suites use the separate test database:
`make db-up` (optional Docker), then `make test-core`, `make test-http`, `make test-mcp`
or `make test-ui`. Never point those tests at personal data.

Historical document gates and reference screenshots are excluded for privacy.
The full `make test` catalogue is not certified in this snapshot; see SHARING.md.
