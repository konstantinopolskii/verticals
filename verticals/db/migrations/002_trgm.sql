-- verticals/db/migrations/002_trgm.sql — WP-03. Substring search, not full-text: `to_tsvector`
-- is lexeme-based and cannot match `cycl` -> `bicycles` (law L7; ARCHITECTURE.md §3's
-- corrected decision). `pg_trgm` is a stock contrib module, already present wherever
-- `pgvector` is, so this adds no dependency of substance.
--
-- The one statement in this whole migration set that needs elevated (database-level
-- CREATE EXTENSION) privilege sits alone in its own file, which is what lets the runner's
-- remediation message point at this file and this statement specifically when it is the one
-- a role lacks privilege for (AC-005/S-111c). The runner applies the whole invocation in one
-- transaction, so a failure here also rolls back 001's work from this same invocation —
-- nothing is left half-migrated either way.
--
-- Verified: `goals_search` is a working GIN trigram index — `ILIKE '%cycl%'` finds exactly
-- the four seeded rows containing "bicycles"/"recycling"/"Cycle"/"Cyan" and none of the
-- decoys (tests/core/test_search.py, S-26).
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE INDEX goals_search ON goals USING GIN ((title || ' ' || body) gin_trgm_ops);
