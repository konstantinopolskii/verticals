"""When the agent is signed out, the field signs it back in (docs/design/agent-sign-in.md), as the owner sees it: the turn that
failed ends with the field's own ask (its title, its line and Sign in) and not the CLI's error; a click says to approve in the
browser and offers the sign-in page, in the conversation and in the field; once signed in, the ask ends with "Signed in" and the
message is answered, in the field when the conversation is hidden. The agent is tests/ui/fake_agent/claude behind the real desktop
gateway, signed out by `fake-auth.json` in its home and signed in by the test."""

from __future__ import annotations

import json
from pathlib import Path

from playwright.sync_api import expect

from tests.ui.conftest import UiSession
from tests.ui.test_agent_conversation import (  # noqa: F401  (ui_agent: the fixture)
    AGENT_BALLOON, ANSWER, BALLOON, CONVERSATION, _send, close_the_conversation, ui_agent,
)

ASK = '[data-role="agent-ask"]'
NOTE = '[data-role="agent-ask-note"]'


def test_a_signed_out_agent_asks_to_sign_in_and_the_message_goes_again(ui_agent: UiSession, tmp_path: Path) -> None:
    page = ui_agent.page
    auth = tmp_path / "desktop-state" / "claude-config" / "fake-auth.json"
    auth.write_text(json.dumps({"signedOut": True}))
    page.wait_for_selector(".goal-card__row")
    _send(page, "Plan the week")

    ask = page.locator(ASK)
    expect(ask).to_be_visible(timeout=10000)
    expect(ask.locator(".agent-balloon__ask-title")).to_have_text("Claude Code is signed out on this Mac")
    expect(ask.locator(NOTE)).to_have_text("Sign in once and your message goes again.")
    expect(ask.get_by_role("button")).to_have_text(["Sign in"])
    expect(page.locator(CONVERSATION)).not_to_contain_text("Failed to authenticate")
    expect(page.locator(".agent-balloon--error")).to_have_count(0)

    ask.get_by_role("button", name="Sign in").click()
    expect(ask.locator(NOTE)).to_have_text("Approve in the browser.", timeout=10000)
    expect(ask.get_by_role("button")).to_have_text(["Open the sign-in page"], timeout=10000)
    expect(page.locator(ASK)).to_have_count(1)  # the same ask, changed in place

    # Hidden, the conversation's ask waits in the field, with no words of the agent's on top.
    close_the_conversation(page)
    field = page.locator(ANSWER)
    expect(field.locator(".circle-field__answer-words")).to_have_text("Claude Code is signed out on this Mac")
    expect(field.locator('[data-role="circle-ask-changes"]')).to_have_text("Approve in the browser.")
    expect(field.get_by_role("button")).to_have_text(["Open the sign-in page"])
    expect(field.locator(".circle-field__answer-lead")).to_have_count(0)

    auth.write_text("{}")  # the owner approved in the browser
    expect(field.locator(".circle-field__answer-words")).to_have_text("Done: Plan the week", timeout=15000)
    page.locator(".circle-field__answer-words").click()
    expect(page.locator(AGENT_BALLOON, has_text="Signed in")).to_have_count(1)
    expect(page.locator(AGENT_BALLOON).last).to_have_text("Done: Plan the week")
    expect(page.locator(ASK)).to_have_count(0)
    expect(page.locator(f'{BALLOON}[data-who="you"]')).to_have_count(1)  # the message went again, not twice in the conversation
