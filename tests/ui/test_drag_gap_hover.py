"""Drag must not move anything the pointer did not ask for: resting in a gap, a combine hover,
and the landed card's colour and hover look."""

from __future__ import annotations

import time

import httpx
import psycopg
from playwright.sync_api import Page

from tests.ui.conftest import UiSession, activate_column

GRIP = {"x": 50, "y": 6}
FLIP_SETTLE_MS = 300
GOAL_HOLD_MS = 500  # lib/dragHover.ts: a drag held this long in a goal's middle opens the goal (flow 4)

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


def _jitter(page: Page, x: float, y: float, amplitude: float, until: float | None = None) -> list[tuple]:
    seen = []
    offsets = [1, -1, 2, -2, 3, -3, amplitude / 2, -amplitude / 2, amplitude, -amplitude, 0]
    for dy in offsets:
        if until is not None and time.monotonic() > until:
            break
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

    # Held half a second in a goal's middle, a drag opens the goal (flow 4, KK 28 Sep 2026; the middle only, 29 Sep): the
    # hand asked for that. So the board's stillness is checked while the hand aims there, inside that half second, and the
    # hand leaves before the goal opens. Coming into the middle moves nothing: the gap stays and only the goal lights up.
    b_live = _row_box(page, second)
    b_centre = b_live["y"] + b_live["height"] / 2
    page.mouse.move(x, b_centre, steps=4)
    arrived = time.monotonic()
    page.wait_for_timeout(80)
    combining = _signature(_state(page))
    assert combining == (second, third, second, resting[3]), combining
    # Half the hold for looking: the last jiggle and the move out take up to another 150 ms.
    seen = _jitter(page, x, b_centre, amplitude=2, until=arrived + (GOAL_HOLD_MS - 250) / 1000)
    assert len(seen) >= 2, f"too slow to watch the combine hover inside the hold: {seen}"
    assert set(seen) == {combining}, f"the board moved while combining into {second}: {seen}"

    page.mouse.move(x, gap_y, steps=4)
    page.wait_for_timeout(FLIP_SETTLE_MS)
    assert _signature(_state(page)) == resting
    assert page.locator(".goal-card--detail-open").count() == 0, "the hand left before the hold, yet a goal opened"

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


_TRACE = """id => {
  const out = window.__trace = []
  const t0 = performance.now()
  const tick = () => {
    const card = document.querySelector(`[data-goal-id="${id}"]`)
    const row = card?.querySelector(':scope > .goal-card__row')
    if (card && row) {
      out.push({
        wash: card.style.getPropertyValue('--goal-hover-background'),
        visible: getComputedStyle(row).visibility === 'visible' && card.getBoundingClientRect().height > 0,
        background: getComputedStyle(card).backgroundColor,
      })
    }
    if (performance.now() - t0 < 1500) requestAnimationFrame(tick)
  }
  tick()
}"""


def _api(session: UiSession, body: dict) -> str:
    resp = httpx.post(
        f"{session.backend.base_url}/api/goals",
        json=body,
        headers={"Authorization": f"Bearer {session.backend.token}"},
        timeout=10,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def test_dropped_card_keeps_value_colour(ui_f2: UiSession) -> None:
    session = ui_f2
    page = session.page
    value = _api(session, {"title": "Orange value", "vertical": "life", "anchor_date": "2026-01-01", "color": "#f2713a"})
    ids = [
        _api(session, {"title": f"Orange task {n}", "vertical": "month", "anchor_date": "2026-08-08", "parent_id": value})
        for n in (1, 2, 3)
    ]
    page.reload()
    activate_column(page, "month")
    first, second = ids[0], ids[1]

    start = _row_box(page, first)
    x, y = start["x"] + GRIP["x"], start["y"] + GRIP["y"]
    page.mouse.move(x, y)
    page.wait_for_timeout(100)
    card = page.locator(f'[data-goal-id="{first}"]')
    wash = card.evaluate("el => el.style.getPropertyValue('--goal-hover-background')")
    hovered = card.evaluate("el => getComputedStyle(el).backgroundColor")
    assert wash != "#d7d7d7", wash

    page.mouse.down()
    page.mouse.move(x, y + 8, steps=2)
    page.wait_for_timeout(FLIP_SETTLE_MS)
    target = _row_box(page, second)
    page.mouse.move(x, target["y"] + target["height"] * 0.9, steps=6)
    page.wait_for_timeout(FLIP_SETTLE_MS)
    page.evaluate(_TRACE, first)
    page.mouse.up()
    page.wait_for_timeout(1600)
    trace = page.evaluate("() => window.__trace")

    assert {frame["wash"] for frame in trace} == {wash}, "the card lost its value colour after the drop"
    shown = [frame["background"] for frame in trace if frame["visible"]]
    assert shown and set(shown) == {hovered}, f"the landed card did not keep the hover look: {set(shown)}"
    assert page.evaluate(_TOP_LEVEL_IDS, "month").index(first) > page.evaluate(_TOP_LEVEL_IDS, "month").index(second)
