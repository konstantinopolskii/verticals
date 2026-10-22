---
name: verticals-operator
description: Read and mutate a Vertical board safely through its MCP tools. Use for board inventory, goal lookup, create/update/schedule/reparent/delete operations, evidence receipts, documents, comments, tags, sizing, carry-over handling, and post-write verification. Discover the live tool catalog, keep writes idempotent, preserve manual edits, and verify the rendered and raw state after every mutation.
---

# Vertical Operator

Use the configured Vertical MCP connection. Never print, copy, or store its bearer token in a command, document, card, tag, or log.

Read [mcp-operations.md](references/mcp-operations.md) before writing. Read [evidence.md](references/evidence.md) when evidence tools are available.

## Operating rules

1. Discover the live tool catalog. Do not assume every deployment exposes every optional family.
2. Read before writing: board or outline for orientation, then `goal` for authoritative detail.
3. Treat the user's latest manual board edit as authoritative.
4. Use a unique stable `client_token` for each logical write. Reuse it only for an exact retry.
5. Apply only an approved mutation set. Preserve unrelated state.
6. After content changes, reread the goal before writing evidence.
7. After schedule, park, or reparent operations, reread the target and descendants because placement may cascade.
8. On conflict, reread and reconsider. Never overwrite or blindly retry.
9. Verify both raw state and the user-facing board after propagation.

## A step's date

A step's date decides where it shows. A step gets a date only when the owner wants to track it on the board; a date the same as its parent's puts it on the board under the parent. An agent's checklist, its working steps and tasks for sub-agents are created without a date (vertical and anchor_date null): they live inside the parent, show when it is opened, and in the Inbox. Removing a goal's date puts a parentless goal in the Inbox and keeps a step inside its parent.

## Read sequence

Use the smallest sufficient calls:

- `board` for the current multi-vertical slice;
- `outline` for a compact subtree or full active map;
- `search` to locate candidate goals;
- `goal` for authoritative body, ancestry, children, revisions, evidence, documents, and related metadata.

Board visibility alone is not proof of raw placement: carry-over rows can make an old period appear current.

## Mutation sequence

1. Reread every target.
2. Compare current state with the approved diff.
3. Stop if a newer manual edit or unexpected dependency changes the decision.
4. Apply the smallest mutation.
5. Reread affected goals and direct descendants.
6. Reread the relevant board slice and value subtree.
7. Report the final hierarchy/schedule, evidence status, and discrepancies, naming goals by title.

Batch related approved writes close together to reduce visible churn, but keep every logical write independently idempotent and verifiable.
