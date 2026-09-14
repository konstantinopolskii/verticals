-- tests/fixtures/f1u_user_rows.sql — the two rows that turn F1 into F1u (docs/E2E.md §2,
-- "F1u — F1 plus two rows the sample removal must not touch"). This file is loaded AFTER
-- verticals/db/seed_sample.sql against the same fresh database — it does not repeat F1's six
-- rows, it only adds the two that prove S-62's delete is scoped by tag and not by table.
--
-- S-62's whole point: on F1 alone, "remove sample leaves the sample gone" is also satisfied by
-- an unfiltered `DELETE FROM goals`, which on a self-hoster's box is total data loss one click
-- away. USERROW1 and USERROW2 are the negative control — neither carries tags @> ARRAY['sample'],
-- so a correct removal (WHERE tags @> ARRAY['sample']) leaves both untouched (byte-identical,
-- full-row digest) while an unfiltered delete would take them too.
--
-- owner = 'local', matching seed_sample.sql — this is still the single-owner Stage-0 board, not
-- a second owner (that is F2's job). origin = 'human' on both, literal title/body/color/position/
-- created_at per E2E.md's own table ("Both carry origin='human' and literal ... values in the
-- fixture file"). Wholly synthetic and neutral (docs/BRIEF.md rule 9), same as F2.
--
-- No ON CONFLICT: a second run against a database that already has these ids is a real bug
-- (double-seeding), not a case to swallow silently — same rule seed_sample.sql states for itself.

INSERT INTO goals
  (id, owner, parent_id, path, depth, vertical, anchor_date, period_key,
   title, body, color, tags, done_at, position, origin, created_at, updated_at,
   parked_from_vertical)
VALUES
  -- "a scheduled row a real user authored" (E2E.md §2) — day column, 2026-08-08, same column
  -- SAMPLE05 occupies. Position 2048 (after SAMPLE05's 1024) so ordering inside that column is
  -- unambiguous; S-62 does not assert an exact position, only that the row survives untouched.
  ('USERROW1', 'local', NULL, '/USERROW1/', 0,
   'day', '2026-08-08', '2026-08-08',
   'Renew the passport', '', NULL, ARRAY[]::TEXT[], NULL, 2048, 'human',
   '2026-07-20 08:00:00+00', '2026-07-20 08:00:00+00', NULL),

  -- "a Maybe row, parent_id IS NULL" (E2E.md §2) — vertical NULL, so period_key must be NULL too
  -- (vertical_period_together, 001_init.sql:48). Alone in Maybe on F1u since F1 itself seeds none.
  ('USERROW2', 'local', NULL, '/USERROW2/', 0,
   NULL, NULL, NULL,
   'Learn woodworking', '', NULL, ARRAY[]::TEXT[], NULL, 1024, 'human',
   '2026-07-22 19:30:00+00', '2026-07-22 19:30:00+00', 'life');
