"""D231/D235 in the real browser: the colour picker is gone from the card menu, and hover lights a chain both ways.
The values the field once offered as filters (D233/D238/D239) left with its filter words (docs/design-handoff S1.P2.027).

Fixture F2 at the suite's pinned clock (2026-08-08). SYNCOL01 is a day root with no life ancestor, the hover test's
neutral bystander.
"""

from __future__ import annotations

from tests.ui.conftest import UiSession, activate_column

HOVER_CLASS = "goal-card--ancestor-hover"


def _has_hover_class(page, goal_id: str) -> bool:
    classes = page.locator(f'[data-goal-id="{goal_id}"]').first.get_attribute("class") or ""
    return HOVER_CLASS in classes.split()


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
    page.wait_for_timeout(450)  # the light waits for the pointer to rest 250 ms (lib/boardViewState.ts HOVER_REST_MS)
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
