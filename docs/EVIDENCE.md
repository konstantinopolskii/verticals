# Agent evidence metadata

This is the contract for goal evidence in the shared Verticals repository. It documents the implemented database, core, and MCP behavior. The executable sources of truth are `verticals/db/migrations/007_evidence.sql`, `verticals/core/evidence.py`, and `verticals/mcp/evidence.py`.

Evidence is separate from a goal's human-readable body and tags. The server stores a receipt; it does not discover sources or verify claims for an agent.

## 1. Purpose

An evidence receipt records which sources an agent read, which claims those sources support, what remains unresolved, and when verification should be reviewed. Source content itself does not belong in the receipt. Evidence writes never change the goal's `updated_at` or `content_revision`.

## 2. Boundaries

The goal body remains for human context and the intended result. Do not put evidence status, source inventories, or service metadata into the body or tags. Evidence writes are available through MCP only; HTTP and other MCP readers expose summaries.

## 3. Storage and content revision

### 3.1 Content revision

Migration `007_evidence.sql` adds `goals.content_revision` and one owner-scoped `goal_evidence` row per goal. A database trigger increments `content_revision` when title, body, parent, vertical, anchor date, done state, tags, or repeat rule changes. Presentation changes such as color and sibling position do not increment it. Deleting a goal also deletes its evidence row.

### 3.2 Trigger ownership

The database trigger is the only writer of `content_revision`. It observes meaningful goal changes regardless of whether they came through HTTP or MCP. Derived fields such as path, depth, and period key do not cause an additional bump.

### 3.3 Evidence row

The evidence row stores `status`, `verified_at`, `source_cutoff_at`, `review_after`, `verified_against_revision`, `evidence_revision`, and the JSON payload. The database and core enforce owner scoping and optimistic revisions. Do not calculate or write `content_revision` from a client.

## 4. Payload shape

`evidence_update.payload` is a JSON object with only these top-level keys:

```json
{
  "identity": {
    "project": "optional string",
    "person": "optional string",
    "disambiguation": "optional string"
  },
  "sources": [
    {
      "id": "S1",
      "type": "source type",
      "ref": "source reference",
      "date": "YYYY-MM-DD",
      "read_scope": "what was actually read"
    }
  ],
  "claims": [
    {
      "id": "C1",
      "text": "short paraphrase supported by S1",
      "source_ids": ["S1"]
    }
  ],
  "unresolved": ["specific remaining question"]
}
```

`identity`, `sources`, `claims`, and `unresolved` may be omitted when not applicable. `identity` accepts only `project`, `person`, and `disambiguation`, each a string. Every source requires a non-empty, unique `id`; its optional `type`, `ref`, `date`, and `read_scope` fields must be strings when supplied. Every claim requires non-empty `id` and `text`; `source_ids` is a list of IDs present in this payload's `sources`. Every unresolved item is a string. Unknown keys are refused at every object level.

Limits: at most 32 sources, 64 claims, and 32 unresolved items; at most 32 KiB after canonical JSON encoding. `claims[].text` must be the agent's short paraphrase, never a quotation or transcript excerpt. Store a reference in `sources[].ref`, not the source content. Read scope must reflect what was actually inspected, not what a search result suggested.

The code validates types and references. The agent remains responsible for whether a source truly supports a claim. A technically valid empty `source_ids` list does not substantiate a factual claim.

## 5. Effective status

Stored statuses are `unverified`, `index_only`, `partial`, and `verified`. The server computes `stale` on reads; clients never store it.

| Condition | Effective status |
| --- | --- |
| No evidence row | `unverified` |
| Stored status is not `verified` | Stored status |
| Verified row's `verified_against_revision` differs from the goal's `content_revision` | `stale` |
| Verified row has `review_after` at or before the read time | `stale` |
| Otherwise | `verified` |

`review_after = null` means no time-based expiry, but a content change can still make a verified row stale. A partial or index-only receipt remains partial or index-only even when content changes; agents must revisit those states independently.

## 6. MCP surface

### 6.1 Readers

`board`, `search`, and `outline` carry only compact evidence summaries: effective `status`, `verified_at`, and `review_after`. `goal` returns the full receipt, including payload, source cutoff, content revision, verified-against revision, and evidence revision. Use `goal` before updating a receipt.

### 6.2 `evidence_update`

Required arguments: `goal_id`, `expected_content_revision`, stored `status`, `payload`, and a non-empty `client_token`. Optional arguments: `expected_evidence_revision` (omit for the first receipt), `verified_at`, `source_cutoff_at`, and `review_after`. Timestamps must be ISO 8601 with a UTC offset. A `verified` row requires `verified_at`.

Apply content edits first, reread `goal`, then write evidence against its current `content_revision` and `evidence_revision`. A revision mismatch returns 409; reread and reconsider rather than guessing a new revision. The same `client_token` with exactly the same arguments is an idempotent replay within 24 hours. Unknown and foreign goal IDs return the same 404 shape. A successful evidence write does not modify the goal row.

Set `source_cutoff_at` only through the latest point actually searched. Choose `review_after` according to how quickly the evidence can change.

### 6.3 `evidence_due`

The due-worklist reader filters effective `unverified`, `index_only`, `partial`, and `stale` states. It accepts an optional `due_before` timestamp, status and vertical filters, `limit` (default 50, maximum 200), and an opaque cursor. Results are slim rows without payload. Follow `next_cursor` to continue; use `goal` for full evidence.

## 7. Repeating goals

A newly materialized occurrence is a new goal with no evidence row and starts `unverified`. Do not copy the previous occurrence's receipt automatically.

## 8. Security and ownership

All evidence reads and writes are owner-scoped. The evidence table has a composite foreign key to the goal's ID and owner. An unknown ID and another owner's ID are indistinguishable to an evidence writer.

## 9. UI boundary

The UI may display evidence status read from the API, but it is not an evidence writer. Agents write receipts through MCP. This separation does not authorize adding a new HTTP write route.

## 10. Verification

The repository's `tests/core/test_evidence.py` and `tests/mcp/test_evidence_tools.py` exercise validation, revision conflicts, effective status, owner scoping, idempotency, slim worklist results, and repeating-goal behavior. The current MCP schema is defined in `verticals/mcp/evidence.py`; consult it for the exact live argument surface.
