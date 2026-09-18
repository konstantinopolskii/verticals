---
name: verticals-morning-report
description: Prepare an evidence-backed daily morning report from a configured Verticals board and optional work sources, then reconcile the same report after review. Use for pre-meeting status, decisions, unfinished promises, and post-meeting updates; not for creating goals or sending messages by default.
---

# Verticals Morning Report

Build one useful review surface, not a dump of the board. Read [setup.md](references/setup.md) when first using this skill in an environment or when a source/destination changes. Read [report-contract.md](references/report-contract.md) for the report and reconciliation rules.

## Before the morning conversation

1. Resolve the reader's timezone, reporting date, source cutoff, report destination, review preferences, and available connectors from the local setup. If a necessary choice is missing, ask; do not invent a schedule or filesystem location.
2. Read the prior report and unresolved reviewer comments. Inspect the relevant Verticals board, exact goals, and owning work sessions. Use other configured sources only where they can settle a material state, promise, dependency, or decision. Exclude the morning conversation that has not happened yet.
3. For each material input, follow the source to the actual goal, work session, document, message, or artifact. Verify whether it was incorporated and whether later events changed its status. A summary or old report is a locator, not proof of current delivery or acceptance.
4. Produce the report with an actual cutoff, concise navigation, attributed context, source links or references, next actor/action, unresolved decisions, and explicit coverage gaps. Preserve every still-open signal under its owner; do not turn a suggested action into a commitment.
5. If the configured workflow has both a local file and a native Verticals document, save identical content and read both back. If only one surface is configured, use that one. Disclose any failed sync instead of claiming publication.

## After review

Apply the reader's explicit decisions to the *same* report. Preserve original comments in history, keep unresolved comments visible, and verify any authorized task/document changes before clearing a comment or claiming a result. Do not repeat a full source scan just to incorporate a transcript or presentation correction. The reviewer, not the agent, accepts outcomes.

Reading and writing a report does not authorize goal creation, scheduling, closure, external sends, or new task sessions. Use `$verticals-operator` for an authorized Verticals mutation when available; otherwise leave the proposed change visible as pending. Keep secrets and machine-specific routing in local configuration, never in this skill or the report.

Return the report link or path, what materially changed, and any blockers. Do not paste a second full report into chat unless requested.
