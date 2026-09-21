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

Treat the reader's explicit input as controlling over earlier assistant suggestions. Recheck affected goals, sessions, comments, and conditions; apply only authorized changes and verify them. Rebuild the affected rows and supporting context in the *same* report, preserving original comments in history and leaving unresolved ones visible. Do not repeat the entire source scan for a targeted correction. A dispatched instruction is not an implemented result, and neither an agent nor a recipient can accept the reader's work for them.

Report writing does not authorize a new priority, date, goal, session, external message, calendar edit, PR, or closure. For an authorized Verticals mutation, use `$verticals-operator` when available and follow its read-before-write and verification rules; otherwise leave the proposed action pending. Keep credentials and machine-specific paths in private local configuration, never in the shared skill.

Return the report link or path, a short account of actual changes, and material blockers. Show full tables in chat only if requested.
