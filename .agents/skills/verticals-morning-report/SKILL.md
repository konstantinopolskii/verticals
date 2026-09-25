---
name: verticals-morning-report
description: Build and update a daily Verticals morning report that reconciles previous decisions, current goals, owning work sessions, meeting summaries, and configured source systems. Use before a morning review or after the reader annotates that same report; do not use it to create goals or send messages by default.
---

# Verticals Morning Report

Produce one decision-ready daily report, not a board export. Before first use on a machine, read [setup.md](references/setup.md) and establish the owner's private configuration. For every run, follow [source-reconciliation.md](references/source-reconciliation.md) and [report-contract.md](references/report-contract.md). Read the [worked example](references/worked-example.md) when learning the format or checking a draft against a realistic result. The example adapts actual report decisions but replaces private names, IDs, paths, and links.

**Source cutoff** means the latest time *through which a particular source was actually checked*, in the reader's timezone. It is not the delivery deadline. A targeted check at 09:48 does not imply every source was refreshed through 09:48; report the wider collection cutoff and the narrower exception separately.

## Before the morning conversation

1. Resolve *today* in the reader's configured timezone. Find the latest completed report that the reader actually reviewed or commented on; compare local and native copies, revisions, comments, and any newer partial draft. Use the reviewed report as continuity baseline, but carry forward verified work from newer drafts. Set actual per-source windows. Exclude the morning conversation that has not happened yet.
2. Inventory relevant Verticals goals and their real owning sessions. Use meeting summaries, search results, and prior agent reports to locate consequential inputs, then inspect the underlying passages, messages, artifacts, or current state before treating them as facts.
3. Map each material input to the exact existing goal/session and its current document or comment. Check whether the input was saved there, whether a later reply changed the state, and what remains for whom. Preserve prior unresolved signals; distinguish discussed, agreed, saved, delivered, recipient response, and reader acceptance.
4. Build the report in the shape specified by [report-contract.md](references/report-contract.md): a short change summary; linked navigation for decisions, today and relevant near-term work; then attributed context, commitments, calendar implications, pending comments, source coverage, and gaps. Include enough detail for the reader to discuss a decision without reopening every source.
5. Save and read back the configured report surface. If the owner configured both a local file and a Verticals document, verify that they match. Confirm that the connection used for any goal/document write is the configured authoritative backend; a successful write to a local mirror is not a hosted save. Do not claim a source was incorporated merely because the report mentions it.

## After annotations or the morning conversation

Treat the reader's explicit input as controlling over earlier assistant suggestions. Transfer comments discovered in the report's fourth column verbatim to the exact existing Verticals task, following [the comment-transfer procedure](references/report-contract.md#comments-and-second-copy). Deduplicate and verify authoritative readback, then clear the report cell to `[]`; implementation is not a condition for clearing it. Keep failed or unresolved transfers visible. Preserve provenance and original text in history, and keep unfinished work in the task row's next-action cell.

An owning-session notification is information only: identify the saved input and require a separate direct command from the reader before assessment, research, revisions, or execution. A report comment or forwarded notification does not itself authorize that work. A separate direct reader command remains controlling for its stated scope. Rebuild affected rows in the *same* report without repeating the whole source scan. Neither successful transfer nor notification establishes implementation or reader acceptance.

Report writing does not authorize a new priority, date, goal, session, external message, calendar edit, PR, or closure. For an authorized Verticals mutation, use `$verticals-operator` when available and follow its read-before-write and verification rules; otherwise leave the proposed action pending. Keep credentials and machine-specific paths in private local configuration, never in the shared skill.

Return the report link or path, a short account of actual changes, and material blockers. Show full tables in chat only if requested.
