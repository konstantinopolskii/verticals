# Verticals desktop (MVP)

A macOS app around Verticals: one window with the board, a bundled PostgreSQL, the API, the MCP
server for agents and a chat with a local agent CLI (Claude Code or Codex) that works on the board
through MCP. Everything runs on 127.0.0.1.

It is additive: the web variant (`tools/local.py`, Docker, `web/dist`) is not touched. The desktop
launcher has its own ports, database, state directory and UI build.

## Layout

- `launcher.py` — starts PostgreSQL, the API, the MCP server (streamable HTTP) and a gateway that
  serves the UI, proxies `/api` with the bearer token (like the Docker nginx) and serves the chat's `/__chat/*` routes.
- `chat/` — chat backend (`chat.py`: Claude via `claude --print` stream-json, Codex via
  `codex app-server`), `mcp_proxy.py` (stdio → HTTP MCP relay for Codex), `prompt-intro.md`
  (the system prompt is this intro plus `.agents/skills/verticals-operator`, read at startup),
  `ui/assets/` (the agents' and models' marks). The conversation itself is drawn by the app
  (`web/src/lib/agentChat.ts`, `AgentConversation.vue`).
- `macos/` — `Verticals.swift` (native window, WKWebView) and `bundle.py` (self-contained
  `Verticals.app` + `.dmg`).

The agent picker follows Enjoy's (strings, model artwork).

## Run from the repository

Requires PostgreSQL 16 (`brew install postgresql@16`), Python 3.12 (`uv python install 3.12`) and,
for the chat, an agent CLI: `claude` (signed in) and optionally `codex`.

1. Build the UI with an empty token into its own directory (never into `web/dist`):
   ```sh
   VITE_VERTICALS_TOKEN= npm --prefix web run build -- --outDir ../desktop/build/web --emptyOutDir
   ```
2. Start:
   ```sh
   python3 desktop/launcher.py        # UI: http://127.0.0.1:8288/
   python3 desktop/launcher.py mcp    # how to connect an agent to MCP
   ```
   The first run creates `.local-verticals-desktop/` (venv with the dependencies, database with the
   sample board, token). Ctrl-C stops everything and keeps the data.

Ports: UI 8288, API 8299, MCP 8281, PostgreSQL 55539 (override with `VERTICALS_DESKTOP_UI_PORT`,
`..._API_PORT`, `..._MCP_PORT`, `..._PG_PORT`). State: `VERTICALS_DESKTOP_STATE`.

## Build the app

After step 1 above, on an Apple Silicon Mac with Homebrew `postgresql@16`, uv (Python 3.12) and
Xcode Command Line Tools:

```sh
python3 desktop/macos/bundle.py     # -> desktop/dist/Verticals.app, desktop/dist/Verticals.dmg
```

The bundle mirrors the repository layout inside `Contents/Resources` (verticals/, desktop/, the
operator skill) plus a trimmed Python 3.12 with the dependencies and PostgreSQL 16 with its
Homebrew libraries copied in and relinked; the build checks that no binary links outside the app
and runs initdb + `pg_trgm` from the bundle. The app keeps its data in
`~/Library/Application Support/Verticals` and never writes into itself.

Installing on another Mac: open the `.dmg`, drag Verticals to Applications, then remove the
quarantine (the app is ad-hoc signed, not notarized):
`xattr -dr com.apple.quarantine /Applications/Verticals.app`.

## Chat

- Chat bar at the bottom (⌘K); the conversation list opens on the left; agent picker with
  Agent / Model / Effort / Speed / Permissions; Enter queues while the agent works, ⌘Enter sends now.
- Each goal card gets a "discuss" button (on hover, next to the "…" menu) that opens a new
  conversation bound to that goal; the agent receives its id and link with every message.
- Agents see the screen context and use only the Verticals MCP tools (Claude runs with no built-in
  tools). Links to goals, docs and board dates open inside Verticals.
- Uses the local CLI's own sign-in; every answer counts against that account's limits.

## Security notes

- Everything listens on 127.0.0.1. The gateway rejects foreign `Host`/`Origin` and cross-site
  requests; the UI bundle contains no token.
- MCP bearer tokens reach agents through owner-only files or the environment, never command lines.
- Agent processes get no variables of a parent Claude Code session.
- Codex keeps its existing CLI sign-in but disables inherited MCP servers and plugins for the
  desktop process. Its dedicated `verticals_desktop` server relays only to this app's local MCP
  endpoint. Startup checks the effective server list and refuses to start if another server
  remains enabled; the user's Codex configuration is not edited. The `verticals_desktop` name
  is reserved for this connection. Shell, web search and app connectors are disabled in chat.

## Status

MVP. Codex support follows the `app-server` protocol. Verified with Codex CLI
`0.155.0-alpha.16`, an existing ChatGPT sign-in, live model/usage discovery, a tool approval,
and a read-only board query returning sample goals through the local MCP relay. This checks
the backend flow; it does not establish every provider/model or packaged-app combination.
No Developer ID signing or notarization yet.
