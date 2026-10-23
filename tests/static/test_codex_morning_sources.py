"""Approved source readers reach Codex's actual launch; other tools stay isolated."""

import json
import logging
import threading
from types import SimpleNamespace

import pytest

from tests.static.test_chat_gateway import _chat


def launch(tmp_path, monkeypatch, *, connected=True, approved=True, escape=False):
    module = _chat()
    home = tmp_path / "codex"
    home.mkdir()
    (home / "config.toml").write_text(
        '[mcp_servers.work_chat]\ncommand="reader"\n'
        '[mcp_servers.unrelated]\ncommand="other"\n'
    )
    monkeypatch.setenv("CODEX_HOME", str(home))
    checked, launched = [], []

    def cli_run(argv, **kwargs):
        checked.append(argv)
        enabled = {"verticals_desktop"}
        if "mcp_servers.work_chat.enabled=true" in argv:
            enabled.add("work_chat")
        if escape:
            enabled.add("unrelated")
        return SimpleNamespace(returncode=0, stdout=json.dumps(
            [{"name": name, "enabled": True} for name in enabled]))

    class Process:
        def __init__(self, argv, *args):
            launched.append(argv)

        def request(self, *args, **kwargs):
            return {"thread": {"id": "synthetic-thread"}}

        def notify(self, *args):
            pass

    monkeypatch.setattr(module, "which", lambda name: name)
    monkeypatch.setattr(module.subprocess, "run", cli_run)
    monkeypatch.setattr(module, "RpcProcess", Process)
    settings = {"provider": "codex", **({"sources": "connected"} if connected else {})}
    session = SimpleNamespace(id="synthetic-session", emit=lambda event: None, settings=settings)
    host = SimpleNamespace(
        load=lambda: {}, lock=threading.Lock(), log=logging.getLogger(__name__),
        workdir=tmp_path, state_dir=tmp_path, mcp_url="http://127.0.0.1:1/mcp", token="synthetic",
        api=lambda *args: {"sources": [
            {"approved": approved, "needs_approval": not approved,
             "title": "Work", "reads": ["mcp__work_chat__read_history"]},
            {"approved": False, "needs_approval": True,
             "reads": ["mcp__unrelated__get_messages"]},
        ]},
    )
    return module, lambda: module.CodexAgent(host, session, settings, None), checked, launched


def test_morning_launch_exposes_only_the_approved_source_tool(tmp_path, monkeypatch):
    _, start, checked, launched = launch(tmp_path, monkeypatch)
    start()
    args = launched[0]
    assert "mcp_servers.work_chat.enabled=true" in args
    assert 'mcp_servers.work_chat.enabled_tools=["read_history"]' in args
    assert 'mcp_servers.work_chat.tools.read_history.approval_mode="approve"' in args
    assert "mcp_servers.unrelated.enabled=false" in args
    assert "mcp_servers.work_chat.enabled=true" in checked[0]


@pytest.mark.parametrize("connected,approved", [(True, False), (False, True)])
def test_unapproved_or_non_morning_launch_keeps_external_servers_off(tmp_path, monkeypatch, connected, approved):
    _, start, _, launched = launch(tmp_path, monkeypatch, connected=connected, approved=approved)
    start()
    assert "mcp_servers.work_chat.enabled=false" in launched[0]
    assert "mcp_servers.unrelated.enabled=false" in launched[0]


def test_morning_launch_refuses_an_unrelated_server_that_escapes_isolation(tmp_path, monkeypatch):
    module, start, _, launched = launch(tmp_path, monkeypatch, escape=True)
    with pytest.raises(module.ChatError, match="isolate"):
        start()
    assert launched == []
