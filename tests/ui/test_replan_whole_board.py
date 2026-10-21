"""Replan over the whole board (docs/design/replan-whole-board.md), through the real gateway and the fake agent: Replan in one
box sends every carried plan of the board, each under the box it sits in; and Claude's question tool shows its questions one
at a time, their options as suggestions that fill the field, and Enter sends the field's words as the answer."""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

import psycopg
import pytest
from playwright.sync_api import Page, expect

from verticals.core import goals
from verticals.core.board import board

from tests.ui.conftest import F2_OWNER, UiSession
from tests.ui.test_agent_conversation import (  # noqa: F401  (ui_agent is the fixture)
    AGENT_BALLOON, ANSWER, BALLOON, _send, close_the_conversation, ui_agent,
)
from tests.ui.views import FIELD

BOXES = {"day": "Day", "week": "Week", "month": "Month", "quarter": "Quarter", "year": "Year", "decade": "3 years"}
CHOICE = ".circle-field__answer-choice"


def _plan(conn: psycopg.Connection, title: str, vertical: str, day: date, parent: str | None = None) -> str:
    return goals.create(conn, owner=F2_OWNER, title=title, vertical=vertical, anchor_date=day, parent_id=parent).goal.id


def _workspace(tmp_path: Path) -> Path:
    return tmp_path / "desktop-state" / "chat-workspace"


def _context_sent(tmp_path: Path) -> str:
    """The app context of the last message the agent was sent (the fake agent keeps each whole in received.log)."""
    text = json.loads((_workspace(tmp_path) / "received.log").read_text().splitlines()[-1])
    return text.split("<app_context>", 1)[1].split("</app_context>", 1)[0]


def test_replan_in_the_week_box_sends_the_carried_plans_of_every_box(ui_agent: UiSession, tmp_path: Path) -> None:
    """Plans of every scale, missed long enough ago to have carried over; the server puts each in the box it rolls into
    (core/board.py), which depends on the date: in the first month of a quarter no plan carries into Month, so the test
    reads where each sits instead of naming boxes. Replan in the Week box sends all of them, each under its own box."""
    today = date.today()
    monday = today - timedelta(days=today.weekday())
    if monday.day == 1:
        pytest.skip("this week began a month: every plan of last week rolled past the Week box, so it is empty")
    quarter = date(today.year, 3 * ((today.month - 1) // 3) + 1, 1)
    with psycopg.connect(ui_agent.backend.dsn, autocommit=True) as conn:
        guide = _plan(conn, "SYN Write the guide", "year", today)
        made = {
            _plan(conn, "SYN Send the draft", "day", monday - timedelta(days=1), parent=guide): "Write the guide",
            _plan(conn, "SYN Call the printer", "week", monday - timedelta(weeks=5)): None,
            _plan(conn, "SYN Plan the review", "month", (today.replace(day=1) - timedelta(days=40)).replace(day=1)): None,
            _plan(conn, "SYN Ship the first edition", "quarter", (quarter - timedelta(days=100)).replace(day=1)): None,
            _plan(conn, "SYN Read three books", "year", date(today.year - 1, 6, 15)): None,
        }
        shown = board(conn, owner=F2_OWNER, date=today)
    box = {g.id: c.vertical for c in shown.columns for g in c.goals if g.id in made and g.id in shown.ghosts}
    assert set(box) == set(made), "every plan carried over"
    assert "week" in box.values() and len(set(box.values())) >= 3, box
    page = ui_agent.page
    page.goto(f"{ui_agent.base_url}/h/{today.isoformat()}")
    week = page.locator('.pattern-vertical-board__column[data-vertical="week"] [data-role="carried-group"]')
    week.locator('[data-role="replan"]').click()
    expect(page.locator(f'{BALLOON}[data-who="you"]')).to_have_text(
        ["Sort out every plan that carried over: what matters now, and where each goes."])
    expect(page.locator(AGENT_BALLOON)).to_have_count(1, timeout=10000)
    lines = _context_sent(tmp_path).splitlines()
    for goal_id, parent in made.items():
        listed = [line for line in lines if f"(id {goal_id}," in line]
        assert len(listed) == 1 and listed[0].startswith(f"{BOXES[box[goal_id]]} box ("), (goal_id, box[goal_id], listed)
        if parent:
            assert f'(id {goal_id}, day plan for {(monday - timedelta(days=1)).isoformat()}, under "SYN {parent}")' in listed[0]
    assert any(line.startswith("The owner clicked Replan: sort out every plan") for line in lines)


def _suggestions(where):
    return where.locator('[data-role="answer-suggestion"]')


def _pressed(where) -> list[str]:
    """The suggestions whose words are in the field: the filled ones."""
    pills = _suggestions(where)
    return [pills.nth(i).inner_text() for i in range(pills.count()) if pills.nth(i).get_attribute("aria-pressed") == "true"]


def test_a_questions_options_are_suggestions_that_fill_the_field_and_only_enter_answers(
        ui_agent: UiSession, tmp_path: Path) -> None:
    """KK 21 Oct 2026: "Let them simply add text to my field, as autocomplete." A click puts an option's words in the field (the
    guess's mark left out) or takes them out again, several can be picked, and only Enter sends the field's words: the answer to
    the question, after which the next one shows. An empty field sends nothing."""
    page = ui_agent.page
    page.wait_for_selector(".goal-card__row")
    _send(page, "Sort it out [question]")
    ask = page.locator('[data-role="agent-ask"]')
    expect(ask).to_contain_text("What matters most this week?", timeout=10000)
    expect(_suggestions(ask)).to_have_text(["The guide (my guess)", "The launch", "Rest"])
    expect(ask.locator(".agent-balloon__choice")).to_have_count(0)
    expect(page.locator(FIELD)).to_have_attribute("aria-label", "Your answer")
    # With the conversation away, the field holds the question and its suggestions, outlined.
    close_the_conversation(page)
    field = page.locator(ANSWER)
    expect(field).to_contain_text("What matters most this week?")
    expect(field).to_contain_text("9 plans carried over")
    expect(_suggestions(field)).to_have_text(["The guide (my guess)", "The launch", "Rest"])
    expect(_suggestions(field).first).to_have_css("background-color", "rgba(0, 0, 0, 0)")
    expect(field.locator(CHOICE)).to_have_count(0)
    # A click: the words go in the field, which takes the caret; the conversation shows the question with that one filled.
    _suggestions(field).filter(has_text="The launch").click()
    expect(page.locator(FIELD)).to_have_value("The launch")
    expect(page.locator(FIELD)).to_be_focused()
    ask = page.locator('[data-role="agent-ask"]')
    expect(_suggestions(ask).filter(has_text="The launch")).to_have_attribute("aria-pressed", "true")
    expect(_suggestions(ask).filter(has_text="The launch")).to_have_css("background-color", "rgb(255, 255, 255)")
    # Several, then one taken out again; the guess goes in without its mark.
    _suggestions(ask).filter(has_text="Rest").click()
    expect(page.locator(FIELD)).to_have_value("The launch, Rest")
    assert _pressed(ask) == ["The launch", "Rest"]
    _suggestions(ask).filter(has_text="The launch").click()
    expect(page.locator(FIELD)).to_have_value("Rest")
    _suggestions(ask).filter(has_text="The guide").click()
    expect(page.locator(FIELD)).to_have_value("Rest, The guide")
    expect(page.locator(FIELD)).to_be_focused()
    assert _pressed(ask) == ["The guide (my guess)", "Rest"]
    assert not (_workspace(tmp_path) / "decisions.log").exists(), "a click answers nothing"
    # Enter answers with the field's words, and the next question shows.
    page.keyboard.press("Enter")
    expect(ask).to_contain_text("Which stream went quiet?", timeout=10000)
    expect(_suggestions(ask)).to_have_text(["Reading (my guess)", "Sport"])
    expect(page.locator(FIELD)).to_have_value("")
    assert _pressed(ask) == []
    # An empty field sends nothing.
    page.keyboard.press("Control+k")
    page.keyboard.press("Enter")
    page.wait_for_timeout(500)
    expect(ask).to_contain_text("Which stream went quiet?")
    _send(page, "Music, mostly")
    expect(page.locator(AGENT_BALLOON).last).to_contain_text(
        'Answers: "What matters most this week?"="Rest, The guide", "Which stream went quiet?"="Music, mostly".', timeout=10000)
    expect(page.locator(f'{BALLOON}[data-who="you"]')).to_have_text(["Sort it out [question]", "Rest, The guide", "Music, mostly"])
    (decision,) = [json.loads(line) for line in (_workspace(tmp_path) / "decisions.log").read_text().splitlines()]
    assert decision["behavior"] == "allow"
    assert decision["updatedInput"]["answers"] == {"What matters most this week?": "Rest, The guide",
                                                   "Which stream went quiet?": "Music, mostly"}
    assert [q["question"] for q in decision["updatedInput"]["questions"]] == ["What matters most this week?",
                                                                              "Which stream went quiet?"]
    received = [json.loads(line) for line in (_workspace(tmp_path) / "received.log").read_text().splitlines()]
    assert len(received) == 1, "the answers went to the questions, not to the agent as new messages"


def test_a_permission_ask_keeps_its_buttons(ui_agent: UiSession) -> None:
    """Only a question's options are suggestions: an ask to use a tool keeps its two buttons, which answer at once."""
    page = ui_agent.page
    page.wait_for_selector(".goal-card__row")
    _send(page, "Change it [ask]")
    ask = page.locator('[data-role="agent-ask"]')
    expect(ask.locator(".agent-balloon__choice")).to_have_text(["Allow once", "Decline"], timeout=10000)
    expect(_suggestions(ask)).to_have_count(0)
    expect(page.locator(FIELD)).not_to_have_attribute("aria-label", "Your answer")
    close_the_conversation(page)
    field = page.locator(ANSWER)
    expect(field.locator(CHOICE)).to_have_text(["Allow once", "Decline"])
    expect(field.locator(CHOICE).first).to_have_css("background-color", "rgb(255, 255, 255)")
    expect(_suggestions(field)).to_have_count(0)
    field.locator(CHOICE, has_text="Allow once").click()
    expect(page.locator(ANSWER)).to_contain_text("Done: Change it", timeout=10000)
