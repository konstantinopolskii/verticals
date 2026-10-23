"""The owner continues a morning conversation without losing its history or keeping report-only instructions.

The real gateway drives CLI subprocesses. Only the cloud agents are stand-ins: Codex records JSON-RPC requests,
and Claude is the suite's existing CLI. Model interpretation is checked separately with a real agent on sample data.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import pytest

from tests.static.test_chat_gateway import _chat

SESSION = "00000000-0000-4000-8000-0000000000ab"
TASK = {"id": "SYNMRN01", "title": "Morning report"}


def _talk(chat, gate, words, *, provider="codex", morning=False, expect_error=False):
    session = gate.session(SESSION)
    done = lambda: sum(event["t"] == "done" for _, event in list(session.events))
    before = done()
    settings = {"provider": provider, "permission": "auto-review" if provider == "codex" else "bypassPermissions"}
    if morning:
        settings["sources"] = "connected"
    gate.send(SESSION, words, {"goal": TASK}, settings)
    deadline = time.monotonic() + 15
    with session.cond:
        while done() == before:
            remaining = deadline - time.monotonic()
            assert remaining > 0, "the CLI did not finish its turn"
            session.cond.wait(remaining)
    ends = [event for _, event in session.events if event["t"] == "done"]
    assert ends[-1]["error"] is expect_error, ends[-1]


@pytest.fixture
def codex_gateway(tmp_path, monkeypatch):
    """A local CLI implementing only the protocol, without simulating the requested fix or making board changes."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    cli = bin_dir / "codex"
    cli.write_text(
        f"#!{sys.executable}\n"
        "import json, sys\nfrom pathlib import Path\n"
        "if 'mcp' in sys.argv:\n"
        " print(json.dumps([{'name': 'verticals_desktop', 'enabled': True}]))\n"
        " sys.exit(0)\n"
        "def out(v):\n"
        " print(json.dumps(v), flush=True)\n"
        "for line in sys.stdin:\n"
        " msg=json.loads(line)\n"
        " with open('rpc.jsonl','a') as f: f.write(json.dumps(msg)+'\\n')\n"
        " method=msg.get('method')\n"
        " if 'id' not in msg: continue\n"
        " if method=='thread/inject_items' and Path('reject-injection').exists():\n"
        "  out({'id':msg['id'],'error':{'code':-32601,'message':'Method not found'}})\n"
        "  continue\n"
        " result={}\n"
        " if method in ('thread/start','thread/resume'): result={'thread':{'id':'sample-thread'}}\n"
        " if method=='turn/start': result={'turn':{'id':str(msg['id'])}}\n"
        " out({'id':msg['id'],'result':result})\n"
        " if method=='turn/start':\n"
        "  out({'method':'turn/completed','params':{'turn':{'id':str(msg['id']),'status':'completed'}}})\n"
    )
    cli.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}:{os.environ['PATH']}")
    config = tmp_path / "agent-config"
    config.mkdir()
    (config / "config.toml").write_text("")
    monkeypatch.setenv("CODEX_HOME", str(config))
    chat = _chat()
    state = tmp_path / "state"
    state.mkdir()
    gate = chat.Chat(state, "http://127.0.0.1:9/mcp", "sample-token", watch_every=0)
    try:
        yield chat, gate
    finally:
        gate.shutdown()


def _rpc(gate, method):
    return [msg["params"] for line in (gate.workdir / "rpc.jsonl").read_text().splitlines()
            if (msg := json.loads(line)).get("method") == method]


def test_finish_in_the_same_chat_replaces_morning_instructions_and_preserves_the_agent_thread(codex_gateway):
    chat, gate = codex_gateway
    _talk(chat, gate, "Make my morning report.", morning=True)
    initial = gate.load()[SESSION]["sessionId"]
    _talk(chat, gate, "Доделай по моим комментариям.")

    resumed = _rpc(gate, "thread/resume")
    assert len(resumed) == 1, "a human follow-up must replace the unattended instructions in the same thread"
    assert resumed[0]["threadId"] == initial == gate.load()[SESSION]["sessionId"]
    assert "## This turn: the morning report" not in resumed[0]["developerInstructions"]
    assert resumed[0]["config"]["features.shell_tool"] is True
    assert "## User-directed work" in resumed[0]["developerInstructions"]
    injected = _rpc(gate, "thread/inject_items")
    assert len(injected) == 1, "resuming a stored thread must also replace its model-visible instructions"
    assert injected[0]["threadId"] == initial
    assert injected[0]["items"] == [{"type": "message", "role": "developer", "content": [
        {"type": "input_text", "text": resumed[0]["developerInstructions"]}]}]
    turns = _rpc(gate, "turn/start")
    assert turns[-1]["input"][0]["text"].endswith("Доделай по моим комментариям.")
    assert [t["threadId"] for t in turns] == [initial, initial]
    assert turns[0]["sandboxPolicy"]["type"] == "readOnly"
    assert turns[1]["sandboxPolicy"]["type"] == "workspaceWrite", "the human's selected permission mode is preserved"

    _talk(chat, gate, "Продолжай.")
    assert len(_rpc(gate, "thread/resume")) == 1, "ordinary follow-ups keep their live agent"
    assert len(_rpc(gate, "thread/inject_items")) == 1


def test_another_automatic_report_in_the_same_chat_restores_the_morning_restrictions(codex_gateway):
    chat, gate = codex_gateway
    _talk(chat, gate, "Apply my decisions.")
    _talk(chat, gate, "Make the next morning report.", morning=True)

    resumed = _rpc(gate, "thread/resume")
    assert len(resumed) == 1, "a working chat must not give an unattended report its ordinary tools"
    assert "## This turn: the morning report" in resumed[0]["developerInstructions"]
    assert resumed[0]["config"]["features.shell_tool"] is False
    injected = _rpc(gate, "thread/inject_items")
    assert len(injected) == 1
    assert injected[0]["items"][0]["content"][0]["text"] == resumed[0]["developerInstructions"]
    assert _rpc(gate, "turn/start")[-1]["sandboxPolicy"]["type"] == "readOnly"


def test_a_failed_instruction_refresh_does_not_run_the_command_with_the_old_morning_rules(codex_gateway):
    chat, gate = codex_gateway
    _talk(chat, gate, "Make my morning report.", morning=True)
    original = gate.load()[SESSION]["sessionId"]
    (gate.workdir / "reject-injection").touch()
    _talk(chat, gate, "Доделай.", expect_error=True)
    assert len(_rpc(gate, "turn/start")) == 1, "the work must wait until its instructions can be updated"
    assert gate.load()[SESSION]["sessionId"] == original, "refresh failure must not silently create a new chat"
    done = [event for _, event in gate.session(SESSION).events if event["t"] == "done"][-1]
    assert "instructions" in done["detail"]


@pytest.mark.parametrize("cold", [False, True], ids=["live-chat", "after-restart"])
def test_claude_rebuilds_the_saved_morning_prompt_when_the_owner_continues(tmp_path, cold):
    from tests.static.test_task_sessions_turns import gateway, received, starts

    with gateway(tmp_path) as (chat, gate, workspace):
        _talk(chat, gate, "Make my morning report.", provider="claude", morning=True)
        first_session = gate.load()[SESSION]["sessionId"]
        if not cold:
            _talk(chat, gate, "Доделай по комментариям.", provider="claude")
    if cold:
        with gateway(tmp_path) as (chat, gate, workspace):
            _talk(chat, gate, "Доделай по комментариям.", provider="claude")
    initial, resumed = starts(workspace)
    assert "## This turn: the morning report" in initial[initial.index("--append-system-prompt") + 1]
    assert resumed[resumed.index("--resume") + 1] == first_session
    assert "--system-prompt-snapshot" in resumed, "Claude otherwise keeps the first turn's saved system prompt"
    assert resumed[resumed.index("--system-prompt-snapshot") + 1] == "off"
    assert "## This turn: the morning report" not in resumed[resumed.index("--append-system-prompt") + 1]
    assert received(workspace)[-1].endswith("Доделай по комментариям.")


def test_user_directed_work_reads_task_comments_and_is_separate_from_unattended_collection():
    prompt = _chat().codex_instructions({"provider": "codex"})
    assert "## User-directed work" in prompt
    for requirement in ("comments already saved on the linked tasks", "Do not ask the owner to repeat",
                        "Execute the work", "read back", "same conversation", "affected rows of the same report"):
        assert requirement in prompt
