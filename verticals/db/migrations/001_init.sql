-- verticals/db/migrations/001_init.sql — WP-03. Enums, `goals`, five indexes, five CHECK
-- constraints: the three frozen in ARCHITECTURE.md §3 (vertical_period_together,
-- vertical_needs_anchor, color_is_canon) plus IR-11's two bounds (depth_bounded: depth <= 32;
-- tags_bounded: cardinality(tags) <= 32 — docs/IMPLEMENTATION.md §0.3). These two are a
-- schema-level backstop only: the operative, agent-facing tag limit is 16, enforced pre-write
-- in core/ (docs/E2E.md S-108 note); 32 exists so a caller that bypasses core/ still cannot
-- push `path` toward the btree row-size ceiling (~depth 300).
--
-- The pg_trgm-dependent search index is deliberately not here — it lives alone in
-- 002_trgm.sql, the one statement in this migration set that needs database-level
-- CREATE EXTENSION privilege, so a role that lacks it fails on exactly that file and
-- statement (AC-005/S-111c) rather than here. `schema_version` is not created by any
-- numbered file either: the runner bootstraps it independently (verticals/db/runner.py),
-- so `status` never requires applying a migration first.
--
-- Verified against a real Postgres 16.14 (2026-08-08): migrates clean to head; catalogue
-- reports exactly 3 tables and enum label counts of 7 (vertical_scale) / 3 (goal_origin);
-- six raw inserts bypassing core/ are refused naming vertical_period_together (x2),
-- vertical_needs_anchor, color_is_canon, depth_bounded, tags_bounded in that order —
-- tests/core/test_constraints.py, `make test-core SCENARIO=S-05` prints `PASS S-05`.

CREATE TYPE vertical_scale AS ENUM ('day','week','month','quarter','year','decade','life');
CREATE TYPE goal_origin   AS ENUM ('human','agent','import');

CREATE TABLE goals (
  id           TEXT PRIMARY KEY,
  owner        TEXT        NOT NULL,
  parent_id    TEXT REFERENCES goals(id) ON DELETE RESTRICT,
  path         TEXT        NOT NULL,
  depth        INTEGER     NOT NULL DEFAULT 0,

  vertical      vertical_scale,
  anchor_date  DATE,
  period_key   TEXT,

  title        TEXT        NOT NULL,
  body         TEXT        NOT NULL DEFAULT '',
  color        TEXT,
  tags         TEXT[]      NOT NULL DEFAULT '{}',

  done_at      TIMESTAMPTZ,
  position     INTEGER     NOT NULL DEFAULT 0,
  origin       goal_origin NOT NULL DEFAULT 'human',

  created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at   TIMESTAMPTZ NOT NULL DEFAULT now(),

  CONSTRAINT vertical_period_together CHECK ((vertical IS NULL) = (period_key IS NULL)),
  CONSTRAINT vertical_needs_anchor    CHECK (vertical IS NULL OR anchor_date IS NOT NULL),
  CONSTRAINT color_is_canon CHECK (color IS NULL OR color IN
    ('#ecce32','#df496d','#92ce14','#278dea','#955be0','#f2713a')),
  CONSTRAINT depth_bounded CHECK (depth <= 32),
  CONSTRAINT tags_bounded  CHECK (cardinality(tags) <= 32)
);

CREATE INDEX goals_column  ON goals (owner, vertical, period_key, position);
CREATE INDEX goals_parent  ON goals (parent_id);
CREATE INDEX goals_path    ON goals (owner, path text_pattern_ops);
CREATE INDEX goals_tags    ON goals USING GIN (tags);
CREATE INDEX goals_inbox   ON goals (owner, position)
  WHERE vertical IS NULL AND parent_id IS NULL AND done_at IS NULL;
