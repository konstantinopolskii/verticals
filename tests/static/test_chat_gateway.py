"""The desktop chat gateway's own rules for the turns the app starts (Inbox and Documents redesign, final page): the
morning report reads the owner's other tools but never changes anything there, and Replan reaches the agent with the
plans it was clicked on."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _chat():
    spec = importlib.util.spec_from_file_location("verticals_desktop_chat", ROOT / "desktop" / "chat" / "chat.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_the_morning_turn_reads_other_tools_and_changes_nothing_there() -> None:
    chat = _chat()
    for tool in ("mcp__google-calendar__list-events", "mcp__telethon__fetch_history", "mcp__coin-prod__search_base",
                 "mcp__mail__searchThreads", "mcp__coin-account__get_transcript"):
        assert chat.reads_only(tool), tool
    for tool in ("mcp__telethon__send_reply", "mcp__telethon__mark_read", "mcp__google-calendar__create-event",
                 "mcp__google-calendar__delete-event", "mcp__telethon__react", "mcp__mail__createDraft"):
        assert not chat.reads_only(tool), tool


def test_the_morning_prompt_carries_the_skill_and_its_two_references() -> None:
    prompt = _chat().MORNING_PROMPT
    assert prompt.startswith("## This turn: the morning report")
    assert "reports/morning/<YYYY-MM-DD>.md" in prompt
    assert "## Reference: source reconciliation" in prompt and "## Reference: report contract" in prompt


def test_replan_reaches_the_agent_with_its_plans_and_how_to_write_the_document() -> None:
    chat = _chat()
    context = chat.format_context({"today": "2026-10-07", "replan": {
        "column": "year", "plans": [{"id": "SYNPLN01", "title": "Plan to sort"}, {"id": "SYNPLN02", "title": "Another"}]}})
    assert 'The owner clicked Replan on 2 plans that carried over into year: "Plan to sort" (id SYNPLN01)' in context
    assert "replan/<today>.md" in context and "Goal | Summary | Next step | Your comment" in context
    assert "Replan" not in chat.format_context({"today": "2026-10-07"})
