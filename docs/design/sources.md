# Sources: a document each, checked every hour without a model

A source is anything the morning report reads: a chat service, a calendar, mail, a repository, a folder. Each one is simply a document, and the app checks it on a timer for free.

## Behaviour

- **A document per source,** in a Sources group, written by the agent from one sentence ("read my calendar for the coming week"). It says what the source gives the report, how to read it, since when, how it is checked, and the fixes the agent may make alone.
- **One check per source,** read-only, of one of five kinds, written once by the agent into the document: an address answers (http); an MCP tool answers with the right field (mcp); a command exits well and a number in its output stays within limits (cmd); a file is fresh and its last line says the right thing (file); a host name resolves (dns). The app runs every check every hour, with no model and no tokens.
- **The owner approves a check once before it runs.** An address, an MCP tool, a command, a file and a host-name lookup each reach something, and can carry data out or bring it in (a lookup sends the name it is given to a resolver), so each runs only after the owner approves that exact check; the app shows it in words beside Approve, and any change to it asks again. The agent writes checks and cannot approve one. Only the app's own check of the agent's servers runs without approval.
- **Every connection too:** the app asks each MCP server the agent uses whether it answers, with no model (`claude mcp list` and the Codex equivalent).
- **Stable:** a source turns red only after two failures in a row, five minutes apart; a single failure is checked again quietly. A check says why in one line ("last exit code 127").
- **The agent comes only when needed.** When a source stays red, it reads the failure once, says what it means, and makes a fix the source's document allows; anything else stays red. When a source is added or changed, it writes the check; once the owner has approved it, it runs it once and sets the value beside the raw output, since a check can be stable and still wrong.
- **In the Inbox,** a third row, Sources, under Documents: a tile per source with its state, "checked 07:00" or, in red, "not answering since 06:00". A red source also opens the next morning report. With no sources yet the row does not vanish: it says so and names the servers the agent reaches, from the Connections check ("No sources yet. The agent reaches Telegram, Coin and mail. Tell it what to read each morning, in one sentence."), and the morning report says the same one line in its red block and has no Sources table.
- **A source has a check.** A document under the sources folder without a check block is a plain document: not a source, not listed, not checked, not in the row, never red for want of a check. The app's own Connections check is not a source either: the Inbox shows it, the agent's list and the report leave it out.
- **Later, in the cloud:** each check says where it must run, here (it needs this Mac: a job, a file, a local service) or anywhere (an address, a name, a remote server). A cloud server runs the anywhere checks; the Mac runs its own and sends their results; a Mac that is asleep leaves its checks grey, "not checked since 23:10", never red.

## Done when

Core tests for each kind of check and the two-failures rule; a UI test for the Sources row and a red tile; the agent's tool to add a source writes its check and, once the owner has approved it, its first result. Before and after pictures.
