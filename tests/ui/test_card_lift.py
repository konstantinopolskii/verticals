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
