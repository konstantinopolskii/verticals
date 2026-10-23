"""The desktop chat gateway's own rules for the turns the app starts (Inbox and Documents redesign, final page): the
morning report reads the owner's other tools but never changes anything there, and Replan reaches the agent with the
plans it was clicked on. Also what a Claude turn may reach under each permission mode."""

from __future__ import annotations

import importlib.util
import json
import os
import sys
import time
import types
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _chat():
    spec = importlib.util.spec_from_file_location("verticals_desktop_chat", ROOT / "desktop" / "chat" / "chat.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_no_tool_is_judged_by_its_name_any_more() -> None:
    """The morning turn used to run a tool of another server when its name began with a reading verb: a chat server's
    `list_messages` or `unread_summary` was declined, and a write called `get_and_send` would have run. A source's document
    now names the tools that read it, and nothing else outside Verticals runs without the reader."""
    chat = _chat()
    assert not hasattr(chat, "reads_only") and not hasattr(chat, "READ_VERBS")


def test_the_morning_prompt_carries_the_skill_and_its_three_references() -> None:
    prompt = _chat().MORNING_PROMPT
    assert prompt.startswith("## This turn: the morning report")
    assert "reports/morning/<YYYY-MM-DD>.md" in prompt
    for reference in ("source reconciliation", "report contract", "the second check"):
        assert f"## Reference: {reference}" in prompt, reference


def test_replan_reaches_the_agent_with_its_plans_and_how_to_write_the_document() -> None:
    chat = _chat()
    context = chat.format_context({"today": "2026-10-07", "replan": {
        "column": "year", "plans": [{"id": "SYNPLN01", "title": "Plan to sort"}, {"id": "SYNPLN02", "title": "Another"}]}})
    assert 'The owner clicked Replan on 2 plans that carried over into year: "Plan to sort" (id SYNPLN01)' in context
    assert "replan/<today>.md" in context and "Goal | Summary | Next step | Your comment" in context
    assert "Replan" not in chat.format_context({"today": "2026-10-07"})


class _Proc:
    def __init__(self, args, cwd, env, handle, exited):
        self.args, self.env, self.sent = args, env, []

    def send(self, message):
        self.sent.append(message)


class _Session:
    id = "00000000-0000-4000-8000-000000000001"

    def __init__(self):
        self.asked = []

    def ask(self, agent, key, title, body, options, tool=None, tool_input=None):
        self.asked.append(title)
        self.write = (tool, tool_input)

    def emit(self, event):
        pass


def _claude(settings, sources=None, role=None):
    """A Claude agent started the way a message starts it: its settings come through the gateway's own clean. `sources` is what
    the server lists when the morning turn asks for the sources' tools; `role` seats the second agent, which the flow does."""
    chat = _chat()
    chat.JsonProcess, chat.which = _Proc, lambda provider: "claude"
    session = _Session()

    def api(method, path, body=None, timeout=20):
        if sources is None:
            raise chat.ChatError("no server")
        assert (method, path) == ("GET", "/api/sources")
        return {"sources": sources}

    host = types.SimpleNamespace(claude_config=lambda session_id=None: Path("mcp.json"), workdir=Path("."), api=api, log=None,
                                 touches_memory=lambda tool, args: False)
    cleaned = chat.clean_settings(settings)
    return chat.ClaudeAgent(host, session, {**cleaned, **({"role": role} if role else {})}, None), session


def _system_prompt(agent) -> str:
    """The prompt Claude is told, inline or, where the system caps a command line, in the file it is handed."""
    args = agent.proc.args
    if "--append-system-prompt" in args:
        return args[args.index("--append-system-prompt") + 1]
    return Path(args[args.index("--append-system-prompt-file") + 1]).read_text(encoding="utf-8")


def test_an_ask_for_a_verticals_write_carries_the_write_so_the_card_can_say_what_changes() -> None:
    """Fix 6 (docs/design/agent-fixes.md): the app drew only the tool's name; the ask now carries the write as the agent
    called it, for web lib/askDetail.ts. A tool of another server or a shell command carries its own name and inputs too."""
    agent, session = _claude({"permission": "manual"})
    _tool(agent, "mcp__verticals__schedule", {"id": "SYN00001", "vertical": "day", "anchor_date": "2026-10-12"})
    assert session.write == ("schedule", {"id": "SYN00001", "vertical": "day", "anchor_date": "2026-10-12"})
    _tool(agent, "Bash", {"command": "ls"})
    assert session.write == ("Bash", {"command": "ls"})


def _tool(agent, name, tool_input=None):
    agent.handle({"type": "control_request", "request_id": f"r-{name}",
                  "request": {"subtype": "can_use_tool", "tool_name": name, "input": tool_input or {}}})


def _bash(agent):
    _tool(agent, "Bash", {"command": "ls"})


def _flag(agent, name):
    args = agent.proc.args
    return args[args.index(name) + 1]


def _decision(agent):
    return agent.proc.sent[-1]["response"]["response"]["behavior"]


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
    assert "Claude Code's own tools" in _system_prompt(agent)
    _bash(agent)
    assert session.asked == ["Allow Claude to use Bash?"]


def test_the_morning_turn_keeps_its_own_rules_in_any_mode() -> None:
    agent, session = _claude({"permission": "bypassPermissions", "sources": "connected"})
    args = agent.proc.args
    assert args[args.index("--tools") + 1] == "" and "--add-dir" not in args
    _bash(agent)  # it has no shell, files or web: a request for one is declined, and nobody is asked about it
    assert not session.asked and agent.proc.sent[-1]["response"]["response"]["behavior"] == "deny"


def test_the_settings_clean_lets_the_morning_turns_sources_through() -> None:
    """Fix 1 (docs/design/agent-fixes.md): the clean dropped `sources`, so no morning turn ever had its own rules."""
    chat = _chat()
    assert chat.clean_settings({"sources": "connected"})["sources"] == "connected"
    for other in ("everything", "", None, True, ["connected"]):
        assert "sources" not in chat.clean_settings({"sources": other}), other
    assert "sources" not in chat.clean_settings({})


def test_the_morning_guide_reaches_the_agent_the_app_asks() -> None:
    """Fix 1: the settings the app sends for the morning ask (web lib/morning.ts) give that turn the morning guide, with
    the report contract; any other turn keeps the board prompt."""
    agent, _ = _claude({"permission": "manual", "sources": "connected"})
    prompt = _system_prompt(agent)
    assert "## This turn: the morning report" in prompt and "## Reference: report contract" in prompt
    assert "## This turn: the morning report" not in _system_prompt(_claude({"permission": "manual"})[0])


def test_codex_gets_the_morning_guide_in_the_same_turn() -> None:
    """Fix 1: the morning turn is asked of whichever agent is chosen, so Codex gets the guide too, under its own server name."""
    chat = _chat()
    morning = chat.codex_instructions(chat.clean_settings({"provider": "codex", "sources": "connected"}))
    assert "## This turn: the morning report" in morning and 'server "verticals_desktop"' in morning
    assert "## This turn: the morning report" not in chat.codex_instructions(chat.clean_settings({"provider": "codex"}))


def test_codex_as_the_second_agent_gets_the_check_prompt_not_the_writers_and_only_reads() -> None:
    """Codex is not on the machines these tests run on, so this is all that is pinned of it as the second agent: what it is told
    and the mode it runs in (docs/design/morning-quality.md)."""
    chat = _chat()
    settings = {**chat.clean_settings({"provider": "codex", "sources": "connected"}), "role": chat.CHECKER}
    text = chat.codex_instructions(settings)
    assert "## This turn: the second check" in text and "## This turn: the morning report" not in text
    assert 'server "verticals_desktop"' in text
    assert chat.codex_mode(settings) == "read-only"


def test_the_app_ships_every_skill_the_chat_reads() -> None:
    """Fix 1: the chat reads the operator skill and, for the morning turn, the morning-report skill from the folder it
    runs in; the app's bundle copies both, or the guide silently shrinks to the few lines of prompt-morning.md."""
    spec = importlib.util.spec_from_file_location("verticals_bundle", ROOT / "desktop" / "macos" / "bundle.py")
    assert spec and spec.loader
    bundle = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(bundle)
    chat = _chat()
    for skill in (chat.SKILL, chat.MORNING_SKILL):
        assert skill.name in bundle.SKILLS, skill.name
        assert (ROOT / ".agents" / "skills" / skill.name / "SKILL.md").is_file()


def test_the_morning_turn_asks_first_whatever_mode_the_chat_is_in() -> None:
    """Fix 4: a chat set to "Bypass permissions" or "Auto" made its own decisions for every tool, so the morning turn,
    which nobody watches, could send or delete in the owner's other tools. In the morning turn the mode is always the
    ask-first one, and each tool of another server comes to the gateway to be judged."""
    for mode in ("manual", "acceptEdits", "plan", "auto", "dontAsk", "bypassPermissions", "board"):
        agent, _ = _claude({"permission": mode, "sources": "connected"})
        assert _flag(agent, "--permission-mode") == "manual", mode
        assert _flag(agent, "--tools") == "" and "--add-dir" not in agent.proc.args, mode
    # Any other turn keeps the mode the owner chose.
    assert _flag(_claude({"permission": "bypassPermissions"})[0], "--permission-mode") == "bypassPermissions"


TEAM_CHAT = ["mcp__chat__list_messages", "mcp__chat__unread_summary"]
SOURCES = [
    {"title": "Team chat", "approved": True, "needs_approval": False, "reads": TEAM_CHAT},
    {"title": "Mail", "approved": True, "needs_approval": False, "reads": ["mcp__mail__search_mail", "mcp__mail__get_mail"]},
    {"title": "Calendar", "approved": False, "needs_approval": True, "reads": ["mcp__calendar__list_events"]},
    {"title": "Sneaky", "approved": True, "needs_approval": False,
     "reads": ["mcp__verticals__delete", "mcp__verticals-desktop__schedule", "not a tool", 7, None]},
]


def test_the_morning_turn_calls_the_tools_its_sources_declare_and_asks_for_every_other() -> None:
    """docs/design/morning-quality.md: a tool was judged by its name (a chat server's `list_messages` was declined). Each source's
    document now declares the tools that read it, inside the check the owner approved; the turn allows exactly those on the
    command line and asks the reader about any other, and about nothing it was already told to allow."""
    agent, session = _claude({"permission": "bypassPermissions", "sources": "connected"}, sources=SOURCES)
    allowed = _flag(agent, "--allowedTools").split(",")
    for tool in (*TEAM_CHAT, "mcp__mail__search_mail", "mcp__mail__get_mail"):
        assert tool in allowed, tool
    # A source whose check the owner has not approved declares nothing; Verticals' own tools cannot be declared; junk is junk.
    for tool in ("mcp__calendar__list_events", "mcp__verticals__delete", "mcp__verticals-desktop__schedule", "not a tool"):
        assert tool not in allowed, tool
    assert agent.reads["mcp__chat__list_messages"] == "Team chat"
    # Anything else outside Verticals comes to the reader, a reading name or not.
    for other in ("mcp__calendar__list_events", "mcp__chat__send_message", "mcp__chat__get_everything_and_send",
                  "mcp__mail__createDraft"):
        _tool(agent, other, {"to": "x"})
        assert session.asked[-1] == f"Allow Claude to use {other}?", other
        assert session.write == (other, {"to": "x"})
    assert len(session.asked) == 4 and not agent.proc.sent[2:]  # no decision was made for the reader


def test_the_morning_turn_writes_in_verticals_only_what_the_report_needs() -> None:
    """Fix 4, as docs/design/morning-quality.md leaves it: the report's own writes and the evidence of what it closes run by
    themselves; closing a task is told apart by what it is called with; any other write is asked of the reader."""
    agent, session = _claude({"permission": "bypassPermissions", "sources": "connected"}, sources=SOURCES)
    allowed = _flag(agent, "--allowedTools").split(",")
    for tool in ("doc_create", "doc_save", "doc_link", "evidence_update", "board", "doc_get", "sources"):
        assert f"mcp__verticals__{tool}" in allowed, tool
    # The report's task is the server's (core/morning.py): the agent neither makes it nor moves it without asking.
    for tool in ("create", "schedule", "delete", "update", "reparent", "doc_delete"):
        assert f"mcp__verticals__{tool}" not in allowed, tool
    _tool(agent, "mcp__verticals__update", {"id": "SYN00001", "done": True})
    assert _decision(agent) == "allow"
    _tool(agent, "mcp__verticals__update", {"ids": ["SYN00001", "SYN00002"], "done": True, "client_token": "t"})
    assert _decision(agent) == "allow" and not session.asked
    for call in ({"id": "SYN00001", "done": True, "title": "A new name"}, {"id": "SYN00001", "done": False},
                 {"id": "SYN00001", "ids": ["SYN00002"], "done": True}, {"id": "SYN00001", "body": "x"}, {"done": True}):
        _tool(agent, "mcp__verticals__update", call)
    assert session.asked == ["Allow Claude to use update?"] * 5
    _tool(agent, "mcp__verticals__delete", {"id": "SYN00001"})
    assert session.asked[-1] == "Allow Claude to use delete?" and len(session.asked) == 6


def test_the_morning_turn_keeps_the_owners_settings_and_asks_the_gateway_about_every_mcp_tool() -> None:
    """The owner's own Claude Code settings may allow a tool outright, and an allowed tool never comes to this gateway to be
    judged. Cutting the settings off (`--setting-sources`) would also cut the owner's own servers, the sources' tools, so the
    morning turns keep them and carry one `ask` rule for every MCP tool on the command line, where `--settings` ranks above the
    user settings. The CLI evaluates deny, then ask, then allow. The owner's other turns carry no rule."""
    for mode in ("board", "manual", "bypassPermissions", "auto"):
        morning, _ = _claude({"permission": mode, "sources": "connected"}, sources=[])
        assert "--setting-sources" not in morning.proc.args and "--strict-mcp-config" not in morning.proc.args, mode
        assert json.loads(_flag(morning, "--settings"))["permissions"] == {"ask": ["mcp__*"]}, mode
        assert "permissions" not in json.loads(_flag(_claude({"permission": mode})[0], "--settings")), mode
    second, _ = _claude({"sources": "connected"}, sources=[], role="checker")
    assert "--setting-sources" not in second.proc.args
    assert json.loads(_flag(second, "--settings"))["permissions"] == {"ask": ["mcp__*"]}
    # The rule asks, it does not allow: nothing is passed to run unasked but what the command line already lists.
    assert "allow" not in json.loads(_flag(second, "--settings"))["permissions"]


def test_a_whole_days_board_reaches_an_agent_that_cannot_open_files_in_one_answer() -> None:
    """Over Claude Code's default cap on one tool's answer the CLI writes the answer to a file, which a seat with no file
    tools cannot read. Every seat takes a larger cap, unless the owner set their own."""
    owners = os.environ.pop("MAX_MCP_OUTPUT_TOKENS", None)
    try:
        for settings, role in (({}, None), ({"sources": "connected"}, None), ({"sources": "connected"}, "checker")):
            agent, _ = _claude(settings, sources=[], role=role)
            assert agent.proc.env["MAX_MCP_OUTPUT_TOKENS"] == "100000", (settings, role)
        os.environ["MAX_MCP_OUTPUT_TOKENS"] = "300000"
        assert _claude({"sources": "connected"}, sources=[])[0].proc.env["MAX_MCP_OUTPUT_TOKENS"] == "300000"
    finally:
        os.environ.pop("MAX_MCP_OUTPUT_TOKENS", None)
        if owners is not None:
            os.environ["MAX_MCP_OUTPUT_TOKENS"] = owners


def test_every_mcp_tool_comes_to_the_gateway_and_a_declared_one_runs_with_no_question_to_the_reader() -> None:
    """With the ask rule the CLI puts a declared tool to the gateway too. The tools the approved sources declare, Verticals'
    reading tools and the report's own writes run with no question; any other tool is asked of the reader."""
    agent, session = _claude({"permission": "bypassPermissions", "sources": "connected"}, sources=SOURCES)
    for tool in (*TEAM_CHAT, "mcp__mail__search_mail", "mcp__mail__get_mail", "mcp__verticals__board", "mcp__verticals__doc_get",
                 "mcp__verticals__sources", "mcp__verticals__doc_create", "mcp__verticals__doc_save", "mcp__verticals__doc_link",
                 "mcp__verticals__evidence_update"):
        _tool(agent, tool)
        assert _decision(agent) == "allow", tool
    assert not session.asked
    # A tool no source lists, a source the reader has not approved, and a write beyond the report come to the reader.
    for tool, title in (("mcp__chat__send_message", "mcp__chat__send_message"), ("mcp__calendar__list_events", "mcp__calendar__list_events"),
                        ("mcp__verticals__create", "create"), ("mcp__verticals__schedule", "schedule")):
        _tool(agent, tool)
        assert session.asked[-1] == f"Allow Claude to use {title}?", tool
    assert len(session.asked) == 4


def test_the_second_agent_reads_what_the_sources_declare_and_is_declined_for_everything_else() -> None:
    """It writes nothing and has nobody to ask: no Verticals write is on its command line, a close or any other change is
    declined, a tool no source lists is declined and not put to the reader."""
    agent, session = _claude({"permission": "manual", "sources": "connected"}, sources=SOURCES, role="checker")
    allowed = _flag(agent, "--allowedTools").split(",")
    for tool in ("board", "goal", "doc_get", "sources", *TEAM_CHAT):
        assert tool in allowed or f"mcp__verticals__{tool}" in allowed, tool
    for tool in ("doc_create", "doc_save", "doc_link", "evidence_update"):
        assert f"mcp__verticals__{tool}" not in allowed, tool
    # The CLI asks about every MCP tool: what is on its command line runs, the rest is declined.
    for name in (*TEAM_CHAT, "mcp__verticals__board", "mcp__verticals__doc_get", "mcp__verticals__sources"):
        _tool(agent, name)
        assert _decision(agent) == "allow", name
    for name, call in (("mcp__verticals__update", {"id": "SYN00001", "done": True}), ("mcp__verticals__doc_save", {"id": "x"}),
                       ("mcp__chat__send_message", {}), ("mcp__calendar__list_events", {})):
        _tool(agent, name, call)
        assert _decision(agent) == "deny", name
    assert not session.asked
    prompt = _system_prompt(agent)
    assert "## This turn: the second check of the morning report" in prompt and "## This turn: the morning report" not in prompt
    assert "## Reference: the second check" in prompt and "## Reference: report contract" in prompt


def test_a_source_list_that_cannot_be_read_declares_nothing_and_the_turn_still_starts() -> None:
    agent, session = _claude({"sources": "connected"})  # the host's API raises
    allowed = _flag(agent, "--allowedTools").split(",")
    assert agent.reads == {} and all(tool.startswith("mcp__verticals__") for tool in allowed)
    _tool(agent, "mcp__chat__list_messages")
    assert session.asked == ["Allow Claude to use mcp__chat__list_messages?"]


def test_a_declared_tool_names_its_source_in_the_step_the_field_shows() -> None:
    agent, session = _claude({"sources": "connected"}, sources=SOURCES)
    events = []
    session.emit = events.append
    agent.handle({"type": "assistant", "message": {"content": [
        {"type": "tool_use", "id": "t1", "name": "mcp__chat__list_messages", "input": {}},
        {"type": "tool_use", "id": "t2", "name": "mcp__verticals__doc_get", "input": {}},
        {"type": "tool_use", "id": "t3", "name": "mcp__chat__send_message", "input": {}}]}})
    tools = [event for event in events if event["t"] == "tool"]
    assert [event.get("step") for event in tools] == ["Reading Team chat", None, None]


def test_the_morning_turn_of_codex_reads_whatever_mode_the_chat_is_in() -> None:
    """Fix 4, Codex: its sandbox is read-only in the morning turn (it can reach only Verticals, and its files not at all)."""
    chat = _chat()
    for mode in ("full-access", "auto-review", "default", "read-only"):
        settings = chat.clean_settings({"provider": "codex", "permission": mode, "sources": "connected"})
        assert chat.codex_mode(settings) == "read-only", mode
        assert chat.codex_policy(chat.codex_mode(settings), "/work")["sandboxPolicy"]["type"] == "readOnly", mode
    assert chat.codex_mode(chat.clean_settings({"provider": "codex", "permission": "full-access"})) == "full-access"
    assert chat.codex_mode(chat.clean_settings({"provider": "codex"})) == "auto-review"


def test_the_agents_instructions_agree_with_themselves() -> None:
    """Fix 5 (docs/design/agent-fixes.md): one length in every turn, goals by title and not by ID, and the board as it is."""
    prompt = _chat().PROMPT
    # One length: one or two short paragraphs, and a document for anything longer.
    assert "one or two short paragraphs" in prompt and "document" in prompt.split("one or two short paragraphs", 1)[1][:200]
    # Goals by title: nothing tells the agent to report IDs.
    assert "by title" in prompt and "exact IDs" not in prompt and "Report exact" not in prompt
    # Seven columns, not a ladder of five rungs.
    assert "Life → Year → Quarter → Week → Day" not in prompt
    for column in ("Life", "3 years", "Year", "Quarter", "Month", "Week", "Day", "Inbox"):
        assert column in prompt.split("The user talks to you", 1)[0], column


def test_the_text_the_owner_selected_reaches_the_agent_in_its_context() -> None:
    """Fix 5: the prompt promises "any text they selected", so the context carries it, cut at 2000 characters."""
    chat = _chat()
    context = chat.format_context({"today": "2026-10-11", "selection": "The second paragraph of the plan"})
    assert "Selected text: The second paragraph of the plan" in context
    assert len(chat.format_context({"today": "2026-10-11", "selection": "x" * 5000}).split("Selected text: ")[1]) == 2000
    assert "Selected text" not in chat.format_context({"today": "2026-10-11"})


SESSION = "5d2c3c3e-1b1a-4c8e-9e1f-0a6f3e3c9b01"


def test_the_gateway_keeps_a_log_of_the_agents_side_with_nothing_private_in_it(scratch_dir) -> None:
    """Fix 7 (docs/design/agent-fixes.md): what the agent was asked to be and did, in lines a bug report can carry, so it
    holds event kinds, tool names, flags, durations and exit details, never your words, the agent's, a tool's inputs or
    results, a title, an ID or the token."""
    chat = _chat()
    gateway = chat.Chat(scratch_dir, "http://127.0.0.1:9/mcp", "tok-secret-0451")
    try:
        session = gateway.session(SESSION)
        session.emit({"t": "user", "text": "private words from the owner", "provider": "claude"})
        session.emit({"t": "turn_start", "provider": "claude", "model": "model-x", "effort": "medium"})
        session.emit({"t": "tool", "id": "tool-1", "name": "schedule", "title": "schedule",
                      "input": {"id": "SYN00001", "title": "private title", "anchor_date": "2031-03-14"}})
        session.emit({"t": "tool_result", "id": "tool-1", "error": True, "summary": "no goal SYN00001 private title"})
        session.emit({"t": "text", "text": "private answer words"})
        session.emit({"t": "permission", "requestId": "r1", "title": "Allow Claude to use schedule?",
                      "body": "private body", "options": [], "tool": "schedule", "input": {"id": "SYN00001"}})
        session.emit({"t": "permission_done", "requestId": "r1", "value": "accept"})
        session.emit({"t": "done", "error": True, "detail": "API Error: overloaded", "ms": 1234, "at": 1.0})
        session.emit({"t": "exit", "code": 1, "detail": "claude: not logged in"})
    finally:
        gateway.shutdown()
    lines = (scratch_dir / "agent.log").read_text().splitlines()
    text = "\n".join(lines)
    assert any("turn_start" in line and "provider=claude" in line and "model=model-x" in line for line in lines), text
    assert any(line.split(" ", 1)[1].startswith("tool name=schedule") for line in lines) and any("tool_error" in line for line in lines), text
    assert any("permission tool=schedule" in line for line in lines) and any("permission_done value=accept" in line for line in lines)
    assert any("done error=True ms=1234" in line and "API Error: overloaded" in line for line in lines), text
    assert any("exit code=1" in line and "not logged in" in line for line in lines), text
    assert all(line[:4].isdigit() for line in lines), "every line starts with its time"
    for private in ("private words", "private answer words", "private title", "private body", "SYN00001", "tok-secret-0451",
                    "2031-03-14", str(Path.home()), str(scratch_dir)):
        assert private not in text, private


def test_the_log_rotates_and_stays_small(scratch_dir) -> None:
    chat = _chat()
    log = chat.open_log(scratch_dir, max_bytes=400, backups=2)
    for n in range(200):
        log.info("tool name=schedule number=%d", n)
    for handler in log.handlers:
        handler.close()
    names = sorted(path.name for path in scratch_dir.iterdir() if path.name.startswith("agent.log"))
    assert names == ["agent.log", "agent.log.1", "agent.log.2"]
    assert all(path.stat().st_size <= 400 + 80 for path in scratch_dir.iterdir() if path.name.startswith("agent.log"))
    assert "number=199" in (scratch_dir / "agent.log").read_text()  # the newest lines stay


def test_a_log_that_cannot_be_opened_stops_nothing(scratch_dir) -> None:
    """The log is for bug reports; it never decides whether the chat starts."""
    chat = _chat()
    (scratch_dir / "agent.log").mkdir()  # a place nothing can be written to
    gateway = chat.Chat(scratch_dir, "http://127.0.0.1:9/mcp", "tok")
    try:
        gateway.log.info("tool name=schedule")  # says nothing, and does not fail
        assert not gateway.log.handlers
        assert (scratch_dir / "chat-workspace").is_dir()  # the gateway started: its agents' folder is made last
    finally:
        gateway.shutdown()


def test_a_refused_message_is_in_the_log_with_its_reason(scratch_dir) -> None:
    """The reason a message never went (the CLI missing, an empty message) is exactly what a bug report needs."""
    chat = _chat()
    chat.which = lambda provider: None
    gateway = chat.Chat(scratch_dir, "http://127.0.0.1:9/mcp", "tok")
    try:
        for text in ("   ", "hello"):
            try:
                gateway.send(SESSION, text, {}, {"provider": "claude", "permission": "board"})
            except chat.ChatError:
                pass
    finally:
        gateway.shutdown()
    log = (scratch_dir / "agent.log").read_text()
    assert "refused" in log and "Empty message" in log and "Claude Code is not installed" in log
    assert "hello" not in log


def test_the_goal_a_create_result_names_is_read_from_its_words() -> None:
    """docs/design/agent-chips.md: the gateway reads the goal a conversation made from what the Verticals server's `create`
    answers ("Created 'Title' [ID]", then the steps made and a replay); tests/mcp/test_create.py pins those words."""
    chat = _chat()
    for words, goal in (
        ("Created 'Plan the review' [AB12CD34]", "AB12CD34"),
        ("Created 'Fix [the bug]' [SYN00001]", "SYN00001"),
        ('Created "It\'s a plan" [SYN00002] + 3 descendant(s)', "SYN00002"),
        ("Created 'Plan' [SYN00003] (replayed)", "SYN00003"),
        ("Created 'Plan' [SYN00004] + 2 descendant(s) (replayed)", "SYN00004"),
        ("  Created 'Plan' [SYN00005]\n", "SYN00005"),
        ('{"goal": {"id": "SYN00007", "title": "Plan", "children": 3}, "children": [], "replayed": false}', "SYN00007"),
        ('{"goal": {"id": "SYN00008", "title": "A plan that was cut at fifteen hundred charac', "SYN00008"),
    ):
        assert chat.made_goal(words) == goal, words
    for words in ("ok", "", None, "Created 'Plan'", "Updated 'Plan' [SYN00006]", "Created 'Plan' [SYN00006] and more",
                  '{"goals": [{"id": "SYN00006"}]}', '{"goal": {"title": "No id"}}'):
        assert chat.made_goal(words) is None, words


OTHER_SESSION = "6e3d4d4f-2c2b-4d9f-8f20-1b7a4f4d0c12"


def _made(session, call, goal, title="Plan the review", error=False, tool="create") -> None:
    """What a session sees when the agent calls a tool: the call, then its result in the server's words."""
    session.emit({"t": "tool", "id": call, "name": tool, "title": tool, "input": {"title": title}})
    session.emit({"t": "tool_result", "id": call, "error": error,
                  "summary": "The user declined this action." if error else f"Created {title!r} [{goal}]"})


def test_a_conversation_about_no_goal_becomes_the_conversation_of_the_first_goal_the_agent_makes(scratch_dir) -> None:
    """The conversation is that goal's from then on: the gateway's record says so (Discuss with agent asks it), the app is
    told with a `goal` event, and a second goal made in it, a declined create or another tool changes nothing."""
    chat = _chat()
    gateway = chat.Chat(scratch_dir, "http://127.0.0.1:9/mcp", "tok-secret-0451")
    try:
        session = gateway.session(SESSION)
        _made(session, "t0", "SYN00009", error=True)       # the owner declined it
        _made(session, "t1", "SYN00009", tool="schedule")  # not a create
        assert gateway.goal_conversations("SYN00009") == [] and not [e for _, e in session.events if e["t"] == "goal"]
        _made(session, "t2", "SYN00001", "Plan the review")
        _made(session, "t3", "SYN00002", "Another one")
        assert [e for _, e in session.events if e["t"] == "goal"] == [{"t": "goal", "id": "SYN00001", "title": "Plan the review"}]
        assert [c["session"] for c in gateway.goal_conversations("SYN00001")] == [SESSION]
        assert gateway.goal_conversations("SYN00002") == []
        assert gateway.goal_conversations("SYN00001")[0]["title"] == "Plan the review"

        # A conversation that already belongs to a goal (Discuss with agent began it) keeps that goal.
        gateway.update(OTHER_SESSION, goal={"id": "SYN00010", "title": "Opened with Discuss"})
        _made(gateway.session(OTHER_SESSION), "t4", "SYN00011")
        assert [c["session"] for c in gateway.goal_conversations("SYN00010")] == [OTHER_SESSION]
        assert gateway.goal_conversations("SYN00011") == []
    finally:
        gateway.shutdown()
    # The log says a goal was bound, and not which: no title, no ID.
    log = (scratch_dir / "agent.log").read_text()
    assert log.count("goal_bound") == 1
    for private in ("SYN00001", "SYN00002", "SYN00009", "SYN00010", "SYN00011", "Plan the review", "Another one", "tok-secret-0451"):
        assert private not in log, private


def test_a_goal_made_in_a_conversation_survives_the_gateway_starting_again(scratch_dir) -> None:
    chat = _chat()
    first = chat.Chat(scratch_dir, "http://127.0.0.1:9/mcp", "tok")
    try:
        _made(first.session(SESSION), "t1", "SYN00001")
    finally:
        first.shutdown()
    second = chat.Chat(scratch_dir, "http://127.0.0.1:9/mcp", "tok")
    try:
        assert [c["session"] for c in second.goal_conversations("SYN00001")] == [SESSION]
    finally:
        second.shutdown()


class _Agent:
    provider = "claude"

    def __init__(self):
        self.closed = False

    def close(self):
        self.closed = True


def test_an_agent_no_turn_used_for_ten_minutes_is_closed_and_a_busy_one_is_not(scratch_dir) -> None:
    """Each conversation's agent is a CLI process that held its memory until the app quit: every Inbox warm-up and every Check
    again left one more. One idle for ten minutes is closed now, and the moment is kept with the conversation (close_agent)."""
    chat = _chat()
    gateway = chat.Chat(scratch_dir, "http://127.0.0.1:9/mcp", "tok", watch_every=0)
    try:
        gateway.update(SESSION, provider="claude")
        idle, busy, asking = gateway.session(SESSION), gateway.session(OTHER_SESSION), gateway.session(str(uuid.uuid4()))
        for s in (idle, busy, asking):
            s.agent, s.ended_at = _Agent(), 1000.0
        agents = [idle.agent, busy.agent, asking.agent]
        busy.running = True
        asking.asks["1"] = asking.agent

        gateway.close_idle(now=1000.0 + chat.AGENT_IDLE_TIMEOUT - 1)
        assert not any(a.closed for a in agents) and idle.agent is agents[0]

        gateway.close_idle(now=1000.0 + chat.AGENT_IDLE_TIMEOUT)
        assert agents[0].closed and idle.agent is None and gateway.load()[SESSION]["closedAt"]
        assert not agents[1].closed and not agents[2].closed
    finally:
        gateway.shutdown()
    assert "agent_idle_close provider=claude" in (scratch_dir / "agent.log").read_text()


class _Asking:
    def __init__(self):
        self.decided = []

    def decide(self, key, option):
        self.decided.append((key, option))


def test_a_morning_ask_nobody_answers_is_declined_and_a_chats_ask_waits(scratch_dir) -> None:
    """The morning report runs while the owner may be asleep: an ask for a tool beyond its list waited for a click that never came,
    and the report with it. Now it is declined in time and the turn goes on; an ordinary chat's ask still waits,
    and an ask the owner answered in time is not declined after."""
    chat = _chat()
    chat.MORNING_PERMISSION_TIMEOUT = 0.2
    gateway = chat.Chat(scratch_dir, "http://127.0.0.1:9/mcp", "tok", watch_every=0)
    try:
        morning, talk = gateway.session(SESSION), gateway.session(OTHER_SESSION)
        morning.settings, talk.settings = {"provider": "claude", "sources": "connected"}, {"provider": "claude"}
        agent = _Asking()
        options = [("Allow once", "accept"), ("Decline", "decline")]
        morning.ask(agent, "1", "Allow Claude to use send?", "", options)
        morning.ask(agent, "2", "Allow Claude to use post?", "", options)
        talk.ask(agent, "3", "Allow Claude to use send?", "", options)
        gateway.decide(SESSION, "2", "accept")
        time.sleep(0.5)
        assert agent.decided == [("2", "accept"), ("1", "decline")]
        assert "3" in talk.asks and "1" not in morning.asks
        done = [e for _, e in morning.events if e["t"] == "permission_done" and e["requestId"] == "1"]
        assert done == [{"t": "permission_done", "requestId": "1", "value": "decline", "says": "No answer in 0 minutes: declined."}]
    finally:
        gateway.shutdown()
    assert "morning ask unanswered" in (scratch_dir / "agent.log").read_text()


def _memory_gateway(chat, scratch_dir, docs):
    """A gateway whose API holds the documents `docs` ({path: body}), as `GET /api/docs` and `GET /api/docs/{id}` answer."""
    gateway = chat.Chat(scratch_dir, "http://127.0.0.1:9/mcp", "tok", api_url="http://127.0.0.1:9", watch_every=0)
    ids = {f"DOC{i:05d}": (path, body) for i, (path, body) in enumerate(docs.items())}

    def api(method, path, body=None, timeout=20):
        if method == "POST":
            ids[f"DOC{len(ids):05d}"] = (body["path"], body["body"])
            return {"id": f"DOC{len(ids) - 1:05d}"}
        if path == "/api/docs":
            return {"docs": [{"id": id, "path": p} for id, (p, _) in ids.items()]}
        return {"body": ids[path.rsplit("/", 1)[1]][1]}

    gateway.api, gateway.held = api, ids
    return gateway


def test_the_memory_comes_after_the_built_in_instructions_and_only_the_morning_turn_reads_its_own(scratch_dir) -> None:
    """docs/design/agent-memory.md: the built-in instructions stay in the app, and every release updates them; the memory
    documents are added after them, every conversation's always and the morning report's in its turns only. A missing one
    is made empty, once."""
    chat = _chat()
    gateway = _memory_gateway(chat, scratch_dir, {chat.EVERY_MEMORY: "Answer like a pirate.",
                                                 chat.MORNING_MEMORY: "Leave password notices out.", "notes/other.md": "Not memory."})
    try:
        every = gateway.owner_memory({"provider": "claude"})
        morning = gateway.owner_memory({"provider": "claude", "sources": "connected"})
        assert every.startswith("## Memory") and "### memory/AGENTS.md\n\nAnswer like a pirate." in every
        assert "password" not in every and "Not memory." not in every
        assert every.rstrip() in morning and morning.rstrip().endswith("Leave password notices out.")
    finally:
        gateway.shutdown()
    empty = _memory_gateway(chat, scratch_dir, {})
    try:
        assert empty.owner_memory({"provider": "claude"}) == ""
        assert sorted(p for p, _ in empty.held.values()) == sorted(chat.MEMORY)
        assert empty.owner_memory({"provider": "claude"}) == "" and len(empty.held) == 2
    finally:
        empty.shutdown()


def test_a_conversation_resumed_after_the_memory_changed_renders_its_prompt_again(scratch_dir) -> None:
    """Claude keeps the prompt a conversation recorded first, on every resume: with a new memory it is told to render it again."""
    chat = _chat()
    started = []

    class _Started:
        provider, session_id = "claude", "11111111-1111-4111-8111-111111111111"

        def __init__(self, chat_, s, settings, resume, cwd=None, rebuild_prompt=False):
            started.append((resume, rebuild_prompt))
            self.settings = settings

        def send(self, text):
            pass

        def close(self):
            pass

    chat.AGENT_CLASSES["claude"] = _Started
    chat.which = lambda provider: "claude"
    gateway = _memory_gateway(chat, scratch_dir, {chat.EVERY_MEMORY: "Answer like a pirate."})
    gateway.open_answer = lambda *a: None
    try:
        gateway.update(SESSION, provider="claude", sessionId=_Started.session_id, memoryHash=chat.NO_MEMORY)
        s = gateway.session(SESSION)
        gateway.start_turn(s, "Hello", {}, chat.clean_settings({}))
        s.running, s.agent = False, None
        gateway.start_turn(s, "Again", {}, chat.clean_settings({}))
        assert started == [(_Started.session_id, True), (_Started.session_id, False)]
    finally:
        gateway.shutdown()


def test_the_agent_writes_its_memory_without_asking_and_nothing_else(scratch_dir) -> None:
    """docs/design/agent-memory.md: making or editing a memory document runs without a question in a chat; any other
    document, a move out of memory, or the second agent's write is put to the owner or declined. A morning turn reads mail,
    so its writer's write to the memory is put to the owner, while its report's own document is written as before."""
    chat = _chat()
    gateway = _memory_gateway(chat, scratch_dir, {chat.EVERY_MEMORY: "Answer like a pirate.", "notes/other.md": "Not memory."})
    try:
        assert gateway.memory_write("doc_create", {"path": chat.MORNING_MEMORY})
        assert gateway.memory_write("doc_save", {"id": "DOC00000", "expected_revision": 1, "body": "Answer briefly."})
        assert not gateway.memory_write("doc_save", {"id": "DOC00000", "expected_revision": 1, "path": "notes/kept.md"})
        assert not gateway.memory_write("doc_save", {"id": "DOC00001", "expected_revision": 1, "body": "x"})
        assert not gateway.memory_write("doc_create", {"path": "notes/new.md"})
        assert not gateway.memory_write("doc_delete", {"id": "DOC00000"})
        assert gateway.touches_memory("doc_save", {"id": "DOC00000", "expected_revision": 1, "path": "notes/kept.md"})
        assert gateway.touches_memory("doc_save", {"id": "DOC00001", "expected_revision": 1, "path": chat.EVERY_MEMORY})
        assert not gateway.touches_memory("doc_save", {"id": "DOC00001", "expected_revision": 1, "body": "x"})
    finally:
        gateway.shutdown()
    chat.JsonProcess, chat.which = _Proc, lambda provider: "claude"
    host = types.SimpleNamespace(claude_config=lambda session_id=None: Path("mcp.json"), workdir=Path("."), log=None,
                                 memory_write=lambda tool, args: args.get("path") == chat.EVERY_MEMORY,
                                 touches_memory=lambda tool, args: args.get("path") == chat.EVERY_MEMORY)
    for settings, decided in (({}, "allow"), ({"sources": "connected", "role": "checker"}, "deny")):
        s = _Session()
        agent = chat.ClaudeAgent(host, s, {**chat.clean_settings({}), **settings}, None)
        agent.handle({"type": "control_request", "request_id": "r1", "request": {
            "subtype": "can_use_tool", "tool_name": "mcp__verticals__doc_create", "input": {"path": chat.EVERY_MEMORY}}})
        assert agent.proc.sent[-1]["response"]["response"]["behavior"] == decided
    s = _Session()
    agent = chat.ClaudeAgent(host, s, chat.clean_settings({}), None)
    agent.handle({"type": "control_request", "request_id": "r2", "request": {
        "subtype": "can_use_tool", "tool_name": "mcp__verticals__doc_create", "input": {"path": "notes/new.md"}}})
    assert s.asked
    for path, asked in ((chat.EVERY_MEMORY, True), ("reports/2026-10-29-morning.md", False)):
        s = _Session()
        agent = chat.ClaudeAgent(host, s, {**chat.clean_settings({}), "sources": "connected"}, None)
        agent.handle({"type": "control_request", "request_id": "r3", "request": {
            "subtype": "can_use_tool", "tool_name": "mcp__verticals__doc_create", "input": {"path": path}}})
        assert bool(s.asked) == asked


def test_the_memory_ends_claudes_prompt_and_a_new_one_starts_codex_again() -> None:
    chat = _chat()
    chat.JsonProcess, chat.which = _Proc, lambda provider: "claude"
    host = types.SimpleNamespace(claude_config=lambda session_id=None: Path("mcp.json"), workdir=Path("."), log=None)
    memory = "## Memory\n\nAnswer like a pirate.\n"
    prompt = _system_prompt(chat.ClaudeAgent(host, _Session(), {**chat.clean_settings({}), "memory": memory}, None))
    assert prompt.startswith(chat.PROMPT) and prompt.endswith(memory)
    assert chat.codex_instructions({"memory": "Answer like a pirate."}).endswith("Answer like a pirate.")
    assert chat.CodexAgent.signature_of({"memory": "a"}) != chat.CodexAgent.signature_of({"memory": "b"})


def test_the_agent_is_told_to_link_what_it_made_and_to_name_the_rest_by_title() -> None:
    """docs/design/agent-chips.md: the chips come from the links in the agent's words, so the agent links what it made or
    changed, each on a line of its own, and names any other goal by its title."""
    prompt = " ".join(_chat().PROMPT.split())
    assert "Link each goal and each document you made or changed in a turn, once, each on a line of its own after your words" in prompt
    assert "goals as [title](#goal/<id>), documents as [title](#doc/<id>)" in prompt
    assert "The app draws those lines as chips under your words" in prompt
    assert "Mention any other goal by its title, with no link" in prompt
    assert "Link board dates inside a sentence as [label](/h/YYYY-MM-DD)" in prompt
