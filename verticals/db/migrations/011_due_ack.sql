-- Due acknowledgments (KK, 2026-08-14): a carry-over ghost ("Due") is dismissed by a VERDICT,
-- not silently. Either "yes, this was overdue" or "it was done on time, just never marked" —
-- both leave a permanent row in the goal's own due history, keyed to the exact period that was
-- missed. The board's ghost branch excludes acknowledged (goal, period) pairs; rescheduling the
-- goal into a new period and missing again is a NEW dueness and ghosts again.
--
-- One row per (goal, owner, vertical, period_key): acknowledging the same missed period twice is
-- idempotent by primary key, never a second history entry. The composite FK rides 007's
-- goals_id_owner_unique, the same construction goal_evidence uses — an acknowledgment whose
-- owner drifted from its goal's owner is unrepresentable.
--
-- No goals column changes, so goals_bump_content_revision() (007) is untouched: acknowledging
-- a due never bumps content_revision. The done_on_time verdict completes the goal through the
-- ordinary update path, which bumps it exactly as any completion does.

CREATE TABLE due_acknowledgements (
  goal_id         TEXT NOT NULL,
  owner           TEXT NOT NULL,
  vertical         vertical_scale NOT NULL,
  period_key      TEXT NOT NULL,
  verdict         TEXT NOT NULL CHECK (verdict IN ('overdue', 'done_on_time')),
  note            TEXT NULL,
  acknowledged_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
  PRIMARY KEY (goal_id, owner, vertical, period_key),
  FOREIGN KEY (goal_id, owner) REFERENCES goals (id, owner) ON DELETE CASCADE
);

-- The board's ghost branch probes by (owner, goal, vertical, period_key) — the PK covers it with
-- goal_id leading; this index serves the owner-first probe shape the board statement uses.
CREATE INDEX due_ack_owner_goal ON due_acknowledgements (owner, goal_id);
