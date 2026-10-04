"""A goal the pointer lifted and clicked opens lifted, stays lifted while the pointer stays on it, and settles when it
leaves (`web/src/lib/cardLift.ts`; KK, 27 Sep 2026: "if you hovered such big unselected card and then clicked on it to
open, scaling shouldn't disappear"; 4 Oct 2026: "keeping it scaled"). The opening is a move only with motion on."""

from __future__ import annotations

import re

import httpx
import pytest
from playwright.sync_api import expect

from tests.ui.conftest import UiSession

ANCHOR_ISO = "2026-08-08"  # conftest.py's pinned clock: the goal lands in the column shown as current
LIFTED = re.compile(r"\bgoal-card--lifted\b")
OPEN = re.compile(r"\bgoal-card--detail-open\b")
TRANSFORM = "el => getComputedStyle(el).transform"


@pytest.fixture
def ui_reduced_motion(request: pytest.FixtureRequest) -> str:
    return getattr(request, "param", "no-preference")


def test_a_clicked_goal_opens_lifted_and_settles_when_the_pointer_leaves(ui_f2: UiSession) -> None:
    session = ui_f2
    resp = httpx.post(
        f"{session.backend.base_url}/api/goals",
        json={"title": "SYN goal the pointer lifts and opens", "vertical": "week", "anchor_date": ANCHOR_ISO},
        headers={"Authorization": f"Bearer {session.backend.token}"},
        timeout=10,
    )
    assert resp.status_code == 201, resp.text
    goal = resp.json()["id"]
    page = session.page
    page.reload()
    card = page.locator(f'.goal-card[data-goal-id="{goal}"]').first
    expect(card).to_be_visible()
    box = card.locator(".goal-card__title").bounding_box()
    assert box is not None
    x, y = box["x"] + min(40, box["width"] / 2), box["y"] + min(8, box["height"] / 2)

    page.mouse.move(x, y, steps=8)
    expect(card).to_have_class(LIFTED)
    page.mouse.down()
    page.mouse.up()
    page.wait_for_timeout(150)  # inside the opening: the lift rides the move, it doesn't wait for it to end
    assert card.evaluate(TRANSFORM) != "none", "the clicked goal lost its lift while it opened"
    expect(card).to_have_class(OPEN)
    page.wait_for_timeout(600)  # the move has landed: the goal it opened is still lifted
    expect(card).to_have_class(LIFTED)
    assert card.evaluate(TRANSFORM) != "none"

    # Opening may slide the goal from under a still pointer (here its column widens, its type grows, and it has nothing
    # to scroll to keep the goal in place): the hand moves on to where the goal now stands, and the lift holds.
    landed = card.locator(".goal-card__title").bounding_box()
    assert landed is not None
    page.mouse.move(landed["x"] + min(60, landed["width"] / 2), landed["y"] + min(8, landed["height"] / 2))
    page.wait_for_timeout(300)
    expect(card).to_have_class(LIFTED)

    page.mouse.move(5, 5, steps=4)  # the hand leaves: the goal settles, and stays open
    expect(card).not_to_have_class(LIFTED)
    expect(card).to_have_class(OPEN)


SETTLE = r"""(id) => {
  const s = window.__settle = { frames: [], on: false };
  const scale = (el) => { const t = getComputedStyle(el).transform; return t === 'none' ? 1 : new DOMMatrix(t).a; };
  function frame() {
    if (!s.on) return;
    const card = [...document.querySelectorAll(`.goal-card[data-goal-id="${id}"]`)].find((c) => !c.closest('[data-role="carried-group"]'));
    const list = card.nextElementSibling && card.nextElementSibling.classList.contains('goal-card__children') ? card.nextElementSibling : null;
    s.frames.push({
      lifted: card.classList.contains('goal-card--lifted'), card: scale(card), list: list ? scale(list) : null,
      wash: parseFloat(getComputedStyle(card.querySelector(':scope > .goal-card__row'), '::before').opacity), z: getComputedStyle(card).zIndex,
    });
    requestAnimationFrame(frame);
  }
  s.start = () => { s.frames = []; s.on = true; requestAnimationFrame(frame); };
  s.stop = () => { s.on = false; return s.frames; };
}"""


def _goal(session: UiSession, title: str) -> str:
    resp = httpx.post(
        f"{session.backend.base_url}/api/goals",
        json={"title": title, "vertical": "week", "anchor_date": ANCHOR_ISO},
        headers={"Authorization": f"Bearer {session.backend.token}"},
        timeout=10,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _settle(page, goal: str) -> list[dict]:
    """The hand leaves the goal it is on; every frame of the goal from then on."""
    page.evaluate(SETTLE, goal)
    page.evaluate("window.__settle.start()")
    page.mouse.move(5, 5, steps=2)
    page.wait_for_timeout(500)
    return page.evaluate("window.__settle.stop()")


def test_an_open_goal_settles_in_one_piece_when_the_pointer_leaves(ui_f2: UiSession) -> None:
    """KK, 4 Oct 2026 ("it goes away buggy way"): the open goal's size used to jump back in one frame while its steps
    eased; now the goal and its steps go back together."""
    goal = _goal(ui_f2, "SYN goal that opens and settles")
    page = ui_f2.page
    page.reload()
    card = page.locator(f'.goal-card[data-goal-id="{goal}"]').first
    title = card.locator(".goal-card__title")
    title.hover()
    expect(card).to_have_class(LIFTED)
    page.mouse.down()
    page.mouse.up()
    expect(card).to_have_class(OPEN)
    page.wait_for_timeout(600)
    title.hover()  # on the goal where it opened
    expect(card).to_have_class(LIFTED)
    frames = _settle(page, goal)
    after = [f for f in frames if not f["lifted"]]
    assert after and after[0]["list"] is not None, "the open goal has its list of steps"
    assert after[0]["card"] > 1.005, f"the goal eases back, it doesn't jump: {after[0]}"
    assert all(abs(f["card"] - f["list"]) < 0.003 for f in after), "the goal and its steps go back together"
    assert after[-1]["card"] == 1 and after[-1]["list"] == 1


def test_a_goal_keeps_its_colour_until_it_settles_and_both_go_together(ui_f2: UiSession) -> None:
    """KK, 4 Oct 2026, from a mockup: the colour used to leave first, 62% gone when the goal began to shrink; it now holds
    while the lift waits and goes back with the size, the goal on its own layer until it lands."""
    goal = _goal(ui_f2, "SYN goal the hand leaves")
    page = ui_f2.page
    page.reload()
    card = page.locator(f'.goal-card[data-goal-id="{goal}"]').first
    card.locator(".goal-card__title").hover()
    expect(card).to_have_class(LIFTED)
    page.wait_for_timeout(250)
    frames = _settle(page, goal)
    lit, top = frames[0]["wash"], frames[0]["card"]
    assert lit > 0.3 and top > 1.01
    waiting = [f for f in frames if f["lifted"]]
    assert all(f["wash"] >= lit - 0.01 for f in waiting), "the colour holds while the lift waits"
    for f in (f for f in frames if not f["lifted"]):
        colour_gone, size_gone = 1 - f["wash"] / lit, 1 - (f["card"] - 1) / (top - 1)
        assert colour_gone <= size_gone + 0.12, f"the colour doesn't run ahead of the size: {f}"
        if f["card"] > 1.001:
            assert f["z"] == "5", f"on its own layer until it lands: {f}"
    assert frames[-1]["wash"] < 0.01 and frames[-1]["card"] == 1
