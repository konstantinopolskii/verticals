-- verticals/db/seed_sample.sql — F1, the shipped sample board (docs/E2E.md §2, "F1 — the
-- sample board, six goals"). Stage 0's whole answer to the empty board: one laddered chain,
-- life -> year -> quarter -> week -> day -> same-day subgoal. All six rows carry
-- tags = ARRAY['sample'], which is the entire removal mechanism (S-62): a one-statement
-- DELETE FROM goals WHERE owner = %s AND tags @> ARRAY['sample'] touches these rows and
-- nothing a real user has written, because a real user's own rows never carry that tag.
--
-- owner = 'local' — the single-owner default (docs/IMPLEMENTATION.md §6.3: VERTICALS_OWNER
-- defaults to 'local', not 'kk'). This file is loaded once against a freshly migrated,
-- empty database, never by application code — ARCHITECTURE.md §3b says core/ never
-- defaults owner, so this raw seed supplies it explicitly on every row, same as every other
-- column here.
--
-- JC-11: the six titles below are neutral placeholders, not final copy. Copywriting the
-- sample board is a separate, later task. Do not read anything here as shipped prose.
--
-- No ON CONFLICT: a second run against a database that already has these ids is a real bug
-- (double-seeding), not a case to swallow silently.

INSERT INTO goals
  (id, owner, parent_id, path, depth, vertical, anchor_date, period_key,
   title, body, color, tags, done_at, position, origin, created_at, updated_at,
   parked_from_vertical)
VALUES
  -- life -> year -> quarter -> week -> day -> same-vertical subgoal, each scheduled scale alone
  -- on its own column,
  -- each at position 1024. Every anchor lands on the product's own reference date,
  -- 2026-08-08, except the two ancestors whose vertical does not need it (life has no
  -- period arithmetic; the sample year is anchored to the same year's Jan 1).
  ('SAMPLE01', 'local', NULL, '/SAMPLE01/', 0,
   'life', '2026-01-01', 'life',
   'Sample life goal', '', NULL, ARRAY['sample'], NULL, 1024, 'human',
   '2026-01-15 09:15:00+00', '2026-01-15 09:15:00+00', NULL),

  ('SAMPLE02', 'local', 'SAMPLE01', '/SAMPLE01/SAMPLE02/', 1,
   'year', '2026-01-01', '2026',
   'Sample year goal', '', NULL, ARRAY['sample'], NULL, 1024, 'human',
   '2026-01-15 09:30:00+00', '2026-01-15 09:30:00+00', NULL),

  ('SAMPLE03', 'local', 'SAMPLE02', '/SAMPLE01/SAMPLE02/SAMPLE03/', 2,
   'quarter', '2026-08-08', '2026-Q3',
   'Sample quarter goal', '', NULL, ARRAY['sample'], NULL, 1024, 'human',
   '2026-01-15 09:45:00+00', '2026-01-15 09:45:00+00', NULL),

  ('SAMPLE04', 'local', 'SAMPLE03', '/SAMPLE01/SAMPLE02/SAMPLE03/SAMPLE04/', 3,
   'week', '2026-08-08', '2026-W32',
   'Sample week goal', '', NULL, ARRAY['sample'], NULL, 1024, 'human',
   '2026-01-15 10:00:00+00', '2026-01-15 10:00:00+00', NULL),

  ('SAMPLE05', 'local', 'SAMPLE04', '/SAMPLE01/SAMPLE02/SAMPLE03/SAMPLE04/SAMPLE05/', 4,
   'day', '2026-08-08', '2026-08-08',
   'Sample day goal', '', NULL, ARRAY['sample'], NULL, 1024, 'human',
   '2026-01-15 10:15:00+00', '2026-01-15 10:15:00+00', NULL),

  -- R7: same-vertical children render only inside their parent, never as duplicate column cards.
  ('SAMPLE06', 'local', 'SAMPLE05',
   '/SAMPLE01/SAMPLE02/SAMPLE03/SAMPLE04/SAMPLE05/SAMPLE06/', 5,
   'day', '2026-08-08', '2026-08-08',
   'Sample subgoal', '', NULL, ARRAY['sample'], NULL, 11264, 'human',
   '2026-01-15 10:30:00+00', '2026-01-15 10:30:00+00', NULL);
