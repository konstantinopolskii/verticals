"""Dragging the first card down and resting in the gap between the next two must not move
anything; a combine hover must not move the gap either."""

from __future__ import annotations

import time

import psycopg
from playwright.sync_api import Page

from tests.ui.conftest import UiSession, activate_column

GRIP = {"x": 50, "y": 6}
FLIP_SETTLE_MS = 300

_TOP_LEVEL_IDS = """vertical => {
  const column = document.querySelector(`.pattern-vertical-board__column[data-vertical="${vertical}"]`)
  const slide = column.querySelector('[data-role="period-slide"]:not([data-state="outgoing"])')
  return [...slide.querySelectorAll('[data-goal-id]')]
    .filter(card => !card.parentElement.closest('.goal-card__children'))
    .map(card => card.dataset.goalId)
}"""

_STATE = """() => {
  const indicator = document.querySelector('[data-role="drop-indicator"]')
  const sibling = (node, step) => {
    for (let el = node?.[step]; el; el = el[step]) {
      if (el.matches('[data-goal-id]') && !el.classList.contains('goal-card--source-gap-closed')) {
        return el.dataset.goalId
      }
    }
    return null
  }
  const lit = document.querySelector('.goal-card__row--combine-target')
  const box = indicator?.getBoundingClientRect()
  return {
    above: sibling(indicator, 'previousElementSibling'),
    below: sibling(indicator, 'nextElementSibling'),
    combine: lit ? lit.parentElement.dataset.goalId : null,
    top: box ? box.top : null,
    height: box ? box.height : null,
  }
}"""


def _row_box(page: Page, goal_id: str) -> dict:
    box = page.locator(f'[data-goal-id="{goal_id}"] > .goal-card__row').bounding_box()
    assert box is not None, f"{goal_id} has no rendered row"
    return box


def _state(page: Page) -> dict:
    return page.evaluate(_STATE)


def _signature(state: dict) -> tuple:
    return (state["above"], state["below"], state["combine"], round(state["top"] or 0))


def _jitter(page: Page, x: float, y: float, amplitude: float) -> list[tuple]:
    seen = []
    offsets = [1, -1, 2, -2, 3, -3, amplitude / 2, -amplitude / 2, amplitude, -amplitude, 0]
    for dy in offsets:
        page.mouse.move(x + (1 if dy > 0 else -1), y + dy, steps=2)
        page.wait_for_timeout(40)
        seen.append(_signature(_state(page)))
    return seen


def test_first_card_rests_in_gap_without_reflow(ui_f2: UiSession) -> None:
    session = ui_f2
    page = session.page
    activate_column(page, "week")
    ids = page.evaluate(_TOP_LEVEL_IDS, "week")
    assert len(ids) >= 3, ids
    first, second, third = ids[:3]

    start = _row_box(page, first)
    b_box = _row_box(page, second)
    x = start["x"] + GRIP["x"]
    y = start["y"] + GRIP["y"]
    before_pickup = [_row_box(page, goal_id)["y"] for goal_id in (second, third)]
    page.mouse.move(x, y)
    page.mouse.down()
    y += 6
    page.mouse.move(x, y)
    page.wait_for_timeout(FLIP_SETTLE_MS)
    after_pickup = [_row_box(page, goal_id)["y"] for goal_id in (second, third)]
    assert all(abs(a - b) < 0.5 for a, b in zip(before_pickup, after_pickup)), (
        f"cards moved on pickup: {before_pickup} -> {after_pickup}"
    )

    deadline = time.monotonic() + 5
    limit = b_box["y"] + b_box["height"] + 40
    while time.monotonic() < deadline and y < limit:
        y += 2
        page.mouse.move(x, y)
        state = _state(page)
        if state["above"] == second and state["below"] == third:
            break
    state = _state(page)
    assert (state["above"], state["below"]) == (second, third), (
        f"the gap never opened between {second} and {third}: {state}"
    )

    page.wait_for_timeout(FLIP_SETTLE_MS)
    state = _state(page)
    gap_y = state["top"] + state["height"] / 2
    page.mouse.move(x, gap_y, steps=4)
    page.wait_for_timeout(FLIP_SETTLE_MS)
    resting = _signature(_state(page))
    assert resting[:3] == (second, third, None), resting
    seen = _jitter(page, x, gap_y, amplitude=max(4.0, state["height"] / 2 - 4))
    assert set(seen) == {resting}, f"the board moved while the pointer rested in the gap: {seen}"

    b_live = _row_box(page, second)
    b_centre = b_live["y"] + b_live["height"] / 2
    page.mouse.move(x, b_centre, steps=4)
    page.wait_for_timeout(FLIP_SETTLE_MS)
    combining = _signature(_state(page))
    assert combining == (second, third, second, resting[3]), combining
    seen = _jitter(page, x, b_centre, amplitude=2)
    assert set(seen) == {combining}, f"the board moved while combining into {second}: {seen}"

    page.mouse.move(x, gap_y, steps=4)
    page.wait_for_timeout(FLIP_SETTLE_MS)
    assert _signature(_state(page)) == resting

    page.mouse.up()
    deadline = time.monotonic() + 5
    order: list[str] = []
    while time.monotonic() < deadline:
        order = page.evaluate(_TOP_LEVEL_IDS, "week")[:3]
        if order == [second, first, third]:
            break
        page.wait_for_timeout(50)
    assert order == [second, first, third], order

    with psycopg.connect(session.backend.dsn, autocommit=True) as conn:
        deadline = time.monotonic() + 5
        positions: dict[str, int] = {}
        while time.monotonic() < deadline:
            rows = conn.execute(
                "SELECT id, position FROM goals WHERE id = ANY(%s)", ([first, second, third],)
            ).fetchall()
            positions = {goal_id: position for goal_id, position in rows}
            if positions[second] < positions[first] < positions[third]:
                break
            time.sleep(0.05)
        assert positions[second] < positions[first] < positions[third], positions
