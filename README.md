# Vertical

![Vertical: one board for today, the week, the year and a whole life, with Claude and Codex working from it](docs/media/vertical-reel.avif)

One board from today to your whole life, and the agents that work from it: an open-source
agentic development environment and a life planner in one.

Life is about to be built around agents, yet a life has no single place to build around, so
agents stay in the same scattered apps as everything else. Vertical gives it one. Day, Week,
Month, Quarter, Year, three years and Life stand side by side as columns. Claude or Codex read
the board, write your morning report from your sources, keep your documents and move goals with you.

## An experiment, in the open

Agents write almost all of the code; two of us hold the bar and aim for an Apple Design Award.
Most of what you see we still don't like, so tell us what you hate. For now, expect things to break.

It runs on your Mac and keeps your data there. You need Claude Code or Codex, signed in.
The light and dark appearance follows macOS automatically, including changes while the app is open.
Dark appearance uses soft grey text while keeping task and document text readable.
The app is in [Releases](https://github.com/konstantinopolskii/verticals/releases); it still
carries its old name, Verticals. Open source under the GNU Affero General Public License v3.0,
see [License](#license).

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

Submit changes as pull requests against `main`, one task each, opened with `tools/pr.py`
(the `verticals-pr` skill below has the rules; `.github/workflows/pr-rules.yml` checks their form on GitHub).
Edit web/src for UI, verticals/core for domain behavior, verticals/db/migrations for schema.
Do not edit generated bundles or vendor archives. Do not commit secrets or real user data.

## Agent skills

The portable, repository-owned skill pack lives in `.agents/skills/`:

- `verticals-planning` maps evidence-backed commitments onto the Life-to-Day ladder and
  requires an approved mutation diff before writes.
- `verticals-operator` uses the live MCP catalog, applies approved writes idempotently,
  and verifies raw and rendered state afterward.
- `verticals-morning-report` reconciles current work and configured sources into one
  daily review report, then updates that same report after the reader's feedback.
- `verticals-pr` holds how a pull request here is made and described, learned from the
  first 64. `tools/pr.py` checks a PR against it and opens it; in Claude Code, the hook in
  `.claude/settings.json` refuses `gh pr create` itself.

Claude discovers the same sources through relative links in `.claude/skills/`; Codex reads
`.agents/skills/` directly. The skills contain no personal routes, local paths, account names,
or mandatory external-app dependencies. Messaging, calendar, meeting, repository, payment,
and time-tracking sources are optional evidence inputs when configured and authorized.
For the report skill, set the reader's timezone, report destination, available sources,
and optional cadence in the owner's local workspace instructions; see its
`references/setup.md`. No personal path, account, or schedule is baked into the pack.

Codex morning turns expose the reading tools named by approved sources on configured
MCP servers. Other servers and plugins remain disabled; ordinary board conversations
still expose only the desktop connection. A server disabled in the owner's Codex
configuration stays disabled. New source approvals take effect on the next morning
agent launch.
Source documents show their check and Approve button both in a window and at a direct
document address, without visiting the Inbox first.

## Verification

Run `npm --prefix web run typecheck` and `npm --prefix web run build`.
Browser smoke: create/complete a task, reload, move between the Inbox and the board, stop/restart,
verify persistence. Database regression suites use the separate test database:
`make db-up` (optional Docker), then `make test-core`, `make test-http`, `make test-mcp`
or `make test-ui`. Never point those tests at personal data.

Historical document gates and reference screenshots are excluded for privacy.
The full `make test` catalogue is not certified here: inherited document and visual
tests need sanitized fixtures first.

## Credits

Made by

- Konstantin Konstantinopolskii, KK: [t.me/superufastar](https://t.me/superufastar)
- Kirill B.: [t.me/chtovyhodit](https://t.me/chtovyhodit)

Thanks to

- [Timestripe](https://timestripe.com), for the idea of a life laid out on its horizons, from a day
  to all time. We used it hard; Vertical stands those horizons up as columns and points them at agents.
- Mo, the founder of [Enjoy](https://enjoy.dev), whose product gave us ideas.
- [Anthropic](https://www.anthropic.com), for Claude and Claude Code. Claude co-wrote 265 of the
  first 372 commits here.

## License

Vertical is licensed under the GNU Affero General Public License v3.0, see `LICENSE`.
The package vendored in `web/vendor/` (`@konstantinopolskii/design-system`, version 2.1.1) is under the
same license.
Three parts keep their own terms:

- `web/vendor/konstantinopolskii-design-system-2.1.1.tgz`: the Commissioner font inside it,
  under the SIL Open Font License 1.1 (its `OFL.txt` is in the archive).
- `web/public/fonts/`: Inter, under the SIL Open Font License 1.1.
- `desktop/chat/ui/assets/`: logos of other companies, which belong to their owners.
