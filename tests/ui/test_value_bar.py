"""D231/D233/D235/D238 in the real browser, as the bottom bar has them since it became one field ("filter board
from one field", 3bc40f9): the values that were links in the app nav (D238) are commands in "Find, filter or ask".
Focused and empty, the field offers each value by its one word (D239); taking one narrows the board to that value's
goals, and taking it away brings the whole board back. The picker is gone, hover runs both directions.

Fixture F2 at the suite's pinned clock (2026-08-08). SYNLIF01 is the only parentless life root,
so the field offers exactly one value. SYNCOL01 is a day root with no life ancestor — the
filter's witness (it must vanish) and the hover test's neutral bystander.
"""

from __future__ import annotations

import httpx
from playwright.sync_api import expect

from tests.ui.conftest import UiSession, activate_column
from tests.ui.views import FIELD, switch_view

VALUE = '.command-field__suggestions [data-token="area:SYNLIF01"]'
TOKEN = ".command-field__token"
HOVER_CLASS = "goal-card--ancestor-hover"


def _has_hover_class(page, goal_id: str) -> bool:
    classes = page.locator(f'[data-goal-id="{goal_id}"]').first.get_attribute("class") or ""
    return HOVER_CLASS in classes.split()


def test_value_filters_the_board_and_taking_it_away_restores(ui_f2: UiSession) -> None:
    session = ui_f2
    page = session.page
    page.wait_for_selector('[data-goal-id="SYNDAY01"]', timeout=10000)

    # The field offers the one value; the D234 bar and the D238 nav links are gone.
    page.locator(FIELD).click()
    expect(page.locator('.command-field__suggestions [data-token^="area:"]')).to_have_count(1)
    assert page.locator(".value-bar, .value-bar__dot, [data-cap=value-filter]").count() == 0

    # D233: the value narrows the dated columns; the unvalued day root vanishes.
    page.locator(VALUE).click()
    page.wait_for_selector('[data-goal-id="SYNCOL01"]', state="detached", timeout=10000)
    expect(page.locator('[data-goal-id="SYNDAY01"]')).to_be_visible()
    live = page.locator(TOKEN, has_text="Live")
    expect(live).to_have_count(1)

    # Taking the value away restores the whole board.
    live.click()
    page.wait_for_selector('[data-goal-id="SYNCOL01"]', timeout=10000)
    expect(page.locator('[data-goal-id="SYNDAY01"]')).to_be_visible()


def test_value_wears_one_word(ui_f2: UiSession) -> None:
    session = ui_f2
    page = session.page
    page.wait_for_selector('[data-goal-id="SYNDAY01"]', timeout=10000)

    # D239 fallback: no short_label set, the value shows the title's FIRST WORD, never the whole
    # title. SYNLIF01's fixture title is two words ("Live deliberately", f2_synth.sql).
    page.locator(FIELD).click()
    assert (page.locator(VALUE).text_content() or "").strip() == "Live"

    # D239 explicit: a short_label set over the API (the only writable surface — value roots
    # only) replaces the fallback after the board refetches.
    patched = httpx.patch(
        f"{session.backend.base_url}/api/goals/SYNLIF01",
        json={"short_label": "Money"},
        headers={"Authorization": f"Bearer {session.backend.token}"},
        timeout=10,
    )
    assert patched.status_code == 200, patched.text
    page.reload()
    page.wait_for_selector('[data-goal-id="SYNDAY01"]', timeout=10000)
    page.locator(FIELD).click()
    assert (page.locator(VALUE).text_content() or "").strip() == "Money"


def test_value_chosen_in_inbox_narrows_the_board_it_returns_to(ui_f2: UiSession) -> None:
    session = ui_f2
    page = session.page
    page.wait_for_selector('[data-goal-id="SYNDAY01"]', timeout=10000)

    # D238's one gesture (a value from Inbox switched and filtered) is two tokens in one field now, the view and the
    # value: taken in Inbox, the value stays when Inbox is taken away, so the board comes back narrowed to it.
    switch_view(page, "inbox")
    page.locator(FIELD).click()
    page.locator(VALUE).click()
    switch_view(page, "verticals")
    page.wait_for_selector('[data-goal-id="SYNDAY01"]', timeout=10000)
    expect(page.locator('[data-goal-id="SYNCOL01"]')).to_have_count(0)
    expect(page.locator(TOKEN, has_text="Live")).to_have_count(1)


def test_colour_picker_is_gone_from_the_card_menu(ui_f2: UiSession) -> None:
    session = ui_f2
    page = session.page
    page.wait_for_selector('[data-goal-id="SYNDAY01"]', timeout=10000)

    # D231 made stored colour un-editable in the product UI: open the one card menu that used to
    # carry the swatch row and prove the picker is absent, while the menu itself still opens.
    page.click('[data-goal-id="SYNDAY01"] > .goal-card__row [data-role="goal-actions-trigger"]')
    page.wait_for_selector('[data-role="goal-actions-menu"]', timeout=10000)
    assert page.locator('[data-role="goal-color-picker"]').count() == 0
    page.keyboard.press("Escape")


def test_hover_highlights_ancestors_and_descendants(ui_f2: UiSession) -> None:
    session = ui_f2
    page = session.page
    # D244: SYNQ2R01 folds into SYNQ1R01's compact stack — wait for the board via the face card,
    # expand below, then the nested row exists to hover.
    page.wait_for_selector('[data-goal-id="SYNQ1R01"]', timeout=10000)

    # D235: hovering SYNQ2R01 (quarter) lights the chain in BOTH directions — SYNLIF01 up,
    # SYNDAY01 down — and leaves the unrelated SYNCOL01 neutral. SYNQ2R01 is SYNQ1R01's
    # same-column subtask, so on the compact board (D244) it lives folded in the stack until the
    # quarter column expands — activate_column is that move now.
    activate_column(page, "quarter")
    page.hover('[data-goal-id="SYNQ2R01"] .goal-card__title')
    page.wait_for_timeout(100)
    assert _has_hover_class(page, "SYNLIF01"), "ancestor must light up"
    assert _has_hover_class(page, "SYNDAY01"), "descendant must light up"
    assert not _has_hover_class(page, "SYNCOL01"), "unrelated card must stay neutral"

    # Leaving the card clears every mark. Move to the top-left corner — guaranteed off every
    # card, unlike hovering `body` whose centre point can land on another card in the chain.
    # The clear lands after the D244 hover grace (~250ms — store.ts HOVER_CLEAR_GRACE_MS, the
    # window that makes a swapped stack face reachable), so the wait must outlast it.
    page.mouse.move(5, 5)
    page.wait_for_timeout(450)
    assert not _has_hover_class(page, "SYNLIF01")
    assert not _has_hover_class(page, "SYNDAY01")
