"""S-65 — L1 + L8: capture to Maybe in at most two gestures.

docs/E2E.md, S-65. Fixture F2. Steps: navigate to Inbox, click the place to write there, type a title, press Enter.
Required by J3, L1, L8, Stage 2.

Since the Inbox and Documents redesign (round 7, KK 7 Oct 2026) the place to write in the Inbox is the field itself: in
the Inbox it rests open saying "Write anything", and ↵ puts the words first among Today's cards as a goal with no date
and no parent, the Maybe bucket (`board.MAYBE_PREDICATE`). Nothing is planned. Navigating to the Inbox is not a
gesture, the same distinction every other scenario in this package draws between loading the app and acting inside
it, so `GestureCounter`'s count still reads 2 (click + Enter) below.

The page's clock is pinned (`conftest.PINNED_CLOCK_ISO`) while the server stamps a new goal with its own clock; this
scenario moves the page's clock to the server's day first, so "today" means the same day on both sides, as it does in
use.
"""

from __future__ import annotations

from datetime import datetime, timezone

import psycopg
from playwright.sync_api import expect

from tests.ui.conftest import UiSession
from tests.ui.views import FIELD, switch_view

CAPTION = ".circle-field__caption"
TODAY_CARDS = '[data-role="inbox-today"] [data-role="inbox-card"]'
# Distinctive and grep-able, so a DB correlation by title cannot collide with any F2 fixture row
# (F2's own titles are enumerated in full in docs/E2E.md §2 — none of them are this string).
NEW_TITLE = "WP-22 S-65 capture probe"


def test_s65_capture_to_maybe(ui_f2: UiSession) -> None:
    session = ui_f2
    page = session.page
    page.clock.set_fixed_time(datetime.now(timezone.utc))
    page.reload()
    conn = psycopg.connect(session.backend.dsn, autocommit=True)
    try:
        (existing,) = conn.execute("SELECT count(*) FROM goals WHERE title = %s", (NEW_TITLE,)).fetchone()
        assert existing == 0, "the probe title must not already exist"

        # --- navigate to Inbox — not a gesture, per this file's own module docstring ----------------
        switch_view(page, "inbox")
        page.mouse.move(5, 5)
        assert session.gestures.count == 0, "navigating to Inbox must not be counted as a gesture"

        # --- resting entry affordance: the field, open, inviting words -------------------------------
        expect(page.locator(CAPTION)).to_have_text("Write anything")
        expect(page.locator(FIELD)).to_be_visible()

        # --- step 1: click (gesture 1) — L8: one text box, zero required selects ---------------------
        session.gestures.click(FIELD)
        assert session.gestures.count == 1
        assert page.locator(FIELD).count() == 1
        assert page.locator('[data-cap="inbox"] select[required]').count() == 0, "L8 violated: a required <select>"

        # --- step 2: type a title (NOT a gesture — E2E.md §6: "typing is not counted") ------------------
        page.locator(FIELD).press_sequentially(NEW_TITLE)
        assert session.gestures.count == 1, "typing must not bump the gesture count"

        # --- step 3: press Enter (gesture 2, committing) ------------------------------------------------
        session.gestures.press_committing(FIELD, "Enter")
        assert session.gestures.count == 2, f"expected gesture count 2 (click + Enter), got {session.gestures.count}"
        assert session.dialog_records() == [], f"a modal opened on capture: {session.dialog_records()}"

        # --- the words land first in Today, and the field empties for the next ones ----------------------
        first = page.locator(TODAY_CARDS).first
        expect(first).to_contain_text(NEW_TITLE, timeout=5000)
        expect(page.locator(FIELD)).to_have_value("")
        new_id = first.get_attribute("data-goal-id")
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
