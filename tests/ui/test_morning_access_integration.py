"""The background timer receives settings only after the first access choice."""

import json
from pathlib import Path

import pytest
from playwright.sync_api import expect

from tests.ui.test_agent_conversation import ui_agent


pytestmark = pytest.mark.skipif(
    not (Path(__file__).resolve().parents[2] / "desktop/chat/morning_schedule.py").exists(),
    reason="requires the background morning report integration",
)


@pytest.fixture
def agent_access_chosen():
    return False


@pytest.mark.parametrize("choice,permission", [
    ("Allow full access", "bypassPermissions"),
    ("Keep asking", "board"),
])
def test_background_reports_wait_for_the_access_choice(ui_agent, tmp_path, choice, permission):
    page = ui_agent.page
    expect(page.get_by_role("dialog", name="Agent access")).to_be_visible()
    before = page.evaluate("async () => (await (await fetch('/__chat/morning')).json())")
    assert before["configured"] is False
    saved = tmp_path / "desktop-state/morning.json"
    assert not saved.exists()

    page.get_by_role("button", name=choice, exact=True).click()
    page.wait_for_function("async () => (await (await fetch('/__chat/morning')).json()).configured")
    assert json.loads(saved.read_text())["settings"]["permission"] == permission
    page.reload()
    expect(page.get_by_role("dialog", name="Agent access")).to_have_count(0)
    assert json.loads(saved.read_text())["settings"]["permission"] == permission
