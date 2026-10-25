"""The period bars, | ||| |, on a line pinned at the column's top (docs/design/column-bars.md).

At rest the line shows no bars. Under the pointer every column but Life shows three, the middle one dark, in place of
← • →, and a bar at each side that steps the column to the period before and after; the middle one opens the column's
spans mode, the one a dragged task opens on the column's corner (`lib/spans.ts`). When a column scrolls, the line holding them stays pinned at
its top on white, the goals fading out under it over 14 px; it names the kind while the column is at its top and the
period once the big name has gone under it. A column whose period no longer holds today shows the dark middle bar alone,
`|`, which brings the board back to today: that look is `test_column_bars_today.py`'s.

The suite's pinned clock is Saturday 8 Aug 2026 and its window 1458 px, so a column is 208 px wide (182 px of room for
its name). Sizes and colours are the board's own: the ink and the light grey the dots in a column's corner already use
(`ColumnDots.vue`), and the kind line's caption type (15/24), whose cap height, 10.7 px, the bars are drawn to.
"""

from __future__ import annotations

import re

import httpx
import pytest
from playwright.sync_api import Page, expect

from tests.ui.conftest import _DIALOG_RECORDER_SCRIPT, UiSession, activate_column, expand_column

STRIP = '[data-role="column-strip"]'
SPANS = '[data-role="spans-board"]'
SPAN_HEADS = '[data-role="spans-row"] > .pattern-vertical-board__column:not([data-span-edge]) .column-header__sub-label'
PAGED = ("day", "week", "month", "quarter", "year", "decade")
KINDS = {"day": "Day", "week": "Week", "month": "Month", "quarter": "Quarter", "year": "Year", "decade": "Three years"}
# What the mode shows, in the plural, for the three bars' name: "Weeks side by side".
PLURALS = {"day": "Days", "week": "Weeks", "month": "Months", "quarter": "Quarters", "year": "Years", "decade": "Three years"}
# The period each column pages to from the suite's pinned day, Saturday 8 Aug 2026: (this period, the next, the one before).
PERIODS = {
    "day": ("2026-08-08", "2026-08-09", "2026-08-07"),
    "week": ("2026-W32", "2026-W33", "2026-W31"),
    "month": ("2026-08", "2026-09", "2026-07"),
    "quarter": ("2026-Q3", "2026-Q4", "2026-Q2"),
    "year": ("2026", "2027", "2025"),
    "decade": ("2026–2028", "2029–2031", "2023–2025"),
}
# ColumnDots.vue's own colours: the board's ink and its light grey.
INK = "rgb(45, 48, 54)"
LIGHT = "rgb(211, 212, 215)"
# A bar, its gaps and the margin to the column's right edge, in px: the bars are 2 px wide and 11 tall, the cap height of
# the kind line's type, rounded; 3 px apart in the sign, 6 from the bars that come at its sides.
BAR_W, BAR_H, GAP_IN, GAP_OUT, MARGIN = 2, 11, 3, 6, 14
ANCHOR = "2026-08-08"


@pytest.fixture
def ui_reduced_motion(request: pytest.FixtureRequest) -> str:
    """Motion off, as the suite runs; the tests that read the fades ask for it on."""
    return getattr(request, "param", "reduce")


def _col(page: Page, vertical: str):
    return page.locator(f"{STRIP} > [data-vertical='{vertical}']")


def _hover(page: Page, vertical: str) -> None:
    box = _col(page, vertical).bounding_box()
    assert box is not None
    page.mouse.move(box["x"] + box["width"] / 2, 400)


def _rest(page: Page) -> None:
    """The pointer over Life, which has no bars: the other six are at rest."""
    _hover(page, "life")
    page.wait_for_timeout(50)


def _frames(page: Page, n: int = 2) -> None:
    """`n` frames drawn: a scroll's event, and what the page does about it, are answered by then."""
    page.evaluate(
        "n => new Promise((done) => { const tick = () => (--n > 0 ? requestAnimationFrame(tick) : done()); requestAnimationFrame(tick); })", n)


def _seed(session: UiSession, vertical: str, n: int, anchor: str = ANCHOR) -> None:
    """Enough goals for a column to scroll."""
    for i in range(n):
        response = httpx.post(
            f"{session.backend.base_url}/api/goals",
            json={"title": f"SYN bars {vertical} {i:02d}", "vertical": vertical, "anchor_date": anchor},
            headers={"Authorization": f"Bearer {session.backend.token}"},
            timeout=10,
        )
        assert response.status_code == 201, response.text


def _open(session: UiSession, anchor: str | None = None, width: int | None = None) -> Page:
    page = session.page
    if width is not None:
        page.set_viewport_size({"width": width, "height": 779})
    page.goto(f"{session.base_url}/h/{anchor}" if anchor else f"{session.base_url}/")
    page.wait_for_selector(f"{STRIP} > [data-vertical='day'] .column-header")
    page.evaluate("() => document.fonts.ready")
    return page


# What the eye sees of a column's bars: where each stands, in px from the column's own edges, and its colour, counting
# only those that are not faded out (a bar at rest is there for the keyboard and invisible).
_BARS = """(vertical) => {
  const col = document.querySelector(`[data-role="column-strip"] > [data-vertical="${vertical}"]`);
  const box = col.getBoundingClientRect();
  const shown = (el) => { let o = 1; for (let e = el; e && e !== col; e = e.parentElement) o *= parseFloat(getComputedStyle(e).opacity); return o; };
  return [...col.querySelectorAll('.column-bars__bar')].map((el) => {
    const r = el.getBoundingClientRect();
    return { left: r.left - box.left, right: box.right - r.right, top: r.top - box.top, bottom: r.bottom - box.top,
             w: r.width, h: r.height, color: getComputedStyle(el).backgroundColor, shown: shown(el), cap: el.closest('[data-cap]').dataset.cap };
  }).filter((bar) => bar.shown > 0.01).sort((a, b) => a.left - b.left);
}"""


def _bars(page: Page, vertical: str) -> list[dict]:
    return page.evaluate(_BARS, vertical)


def _wait_bars(page: Page, vertical: str, count: int) -> list[dict]:
    """The bars once `count` of them show (a fade in or out takes a moment under motion)."""
    bars = _bars(page, vertical)
    for _ in range(40):
        if len(bars) == count:
            break
        page.wait_for_timeout(25)
        bars = _bars(page, vertical)
    return bars


def _wait_colours(page: Page, vertical: str, want: list[str]) -> list[str]:
    """The bars' colours once they are `want` (a hover is taken a frame or two after the pointer has moved, more when the
    machine is busy)."""
    got = [bar["color"] for bar in _bars(page, vertical)]
    for _ in range(40):
        if got == want:
            break
        page.wait_for_timeout(25)
        got = [bar["color"] for bar in _bars(page, vertical)]
    return got


def _gaps(bars: list[dict]) -> list[float]:
    return [round(b["left"] - a["left"] - BAR_W, 2) for a, b in zip(bars, bars[1:])]


def _step(page: Page, vertical: str, cap: str, key: str) -> None:
    """One click on a side bar of `vertical`, the pointer on its column as for a person, and the column on `key`."""
    _hover(page, vertical)
    column = _col(page, vertical)
    column.locator(f'[data-cap="{cap}"]').click()
    expect(column).to_have_attribute("data-period-key", key)
    expect(column.locator('[data-role="period-slide"]')).to_have_count(1)


def _blur(page: Page) -> None:
    """A click on a bar leaves the focus on it, and a later key makes that a keyboard's focus, which brings the side bars
    into view: the focus goes back to the page, so the bars show as the pointer alone shows them."""
    page.evaluate("() => document.activeElement instanceof HTMLElement && document.activeElement.blur()")


def test_the_bars_show_only_under_the_pointer(ui_f2: UiSession) -> None:
    """At rest no column shows a bar. Under the pointer a column shows | ||| |, the middle one dark, in each of the six
    columns that page, and only in the one the pointer is on; Life has none, and the dot that was "Today" is gone."""
    page = _open(ui_f2)
    _rest(page)
    for vertical in PAGED:
        assert _wait_bars(page, vertical, 0) == [], f"{vertical}: no bars at rest"
    for vertical in PAGED:
        _hover(page, vertical)
        bars = _wait_bars(page, vertical, 5)
        assert [bar["color"] for bar in bars] == [LIGHT, LIGHT, INK, LIGHT, LIGHT], f"{vertical}: {bars}"
        assert [bar["cap"] for bar in bars] == ["period-prev", "period-mode", "period-mode", "period-mode", "period-next"]
        assert all((bar["w"], bar["h"]) == (BAR_W, BAR_H) for bar in bars), f"{vertical}: the bars' size"
        assert len({round(bar["bottom"], 2) for bar in bars}) == 1, f"{vertical}: the bars stand on one line"
        assert _gaps(bars) == [GAP_OUT, GAP_IN, GAP_IN, GAP_OUT], f"{vertical}: 3 px in the sign, 6 to its sides"
        assert bars[-1]["right"] == pytest.approx(MARGIN, abs=0.01), f"{vertical}: {bars[-1]}"
        others = {other: _wait_bars(page, other, 0) for other in PAGED if other != vertical}
        assert not any(others.values()), f"the pointer is on {vertical} only: {others}"
    expect(_col(page, "life").locator('[data-cap="period-nav"]')).to_have_count(0)
    expect(page.locator('[data-cap="period-today"]')).to_have_count(0)
    expect(page.locator(".column-period-controls")).to_have_count(0)
    # they stand on the kind line, on the baseline of its type, 22 px under the column's top, and reach its cap height
    _hover(page, "week")
    week = _wait_bars(page, "week", 5)[0]
    assert week["bottom"] == pytest.approx(22, abs=0.01) and week["top"] == pytest.approx(11, abs=0.01)
    _hover(page, "life")
    assert _wait_bars(page, "week", 0) == [], "leaving, the bars go"


@pytest.mark.parametrize("ui_reduced_motion", ["no-preference"], indirect=True)
def test_the_bars_appear_at_once_and_fade_back_in_200_ms(ui_f2: UiSession) -> None:
    """All three buttons come with the pointer, in the first frame, and go in 200 ms, as one."""
    page = _open(ui_f2)
    _rest(page)
    buttons = f"{STRIP} > [data-vertical='week'] .column-bars__button"
    durations = page.locator(buttons).evaluate_all("els => els.map((el) => getComputedStyle(el).transitionDuration)")
    assert durations == ["0.2s"] * 3, "the fade back takes 200 ms"
    page.evaluate(
        """(buttons) => {
          const els = [...document.querySelectorAll(buttons)]; const t0 = performance.now(); const log = [];
          window.__fade = log;
          const tick = () => { log.push([performance.now() - t0, ...els.map((el) => parseFloat(getComputedStyle(el).opacity))]); if (performance.now() - t0 < 1500) requestAnimationFrame(tick); };
          requestAnimationFrame(tick);
        }""",
        buttons,
    )
    page.wait_for_timeout(150)
    _hover(page, "week")
    page.wait_for_timeout(300)
    _hover(page, "life")
    page.wait_for_timeout(700)
    frames = page.evaluate("window.__fade")
    assert all(max(f[1:]) - min(f[1:]) < 1e-9 for f in frames), "the three are never apart"
    log = [(f[0], f[1]) for f in frames]
    came = next(i for i, (_, o) in enumerate(log) if o > 0.01)
    full = next(i for i, (_, o) in enumerate(log) if o > 0.99)
    assert log[full][0] - log[came][0] <= 90, f"the bars took {log[full][0] - log[came][0]:.0f} ms to come: it appears at once"
    left = next(i for i in range(full, len(log)) if log[i][1] < 0.999)
    gone = next(i for i in range(left, len(log)) if log[i][1] <= 0.001)
    assert any(0.02 < o < 0.98 for _, o in log[left:gone]), "it fades, it does not cut"
    took = log[gone][0] - log[left - 1][0]
    assert 100 <= took <= 320, f"the fade back takes {took:.0f} ms, 200 by design"


def test_under_reduced_motion_the_bars_simply_appear_and_go(ui_f2: UiSession) -> None:
    page = _open(ui_f2)
    _rest(page)
    side = f"{STRIP} > [data-vertical='week'] [data-cap='period-prev']"
    assert float(page.locator(side).evaluate("el => parseFloat(getComputedStyle(el).transitionDuration)")) < 0.001
    _hover(page, "week")
    assert len(_wait_bars(page, "week", 5)) == 5
    _hover(page, "life")
    _frames(page)
    assert _bars(page, "week") == []


def test_a_bar_under_the_pointer_darkens(ui_f2: UiSession) -> None:
    """The one that would be pressed says so: every bar of the button turns ink, the others stay."""
    page = _open(ui_f2)
    _hover(page, "week")
    _wait_bars(page, "week", 5)
    for cap, want in (("period-prev", [INK, LIGHT, INK, LIGHT, LIGHT]), ("period-mode", [LIGHT, INK, INK, INK, LIGHT]),
                      ("period-next", [LIGHT, LIGHT, INK, LIGHT, INK])):
        box = _col(page, "week").locator(f'[data-cap="{cap}"]').bounding_box()
        assert box is not None
        page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
        assert _wait_colours(page, "week", want) == want, cap


def test_a_press_marks_the_bar_and_sliding_away_cancels_it(ui_f2: UiSession) -> None:
    """The look changes at the press, in the mark a keyboard's focus has; the paging waits for the release over the same bar."""
    page = _open(ui_f2)
    _hover(page, "week")
    _wait_bars(page, "week", 5)
    next_bar = _col(page, "week").locator('[data-cap="period-next"]')
    box = next_bar.bounding_box()
    assert box is not None
    mark = next_bar.locator(".column-bars__mark")

    def mark_is(want: str) -> str:
        """The mark's colour once it is `want`."""
        got = mark.evaluate("el => getComputedStyle(el).backgroundColor")
        for _ in range(40):
            if got == want:
                break
            page.wait_for_timeout(25)
            got = mark.evaluate("el => getComputedStyle(el).backgroundColor")
        return got

    none, marked = "rgba(0, 0, 0, 0)", "rgba(45, 48, 54, 0.08)"
    centre = (box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
    page.mouse.move(*centre)
    assert mark_is(none) == none, "under the pointer, not pressed"
    page.mouse.down()
    assert mark_is(marked) == marked, "pressed"
    page.mouse.move(centre[0], 700)
    page.mouse.up()
    assert mark_is(none) == none, "let go"
    _frames(page)
    expect(_col(page, "week")).to_have_attribute("data-period-key", "2026-W32")


@pytest.mark.parametrize("vertical", PAGED)
def test_the_side_bars_page_the_column(ui_f2: UiSession, vertical: str) -> None:
    """The bar at the right steps its column to the next period and the left one to the one before, by the column's own
    unit; one click, one period; and back."""
    page = _open(ui_f2)
    here, after, before = PERIODS[vertical]
    column = _col(page, vertical)
    expect(column).to_have_attribute("data-period-key", here)
    activate_column(page, vertical)  # the pointer is on the column, as it is for a person
    column.locator('[data-cap="period-next"]').click()
    expect(column).to_have_attribute("data-period-key", after)
    expect(column.locator('[data-role="period-slide"]')).to_have_count(1)
    column.locator('[data-cap="period-prev"]').click()
    expect(column).to_have_attribute("data-period-key", here)
    expect(column.locator('[data-role="period-slide"]')).to_have_count(1)
    column.locator('[data-cap="period-prev"]').click()
    expect(column).to_have_attribute("data-period-key", before)


def test_the_single_bar_goes_back_to_today(ui_f2: UiSession) -> None:
    """A click on the single bar brings the column back to today, and the sign turns back into three bars."""
    page = _open(ui_f2)
    _step(page, "week", "period-next", "2026-W33")
    _hover(page, "week")  # the pointer is on the column, not on the side bar it just pressed
    _blur(page)
    assert _wait_colours(page, "week", [LIGHT, INK, LIGHT]) == [LIGHT, INK, LIGHT], "the single bar between its sides"
    _col(page, "week").locator('[data-cap="period-today"]').click()
    _hover(page, "week")
    _blur(page)
    expect(_col(page, "week")).to_have_attribute("data-period-key", "2026-W32")
    _wait_bars(page, "week", 5)
    assert _wait_colours(page, "week", [LIGHT, LIGHT, INK, LIGHT, LIGHT]) == [LIGHT, LIGHT, INK, LIGHT, LIGHT]


def test_a_click_on_the_lines_words_does_what_a_click_on_the_header_does(ui_f2: UiSession) -> None:
    """The line covers the header's kind: a click on its words widens the column, and pages nothing."""
    page = _open(ui_f2)
    box = _col(page, "week").bounding_box()
    assert box is not None
    page.mouse.click(box["x"] + 30, box["y"] + 14)
    expect(_col(page, "week")).to_have_class(re.compile("pattern-vertical-board__column--active"))
    expect(_col(page, "week")).to_have_attribute("data-period-key", "2026-W32")
    page.mouse.click(box["x"] + 30, box["y"] + 14)
    expect(_col(page, "week")).not_to_have_class(re.compile("pattern-vertical-board__column--active"))


@pytest.mark.parametrize("vertical,view,how,floats", [
    ("week", "Weeks", ["This week", "Next week", "In 2 weeks"], "month"),
    ("month", "Months", ["This month", "Next month", "In 2 months"], "quarter"),
])
def test_the_middle_bar_opens_the_spans_mode(ui_f2: UiSession, vertical: str, view: str, how: list[str], floats: str) -> None:
    """The mode a dragged task opens on the column's corner: a week in each column for Week, a month in each for Month,
    this period first, the next one up floating wide over them, and the field naming the view. Esc, with nothing in the
    hand, leaves it and the board is as it was."""
    page = _open(ui_f2)
    here = _col(page, vertical).get_attribute("data-period-key")
    _hover(page, vertical)
    _col(page, vertical).locator('[data-cap="period-mode"]').click()
    expect(page.locator(SPANS)).to_have_count(1, timeout=5000)
    expect(page.locator(SPANS)).to_have_attribute("data-vertical", vertical)
    heads = page.locator(SPAN_HEADS)
    for i, words in enumerate(how):
        expect(heads.nth(i)).to_have_text(words)
    expect(page.locator(f'[data-role="spans-floating"] [data-vertical="{floats}"]')).to_have_count(1)
    expect(page.locator('[data-role="moving-view"]')).to_have_text(view)
    # neither the floating column nor a span pages, so neither has bars that would do nothing, nor the line
    expect(page.locator(f'{SPANS} [data-cap="period-nav"]')).to_have_count(0)
    expect(page.locator(f'{SPANS} [data-role="column-line"]')).to_have_count(0)
    page.keyboard.press("Escape")
    expect(page.locator(SPANS)).to_have_count(0, timeout=5000)
    expect(page.locator(STRIP)).to_have_count(1)
    expect(_col(page, vertical)).to_have_attribute("data-period-key", here or "")
    expect(page.locator('[data-role="moving-stack"]')).to_have_count(0)


# Where each of a column's three buttons and five bars stands, in px from the column's own top left; the Today bar's box is
# the mode's, so both go by "period-mode" here.
_GEOMETRY = """(vertical) => {
  const col = document.querySelector(`[data-role="column-strip"] > [data-vertical="${vertical}"]`);
  const box = col.getBoundingClientRect();
  const rel = (el) => { const r = el.getBoundingClientRect(); return [r.left - box.left, r.top - box.top, r.width, r.height].map((v) => Math.round(v * 100) / 100); };
  return {
    width: box.width,
    boxes: Object.fromEntries([...col.querySelectorAll('.column-bars__button')].map((b) => [b.dataset.cap.replace('period-today', 'period-mode'), rel(b)])),
    bars: [...col.querySelectorAll('.column-bars__bar')].map(rel),
  };
}"""


def test_the_three_boxes_do_not_overlap_and_the_side_boxes_grow_outward(ui_f2: UiSession) -> None:
    """The sign's marks stand as drawn and only the invisible boxes grow, outward from it: the left one to 24 px, the right
    one to the column's own edge, which is as far as that edge allows (the sign stands 22 px from it), and the middle one
    keeps its 18. All three are 28 px tall, the line's height, and none overlaps another."""
    page = _open(ui_f2)
    _hover(page, "week")
    geometry = page.evaluate(_GEOMETRY, "week")
    prev, mode, nxt = (geometry["boxes"][cap] for cap in ("period-prev", "period-mode", "period-next"))
    left = lambda box: box[0]  # noqa: E731
    right = lambda box: box[0] + box[2]  # noqa: E731
    assert right(prev) <= left(mode) + 0.01 and right(mode) <= left(nxt) + 0.01, "none overlaps another"
    assert (prev[2], mode[2]) == (24, 18) and nxt[2] == 19
    assert right(nxt) == pytest.approx(geometry["width"], abs=0.01), "the right box stops at the column's edge, not beyond"
    assert [box[3] for box in (prev, mode, nxt)] == [28, 28, 28] and [box[1] for box in (prev, mode, nxt)] == [0, 0, 0]
    # every mark is inside its own box
    bars = geometry["bars"]
    for box, mark in ((prev, bars[0]), (mode, bars[1]), (mode, bars[2]), (mode, bars[3]), (nxt, bars[4])):
        assert left(box) <= left(mark) and right(mark) <= right(box) + 0.01, (box, mark)


def test_the_left_box_stops_where_the_words_of_the_kind_line_end(ui_f2: UiSession) -> None:
    """A 1320 px window with the Quarter column open leaves the others 160 px, and Week's kind line, "Week · May ’27",
    fills its room: it ends about 3 px from the first bar. The left box grows no further left than that, so it never covers the
    words, though it is smaller than 24 px there; Day's short "Day · ’27" leaves the whole 24 px."""
    page = _open(ui_f2, "2027-05-12", width=1320)
    expand_column(page, "quarter")
    expect(_col(page, "week").locator(".column-header__sub-label")).to_have_text("Week · May ’27", timeout=5000)
    page.wait_for_timeout(600)
    ends = page.evaluate(
        """() => Object.fromEntries(['day', 'week'].map((v) => {
          const col = document.querySelector(`[data-role="column-strip"] > [data-vertical="${v}"]`);
          const word = col.querySelector('[data-role="column-line-kind"]'); const range = document.createRange(); range.selectNodeContents(word);
          return [v, [range.getBoundingClientRect().right - col.getBoundingClientRect().left, col.getBoundingClientRect().width]];
        }))""")
    assert ends["week"][1] == pytest.approx(160, abs=1.5), ends
    week = page.evaluate(_GEOMETRY, "week")["boxes"]
    assert week["period-prev"][0] >= ends["week"][0] - 0.5, f"the left box starts at {week['period-prev'][0]:.1f}, the words end at {ends['week'][0]:.1f}"
    assert 8 <= week["period-prev"][2] < 24
    assert (week["period-mode"][2], week["period-next"][2]) == (18, 19), "the others keep their sizes"
    day = page.evaluate(_GEOMETRY, "day")["boxes"]
    assert day["period-prev"][2] == 24 and day["period-prev"][0] >= ends["day"][0]


# What the pinned line shows, read off the page: its state, both of its words with how much each is seen, where it stands
# under the column's top, and the fade under it.
_LINE = """(vertical) => {
  const col = document.querySelector(`[data-role="column-strip"] > [data-vertical="${vertical}"]`);
  const line = col.querySelector('[data-role="column-line"]');
  const kind = line.querySelector('[data-role="column-line-kind"]');
  const name = line.querySelector('[data-role="column-line-name"]');
  const box = col.getBoundingClientRect(), lineBox = line.getBoundingClientRect();
  const fade = getComputedStyle(line, '::after');
  const slide = col.querySelector('.period-slide:not([data-state="outgoing"])');
  const title = col.querySelector('.t-title');
  return {
    state: line.dataset.state, kind: kind.textContent.trim(), name: name.textContent.trim(),
    kindShown: parseFloat(getComputedStyle(kind).opacity), nameShown: parseFloat(getComputedStyle(name).opacity),
    top: lineBox.top - box.top, left: lineBox.left - box.left, right: box.right - lineBox.right, height: lineBox.height,
    background: getComputedStyle(line).backgroundColor,
    fade: { top: parseFloat(fade.top), height: fade.height, image: fade.backgroundImage, opacity: parseFloat(fade.opacity) },
    scrollTop: slide.scrollTop, titleTop: title.getBoundingClientRect().top - box.top,
  };
}"""


def _line(page: Page, vertical: str) -> dict:
    return page.evaluate(_LINE, vertical)


def _scroll(page: Page, vertical: str, top: int) -> None:
    _col(page, vertical).locator(".period-slide:not([data-state='outgoing'])").evaluate("(el, top) => { el.scrollTop = top }", top)
    _frames(page)


def _wait_line(page: Page, vertical: str, state: str) -> dict:
    """The line once it says `state` and the word of that state is the one seen."""
    expect(_col(page, vertical).locator('[data-role="column-line"]')).to_have_attribute("data-state", state)
    role = "column-line-kind" if state == "kind" else "column-line-name"
    page.wait_for_function(
        """([vertical, role]) => {
          const line = document.querySelector(`[data-role="column-strip"] > [data-vertical="${vertical}"] [data-role="column-line"]`);
          return parseFloat(getComputedStyle(line.querySelector(`[data-role="${role}"]`)).opacity) > 0.99;
        }""",
        arg=[vertical, role],
    )
    return _line(page, vertical)


def test_a_scrolled_column_pins_its_line_and_names_the_period(ui_f2: UiSession) -> None:
    """At its top the line says the kind, "Week", where the header's own kind stands; scrolled until the big name has gone
    under it, the period, "3–9 Aug". It stays at the column's top on white all along, over the goals, and fades them over
    14 px: the line's own 28 px take every click, the 14 under it none."""
    _seed(ui_f2, "week", 40)
    page = _open(ui_f2)
    top = _wait_line(page, "week", "kind")
    assert (top["kind"], top["name"]) == ("Week", "3–9 Aug")
    assert top["top"] == 0 and top["height"] == 28 and top["background"] == "rgb(255, 255, 255)"
    assert top["left"] == 0 and top["right"] == 0, "the line is the column's width"
    assert top["fade"]["top"] == 28 and top["fade"]["height"] == "14px", "the fade is 14 px, right under the line"
    assert "linear-gradient" in top["fade"]["image"] and "255, 255, 255" in top["fade"]["image"]
    assert top["fade"]["opacity"] == 0, "at rest nothing fades: the big name stands right under the line"
    assert top["titleTop"] > 0, "the big name stands below the line"

    _scroll(page, "week", 7)
    near = _wait_line(page, "week", "kind")
    assert near["kind"] == "Week" and near["top"] == 0 and 0.4 < near["fade"]["opacity"] < 0.6, near["fade"]

    _scroll(page, "week", 300)
    named = _wait_line(page, "week", "period")
    assert named["name"] == "3–9 Aug" and named["top"] == 0, "pinned at the top of the column"
    assert named["scrollTop"] == 300 and named["titleTop"] < -200, "the big name has scrolled up and away"
    assert named["fade"]["opacity"] == 1

    # the line's own height takes the click, so a goal that is out of sight under it is not opened; the fade under it lets
    # the pointer through to what shows there
    box = _col(page, "week").bounding_box()
    assert box is not None
    covers = "([x, y]) => document.elementFromPoint(x, y)?.closest('[data-role=\"column-line\"]') !== null"
    assert page.evaluate(covers, [box["x"] + 80, box["y"] + 10]) is True
    assert page.evaluate(covers, [box["x"] + 80, box["y"] + 34]) is False

    _scroll(page, "week", 0)
    _wait_line(page, "week", "kind")


def test_the_line_moves_nothing_at_rest(ui_f2: UiSession) -> None:
    """The line holds the room the slide's padding held, so a column at its top stands as it did before it: the kind row 4 px
    under the column's top, the big name's box 22 under it, and the first goal 88."""
    _seed(ui_f2, "week", 5)
    page = _open(ui_f2)
    column = _col(page, "week")
    expect(column.locator(".goal-card").first).to_be_visible()
    placed = column.evaluate(
        """(col) => {
          const top = col.getBoundingClientRect().top;
          const at = (sel) => col.querySelector(sel).getBoundingClientRect().top - top;
          return { kind: at('.t-caption'), title: at('.t-title'), goal: at('.goal-card') };
        }""")
    assert placed == {"kind": 4, "title": 22, "goal": 88}


def test_a_wheel_over_the_line_scrolls_the_column(ui_f2: UiSession) -> None:
    """The line is part of the slide that scrolls, as the header is: the pointer on it, scrolled or not, wheels the goals,
    and the line stays."""
    _seed(ui_f2, "week", 40)
    page = _open(ui_f2)
    box = _col(page, "week").bounding_box()
    assert box is not None
    page.mouse.move(box["x"] + 80, box["y"] + 10)
    for want in (100, 220):
        page.mouse.wheel(0, 150)
        page.wait_for_function(
            "(want) => document.querySelector('[data-role=\"column-strip\"] > [data-vertical=\"week\"] .period-slide').scrollTop >= want",
            arg=want,
        )
        assert _line(page, "week")["top"] == 0


def test_an_opened_goal_is_scrolled_into_view_below_the_line(ui_f2: UiSession) -> None:
    """A goal opened while its top is behind the line stops 16 px under the edge the goals scroll under (lib/columnFit.ts):
    below the line and its 14 px of fade, not behind them."""
    _seed(ui_f2, "week", 40)
    page = _open(ui_f2)
    column = _col(page, "week")
    ninth = column.locator(".goal-card[data-row-key]").nth(8)
    wanted = ninth.get_attribute("data-goal-id")
    start = ninth.evaluate(
        """(card) => { const slide = card.closest('.period-slide');
          return card.getBoundingClientRect().top - slide.getBoundingClientRect().top + slide.scrollTop; }""")
    _scroll(page, "week", round(start - 20))  # its top stands 20 px under the column's top: its row lies behind the line and its fade
    box = column.bounding_box()
    assert box is not None
    at = (box["x"] + 100, box["y"] + 36)  # on the goal's title, in the fade under the line, which lets the pointer through
    page.mouse.move(*at)
    _frames(page, 4)
    page.mouse.click(*at)
    expect(page.locator(".goal-card--detail-open")).to_have_count(1)
    page.wait_for_function("() => !document.body.dataset.familyMoving")
    _frames(page, 6)
    opened = column.locator(".goal-card--detail-open")
    assert opened.get_attribute("data-goal-id") == wanted, "the click opened the goal it was on"
    # where it stands as laid out: the hovered card's lift is not where the column put it
    top = opened.evaluate(
        """(card) => { const slide = card.closest('.period-slide'); let y = 0;
          for (let e = card; e && e !== slide; e = e.offsetParent) y += e.offsetTop;
          return y - slide.scrollTop; }""")
    assert top >= 42, f"the opened goal stands {top:.0f} px under the column's top: behind the line and its fade"


def test_the_line_takes_the_period_once_the_name_is_under_it_and_gives_it_back_sooner(ui_f2: UiSession) -> None:
    """Between the two states there is no flicker: it takes the period at 32 px, once the big name is under the line, and
    gives it back at 27, a few px sooner on the way up."""
    _seed(ui_f2, "week", 40)
    page = _open(ui_f2)
    down = {}
    for top in (0, 20, 28, 31, 32, 33, 40, 100):
        _scroll(page, "week", top)
        down[top] = _line(page, "week")["state"]
    assert down == {0: "kind", 20: "kind", 28: "kind", 31: "kind", 32: "period", 33: "period", 40: "period", 100: "period"}
    up = {}
    for top in (40, 30, 29, 28, 27, 10):
        _scroll(page, "week", top)
        up[top] = _line(page, "week")["state"]
    assert up == {40: "period", 30: "period", 29: "period", 28: "period", 27: "kind", 10: "kind"}


def test_the_bars_stay_in_reach_on_a_scrolled_column(ui_f2: UiSession) -> None:
    """They are on the line: scrolled far down, the side bar still pages the column, which comes in at its top."""
    _seed(ui_f2, "week", 40)
    page = _open(ui_f2)
    _hover(page, "week")
    _scroll(page, "week", 300)
    _wait_line(page, "week", "period")
    _col(page, "week").locator('[data-cap="period-next"]').click()
    expect(_col(page, "week")).to_have_attribute("data-period-key", "2026-W33")
    expect(_col(page, "week").locator('[data-role="period-slide"]')).to_have_count(1)
    line = _wait_line(page, "week", "kind")
    assert line["kind"] == "Week" and line["scrollTop"] == 0


def test_the_line_says_the_words_the_header_chose(ui_f2: UiSession) -> None:
    """Beside an open column Day's room is 152 px: its big name, Wednesday, takes its short form, "Wed" (the 164.5 px of
    the whole word do not fit); the pinned line says the same word, and the kind stays "Day"."""
    _seed(ui_f2, "day", 40, "2026-08-05")
    page = _open(ui_f2, "2026-08-05", width=1470)
    expand_column(page, "month")
    expect(_col(page, "day").locator(".t-title")).to_have_text("Wed", timeout=5000)
    _scroll(page, "day", 300)
    line = _wait_line(page, "day", "period")
    assert (line["name"], line["kind"]) == ("Wed", "Day")
    _scroll(page, "day", 0)
    # opened, the column has room for the whole word, in the header and on the line
    expand_column(page, "day")
    expect(_col(page, "day").locator(".t-title")).to_have_text("Wednesday", timeout=5000)
    _scroll(page, "day", 300)
    assert _wait_line(page, "day", "period")["name"] == "Wednesday"


def test_the_line_brings_along_what_the_kind_line_carried(ui_f2: UiSession) -> None:
    """A period outside this year says its year on the kind line, and a week whose month moved up there says the month. The
    line names the period without its kind, so it says them after the name: a column scrolled to January 2027 does not
    read as this January, nor a week as no month's."""
    _seed(ui_f2, "month", 40, "2027-01-10")
    page = _open(ui_f2, "2027-01-10")
    top = _wait_line(page, "month", "kind")
    assert (top["kind"], top["name"]) == ("Month · ’27", "January · ’27")
    _scroll(page, "month", 300)
    assert _wait_line(page, "month", "period")["name"] == "January · ’27"

    # beside an open column "25–31 May" does not fit its 152 px: the month moves up to the kind line, "Week · May"
    _seed(ui_f2, "week", 40, "2026-05-27")
    page = _open(ui_f2, "2026-05-27", width=1470)
    expand_column(page, "day")
    expect(_col(page, "week").locator(".t-title")).to_have_text("25–31", timeout=5000)
    assert _wait_line(page, "week", "kind")["kind"] == "Week · May"
    _scroll(page, "week", 300)
    assert _wait_line(page, "week", "period")["name"] == "25–31 · May"


def test_life_has_the_line_and_no_bars(ui_f2: UiSession) -> None:
    """Life does not page, so it has no bars; its goals still scroll under the same line, "Life" and then "All time"."""
    _seed(ui_f2, "life", 40)
    page = _open(ui_f2)
    expect(_col(page, "life").locator('[data-cap="period-nav"]')).to_have_count(0)
    top = _wait_line(page, "life", "kind")
    assert (top["kind"], top["name"], top["top"]) == ("Life", "All time", 0)
    _scroll(page, "life", 300)
    assert _wait_line(page, "life", "period")["name"] == "All time"


def test_the_bars_are_buttons_named_by_what_they_do(ui_f2: UiSession) -> None:
    """"Previous week", "Weeks side by side", "Next week" for Week, and the same by each column's kind, for the keyboard
    and for assistive tech: three buttons, the side bars first and last. A column away from today has "Today" for its
    middle one."""
    page = _open(ui_f2)
    for vertical in PAGED:
        kind = KINDS[vertical]
        want = [f"Previous {kind.lower()}", f"{PLURALS[vertical]} side by side", f"Next {kind.lower()}"]
        column = _col(page, vertical)
        bars = column.locator("[data-cap='period-prev'], [data-cap='period-mode'], [data-cap='period-next']")
        assert bars.evaluate_all("els => els.map((el) => [el.tagName, el.getAttribute('aria-label')])") == [["BUTTON", name] for name in want]
        for name in want:
            expect(column.get_by_role("button", name=name, exact=True)).to_have_count(1)
    _step(page, "week", "period-next", "2026-W33")
    for vertical in ("day", "week"):
        kind = KINDS[vertical]
        column = _col(page, vertical)
        bars = column.locator("[data-cap='period-prev'], [data-cap='period-today'], [data-cap='period-next']")
        assert bars.evaluate_all("els => els.map((el) => [el.tagName, el.getAttribute('aria-label')])") == [
            ["BUTTON", f"Previous {kind.lower()}"], ["BUTTON", "Today"], ["BUTTON", f"Next {kind.lower()}"]]
    month = _col(page, "month")
    expect(month.get_by_role("button", name="Months side by side", exact=True)).to_have_count(1)
    expect(month.get_by_role("button", name="Today", exact=True)).to_have_count(0)


def test_the_keyboard_reaches_every_bar_and_shows_them(ui_f2: UiSession) -> None:
    """Tab goes through a column's three bars, which come first in it, whether the pointer is there or not, and a bar in
    focus brings them all into view; Enter pages, Space brings a paged column back to today and then opens the mode, Esc
    leaves it."""
    page = _open(ui_f2)
    _rest(page)
    assert _bars(page, "week") == []
    week = _col(page, "week")
    week.locator('[data-cap="period-prev"]').focus()
    assert len(_wait_bars(page, "week", 5)) == 5, "a bar in focus shows the whole sign"
    page.keyboard.press("Tab")
    assert page.evaluate("document.activeElement.dataset.cap") == "period-mode"
    mark = week.locator('[data-cap="period-mode"] .column-bars__mark').evaluate("el => getComputedStyle(el).backgroundColor")
    assert mark == "rgba(45, 48, 54, 0.08)", f"focus has a mark: {mark}"
    page.keyboard.press("Tab")
    assert page.evaluate("document.activeElement.dataset.cap") == "period-next"
    page.keyboard.press("Enter")
    expect(week).to_have_attribute("data-period-key", "2026-W33")
    expect(week.locator('[data-role="period-slide"]')).to_have_count(1)
    week.locator('[data-cap="period-today"]').focus()  # the middle bar is the single one now
    page.keyboard.press("Space")
    expect(week).to_have_attribute("data-period-key", "2026-W32")
    expect(week.locator('[data-role="period-slide"]')).to_have_count(1)
    week.locator('[data-cap="period-mode"]').focus()
    page.keyboard.press("Space")
    expect(page.locator(SPANS)).to_have_count(1, timeout=5000)
    page.keyboard.press("Escape")
    expect(page.locator(SPANS)).to_have_count(0, timeout=5000)


def test_on_touch_the_bars_stay_in_view(ui_f2: UiSession) -> None:
    """Nothing hovers on a touch screen, so the bars are all there at rest, and a tap does what the pointer does: the
    side bars page, the single bar goes back to today, the three open the mode."""
    context = ui_f2.context.browser.new_context(
        viewport={"width": 390, "height": 800}, has_touch=True, is_mobile=True, reduced_motion="reduce")
    context.add_init_script(script=_DIALOG_RECORDER_SCRIPT)
    page = context.new_page()
    try:
        page.clock.set_fixed_time("2026-08-08T09:00:00+03:00")
        page.goto(ui_f2.base_url)
        page.wait_for_selector(f"{STRIP} > [data-vertical='day'] .column-header")
        assert page.evaluate("matchMedia('(hover: hover) and (pointer: fine)').matches") is False
        bars = _wait_bars(page, "day", 5)
        assert [bar["color"] for bar in bars] == [LIGHT, LIGHT, INK, LIGHT, LIGHT], bars
        assert bars[-1]["right"] == pytest.approx(MARGIN, abs=0.01)
        heights = {cap: box[3] for cap, box in page.evaluate(_GEOMETRY, "day")["boxes"].items()}
        assert heights == {"period-prev": 44, "period-mode": 44, "period-next": 44}, "a finger's boxes are 44 px tall"
        _col(page, "day").locator('[data-cap="period-next"]').tap()
        expect(_col(page, "day")).to_have_attribute("data-period-key", "2026-08-09")
        assert _wait_colours(page, "day", [LIGHT, INK, LIGHT]) == [LIGHT, INK, LIGHT], "the single bar between its sides"
        _col(page, "day").locator('[data-cap="period-today"]').tap()
        expect(_col(page, "day")).to_have_attribute("data-period-key", "2026-08-08")
        expect(_col(page, "day").locator('[data-role="period-slide"]')).to_have_count(1)
        _col(page, "day").locator('[data-cap="period-mode"]').tap()
        expect(page.locator(SPANS)).to_have_count(1, timeout=5000)
    finally:
        context.close()
