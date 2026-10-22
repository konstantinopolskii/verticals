# The morning report reads every source, and a second agent checks it

A morning report is only as good as what it read. It reads every source, places every input, and is checked against the raw sources before the owner sees it.

## Behaviour

- **Access is chosen once in the app before the first automatic run.** Full access applies to Claude and Codex, including report writing and checking; the checker's instructions still require it to only read. Restricted modes keep their existing tool boundaries. Changing access in the agent menu takes effect on the next turn, including a new Codex process when its tool configuration changes.
- **Every source, from where the last report stopped.** The report reads each source by its document (`sources.md`) and starts each one at the last report's own cut-off for it.
- **Everything first, the rows second.** Every request the owner made, in a voice note, a chat or a call, becomes its own item with what comes out of it and who does it; "probably create…" counts as asked. Every other message gets a place too: a task, the Inbox, done by newer news, put off by the owner, context, or a gap. The report's end counts them per source, so a miss shows as a number.
- **A second agent checks it before it's ready,** with the raw sources and ten checks: every source covered, every input covered, continuity with the last report, the Inbox, the changes allowed, the current state, names, hierarchy and dates, where each item went, the published copy. Each check passes, fails or finds a gap. A gap is never a pass, and a fail sends the report back to be fixed. The checker may run at a lower effort than the report.
- **The report's shape:** what couldn't be read, on top in red; the check's verdict; the rows (the task, its purpose, Latest, Next action, and a cell for the owner's comment; a parent in bold, its children under it; names by result, dates in the schedule); what was closed since the last report, once, at the end; every source with its window and where its messages went.
- **The owner's comments land on the task,** word for word, then read back. A closed task leaves the table.
- **What's done since closes on the board too,** each with its evidence linked; the whole morning's changes are taken back at once from the report's answer (`agent-answer-undo.md`, PR #50).
- **While it works,** the agent's step shows inside the field.
- **Cost:** the quality is in the reading. A full report costs tens of millions of tokens, nearly all of them read again from cache; the checks of sources add nothing.

## Done when

Tests with the fake agent and sample sources: windows start at the last cut-off, every input is placed and counted, a failing check holds the report back, comments are saved word for word and read back. A sample report, before and after.
