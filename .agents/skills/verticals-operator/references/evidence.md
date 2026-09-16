# Evidence receipts

Use evidence tools only when the live server exposes them.

## Status meaning

- `verified`: required factual claims are supported and material unknowns are explicit.
- `partial`: at least one primary source was checked, but required coverage is incomplete.
- `index_only`: only discovery indexes were checked.
- `unverified`: no usable verification exists.
- `stale`: server-computed; never send it as a stored status.

## Receipt rules

- Give each source a stable local ID, type, reference, date, and read scope.
- Store short paraphrased claims, not quotations or source content.
- Map every claim to existing source IDs.
- Keep unresolved questions factual and short.
- Set a source cutoff only through the latest point actually searched.
- Choose review timing by volatility: active operational work expires sooner than stable strategy.

## Write protocol

1. Draft content changes and evidence together.
2. Obtain approval for both unless the request explicitly authorizes the refresh.
3. Apply content changes first.
4. Reread the goal for current content and evidence revisions.
5. Write evidence with those expected revisions and a unique `client_token`.
6. On conflict, reread and reconsider; never guess revisions.
7. Reread and confirm the effective status and saved receipt.

If evidence tools are absent, keep the claim-source map only in current working notes. Do not emulate evidence with tags, body text, or an invented side ledger.
