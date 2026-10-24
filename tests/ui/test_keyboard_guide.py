from pathlib import Path

from playwright.sync_api import expect

from tests.ui.conftest import UiSession, activate_column

FIELD = '.circle-field__words textarea'
GUIDE = 'dialog.keyboard-guide'


def start(page, vertical='day'):
    page.wait_for_selector('.goal-card__row')
    activate_column(page, vertical)
    row = page.locator(f'[data-keyboard-column][data-vertical="{vertical}"] .goal-card__row').first
    row.focus()
    return row


def test_guide_restores_focus_and_consumes_no_board_actions(ui_f2: UiSession):
    page = ui_f2.page
    row = start(page)
    page.keyboard.press('?')
    expect(page.locator(GUIDE)).to_be_visible()
    expect(page.locator(FIELD)).to_have_value('')
    expect(page.get_by_role('button', name='Close keyboard shortcuts')).to_be_focused()
    for key in ['n', 'f', 't', '?', 'Control+z', 'Control+Shift+p']:
        page.keyboard.press(key)
    expect(page.locator('[data-role="column-add-editor"]')).to_have_count(0)
    expect(page.locator(FIELD)).to_have_value('')
    page.keyboard.press('Tab')
    page.keyboard.press('Shift+Tab')
    expect(page.get_by_role('button', name='Close keyboard shortcuts')).to_be_focused()
    page.keyboard.press('Escape')
    expect(page.locator(GUIDE)).not_to_be_visible()
    expect(row).to_be_focused()
    assert not any(r['method'] in ['POST', 'PUT', 'PATCH', 'DELETE'] and '/api/goals' in r['url'] for r in ui_f2.request_log)


def test_help_preserves_uncommitted_title_and_selection(ui_f2: UiSession):
    page = ui_f2.page
    row = start(page)
    page.keyboard.press('Enter')
    title = page.locator('.goal-card__title-input')
    title.fill('Unfinished keyboard title')
    title.evaluate('el => el.setSelectionRange(3, 8)')
    page.get_by_role('button', name='Keyboard shortcuts', exact=True).click()
    expect(page.locator(GUIDE)).to_be_visible()
    expect(title).to_have_value('Unfinished keyboard title')
    assert not any(r['method'] == 'PATCH' and '/api/goals/' in r['url'] for r in ui_f2.request_log)
    page.keyboard.press('Escape')
    expect(title).to_be_focused()
    assert title.evaluate('el => [el.selectionStart, el.selectionEnd]') == [3, 8]
    page.keyboard.press('Escape')
    expect(title).to_have_count(0)
    expect(row).not_to_contain_text('Unfinished keyboard title')


def test_arrows_create_and_field_are_scoped(ui_f2: UiSession):
    page = ui_f2.page
    first = start(page)
    field = page.locator(FIELD)
    week = page.locator('[data-keyboard-column][data-vertical="week"]')
    page.keyboard.press('ArrowRight')
    expect(week.locator('.goal-card__row').first).to_be_focused()
    page.keyboard.press('ArrowLeft')
    expect(first).to_be_focused()
    page.keyboard.press('n')
    add = page.locator('[data-vertical="day"] [data-role="column-add-editor"]')
    expect(add).to_be_focused()
    add.fill('Keyboard creation check')
    page.keyboard.press('Enter')
    expect(page.locator('[data-vertical="day"] .goal-card__title-text').filter(has_text='Keyboard creation check')).to_have_count(1)
    first.focus()
    page.keyboard.press('f')
    expect(field).to_be_focused()
    field.fill('native text')
    page.keyboard.press('Home')
    page.keyboard.press('ArrowRight')
    page.keyboard.insert_text('?n')
    expect(field).to_have_value('n?native text')
    expect(page.locator(GUIDE)).not_to_be_visible()


def test_row_slash_and_checkbox_keep_native_ownership(ui_f2: UiSession):
    page = ui_f2.page
    row = start(page)
    page.keyboard.press('/')
    expect(page.locator('[data-role="goal-context-menu"]')).to_be_visible()
    expect(page.locator(FIELD)).to_have_value('')
    page.keyboard.press('Escape')
    row.locator('input[type="checkbox"]').first.focus()
    page.keyboard.press('Space')
    expect(page.locator('#goal-detail')).to_have_count(0)


def test_guide_empty_columns_context_and_layout(ui_f2: UiSession):
    page = ui_f2.page
    start(page)
    for viewport in [dict(width=1440, height=900), dict(width=393, height=659)]:
        page.set_viewport_size(viewport)
        page.get_by_role('button', name='Keyboard shortcuts', exact=True).click()
        guide = page.locator(GUIDE)
        expect(guide).to_be_visible()
        assert guide.evaluate('el => el.scrollWidth <= el.clientWidth')
        page.keyboard.press('Escape')
    page.set_viewport_size(dict(width=1440, height=900))
    page.keyboard.press('?')
    out=Path('/tmp/keyboard-after'); out.mkdir(exist_ok=True)
    page.screenshot(path=str(out/'00.png'))
    page.locator(GUIDE).screenshot(path=str(out/'guide.png'))
    page.emulate_media(color_scheme='dark')
    page.screenshot(path=str(out/'dark.png'))
    page.emulate_media(color_scheme='light')
    page.keyboard.press('Escape')
    page.screenshot(path=str(out/'01.png'))


def test_help_leaves_open_details_and_backdrop_restores_focus(ui_f2: UiSession):
    page = ui_f2.page
    row = start(page)
    page.keyboard.press('Space')
    expect(page.locator('#goal-detail')).to_be_visible()
    page.get_by_role('button', name='Keyboard shortcuts', exact=True).click()
    expect(page.locator(GUIDE)).to_be_visible()
    page.mouse.click(5, 5)
    expect(page.locator(GUIDE)).not_to_be_visible()
    expect(page.locator('#goal-detail')).to_be_visible()
    expect(row).to_be_focused()


def test_empty_filtered_columns_remain_navigable(ui_f2: UiSession):
    page = ui_f2.page
    start(page)
    page.keyboard.press('f')
    page.locator(FIELD).fill('no-match-keyboard-check')
    day = page.locator('[data-keyboard-column][data-vertical="day"]')
    expect(day.locator('.goal-card__row')).to_have_count(0)
    day.focus()
    page.keyboard.press('ArrowRight')
    week = page.locator('[data-keyboard-column][data-vertical="week"]')
    expect(week).to_be_focused()
    page.keyboard.press('ArrowDown')
    expect(week).to_be_focused()
    page.keyboard.press('?')
    expect(page.locator(GUIDE)).to_contain_text('Clear the filter to create a new goal.')
    page.keyboard.press('Escape')
    expect(week).to_be_focused()
    expect(page.locator(FIELD)).to_have_value('no-match-keyboard-check')


def test_help_escape_precedes_the_field_notice(ui_f2: UiSession):
    page = ui_f2.page
    row = start(page)
    page.keyboard.press('/')
    page.locator('[data-role="goal-context-menu"] [data-move="tomorrow"]').click()
    expect(page.locator('[data-role="field-notice"]')).to_be_visible()
    page.get_by_role('button', name='Keyboard shortcuts', exact=True).click()
    expect(page.locator(GUIDE)).to_be_visible()
    page.keyboard.press('Escape')
    expect(page.locator(GUIDE)).not_to_be_visible()


def test_add_draft_survives_help_and_n_refocuses_it(ui_f2: UiSession):
    page = ui_f2.page
    start(page)
    page.keyboard.press('n')
    editor = page.locator('[data-role="column-add-editor"]')
    page.get_by_role('button', name='Keyboard shortcuts', exact=True).click()
    page.keyboard.press('Escape')
    expect(editor).to_be_focused()
    editor.fill('Pending creation')
    page.locator('[data-keyboard-column][data-vertical="day"]').focus()
    page.keyboard.press('n')
    expect(editor).to_be_focused()
    expect(editor).to_have_value('Pending creation')
    page.keyboard.press('Escape')


def test_composition_does_not_run_shortcuts_or_submit_creation(ui_f2: UiSession):
    page = ui_f2.page
    row = start(page)
    row.dispatch_event('keydown', dict(key='n', isComposing=True))
    expect(page.locator('[data-role="column-add-editor"]')).to_have_count(0)
    page.keyboard.press('n')
    editor = page.locator('[data-role="column-add-editor"]')
    editor.fill('Composition draft')
    editor.dispatch_event('keydown', dict(key='Enter', isComposing=True))
    expect(editor).to_be_visible()
    assert not any(r['method'] == 'POST' and r['url'].endswith('/api/goals') for r in ui_f2.request_log)
    page.keyboard.press('Escape')


def test_help_preserves_an_empty_subgoal_editor(ui_f2: UiSession):
    page = ui_f2.page
    start(page)
    page.keyboard.press('Space')
    page.locator('[data-role="subgoal-add"]').click()
    editor = page.locator('[data-role="subgoal-add-editor"]')
    expect(editor).to_be_focused()
    page.get_by_role('button', name='Keyboard shortcuts', exact=True).click()
    expect(page.locator(GUIDE)).to_be_visible()
    page.keyboard.press('Escape')
    expect(editor).to_be_visible()
    expect(editor).to_be_focused()
    expect(editor).to_have_value('')
