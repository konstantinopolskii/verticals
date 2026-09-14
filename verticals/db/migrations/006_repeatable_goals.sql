-- verticals/db/migrations/006_repeatable_goals.sql — repeat rules and occurrence identity.
--
-- A repeating occurrence remains an ordinary `goals` row. `repeat_rule` is the validated,
-- structured schedule copied to each occurrence; `repeat_series_id` and `repeat_index` identify
-- that occurrence within the series; `repeat_start_date` preserves the first anchor. The next
-- occurrence is materialised transactionally when the current one changes from open to done.
--
-- The partial unique index is the idempotency backstop: two executions of that completion path
-- may race or replay, but only one row can occupy an `(owner, series, index)` slot. This is also
-- why series identity is stored separately from a generated row id.
--
-- Forward-only and safe on a populated database. Every new column is nullable, so every existing
-- goal remains a valid non-repeating goal without a table rewrite. The CHECK constraints accept
-- the all-NULL legacy state and refuse half-written recurrence metadata. Building the small
-- partial index scans existing rows but indexes none of them on first application.

ALTER TABLE goals
  ADD COLUMN repeat_rule       JSONB,
  ADD COLUMN repeat_series_id  TEXT,
  ADD COLUMN repeat_index      INTEGER,
  ADD COLUMN repeat_start_date DATE,
  ADD CONSTRAINT repeat_rule_is_object CHECK (
    repeat_rule IS NULL OR jsonb_typeof(repeat_rule) = 'object'
  ),
  ADD CONSTRAINT repeat_fields_together CHECK (
    (repeat_rule IS NULL AND repeat_series_id IS NULL AND repeat_index IS NULL
      AND repeat_start_date IS NULL)
    OR
    (repeat_rule IS NOT NULL AND repeat_series_id IS NOT NULL AND repeat_index IS NOT NULL
      AND repeat_index >= 0 AND repeat_start_date IS NOT NULL
      AND vertical IS NOT NULL AND anchor_date IS NOT NULL)
  );

CREATE UNIQUE INDEX goals_repeat_occurrence
  ON goals (owner, repeat_series_id, repeat_index)
  WHERE repeat_series_id IS NOT NULL;
