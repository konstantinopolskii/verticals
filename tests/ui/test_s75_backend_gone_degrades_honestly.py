"""S-75 — The UI degrades honestly when the backend is gone.

docs/E2E.md §6 S-75. Fixture F2. Steps: 1. Load the board. 2. Kill uvicorn. 3. Click a checkbox.
4. Restart uvicorn. 5. Reload. Required by AC-119. Serves Stage 5.

The outage is real: `Server.kill_backend()` SIGTERMs the actual `python -m verticals.api.app`
subprocess and waits for the port to be released. E2E.md §1's no-mocks rule is why — a routed-away
`page.route` or an injected 503 would be a test of the test, not of the product.
"""

from __future__ import annotations

import re
import time

import psycopg

from tests.harness.report import gate
from tests.ui.conftest import UiSession

GOAL_ID = "SYNCOL01"
AFFORDANCE = (
    f'[data-goal-id="{GOAL_ID}"] > .goal-card__row '
    '[data-role="goal-affordance"][data-affordance="leaf"]'
)
CHECKBOX = f"{AFFORDANCE} input.checkbox__input"

# The kit's `toast()` (`@konstantinopolskii/vue`, read from the vendored bundle) builds a
# `div.toast[role=status]` inside a `div.toast-stack[data-toast-stack][aria-live=polite]` appended
# to `<body>` — inline page furniture, no scrim, no focus trap, no `role="dialog"`, nothing
# `[data-modal]`. That is the element this scenario's "inline, non-modal status message" is.
STATUS = '.toast-stack .toast'
STATUS_TEXT = '.toast-stack .toast .toast__text'

# AC-122's own property test, applied to the one string this scenario produces (E2E.md S-75: "no
# emoji"). Python's `re` has no `\p{Extended_Pictographic}`, so the four assertion ranges S-78
# enumerates are used here — this is one short status string, not S-78's whole-surface scan.
EMOJI_RE = re.compile(
    "[\U0001f000-\U0001faff☀-➿⬀-⯿️‍"
    "‼⁉™ℹ〰〽㊗㊙]"
)


def test_s75_backend_gone_degrades_honestly(ui_f2: UiSession) -> None:
    session = ui_f2
    session.expects_network_failures = True  # step 3 is a deliberately-caused failed request
    page = session.page

    # --- 1: the board is loaded and real ----------------------------------------------------------
    page.wait_for_selector(CHECKBOX, timeout=10000)
    checkbox = page.locator(CHECKBOX)
    assert not checkbox.is_checked(), f"{GOAL_ID} must start open for this scenario to mean anything"

    conn = psycopg.connect(session.backend.dsn, autocommit=True)
    try:
        (before,) = conn.execute("SELECT done_at FROM goals WHERE id = %s", (GOAL_ID,)).fetchone()
        assert before is None, f"{GOAL_ID} must start open in the database too"

        # --- 2: kill uvicorn --------------------------------------------------------------------
        session.backend.kill_backend()

        # --- 3: click a checkbox — an inline, non-modal status within 5 s -------------------------
        t0 = time.monotonic()
        page.click(AFFORDANCE)
        page.wait_for_selector(STATUS, timeout=5000)
        elapsed = time.monotonic() - t0
        assert elapsed < 5.0, f"the status message took {elapsed:.1f}s to appear"

        message = page.locator(STATUS_TEXT).first.inner_text().strip()

        # non-modal: nothing with role=dialog or [data-modal] was ever added (instrumentation
        # entry 1, live since before app load).
        assert session.dialog_records() == [], (
            f"the failure opened a modal instead of an inline status: {session.dialog_records()}"
        )
        assert page.locator(STATUS).first.bounding_box() is not None, "the status message has no visible box"

        # no emoji, sentence case, names the condition. The emoji rule holds today, so it stays a
        # plain assertion; the other two are collected rather than asserted, so the rest of the
        # scenario (which does hold) is still exercised before this file reports its outcome. See
        # the gate at the bottom.
        assert EMOJI_RE.search(message) is None, f"the status message contains an emoji: {message!r}"
        defects: list[str] = []
        if not message[:1].isupper():
            defects.append(f"it is not sentence case (starts lowercase): {message!r}")
        if not re.search(r"reach|connect|offline|unavailable|backend|server|network", message, re.I):
            defects.append(
                f"it names an HTTP status number rather than the condition: {message!r}"
            )

        # the page did not white-screen.
        body_text = page.evaluate("document.body.innerText")
        assert len(body_text) > 200, f"the page collapsed to {len(body_text)} characters of text"

        # zero uncaught exceptions — asserted here as well as in teardown, so a breach is
        # attributed to this step rather than to the fixture.
        assert session.page_errors == [], f"uncaught exception(s) while the backend was down: {session.page_errors}"

        # --- 4: restart uvicorn -------------------------------------------------------------------
        session.backend.restart_backend()

        # --- 5: reload — the board is back and the failed write was not silently applied ------------
        page.reload()
        page.wait_for_selector(CHECKBOX, timeout=10000)
        assert not page.locator(CHECKBOX).is_checked(), (
            f"{GOAL_ID} renders as done after a write that never reached the server"
        )
        (after,) = conn.execute("SELECT done_at FROM goals WHERE id = %s", (GOAL_ID,)).fetchone()
        assert after is None, f"a failed write appeared to succeed: done_at = {after!r}"
    finally:
        conn.close()

    # --- the one thing S-75 requires that the app does not do ---------------------------------
    # Everything above holds: the outage is real, the status is inline and non-modal and arrives
    # well inside 5 s, the page keeps its content, no exception escapes, and the failed write is
    # neither applied nor faked. The message itself is the gap. With uvicorn dead, `vite preview`
    # answers the proxied PATCH with 502 and a JSON body carrying no `detail`/`error` key, so
    # `web/src/lib/api.ts::messageFrom` falls through to its last line —
    # `return `request failed with status ${status}`` — and that string is what `store.ts::toast`
    # shows. It is lowercase and it names a status code, not a condition a reader can act on.
    if defects:
        gate(
            "the inline status message the app shows when the backend is gone fails two of S-75's "
            "three text requirements: " + "; ".join(defects) + ". The string comes from "
            "`web/src/lib/api.ts::messageFrom`'s fallback branch "
            "(`request failed with status ${status}`), reached because a dead upstream produces a "
            "502 whose body carries neither `detail` nor `error`. S-75 needs a sentence-case "
            "message naming the unreachable backend (and, per AC-119, one that does not read as a "
            "success); every other assertion in this scenario already passes"
        )
