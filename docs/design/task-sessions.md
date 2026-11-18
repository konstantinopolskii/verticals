# Every task has its session, in Vertical, Claude or Codex

A task's conversation is one session with two doors: Vertical, and the place it lives, Claude or Codex. Either door opens the same session, and a session begun outside links back to its task.

## Behaviour

- **Already agreed and partly built:** Discuss continues a task's latest conversation wherever it started, and the task's links list its conversations first, each with its agent's mark. Not built: opening one where it lives, and sessions begun outside.
- **The menu's Agent section** gets Start work and Open in ›. Start work hands the task to the agent in a new session of its own, in the chat's permission mode, with the agent the task last worked with. Open in › lists the task's sessions, newest first ("Claude · 5 min ago", "Codex · 2 days ago"), and opens the one picked where it lives; with no session it is pale.
- **Where it lives:** a Codex thread opens by its link (`codex://threads/<id>`); a Claude session opens in the Claude app by its id, or in Terminal with `claude --resume <id>` from the session's folder. The open icon at the end of a session's row in the task's links does the same.
- **In Codex's list:** new chats begun in Vertical get a task or first-message title and are assigned to a **Verticals** section. Displaying that section requires Codex's server-backed sidebar; older local-only sidebars show names but keep the chats in their main list. Existing chats are not migrated: manual names, sections and later moves are preserved, including externally linked sessions. Unsupported sidebar APIs do not stop a conversation or change its access.
- **Visible:** each session's row says when it last moved, read from the session's file on disk. While a session works on the task, the task's card shows the field's turning line at its end.
- **And back:** in Claude or Codex the agent links its session to the task with one new tool in Vertical's MCP server, which both already reach. A new `verticals://goal/<id>` address opens the task in the app, and a session started from Vertical begins with it.
- **Continued outside without a word to Vertical:** Vertical watches the files of each task's known sessions, their size and time on disk, with no model and no tokens. When one grows while Vertical didn't drive it, the row says "Continued in Claude · 3 min ago" and the card shows the agent's mark. Discuss then resumes the same session, so its context is already in sync and nothing is read again. What Vertical writes itself is not that: a turn it runs, the lines just after it, and the last lines an agent's CLI writes as Vertical closes it (the app quitting or restarting, a reset, ten minutes with no turn), also when the gateway that looks next is a new one. A session started outside is linked when its agent calls the tool, or when it carries the task's `verticals://` link.
- **Connecting:** the menu bar's "Connect Claude Code" is named by what it does, "Use Verticals in Claude Code", with a tick once it is done, and "Use Verticals in Codex" stands beside it. The click is the consent: nothing is written into another app's settings before it.
- **To test first:** whether the Claude app opens a session the app's agent started; whether a session begun in another folder resumes from Vertical, since Claude keeps sessions per folder; whether the Codex app lists the threads the app's Codex starts.

## Done when

Tests with the fake agent: Start work makes a session tied to the task; Open in › lists sessions and builds the right link; a session file growing outside marks the row; the MCP tool links a session; `verticals://goal/<id>` opens the task. Before and after pictures.
