"""The goal window (docs/design-handoff scope 3): Discuss with agent lifts the goal into a window with its conversation,
continues the goal's latest conversation, and a document or a page opened from the conversation takes the centre while
the card moves to the side."""

from __future__ import annotations

import re
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import httpx
import pytest
from playwright.sync_api import Page, expect

from tests.ui.conftest import UiSession
from tests.ui.test_agent_conversation import ui_agent  # noqa: F401  (the fixture)
from tests.ui.views import FIELD

GOAL = "SYNQ1R01"
WINDOW = ".vt-window"
CONVERSATION = '[data-role="agent-conversation"]'


def _discuss(page: Page, goal_id: str = GOAL) -> None:
    row = page.locator(f'[data-goal-id="{goal_id}"] > .goal-card__row').first
    row.hover()
    row.locator('[data-role="goal-actions-trigger"]').click()
    page.get_by_text("Discuss with agent").click()
    expect(page.locator(f'{WINDOW}[data-window="goal"]')).to_have_count(1)


def _send(page: Page, words: str) -> None:
    answers = page.locator('[data-balloon][data-who="agent"]')
    before = answers.count()
    page.keyboard.press("Control+k")
    page.locator(FIELD).fill(words)
    page.keyboard.press("Enter")
    expect(answers).to_have_count(before + 1, timeout=10000)
    expect(page.locator('[data-role="agent-step"]')).to_have_count(0, timeout=10000)


@pytest.fixture
def pages() -> Iterator[str]:
    """Two local pages: /open frames, /closed forbids framing."""

    class Pages(BaseHTTPRequestHandler):
        def log_message(self, *args: object) -> None:
            pass

        def do_GET(self) -> None:  # noqa: N802
            body = b"<!doctype html><title>A page</title><p>A page to read</p>"
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            if self.path.startswith("/closed"):
                self.send_header("X-Frame-Options", "DENY")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Pages)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()


def test_discuss_lifts_the_goal_into_a_window_under_its_conversation(ui_agent: UiSession) -> None:  # noqa: F811
    page = ui_agent.page
    page.wait_for_selector(f'[data-goal-id="{GOAL}"]')
    _discuss(page)
    window = page.locator(f'{WINDOW}[data-window="goal"]')
    # S3.P2.035: at the top centre, over the board out of focus, the conversation over it and the card stepped back.
    box = window.bounding_box()
    assert box is not None and round(box["y"]) >= 31 and abs(box["x"] + box["width"] / 2 - 1458 / 2) < 12
    expect(page.locator(".app-content--out-of-focus")).to_have_count(1)
    expect(page.locator(CONVERSATION)).to_have_count(1)
    expect(window).to_have_class(re.compile("vt-shadow--back"))
    expect(page.locator(FIELD)).to_have_attribute("aria-label", "Ask about this goal")
    # S3.P2.036: the card in full, with its name.
    expect(window.locator(f'.pblur__live .goal-card[data-goal-id="{GOAL}"]')).to_have_count(1)

    # S3.P2.008: a click on the card brings it in front and sends the conversation into the circle.
    page.mouse.click(box["x"] + 20, box["y"] + box["height"] - 20)
    expect(page.locator(CONVERSATION)).to_have_count(0)
    # S3.P2.005: the card is the window; pointed at, it doesn't lift, and it can't be dragged out of it.
    card = window.locator(f'.pblur__live .goal-card[data-goal-id="{GOAL}"]')
    title = card.locator("> .goal-card__row .goal-card__title-text")
    title.hover()
    page.wait_for_timeout(300)
    expect(card).not_to_have_class(re.compile("goal-card--lifted"))
    at = title.bounding_box()
    page.mouse.move(at["x"] + 10, at["y"] + 8)
    page.mouse.down()
    page.mouse.move(at["x"] + 60, at["y"] + 80, steps=8)
    page.wait_for_timeout(300)
    expect(page.locator('[data-role="drag-overlay"]')).to_have_count(0)
    page.mouse.up()
    # S3.P2.037: Esc brings the goal back to its row and the board into focus.
    page.keyboard.press("Escape")
    expect(page.locator(WINDOW)).to_have_count(0)
    expect(page.locator(".app-content--out-of-focus")).to_have_count(0)


def test_discuss_twice_continues_the_goals_conversation(ui_agent: UiSession) -> None:  # noqa: F811
    """S3.P1.026: the same conversation, with its messages."""
    page = ui_agent.page
    page.wait_for_selector(f'[data-goal-id="{GOAL}"]')
    _discuss(page)
    _send(page, "Remember this one")
    page.keyboard.press("Escape")
    page.keyboard.press("Escape")
    expect(page.locator(WINDOW)).to_have_count(0)
    _discuss(page)
    expect(page.locator('[data-balloon][data-who="you"]', has_text="Remember this one")).to_have_count(1)


def test_a_document_from_the_conversation_takes_the_centre(ui_agent: UiSession) -> None:  # noqa: F811
    """S3.P3.027: the document in the centre, the card at the left with 200 px of it in view; ⌘[ and ⌘] move one."""
    page = ui_agent.page
    doc = httpx.post(
        f"{ui_agent.backend.base_url}/api/docs",
        json={"path": "syn-window/plan.md", "title": "SYN window plan", "body": "# SYN window plan\n\n## Second part\n\nThe words."},
        headers={"Authorization": f"Bearer {ui_agent.backend.token}"},
        timeout=10,
    )
    assert doc.status_code == 201, doc.text
    doc_id = doc.json()["id"]
    page.wait_for_selector(f'[data-goal-id="{GOAL}"]')
    _discuss(page)
    _send(page, f"[say] See [the plan](#doc/{doc_id}#Second%20part).")
    page.locator('[data-balloon][data-who="agent"] a', has_text="the plan").click()
    doc_window = page.locator(f'{WINDOW}[data-window="doc"]')
    expect(doc_window).to_contain_text("SYN window plan")
    expect(doc_window).to_have_class(re.compile("vt-window--front"))
    page.wait_for_timeout(400)
    card = page.locator(f'{WINDOW}[data-window="goal"]').bounding_box()
    assert card is not None and 190 <= card["x"] + card["width"] <= 210, card

    page.keyboard.press("Meta+BracketLeft")
    expect(page.locator(f'{WINDOW}[data-window="goal"]')).to_have_class(re.compile("vt-window--front"))
    page.keyboard.press("Meta+BracketRight")
    expect(doc_window).to_have_class(re.compile("vt-window--front"))


def test_a_page_opens_in_a_window_only_when_it_may(ui_agent: UiSession, pages: str) -> None:  # noqa: F811
    """S3.P4.023, .024: a page that forbids framing says so and offers Chrome; one that allows it loads."""
    page = ui_agent.page
    page.wait_for_selector(f'[data-goal-id="{GOAL}"]')
    _discuss(page)
    _send(page, f"[say] Read [the closed one]({pages}/closed).")
    page.locator('[data-balloon][data-who="agent"] a', has_text="the closed one").click()
    refused = page.locator('[data-role="page-refused"]')
    expect(refused).to_contain_text("This page can't open here")
    expect(refused.locator('[data-role="open-in-chrome"]')).to_have_attribute("href", f"{pages}/closed")
    page.locator(f'{WINDOW}[data-window="page"] [aria-label="Close"]').click()
    _send(page, f"[say] Or [the open one]({pages}/open).")
    page.locator('[data-balloon][data-who="agent"] a', has_text="the open one").click()
    expect(page.locator('[data-role="page-window"][data-state="framed"]')).to_have_count(1)


def test_the_agent_hears_what_changed_on_the_goal(ui_agent: UiSession) -> None:  # noqa: F811
    """S3.P1.028: after a new comment on the goal, the agent's next turn knows it without being told."""
    page = ui_agent.page
    page.wait_for_selector(f'[data-goal-id="{GOAL}"]')
    _discuss(page)
    _send(page, "First look")
    comment = httpx.post(
        f"{ui_agent.backend.base_url}/api/comments",
        json={"goal_id": GOAL, "body": "SYN the venue moved to Friday"},
        headers={"Authorization": f"Bearer {ui_agent.backend.token}"},
        timeout=10,
    )
    assert comment.status_code in (200, 201), comment.text
    _send(page, "[context]")
    expect(page.locator('[data-balloon][data-who="agent"]').last).to_contain_text("SYN the venue moved to Friday")

