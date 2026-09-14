"""S-70 — L4 in the UI: progress moves, the parent does not close.

docs/E2E.md §6 S-70 (line 1706). Fixture F2. Required by AC-112 (and AC-033's UI half). Serves L4,
Stage 4, §0.

Three claims in one scenario, and they pull against each other on purpose:

  * the rollup is visible and live — closing one leaf moves six ancestors' labels to the S-17
    table, within 400 ms;
  * nothing navigates while it happens (`performance.getEntriesByType('navigation')` stays at one
    entry, so a reload cannot be what produced the new numbers);
  * and the top of the chain does not close — `SYNLIF01.done_at` is still NULL, because completion
    never propagates (S-18/L4), and a life card carries no checkbox to close it with (§0).

The S-17 table verbatim, since it is what "every intermediate ancestor" means here.
"""

from __future__ import annotations

import time

import httpx
import psycopg
from playwright.sync_api import expect

from tests.ui.conftest import UiSession, activate_column

# `docs/E2E.md` S-17's own table, `(id, before, after)`. Root first, leaf's parent last.
CHAIN = (
    ("SYNLIF01", "0/8", "1/8"),
    ("SYNYRR01", "0/6", "1/6"),
    ("SYNQ1R01", "0/5", "1/5"),
    ("SYNQ2R01", "0/4", "1/4"),
    ("SYNDAY01", "0/3", "1/3"),
)

# R3 kit-ext leaf square: wrapper is click surface; nested input remains checked-state probe.
LEAF_AFFORDANCE = (
    '[data-goal-id="SYNSUB01"] > .goal-card__row '
    '[data-role="goal-affordance"][data-affordance="leaf"]'
)
LEAF_CHECKBOX = f'{LEAF_AFFORDANCE} input.checkbox__input'
def _progress(page, goal_id: str):
    return page.locator(f'[data-goal-id="{goal_id}"] > .goal-card__row [data-role=milestone-ring]')


def test_s70_progress_moves_parent_stays_open(ui_f2: UiSession) -> None:
    session = ui_f2
    page = session.page
    scheduled = httpx.put(
        f"{session.backend.base_url}/api/goals/SYNSUB01/schedule",
        json={"vertical": "day", "anchor_date": "2026-08-08"},
        headers={"Authorization": f"Bearer {session.backend.token}"},
        timeout=10,
    )
    assert scheduled.status_code == 200, scheduled.text
    page.reload()
    page.wait_for_selector('[data-goal-id="SYNLIF01"]', timeout=10000)
    # D142: both hierarchy levels render expanded with no collapse control.
    assert page.locator('[data-role="subgoal-toggle"]').count() == 0
    # D244: SYNSUB01 lives folded in the compact day stack until the column expands.
    activate_column(page, "day")
    page.wait_for_selector(LEAF_CHECKBOX, timeout=10000)

    conn = psycopg.connect(session.backend.dsn, autocommit=True)
    try:
        (life_before,) = conn.execute(
            "SELECT done_at FROM goals WHERE id = 'SYNLIF01'"
        ).fetchone()
        assert life_before is None, "SYNLIF01 must start open for this scenario to mean anything"

        assert page.locator(
            '[data-goal-id="SYNLIF01"] > .goal-card__row [data-role="milestone-ring"]'
        ).count() == 1
        assert page.locator(
            '[data-goal-id="SYNSUB01"] > .goal-card__row [data-role="leaf-square"]'
        ).count() == 1

        # --- the chain reads its "before" column ---------------------------------------------------
        # D244: SYNQ2R01 is SYNQ1R01's same-column subtask; its ring is in the DOM only while
        # the quarter column is expanded. The other four chain members are top-level cards and
        # render in every state.
        activate_column(page, "quarter")
        for goal_id, before, _ in CHAIN:
            expect(_progress(page, goal_id)).to_have_attribute(
                "aria-label", f"Milestone progress {before.replace('/', ' of ')}", timeout=5000
            )

        # Two independent readings of "no page reload", because neither alone is sound here.
        #
        # A marker on `window`: a reload builds a new JavaScript realm, so the property cannot
        # survive one. This is the positive check and it does not depend on the browser buffering
        # anything.
        #
        # And the navigation-timing entry count, asserted as *unchanged* rather than as a literal
        # 1. Measured on this suite's own Chromium: `performance.getEntriesByType('navigation')` is
        # empty here, not one-long — the buffer is cleared by the time the scenario reads it (the
        # pinned clock this suite installs, `page.clock.set_fixed_time`, is the plausible cause and
        # is not worth working around). A reload would still add an entry, so the delta carries the
        # claim even when the absolute number does not.
        page.evaluate("window.__s70Marker = 'set'")
        navigations_before = page.evaluate("performance.getEntriesByType('navigation').length")

        # --- the one gesture ------------------------------------------------------------------------
        # D244: unfold the day column BEFORE the timed gesture — the leaf row must be in the DOM
        # for the click, and the expansion is view navigation, not part of the completion gesture.
        activate_column(page, "day")
        requests_before = len(session.request_log)
        session.gestures.click(LEAF_AFFORDANCE)

        # --- within 400 ms, every ancestor moves to the S-17 table ------------------------------
        # `expect(...).to_have_text` polls and retries internally up to `timeout`; the raised
        # TimeoutError on breach is the observed failure text. The budget is applied to the top of
        # the chain (the assertion AC-112 names literally) and the rest are checked immediately
        # after — they are the same optimistic mutation in the same frame, so a generous timeout on
        # the tail cannot hide a slow first one.
        expect(_progress(page, "SYNLIF01")).to_have_attribute(
            "aria-label", "Milestone progress 1 of 8", timeout=400
        )
        # D244: the leaf click expanded the day column (one-expanded-at-a-time), folding
        # SYNQ2R01 away again; unfold quarter to read the tail of the chain. The values moved
        # in the same optimistic frame — remounting the card renders the already-updated state.
        activate_column(page, "quarter")
        for goal_id, _, after in CHAIN[1:]:
            expect(_progress(page, goal_id)).to_have_attribute(
                "aria-label", f"Milestone progress {after.replace('/', ' of ')}", timeout=1000
            )

        # --- and nothing navigated to produce them ---------------------------------------------
        assert page.evaluate("window.__s70Marker") == "set", (
            "the page reloaded during the gesture — the marker set before it did not survive"
        )
        navigations_after = page.evaluate("performance.getEntriesByType('navigation').length")
        assert navigations_after == navigations_before, (
            f"the page navigated during the gesture: navigation entries went "
            f"{navigations_before} -> {navigations_after}"
        )

        # --- the leaf closed, the top of the chain did not --------------------------------------
        activate_column(page, "day")  # D244: the leaf row unfolds with its column
        expect(page.locator(LEAF_CHECKBOX)).to_be_checked(timeout=2000)
        # The checkbox and the six labels all move optimistically, strictly before the PATCH
        # settles (`store.ts::completeGoal`), so reading the database at this instant is a race
        # against a request still in flight rather than a property of the app. Wait for the write
        # to actually land first — polling through `page.wait_for_timeout`, never a bare
        # `time.sleep`, which starves Playwright's own event dispatch and therefore this suite's
        # `requestfinished` listener (`tests/ui/conftest.py` records the measurement).
        deadline = time.monotonic() + 5.0
        goals_requests: list[dict] = []
        while time.monotonic() < deadline:
            # Non-GET only: D226's idle prefetch issues read-only GETs against /api/goals, and
            # this wait must land on the completion PATCH, not whichever prefetch resolves first.
            goals_requests = [
                r
                for r in session.request_log[requests_before:]
                if "/api/goals" in r["url"] and r["method"] != "GET"
            ]
            if goals_requests:
                break
            page.wait_for_timeout(20)
        assert goals_requests, "the completion never issued a request to /api/goals"
        assert goals_requests[0]["status"] == 200, f"the PATCH did not succeed: {goals_requests[0]}"

        (leaf_after,) = conn.execute("SELECT done_at FROM goals WHERE id = 'SYNSUB01'").fetchone()
        assert leaf_after is not None, "SYNSUB01.done_at is still null after completing it"
        (life_after,) = conn.execute("SELECT done_at FROM goals WHERE id = 'SYNLIF01'").fetchone()
        assert life_after is None, (
            f"completion propagated to SYNLIF01 — done_at is {life_after!r}, expected NULL"
        )
    finally:
        conn.close()
