"""The first-run access choice persists and reaches ordinary and automatic agent turns."""
import json
from pathlib import Path

import psycopg
import pytest
from playwright.sync_api import expect

from tests.ui.conftest import F2_OWNER, UiSession, VIEWPORT
from tests.ui.test_agent_conversation import ui_agent, _send, _answered, _cli_starts, _flag


@pytest.fixture
def agent_access_chosen():
    return False


def test_full_access_is_chosen_once_and_used_after_reload(ui_agent: UiSession, tmp_path: Path):
    page = ui_agent.page
    setup = page.get_by_role('dialog', name='Agent access')
    expect(setup).to_be_visible()
    assert not _cli_starts(tmp_path)
    shots = Path('artifacts/agent-access')
    shots.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(shots / 'setup-desktop.png'))
    page.set_viewport_size({'width': 390, 'height': 844})
    page.screenshot(path=str(shots / 'setup-phone.png'))
    bounds = setup.bounding_box()
    assert bounds['width'] <= 358 and bounds['x'] >= 16 and bounds['y'] >= 16
    page.get_by_role('button', name='Allow full access', exact=True).click()
    expect(setup).to_have_count(0)
    page.set_viewport_size(VIEWPORT)
    page.screenshot(path=str(shots / 'board-after-choice.png'))
    page.reload()
    expect(page.locator('[data-tag="agent"]')).to_be_visible()
    expect(setup).to_have_count(0)
    _send(page, 'Hello')
    _answered(page, 'Done: Hello')
    assert _flag(_cli_starts(tmp_path)[-1], '--permission-mode') == 'bypassPermissions'
    prefs = page.evaluate("JSON.parse(localStorage.getItem('vt-chat:agent-prefs'))")
    assert prefs['codex']['permission'] == 'full-access'
    assert prefs['claude']['permission'] == 'bypassPermissions'
    page.locator('[data-tag="agent"]').click()
    page.get_by_role('button', name='Verticals only', exact=True).click()
    page.keyboard.press('Escape')
    _send(page, 'Restricted now')
    _answered(page, 'Done: Restricted now')
    assert _flag(_cli_starts(tmp_path)[-1], '--permission-mode') != 'bypassPermissions'


def test_morning_waits_for_access_choice_then_honors_it(ui_agent: UiSession, tmp_path: Path):
    page = ui_agent.page
    with psycopg.connect(ui_agent.backend.dsn, autocommit=True) as conn:
        conn.execute("DELETE FROM idempotency WHERE owner = %s AND client_token LIKE 'morning:%%'", (F2_OWNER,))
    page.reload()
    expect(page.get_by_role('dialog', name='Agent access')).to_be_visible()
    assert not _cli_starts(tmp_path)
    page.get_by_role('button', name='Allow full access', exact=True).click()
    expect(page.locator('[data-role="circle-answer"]')).to_contain_text('Make my morning report', timeout=15000)
    args = _cli_starts(tmp_path)[0]
    assert _flag(args, '--permission-mode') == 'bypassPermissions'
    assert '--tools' not in args


def test_keep_asking_does_not_grant_full_access(ui_agent: UiSession, tmp_path: Path):
    page = ui_agent.page
    page.get_by_role('button', name='Keep asking', exact=True).click()
    page.reload()
    expect(page.get_by_role('dialog', name='Agent access')).to_have_count(0)
    _send(page, 'Hello')
    _answered(page, 'Done: Hello')
    assert _flag(_cli_starts(tmp_path)[-1], '--permission-mode') != 'bypassPermissions'
