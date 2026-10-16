# The report's shape

One report a day is one document, `reports/morning/<YYYY-MM-DD>.md`, titled `Morning report — <d Month YYYY>` and linked to the open "Morning report" task. The title is the document's own: the body does not repeat it. Read from top to bottom, the document has the parts below, in this order. A part with nothing to say is left out, except the check line and the sources. [worked-example.md](worked-example.md) shows a whole report.

Code reads four places in it: the red block, the check line, the rows' last cell and the sources. Keep their shapes exactly as written here.

## 1. What could not be read, in red

A fenced block named `unread`, at the very top, one line for each source or tool: its name, what happened, since when.

````
```unread
Mail: waiting for your Approve, so it was not read.
Team chat: list_messages answered with an error at 06:51.
```
````

It holds every source that is red or waiting for the reader's Approve, every tool that was declined or failed, and every source with no tool listed for reading it. The app draws it in red. Leave it out when everything was read. A source named here still has its row in the sources, with the window it had before.

A source is a document under `sources/` with a check block; a document there without one is a plain document, and the app's own Connections check is not a source. With no sources at all, the block is one line, `No sources yet. The agent reaches chat and mail. Tell it what to read each morning, in one sentence.`, naming the servers the Connections check found answering, and the report has no Sources section.

## 2. The check

One line, directly under the red block (or at the very top when there is none), written as:

`Not checked yet: a second agent is reading it against the sources.`

Write that line and no verdict. A second agent reads the report against the raw sources and the app puts its verdict in this place: how many of ten checks passed, and a short table of every one that did not. [second-check.md](second-check.md) lists the ten. The reader is told the report is ready only after it has been checked.

## 3. The rows

Under these headings, in this order, leaving out the ones with no rows: `## Inbox — decisions needed`, `## Today`, `## This week — keep in mind`. Under each, one table with exactly these columns:

| Task | Purpose | Latest | Next action | Your comment |
| --- | --- | --- | --- | --- |

- **Task:** the task linked as `[Name](goal:<id>)`, with its name from the board, never reworded. A task with children is **bold** (`**[Name](goal:<id>)**`), and its children follow on the lines under it, each starting with an en dash and a space (`– [Name](goal:<id>)`); only real children from the board. In the Inbox group, a proposal that has no task yet is named by its result ("Launch plan is shared", not "Work on the launch plan") and links nothing.
- **Purpose:** the result the task is for, in one sentence. It stays the same from one report to the next.
- **Latest:** what changed since the last report, only what a source shows, in one or two sentences. Write dates as the board's schedule does: `Fri 25 Sep`, `21–27 Sep`, `August`, `Q3`; never "yesterday" or "last week". Say a thing once: what the Purpose already says is not repeated.
- **Next action:** who acts next, and what. Say when it waits for the reader's own command.
- **Your comment:** empty. The reader writes there.

One main outcome to a row. A short list of children may not hide a blocker or a promise: say its consequence in the parent's row. Keep the reader's priority order. A carried-over date keeps its date and is labelled as carried over; an old date is not a new priority. A closed task is not a row.

Say which state a thing is in, and no more: discussed, agreed, saved, delivered, answered by the recipient, accepted by the reader. A proposal is not a promise, a merged change is not the reader's acceptance, and a talk about payment is not money received. Check later replies before calling a message or a handoff pending.

## 4. What was closed since the last report

`## Closed since the last report`, once, after the rows. One line for each task: `- [Name](goal:<id>): what shows it is done, and in which source.` Close a task only when a source shows it done beyond doubt and the reader has not left it open on purpose. Close it on the board first (`update` with `done` true), then record how you know with `evidence_update` (the source, the claim in your own words, the source's cut-off). A closed task is listed here once and never in the rows.

## 5. The sources

The last section, `## Sources`. Its first line says the zone the times are in, as the context names it:

`Times in Europe/Berlin.`

Then one table with a row for every source, in this shape, the numbers after `Read` being counts (with no sources at all, this section is left out; see the red block above):

| Source | Window | Read | Tasks | Inbox | Done | Put off | Context | Gap |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| [Team chat](doc:sources/team-chat.md) | 2026-10-11 18:40 – 2026-10-12 06:57 | 42 | 11 | 4 | 6 | 3 | 15 | 3 |

- **Source:** the source's document, linked as `doc:<its path>`.
- **Window:** from where the last report stopped reading it (`cutoff`) to the time you began (`Now:`), as `YYYY-MM-DD HH:MM – YYYY-MM-DD HH:MM` in the zone above. The next morning starts here. A source you could not read keeps the window it had: both times are its old end, and every count is 0.
- **Read:** how many items the source gave inside the window: messages of a chat, events of a calendar, threads of a mailbox. The second agent counts them again.
- **The six after it** say where those items went, and add up to `Read`, to the last one: a **task** (it became a row or went into one), the **Inbox** (it needs the reader's decision), **done** (newer news answered or finished it), **put off** (the reader put it off), **context** (it changes no row) or a **gap** (you could not place or understand it). Every request the reader made, in a voice note, a chat or a call, is its own item with what comes out of it and who does it; "probably create…" counts as asked.

A row whose counts do not add up is a message with no place: the app fails the check on it.

## The reader's comments

The reader's words in a row's last cell are input, not an order. At the start of each morning the app saves every comment in the last report's cells on its task, word for word, reads each back from the thread, and clears the cell; the ask lists them. Do not save them a second time and do not act on them.

When the reader later asks you to check a report again, do the same for the comments in it: for each, `comment_add` on the row's task with the cell's words exactly as written (no summary, no fixed punctuation), read it back with `comments` and compare, then clear the cell and add "Your comment is on the task." to Next action. Check the task's comments first and reuse an exact copy. If the readback differs or the task is unclear, leave the cell and say why in Next action. Keep unfinished work in Next action. A task that is closed leaves the table. Edit only the cells you change, in the same dated report: do not make a second briefing.
