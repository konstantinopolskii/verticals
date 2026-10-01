"""Moving a goal (docs/design-handoff scope 5): a column's dots open its periods as spans with the goal's own column
floating wide; the screen's edges move them on; a drop lands as today's drop and the board comes back; let go over the
field, the goal waits there beside "Weeks" and Backspace picks things up. F2, the browser clock pinned to 2026-08-08."""

from __future__ import annotations

import re

import psycopg
from playwright.sync_api import Page, expect

from tests.ui.conftest import UiSession
from tests.ui.test_agent_conversation import ui_agent  # noqa: F401  (the fixture)
from tests.ui.views import FIELD

SPANS = '[data-role="spans-board"]'
SPAN = '[data-role="spans-row"] > .pattern-vertical-board__column'
MONTH_GOAL = "SYNSCH01"


def _glide(page: Page, a: tuple[float, float], b: tuple[float, float], steps: int = 12) -> None:
    for i in range(1, steps + 1):
        page.mouse.move(a[0] + (b[0] - a[0]) * i / steps, a[1] + (b[1] - a[1]) * i / steps)
        page.wait_for_timeout(16)


def _centre(page: Page, selector: str, dy: float = 0) -> tuple[float, float]:
    box = page.locator(selector).first.bounding_box()
    assert box is not None, selector
    return box["x"] + box["width"] / 2, box["y"] + box["height"] / 2 + dy


def _grab(page: Page, goal_id: str) -> tuple[float, float]:
    box = page.locator(f'[data-goal-id="{goal_id}"] > .goal-card__row').first.bounding_box()
    assert box is not None
    at = (box["x"] + 30, box["y"] + box["height"] / 2)
    page.mouse.move(*at)
    page.mouse.down()
    _glide(page, at, (at[0] + 12, at[1] + 8), 4)
    page.wait_for_timeout(500)
    return at[0] + 12, at[1] + 8


def _open_weeks(page: Page, goal_id: str = MONTH_GOAL) -> tuple[float, float]:
    at = _grab(page, goal_id)
    dots = _centre(page, '[data-role="column-dots"][data-dots-vertical="week"]')
    _glide(page, at, dots)
    expect(page.locator(SPANS)).to_have_count(1, timeout=5000)
    expect(page.locator(SPAN)).not_to_have_count(0)
    page.wait_for_timeout(700)
    return dots


def test_a_drag_shows_dots_in_every_column_but_life(ui_f2: UiSession) -> None:
    """S5.P2.026, .028: three dots in each corner; passing over them without resting opens nothing."""
    page = ui_f2.page
    page.wait_for_selector(f'[data-goal-id="{MONTH_GOAL}"]')
    at = _grab(page, MONTH_GOAL)
    dots = page.locator('[data-role="column-dots"]')
    expect(dots).to_have_count(6)
    assert page.locator('[data-vertical="life"] [data-role="column-dots"]').count() == 0
    expect(dots.first.locator(".column-dots__dot")).to_have_count(3)
    week = _centre(page, '[data-role="column-dots"][data-dots-vertical="week"]')
    _glide(page, at, week, 3)
    _glide(page, week, (week[0], week[1] + 200), 3)
    page.wait_for_timeout(400)
    assert page.locator(SPANS).count() == 0
    page.keyboard.press("Escape")
    page.mouse.up()


def test_resting_on_weeks_dots_opens_the_weeks_with_month_floating(ui_f2: UiSession) -> None:
    """S5.P1.044, .045, S5.P2.027: this week first, each header how far away with its start big and its end small and
    light; the goal's own Month floats wide at the right; the field is a pill with "Weeks" above it (S5.P3.036)."""
    page = ui_f2.page
    page.wait_for_selector(f'[data-goal-id="{MONTH_GOAL}"]')
    _open_weeks(page)
    heads = page.locator(f"{SPAN} .column-header__sub-label")
    expect(heads.first).to_have_text("This week")
    expect(heads.nth(1)).to_have_text("Next week")
    expect(heads.nth(2)).to_have_text("In 2 weeks")
    title = page.locator(f"{SPAN} .t-title").first
    expect(title).to_contain_text("3 Aug")
    assert title.evaluate("el => getComputedStyle(el).fontSize") == "31px"
    end = page.locator(f'{SPAN} [data-role="span-end"]').first
    expect(end).to_have_text("9 Aug")
    assert end.evaluate("el => getComputedStyle(el).color") == "rgb(179, 180, 183)"
    floating = page.locator('[data-role="spans-floating"]')
    expect(floating.locator('[data-vertical="month"]')).to_have_count(1)
    box = floating.bounding_box()
    assert box is not None and abs(box["width"] - 400) <= 1 and abs(box["x"] + box["width"] - 1456) <= 1
    expect(page.locator('[data-role="moving-view"]')).to_have_text("Weeks")
    shape = page.locator(".circle-field__shape").bounding_box()
    assert shape is not None and round(shape["width"]) == 120
    page.keyboard.press("Escape")
    page.mouse.up()
    expect(page.locator(SPANS)).to_have_count(0, timeout=5000)


def test_the_right_edge_moves_the_weeks_on(ui_f2: UiSession) -> None:
    """S5.P1.046, .052: at the side where Month floats it first goes to the other side, then the weeks move on."""
    page = ui_f2.page
    page.wait_for_selector(f'[data-goal-id="{MONTH_GOAL}"]')
    dots = _open_weeks(page)
    _glide(page, dots, (1454, 400))
    expect(page.locator(SPANS)).to_have_class(re.compile("spans-board--float-left"), timeout=3000)
    expect(page.locator(f"{SPAN} .column-header__sub-label").first).to_have_text(re.compile("Next week|In \\d weeks"), timeout=3000)
    page.keyboard.press("Escape")
    page.mouse.up()


def test_a_drop_in_a_week_schedules_it_there_and_the_board_comes_back(ui_f2: UiSession) -> None:
    """S5.P6.003, .005: let go in a period on no goal: the goal takes that period, as a drop does; then the board."""
    page = ui_f2.page
    page.wait_for_selector(f'[data-goal-id="{MONTH_GOAL}"]')
    dots = _open_weeks(page)
    target = _centre(page, f"{SPAN} >> nth=2", dy=120)
    _glide(page, dots, target)
    page.wait_for_timeout(300)
    page.mouse.up()
    expect(page.locator(SPANS)).to_have_count(0, timeout=5000)
    expect(page.locator('[data-role="column-strip"]')).to_have_count(1)
    with psycopg.connect(ui_f2.backend.dsn, autocommit=True) as conn:
        vertical, period = conn.execute("SELECT vertical, period_key FROM goals WHERE id = %s", (MONTH_GOAL,)).fetchone()
    assert (vertical, period) == ("week", "2026-W34")


def test_letting_go_on_a_goal_makes_it_that_goals_step(ui_f2: UiSession) -> None:
    """S5.P6.002, .016: on a goal you haven't opened, the held goal becomes its last step."""
    page = ui_f2.page
    page.wait_for_selector(f'[data-goal-id="{MONTH_GOAL}"]')
    dots = _open_weeks(page)
    row = f'{SPAN} [data-goal-id="SYNORD02"] > .goal-card__row'
    near = _centre(page, row)
    _glide(page, dots, near)
    page.wait_for_timeout(300)
    # The slot opened on the way in moves the row: meet it where it is now, in its middle.
    _glide(page, near, _centre(page, row), 4)
    page.wait_for_timeout(300)
    expect(page.locator(f'{SPAN} [data-goal-id="SYNORD02"] > [data-dnd-combine-target]')).to_have_count(1)
    page.mouse.up()
    expect(page.locator(SPANS)).to_have_count(0, timeout=5000)
    with psycopg.connect(ui_f2.backend.dsn, autocommit=True) as conn:
        (parent,) = conn.execute("SELECT parent_id FROM goals WHERE id = %s", (MONTH_GOAL,)).fetchone()
    assert parent == "SYNORD02"


def test_let_go_over_the_field_the_goal_waits_and_backspace_picks(ui_f2: UiSession) -> None:
    """S5.P3.037, S5.P4.020, .021: the goal waits beside "Weeks", out of its group; one Backspace lifts it, a second
    puts it back and lifts "Weeks", a third takes "Weeks" off and the board is as it was."""
    page = ui_f2.page
    page.wait_for_selector(f'[data-goal-id="{MONTH_GOAL}"]')
    dots = _open_weeks(page)
    _glide(page, dots, _centre(page, ".circle-field__shape"))
    page.wait_for_timeout(200)
    page.mouse.up()
    waiting = page.locator('[data-role="moving-goal"]')
    expect(waiting).to_have_count(1)
    expect(waiting).to_contain_text("Fix the bicycles rack")
    expect(page.locator(f'[data-role="spans-floating"] [data-goal-id="{MONTH_GOAL}"]:not([data-parked])')).to_be_hidden()
    shape = page.locator(".circle-field__shape").bounding_box()
    assert shape is not None and round(shape["width"]) in (300, 434)
    page.locator(FIELD).focus()
    page.keyboard.press("Backspace")
    expect(waiting).to_have_class(re.compile("is-picked"))
    assert waiting.evaluate("el => getComputedStyle(el).borderStyle") in ("none", "")
    page.keyboard.press("Backspace")
    expect(waiting).to_have_count(0)
    expect(page.locator('[data-role="moving-view"]')).to_have_class(re.compile("is-picked"))
    page.keyboard.press("Backspace")
    expect(page.locator(SPANS)).to_have_count(0)
    expect(page.locator('[data-role="moving-stack"]')).to_have_count(0)
    with psycopg.connect(ui_f2.backend.dsn, autocommit=True) as conn:
        (vertical,) = conn.execute("SELECT vertical FROM goals WHERE id = %s", (MONTH_GOAL,)).fetchone()
    assert vertical == "month"


def test_typing_brings_the_board_and_clearing_the_weeks(ui_f2: UiSession) -> None:
    """S5.P3.038's first half: the regular board and its matches while you type; clearing brings the spans back."""
    page = ui_f2.page
    page.wait_for_selector(f'[data-goal-id="{MONTH_GOAL}"]')
    dots = _open_weeks(page)
    _glide(page, dots, _centre(page, ".circle-field__shape"))
    page.mouse.up()
    page.locator(FIELD).fill("Order")
    expect(page.locator(SPANS)).to_have_count(0)
    expect(page.locator('[data-role="column-strip"]')).to_have_count(1)
    expect(page.locator('[data-role="moving-view"]')).to_have_text("Weeks")
    page.locator(FIELD).fill("")
    expect(page.locator(SPANS)).to_have_count(1)


def test_words_sent_while_moving_go_to_the_agent_with_the_move(ui_agent: UiSession) -> None:  # noqa: F811
    """S5.P3.038's second half, .041, .042: ↵ sends a new task with the move's context and ends the move."""
    page = ui_agent.page
    page.wait_for_selector(f'[data-goal-id="{MONTH_GOAL}"]')
    dots = _open_weeks(page)
    _glide(page, dots, _centre(page, ".circle-field__shape"))
    page.mouse.up()
    expect(page.locator('[data-role="moving-goal"]')).to_have_count(1)
    page.locator(FIELD).fill("[context]")
    page.keyboard.press("Enter")
    answer = page.locator('[data-balloon][data-who="agent"]').last
    expect(answer).to_contain_text("moving a goal", timeout=10000)
    expect(answer).to_contain_text("Fix the bicycles rack")
    expect(page.locator(SPANS)).to_have_count(0)
    expect(page.locator('[data-role="moving-stack"]')).to_have_count(0)
