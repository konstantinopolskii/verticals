"""An opened goal glides to the top of its column; once it closes, however it closes, the column scrolls back: the goal
nearest its top edge stands where it stood, even when the column's width changed the cards' height
(`web/src/lib/familyView.ts`)."""

from __future__ import annotations

import httpx
import pytest
from playwright.sync_api import Page

from tests.ui.conftest import UiSession, expand_column

ANCHOR_ISO = "2026-08-08"  # conftest.py's pinned clock: every goal lands in the column shown as current
COLUMN = "quarter"
SCROLLER = '.pattern-vertical-board__column[data-vertical="{}"] .period-slide:not([data-state="outgoing"])'
CONTENT_TOP = "(card, slide) => { let y = 0; for (let e = card; e && e !== slide; e = e.offsetParent) y += e.offsetTop; return y }"


@pytest.fixture
def ui_reduced_motion(request: pytest.FixtureRequest) -> str:
    return getattr(request, "param", "reduce")


def _create(session: UiSession, title: str, vertical: str) -> str:
    resp = httpx.post(
        f"{session.backend.base_url}/api/goals",
        json={"title": title, "vertical": vertical, "anchor_date": ANCHOR_ISO},
        headers={"Authorization": f"Bearer {session.backend.token}"},
        timeout=10,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _seed(session: UiSession) -> str:
    """A quarter column long enough to scroll, its titles wrapping more when it is narrow, and one month goal."""
    ids = [_create(session, f"SYN scroll back {i:02d}, a title long enough to wrap", COLUMN) for i in range(24)]
    month = _create(session, "SYN scroll back month", "month")
    session.page.reload()
    session.page.wait_for_selector(f'.goal-card[data-goal-id="{ids[-1]}"]')
    return month


def _scroll_top(page: Page) -> float:
    return page.locator(SCROLLER.format(COLUMN)).evaluate("el => el.scrollTop")


def _scroll_to(page: Page, top: int) -> None:
    page.locator(SCROLLER.format(COLUMN)).evaluate("(el, top) => { el.scrollTop = top }", top)


def _top_row(page: Page) -> tuple[str, float]:
    """The goal nearest the column's top edge and where it stands in the window, as laid out (no hover lift)."""
    return page.locator(SCROLLER.format(COLUMN)).evaluate(
        f"""slide => {{
          const top = {CONTENT_TOP}
          for (const card of slide.querySelectorAll('.goal-card[data-row-key]')) {{
            const y = top(card, slide) - slide.scrollTop
            if (y + card.offsetHeight > 0) return [card.dataset.rowKey, y]
          }}
          return null
        }}"""
    )


def _window_top(page: Page, row_key: str) -> float:
    return page.locator(SCROLLER.format(COLUMN)).evaluate(
        f"(slide, key) => ({CONTENT_TOP})(slide.querySelector(`.goal-card[data-row-key=\"${{key}}\"]`), slide) - slide.scrollTop",
        row_key,
    )


def _goal_low_in_window(page: Page) -> str:
    return page.locator(SCROLLER.format(COLUMN)).evaluate(
        f"""slide => {{
          const top = {CONTENT_TOP}
          for (const card of slide.querySelectorAll('.goal-card[data-row-key]')) {{
            if (top(card, slide) - slide.scrollTop > slide.clientHeight / 2) return card.dataset.goalId
          }}
          return null
        }}"""
    )


def _settle(page: Page) -> None:
    page.wait_for_function("() => !document.body.dataset.familyMoving")
    last = None
    for _ in range(40):
        now = _scroll_top(page)
        if now == last:
            return
        last = now
        page.wait_for_timeout(150)


def _open(page: Page, goal_id: str, vertical: str = COLUMN) -> None:
    card = f'.pattern-vertical-board__column[data-vertical="{vertical}"] .goal-card[data-goal-id="{goal_id}"]'
    page.locator(f"{card} > .goal-card__row .goal-card__title").first.click()
    page.wait_for_selector(f'.goal-card--detail-open[data-goal-id="{goal_id}"]')
    _settle(page)


def _closed(page: Page) -> None:
    page.wait_for_selector(".goal-card--detail-open", state="detached")
    _settle(page)


@pytest.mark.parametrize("ui_reduced_motion", ["reduce", "no-preference"], indirect=True)
def test_closing_scrolls_the_column_back(ui_f2: UiSession) -> None:
    page = ui_f2.page
    _seed(ui_f2)

    # from a narrow column, which stays wide once the goal closes
    _scroll_to(page, 400)
    key, at = _top_row(page)
    _open(page, _goal_low_in_window(page))
    assert _scroll_top(page) > 500, "the opened goal glides up"
    page.keyboard.press("Escape")
    _closed(page)
    assert _window_top(page, key) == pytest.approx(at, abs=1)

    # in the wide column, closed by a press beside the goal
    _scroll_to(page, 250)
    scrolled = _scroll_top(page)
    _open(page, _goal_low_in_window(page))
    assert _scroll_top(page) > scrolled + 100
    page.evaluate("() => document.body.dispatchEvent(new PointerEvent('pointerdown', { bubbles: true }))")
    _closed(page)
    assert _scroll_top(page) == pytest.approx(scrolled, abs=1)


@pytest.mark.parametrize("wide", [False, True], ids=["narrow", "wide"])
def test_a_goal_opened_in_another_column_scrolls_the_old_one_back(ui_f2: UiSession, wide: bool) -> None:
    page = ui_f2.page
    month = _seed(ui_f2)
    if wide:
        expand_column(page, COLUMN)
    _scroll_to(page, 400)
    key, at = _top_row(page)
    _open(page, _goal_low_in_window(page))

    _open(page, month, "month")
    assert _window_top(page, key) == pytest.approx(at, abs=1)
