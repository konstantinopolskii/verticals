"""The desktop chat gateway's own rules for the turns the app starts (Inbox and Documents redesign, final page): the
morning report reads the owner's other tools but never changes anything there, and Replan reaches the agent with the
plans it was clicked on. Also what a Claude turn may reach under each permission mode."""

from __future__ import annotations

import importlib.util
import sys
import types
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


class _Proc:
    def __init__(self, args, cwd, env, handle, exited):
        self.args, self.sent = args, []

    def send(self, message):
        self.sent.append(message)


class _Session:
    def __init__(self):
        self.asked = []

    def ask(self, agent, key, title, body, options):
        self.asked.append(title)

    def emit(self, event):
        pass


def _claude(settings):
    chat = _chat()
    chat.JsonProcess, chat.which = _Proc, lambda provider: "claude"
    session = _Session()
    host = types.SimpleNamespace(claude_mcp=Path("mcp.json"), workdir=Path("."))
    return chat.ClaudeAgent(host, session, settings, None), session


def _bash(agent):
    agent.handle({"type": "control_request", "request_id": "r1",
                  "request": {"subtype": "can_use_tool", "tool_name": "Bash", "input": {"command": "ls"}}})


def test_verticals_only_is_the_default_and_keeps_claude_to_the_board() -> None:
    assert _chat().clean_settings({})["permission"] == "board"
    agent, session = _claude({"permission": "board"})
    args = agent.proc.args
    assert args[args.index("--tools") + 1] == "" and "--strict-mcp-config" in args and "--add-dir" not in args
    assert args[args.index("--permission-mode") + 1] == "manual"
    _bash(agent)
    assert not session.asked and agent.proc.sent[-1]["response"]["response"]["behavior"] == "deny"


def test_another_mode_gives_claude_its_tools_and_asks_in_the_chat() -> None:
    agent, session = _claude({"permission": "manual"})
    args = agent.proc.args
    assert "--tools" not in args and "--strict-mcp-config" not in args
    assert args[args.index("--add-dir") + 1] == str(Path.home())
    assert "Claude Code's own tools" in args[args.index("--append-system-prompt") + 1]
    _bash(agent)
    assert session.asked == ["Allow Claude to use Bash?"]


def test_the_morning_turn_keeps_its_own_rules_in_any_mode() -> None:
    agent, session = _claude({"permission": "bypassPermissions", "sources": "connected"})
    args = agent.proc.args
    assert args[args.index("--tools") + 1] == "" and "--add-dir" not in args
    _bash(agent)
    assert not session.asked and agent.proc.sent[-1]["response"]["response"]["behavior"] == "deny"
