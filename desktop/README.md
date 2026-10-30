# Vertical desktop (MVP)

A macOS app around Vertical: one window with the board, a bundled PostgreSQL, the API, the MCP
server for agents and a chat with a local agent CLI (Claude Code or Codex) that works on the board
through MCP. Everything runs on 127.0.0.1.

The app itself still carries the old name: it is built as `Verticals.app`, keeps its data in
`~/Library/Application Support/Verticals` and says Verticals in its menus. Where this file quotes
those names, they are written as the app shows them today.

It is additive: the web variant (`tools/local.py`, Docker, `web/dist`) is not touched. The desktop
launcher has its own ports, database, state directory and UI build.

## Layout

- `launcher.py` — starts PostgreSQL, the API, the MCP server (streamable HTTP) and a gateway that
  serves the UI, proxies `/api` with the bearer token (like the Docker nginx) and serves the chat's `/__chat/*` routes.
- `chat/` — chat backend (`chat.py`: Claude via `claude --print` stream-json, Codex via
  `codex app-server`), `mcp_proxy.py` (stdio → HTTP MCP relay for Codex), `prompt-intro.md`
  (the system prompt is this intro plus `.agents/skills/verticals-operator`, read at startup; the morning report's
  turn adds `prompt-morning.md` and `.agents/skills/verticals-morning-report`; `morning_flow.py` runs its turns: the
  writing one, a second agent's check with `prompt-check.md`, and one fixing turn if a check fails),
  `ui/assets/` (the agents' and models' marks). The conversation itself is drawn by the app
  (`web/src/lib/agentChat.ts`, `AgentConversation.tsx`). A conversation belongs to a goal when Discuss with agent began
  it, or when the agent makes its first goal in it: the gateway reads the new goal's id from what the `create` tool answers
  and records it, so `/__chat/goal?id=` finds the conversation, and it sends the app a `goal` event
  (docs/design/agent-chips.md). The gateway keeps `agent.log` in the state folder, beside
  `api.log` and `mcp.log`: a small rotating file (three files of 200 kB at most) of what the agent was asked to be and did,
  that is, event kinds, tool names, flags, durations and exit details, never your words, the agent's, tool inputs or
  titles, so a bug report can carry its last lines.
- `chat/agent_sessions.py` — the sessions of tasks (docs/design/task-sessions.md). A session is a file its agent writes
  (Claude Code's `projects/<folder>/<id>.jsonl`, Codex's `sessions/<y>/<m>/<d>/rollout-<time>-<id>.jsonl`, under
  `CLAUDE_CONFIG_DIR` / `CODEX_HOME`, else `~/.claude` / `~/.codex`), and Vertical reads only its size and modified time:
  never a byte of what is in it, no model, no token. The gateway keeps each task's sessions in `chat-sessions.json`
  (`GET /__chat/sessions` is what the board polls), looks at their files every two seconds (a stat each), marks one that grew
  while Vertical wasn't driving it as "continued in Claude/Codex", and opens one where it lives (`POST /__chat/open`: a Codex
  thread by `codex://threads/<id>`, a Claude session in Terminal by `claude --resume <id>` from its folder). A session begun
  from a task starts with its link, `verticals://goal/<id>`; the MCP tool `session_link` (the MCP server is told where the
  gateway is by `--gateway-url`) ties a session begun in Claude Code or Codex to a task, and it is the only way one is linked.
- `chat/report_facts.py`, `chat/report_kind.py` and `chat/prompt-report.md` — what a report carries from the app
  (`GET /__report/facts`: the version, the Mac, and for a bug the last lines of `app.log`, `api.log` and `agent.log` with
  every word of the board left out), whether the words are a bug or a request (`POST /__chat/report-kind`), and what the
  agent is told about reports (docs/design/bug-reports.md; see Reports below).
- `macos/` — `Verticals.swift` (native window, WKWebView), `AppLinks.swift` (the `verticals://goal/<id>` link and the lines
  that connect Claude Code and Codex, no window in it, checked by `tests/static/test_app_links.py`), `Updater.swift` (checks,
  downloads and installs updates), `UpdateIndicator.swift` (the Update button in the title bar) and `bundle.py`
  (self-contained `Verticals.app` + `.dmg`).

The agent picker follows Enjoy's (strings, model artwork).

## Page zoom

View → Zoom In (⌘+, or ⌘=), Zoom Out (⌘−) and Actual Size (⌘0) change the page zoom, including while
editing a task or writing in the chat. The browser-style steps range from 50% to 200% and use the
same saved setting as the developer panel. The chosen scale survives a reload and the next launch.

## Appearance

View → Appearance chooses System, Light or Dark. System follows macOS; Light or Dark is kept in the app's defaults
(`Appearance`: `defaults delete app.verticals.desktop Appearance` hands it back to macOS). The window, title bar,
update popover and page take the choice: the app sets its own appearance, and the page's `prefers-color-scheme`
follows the web view's (`web/src/design/tokens.css`). A change updates an open window immediately and keeps the current view
and draft.

## Reduce Motion

View → Reduce Motion is a checkmark between Reload and Enter Full Screen. It starts as macOS's own Reduce motion
(System Settings → Accessibility → Display); after a click it keeps the person's choice (`ReduceMotion` in the app's
defaults: `defaults delete app.verticals.desktop ReduceMotion` hands it back to macOS). A web view can't be told to
change what it reads from macOS, so the app puts its answer on `<html>` as `data-reduce-motion="on"` or `"off"` — a
user script at document start, like the title bar's height (`syncTitlebar` in `macos/Verticals.swift`) — and puts
nothing there while no choice is made, so the page asks macOS as a browser does. Everything in the page that obeys
`prefers-reduced-motion` obeys the answer: styles through `web/vite.config.ts`, which copies every such block under
the switch, and scripts through `reducedMotion()` in `web/src/lib/motion.ts`. A column bounces at its ends
(`overscroll-behavior: contain`) unless motion is reduced.

## Menu bar

Closing the window keeps Vertical running: PostgreSQL, the API and MCP stay up for agents, the Dock
icon goes away and the mascot stays in the menu bar. Its menu opens the window, says whether the
board and MCP are running, and has:

- Use Verticals in Claude Code — adds the `verticals-desktop` MCP server to Claude Code for every project
  (`claude mcp add-json --scope user`), so terminal sessions work on this board. Its `headersHelper`
  reads the token from the owner-only `mcp-headers.json` in the state folder, so Claude Code's config
  holds no token.
- Use Verticals in Codex — adds the `verticals` MCP server to Codex (`codex mcp add`): Codex starts
  `chat/mcp_proxy.py` with the bundled Python, told the MCP address and the path of that same
  `mcp-headers.json`, so Codex's config holds no token either.

  The click on either is the consent: nothing is written into Claude Code's or Codex's settings before it, and the tick
  beside the item is the app's own note that it was done (it does not read their settings). A click again replaces the
  connection. Both need a full release of the app (a web-only update doesn't carry the menu).
- A link `verticals://goal/<id>` — the app is registered for the `verticals` scheme: a click on one in Terminal or
  Codex brings the window forward and opens that task (`board/#goal/<id>`); a link in the board's own page does the same.
- Open at Login — a login item (`SMAppService`); at login Vertical starts in the menu bar only.
- Restart Verticals — quits as Quit does and opens the app again on the same page; with an update downloaded it is
  the title bar's Restart. Also in the Verticals menu.
- Quit Verticals — the only way, with ⌘Q, to stop the board and MCP.

## Which account the agents use

The app runs `claude` and `codex` as they are signed in by default (`~/.claude`, `~/.codex`). An app opened from Finder
never sees your shell, so a `CLAUDE_CONFIG_DIR` or `CODEX_HOME` set there doesn't reach it. To give Vertical another
sign-in, for example a personal account beside a work one, put the folder in `agents.env` in the state folder
(`~/Library/Application Support/Verticals/agents.env`) and restart the app:

```sh
CLAUDE_CONFIG_DIR=~/.claude-personal
CODEX_HOME=~/.codex-personal
```

Only these two variables are read, and only absolute paths (`~/` is your home folder). The chat, the morning report, the
source checks, "Use Verticals in Claude Code" and "Use Verticals in Codex" in the menu bar, and a session opened in
Terminal all use them. A folder that has never been signed in to needs one sign-in first:
`CLAUDE_CONFIG_DIR=~/.claude-personal claude`, then `/login`. The ticks beside the two menu items belong to the app, not
to an account: after a change to `agents.env`, click them again to connect the new folder.

## Codex chat list

Chats begun in Verticals get the task's title or the first message as their name and are assigned to a **Verticals**
section through Codex's app-server API. The morning report's checking chat is grouped too. Existing chats are not migrated;
after the initial organization,
moving, renaming or removing a chat from its section in Codex is left as the owner chose. Sessions linked from outside
Verticals keep their own names and placement.

Grouping uses Codex's sidebar API, not another `CODEX_HOME` or working folder: sign-in, tools and file access stay the
same. If the installed Codex does not support sections, the conversation still runs. Some desktop versions still use a
local-only sidebar and do not display app-server sections: names work, but chats stay in the main list until Codex enables
server-backed sections. Verticals does not rewrite Codex's private sidebar settings.

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

   If `desktop/build/web` is missing and `web/node_modules` is there, the launcher builds it this way itself.

Ports: UI 8288, API 8299, MCP 8281, PostgreSQL 55539 (override with `VERTICALS_DESKTOP_UI_PORT`,
`..._API_PORT`, `..._MCP_PORT`, `..._PG_PORT`). State: `VERTICALS_DESKTOP_STATE`. A database left running by a
launcher that was killed is reused by the next start.

### Windows

There is no app to build: the same `launcher.py` starts the services, the gateway and the chat, and the board opens in a
browser. What differs between the systems lives in `verticals/host/` (`posix.py`, `windows.py`), never in the launcher.

```powershell
npm --prefix web ci                 # once (or python tools/local.py setup)
python desktop/launcher.py          # UI: http://127.0.0.1:8288/ (builds desktop/build/web on first run)
python desktop/launcher.py mcp      # how to connect an agent to MCP
```

PostgreSQL 16 is found as `tools/local.py` finds it (see the main README); Python 3.12 is also found through the `py`
launcher. Closing the console window stops everything as Ctrl-C does. The API's and MCP server's output goes to `api.log`
and `mcp.log`, as on macOS. Claude's system prompt travels in a file (`--append-system-prompt-file`), because the
morning report's prompt is close to Windows' 32,767-character command line. Opening a task's session in a terminal is
macOS-only for now.

## Build the app

After step 1 above, on an Apple Silicon Mac with Homebrew `postgresql@16`, uv (Python 3.12) and
Xcode Command Line Tools:

```sh
python3 desktop/macos/bundle.py     # -> desktop/dist/Verticals.app, .dmg, .zip and -lite.zip
python3 desktop/macos/bundle.py --version 0.4   # version in Info.plist (default 0.2)
python3 desktop/macos/bundle.py --dev           # a dev build: the yellow icon instead of the white one
```

The icon is the board's mascot on a macOS tile: `macos/icon/AppIcon.icns` (white) and `AppIcon-dev.icns` (yellow, for
dev builds), drawn by `macos/icon/make_icon.py` (`.venv/bin/python desktop/macos/icon/make_icon.py` redraws both from
the repository's Playwright Chrome and macOS's `iconutil`).

The bundle mirrors the repository layout inside `Contents/Resources` (verticals/, desktop/, the
operator and morning-report skills) plus a trimmed Python 3.12 with the dependencies and PostgreSQL 16 with its
Homebrew libraries copied in and relinked; the build checks that no binary links outside the app
and runs initdb + `pg_trgm` from the bundle. The app keeps its data in
`~/Library/Application Support/Verticals` and never writes into itself; an update replaces the
whole bundle (see below).

Installing on another Mac: open the `.dmg`, drag Verticals to Applications, then remove the
quarantine (the app is ad-hoc signed, not notarized):
`xattr -dr com.apple.quarantine /Applications/Verticals.app`.

## Releases and updates

A release is started by hand: Actions → desktop release → Run workflow (or
`gh workflow run desktop-release.yml -f bump=minor`). The version is the latest release's with one part
up: patch (the default) 0.5 → 0.5.1, minor 0.5 → 0.6.0, major 0.5 → 1.0.0. `.github/workflows/desktop-release.yml` builds the UI and the app on a macOS runner
and leaves a draft release `v<version>` on the chosen commit with `Verticals.zip`,
`Verticals-lite.zip`, `release.json` (`min_macos` and the runtime's fingerprint) and `Verticals.dmg`.
Apps see the release only once it is published, so the last step is on GitHub: edit the draft's
text and press Publish.

The text starts as the merged PRs' titles. The app reads it this way:

```markdown
Goals can repeat every week

- Pick Every week in a goal's repeat menu
```

A line above the list is what gets better for the person, in a few words: the app shows it beside
the Update button. Without it the release installs at quit without a word, for fixes only. The `- `
items are the notes in the card. Headings, comments and other lines stay on the release page.

Updates never interrupt work:

- The app asks the GitHub API for the latest release at launch and every 6 hours. A newer one
  downloads at once in the background into `updates/` in the state folder; an interrupted download
  continues where it stopped. When the release's runtime (`pg/`, `python/`, `site/`, fingerprinted
  in `Resources/RUNTIME` by `bundle.py`) is the one the installed app has, it takes
  `Verticals-lite.zip`, a few MB without the runtime, and clones the runtime in from itself; the
  signature check then proves the result is the release byte for byte, and anything off falls back
  to `Verticals.zip`. `.pyc` files are built hash-based, so an unchanged runtime builds to the same
  bytes; a new Python, PostgreSQL or dependency changes the fingerprint and the next update is the
  whole app. The release workflow runs `desktop/macos/lite_check.py` against the previous release.
  The zip is checked against the asset's sha256, then the bundle id, the version and the
  signature. A failed background check shows nothing and comes back later (15 min, doubling up to
  6 h).
- A downloaded release with a `summary` shows a grey Update button in the title bar's right corner,
  the summary on its left. The button opens the notes, Restart and Skip This Version. Nothing else
  asks: ignored, the update installs when Vertical quits, and the next launch is the new version.
- With the window closed, a downloaded update installs once no agent is answering: Vertical quits,
  installs and comes back in the menu bar; MCP is away for those seconds. An install that failed
  waits for Restart instead.
- Restart waits while an agent is answering (`/__chat/busy`), sends the edits still waiting to be
  saved, quits and opens the new version on the same page. A Restart lost to a crash installs at the
  next launch from the files already downloaded.
- Skip This Version deletes the download; the next newer release starts over.
- Verticals → Check for Updates… answers in the same line, never in a window: the progress, then
  "Verticals 0.4 is the latest version" or the error, which opens to its reason and Try Again. A
  found update opens its card. The check also brings back a skipped version.
- The state (`updates/state.json`) survives quits and crashes. An install that fails keeps the old
  app and says why in the title bar.

This needs the repository to be public: the app sends no GitHub token. For testing,
`-ReleasesAPI <url>` points the check elsewhere and `-StateDir <path>` keeps the data apart (both
also work as `defaults write` keys, so a relaunched app keeps them).

The database survives an update three ways:

- Before publishing, the workflow runs `desktop/macos/upgrade_check.py` with the previous
  release: the old app makes a board, the new one starts on it. No release if the new one does not
  come up, does not serve the board, or has fewer rows in any table. Run it by hand on a copy of
  real data before a risky migration (Vertical quit, the folder is only read):
  `python3 desktop/macos/upgrade_check.py /Applications/Verticals.app desktop/dist/Verticals.app --state ~/Library/Application\ Support/Verticals`
- The install waits for PostgreSQL to stop (up to a minute, otherwise it waits for the next quit),
  then copies `postgres/` to `backups/<date>-<old version>/`; its last three copies stay, and
  nothing else in `backups/` is touched. The new bundle goes in with one atomic rename. Steps go
  to `update.log`.
- Migrations run in one transaction (`verticals/db/runner.py`): a failing one changes nothing.

To roll back, quit Vertical, move `postgres/` aside, copy a backup to `postgres/` and install the
matching `.dmg` from the release page.

- Chat bar at the bottom (⌘K); the conversation list opens on the left; agent picker with
  Agent / Model / Effort / Speed / Permissions; Enter queues while the agent works, ⌘Enter sends now.
- Each goal card gets a "discuss" button (on hover, next to the "…" menu) that opens a new
  conversation bound to that goal; the agent receives its id and link with every message.
- Agents see the screen context and use only the Vertical MCP tools (Claude runs with no built-in
  tools). Links to goals, docs and board dates open inside Vertical.
- Uses the local CLI's own sign-in; every answer counts against that account's limits.

## Reports

Something is wrong, or could be better: pictures dropped on the window (or pasted into the field) wait above the field, and with
them there what you type says what you see and what you want. ↵ makes a report (docs/design/bug-reports.md): a document with
your words, the pictures and the version, and a task with no date that holds it. There is nothing to pick: the agent tells
which kind it is from your words, once, and gets the words alone (`chat/report_kind.py` asks the Claude Code the chat runs, in a
conversation nobody sees, with no tools and no MCP servers; the pictures and the logs never go to a model). In the same answer it
names the task by its result, as the board names its tasks ("A card dragged to Friday stays there"), in the language of your words
and in at most 8 words; the report keeps your words as you wrote them, and with no name (no agent, a slow or unsure one) the task
takes your words. A bug, something that
went wrong, is made under `reports/bugs/` and also holds the last lines of the app's and the agent's logs; a request, something
that could be better, is made under `reports/requests/` and holds none (`GET /__report/facts?logs=0` opens no log). When the agent
cannot tell, is slow (25 seconds), fails, is Codex or is not there, it is a request: that shape loses nothing. A document holds
512 KiB, so the pictures are drawn smaller as JPEGs until they fit with the words and logs.

- **Send to developers** is a link to a new GitHub issue on this repository, filled in with the report's text as the
  document stands (the pictures cannot travel in a link: the issue ends with how many there were and to drag them in). It
  reads as what it is: `labels=bug` for a bug and `labels=enhancement` for a request, the repository's own labels (GitHub
  applies a label from a link only for someone who may label), and a request has no logs in it. GitHub does not publish its
  link limit; a link is kept to 6,000 characters, the oldest log lines going first and the issue saying how many. With ⌥
  held it is an email draft with the same text, to no address (`DEVELOPERS_EMAIL` in `web/src/lib/reportSend.ts` is empty;
  the repository publishes none).
- **What an agent reads of a report:** its pictures are data URLs inside the text, hundreds of kilobytes of base64, so every MCP read
  of a document or a goal (`doc_get`, `doc_revision`, `doc_create`/`doc_save`/`doc_restore`'s answers, `goal`) returns each as
  `[picture 1]`, `[picture 2]` and so on with every word as it is (`verticals/core/pictures.py`), and a placeholder the agent keeps
  in a body it saves (`doc_save`, `update` of one goal) is the picture again, so editing a report's words never costs it its
  pictures. The agent can open a screenshot with `doc_image`, giving its document id and placeholder number; it receives
  image content without adding base64 to the text read. The app's own views read the full text; the previews of a document (a chip's page, the Documents desk) are cut from the
  text without its pictures.
- **What the logs may say** is decided in `chat/report_facts.py`, not by a model: an entry is kept only in a shape that code
  knows, without the words of a goal or a document, a tool's answer, an error's own message, another server's tool names or the
  Mac's user name; the number of entries left out is told in the report.
- **Improve it** asks the agent for a design document in the report's task. Once the person agrees (a comment and Check
  again, or a word in the chat), the agent makes the change in a checkout of the source, with its tests, and opens a pull
  request whose address it adds to the task's notes. The installed app ships without a checkout: the gateway looks for one at
  `VERTICALS_SOURCE`, then `source` in the state folder's `config.json`, then the repository it runs from, then the usual
  folders (`~/verticals`, `~/Developer/verticals`, …). With none, or with Vertical-only access, the task and its documents
  still come and only the pull request waits. An explicitly selected checkout is also the working folder of new
  conversations, and of resumed conversations that used the default chat workspace. Sessions linked from other projects
  keep their own folder. Source validation is deferred until code work needs the checkout: it never blocks gateway startup.
  Morning report writing/checking, account probes and report classification use the private chat workspace, independently
  of source-folder permissions.

## Security notes

- Everything listens on 127.0.0.1. The gateway rejects foreign `Host`/`Origin` and cross-site
  requests; the UI bundle contains no token.
- MCP bearer tokens reach agents through owner-only files or the environment, never command lines.
- Agent processes get no variables of a parent Claude Code session.
- Codex keeps its existing CLI sign-in but disables inherited MCP servers and plugins for the
  desktop process. Its dedicated `verticals_desktop` server relays only to this app's local MCP
  endpoint. Startup checks the effective server list and refuses to start if another server
  remains enabled; the user's Codex configuration is not edited. The `verticals_desktop` name
  is reserved for this connection. Commands follow the selected access mode; the unattended morning turn disables the shell.
  Web search and app connectors remain disabled in this desktop connection.

## Status

MVP. Codex support follows the `app-server` protocol. Verified with Codex CLI
`0.155.0-alpha.16`, an existing ChatGPT sign-in, live model/usage discovery, a tool approval,
and a read-only board query returning sample goals through the local MCP relay. This checks
the backend flow; it does not establish every provider/model or packaged-app combination.
No Developer ID signing or notarization yet.

## Quick Entry

Press Command+Shift+Space to open a small black field above another application. The bubble shares SearchBar’s CSS and Commissioner font. Return saves an undated Inbox task and returns focus; ⌘Return creates a task, opens it in the same app and starts a linked agent conversation. Shift+Return adds a line. There are no action buttons. Escape discards input. Failed submissions keep the text.

Command+Shift+Space is the only default shortcut and uses Carbon without Accessibility permission. The tray’s Quick Entry command is also available. A custom modifier-only binding requires Accessibility; the app never prompts automatically.

Ask the agent to change the binding using `quick_entry_binding`; no binding settings are shown in the UI. Read with no arguments, or set `binding` to `cmd+shift+key:49`, `fn`, `key:49` (Space), or a macOS virtual key code prefixed with `ctrl+`, `alt+`, `shift+`, `cmd+`. Native registration is acknowledged, persisted, and the previous binding is retained on failure. Registration cannot prove that no other app also observes the gesture.

For an isolated native test copy, give it its own bundle identifier and set its defaults `StateDir`, `UIPort`, `APIPort`, `MCPPort`, and `PGPort`; the native launcher forwards the ports to its bundled backend. Point `ReleasesAPI` at an inert local URL to keep test copies out of release updates.

On first launch, a single Inbox task explains Quick Entry and changing the binding through the agent in that task. A saved marker keeps completed or deleted onboarding from returning.
