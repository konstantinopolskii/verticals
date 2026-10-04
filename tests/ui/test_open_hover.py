"""KK's 4 Oct hover regressions: visible progress after a busy frame, one leave fade, and one open-plan colour.

Chrome checks the real bundle's state. The system-WebKit screen recording remains the performance check;
computed styles alone cannot prove that its compositor presented those frames.
"""
from __future__ import annotations

import pytest
from playwright.sync_api import expect

from tests.ui.conftest import UiSession
from tests.ui.test_carried_motion import _board as carried_board
from tests.ui.test_flow4_going_deeper import _card, _click_open, _seed, _title
from tests.ui.test_light_swap import SAMPLER


@pytest.fixture
def ui_reduced_motion(request: pytest.FixtureRequest) -> str:
    return getattr(request, "param", "no-preference")


def _away(page):
    return page.locator('.pattern-vertical-board__column[data-vertical="week"] .pattern-vertical-board__header').first


def _trace(page, act, wait=800):
    page.evaluate("window.__swap.start()")
    act()
    page.wait_for_timeout(wait)
    return page.evaluate("window.__swap.stop()")


def _progress(values):
    """A fade has several middle frames, no large first step, and never turns back."""
    start, end = values[0], values[-1]
    assert abs(end - start) > 0.2, values
    p = [(v - start) / (end - start) for v in values]
    changed = [v for v in p if v > 0.05]
    assert changed[0] <= 0.5, p
    assert sum(0.05 < v < 0.95 for v in p) >= 3, p
    assert all(-0.04 <= b - a <= 0.5 for a, b in zip(p, p[1:])), p


@pytest.mark.parametrize("ui_reduced_motion,off_opacity", [("no-preference", .32), ("reduce", .32),
                                                        ("no-preference", 0)], indirect=["ui_reduced_motion"])
def test_a_busy_swap_keeps_its_first_frame_and_finishes_its_fade(ui_f2: UiSession, off_opacity: float) -> None:
    fam = _seed(ui_f2)
    page = ui_f2.page
    _click_open(page, "quarter", fam.open)
    _away(page).hover()
    page.wait_for_timeout(900)
    page.evaluate("v => document.documentElement.style.setProperty('--kkov-off-opacity', String(v))", off_opacity)
    family = _card("year", fam.parent)
    page.evaluate(SAMPLER, {"family": family, "open": _card("quarter", fam.open),
                            "other": _card("quarter", fam.unrelated)})
    # Emulate the expensive first render seen in WebKit. A wall-clock cleanup must not remove the fade before
    # that render reaches the screen. Only the first swap is delayed; no app state or animation is replaced.
    page.evaluate("""sel => {
      const card = document.querySelector(sel);
      const observer = new MutationObserver(() => {
        if (card.hasAttribute('data-light')) return;
        observer.disconnect();
        getComputedStyle(card.querySelector('.goal-card__row')).opacity;
        const until = performance.now() + 180;
        while (performance.now() < until) {}
      });
      observer.observe(card, { attributes: true, attributeFilter: ['data-light'] });
    }""", family)
    frames = _trace(page, lambda: page.locator(_title("quarter", fam.unrelated)).first.hover())
    # The parent goes from visible to the veil. Its underlying opacity becomes 1 again under the veil,
    # so use its effective opacity there (the veil's .32), not that hidden reset.
    _progress([f["family"]["o"] if f["family"]["z"] == "2" else off_opacity for f in frames])
    _progress([f["open"]["o"] for f in frames])
    assert all(abs(f["open"]["o"] - f["open"]["list"]) < .03 for f in frames), "row and notes fade as one piece"
    hovered = frames[next(i for i, f in enumerate(frames) if f["other"]["lifted"]):]
    assert all(f["other"]["o"] == 1 and f["other"]["wash"] == 1 for f in hovered)

    frames = _trace(page, lambda: _away(page).hover(), 1000)
    _progress([f["family"]["o"] if f["family"]["z"] == "2" else off_opacity for f in frames])
    _progress([f["open"]["o"] for f in frames])
    assert all(abs(f["open"]["o"] - f["open"]["list"]) < .03 for f in frames)
    expect(page.locator('[data-light-move]')).to_have_count(0)


@pytest.mark.parametrize("ui_reduced_motion", ["no-preference", "reduce"], indirect=True)
@pytest.mark.parametrize("destination", ["away", "unrelated"])
def test_leaving_a_green_card_keeps_full_colour_until_the_lift_settles(ui_f2: UiSession, destination: str) -> None:
    fam = _seed(ui_f2)
    page = ui_f2.page
    _click_open(page, "quarter", fam.open)
    page.wait_for_timeout(900)
    page.locator(_title("quarter", fam.sibling)).first.hover()
    page.wait_for_timeout(400)
    page.evaluate(SAMPLER, {"left": _card("quarter", fam.sibling)})
    target = _away(page) if destination == "away" else page.locator(_title("quarter", fam.unrelated)).first
    frames = _trace(page, lambda: target.hover())
    held = [f["left"] for f in frames if f["left"]["lifted"]]
    assert len(held) >= 2, frames
    assert all(f["wash"] == 1 for f in held), held
    # A swap can start before this leave fade ends. Their combined colour must keep moving from the shade on screen.
    _progress([f["left"]["o"] * f["left"]["wash"] for f in frames])


def test_a_grey_card_has_one_fade_when_the_light_returns(ui_f2: UiSession) -> None:
    fam = _seed(ui_f2)
    page = ui_f2.page
    _click_open(page, "quarter", fam.open)
    page.wait_for_timeout(900)
    page.locator(_title("quarter", fam.unrelated)).first.hover()
    page.wait_for_timeout(600)
    page.evaluate(SAMPLER, {"left": _card("quarter", fam.unrelated)})
    frames = _trace(page, lambda: _away(page).hover(), 1000)
    lit = [f["left"] for f in frames if f["left"]["light"] is not None]
    assert all(f["wash"] == 1 for f in lit), "the grace must not introduce an intermediate 70% shade"
    _progress([f["left"]["o"] * f["left"]["wash"] for f in frames])


def test_reversing_a_swap_continues_from_the_visible_shade(ui_f2: UiSession) -> None:
    fam = _seed(ui_f2)
    page = ui_f2.page
    _click_open(page, "quarter", fam.open)
    _away(page).hover()
    page.wait_for_timeout(900)
    family = _card("year", fam.parent)
    green = page.locator(_title("quarter", fam.sibling)).first.bounding_box()
    page.evaluate(SAMPLER, {"family": family})
    page.evaluate("window.__swap.start()")
    page.locator(_title("quarter", fam.unrelated)).first.hover()
    page.wait_for_function("""sel => {
      const el = document.querySelector(sel);
      const o = Number(getComputedStyle(el.querySelector('.goal-card__row')).opacity);
      return el.dataset.lightMove === 'out' && o < .95 && o > .4;
    }""", arg=family)
    page.mouse.move(green["x"] + 20, green["y"] + 8)
    page.wait_for_timeout(800)
    frames = page.evaluate("window.__swap.stop()")
    at = next(i for i, f in enumerate(frames) if f["family"]["move"] == "in")
    assert frames[at - 1]["family"]["o"] > .4, "the return interrupts a crossing still in flight"
    before, after = frames[at - 1]["family"], frames[at]["family"]
    # The outgoing fade can advance between the last sampled frame and the pointer event. Allow that elapsed
    # share of its 150 ms crossing, but not a reset to the veil's .32 when the direction changes.
    elapsed = after["time"] - before["time"]
    assert after["o"] >= before["o"] - .68 * elapsed / 150 - .02, frames[at - 2:at + 3]
    assert all(b["family"]["o"] >= a["family"]["o"] - .04 for a, b in zip(frames[at:], frames[at + 1:]))
    assert frames[-1]["family"]["o"] == 1
    expect(page.locator('[data-light-move]')).to_have_count(0)


def test_an_open_carried_plan_keeps_one_colour_under_the_pointer(ui_f2: UiSession) -> None:
    _, plan = carried_board(ui_f2)
    page = ui_f2.page
    card = page.locator(_card("year", plan)).first
    card.locator('.goal-card__title').hover()
    card.locator('.goal-card__title').click()
    page.wait_for_timeout(1100)
    for target in [card.locator('.goal-card__title'), _away(page), card.locator('.goal-card__title')]:
        target.hover()
        page.wait_for_timeout(400)
        parts = card.evaluate("""card => {
          const row = card.querySelector(':scope > .goal-card__row'), list = card.nextElementSibling;
          return [row, list].map(el => ({ wash: Number(getComputedStyle(el, '::before').opacity),
            opacity: Number(getComputedStyle(el).opacity), colour: getComputedStyle(el, '::before').backgroundColor }));
        }""")
        assert parts[0]["wash"] == parts[1]["wash"] == 1, parts
        assert parts[0]["opacity"] == parts[1]["opacity"] == 1, parts
