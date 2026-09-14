"""D231/D233/D235/D238 in the real browser: value links in the app nav filter the board, the
picker is gone, hover runs both directions.

D238 (KK, 2026-08-15, correcting D234): the value filter is plain items in the shell's one nav
row — "Inbox | Verticals | <value> ..." — the same `.app-nav__link` component the two view links
use. No bottom bar, no dots, no colour in the menu. "Verticals" doubles as the unfiltered board.

Fixture F2 at the suite's pinned clock (2026-08-08). SYNLIF01 is the only parentless life root,
so the nav renders exactly one value link. SYNCOL01 is a day root with no life ancestor — the
filter's witness (it must vanish) and the hover test's neutral bystander.
"""

from __future__ import annotations

import httpx
from playwright.sync_api import expect

from tests.ui.conftest import UiSession, activate_column

NAV = "[data-cap=value-filter]"
ACTIVE = "app-nav__link--active"
HOVER_CLASS = "goal-card--ancestor-hover"


def _is_active(page, selector: str) -> bool:
    classes = page.locator(selector).get_attribute("class") or ""
    return ACTIVE in classes.split()


def _has_hover_class(page, goal_id: str) -> bool:
    classes = page.locator(f'[data-goal-id="{goal_id}"]').first.get_attribute("class") or ""
    return HOVER_CLASS in classes.split()


def test_value_links_filter_and_verticals_restores(ui_f2: UiSession) -> None:
    session = ui_f2
    page = session.page
    page.wait_for_selector('[data-goal-id="SYNDAY01"]', timeout=10000)

    # D238: the value link is a sibling of the two view links, same component, no dot anywhere.
    verticals_btn = page.locator(f'{NAV} [data-nav-item="verticals"]')
    value_btn = page.locator(f'{NAV} [data-value-id="SYNLIF01"]')
    expect(page.locator(f"{NAV} [data-value-id]")).to_have_count(1)
    assert page.locator(".value-bar, .value-bar__dot").count() == 0, "the D234 bar must be gone"
    assert _is_active(page, f'{NAV} [data-nav-item="verticals"]')
    assert not _is_active(page, f'{NAV} [data-value-id="SYNLIF01"]')

    # D233: click narrows the dated columns server-side; the unvalued day root vanishes.
    value_btn.click()
    page.wait_for_selector('[data-goal-id="SYNCOL01"]', state="detached", timeout=10000)
    expect(page.locator('[data-goal-id="SYNDAY01"]')).to_be_visible()
    assert _is_active(page, f'{NAV} [data-value-id="SYNLIF01"]')
    assert not _is_active(page, f'{NAV} [data-nav-item="verticals"]'), (
        "Verticals means the unfiltered board; a filtered board must not mark it active"
    )
    # The nav itself survives the filter: it reads the board's never-narrowed `values` list
    # (D240 — the life COLUMN narrows now), so the menu keeps offering every value.
    expect(page.locator(f"{NAV} [data-value-id]")).to_have_count(1)

    # Verticals restores the whole board (it doubles as All — D238 has no separate All button).
    verticals_btn.click()
    page.wait_for_selector('[data-goal-id="SYNCOL01"]', timeout=10000)
    expect(page.locator('[data-goal-id="SYNDAY01"]')).to_be_visible()
    assert _is_active(page, f'{NAV} [data-nav-item="verticals"]')


def test_value_link_wears_one_word(ui_f2: UiSession) -> None:
    session = ui_f2
    page = session.page
    page.wait_for_selector('[data-goal-id="SYNDAY01"]', timeout=10000)

    # D239 fallback: no short_label set, the link shows the title's FIRST WORD, never the whole
    # title. SYNLIF01's fixture title is two words ("Live deliberately", f2_synth.sql).
    value_btn = page.locator(f'{NAV} [data-value-id="SYNLIF01"]')
    assert (value_btn.text_content() or "").strip() == "Live"

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
    assert (page.locator(f'{NAV} [data-value-id="SYNLIF01"]').text_content() or "").strip() == "Money"


def test_value_link_from_inbox_switches_to_the_filtered_board(ui_f2: UiSession) -> None:
    session = ui_f2
    page = session.page
    page.wait_for_selector('[data-goal-id="SYNDAY01"]', timeout=10000)

    # From Inbox a value click is a view switch AND a filter, one gesture (D238).
    page.click(f'{NAV} [data-nav-item="inbox"]')
    page.wait_for_selector('[data-cap="inbox"]', timeout=10000)
    page.click(f'{NAV} [data-value-id="SYNLIF01"]')
    page.wait_for_selector('[data-goal-id="SYNDAY01"]', timeout=10000)
    page.wait_for_selector('[data-goal-id="SYNCOL01"]', state="detached", timeout=10000)
    assert _is_active(page, f'{NAV} [data-value-id="SYNLIF01"]')


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
