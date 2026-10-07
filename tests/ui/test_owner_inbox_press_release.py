"""D90: a press on an Inbox card must be releasable, or the goal disappears from the board.

Found by hand in the live app on 2026-08-11, then reproduced here. `GoalCard.vue`'s row arms the
drag on `pointerdown` wherever it is rendered, and `InboxView` renders the same card `Board` does —
but the window-level `pointerup`/`pointercancel` listeners lived in `Board.vue`, which is unmounted
for the whole time Inbox is on screen. `lib/drag.ts::armPointerDown` promotes a press to a real
drag on a TIMER (`DESKTOP_HOLD_MS`, 200 ms) with no movement required, so an ordinary press held
past that on an Inbox card armed a drag nothing could release. `drag.id` then stayed set for the
rest of the session, and `GoalCard.vue`'s `closesSourceGap` collapsed that card to `height: 0` in
every view afterwards — the goal was still in the database, still in the payload, and invisible.

The assertion is deliberately the rendered box, not a class name: what the owner would report is
"the goal vanished", and a zero-height card is exactly that however it got there.
"""

from __future__ import annotations

from playwright.sync_api import expect

from tests.ui.conftest import UiSession
from tests.ui.views import switch_view, tick

MAYBE_GOAL = "SYNMAY01"  # F2's Maybe row — same goal S-66 schedules
HOLD_MS = 400  # comfortably past lib/drag.ts::DESKTOP_HOLD_MS (200), the promotion threshold
SETTLE_DEADLINE_MS = 3000  # >> SETTLE_FALLBACK_MS (250) + SETTLE_GRACE_MS (50); a deadline, not a sleep


def test_owner_inbox_press_and_hold_releases_and_leaves_the_card_visible(ui_f2: UiSession) -> None:
    session = ui_f2
    switch_view(session.page, "inbox")
    card = session.page.locator(f'[data-cap="inbox"] [data-goal-id="{MAYBE_GOAL}"]')
    card.wait_for(state="visible")
    # An older task lies in Earlier's row, which you swipe (Inbox and Documents redesign, final page): bring it into view.
    card.scroll_into_view_if_needed()

    box = card.bounding_box()
    assert box is not None, f"{MAYBE_GOAL} has no box in the Inbox"
    resting_height = box["height"]
    assert resting_height > 0, f"{MAYBE_GOAL} rests at height {resting_height} in the Inbox"

    # Press, hold past the promotion threshold, release — one committed gesture, in pieces so the
    # dwell is real. A Playwright `click` already dwells long enough to reach this on a loaded box,
    # which is why the defect surfaced as an intermittent failure in S-66 and S-105 rather than as
    # a permanent one.
    session.page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
    session.page.mouse.down()
    session.page.wait_for_timeout(HOLD_MS)
    session.page.mouse.up()
    # The release runs the settle animation before it hands the row back (`SETTLE_FALLBACK_MS` 250
    # + `SETTLE_GRACE_MS` 50 for a release that never travelled), so the card is legitimately
    # collapsed for a moment. Poll to a deadline rather than sleep a magic number: the defect is a
    # card that NEVER comes back, and a deadline is what distinguishes the two.
    session.page.wait_for_selector(
        f'[data-cap="inbox"] [data-goal-id="{MAYBE_GOAL}"]:not(.goal-card--source-gap-closed)', timeout=SETTLE_DEADLINE_MS
    )

    after = card.bounding_box()
    assert after is not None and after["height"] > 0, (
        f"{MAYBE_GOAL} collapsed to height "
        f"{None if after is None else after['height']} after a press-and-release in the Inbox — "
        f"the drag was armed and never released (D90)"
    )

    # And it must survive the round trip: the stuck state was global, not a stale node in this
    # view's DOM, so it outlived every remount. (An unverticaled goal has no board column of its
    # own — S-66's own note — so Inbox is where it is looked at again.)
    # A press that never travelled is a click: since the Inbox and Documents redesign (round 7) it opens the goal as a
    # window over the Inbox (S3.P4), which goes before the views are switched.
    tick(session.page)
    session.page.locator('[data-role="window-close"]').click()
    expect(session.page.locator('[data-role="goal-window"]')).to_have_count(0)
    switch_view(session.page, "verticals")
    switch_view(session.page, "inbox")
    returned = session.page.locator(f'[data-cap="inbox"] [data-goal-id="{MAYBE_GOAL}"]')
    returned.wait_for(state="visible", timeout=5000)
    returned_box = returned.bounding_box()
    assert returned_box is not None and returned_box["height"] > 0, (
        f"{MAYBE_GOAL} came back from the board at height "
        f"{None if returned_box is None else returned_box['height']} (D90)"
    )
