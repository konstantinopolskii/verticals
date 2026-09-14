-- tests/fixtures/f2_synth.sql — F2, the synthetic tree (docs/E2E.md §2, "F2 — the synthetic
-- tree, 49 rows"). 46 rows for owner 't1', 3 for owner 't2'. Every id, path, depth and every
-- other column is a literal below — nothing is computed by application code, and no scenario
-- may depend on a value this file does not contain.
--
-- Wholly synthetic and neutral: titles, bodies and dates are invented for test coverage only.
-- Nothing here is derived from any real person's data — that is a hard constraint, not a
-- style choice (docs/BRIEF.md rule 9).
--
-- Nine groups, each answering one hard question (full shape in E2E.md §2):
--   G1 ladder (9)      the 6-deep cross-vertical chain, quarter nested under quarter, plus
--                       three vertical-NULL subgoals under the day leaf
--   G2 ordering (4)    one column, four rows: gap ordering, gap exhaustion, renumber
--   G3 Maybe (6)       vertical NULL, parent NULL; one of the six is done and must not
--                       surface in the Maybe partial index
--   G4 search (6)      substring search ('cycl') must return exactly {01,02,03,04}
--   G5 tags (3)        retro-by-tag; two rows sit off the 2026-08-08 board on purpose
--   G6 colors (7)      one row per canon hex plus one NULL, origin='import' throughout
--   G7 completion (4)  two stale-open rows, two done rows, origin='import' throughout
--   G8 period edges (7) the ISO-week-53 and decade-boundary cases named in S-03
--   t2 (3)             a second owner, to prove owner scoping holds
--
-- Depends on a freshly migrated, empty database (F0). No ON CONFLICT: a second run against a
-- database that already has these ids is a real bug, not a case to swallow silently.
-- Foreign keys are not deferred, so G1's chain is listed parent-before-child; every other
-- row is a root (parent_id NULL) and order does not matter for it.
-- V2 fields are explicit: vertical-NULL rows retain the W2 parked-from-life marker; foil is false,
-- and carry-over/expected-size/actual-size are unset throughout this baseline fixture.

INSERT INTO goals
  (id, owner, parent_id, path, depth, vertical, anchor_date, period_key,
   title, body, color, tags, done_at, position, origin, created_at, updated_at,
   parked_from_vertical, foil, carryover_ignored_until, size_expected, size_actual)
VALUES
  -- G1 ladder (9) — the 6-deep cross-vertical chain, quarter-under-quarter included,
  -- plus its three vertical-NULL subgoals.
  ('SYNLIF01', 't1', NULL, '/SYNLIF01/', 0, 'life', '2026-01-01', 'life', 'Live deliberately', '', NULL, '{}', NULL, 1024, 'human', '2026-01-15 09:15:00+00:00', '2026-01-15 09:15:00+00:00', NULL, FALSE, NULL, NULL, NULL),
  ('SYNDEC01', 't1', 'SYNLIF01', '/SYNLIF01/SYNDEC01/', 1, 'decade', '2020-01-01', '2020s', 'The decade of the craft', '', NULL, '{}', NULL, 1024, 'human', '2026-01-15 09:30:00+00:00', '2026-01-15 09:30:00+00:00', NULL, FALSE, NULL, NULL, NULL),
  ('SYNYRR01', 't1', 'SYNDEC01', '/SYNLIF01/SYNDEC01/SYNYRR01/', 2, 'year', '2026-06-15', '2026', 'Ship the thing in 2026', '', NULL, '{}', NULL, 1024, 'human', '2026-01-15 09:45:00+00:00', '2026-01-15 09:45:00+00:00', NULL, FALSE, NULL, NULL, NULL),
  ('SYNQ1R01', 't1', 'SYNYRR01', '/SYNLIF01/SYNDEC01/SYNYRR01/SYNQ1R01/', 3, 'quarter', '2026-08-08', '2026-Q3', 'Q3 groundwork', '', NULL, '{}', NULL, 1024, 'human', '2026-01-15 10:00:00+00:00', '2026-01-15 10:00:00+00:00', NULL, FALSE, NULL, NULL, NULL),
  -- position 2048, not 1024: this row's anchor (2026-09-30, month 9) computes to the SAME
  -- period_key as SYNQ1R01 above — (9-1)//3+1 = 3, both '2026-Q3' — so the two share one
  -- column (census: "quarter | 2026-Q3 | 2") and cannot both sit at 1024 without a duplicate
  -- position inside that column, which breaks this fixture's own "1024-spaced, ascending by
  -- id" invariant. Ascending by id within the shared column: SYNQ1R01 (1024) < SYNQ2R01 (2048).
  ('SYNQ2R01', 't1', 'SYNQ1R01', '/SYNLIF01/SYNDEC01/SYNYRR01/SYNQ1R01/SYNQ2R01/', 4, 'quarter', '2026-09-30', '2026-Q3', 'Q4 follow-through', '', NULL, '{}', NULL, 2048, 'human', '2026-01-15 10:15:00+00:00', '2026-01-15 10:15:00+00:00', NULL, FALSE, NULL, NULL, NULL),
  ('SYNDAY01', 't1', 'SYNQ2R01', '/SYNLIF01/SYNDEC01/SYNYRR01/SYNQ1R01/SYNQ2R01/SYNDAY01/', 5, 'day', '2026-08-08', '2026-08-08', 'Draft the outline', '', NULL, '{}', NULL, 1024, 'human', '2026-01-15 10:30:00+00:00', '2026-01-15 10:30:00+00:00', NULL, FALSE, NULL, NULL, NULL),
  ('SYNSUB01', 't1', 'SYNDAY01', '/SYNLIF01/SYNDEC01/SYNYRR01/SYNQ1R01/SYNQ2R01/SYNDAY01/SYNSUB01/', 6, NULL, NULL, NULL, 'Collect the sources', '', NULL, '{}', NULL, 1024, 'human', '2026-01-15 10:45:00+00:00', '2026-01-15 10:45:00+00:00', 'life', FALSE, NULL, NULL, NULL),
  ('SYNSUB02', 't1', 'SYNDAY01', '/SYNLIF01/SYNDEC01/SYNYRR01/SYNQ1R01/SYNQ2R01/SYNDAY01/SYNSUB02/', 6, NULL, NULL, NULL, 'Name the argument', '', NULL, '{}', NULL, 2048, 'human', '2026-01-15 11:00:00+00:00', '2026-01-15 11:00:00+00:00', 'life', FALSE, NULL, NULL, NULL),
  ('SYNSUB03', 't1', 'SYNDAY01', '/SYNLIF01/SYNDEC01/SYNYRR01/SYNQ1R01/SYNQ2R01/SYNDAY01/SYNSUB03/', 6, NULL, NULL, NULL, 'Cut the first pass', '', NULL, '{}', NULL, 3072, 'human', '2026-01-15 11:15:00+00:00', '2026-01-15 11:15:00+00:00', 'life', FALSE, NULL, NULL, NULL),
  -- G2 ordering (4) — one column, four rows, gap ordering / exhaustion / renumber.
  ('SYNORD01', 't1', NULL, '/SYNORD01/', 0, 'week', '2026-08-05', '2026-W32', 'Order one', '', NULL, '{}', NULL, 1024, 'human', '2026-01-15 11:30:00+00:00', '2026-01-15 11:30:00+00:00', NULL, FALSE, NULL, NULL, NULL),
  ('SYNORD02', 't1', NULL, '/SYNORD02/', 0, 'week', '2026-08-05', '2026-W32', 'Order two', '', NULL, '{}', NULL, 2048, 'human', '2026-01-15 11:45:00+00:00', '2026-01-15 11:45:00+00:00', NULL, FALSE, NULL, NULL, NULL),
  ('SYNORD03', 't1', NULL, '/SYNORD03/', 0, 'week', '2026-08-05', '2026-W32', 'Order three', '', NULL, '{}', NULL, 3072, 'human', '2026-01-15 12:00:00+00:00', '2026-01-15 12:00:00+00:00', NULL, FALSE, NULL, NULL, NULL),
  ('SYNORD04', 't1', NULL, '/SYNORD04/', 0, 'week', '2026-08-05', '2026-W32', 'Order four', '', NULL, '{}', NULL, 4096, 'human', '2026-01-15 12:15:00+00:00', '2026-01-15 12:15:00+00:00', NULL, FALSE, NULL, NULL, NULL),
  -- G3 Maybe (6) — vertical NULL, parent NULL; 06 is done and must not surface in Maybe.
  ('SYNMAY01', 't1', NULL, '/SYNMAY01/', 0, NULL, NULL, NULL, 'Maybe candidate one', '', NULL, '{}', NULL, 1024, 'human', '2026-01-15 12:30:00+00:00', '2026-01-15 12:30:00+00:00', 'life', FALSE, NULL, NULL, NULL),
  ('SYNMAY02', 't1', NULL, '/SYNMAY02/', 0, NULL, NULL, NULL, 'Maybe candidate two', '', NULL, '{}', NULL, 2048, 'human', '2026-01-15 12:45:00+00:00', '2026-01-15 12:45:00+00:00', 'life', FALSE, NULL, NULL, NULL),
  ('SYNMAY03', 't1', NULL, '/SYNMAY03/', 0, NULL, NULL, NULL, 'Maybe candidate three', '', NULL, '{}', NULL, 3072, 'human', '2026-01-15 13:00:00+00:00', '2026-01-15 13:00:00+00:00', 'life', FALSE, NULL, NULL, NULL),
  ('SYNMAY04', 't1', NULL, '/SYNMAY04/', 0, NULL, NULL, NULL, 'Maybe candidate four', '', NULL, '{}', NULL, 4096, 'human', '2026-01-15 13:15:00+00:00', '2026-01-15 13:15:00+00:00', 'life', FALSE, NULL, NULL, NULL),
  ('SYNMAY05', 't1', NULL, '/SYNMAY05/', 0, NULL, NULL, NULL, 'Maybe candidate five', '', NULL, '{}', NULL, 5120, 'human', '2026-01-15 13:30:00+00:00', '2026-01-15 13:30:00+00:00', 'life', FALSE, NULL, NULL, NULL),
  ('SYNMAY06', 't1', NULL, '/SYNMAY06/', 0, NULL, NULL, NULL, 'Maybe candidate six', '', NULL, '{}', '2026-01-16 13:45:00+00:00', 6144, 'human', '2026-01-15 13:45:00+00:00', '2026-01-15 13:45:00+00:00', 'life', FALSE, NULL, NULL, NULL),
  -- G4 search (6) — substring search must find exactly {01,02,03,04} on 'cycl'.
  ('SYNSCH01', 't1', NULL, '/SYNSCH01/', 0, 'month', '2026-08-08', '2026-08', 'Fix the bicycles rack', '', NULL, '{}', NULL, 1024, 'human', '2026-01-15 14:00:00+00:00', '2026-01-15 14:00:00+00:00', NULL, FALSE, NULL, NULL, NULL),
  ('SYNSCH02', 't1', NULL, '/SYNSCH02/', 0, 'month', '2026-08-08', '2026-08', 'Start recycling paper', '', NULL, '{}', NULL, 2048, 'human', '2026-01-15 14:15:00+00:00', '2026-01-15 14:15:00+00:00', NULL, FALSE, NULL, NULL, NULL),
  ('SYNSCH03', 't1', NULL, '/SYNSCH03/', 0, 'month', '2026-08-08', '2026-08', 'Cycle through the backlog', '', NULL, '{}', NULL, 3072, 'human', '2026-01-15 14:30:00+00:00', '2026-01-15 14:30:00+00:00', NULL, FALSE, NULL, NULL, NULL),
  ('SYNSCH04', 't1', NULL, '/SYNSCH04/', 0, 'month', '2026-08-08', '2026-08', 'Garage day', 'Sort the motorcycle parts bin before the weekend.', NULL, '{}', NULL, 4096, 'human', '2026-01-15 14:45:00+00:00', '2026-01-15 14:45:00+00:00', NULL, FALSE, NULL, NULL, NULL),
  ('SYNSCH05', 't1', NULL, '/SYNSCH05/', 0, 'month', '2026-08-08', '2026-08', 'Circle back on pricing', '', NULL, '{}', NULL, 5120, 'human', '2026-01-15 15:00:00+00:00', '2026-01-15 15:00:00+00:00', NULL, FALSE, NULL, NULL, NULL),
  ('SYNSCH06', 't1', NULL, '/SYNSCH06/', 0, 'month', '2026-08-08', '2026-08', 'Cyan palette review', '', NULL, '{}', NULL, 6144, 'human', '2026-01-15 15:15:00+00:00', '2026-01-15 15:15:00+00:00', NULL, FALSE, NULL, NULL, NULL),
  -- G5 tags (3) — retro-by-tag; RET01/02 sit off the 2026-08-08 board on purpose.
  -- Bodies use only bold and links, matching ARCHITECTURE.md §0's measured finding for real
  -- bodies ("the only markdown used is links and bold — no headings"); a synthetic fixture
  -- modelling realistic content should not introduce a heading the corpus never uses. The two
  -- rows are deliberately distinct text, not copies: SYNRET01 is the retro write-up, SYNRET02
  -- is the carry-forward note, exactly the two-artifact shape ARCHITECTURE.md §4b describes.
  ('SYNRET01', 't1', NULL, '/SYNRET01/', 0, 'week', '2026-07-28', '2026-W31', 'Sprint retro notes', '**What happened.** Shipped the outline and cleared most of the backlog; review closed a day later than planned because the introduction needed a full rewrite. **Next.** Read the [style notes](https://example.com/style-notes) before the next draft and block one clean morning for revisions, not tests.', NULL, ARRAY['retro'], NULL, 1024, 'human', '2026-01-15 15:30:00+00:00', '2026-01-15 15:30:00+00:00', NULL, FALSE, NULL, NULL, NULL),
  ('SYNRET02', 't1', NULL, '/SYNRET02/', 0, 'week', '2026-07-28', '2026-W31', 'Retro action items', '**Carried from W31.** Two items slipped: the [pricing review](https://example.com/pricing) and the client follow-up call. Neither was urgent enough to chase mid-week, but both still matter. **Plan.** Move the pricing review into this week and let the follow-up wait one more full week without excuse.', NULL, ARRAY['retro','planning'], NULL, 2048, 'human', '2026-01-15 15:45:00+00:00', '2026-01-15 15:45:00+00:00', NULL, FALSE, NULL, NULL, NULL),
  ('SYNRET03', 't1', NULL, '/SYNRET03/', 0, 'day', '2026-08-08', '2026-08-08', 'Plan the next sprint', '', NULL, ARRAY['planning'], NULL, 10240, 'human', '2026-01-15 16:00:00+00:00', '2026-01-15 16:00:00+00:00', NULL, FALSE, NULL, NULL, NULL),
  -- G6 colors (7) — one row per canon hex plus one NULL; origin='import' throughout.
  ('SYNCOL01', 't1', NULL, '/SYNCOL01/', 0, 'day', '2026-08-08', '2026-08-08', 'Color check yellow', '', '#ecce32', '{}', NULL, 2048, 'import', '2026-01-15 16:15:00+00:00', '2026-01-15 16:15:00+00:00', NULL, FALSE, NULL, NULL, NULL),
  ('SYNCOL02', 't1', NULL, '/SYNCOL02/', 0, 'day', '2026-08-08', '2026-08-08', 'Color check pink', '', '#df496d', '{}', NULL, 3072, 'import', '2026-01-15 16:30:00+00:00', '2026-01-15 16:30:00+00:00', NULL, FALSE, NULL, NULL, NULL),
  ('SYNCOL03', 't1', NULL, '/SYNCOL03/', 0, 'day', '2026-08-08', '2026-08-08', 'Color check green', '', '#92ce14', '{}', NULL, 4096, 'import', '2026-01-15 16:45:00+00:00', '2026-01-15 16:45:00+00:00', NULL, FALSE, NULL, NULL, NULL),
  ('SYNCOL04', 't1', NULL, '/SYNCOL04/', 0, 'day', '2026-08-08', '2026-08-08', 'Color check blue', '', '#278dea', '{}', NULL, 5120, 'import', '2026-01-15 17:00:00+00:00', '2026-01-15 17:00:00+00:00', NULL, FALSE, NULL, NULL, NULL),
  ('SYNCOL05', 't1', NULL, '/SYNCOL05/', 0, 'day', '2026-08-08', '2026-08-08', 'Color check purple', '', '#955be0', '{}', NULL, 6144, 'import', '2026-01-15 17:15:00+00:00', '2026-01-15 17:15:00+00:00', NULL, FALSE, NULL, NULL, NULL),
  ('SYNCOL06', 't1', NULL, '/SYNCOL06/', 0, 'day', '2026-08-08', '2026-08-08', 'Color check orange', '', '#f2713a', '{}', NULL, 7168, 'import', '2026-01-15 17:30:00+00:00', '2026-01-15 17:30:00+00:00', NULL, FALSE, NULL, NULL, NULL),
  ('SYNCOL07', 't1', NULL, '/SYNCOL07/', 0, 'day', '2026-08-08', '2026-08-08', 'Color check none', '', NULL, '{}', NULL, 8192, 'import', '2026-01-15 17:45:00+00:00', '2026-01-15 17:45:00+00:00', NULL, FALSE, NULL, NULL, NULL),
  -- G7 completion (4) — two stale-open rows, two done rows, origin='import' throughout.
  ('SYNOLD01', 't1', NULL, '/SYNOLD01/', 0, 'day', '2025-01-06', '2025-01-06', 'Stale day task', '', NULL, '{}', NULL, 1024, 'import', '2026-01-15 18:00:00+00:00', '2026-01-15 18:00:00+00:00', NULL, FALSE, NULL, NULL, NULL),
  ('SYNOLD02', 't1', NULL, '/SYNOLD02/', 0, 'week', '2025-01-06', '2025-W02', 'Stale week task', '', NULL, '{}', NULL, 1024, 'import', '2026-01-15 18:15:00+00:00', '2026-01-15 18:15:00+00:00', NULL, FALSE, NULL, NULL, NULL),
  ('SYNDON01', 't1', NULL, '/SYNDON01/', 0, 'day', '2026-08-08', '2026-08-08', 'Shipped today', '', NULL, '{}', '2026-01-16 18:30:00+00:00', 9216, 'import', '2026-01-15 18:30:00+00:00', '2026-01-15 18:30:00+00:00', NULL, FALSE, NULL, NULL, NULL),
  ('SYNDON02', 't1', NULL, '/SYNDON02/', 0, 'day', '2026-08-07', '2026-08-07', 'Shipped yesterday', '', NULL, '{}', '2026-01-16 18:45:00+00:00', 1024, 'import', '2026-01-15 18:45:00+00:00', '2026-01-15 18:45:00+00:00', NULL, FALSE, NULL, NULL, NULL),
  -- G8 period edges (7) — the ISO-week-53 and decade-boundary cases from S-03.
  ('SYNEDG01', 't1', NULL, '/SYNEDG01/', 0, 'day', '2024-02-29', '2024-02-29', 'Leap day edge', '', NULL, '{}', NULL, 1024, 'human', '2026-01-15 19:00:00+00:00', '2026-01-15 19:00:00+00:00', NULL, FALSE, NULL, NULL, NULL),
  ('SYNEDG02', 't1', NULL, '/SYNEDG02/', 0, 'week', '2021-01-01', '2020-W53', 'ISO week 53 edge A', '', NULL, '{}', NULL, 1024, 'human', '2026-01-15 19:15:00+00:00', '2026-01-15 19:15:00+00:00', NULL, FALSE, NULL, NULL, NULL),
  ('SYNEDG03', 't1', NULL, '/SYNEDG03/', 0, 'week', '2026-12-31', '2026-W53', 'ISO week 53 edge B', '', NULL, '{}', NULL, 1024, 'human', '2026-01-15 19:30:00+00:00', '2026-01-15 19:30:00+00:00', NULL, FALSE, NULL, NULL, NULL),
  ('SYNEDG04', 't1', NULL, '/SYNEDG04/', 0, 'week', '2027-01-01', '2026-W53', 'ISO week 53 edge C', '', NULL, '{}', NULL, 2048, 'human', '2026-01-15 19:45:00+00:00', '2026-01-15 19:45:00+00:00', NULL, FALSE, NULL, NULL, NULL),
  ('SYNEDG05', 't1', NULL, '/SYNEDG05/', 0, 'decade', '2029-12-31', '2020s', 'Decade edge 2020s', '', NULL, '{}', NULL, 2048, 'human', '2026-01-15 20:00:00+00:00', '2026-01-15 20:00:00+00:00', NULL, FALSE, NULL, NULL, NULL),
  ('SYNEDG06', 't1', NULL, '/SYNEDG06/', 0, 'decade', '2030-01-01', '2030s', 'Decade edge 2030s', '', NULL, '{}', NULL, 1024, 'human', '2026-01-15 20:15:00+00:00', '2026-01-15 20:15:00+00:00', NULL, FALSE, NULL, NULL, NULL),
  ('SYNEDG07', 't1', NULL, '/SYNEDG07/', 0, 'week', '2029-12-31', '2030-W01', 'ISO week 1 edge', '', NULL, '{}', NULL, 1024, 'human', '2026-01-15 20:30:00+00:00', '2026-01-15 20:30:00+00:00', NULL, FALSE, NULL, NULL, NULL),
  -- t2 — owner scoping (3): a second owner, never visible through owner='t1' reads.
  ('SYNOTH01', 't2', NULL, '/SYNOTH01/', 0, 'day', '2026-08-08', '2026-08-08', 'Other owner day item', '', NULL, '{}', NULL, 1024, 'human', '2026-01-15 20:45:00+00:00', '2026-01-15 20:45:00+00:00', NULL, FALSE, NULL, NULL, NULL),
  ('SYNOTH02', 't2', NULL, '/SYNOTH02/', 0, 'life', '2026-01-01', 'life', 'Other owner life item', '', NULL, '{}', NULL, 1024, 'human', '2026-01-15 21:00:00+00:00', '2026-01-15 21:00:00+00:00', NULL, FALSE, NULL, NULL, NULL),
  ('SYNOTH03', 't2', NULL, '/SYNOTH03/', 0, NULL, NULL, NULL, 'Other owner maybe item', '', NULL, '{}', NULL, 1024, 'human', '2026-01-15 21:15:00+00:00', '2026-01-15 21:15:00+00:00', 'life', FALSE, NULL, NULL, NULL);
