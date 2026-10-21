# When the agent is signed out, the field signs it back in

The owner's chat and morning report stopped one morning: every Claude turn ended in "Failed to authenticate: OAuth session expired and could not be refreshed", shown raw in the field, once per message. Claude Code's own sign-in on the Mac had expired (`claude auth status` said `loggedIn: false`), and the only fix was a terminal command the field never mentioned. The owner: "in that case app should help me to do all the needed stuff."

## Behaviour

- A Claude turn that fails because the CLI is signed out ends with one message in the field instead of the raw error: **Claude Code is signed out on this Mac** · "Sign in once and your message goes again." · **Sign in**. The gateway knows it by the error's words ("Failed to authenticate", "OAuth", "not logged in", "/login", "Invalid API key") and confirms with `claude auth status`, which prints `loggedIn`. The message is the field's ask, the same balloon and buttons as "Allow Claude to use…", not a new form.
- **Sign in** runs `claude auth login` from the app, under the app's `CLAUDE_CONFIG_DIR` when it has one. The command opens the sign-in page in the browser. The message says "Approve in the browser". When the command prints the page's address, the message links it ("Open the sign-in page") for the case no browser came up.
- The gateway checks `claude auth status` every 2 seconds while the login runs. Signed in: the message says "Signed in", and the message that failed goes again by itself, in the same conversation with the same context. A morning report runs its morning turn again; a Replan, its Replan.
- If the login command ends without a sign-in, or 5 minutes pass, the ask comes back with **Sign in** and **Open in Terminal**. Terminal runs the same command through `agent_sessions.terminal_script`, for when the browser hand-off asks for a code to be typed. The status checks go on while Terminal is open.
- While the ask is open, another message in that conversation doesn't fail again: it waits behind the sign-in and goes after it. One ask per conversation, never two.
- Codex takes the same path with its own commands (`codex login`, and `codex login status`, whose exit code says signed in). The commands live in the agent table (`AGENTS` in `desktop/chat/chat.py`), so the gateway has one mechanism for both.
- Every other error shows as it does today.

## Done when

Static gateway tests with a fake `claude` that is signed out and then signed in: the ask replaces the raw error; Sign in runs the login command with the config folder; the status check resends the failed message once, with its context; a second message waits instead of failing; a login that ends without a sign-in brings back both buttons. A UI test of the balloon with the fake agent. The owner tries it in the app.
