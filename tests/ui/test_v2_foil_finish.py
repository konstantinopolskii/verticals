"""D105 iridescent finish through Chromium, live HTTP, and real Postgres."""

from __future__ import annotations

import re

import pytest
from playwright.sync_api import expect

from tests.ui.conftest import UiSession, activate_column

MENU = '[data-role="goal-context-menu"]'
CARD = '[data-goal-id="SYNCOL04"]'
LAST_COLUMN_CARD = '[data-vertical="life"] [data-goal-id="SYNLIF01"]'
OVERLAY = '[data-role="iridescent-overlay"]'

pytestmark = pytest.mark.skip(
    reason='Foil is off the card (KK, 27 Sep 2026: "let\'s kill the foil option. It\'s a mess for now"): no menu item, no '
    "shimmer. The stored flag and kit-ext/iridescent stay for when it comes back, and so does this file."
)


@pytest.fixture
def ui_reduced_motion(request: pytest.FixtureRequest) -> str:
    """Keep suite default; opt the shader scenario into motion with indirect parametrization."""
    return getattr(request, "param", "reduce")


def _toggle_foil(session: UiSession) -> None:
    _toggle_foil_card(session, CARD, "SYNCOL04")


def _toggle_foil_card(session: UiSession, selector: str, goal_id: str) -> None:
    card = session.page.locator(selector)
    card.wait_for(state="visible")
    vertical = card.evaluate("el => el.closest('[data-vertical]').dataset.vertical")
    activate_column(session.page, vertical)
    card.click(button="right")
    with session.page.expect_response(
        lambda response: response.request.method == "PATCH"
        and response.url.endswith(f"/api/goals/{goal_id}")
    ):
        session.page.click(f'{MENU} [data-menu-item="foil"]')


def _assert_canvas_covers_card_center(session: UiSession, selector: str) -> None:
    geometry = session.page.locator(selector).evaluate(
        """card => {
          const canvas = document.querySelector('[data-role="iridescent-overlay"]');
          const cardRect = card.getBoundingClientRect();
          const canvasRect = canvas.getBoundingClientRect();
          return {
            canvasHidden: canvas.hidden,
            canvas: {
              left: canvasRect.left,
              top: canvasRect.top,
              right: canvasRect.right,
              bottom: canvasRect.bottom,
            },
            center: {
              x: cardRect.left + cardRect.width / 2,
              y: cardRect.top + cardRect.height / 2,
            },
          };
        }"""
    )
    assert geometry["canvasHidden"] is False
    assert geometry["canvas"]["left"] <= geometry["center"]["x"] <= geometry["canvas"]["right"]
    assert geometry["canvas"]["top"] <= geometry["center"]["y"] <= geometry["canvas"]["bottom"]


@pytest.mark.parametrize("ui_reduced_motion", ["no-preference"], indirect=True)
def test_foil_toggle_registers_shared_overlay_and_unregisters_last_card(
    ui_f2: UiSession,
) -> None:
    session = ui_f2
    page = session.page
    card = page.locator(CARD)
    overlay = page.locator(OVERLAY)
    expect(overlay).to_have_count(1)
    expect(overlay).to_be_hidden()

    _toggle_foil(session)
    expect(card).to_have_class(re.compile(r"\bfoil\b"))
    expect(card).to_have_attribute("data-foil", "true")
    expect(overlay).to_have_attribute("data-tier", "webgl")
    expect(overlay).to_be_visible()
    _assert_canvas_covers_card_center(session, CARD)
    print("IRIDESCENT_HEADLESS_TIER: webgl (SwiftShader overlay visible)")

    _toggle_foil(session)
    expect(card).not_to_have_class(re.compile(r"\bfoil\b"))
    expect(card).not_to_have_attribute("data-foil", "true")
    expect(page.locator(".foil")).to_have_count(0)
    expect(overlay).to_be_hidden()


@pytest.mark.parametrize("ui_reduced_motion", ["no-preference"], indirect=True)
def test_foil_overlay_covers_card_in_last_visible_column(ui_f2: UiSession) -> None:
    session = ui_f2
    page = session.page
    card = page.locator(LAST_COLUMN_CARD)
    overlay = page.locator(OVERLAY)

    card.scroll_into_view_if_needed()
    right_edge = page.locator('[data-vertical="life"]').evaluate(
        "column => ({ right: column.getBoundingClientRect().right, viewport: window.innerWidth })"
    )
    assert right_edge["right"] >= right_edge["viewport"] - 1

    _toggle_foil_card(session, LAST_COLUMN_CARD, "SYNLIF01")
    expect(card).to_have_class(re.compile(r"\bfoil\b"))
    expect(card).to_have_attribute("data-foil", "true")
    expect(overlay).to_have_attribute("data-tier", "webgl")
    expect(overlay).to_be_visible()
    _assert_canvas_covers_card_center(session, LAST_COLUMN_CARD)


def test_reduced_motion_uses_static_finish_without_canvas_loop(ui_f2: UiSession) -> None:
    session = ui_f2
    card = session.page.locator(CARD)
    overlay = session.page.locator(OVERLAY)

    _toggle_foil(session)
    expect(card).to_have_class(re.compile(r"\bfoil--static\b"))
    expect(card).to_have_attribute("data-foil", "true")
    expect(overlay).to_have_attribute("data-tier", "static")
    expect(overlay).to_be_hidden()
