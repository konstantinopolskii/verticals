# Verticals MCP operations

The current server exposes core tools plus optional families. Call `tools/list` when the runtime does not expose them natively.

## Core tools

| Tool | Purpose |
| --- | --- |
| `board` | Current multi-vertical board slice, value roots, direct children, ancestors, and progress. |
| `goal` | Authoritative detail for one goal, including ancestry and direct children. |
| `outline` | Compact readable subtree or active map. |
| `search` | Bounded title/body/tag/vertical search. |
| `create` | Create one goal or an approved nested tree. |
| `update` | Change content/status/ordering on one or more goals. |
| `schedule` | Set or clear vertical and anchor date. |
| `reparent` | Move a goal under another parent or detach it. |
| `delete` | Delete an exact goal; cascade only when every descendant is approved for deletion. |

Optional families can include evidence, parking, tags, size reporting, carry-over acknowledgement, documents, and comments. Discover them instead of assuming names or schemas.

## Inventory limits

- `board` is a dated slice, not a complete registry.
- `search` is bounded and may not expose every status filter.
- `outline` is useful for orientation; use `goal` before writes.
- Traverse known roots and exact historical IDs when a cleanup requires complete coverage.
- State the cutoff and blind spots when the inventory cannot be proven complete.

## Value roots

A value is a parentless Life goal. Every other active goal should inherit exactly one value root through its primary-parent chain.

- Set color and short labels only on value roots when the server enforces inherited value metadata.
- Preserve root order unless a strategy-order change is approved.
- Do not use child colors or unrooted cards to imitate grouping.

## Propagation traps

Schedule, park, and reparent writes may coerce descendants to the parent's rung or period. After each operation, verify `vertical`, `anchor_date`, `period_key`, parent ID, and direct children. A successful response is not enough.

If a cascade touches a goal outside the approved set, stop. Repair only when the intended state is explicit, already authorized, and not superseded by a newer manual edit.

## Connection fallback

Prefer the agent runtime's configured MCP tools. If only streamable HTTP is available:

1. Send `initialize`.
2. Preserve the returned `Mcp-Session-Id`.
3. Send `notifications/initialized` with that session header.
4. Include the same header on later `tools/list` and `tools/call` requests.

Parse structured content and keep logs compact. Never expose authorization headers or tokens.
