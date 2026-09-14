-- verticals/db/migrations/008_park_foil.sql — v2 park state and foil decoration.
--
-- A parked goal keeps its tree location and anchor_date. Only vertical/period_key become NULL;
-- parked_from_vertical records its former scale. Existing vertical-NULL v1 rows predate that
-- distinction, so they are backfilled to the lowest-information valid rank (`life`) before the
-- two-way CHECK lands. Future core writes record the real former/parent scale where one exists.

ALTER TABLE goals
  ALTER COLUMN vertical DROP NOT NULL,
  ADD COLUMN parked_from_vertical TEXT,
  ADD COLUMN foil BOOLEAN NOT NULL DEFAULT false,
  ADD COLUMN carryover_ignored_until DATE;

UPDATE goals
   SET parked_from_vertical = 'life'
 WHERE vertical IS NULL;

ALTER TABLE goals
  ADD CONSTRAINT parked_from_vertical_is_scale
    CHECK (parked_from_vertical IS NULL OR parked_from_vertical IN
      ('day','week','month','quarter','year','decade','life')),
  ADD CONSTRAINT vertical_parked_together
    CHECK ((vertical IS NULL) = (parked_from_vertical IS NOT NULL));

-- Keep WP-33's content semantics in one trigger. `vertical` remains watched: parking or
-- recommitting changes the obligation and stales evidence. Foil/carry-over/park rank are
-- decoration or bookkeeping and therefore deliberately absent from the watched list.
CREATE OR REPLACE FUNCTION goals_bump_content_revision() RETURNS trigger
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
