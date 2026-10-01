-- The roll's sorting task (docs/design-handoff S4.P1). Once a day the server adds the plans
-- newly carried over to the open "Replan carried-over plans" task in the Inbox, or makes one.
-- It is the first goal the server writes on its own, so its author is the app, neither the
-- owner nor an agent (S4.P1.029). The label is only added here, never used, so the runner's one
-- transaction is fine with it.
ALTER TYPE goal_origin ADD VALUE IF NOT EXISTS 'app';

-- The day the carry-over last ran for an owner: a second run on the same day does nothing, and
-- a run after days away gathers every turn since into one task (S4.P1.023, .035).
CREATE TABLE carryover_runs (
  owner     TEXT PRIMARY KEY,
  last_run  DATE NOT NULL
);
