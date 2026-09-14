-- verticals/db/migrations/007_evidence.sql — agent evidence metadata (docs/EVIDENCE.md, WP-33).
--
-- Two additions. First, `goals.content_revision`: a counter of MEANING changes, bumped by the
-- trigger below and by nothing else. The trigger is deliberately the sole writer — this repo has
-- two write paths (HTTP API and MCP) and an application-level bump WOULD drift between them;
-- a database that decides freshness itself cannot. Second, `goal_evidence`: one row per goal,
-- the agent's record of how it verified what it wrote — sources, claims, unresolved questions —
-- in a jsonb payload, with top-level columns only for what `evidence_due` filters and sorts on.
--
-- Evidence living in its own table is what makes the spec's core invariant structural rather
-- than disciplinary: an evidence write cannot touch `goals`, so it cannot bump
-- `content_revision`, so verification can never invalidate itself.
--
-- Forward-only and safe on a populated database (`verticals/db/runner.py` refuses downgrades):
-- ADD COLUMN with a constant DEFAULT rewrites no rows on PG 11+; the UNIQUE constraint builds
-- one index over (id, owner), which no existing data can violate (id is already the PK); the
-- trigger fires only on future UPDATEs.

ALTER TABLE goals
  ADD COLUMN content_revision INTEGER NOT NULL DEFAULT 0;

-- goal_evidence's composite FK needs a unique constraint on the referenced PAIR — the PK on id
-- alone does not provide one. This is what makes an evidence row whose owner drifted from its
-- goal's owner unrepresentable, not merely unlikely.
ALTER TABLE goals
  ADD CONSTRAINT goals_id_owner_unique UNIQUE (id, owner);

-- Bumps when the goal's MEANING changes. Watched: title, body, parent_id, vertical, anchor_date,
-- done (as a NULL<->NOT NULL transition — the timestamp value is noise), tags (any change; a
-- binary rule, no taxonomy of "significant" tags), repeat_rule (recurrence changes the meaning
-- of the obligation). Deliberately NOT watched (owner ruling 2026-08-11, docs/EVIDENCE.md §3.2):
-- color and position (presentation), repeat_series_id/index/start_date (occurrence identity,
-- immutable after mint — 006's goals_repeat_occurrence depends on that), path/depth/period_key
-- (derived from parent_id and vertical+anchor_date; watching source and derivation would
-- double-bump). One UPDATE statement = one meaning change = +1, however many columns it touched.
CREATE FUNCTION goals_bump_content_revision() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF NEW.title          IS DISTINCT FROM OLD.title
     OR NEW.body        IS DISTINCT FROM OLD.body
     OR NEW.parent_id   IS DISTINCT FROM OLD.parent_id
     OR NEW.vertical     IS DISTINCT FROM OLD.vertical
     OR NEW.anchor_date IS DISTINCT FROM OLD.anchor_date
     OR (NEW.done_at IS NULL) <> (OLD.done_at IS NULL)
     OR NEW.tags        IS DISTINCT FROM OLD.tags
     OR NEW.repeat_rule IS DISTINCT FROM OLD.repeat_rule
  THEN
    NEW.content_revision := OLD.content_revision + 1;
  END IF;
  RETURN NEW;
END $$;

CREATE TRIGGER goals_content_revision
  BEFORE UPDATE ON goals
  FOR EACH ROW EXECUTE FUNCTION goals_bump_content_revision();

-- Stored statuses only — `stale` is COMPUTED at read time (docs/EVIDENCE.md §5) and never
-- stored: a stored stale would need its own invalidation, which is the exact self-reference
-- the computed form exists to avoid. The payload is validated at the tool layer
-- (`core/evidence.py`); the database asserts only that it is an object — the same stance
-- 006 takes on repeat_rule.
CREATE TABLE goal_evidence (
  goal_id           TEXT NOT NULL PRIMARY KEY,
  owner             TEXT NOT NULL,

  status            TEXT NOT NULL
                      CHECK (status IN ('unverified','index_only','partial','verified')),
  verified_at       TIMESTAMPTZ,
  source_cutoff_at  TIMESTAMPTZ,
  review_after      TIMESTAMPTZ,
  verified_against_revision INTEGER NOT NULL,

  payload           JSONB NOT NULL DEFAULT '{}'
                      CHECK (jsonb_typeof(payload) = 'object'),

  -- Concurrency guard for two agents editing the same receipts: `evidence_update` checks the
  -- caller's expected value and increments on every real write. In from day one — one integer
  -- and one WHERE clause now, versus retrofitting after a lost write.
  evidence_revision INTEGER NOT NULL DEFAULT 0,
  updated_at        TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),

  -- A verified row without a timestamp is a contradiction; keep it unrepresentable.
  CONSTRAINT verified_has_timestamp
    CHECK (status <> 'verified' OR verified_at IS NOT NULL),

  FOREIGN KEY (goal_id, owner) REFERENCES goals (id, owner) ON DELETE CASCADE
);

-- `evidence_due`'s scan: owner-scoped, ordered by review_after. NULLS FIRST is the query's own
-- ORDER BY; the btree serves both directions regardless.
CREATE INDEX goal_evidence_due ON goal_evidence (owner, review_after);
