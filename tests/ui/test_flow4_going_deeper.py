"""Flow 4 · going deeper into a goal's steps (KK agreed its full detail on 29 Sep 2026: "The other part you've done is
great"; `web/src/lib/familyView.ts`, `familyMotion.ts`, `cardFamily.ts`).

A goal opens in its own column, which widens. The wide column stands on one edge: the levels stepped through as lines
on top, the open goal as the one card listing the steps its own column holds ("We show inside only those who are on
the same vertical column"), its siblings under it. Two levels in is the deepest. A click on any goal drawn there opens
the chain it is drawn under plus itself (the path rule): a step goes one level in, a sibling sideways, a line on top
back to its level; a goal in another column opens where it is ("It opens where it's are. Your current opened column
collapses and goes back to the regular state"). Esc goes up a level and, at the first level, closes. A dragged goal
held half a second in a goal's middle, where a drop means "into it", opens it as a click does; on its edges it only
reorders.

The light falls off by distance in the family: the open goal and its parent full, one level away light, two faint,
further the farthest tint; everything else turns off under the veil, and nothing changes while nothing is open ("Don't
change the default way we right now light stuff on verticals please!!! No dim when nothing is opened").

What the pointer does to the light while a goal is open is left out on purpose: "the right active colour" is still
KK's call (build round 1, 29 Sep 2026), so no test pins today's answer.

Every scenario runs on the real bundle against a real backend, with prefers-reduced-motion (E2E.md §6): the family
moves in one frame, so each state is read the moment it lands.
"""

from __future__ import annotations

from dataclasses import dataclass

import httpx
from playwright.sync_api import Page, expect

from tests.ui.conftest import EXPANDED_COLUMN_CLASS, UiSession

ANCHOR_ISO = "2026-08-08"  # conftest.py's pinned clock: every goal lands in the column shown as current
GOAL_HOLD_MS = 500  # lib/dragHover.ts GOAL_HOLD_MS, pinned here so a change to it re-justifies this file
DRAG_THRESHOLD_PX = 5  # lib/drag.ts: a desktop drag arms past this many px
GRIP = {"x": 50, "y": 6}  # test_hand_drag.py's inert strip of a row: past the checkbox, above any meta line
FLIP_SETTLE_MS = 300  # test_drag_gap_hover.py: rows that made room have settled


def _create(session: UiSession, title: str, vertical: str, parent_id: str | None = None) -> str:
    """Seeded over the API (test-craft law: httpx and the session's token, never raw SQL inserts)."""
    payload: dict[str, object] = {"title": title, "vertical": vertical, "anchor_date": ANCHOR_ISO}
    if parent_id is not None:
        payload["parent_id"] = parent_id
    resp = httpx.post(
        f"{session.backend.base_url}/api/goals",
        json=payload,
        headers={"Authorization": f"Bearer {session.backend.token}"},
        timeout=10,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


@dataclass
class Family:
    """One family across five columns, two levels deep in Quarter, and one goal outside it:

        value (life) > decade > parent (year) > OPEN (quarter)
          OPEN > step one (quarter) > inner (quarter) > deepest (quarter)
                                    > inner month (month) > week (week)
               > step two (quarter)
               > month step (month)
        parent > sibling (quarter)
        unrelated (quarter), no parent
    """

    value: str
    decade: str
    parent: str
    open: str
    step_one: str
    step_two: str
    month_step: str
    inner: str
    inner_month: str
    deepest: str
    week: str
    sibling: str
    unrelated: str


def _seed(session: UiSession) -> Family:
    value = _create(session, "SYN deep value", "life")
    decade = _create(session, "SYN deep decade", "decade", value)
    parent = _create(session, "SYN deep parent", "year", decade)
    open_ = _create(session, "SYN deep open", "quarter", parent)
    step_one = _create(session, "SYN deep step one", "quarter", open_)
    step_two = _create(session, "SYN deep step two", "quarter", open_)
    month_step = _create(session, "SYN deep month step", "month", open_)
    inner = _create(session, "SYN deep inner", "quarter", step_one)
    inner_month = _create(session, "SYN deep inner month", "month", step_one)
    deepest = _create(session, "SYN deep deepest", "quarter", inner)
    week = _create(session, "SYN deep week", "week", inner_month)
    sibling = _create(session, "SYN deep sibling", "quarter", parent)
    unrelated = _create(session, "SYN deep unrelated", "quarter")
    session.page.reload()
    session.page.wait_for_selector(f'.goal-card[data-goal-id="{open_}"]')
    return Family(value, decade, parent, open_, step_one, step_two, month_step, inner, inner_month, deepest, week,
                  sibling, unrelated)


def _card(vertical: str, goal_id: str) -> str:
    """A goal's card as its own column draws it (the first one, where a goal also stands nested)."""
    return f'.pattern-vertical-board__column[data-vertical="{vertical}"] .goal-card[data-goal-id="{goal_id}"]'


def _title(vertical: str, goal_id: str) -> str:
    return f"{_card(vertical, goal_id)} > .goal-card__row .goal-card__title"


def _open_card(goal_id: str) -> str:
    return f'.goal-card.goal-card--detail-open[data-goal-id="{goal_id}"]'


def _click_open(page: Page, vertical: str, goal_id: str) -> None:
    page.locator(_title(vertical, goal_id)).first.click()
    page.wait_for_selector(_open_card(goal_id))


def _is_wide(page: Page, vertical: str) -> bool:
    column = page.locator(f'.pattern-vertical-board__column[data-vertical="{vertical}"]')
    return EXPANDED_COLUMN_CLASS in (column.get_attribute("class") or "")


def _light(page: Page, vertical: str, goal_id: str) -> str | None:
    return page.locator(_card(vertical, goal_id)).first.get_attribute("data-light")


def _open_path(page: Page) -> list[str]:
    """The levels the wide column shows: its lines on top, outermost first, then the open card."""
    return page.evaluate(
        """() => {
          const column = document.querySelector('.pattern-vertical-board__column--active')
          if (!column) return []
          const lines = [...column.querySelectorAll('.goal-card.goal-card--path-line')].map((el) => el.dataset.goalId)
          const open = column.querySelector('.goal-card.goal-card--detail-open')
          return open ? [...lines, open.dataset.goalId] : lines
        }"""
    )


def test_open_lists_its_own_column_and_lights_the_family_by_distance(ui_f2: UiSession) -> None:
    session = ui_f2
    page = session.page
    fam = _seed(session)

    # At rest nothing changes: no veil, no light of the family's.
    assert page.locator(".pattern-vertical-board--family").count() == 0
    assert page.locator(".goal-card[data-light]").count() == 0

    _click_open(page, "quarter", fam.open)
    assert _is_wide(page, "quarter")
    expect(page.locator(".pattern-vertical-board--family")).to_have_count(1)

    # The card lists the steps its own column holds; a step in another column lights where it sits instead.
    steps = page.locator(f"{_open_card(fam.open)} + .goal-card__children--open")
    expect(steps.locator(f'.goal-card[data-goal-id="{fam.step_one}"]')).to_have_count(1)
    expect(steps.locator(f'.goal-card[data-goal-id="{fam.step_two}"]')).to_have_count(1)
    assert steps.locator(f'.goal-card[data-goal-id="{fam.month_step}"]').count() == 0
    # ...and a step's own steps stay folded until that step is the open one
    assert steps.locator(f'.goal-card[data-goal-id="{fam.inner}"]').count() == 0

    # The light by distance, wherever each goal sits on the board.
    expected = {
        ("quarter", fam.open): "full",
        ("year", fam.parent): "full",  # "The one level up should be same green as opened card"
        ("month", fam.month_step): "light",
        ("decade", fam.decade): "faint",
        ("month", fam.inner_month): "faint",
        ("quarter", fam.sibling): "faint",  # a sibling of the level stepped through
        ("life", fam.value): "far",
        ("week", fam.week): "far",
    }
    for (vertical, goal_id), light in expected.items():
        assert _light(page, vertical, goal_id) == light, f"{vertical} {goal_id}: expected {light}"
    for goal_id in (fam.step_one, fam.step_two):
        assert steps.locator(f'.goal-card[data-goal-id="{goal_id}"]').get_attribute("data-light") == "light"
    # Grey and faded means only "not related".
    assert page.locator(_card("quarter", fam.unrelated)).first.get_attribute("data-light") is None

    # Each step down the light is a weaker tint of the goal's colour, and a goal that's off shows none.
    def tint(vertical: str, goal_id: str) -> float:
        return float(page.locator(_card(vertical, goal_id)).first.evaluate(
            "el => getComputedStyle(el.querySelector(':scope > .goal-card__row'), '::before').opacity"
        ))

    page.wait_for_timeout(400)  # the light's own 150 ms under reduced motion
    full, light = tint("year", fam.parent), tint("month", fam.month_step)
    faint, far = tint("month", fam.inner_month), tint("week", fam.week)
    off = tint("quarter", fam.unrelated)
    assert full == 1 and full > light > faint > far > off == 0, (full, light, faint, far, off)


def test_a_click_opens_the_chain_it_is_drawn_under(ui_f2: UiSession) -> None:
    session = ui_f2
    page = session.page
    fam = _seed(session)
    _click_open(page, "quarter", fam.open)
    assert _open_path(page) == [fam.open]

    # A step in the card goes one level in: the open goal becomes the line on top.
    _click_open(page, "quarter", fam.step_one)
    assert _open_path(page) == [fam.open, fam.step_one]
    step_one_steps = page.locator(f"{_open_card(fam.step_one)} + .goal-card__children--open")
    expect(step_one_steps.locator(f'.goal-card[data-goal-id="{fam.inner}"]')).to_have_count(1)
    assert step_one_steps.locator(f'.goal-card[data-goal-id="{fam.inner_month}"]').count() == 0
    assert _light(page, "quarter", fam.step_one) == "full"
    assert _light(page, "quarter", fam.open) == "full"  # the parent keeps the open goal's light

    # A sibling goes sideways.
    _click_open(page, "quarter", fam.step_two)
    assert _open_path(page) == [fam.open, fam.step_two]

    # The line on top goes back to its level.
    _click_open(page, "quarter", fam.open)
    assert _open_path(page) == [fam.open]
    assert page.locator(".goal-card.goal-card--path-line").count() == 0

    # Two levels in is the deepest: that card's steps don't open.
    _click_open(page, "quarter", fam.step_one)
    _click_open(page, "quarter", fam.inner)
    assert _open_path(page) == [fam.open, fam.step_one, fam.inner]
    deepest = page.locator(f'.goal-card.goal-card--deepest-step[data-goal-id="{fam.deepest}"]')
    expect(deepest).to_have_count(1)
    deepest.locator(":scope > .goal-card__row .goal-card__title").click()
    page.wait_for_timeout(300)
    assert _open_path(page) == [fam.open, fam.step_one, fam.inner]


def test_a_goal_in_another_column_opens_where_it_is(ui_f2: UiSession) -> None:
    session = ui_f2
    page = session.page
    fam = _seed(session)
    _click_open(page, "quarter", fam.open)
    _click_open(page, "quarter", fam.step_one)

    _click_open(page, "month", fam.month_step)
    assert _is_wide(page, "month")
    assert not _is_wide(page, "quarter"), "the column that had the open goal goes back to its regular state"
    assert _open_path(page) == [fam.month_step]
    assert page.locator(".goal-card.goal-card--path-line").count() == 0
    assert _light(page, "month", fam.month_step) == "full"
    assert _light(page, "quarter", fam.open) == "full"  # now the parent of the open goal


def test_escape_goes_up_a_level_then_closes(ui_f2: UiSession) -> None:
    session = ui_f2
    page = session.page
    fam = _seed(session)
    _click_open(page, "quarter", fam.open)
    _click_open(page, "quarter", fam.step_one)
    _click_open(page, "quarter", fam.inner)

    page.keyboard.press("Escape")
    page.wait_for_selector(_open_card(fam.step_one))
    assert _open_path(page) == [fam.open, fam.step_one]
    page.keyboard.press("Escape")
    page.wait_for_selector(_open_card(fam.open))
    assert _open_path(page) == [fam.open]
    page.keyboard.press("Escape")
    page.wait_for_selector(".goal-card.goal-card--detail-open", state="detached")
    expect(page.locator(".pattern-vertical-board--family")).to_have_count(0)
    assert page.locator(".goal-card[data-light]").count() == 0
    assert _is_wide(page, "quarter"), "closing leaves the column wide, where you were"


def test_holding_a_dragged_goal_over_a_step_opens_it(ui_f2: UiSession) -> None:
    session = ui_f2
    page = session.page
    fam = _seed(session)
    _click_open(page, "quarter", fam.open)
    writes_before = sum(1 for r in session.request_log if r["method"] not in ("GET", "HEAD", "OPTIONS"))

    # Pick up the open goal's sibling, drawn under it in the same wide column, and hold it over the open card's first
    # step. The hand stays in that column: a drag resting 0.2 s over another column widens it (D246), which folds this one.
    source = page.locator(_card("quarter", fam.sibling)).first
    box = source.locator(":scope > .goal-card__row").bounding_box()
    assert box is not None
    page.mouse.move(box["x"] + GRIP["x"], box["y"] + GRIP["y"])
    page.mouse.down()
    page.mouse.move(box["x"] + GRIP["x"] + DRAG_THRESHOLD_PX + 15, box["y"] + GRIP["y"], steps=4)
    target = page.locator(f'{_open_card(fam.open)} + .goal-card__children--open [data-goal-id="{fam.step_one}"] > .goal-card__row')

    def aim(fraction: float, steps: int) -> None:
        """The board makes room under the hand (a gap opens where a drop would land), so aim at the step where it is now."""
        page.wait_for_timeout(FLIP_SETTLE_MS)
        tbox = target.bounding_box()
        assert tbox is not None
        page.mouse.move(tbox["x"] + 60, tbox["y"] + tbox["height"] * fraction, steps=steps)

    # On the step's edge, where a drop means "before it", holding only reorders: nothing opens (KK picked it on 29 Sep
    # 2026; a pause there to aim used to open the goal under the hand). The gap opens there, under the hand.
    aim(0.12, 12)
    page.wait_for_timeout(GOAL_HOLD_MS + 300)
    assert page.locator(f'.goal-card[data-goal-id="{fam.step_one}"][data-holding]').count() == 0
    assert _open_path(page) == [fam.open]

    # In its middle, where a drop means "into it", the row fills with light while the hold runs, then the step opens as
    # a click on it would.
    aim(0.5, 4)
    expect(page.locator(f'.goal-card[data-goal-id="{fam.step_one}"][data-holding]')).to_have_count(1)
    page.wait_for_timeout(GOAL_HOLD_MS + 400)
    page.wait_for_selector(_open_card(fam.step_one))
    assert _open_path(page) == [fam.open, fam.step_one]

    # Esc in a drag cancels only the drag: the family stays one level in, and nothing was written.
    page.keyboard.press("Escape")
    page.mouse.up()
    page.wait_for_timeout(700)
    assert _open_path(page) == [fam.open, fam.step_one]
    writes_after = sum(1 for r in session.request_log if r["method"] not in ("GET", "HEAD", "OPTIONS"))
    assert writes_after == writes_before
