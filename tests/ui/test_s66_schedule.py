"""S-66 — L1: schedule in at most two gestures, from the open detail surface.

docs/E2E.md lines 1618-1642. Fixture F2. Steps: open `SYNMAY01`'s detail surface, click
`[data-cap=schedule]`, then click the `W32` cell in the popover. Required by L1, Stage 2.

**KK ruling, 2026-08-09** — "scheduling shouldn't stay as a button right on the card on the
overview, it should be inside the edit card" — moved the trigger off the board card
(`GoalCard.vue`'s former `goal-card__schedule`) into `GoalDetailEditor.vue`, in the same field
cluster as Title/Colour/Tags. Two consequences for this file, both load-bearing:

  * The trigger resolves inside `#goal-detail` (`GoalDetail.vue`'s `KModal` id), while
    `PopoverEngine` portals the opened menu to `#dropdownPortal`, a direct child of `body`.
    The schedule surface is identified there by its schedule-grid content; scoping it below
    `#goal-detail` can never match the portalled node.
  * "No modal" is retired for this scenario's own title: the trigger lives inside `KModal` by
    design now, so opening the detail surface (its own gesture, identical in kind to the one
    title/colour/tags editing already pays) is **not** charged against the 2-gesture budget —
    see `docs/JOURNEYS.md` L1 and `docs/PENDING_DOC_FIXES.md` row 126. The budget below still
    covers exactly two things: the trigger click and the target-cell click.

"Eight elements covering seven scales" (E2E.md's own count): the sentence enumerates eight
comma-separated items — life, decade, year, **four quarters**, month, the ISO-week column, the
day grid, plus the today/tomorrow/this-week footer — where "four quarters" is one named item that
is itself four DOM nodes. This test asserts the real decomposition read from
`web/src/components/SchedulePopover.vue`'s own template: life(1) + decade(1) + year(1, the
stepper-label only, distinguished from the four quarter buttons that share its row) + quarter(4)
+ month(1) + week column(1 container) + day grid(1 container) = seven scales, plus the footer
(1 container, not itself an eighth scale — a shortcut cluster into day/day/week).
"""

from __future__ import annotations

import psycopg

from tests.ui.conftest import UiSession
from tests.ui.views import switch_view

PRIMARY_GOAL = "SYNMAY01"  # scheduled to week 2026-W32 — the scenario's own two gestures
SECONDARY_GOAL = "SYNMAY02"  # separate card, separate popover — the supplementary "life" check

DETAIL_MODAL = "#goal-detail"
# The open goal's date is the first fact under its title, and it opens the schedule popup (GoalFacts.vue, the
# opened-card cleanup, KK 27-28 Sep 2026).
DETAIL_TRIGGER = '.goal-card--detail-open .goal-facts [data-cap="schedule"]'
DETAIL_POPOVER = (
    '#dropdownPortal [data-popover-surface][data-state="open"]:has(.schedule-popover__row)'
)


def _card_title(goal_id: str) -> str:
    """The goal's row in the Inbox: since the Inbox and Documents redesign (round 7) a click there opens the goal as a
    window over the Inbox (S3.P4), its card open inside with the date fact that opens the schedule popup."""
    return f'[data-cap="inbox"] [data-goal-id="{goal_id}"]'


def _in_popover(rest: str) -> str:
    return f"{DETAIL_POPOVER} {rest}"


def test_s66_schedule(ui_f2: UiSession) -> None:
    session = ui_f2
    conn = psycopg.connect(session.backend.dsn, autocommit=True)
    try:
        before = conn.execute(
            "SELECT vertical, period_key, anchor_date FROM goals WHERE id = %s", (PRIMARY_GOAL,)
        ).fetchone()
        assert before is not None and before[0] is None, f"{PRIMARY_GOAL} must start in Maybe (vertical IS NULL)"

        # --- open the detail surface — its own gesture, not counted against the 2-gesture budget
        # below (docs/JOURNEYS.md L1, KK ruling 2026-08-09) ------------------------------------------
        # Ruling 1 (owner, 2026-08-09) took the Maybe column off the board — PRIMARY_GOAL starts
        # unverticaled (asserted above), so its card only renders in the Inbox view
        # (`InboxView.vue`), not on the Verticals board `Board.vue` draws. `GoalDetail.vue` itself
        # is mounted at `App.vue` level regardless of which nav view is active (this file's own
        # relocation fix), so the click-to-open works the same once the card is actually visible.
        switch_view(session.page, "inbox")
        session.page.wait_for_selector('[data-cap="inbox"]', timeout=5000)
        session.page.click(_card_title(PRIMARY_GOAL))
        session.page.wait_for_selector(DETAIL_TRIGGER, timeout=5000)

        # KK ruling 2026-08-09 (docs/PENDING_DOC_FIXES.md row 126) moved the schedule trigger
        # *inside* the detail modal — "the 'no modal' clause no longer applies to the schedule
        # path, since the trigger lives inside `KModal` by design." Opening the detail surface
        # itself is therefore expected to have already recorded (`KModal`'s own `role="dialog"`
        # node, mounted the instant `GoalDetail.vue` first mounts). What this scenario's own
        # "popover is a popover, not a modal" clause actually needs is: opening the *popover* adds
        # no record on top of that — so the baseline is snapshotted here, before the trigger click.
        dialog_records_before_popover = session.dialog_records()

        body_overflow_before = session.page.evaluate("() => getComputedStyle(document.body).overflow")

        # --- step 1: click the trigger (gesture 1) --------------------------------------------------
        session.gestures.click(DETAIL_TRIGGER)
        assert session.gestures.count == 1

        popover = session.page.locator(DETAIL_POPOVER)
        popover.wait_for(state="visible")

        # --- popover is a popover, not a modal: role != dialog, background scroll unaffected --------
        assert popover.get_attribute("role") == "menu", f"popover role is {popover.get_attribute('role')!r}, expected 'menu'"
        assert popover.get_attribute("role") != "dialog"
        assert session.dialog_records() == dialog_records_before_popover, (
            f"opening the popover added a modal record on top of the detail surface's own: "
            f"{dialog_records_before_popover} -> {session.dialog_records()}"
        )
        # docs/PENDING_DOC_FIXES.md row 27's already-settled shape: the kit's own base CSS reset
        # sets `body { overflow: hidden }` unconditionally before any component mounts, so the
        # *value* is not the testable property — whether opening this popover *changes* it is.
        body_overflow_after_open = session.page.evaluate("() => getComputedStyle(document.body).overflow")
        assert body_overflow_after_open == body_overflow_before, (
            f"opening the popover changed document.body overflow: "
            f"{body_overflow_before!r} -> {body_overflow_after_open!r}"
        )

        # --- all seven scales, eight named elements (see module docstring) ---------------------------
        life_els = session.page.locator(_in_popover('.schedule-popover__row[data-scale="life"] [data-period-key]'))
        assert life_els.count() == 1, f"expected 1 life element, found {life_els.count()}"

        decade_els = session.page.locator(_in_popover('.schedule-popover__row[data-scale="decade"] .schedule-popover__stepper-label'))
        assert decade_els.count() == 1, f"expected 1 decade element, found {decade_els.count()}"

        year_els = session.page.locator(_in_popover('.schedule-popover__row[data-scale="year"] .schedule-popover__stepper-label'))
        assert year_els.count() == 1, f"expected 1 year element, found {year_els.count()}"

        quarter_els = session.page.locator(_in_popover('[data-scale="quarter"]'))
        assert quarter_els.count() == 4, f"expected 4 quarter elements, found {quarter_els.count()}"

        month_els = session.page.locator(_in_popover('.schedule-popover__row[data-scale="month"] .schedule-popover__stepper-label'))
        assert month_els.count() == 1, f"expected 1 month element, found {month_els.count()}"

        week_container = session.page.locator(_in_popover('[data-scale="week"]'))
        assert week_container.count() == 1, f"expected 1 ISO-week column container, found {week_container.count()}"

        day_container = session.page.locator(_in_popover('[data-scale="day"]'))
        assert day_container.count() == 1, f"expected 1 day grid container, found {day_container.count()}"

        footer = session.page.locator(_in_popover('[data-role="schedule-footer"]'))
        assert footer.count() == 1, f"expected 1 today/tomorrow/this-week footer, found {footer.count()}"
        footer_buttons = footer.locator("button")
        assert footer_buttons.count() == 3, f"expected 3 footer shortcuts, found {footer_buttons.count()}"

        distinct_scales = {"life", "decade", "year", "quarter", "month", "week", "day"}
        present_scales = set(
            session.page.locator(_in_popover("[data-scale]")).evaluate_all(
                "els => els.map(el => el.getAttribute('data-scale'))"
            )
        )
        assert distinct_scales <= present_scales, f"missing scale(s): {distinct_scales - present_scales}"

        # --- step 2: click the W32 cell (gesture 2) -------------------------------------------------
        w32_cell = session.page.locator(_in_popover('.schedule-popover__weeks [data-period-key="2026-W32"]'))
        assert w32_cell.count() == 1, f"expected exactly one W32 week cell, found {w32_cell.count()}"
        # No-reload marker: a JS global survives an SPA-internal re-render but is wiped by any
        # real navigation (the whole JS realm resets). Not `performance.getEntriesByType
        # ('navigation')` — confirmed live that under this suite's pinned virtual clock
        # (`page.clock.set_fixed_time`, E2E.md §1 entry 3) the entire Performance Timeline buffer
        # reads empty (`performance.getEntries().length === 0`, `performance.navigation` itself
        # `None`), before *and* after any navigation — an artifact of the fake-timers mechanism
        # `page.clock` is built on, not a real signal, so it can't tell reload from no-reload here.
        session.page.evaluate("() => { window.__wp22NoReloadMarker = true }")

        session.gestures.click(_in_popover('.schedule-popover__weeks [data-period-key="2026-W32"]'))
        assert session.gestures.count == 2, f"expected gesture count 2, got {session.gestures.count}"

        # --- no page reload --------------------------------------------------------------------------
        # The detail surface is a full-screen `KModal` (`.modal`, kit CSS `z-index: 200`) — its
        # scrim sits above everything else in the shell, including `.app-nav`, which carries no
        # elevated `z-index` of its own and is therefore genuinely unreachable by a real pointer
        # click while the modal is open (measured live: the nav click above timed out, Playwright
        # reporting `.modal__scrim` intercepting the event). Closing the surface first is a real
        # gesture the product requires here — not a scenario shortcut — before the nav switch that
        # reads `[data-vertical="week"]` (`Board.vue`'s own column, unmounted while Inbox is active).
        # `window.__wp22NoReloadMarker` lives on the JS realm, not the DOM, so closing the modal
        # (an SPA-internal state change) does not touch it either way.
        #
        # Two Escapes, not one: `pick()` (`SchedulePopover.vue`'s own doc comment) never closes
        # the dropdown itself on selection — a kit gap, reported there, not DOM-poked around from
        # here — so the popover this scenario just picked a cell from is still open. The first
        # Escape is `useDropdown`'s own (closes the popover); only the second reaches `KModal`'s.
        session.page.keyboard.press("Escape")
        popover.wait_for(state="hidden", timeout=5000)
        session.page.keyboard.press("Escape")
        session.page.wait_for_selector(DETAIL_TRIGGER, state="hidden", timeout=5000)
        switch_view(session.page, "verticals")
        session.page.wait_for_selector(f'[data-vertical="week"] [data-goal-id="{PRIMARY_GOAL}"]', timeout=5000)
        marker_survived = session.page.evaluate("() => window.__wp22NoReloadMarker === true")
        assert marker_survived, "window.__wp22NoReloadMarker did not survive — a page reload happened"

        # --- DB: period_key moved, card moved columns -------------------------------------------------
        after = conn.execute(
            "SELECT vertical, period_key, anchor_date FROM goals WHERE id = %s", (PRIMARY_GOAL,)
        ).fetchone()
        vertical, period_key, anchor_date = after
        assert period_key == "2026-W32", f"expected period_key '2026-W32', got {period_key!r}"
        assert vertical == "week", f"expected vertical 'week', got {vertical!r}"
        assert anchor_date is not None, "vertical_needs_anchor: anchor_date must not be null after scheduling"

        assert session.page.locator(f'[data-vertical="week"] [data-goal-id="{PRIMARY_GOAL}"]').count() == 1, (
            f"{PRIMARY_GOAL} did not render in the week column"
        )
        # Ruling 1 retired the board's own Maybe column (`[data-vertical="maybe"]` no longer
        # exists on `Board.vue` at all) — the honest form of "no longer Maybe" now is "no longer
        # in the Inbox view", `InboxView.vue`'s own card list.
        switch_view(session.page, "inbox")
        session.page.wait_for_selector('[data-cap="inbox"]', timeout=5000)
        assert session.page.locator(f'[data-cap="inbox"] [data-goal-id="{PRIMARY_GOAL}"]').count() == 0, (
            f"{PRIMARY_GOAL} still rendered in the Inbox view after being scheduled to week"
        )
        switch_view(session.page, "verticals")
        session.page.wait_for_selector(f'[data-vertical="week"] [data-goal-id="{PRIMARY_GOAL}"]', timeout=5000)

        # --- supplementary, non-gesture-budget-counted check: scheduling to life (E2E.md's own
        # Assert block requires this even though it is outside the scenario's literal 2-step "Steps"
        # list) — a *different* goal/popover so as not to disturb the assertions already made above.
        # PRIMARY_GOAL's own detail surface was already closed above (the nav-reachability fix), so
        # there is nothing left to close here — SECONDARY_GOAL's own detail is simply opened fresh;
        # neither its opening nor the trigger/cell clicks below are routed through
        # `session.gestures`, so they never inflate the 2-gesture budget already checked and passed.
        # It gets the same close-before-nav treatment below, for the same reason: `App.vue`'s
        # `onNavClick` does call `store.closeGoal()` itself, but only *after* the click lands —
        # and a real pointer click at the nav bar's on-screen position never lands at all while the
        # modal's full-viewport scrim (`z-index: 200`, no elevated `z-index` on `.app-nav` to beat
        # it) sits on top of it, so the handler's own cleanup never gets the chance to run.
        gestures_before_supplement = session.gestures.count
        # SECONDARY_GOAL is still unverticaled (Maybe) at this point — same Inbox detour as
        # PRIMARY_GOAL's own opening above, not routed through `session.gestures`.
        switch_view(session.page, "inbox")
        session.page.wait_for_selector('[data-cap="inbox"]', timeout=5000)
        session.page.click(_card_title(SECONDARY_GOAL))
        session.page.wait_for_selector(DETAIL_TRIGGER, timeout=5000)
        session.page.click(DETAIL_TRIGGER)
        life_cell = session.page.locator(_in_popover('.schedule-popover__row[data-scale="life"] [data-period-key="life"]'))
        life_cell.wait_for(state="visible")
        life_popover = session.page.locator(DETAIL_POPOVER)
        session.page.click(_in_popover('.schedule-popover__row[data-scale="life"] [data-period-key="life"]'))
        # `[data-vertical="life"]` is `Board.vue`'s own column — Inbox is still the active nav view
        # from the click above, so switch back before reading it (a nav click, not a scenario
        # gesture, same reasoning as the supplementary block's own header comment). Close the
        # popover then the modal first — the same two-Escape reason as PRIMARY_GOAL's own close
        # above: `pick()` never closes the popover on selection, and the nav click can't land
        # through the modal's scrim until the modal itself is gone.
        session.page.keyboard.press("Escape")
        life_popover.wait_for(state="hidden", timeout=5000)
        session.page.keyboard.press("Escape")
        session.page.wait_for_selector(DETAIL_TRIGGER, state="hidden", timeout=5000)
        switch_view(session.page, "verticals")
        session.page.wait_for_selector(f'[data-vertical="life"] [data-goal-id="{SECONDARY_GOAL}"]', timeout=5000)
        # These clicks (close, reopen, trigger, cell) are supplementary verification, not scripted
        # "Steps" of S-66 — deliberately not routed through `session.gestures` so they never inflate
        # the 2-gesture budget asserted above (already checked and passed before this block began).
        assert session.gestures.count == gestures_before_supplement, "supplementary life-check must not touch the gesture budget"

        life_row = conn.execute(
            "SELECT vertical, period_key, anchor_date FROM goals WHERE id = %s", (SECONDARY_GOAL,)
        ).fetchone()
        life_vertical, life_period_key, life_anchor = life_row
        assert life_vertical == "life", f"expected vertical 'life', got {life_vertical!r}"
        assert life_period_key == "life", f"expected period_key 'life', got {life_period_key!r}"
        # scheduleGrid.anchorDate('life', ...) returns isoDate(today) — the pinned clock's date.
        assert str(life_anchor) == "2026-08-08", f"expected anchor_date 2026-08-08, got {life_anchor}"
    finally:
        conn.close()
