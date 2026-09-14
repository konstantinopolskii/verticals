"""S-64 — L1: complete in exactly one gesture.

docs/E2E.md lines 1560-1565. Fixture F2. R4 keeps the one-gesture contract on a leaf;
parents now open the unified context menu instead.
"""

from __future__ import annotations

import time

import psycopg
from playwright.sync_api import expect

from tests.ui.conftest import UiSession

GOAL_ID = "SYNCOL01"
CHECKBOX = f'[data-goal-id="{GOAL_ID}"] > .goal-card__row input.checkbox__input'
# `KCheckbox`'s own compiled template (decompiled from the vendored bundle): the native
# `<input class="checkbox__input">` sits *under* a sibling `<span class="checkbox__box">` that
# paints the visible faux-box on top of it (the standard custom-checkbox CSS pattern) — Playwright
# refuses to click the input directly ("<span class='checkbox__box'> intercepts pointer events",
# confirmed live). A real user does not aim at the invisible input either; they click the visible
# box, which sits inside the `<label class="checkbox">` wrapper that natively forwards the click
# to its descendant input. One `page.click` on the label is still exactly one gesture (E2E.md §6
# only requires "one committed input action issued by the harness" — it does not name a target
# element), so this is the click target; `CHECKBOX` above (the real input) stays what state
# assertions (`is_checked`/`expect(...).to_be_checked`) read.
CHECKBOX_LABEL = f'[data-goal-id="{GOAL_ID}"] > .goal-card__row label.checkbox'


def test_s64_complete_one_gesture(ui_f2: UiSession) -> None:
    session = ui_f2
    conn = psycopg.connect(session.backend.dsn, autocommit=True)
    try:
        (before,) = conn.execute("SELECT done_at FROM goals WHERE id = %s", (GOAL_ID,)).fetchone()
        assert before is None, f"{GOAL_ID} must start open for this scenario to mean anything"

        checkbox = session.page.locator(CHECKBOX)
        assert not checkbox.is_checked(), f"{GOAL_ID}'s checkbox must start unchecked"

        requests_before = len(session.request_log)

        # --- the one scripted gesture -------------------------------------------------------------
        t0 = time.monotonic()
        session.gestures.click(CHECKBOX_LABEL)
        assert session.gestures.count == 1, f"expected gesture count 1, got {session.gestures.count}"

        # --- modal record empty ---------------------------------------------------------------------
        assert session.dialog_records() == [], f"a modal opened on complete: {session.dialog_records()}"

        # --- within 400 ms the card shows the closed state --------------------------------------------
        # `expect(...).to_be_checked` polls/retries internally up to `timeout`; the raised
        # TimeoutError on breach *is* the observed failure text E2E.md's calibration rule asks a
        # threshold breach to be re-run once before reporting.
        expect(checkbox).to_be_checked(timeout=400)
        elapsed_ms = (time.monotonic() - t0) * 1000
        assert elapsed_ms < 1500, (  # generous outer sanity bound; the real budget is expect()'s own 400ms
            f"sanity bound blown too — {elapsed_ms:.0f}ms"
        )

        # --- exactly one request to /api/goals for this action -------------------------------------
        # store.ts::completeGoal flips `checked` optimistically, client-only, *before* the PATCH
        # settles (its own header comment: "Optimistic before the `await`") — so `to_be_checked`
        # above can pass on the optimistic flip alone, strictly before the network round trip
        # actually lands. Querying the DB at that instant is a genuine race against the still-in-
        # flight request, not a property of the app — confirmed live (the DB read came back NULL
        # while the checkbox already showed checked). Poll `session.request_log` for the request to
        # actually finish before reading the DB, so the DB assertion is checked once the write it
        # depends on is known to have happened, not raced against it.
        #
        # `session.page.wait_for_timeout`, never a bare `time.sleep`, inside this loop — confirmed
        # live that a raw `time.sleep` starves Playwright's own sync-API bridge (its Python
        # wrapper dispatches queued events, including this suite's own `requestfinished` listener
        # that fills `request_log`, only when a Playwright call itself yields control back to the
        # driver). A `time.sleep`-based version of this exact loop found 0 requests after the full
        # 2s budget on every one of 3 straight runs even though the real network request had
        # completed in well under 500ms each time — not a slow request, a starved listener.
        deadline = time.monotonic() + 2.0
        goals_requests: list[dict] = []
        while time.monotonic() < deadline:
            # Method filter: D226's idle prefetch sweep issues read-only GETs against /api/goals
            # at its own pace; the one-gesture-one-write claim is about mutations.
            goals_requests = [
                r
                for r in session.request_log[requests_before:]
                if "/api/goals" in r["url"] and r["method"] != "GET"
            ]
            if goals_requests:
                break
            session.page.wait_for_timeout(20)
        assert len(goals_requests) == 1, (
            f"expected exactly 1 mutating request to /api/goals for this action, got "
            f"{len(goals_requests)}: {[(r['method'], r['url']) for r in goals_requests]}"
        )
        assert goals_requests[0]["method"] == "PATCH", (
            f"expected the one /api/goals request to be PATCH, got {goals_requests[0]['method']}"
        )
        assert goals_requests[0]["status"] == 200, f"PATCH did not succeed: {goals_requests[0]}"

        # --- DB: done_at is not null -------------------------------------------------------------------
        # Safe to read now: the PATCH response (status 200, asserted above) already landed, and
        # `verticals/api` commits before responding (no fire-and-forget write path anywhere in this
        # codebase), so the row is guaranteed visible to a fresh connection at this point.
        (after,) = conn.execute("SELECT done_at FROM goals WHERE id = %s", (GOAL_ID,)).fetchone()
        assert after is not None, f"{GOAL_ID}.done_at is still null after completing"
    finally:
        conn.close()
