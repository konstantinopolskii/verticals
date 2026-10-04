"""While a goal is open, resting on a goal outside its family moves the light to that goal's family, and leaving moves it
back (`web/src/lib/familyView.ts`). The light used to jump across the column's veil in one frame, both ways (KK, 4 Oct
2026, a recording: the board flipped from one family to the other and back on every hover); now each goal it takes or
leaves passes through the veil's own look in the swap's 150 ms (`lib/cardFamily.ts`, goalCard.css). The goal under the
hand answers first, on its own: it lifts in its full colour at once, before the light reaches its family, and the swap
leaves it alone (KK, the same evening, a recording: "immediately light the one that is hovered right now and decouple
the animation of the others"; it used to wait for the swap and blink through the veil's look). Traced frame by frame in
the page, motion on."""

from __future__ import annotations

import pytest

from tests.ui.conftest import UiSession
from tests.ui.test_flow4_going_deeper import _click_open, _seed, _title

SAMPLER = r"""(ids) => {
  const s = window.__swap = { frames: [], on: false };
  const look = (sel) => {
    const card = document.querySelector(sel);
    const row = card.querySelector(':scope > .goal-card__row');
    const cs = getComputedStyle(row);
    return { time: Number(document.timeline.currentTime), light: card.dataset.light ?? null, move: card.dataset.lightMove ?? null,
      o: Math.round(parseFloat(cs.opacity) * 100) / 100, z: cs.zIndex,
      wash: Math.round(parseFloat(getComputedStyle(row, '::before').opacity) * 100) / 100,
      list: card.classList.contains('goal-card--detail-open')
        ? Number(getComputedStyle(card.nextElementSibling).opacity) : null,
      lifted: card.classList.contains('goal-card--lifted') };
  };
  function frame() {
    if (!s.on) return;
    s.frames.push(Object.fromEntries(Object.entries(ids).map(([k, sel]) => [k, look(sel)])));
    requestAnimationFrame(frame);
  }
  s.start = () => { s.frames = []; s.on = true; requestAnimationFrame(frame); };
  s.stop = () => { s.on = false; return s.frames; };
}"""


@pytest.fixture
def ui_reduced_motion(request: pytest.FixtureRequest) -> str:
    return getattr(request, "param", "no-preference")


def _card(vertical: str, goal_id: str) -> str:
    return f'.pattern-vertical-board__column[data-vertical="{vertical}"] .goal-card[data-goal-id="{goal_id}"]'


def test_the_light_passes_through_the_veil_when_it_swaps_under_the_pointer(ui_f2: UiSession) -> None:
    fam = _seed(ui_f2)
    page = ui_f2.page
    _click_open(page, "quarter", fam.open)
    header = page.locator('.pattern-vertical-board__column[data-vertical="week"] .pattern-vertical-board__header').first
    header.hover()  # on a column's name: no goal under the pointer
    page.wait_for_timeout(900)  # the opening has landed
    page.evaluate(SAMPLER, {"family": _card("year", fam.parent), "other": _card("quarter", fam.unrelated)})

    def trace(act, wait_ms: int) -> list[dict]:
        page.evaluate("window.__swap.start()")
        act()
        page.wait_for_timeout(wait_ms)
        return page.evaluate("window.__swap.stop()")

    frames = trace(lambda: page.locator(_title("quarter", fam.unrelated)).first.hover(), 900)
    lifted = next(i for i, f in enumerate(frames) if f["other"]["lifted"])
    taken = next(i for i, f in enumerate(frames) if f["other"]["light"] is not None)
    swap = frames[taken:]
    # the goal under the hand lights at once, lifted in its full colour, before the light reaches its family
    assert lifted < taken, (lifted, taken)
    hovered = frames[lifted:]
    assert all(f["other"]["o"] == 1 and f["other"]["wash"] >= 0.99 for f in hovered), [
        (f["other"]["o"], f["other"]["wash"]) for f in hovered[:12]]
    # the goal it leaves stays over the veil while it turns to the veil's look, then goes under it
    assert swap[0]["family"]["light"] is None and swap[0]["family"]["z"] == "2" and swap[0]["family"]["o"] > 0.6, swap[0]
    assert any(f["family"]["z"] == "2" and f["family"]["o"] < 0.45 for f in swap), [f["family"] for f in swap[:12]]
    assert swap[-1]["family"]["z"] == "auto" and swap[-1]["family"]["o"] == 1

    frames = trace(lambda: header.hover(), 1200)  # the hand leaves: after the light's grace it comes back the same way
    back = frames[next(i for i, f in enumerate(frames) if f["family"]["light"] is not None):]
    assert back[0]["family"]["o"] < 0.6, back[0]
    assert any(0.6 < f["family"]["o"] < 0.99 for f in back), [f["family"]["o"] for f in back[:10]]
    assert back[-1]["family"]["o"] == 1
    assert any(f["other"]["z"] == "2" and f["other"]["o"] < 0.45 for f in back), [f["other"] for f in back[:12]]
    assert back[-1]["other"]["z"] == "auto" and back[-1]["other"]["o"] == 1
