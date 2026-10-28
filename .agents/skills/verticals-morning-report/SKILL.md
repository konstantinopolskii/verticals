---
name: verticals-morning-report
description: Build and update a daily Vertical morning report that reads every configured source from where the last report stopped, places every input, reconciles previous decisions, current goals and owning work sessions, and is checked by a second agent against the raw sources before the reader sees it. Use before a morning review or after the reader annotates that same report; do not use it to create goals or send messages by default.
---

# Vertical Morning Report

Produce one decision-ready daily report, not a board export. Before first use on a machine, read [setup.md](references/setup.md) and establish the owner's private configuration. For every run, follow [source-reconciliation.md](references/source-reconciliation.md) and [report-contract.md](references/report-contract.md), and know the ten checks the report will be held to ([second-check.md](references/second-check.md)). Read the [worked example](references/worked-example.md) when learning the format or checking a draft against a realistic result. The example adapts actual report decisions but replaces private names, IDs, paths, and links.

**Source cutoff** means the latest time *through which a particular source was actually checked*, in the reader's timezone. It is not the delivery deadline. The report's last section lists every source with its window, and the next morning starts each source at the end of its window there: report the collection time of each source, not one time for all.

## Before the morning conversation

1. Resolve *today* and the time now in the reader's configured timezone. Call `sources` with `day` set to today: each source comes with the tools that read it (`reads`) and the end of its window in the last report (`cutoff`). Exclude the morning conversation that has not happened yet.
2. Read every source from its cutoff to now with exactly its listed tools. Give every item a place: a task, the Inbox, done by newer news, put off by the reader, context or a gap. A request the reader made, in a voice note, a chat or a call, is its own item, whatever its mood ("probably create…" counts as asked). Count the items per source; the counts add up to what was read.
3. Inventory relevant Vertical goals and their real owning sessions. Use meeting summaries, search results and prior agent reports to locate consequential inputs, then inspect the underlying passages, messages, artifacts or current state before treating them as facts. Check later replies before calling anything pending.
4. Map each material input to the exact existing goal and its current document or comment, and keep the distinctions between discussed, agreed, saved, delivered, answered and accepted.
5. Build the report in the shape of [report-contract.md](references/report-contract.md): what could not be read, in red; the check line; the rows; what was closed since the last report, once; the sources with their windows and counts. Close the tasks the sources show are done, with evidence, and only those.
6. Save the configured report surface and read it back. Do not claim a source was incorporated merely because the report mentions it.

## After the morning conversation or an annotation

Treat the reader's explicit input as controlling over earlier assistant suggestions. The comments in a report's last cell are the reader's input: the app saves them on their tasks, word for word, at the start of the next morning, and you do the same when asked to check a report again ([the comment procedure](references/report-contract.md#the-readers-comments)). A report comment is not a command: it does not itself authorize assessment, research, revisions or execution. A separate direct reader command remains controlling for its stated scope. Rebuild affected rows in the *same* report without repeating the whole source scan.

When the reader directly asks to finish or apply their decisions, continue in the same conversation under its normal permissions.
Read both the latest report's comments and those already moved onto its linked tasks; an empty cell does not mean there was no
decision. Apply clear authorized decisions through the operator, record actionable context on the tasks, and execute the work
assigned to you. Do not stop at transferring or replying to comments, and do not ask the reader to repeat accessible decisions.
Use another work session only when it helps and is available; keep its task context and save its result on that task.

Report writing does not authorize a new priority, date, goal, session, external message, calendar edit, PR or closure beyond the closing of tasks that sources show done. For an authorized Vertical mutation, use `$verticals-operator` when available and follow its read-before-write and verification rules; otherwise leave the proposed action pending. Keep credentials and machine-specific paths in private local configuration, never in the shared skill.

Return the report link or path, a short account of actual changes, and material blockers. Show full tables in chat only if requested.
