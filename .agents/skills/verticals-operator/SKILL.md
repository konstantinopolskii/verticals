---
name: verticals-operator
description: Read and mutate a Verticals board safely through its MCP tools. Use for board inventory, goal lookup, create/update/schedule/reparent/delete operations, evidence receipts, documents, comments, tags, sizing, carry-over handling, and post-write verification. Discover the live tool catalog, keep writes idempotent, preserve manual edits, and verify the rendered and raw state after every mutation.
---

# Verticals Operator

Use the configured Verticals MCP connection. Never print, copy, or store its bearer token in a command, document, card, tag, or log.

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
7. Report exact IDs, final hierarchy/schedule, evidence status, and discrepancies.

Batch related approved writes close together to reduce visible churn, but keep every logical write independently idempotent and verifiable.
