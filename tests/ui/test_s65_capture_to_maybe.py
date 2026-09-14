"""S-65 — L1 + L8: capture to Maybe in at most two gestures.

docs/E2E.md, S-65. Fixture F2. Steps: navigate to Inbox, click the inline add row there, type a
title, press Enter. Required by J3, L1, L8, Stage 2.

Scope note (docs/PENDING_DOC_FIXES.md row 56, filed a prior pass this session): S-65's own steps
name **the Maybe column** only. AC-110's stronger "every column" claim is S-106's job (WP-24, suite
`uidiff`) — this test deliberately does not stretch past the Maybe column under the S-65 name.

Ruling 1 (owner, 2026-08-09): "There's no need to show Maybe as a left column. Make it same tab as
inbox." `ARCHITECTURE.md`:445's eighth-column reading is superseded — `Board.vue` no longer draws a
Maybe column at all, so `[data-vertical="maybe"]` only exists once the Inbox nav view is open
(`InboxView.vue`, `App.vue`'s `[data-nav-item="inbox"]` link). The one added step, a raw
`page.click` on that nav link rather than `session.gestures.click`, is navigation, not the capture
gesture itself — the same distinction every other scenario in this package draws between loading
the app and acting inside it, and it is why `GestureCounter`'s own count still reads 2 (click +
Enter) below, not 3.
"""

from __future__ import annotations

import psycopg

from tests.ui.conftest import UiSession

MAYBE_ADD = '[data-vertical="maybe"] [data-cap="create-goal"]'
MAYBE_EDITOR = f'{MAYBE_ADD} [data-role="column-add-editor"]'
# Distinctive and grep-able, so a DB correlation by title cannot collide with any F2 fixture row
# (F2's own titles are enumerated in full in docs/E2E.md §2 — none of them are this string).
NEW_TITLE = "WP-22 S-65 capture probe"


def test_s65_capture_to_maybe(ui_f2: UiSession) -> None:
    session = ui_f2
    conn = psycopg.connect(session.backend.dsn, autocommit=True)
    try:
        (existing,) = conn.execute("SELECT count(*) FROM goals WHERE title = %s", (NEW_TITLE,)).fetchone()
        assert existing == 0, "the probe title must not already exist"

        # --- navigate to Inbox (ruling 1) — not a gesture, per this file's own module docstring ----
        session.page.click('[data-nav-item="inbox"]')
        session.page.wait_for_selector('[data-cap="inbox"]')
        assert session.gestures.count == 0, "navigating to Inbox must not be counted as a gesture"

        # --- resting entry affordance: one ghost row, not a prematurely open editor ---------------
        maybe_add = session.page.locator(MAYBE_ADD)
        assert maybe_add.count() == 1, (
            f"expected exactly 1 create-goal ghost row in Maybe, found {maybe_add.count()}"
        )
        rest_tag = maybe_add.evaluate("el => el.tagName.toLowerCase()")
        assert rest_tag == "div", f"the resting add row's own element is {rest_tag!r}, not a div"

        # --- step 1: click (gesture 1) --------------------------------------------------------------
        session.gestures.click(MAYBE_ADD)
        assert session.gestures.count == 1

        # --- L8: capture surface is exactly one input, zero required selects -----------------------
        # InlineAdd's resting card-like div is replaced in place only after activation. L8 describes
        # what the user must fill in, so inspect the active capture surface rather than its resting
        # entry affordance. `data-cap=create-goal` falls through onto the editor's own input.
        editor = session.page.locator(MAYBE_EDITOR)
        editor.wait_for(state="visible")
        assert editor.count() == 1, f"expected exactly 1 active add input in Maybe, found {editor.count()}"
        editor_tag = editor.evaluate("el => el.tagName.toLowerCase()")
        assert editor_tag == "input", f"the active capture surface is a {editor_tag!r}, not an input"
        required_selects = session.page.locator('[data-vertical="maybe"] select[required]')
        assert required_selects.count() == 0, "L8 violated: a required <select> exists in the Maybe column"

        # --- step 2: type a title (NOT a gesture — E2E.md §6: "typing is not counted"; using
        # `press_sequentially`, never `GestureCounter.fill`, is what keeps it uncounted here) --------
        editor.press_sequentially(NEW_TITLE)
        assert session.gestures.count == 1, "typing must not bump the gesture count"

        # --- step 3: press Enter (gesture 2, committing) ------------------------------------------------
        session.gestures.press_committing(MAYBE_EDITOR, "Enter")
        assert session.gestures.count == 2, f"expected gesture count 2 (click + Enter), got {session.gestures.count}"

        # --- modal record empty -------------------------------------------------------------------------
        assert session.dialog_records() == [], f"a modal opened on capture: {session.dialog_records()}"

        # --- appears in Maybe (wait for the reload store.ts::createGoalOn triggers) --------------------
        new_card = session.page.locator(f'[data-vertical="maybe"] .card-stack > [data-goal-id]', has_text=NEW_TITLE)
        new_card.wait_for(state="visible", timeout=5000)
        new_id = new_card.get_attribute("data-goal-id")
        assert new_id, "new card rendered with no data-goal-id"

        # --- DB: vertical IS NULL, parent_id IS NULL, done_at IS NULL ------------------------------------
        row = conn.execute(
            "SELECT vertical, parent_id, done_at, title FROM goals WHERE id = %s", (new_id,)
        ).fetchone()
        assert row is not None, f"new id {new_id} not found in goals table"
        vertical, parent_id, done_at, title = row
        assert vertical is None, f"expected vertical IS NULL, got {vertical!r}"
        assert parent_id is None, f"expected parent_id IS NULL, got {parent_id!r}"
        assert done_at is None, f"expected done_at IS NULL, got {done_at!r}"
        assert title == NEW_TITLE, f"title mismatch: {title!r}"
    finally:
        conn.close()
