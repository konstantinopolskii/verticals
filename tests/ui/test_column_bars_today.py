"""A column away from today shows the single bar, `|`, and its click brings the board back (docs/design/column-bars.md).

The owner, 12 October 2026: "If u scrolled to the other bar, to the central one first becomes the single | instead of |||
meaning it will bring you center. Second click will open weeks mode or verticals mode idk how to call it." A column
whose own period holds today shows `|||`; one whose period does not shows the dark middle bar alone. The first click on
the single bar goes back to today, as the `t` key does, and the sign turns back into `|||`; the next click opens the
mode. The middle bar, the two side bars and their three boxes stand where they did in both looks, and the two light bars
only fade, together, as one movement with the page's own change.

The sign's helpers, the pinned day and the fixture that sets motion are `test_column_bars.py`'s.
"""

from __future__ import annotations

import pytest
from playwright.sync_api import Page, expect

from tests.ui.conftest import UiSession
from tests.ui.test_column_bars import (
    _GEOMETRY, INK, LIGHT, PAGED, PERIODS, SPAN_HEADS, SPANS, STRIP, _blur, _col, _hover, _open, _step, _wait_bars,
    _wait_colours,
    ui_reduced_motion,  # noqa: F401  (the fixture)
)

# Paging the board one step by a column's side bar from the pinned day puts it on this day (adjacentPeriodAnchor), and the
# columns whose own period then no longer holds today: Day is on Sunday 9 Aug, still this ISO week; Week on Monday 10 Aug;
# Month on 1 Sep, still this quarter; Quarter on 1 Oct, still this year; Year on 1 Jan 2027, still these three years.
AWAY = {
    "day": {"day"},
    "week": {"day", "week"},
    "month": {"day", "week", "month"},
    "quarter": {"day", "week", "month", "quarter"},
    "year": {"day", "week", "month", "quarter", "year"},
    "decade": set(PAGED),
}


@pytest.mark.parametrize("stepped", PAGED)
def test_each_column_shows_the_sign_its_own_period_calls_for(ui_f2: UiSession, stepped: str) -> None:
    """Under the pointer a column whose period holds today shows `|||`; one whose period does not shows the dark middle bar
    alone, `|`, each between its two side bars. The board pages as one, so each column judges for itself: a day on, Day
    stands away and Week, whose week still holds today, does not."""
    page = _open(ui_f2)
    _step(page, stepped, "period-next", PERIODS[stepped][1])
    for vertical in PAGED:
        away = vertical in AWAY[stepped]
        _hover(page, vertical)
        want = [LIGHT, INK, LIGHT] if away else [LIGHT, LIGHT, INK, LIGHT, LIGHT]
        assert _wait_colours(page, vertical, want) == want, vertical
    expect(_col(page, "life").locator('[data-cap="period-nav"]')).to_have_count(0)


def test_the_single_bar_brings_the_board_back_to_today(ui_f2: UiSession) -> None:
    """Its click is the old Today button's and the `t` key's: every column on this period again, and the sign three bars
    again."""
    page = _open(ui_f2)
    _step(page, "week", "period-next", "2026-W33")
    week = _col(page, "week")
    expect(week.locator('[data-cap="period-today"]')).to_have_count(1)
    expect(week.locator('[data-cap="period-mode"]')).to_have_count(0)
    week.locator('[data-cap="period-today"]').click()
    for vertical in PAGED:
        expect(_col(page, vertical)).to_have_attribute("data-period-key", PERIODS[vertical][0])
    expect(week.locator('[data-role="period-slide"]')).to_have_count(1)
    assert len(_wait_bars(page, "week", 5)) == 5, "the pointer is still on the column: the sign and its two sides"
    expect(week.locator('[data-cap="period-today"]')).to_have_count(0)
    expect(week.locator('[data-cap="period-mode"]')).to_have_count(1)
    for vertical in PAGED:
        _hover(page, vertical)
        assert len(_wait_bars(page, vertical, 5)) == 5, vertical
    expect(page.locator(SPANS)).to_have_count(0)


def test_a_second_click_opens_the_mode(ui_f2: UiSession) -> None:
    """After the way back to today the same bar opens the mode, from this period: Weeks, this week first."""
    page = _open(ui_f2)
    _step(page, "week", "period-next", "2026-W33")
    week = _col(page, "week")
    week.locator('[data-cap="period-today"]').click()
    expect(week).to_have_attribute("data-period-key", "2026-W32")
    expect(week.locator('[data-role="period-slide"]')).to_have_count(1)
    expect(page.locator(SPANS)).to_have_count(0)
    week.locator('[data-cap="period-mode"]').click()
    expect(page.locator(SPANS)).to_have_count(1, timeout=5000)
    expect(page.locator(SPAN_HEADS).first).to_have_text("This week")
    page.keyboard.press("Escape")
    expect(page.locator(SPANS)).to_have_count(0, timeout=5000)


def test_the_boxes_and_the_bars_stand_in_the_same_places_in_both_looks(ui_f2: UiSession) -> None:
    """Only the sign's two light bars go and come: the middle bar, the two side bars and the three boxes stay where they
    are, so the hand finds everything where it was."""
    page = _open(ui_f2)
    _hover(page, "week")
    assert len(_wait_bars(page, "week", 5)) == 5
    holds = page.evaluate(_GEOMETRY, "week")
    _step(page, "week", "period-next", "2026-W33")
    _hover(page, "week")  # the pointer is on the column, not on the side bar it just pressed
    assert _wait_colours(page, "week", [LIGHT, INK, LIGHT]) == [LIGHT, INK, LIGHT], "the single bar between the two sides"
    assert page.evaluate(_GEOMETRY, "week") == holds


_FADE_SAMPLER = """([week, light, ms]) => {
  const bars = [...document.querySelectorAll(light)]; const col = document.querySelector(week); const t0 = performance.now(); const log = [];
  window.__light = log;
  const tick = () => { log.push([performance.now() - t0, ...bars.map((b) => parseFloat(getComputedStyle(b).opacity)), col.querySelectorAll('[data-role="period-slide"]').length]); if (performance.now() - t0 < ms) requestAnimationFrame(tick); };
  requestAnimationFrame(tick);
}"""
WEEK = f"{STRIP} > [data-vertical='week']"
LIGHT_BARS = f"{WEEK} .column-bars__button--mode .column-bars__bar--outer"


def _fade(page: Page, act, key: str, ends_at: float) -> None:
    """Both light bars, every frame, from just before `act` until a second after the column is on `key`: they are never
    apart, they start within 50 ms of the frame the column's slides swap, and they take 60 to 330 ms to get there (the
    declared 150, on the app's strong ease-out)."""
    page.evaluate(_FADE_SAMPLER, [WEEK, LIGHT_BARS, 1600])
    page.wait_for_timeout(100)
    act()
    expect(_col(page, "week")).to_have_attribute("data-period-key", key)
    page.wait_for_timeout(1000)
    log = page.evaluate("window.__light")
    assert all(abs(a - b) < 1e-9 for _, a, b, _ in log), "the two light bars are never apart"
    swap = next(t for t, _, _, slides in log if slides >= 2)
    moved = next(t for t, a, _, _ in log if 0.001 < a < 0.999)
    assert abs(moved - swap) <= 50, f"the bars start {moved - swap:.0f} ms from the swap"
    resting = next(t for t, a, _, _ in log if t > moved and (a <= 0.001 or a >= 0.999))
    assert 60 <= resting - moved <= 330, f"the fade takes {resting - moved:.0f} ms, 150 by design"
    assert log[-1][1] == ends_at


@pytest.mark.parametrize("ui_reduced_motion", ["no-preference"], indirect=True)
def test_the_two_light_bars_go_and_come_with_the_page_in_150_ms_together(ui_f2: UiSession) -> None:
    """One movement with the page's own change: both fade on opacity alone, in the title's 150 ms, from the frame the
    column's slides swap, and they are never apart. They go when a side bar pages the column away, and come when a click
    on the single bar, the pointer on it, brings the board back."""
    page = _open(ui_f2)
    assert page.locator(LIGHT_BARS).count() == 2
    props = page.locator(LIGHT_BARS).first.evaluate("el => [getComputedStyle(el).transitionProperty, getComputedStyle(el).transitionDuration]")
    assert "opacity" in props[0] and "0.15s" in props[1], props
    _hover(page, "week")
    _fade(page, lambda: page.locator(f"{WEEK} [data-cap='period-next']").click(), "2026-W33", 0)
    _fade(page, lambda: page.locator(f"{WEEK} [data-cap='period-today']").click(), "2026-W32", 1)


@pytest.mark.parametrize("ui_reduced_motion", ["no-preference"], indirect=True)
def test_the_light_bars_come_the_same_way_when_the_keyboard_brings_the_board_back(ui_f2: UiSession) -> None:
    """A keyboard's focus on the single bar has its own look (the bars darken at once, nothing waits); the light bars still
    fade in with the page, in the same 150 ms."""
    page = _open(ui_f2)
    _step(page, "week", "period-next", "2026-W33")
    page.locator(f"{WEEK} [data-cap='period-today']").focus()

    def press() -> None:
        page.keyboard.press("Space")
        assert page.evaluate("() => document.activeElement.matches(':focus-visible')"), "the keyboard's focus look is on during the fade"

    _fade(page, press, "2026-W32", 1)


def test_under_reduced_motion_the_light_bars_simply_go_and_come(ui_f2: UiSession) -> None:
    """The app's own convention: the token is 0 under reduced motion, so the two light bars are gone and back with the
    page, and nothing fades."""
    page = _open(ui_f2)
    light = f"{STRIP} > [data-vertical='week'] .column-bars__button--mode .column-bars__bar--outer"
    assert float(page.locator(light).first.evaluate("el => parseFloat(getComputedStyle(el).transitionDuration)")) < 0.001
    _step(page, "week", "period-next", "2026-W33")
    _hover(page, "week")  # the pointer is on the column, not on the side bar it just pressed
    _blur(page)
    assert _wait_colours(page, "week", [LIGHT, INK, LIGHT]) == [LIGHT, INK, LIGHT]
    _col(page, "week").locator('[data-cap="period-today"]').click()
    _hover(page, "week")
    _blur(page)
    expect(_col(page, "week")).to_have_attribute("data-period-key", "2026-W32")
    _wait_bars(page, "week", 5)
    assert _wait_colours(page, "week", [LIGHT, LIGHT, INK, LIGHT, LIGHT]) == [LIGHT, LIGHT, INK, LIGHT, LIGHT]
