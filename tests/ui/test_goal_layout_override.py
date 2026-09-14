"""Promoted browser override: goal typography/layout controls and add-editor space handling."""

from __future__ import annotations

from datetime import date

import psycopg
from playwright.sync_api import expect

from verticals.core import goals
from tests.ui.conftest import UiSession


def test_saved_goal_layout_defaults_panel_persistence_and_space_key(ui_f2: UiSession) -> None:
    session = ui_f2
    page = session.page
    with psycopg.connect(session.backend.dsn, autocommit=True) as conn:
        parent = goals.create(
            conn, owner="t1", title="SYN layout parent", vertical="quarter",
            anchor_date=date(2026, 8, 8),
        ).goal
        first = goals.create(
            conn, owner="t1", title="SYN layout first child", vertical="quarter",
            anchor_date=date(2026, 8, 8), parent_id=parent.id,
        ).goal
        second = goals.create(
            conn, owner="t1", title="SYN layout second child", vertical="quarter",
            anchor_date=date(2026, 8, 8), parent_id=parent.id,
        ).goal

    page.reload()
    column = page.locator('.pattern-vertical-board__column[data-vertical="quarter"]')
    parent_card = column.locator(f'[data-goal-id="{parent.id}"]')
    parent_title = parent_card.locator('.goal-card__title').first
    parent_box = parent_card.locator('[data-role="checkbox-box"]').first
    expect(parent_title).to_be_visible()

    compact = parent_title.evaluate(
        "el => ({size:getComputedStyle(el).fontSize, line:getComputedStyle(el).lineHeight, weight:getComputedStyle(el).fontWeight})"
    )
    assert compact == {"size": "12px", "line": "19px", "weight": "500"}
    assert parent_box.evaluate("el => getComputedStyle(el).width") == "14px"

    children = parent_card.locator('xpath=following-sibling::*[1][contains(@class, "goal-card__children")]')
    first_card = children.locator(f':scope > [data-goal-id="{first.id}"]')
    second_card = children.locator(f':scope > [data-goal-id="{second.id}"]')
    expect(first_card).to_be_visible()
    expect(second_card).to_be_visible()
    assert first_card.evaluate("el => getComputedStyle(el, '::before').opacity") == "1"
    assert second_card.evaluate("el => getComputedStyle(el, '::before').opacity") == "0"

    column.locator('.pattern-vertical-board__header').first.click()
    page.wait_for_function(
        """() => document.querySelector('[data-vertical="quarter"]')
          ?.classList.contains('pattern-vertical-board__column--active')"""
    )
    expanded = parent_title.evaluate(
        "el => ({size:getComputedStyle(el).fontSize, line:getComputedStyle(el).lineHeight, weight:getComputedStyle(el).fontWeight})"
    )
    assert expanded == {"size": "24px", "line": "32px", "weight": "500"}
    assert parent_box.evaluate("el => getComputedStyle(el).width") == "22px"

    page.keyboard.press("Backslash")
    layout_button = page.get_by_role("button", name="Open goal layout settings")
    expect(layout_button).to_be_visible()
    layout_button.click()
    panel = page.get_by_role("complementary", name="Goal column layout")
    expect(panel).to_be_visible()
    font_size = panel.locator('#goal-layout-kkov-collapsed-goal-font-size')
    font_size.evaluate(
        """el => { el.value = '13'; el.dispatchEvent(new Event('input', {bubbles:true})) }"""
    )
    assert page.evaluate(
        "localStorage.getItem('verticals-dev-goal-layout-v1')?.includes('13')"
    )

    # Reload proves the panel stores values instead of resetting on ordinary app interaction.
    page.reload()
    parent_title = page.locator(f'[data-goal-id="{parent.id}"] .goal-card__title').first
    expect(parent_title).to_be_visible()
    assert parent_title.evaluate("el => getComputedStyle(el).fontSize") == "13px"

    # Exact iPad landscape CSS viewport: the seven-column flat layout stays inside its strip.
    page.set_viewport_size({"width": 1024, "height": 768})
    assert page.evaluate("[innerWidth, innerHeight]") == [1024, 768]
    assert page.locator('.pattern-vertical-board__column').count() == 7
    assert page.evaluate(
        """() => { const board = document.querySelector('.pattern-vertical-board');
        return board && board.scrollWidth <= board.clientWidth + 1
          && document.documentElement.scrollWidth <= innerWidth + 1 }"""
    )

    add_row = page.locator('.pattern-vertical-board__column[data-vertical="quarter"] [data-role="column-add"]')
    add_row.click()
    editor = add_row.locator('[data-role="column-add-editor"]')
    editor.press_sequentially("Alpha Beta")
    assert editor.input_value() == "Alpha Beta"
    editor.press("Escape")
