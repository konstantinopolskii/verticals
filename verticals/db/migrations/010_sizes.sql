-- Expected and actual active-work sessions ("shots"). Token validation belongs to core;
-- these checks keep the storage shape honest even for maintenance/import paths.
ALTER TABLE goals
  ADD COLUMN size_expected JSONB NULL,
  ADD COLUMN size_actual JSONB NULL,
  ADD CONSTRAINT goals_size_expected_array
    CHECK (size_expected IS NULL OR jsonb_typeof(size_expected) = 'array'),
  ADD CONSTRAINT goals_size_actual_array
    CHECK (size_actual IS NULL OR jsonb_typeof(size_actual) = 'array');

-- No trigger rewrite is needed here. goals_bump_content_revision() (007, and any additive
-- replacement built from it) names watched content fields explicitly; neither new column is
-- named, so changing sizes cannot bump content_revision.
