"""An opened goal is seen whole: one that doesn't fit scrolls into view just enough, one that fits leaves the column where
it is (`web/src/components/GoalDetail.vue`). Once it closes, however it closes, the column scrolls back: the goal stands
where it stood, even when the column's width changed the cards' height (`web/src/lib/familyView.ts`)."""

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


def _window_top(page: Page, goal_id: str) -> float:
    """Where the goal stands in the column's window, as laid out (no hover lift)."""
    return page.locator(SCROLLER.format(COLUMN)).evaluate(
        f"(slide, id) => ({CONTENT_TOP})(slide.querySelector(`.goal-card[data-goal-id=\"${{id}}\"]`), slide) - slide.scrollTop",
        goal_id,
    )


def _goals_in_window(page: Page) -> list[tuple[str, float]]:
    """The column's goals whose titles show above the board's bottom fade, each with where it stands."""
    return page.locator(SCROLLER.format(COLUMN)).evaluate(
        f"""slide => {{
          const top = {CONTENT_TOP}
          const fade = document.querySelector('[data-role="board-bottom-fade"]')
          const seen = Math.min(slide.clientHeight, fade.getBoundingClientRect().top - slide.getBoundingClientRect().top)
          const out = []
          for (const card of slide.querySelectorAll('.goal-card[data-row-key]')) {{
            const y = top(card, slide) - slide.scrollTop
            if (y > 0 && y + 40 < seen) out.push([card.dataset.goalId, y])
          }}
          return out
        }}"""
    )


def _goal_low_in_window(page: Page) -> str:
    """The lowest goal in the window: opened, it doesn't fit."""
    return _goals_in_window(page)[-1][0]


def _goal_high_in_window(page: Page) -> str:
    """A goal well inside the window: opened, it fits."""
    return next(goal for goal, y in _goals_in_window(page) if y > 120)


def _assert_seen_whole(page: Page) -> None:
    """The open goal, its card down to its notes, stands between the window's top and the board's bottom fade."""
    top, bottom, seen = page.locator(SCROLLER.format(COLUMN)).evaluate(
        """slide => {
          const box = slide.getBoundingClientRect()
          const fade = document.querySelector('[data-role="board-bottom-fade"]')
          const card = slide.querySelector('.goal-card--detail-open')
          const list = card.nextElementSibling
          return [card.getBoundingClientRect().top - box.top, list.getBoundingClientRect().bottom - box.top,
                  Math.min(slide.clientHeight, fade.getBoundingClientRect().top - box.top)]
        }"""
    )
    assert top >= 0 and bottom <= seen, (top, bottom, seen)


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
    goal = _goal_low_in_window(page)
    at = _window_top(page, goal)
    _open(page, goal)
    assert _scroll_top(page) > 400, "the opened goal scrolls into view"
    _assert_seen_whole(page)
    page.keyboard.press("Escape")
    _closed(page)
    assert _window_top(page, goal) == pytest.approx(at, abs=1)

    # in the wide column, closed by a press beside the goal
    _scroll_to(page, 250)
    scrolled = _scroll_top(page)
    _open(page, _goal_low_in_window(page))
    assert _scroll_top(page) > scrolled
    _assert_seen_whole(page)
    page.evaluate("() => document.body.dispatchEvent(new PointerEvent('pointerdown', { bubbles: true }))")
    _closed(page)
    assert _scroll_top(page) == pytest.approx(scrolled, abs=1)


@pytest.mark.parametrize("ui_reduced_motion", ["reduce", "no-preference"], indirect=True)
def test_a_goal_that_fits_leaves_the_column_where_it_is(ui_f2: UiSession) -> None:
    page = ui_f2.page
    _seed(ui_f2)
    _scroll_to(page, 400)
    goal = _goal_high_in_window(page)
    at = _window_top(page, goal)

    _open(page, goal)
    assert _window_top(page, goal) == pytest.approx(at, abs=1)
    _assert_seen_whole(page)
    page.keyboard.press("Escape")
    _closed(page)
    assert _window_top(page, goal) == pytest.approx(at, abs=1)


@pytest.mark.parametrize("wide", [False, True], ids=["narrow", "wide"])
def test_a_goal_opened_in_another_column_scrolls_the_old_one_back(ui_f2: UiSession, wide: bool) -> None:
    page = ui_f2.page
    month = _seed(ui_f2)
    if wide:
        expand_column(page, COLUMN)
    _scroll_to(page, 400)
    goal = _goal_low_in_window(page)
    at = _window_top(page, goal)
    _open(page, goal)

    _open(page, month, "month")
    assert _window_top(page, goal) == pytest.approx(at, abs=1)
