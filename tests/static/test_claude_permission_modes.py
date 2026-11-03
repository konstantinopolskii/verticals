"""The adapter translates the UI's ask-first choice into Claude Code's CLI mode."""

import pytest

from tests.static.test_chat_gateway import _claude, _flag, _tool


@pytest.mark.parametrize("settings", [
    {"permission": "board"},
    {"permission": "manual"},
    {"permission": "board", "sources": "connected"},
])
def test_ask_first_launch_uses_a_supported_cli_mode(settings):
    agent, _ = _claude(settings)
    assert _flag(agent, "--permission-mode") == "default"


def test_asking_mode_still_sends_unapproved_tools_to_the_owner():
    agent, session = _claude({"permission": "manual"})
    _tool(agent, "Bash", {"command": "echo synthetic"})
    assert session.asked == ["Allow Claude to use Bash?"]


def test_morning_mode_still_refuses_a_tool_outside_approved_sources():
    agent, session = _claude({"sources": "connected"})
    _tool(agent, "mcp__unapproved__read_history")
    assert session.asked == ["Allow Claude to use mcp__unapproved__read_history?"]


def test_streaming_launch_uses_the_stdio_permission_transport():
    agent, _ = _claude({"sources": "connected"})
    assert _flag(agent, "--permission-prompt-tool") == "stdio"
    assert "--permission-prompts" not in agent.proc.args
