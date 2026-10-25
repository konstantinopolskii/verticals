"""Board keys as a person meets them: no focus set up by the test, the pointer mixed in, and an empty board."""
from collections.abc import Iterator
from datetime import date
import re
from pathlib import Path

import psycopg
import pytest
from playwright.sync_api import Browser, expect

from verticals.core import goals
from tests.ui.conftest import F2_OWNER, UiSession, _backend, _make_ui_session, _static_server
from tests.ui.views import switch_view

FIELD = '.circle-field__words textarea'
GUIDE = 'dialog.keyboard-guide'


@pytest.fixture
def ui_empty(browser: Browser, db_dsn: str, tmp_path: Path, request: pytest.FixtureRequest, web_dist: None,
             ui_reduced_motion: str) -> Iterator[UiSession]:
    """A board with no goals at all."""
    with _backend(db_dsn, F2_OWNER, tmp_path) as backend:
        with _static_server(backend.base_url, tmp_path) as static_base_url:
            yield from _make_ui_session(browser=browser, backend=backend, static_base_url=static_base_url,
                                        request=request, reduced_motion=ui_reduced_motion)


def column(page, vertical):
    return page.locator(f'[data-keyboard-column][data-vertical="{vertical}"]')


def first_row(page, vertical):
    return column(page, vertical).locator('.goal-card__row').first


def away(page):
    page.evaluate('() => document.activeElement?.blur()')


def add_row(page, vertical):
    return column(page, vertical).locator('[data-role="column-add"]')


def add_field(page, vertical):
    return column(page, vertical).locator('[data-role="column-add-editor"]')


def loaded(page):
    page.wait_for_selector('.goal-card__row')
    away(page)


def test_an_arrow_on_a_fresh_board_picks_the_first_goal(ui_f2: UiSession):
    page = ui_f2.page
    loaded(page)
    page.keyboard.press('ArrowDown')
    expect(first_row(page, 'day')).to_be_focused()
    expect(page.locator(FIELD)).to_have_value('')


def test_arrows_then_move_between_columns(ui_f2: UiSession):
    page = ui_f2.page
    loaded(page)
    page.keyboard.press('ArrowRight')
    page.keyboard.press('ArrowRight')
    expect(first_row(page, 'week')).to_be_focused()


def test_question_mark_on_the_background_opens_the_guide(ui_f2: UiSession):
    page = ui_f2.page
    loaded(page)
    page.keyboard.press('?')
    expect(page.locator(GUIDE)).to_be_visible()
    page.keyboard.press('Escape')
    expect(page.locator(FIELD)).to_have_value('')


def test_a_letter_on_the_background_still_starts_the_field(ui_f2: UiSession):
    page = ui_f2.page
    loaded(page)
    page.keyboard.press('h')
    expect(page.locator(FIELD)).to_be_focused()
    expect(page.locator(FIELD)).to_have_value('h')


def test_a_click_away_keeps_the_goal_the_arrows_return_to(ui_f2: UiSession):
    page = ui_f2.page
    loaded(page)
    page.keyboard.press('ArrowDown')
    page.keyboard.press('ArrowRight')
    page.keyboard.press('ArrowDown')
    second = column(page, 'week').locator('.goal-card__row').nth(1)
    expect(second).to_be_focused()
    away(page)
    page.keyboard.press('ArrowUp')
    expect(second).to_be_focused()


def test_a_created_goal_leaves_the_keys_in_its_column(ui_f2: UiSession):
    page = ui_f2.page
    loaded(page)
    page.keyboard.press('ArrowDown')
    page.keyboard.press('n')
    page.keyboard.type('Made from the keyboard')
    page.keyboard.press('Enter')
    expect(page.locator('[data-vertical="day"] .goal-card__title-text').filter(has_text='Made from the keyboard')).to_have_count(1)
    expect(add_row(page, 'day')).to_be_focused()
    page.keyboard.press('n')
    expect(page.locator('[data-vertical="day"] [data-role="column-add-editor"]')).to_be_focused()
    page.keyboard.press('Escape')
    expect(add_row(page, 'day')).to_be_focused()
    expect(page.locator(FIELD)).to_have_value('')


def test_enter_on_a_column_starts_a_goal_there(ui_f2: UiSession):
    page = ui_f2.page
    loaded(page)
    column(page, 'month').focus()
    page.keyboard.press('Enter')
    expect(page.locator('[data-vertical="month"] [data-role="column-add-editor"]')).to_be_focused()


def test_focus_marks_the_goal_and_column_without_white_frames(ui_f2: UiSession):
    page = ui_f2.page
    page.emulate_media(color_scheme='dark')
    loaded(page)
    page.keyboard.press('ArrowDown')
    row = first_row(page, 'day')
    expect(row).to_be_focused()
    assert row.evaluate('el => getComputedStyle(el).outlineStyle') == 'none'
    assert float(row.evaluate("el => getComputedStyle(el, '::before').opacity")) > 0.3
    month = column(page, 'month')
    add = month.locator('[data-role="column-add"]')
    rest = add.evaluate('el => getComputedStyle(el).backgroundColor')
    page.keyboard.press('ArrowRight')
    page.keyboard.press('ArrowRight')
    month.focus()
    expect(month).to_be_focused()
    assert month.evaluate('el => getComputedStyle(el).outlineStyle') == 'none'
    assert month.evaluate("el => getComputedStyle(el).boxShadow") == 'none'
    page.wait_for_timeout(400)
    assert add.evaluate('el => getComputedStyle(el).backgroundColor') != rest


def test_leaving_the_board_lets_the_open_column_lead_again(ui_f2: UiSession):
    page = ui_f2.page
    loaded(page)
    page.keyboard.press('ArrowRight')
    page.keyboard.press('ArrowRight')
    page.keyboard.press('ArrowRight')
    expect(page.locator('.pattern-vertical-board__column--deck-main')).to_have_attribute('data-vertical', 'month')
    away(page)
    expect(page.locator('.pattern-vertical-board__column--deck-main')).to_have_attribute('data-vertical', 'day')


def test_the_guide_says_how_to_start(ui_f2: UiSession):
    page = ui_f2.page
    loaded(page)
    page.keyboard.press('?')
    expect(page.locator(GUIDE)).to_contain_text('Press an arrow key to pick a goal.')


def test_an_empty_board_takes_the_keys(ui_empty: UiSession):
    page = ui_empty.page
    page.wait_for_selector('[data-keyboard-column]')
    page.keyboard.press('ArrowDown')
    expect(add_field(page, 'day')).to_be_focused()
    page.keyboard.press('ArrowRight')
    expect(add_field(page, 'week')).to_be_focused()
    expect(add_field(page, 'day')).to_have_count(0)
    page.keyboard.type('First goal')
    page.keyboard.press('Enter')
    expect(add_row(page, 'week')).to_be_focused()
    expect(first_row(page, 'week')).to_contain_text('First goal')
    page.keyboard.press('ArrowUp')
    expect(first_row(page, 'week')).to_be_focused()


def test_arrows_in_the_field_stay_in_the_field(ui_f2: UiSession):
    page = ui_f2.page
    loaded(page)
    page.keyboard.press('h')
    page.keyboard.press('ArrowLeft')
    page.keyboard.press('ArrowDown')
    expect(page.locator(FIELD)).to_be_focused()


def test_typing_after_a_click_in_a_column_goes_to_the_field(ui_f2: UiSession):
    page = ui_f2.page
    loaded(page)
    box = column(page, 'week').bounding_box()
    page.mouse.click(box['x'] + box['width'] / 2, box['y'] + box['height'] - 120)
    page.keyboard.type('next')
    expect(page.locator(FIELD)).to_have_value('next')
    expect(page.locator('[data-role="column-add-editor"]')).to_have_count(0)


def test_typing_after_clicking_a_goal_goes_to_the_field(ui_f2: UiSession):
    page = ui_f2.page
    loaded(page)
    box = first_row(page, 'week').bounding_box()
    page.mouse.click(box['x'] + 60, box['y'] + box['height'] / 2)
    page.keyboard.type('hello')
    expect(page.locator(FIELD)).to_have_value('hello')


def test_arrows_in_inbox_leave_the_hidden_board_alone(ui_f2: UiSession):
    page = ui_f2.page
    loaded(page)
    switch_view(page, 'inbox')
    away(page)
    page.keyboard.press('ArrowDown')
    page.keyboard.press('?')
    assert page.evaluate("() => !document.activeElement.closest('[data-keyboard-column]')")
    expect(page.locator(GUIDE)).not_to_be_visible()


def test_escape_from_a_goal_title_edit_returns_to_the_goal(ui_f2: UiSession):
    page = ui_f2.page
    loaded(page)
    page.keyboard.press('ArrowDown')
    page.keyboard.press('Enter')
    expect(page.locator('.goal-card__title-input')).to_be_focused()
    page.keyboard.press('Escape')
    expect(first_row(page, 'day')).to_be_focused()
    page.keyboard.press('ArrowDown')
    expect(column(page, 'day').locator('.goal-card__row').nth(1)).to_be_focused()


def test_arrows_leave_an_add_row_a_checkbox_and_the_period_bars(ui_f2: UiSession):
    page = ui_f2.page
    loaded(page)
    add = add_row(page, 'week')
    add.focus()
    page.keyboard.press('ArrowUp')
    expect(column(page, 'week').locator('.goal-card__row').last).to_be_focused()
    page.keyboard.press('ArrowDown')
    expect(add_field(page, 'week')).to_be_focused()
    page.keyboard.press('ArrowLeft')
    expect(column(page, 'day').locator('.goal-card__row, [data-role="column-add-editor"]').nth(4)).to_be_focused()
    first_row(page, 'month').locator('input[type="checkbox"]').first.focus()
    page.keyboard.press('ArrowDown')
    expect(column(page, 'month').locator('.goal-card__row').nth(1)).to_be_focused()
    column(page, 'week').locator('.column-bars button').first.focus()
    page.keyboard.press('ArrowDown')
    expect(first_row(page, 'week')).to_be_focused()


def test_ctrl_backslash_puts_the_field_away_until_pressed_again(ui_f2: UiSession):
    page = ui_f2.page
    loaded(page)
    circle = page.locator('.circle-field')
    page.keyboard.press('Control+Backslash')
    expect(circle).to_have_css('visibility', 'hidden')
    page.keyboard.press('h')
    page.keyboard.press('Control+k')
    page.keyboard.press('ArrowDown')
    page.keyboard.press('f')
    expect(page.locator(FIELD)).to_have_value('')
    expect(page.locator(FIELD)).not_to_be_focused()
    expect(first_row(page, 'day')).to_be_focused()
    page.reload()
    page.wait_for_selector('.goal-card__row')
    expect(circle).to_have_css('visibility', 'hidden')
    page.keyboard.press('Control+Backslash')
    expect(circle).to_have_css('visibility', 'visible')
    away(page)
    page.keyboard.press('h')
    expect(page.locator(FIELD)).to_have_value('h')


def test_hiding_the_field_while_typing_in_it_drops_the_caret(ui_f2: UiSession):
    page = ui_f2.page
    loaded(page)
    page.keyboard.press('h')
    expect(page.locator(FIELD)).to_be_focused()
    page.keyboard.press('Control+Backslash')
    expect(page.locator(FIELD)).not_to_be_focused()
    page.keyboard.press('ArrowDown')
    expect(first_row(page, 'day')).to_be_focused()


def test_space_closes_the_goal_it_opened_without_redrawing_it(ui_f2: UiSession):
    page = ui_f2.page
    loaded(page)
    page.keyboard.press('ArrowDown')
    row = first_row(page, 'day')
    page.keyboard.press('Space')
    expect(page.locator('#goal-detail')).to_be_visible()
    opened = -1
    while opened != len(ui_f2.request_log):  # the opening's own fetches land before the count
        opened = len(ui_f2.request_log)
        page.wait_for_timeout(400)
    page.keyboard.press('Space')
    expect(page.locator('#goal-detail')).to_have_count(0)
    expect(row).to_be_focused()
    # Prefetches of other goals may come; the open goal itself is not fetched again.
    goal = row.evaluate('el => el.closest("[data-goal-id]").dataset.goalId')
    late = [r['url'] for r in ui_f2.request_log[opened:] if r['method'] == 'GET' and f'/api/goals/{goal}' in r['url']]
    assert not late, late
    page.keyboard.press('Space')
    expect(page.locator('#goal-detail')).to_be_visible()


def test_arrows_reach_the_plans_carried_over(ui_f2: UiSession):
    with psycopg.connect(ui_f2.backend.dsn, autocommit=True) as conn:
        goals.create(conn, owner='t1', title='SYN carried by keys', vertical='year',
                     anchor_date=date(date.today().year - 1, 6, 15))
    page = ui_f2.page
    page.goto(f'{ui_f2.base_url}/h/{date.today().isoformat()}')
    page.wait_for_selector('[data-role="carried-group"]')
    year = column(page, 'year')
    year.locator('[data-section="planned"] .goal-card__row, [data-role="column-add"]').first.focus()
    page.keyboard.press('ArrowUp')
    focused_in_box = 'document.activeElement.matches("[data-role=carried-group] .goal-card__row")'
    assert page.evaluate(focused_in_box)
    page.keyboard.press('ArrowDown')
    assert not page.evaluate(focused_in_box)


def test_e_marks_the_goal_done_without_opening_it(ui_f2: UiSession):
    page = ui_f2.page
    loaded(page)
    page.keyboard.press('ArrowDown')
    row = page.locator(':focus')
    card = row.locator('xpath=..')
    box = row.locator('[data-cap="complete"]').first
    was = box.get_attribute('aria-checked')
    page.keyboard.press('e')
    expect(box).not_to_have_attribute('aria-checked', was)
    expect(page.locator('#goal-detail')).to_have_count(0)
    expect(page.locator(FIELD)).to_have_value('')
    expect(card.locator('> .goal-card__row')).to_be_focused()
    page.keyboard.press('e')
    expect(box).to_have_attribute('aria-checked', was)


def test_shift_arrows_page_the_column_and_the_columns_under_it(ui_f2: UiSession):
    page = ui_f2.page
    loaded(page)
    month, week = column(page, 'month'), column(page, 'week')
    was = month.get_attribute('data-period-key'), week.get_attribute('data-period-key')
    add_row(page, 'month').first.focus()
    page.keyboard.press('Shift+ArrowRight')
    expect(month).not_to_have_attribute('data-period-key', was[0])
    expect(week).not_to_have_attribute('data-period-key', was[1])
    expect(month).to_be_focused()
    page.keyboard.press('Shift+ArrowLeft')
    expect(month).to_have_attribute('data-period-key', was[0])
    expect(page.locator(FIELD)).to_have_value('')


def test_shift_down_widens_the_column_and_shift_up_narrows_it(ui_f2: UiSession):
    page = ui_f2.page
    loaded(page)
    month = column(page, 'month')
    add_row(page, 'month').first.focus()
    page.keyboard.press('Shift+ArrowDown')
    expect(month).to_have_class(re.compile('pattern-vertical-board__column--active'))
    page.keyboard.press('Shift+ArrowDown')
    expect(month).to_have_class(re.compile('pattern-vertical-board__column--active'))
    page.keyboard.press('Shift+ArrowUp')
    expect(month).not_to_have_class(re.compile('pattern-vertical-board__column--active'))


def test_space_lights_the_goal_it_opens_not_the_one_under_the_pointer(ui_f2: UiSession):
    page = ui_f2.page
    loaded(page)
    rows = column(page, 'day').locator('[data-section="planned"] > .goal-card > .goal-card__row')
    pointed, keyed = rows.nth(0), rows.nth(1)
    box = pointed.bounding_box()
    page.mouse.move(box['x'] + 40, box['y'] + box['height'] / 2)
    page.mouse.move(box['x'] + 44, box['y'] + box['height'] / 2)
    page.wait_for_timeout(400)  # the pointer rests: its goal's family lights
    keyed.focus()
    page.keyboard.press('Space')
    expect(page.locator('#goal-detail')).to_be_visible()
    page.wait_for_timeout(600)
    opened = keyed.locator('xpath=..')
    expect(opened).to_have_attribute('data-light', re.compile('.+'))
    expect(opened).not_to_have_class(re.compile('goal-card--lifted'))
    expect(pointed.locator('xpath=..')).not_to_have_class(re.compile('goal-card--lifted'))


def test_the_keys_reach_an_add_row_ready_to_type(ui_f2: UiSession):
    page = ui_f2.page
    loaded(page)
    column(page, 'month').locator('.goal-card__row').last.focus()
    page.keyboard.press('ArrowDown')
    expect(add_field(page, 'month')).to_be_focused()
    page.keyboard.type('Typed at once')
    page.keyboard.press('ArrowUp')  # a field with words keeps its arrows
    expect(add_field(page, 'month')).to_be_focused()
    page.keyboard.press('Escape')
    expect(add_row(page, 'month')).to_be_focused()
    expect(page.locator(FIELD)).to_have_value('')
