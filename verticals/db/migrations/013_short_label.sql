-- D239 (KK, 2026-08-15): the value menu (App.vue's nav row, D238) shows a ONE-WORD label per
-- value, and the owner chose an explicit field over deriving it from the title. `short_label`
-- is meaningful only on value roots (parentless life-vertical goals) — the same write law as
-- `color` under D231, enforced in `core/goals.py::update`, not here: a CHECK spanning
-- parent_id/vertical would also have to fire on reparent/reschedule, which is D231's read-time
-- derivation problem all over again. The column-level truth this migration CAN own is the
-- shape: one word (no whitespace), at most 24 characters, or NULL.
ALTER TABLE goals ADD COLUMN short_label text;
ALTER TABLE goals ADD CONSTRAINT short_label_is_one_word
    CHECK (short_label IS NULL OR short_label ~ '^[^[:space:]]{1,24}$');
