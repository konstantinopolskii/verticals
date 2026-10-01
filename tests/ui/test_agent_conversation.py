"""The circle and the agent (docs/design-handoff scope 2): the conversation over the board, the step bubble, the answer
in the circle, the agent's asks, message scroll, and the field with no agent. The agent is `tests/ui/fake_agent/claude`
behind the real desktop gateway and chat server; marks in the words steer it (`[tool:NAME]`, `[slow]`, `[ask]`,
`[long]`)."""

from __future__ import annotations

import json
import subprocess
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest
from playwright.sync_api import Browser, Page, expect

from tests.ui.conftest import (
    F2_OWNER, REPO_ROOT, TEST_TOKEN, Server, UiSession, _backend, _free_port, _make_ui_session, _shutdown, _wait_http_ok,
)
from tests.ui.views import FIELD


@contextmanager
def _agent_gateway(backend: Server, tmp_path: Path) -> Iterator[str]:
    """The desktop gateway over this test's backend, its agent the fake one (`tests/ui/agent_gateway.py`)."""
    port = _free_port()
    log_path = tmp_path / "gateway.log"
    with open(log_path, "w") as logfile:
        proc = subprocess.Popen(
            [sys.executable, str(REPO_ROOT / "tests" / "ui" / "agent_gateway.py"), str(port), str(backend.port),
             str(tmp_path / "desktop-state"), TEST_TOKEN],
            cwd=REPO_ROOT, stdout=logfile, stderr=subprocess.STDOUT, start_new_session=True,
        )
    base_url = f"http://127.0.0.1:{port}"
    try:
        _wait_http_ok(f"{base_url}/healthz", proc, log_path)
        yield base_url
    finally:
        _shutdown(proc, port)


@pytest.fixture
def ui_agent(
    browser: Browser, f2_dsn: str, tmp_path: Path, request: pytest.FixtureRequest, web_dist: None,
    ui_reduced_motion: str,
) -> Iterator[UiSession]:
    """F2 served by the desktop gateway, with the conversation's server and a fake agent (docs/design-handoff S2)."""
    with _backend(f2_dsn, F2_OWNER, tmp_path) as backend:
        with _agent_gateway(backend, tmp_path) as base_url:
            yield from _make_ui_session(
                browser=browser, backend=backend, static_base_url=base_url, request=request,
                reduced_motion=ui_reduced_motion,
            )


CONVERSATION = '[data-role="agent-conversation"]'
BALLOON = "[data-balloon]"
CIRCLE = ".circle-field"


def _send(page: Page, words: str) -> None:
    page.keyboard.press("Control+k")
    page.locator(FIELD).fill(words)
    page.keyboard.press("Enter")


def _answered(page: Page, text: str) -> None:
    expect(page.locator(f'{BALLOON}[data-who="agent"]', has_text=text).last).to_be_visible(timeout=10000)
    expect(page.locator('[data-role="agent-step"]')).to_have_count(0, timeout=10000)


def test_sending_rises_into_the_conversation_and_the_agent_answers(ui_agent: UiSession) -> None:
    page = ui_agent.page
    page.wait_for_selector(".goal-card__row")
    _send(page, "Plan the week [tool:schedule] [slow]")

    # S2.P3.002: the words are your balloon, the field is the circle again, the board is out of focus.
    expect(page.locator(f'{BALLOON}[data-who="you"]')).to_have_text("Plan the week [tool:schedule] [slow]")
    expect(page.locator(FIELD)).to_have_value("")
    expect(page.locator(".app-content--out-of-focus")).to_have_count(1)
    # S2.P3.004: the step bubble names the step; the line turns while the agent works.
    expect(page.locator('[data-role="agent-step"]')).to_have_text("Setting the date", timeout=5000)
    expect(page.locator(CIRCLE)).to_have_attribute("data-state", "working")
    expect(page.locator(".circle-field__pivot.is-turning")).to_have_count(1)

    _answered(page, "Done: Plan the week")
    expect(page.locator(".circle-field__pivot.is-turning")).to_have_count(0)
    # S2.P4.036: with the conversation open, the answer is a balloon and the circle stays a circle.
    expect(page.locator(CIRCLE)).to_have_attribute("data-state", "rest")

    # S2.P1.011: a click on the board sends the conversation away; the field asks the agent now (S1.P1.015).
    page.locator('[data-role="out-of-focus"]').click(position={"x": 60, "y": 60})
    expect(page.locator(CONVERSATION)).to_have_count(0)
    expect(page.locator(".app-content--out-of-focus")).to_have_count(0)
    expect(page.locator(FIELD)).to_have_attribute("aria-label", "Ask the agent")


def test_an_answer_lands_in_the_circle_and_a_click_sends_it_up(ui_agent: UiSession) -> None:
    page = ui_agent.page
    page.wait_for_selector(".goal-card__row")
    _send(page, "Tell me more [long] [slow]")
    page.locator('[data-role="out-of-focus"]').click(position={"x": 60, "y": 60})
    expect(page.locator(CONVERSATION)).to_have_count(0)

    # S2.P4.030: the circle grows around the answer; a long one shows three lines at most.
    answer = page.locator('[data-role="circle-answer"]')
    expect(answer).to_contain_text("Here is the first part", timeout=10000)
    box = page.locator(".circle-field__shape").bounding_box()
    assert box is not None and box["width"] <= 464 and box["height"] <= 114

    # S2.P4.031: a click sends it up as the agent's last balloon, and the field has the caret.
    page.locator(".circle-field__shape").click()
    expect(page.locator(CONVERSATION)).to_have_count(1)
    expect(page.locator(f'{BALLOON}[data-who="agent"]').last).to_contain_text("The third part closes it")
    expect(page.locator(FIELD)).to_be_focused()
    expect(page.locator('[data-role="circle-answer"]')).to_have_count(0)


def test_an_ask_is_the_agents_balloon_with_its_choices(ui_agent: UiSession) -> None:
    page = ui_agent.page
    page.wait_for_selector(".goal-card__row")
    _send(page, "Change it [ask]")
    ask = page.locator('[data-role="agent-ask"]')
    expect(ask).to_contain_text("Allow Claude to use update?", timeout=10000)
    # S2.P1.043: the line waits upright until you answer.
    expect(page.locator(".circle-field__pivot.is-turning")).to_have_count(0)
    ask.get_by_role("button", name="Allow once").click()
    _answered(page, "Done: Change it")
    expect(ask.get_by_role("button", name="Allow once")).to_be_disabled()


def test_a_conversation_from_before_opens_with_its_messages(ui_agent: UiSession) -> None:
    """S2.P1.031, .040: the conversations stored under `vt-chat:*` are read as they are."""
    page = ui_agent.page
    thread = "5d2c3c3e-1b1a-4c8e-9e1f-0a6f3e3c9b01"
    events = [{"t": "user", "text": "An old question", "ts": 1}, {"t": "turn_start", "ts": 2},
              {"t": "text", "text": "An old answer", "ts": 3}, {"t": "done", "ts": 4}]
    page.evaluate(
        """([id, events]) => {
          localStorage.setItem('vt-chat:threads', JSON.stringify([{ id, title: 'Old', provider: 'claude', updatedAt: 1, status: 'idle' }]))
          localStorage.setItem('vt-chat:current', JSON.stringify(id))
          localStorage.setItem(`vt-chat:events:${id}`, JSON.stringify(events))
        }""",
        [thread, events],
    )
    page.reload()
    page.wait_for_selector(".goal-card__row")
    _send(page, "And a new one")
    expect(page.locator(BALLOON).first).to_have_text("An old question")
    expect(page.locator(BALLOON).nth(1)).to_have_text("An old answer")
    _answered(page, "Done: And a new one")
    stored = json.loads(page.evaluate(f"localStorage.getItem('vt-chat:events:{thread}')"))
    assert [e["t"] for e in stored][:4] == ["user", "turn_start", "text", "done"]


def test_balloons_go_out_at_the_ends_and_come_back(ui_agent: UiSession) -> None:
    """S2.P5.022: a balloon goes out as half of it passes an end, and comes back as half of it returns."""
    page = ui_agent.page
    page.wait_for_selector(".goal-card__row")
    for n in range(5):
        _send(page, f"Message {n} [long]")
        expect(page.locator(f'{BALLOON}[data-who="agent"]')).to_have_count(n + 1, timeout=10000)
        expect(page.locator('[data-role="agent-step"]')).to_have_count(0, timeout=10000)
    sides = lambda: page.locator(BALLOON).evaluate_all("els => els.map(el => el.dataset.side)")  # noqa: E731
    assert "top" in sides() and "bottom" not in sides() and sides()[-1] == "in"
    page.mouse.move(735, 400)
    page.mouse.wheel(0, -600)
    page.wait_for_function(
        "() => [...document.querySelectorAll('[data-balloon]')].some(el => el.dataset.side === 'bottom')", timeout=5000
    )
    page.mouse.wheel(0, 2000)
    page.wait_for_function(
        "() => [...document.querySelectorAll('[data-balloon]')].slice(-1)[0].dataset.side === 'in'", timeout=5000
    )


def test_the_tags_stay_while_the_field_has_the_caret_or_the_conversation_is_open(ui_agent: UiSession) -> None:
    """Not only under the pointer: the tags stay in while the field has the caret or the conversation is open."""
    page = ui_agent.page
    page.wait_for_selector(".goal-card__row")
    page.mouse.move(100, 300)
    tags = page.locator(".circle-tags.is-shown")
    expect(tags).to_have_count(0)
    page.keyboard.press("Control+k")
    expect(tags).to_have_count(1)
    page.keyboard.press("Escape")
    expect(tags).to_have_count(0)

    _send(page, "Hello")
    _answered(page, "")
    page.evaluate("() => document.activeElement?.blur()")
    expect(page.locator(CONVERSATION)).to_be_visible()
    expect(tags).to_have_count(1)
    page.keyboard.press("Control+k")
    page.keyboard.press("Escape")  # the conversation goes, the caret stays
    expect(page.locator(CONVERSATION)).to_have_count(0)
    expect(tags).to_have_count(1)
    page.keyboard.press("Escape")
    expect(tags).to_have_count(0)


def test_no_agent_the_field_only_finds(ui_f2: UiSession) -> None:
    """S2.P1.026: the web build has no gateway: ↵ does nothing, and Discuss with agent isn't offered."""
    page = ui_f2.page
    page.wait_for_selector('[data-goal-id="SYNDAY01"]')
    page.keyboard.press("Control+k")
    page.locator(FIELD).fill("cycl")
    page.keyboard.press("Enter")
    expect(page.locator(CONVERSATION)).to_have_count(0)
    expect(page.locator(FIELD)).to_have_value("cycl")
    page.keyboard.press("Escape")
    page.keyboard.press("Escape")
    page.click('[data-goal-id="SYNDAY01"] > .goal-card__row [data-role="goal-actions-trigger"]')
    menu = page.locator('[data-role="goal-actions-menu"]')
    expect(menu).to_be_visible()
    expect(menu.get_by_text("Discuss with agent")).to_have_count(0)
