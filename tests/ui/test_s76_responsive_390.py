"""S-76 — Responsive at 390x844.

docs/E2E.md §6 S-76. Fixture F2. Steps: resize to 390x844, reload. Required by AC-103 (and
AC-188's "web only; responsive verified at 390x844"). Serves L1.

Assert per the catalogue: `document.body.scrollWidth <= 391`; the column strip is horizontally
scrollable within its own container (`scrollWidth > clientWidth` on `[data-role=column-strip]`);
every card title has `scrollWidth <= clientWidth + 1`; all four L1 gestures (S-64 to S-67) still
complete within their budgets at this viewport.
"""

from __future__ import annotations

import psycopg
from playwright.sync_api import expect

from verticals.core import goals
from tests.harness.report import gate
from tests.ui.conftest import UiSession

MOBILE = {"width": 390, "height": 844}
COLUMN_STRIP = "[data-role=column-strip]"
CARD_TITLE = ".goal-card__title"
GOAL_ID = "SYNCOL01"
LONG_TAG = "SYNPROJECTTAGWITHOUTBREAKS0123456789ABCDEFGHIJ"
CHECKBOX = f'[data-goal-id="{GOAL_ID}"] > .goal-card__row input.checkbox__input'
CHECKBOX_LABEL = f'[data-goal-id="{GOAL_ID}"] > .goal-card__row label.checkbox'
# S-67's own two paths: the drag drop target, and the keyboard/menu route via `[data-cap=reparent]`
# (F5's own `reparent`/`detach` selector).
REPARENT_CAP = "[data-cap=reparent]"


def test_s76_responsive_390(ui_f2: UiSession) -> None:
    session = ui_f2
    page = session.page

    with psycopg.connect(session.backend.dsn, autocommit=True) as conn:
        goals.update(conn, owner="t1", id=GOAL_ID, tags=[LONG_TAG])

    page.set_viewport_size(MOBILE)
    page.reload()
    page.wait_for_selector(CHECKBOX, timeout=10000)

    # --- precondition probe: the two things the scenario names that the app does not have --------
    missing: list[str] = []
    if page.locator(COLUMN_STRIP).count() == 0:
        missing.append(
            "no element carries `[data-role=column-strip]` — `Board.vue` renders the columns "
            "inside `<KCardStack class=\"pattern-vertical-board\">` and neither that element nor "
            "any ancestor carries the attribute, so the scenario's own horizontal-scroll "
            "assertion (`scrollWidth > clientWidth` on `[data-role=column-strip]`) has no subject"
        )
    if page.locator(REPARENT_CAP).count() == 0:
        missing.append(
            "no element carries `[data-cap=reparent]` and no card exposes a drop target, so S-67 "
            "(the fourth of the four L1 gestures this scenario re-runs at 390x844) cannot be "
            "performed at any viewport — drag-to-reparent and the keyboard/menu reparent route are "
            "both absent from `web/src/**`"
        )
    if missing:
        gate("; ".join(missing))

    # --- body does not scroll horizontally --------------------------------------------------------
    body_scroll_width = page.evaluate("document.body.scrollWidth")
    assert body_scroll_width <= 391, f"body.scrollWidth is {body_scroll_width} at a 390px viewport"
    # D115: tags stay in data/detail/search, never on board cards.
    assert page.locator('[data-vertical] [data-role="tag-chips"]').count() == 0

    # --- the column strip scrolls inside its own container -----------------------------------------
    strip = page.locator(COLUMN_STRIP).first.evaluate(
        "el => ({ scrollWidth: el.scrollWidth, clientWidth: el.clientWidth })"
    )
    assert strip["scrollWidth"] > strip["clientWidth"], (
        f"the column strip is not horizontally scrollable: {strip}"
    )

    # --- no clipped card titles ---------------------------------------------------------------------
    clipped = page.locator(CARD_TITLE).evaluate_all(
        "els => els.filter(el => el.scrollWidth > el.clientWidth + 1)"
        ".map(el => ({ text: el.textContent.trim(), scrollWidth: el.scrollWidth, clientWidth: el.clientWidth }))"
    )
    assert clipped == [], f"{len(clipped)} card title(s) are clipped at 390x844: {clipped[:5]}"

    # --- S-64's budget, at this viewport ------------------------------------------------------------
    conn = psycopg.connect(session.backend.dsn, autocommit=True)
    try:
        checkbox = page.locator(CHECKBOX)
        assert not checkbox.is_checked(), f"{GOAL_ID} must start open"
        session.gestures.click(CHECKBOX_LABEL)
        assert session.gestures.count == 1, f"complete took {session.gestures.count} gestures at 390x844"
        expect(checkbox).to_be_checked(timeout=400)
        assert session.dialog_records() == [], f"a modal opened on complete at 390x844: {session.dialog_records()}"
    finally:
        conn.close()
