"""Replan over the whole board (docs/design/replan-whole-board.md), as the desktop chat gateway carries it: every carried plan
of the board reaches the agent grouped by the box it sits in, with the rules that sort them with the owner in about five
minutes; Claude's own question tool (`AskUserQuestion`) becomes the field's asks, one question at a time, and its answers go
back to Claude once, in the tool's answer shape; words typed while a question waits answer it; and a conversation that a
Replan message started runs its board writes without asking for each, while every other conversation asks as before."""

from __future__ import annotations

import json
import time
from pathlib import Path

from tests.static.test_chat_gateway import _Proc, _chat, _decision, _flag, _tool

SESSION = "7a1b2c3d-4e5f-4a6b-8c7d-9e0f1a2b3c4d"
OTHER = "8b2c3d4e-5f6a-4b7c-9d8e-0f1a2b3c4d5e"
WRITES = ("schedule", "delete", "update", "reparent", "doc_create", "doc_save", "doc_link")
MODES = ("board", "manual", "acceptEdits", "plan", "auto", "dontAsk", "bypassPermissions")

PLANS = [
    {"id": "SYNWEEK1", "title": "Draft the outline", "column": "week", "vertical": "day", "anchor_date": "2026-09-29",
     "parent": "Write the guide"},
    {"id": "SYNMNTH1", "title": "Plan the review", "column": "month", "vertical": "month", "anchor_date": "2026-09-01",
     "parent": None},
    {"id": "SYNWEEK2", "title": "Call the printer", "column": "week", "vertical": "week", "anchor_date": "2026-10-12",
     "parent": "Print the guide"},
    {"id": "SYNQRTR1", "title": "Ship the first edition", "column": "quarter", "vertical": "quarter",
     "anchor_date": "2026-07-01", "parent": "Write the guide"},
    {"id": "SYNDAY01", "title": "Send the draft", "column": "day", "vertical": "day", "anchor_date": "2026-10-20"},
]

QUESTIONS = {"questions": [
    {"question": "What matters most this week?", "header": "Focus", "multiSelect": False, "options": [
        {"label": "The launch", "description": "The plans of the launch stream"},
        {"label": "The guide (my guess)", "description": "You worked on it every day last week"},
        {"label": "Rest", "description": "Keep the week light"}]},
    {"question": "Which streams went quiet?", "header": "Quiet", "multiSelect": True, "options": [
        {"label": "Reading", "description": ""},
        {"label": "Sport (Recommended)", "description": ""},
        {"label": "Music", "description": ""}]},
]}


def _context(plans, **more) -> str:
    return _chat().format_context({"today": "2026-10-21", "replan": {"plans": plans}, **more})


# ---------------------------------------------------------------- what the agent is told

def test_the_context_lists_every_columns_carried_plans_grouped_by_box() -> None:
    context = _context(PLANS)
    assert "The plans that carried over on the board, 5 in all, by the box each sits in:" in context
    lines = context.splitlines()
    day, week, month, quarter = (next(i for i, line in enumerate(lines) if line.startswith(f"{box} box (")) for box in
                                 ("Day", "Week", "Month", "Quarter"))
    assert day < week < month < quarter, "the boxes come in the board's order, small to large"
    assert lines[week] == ('Week box (2): "Draft the outline" (id SYNWEEK1, day plan for 2026-09-29, under "Write the guide"); '
                           '"Call the printer" (id SYNWEEK2, week plan for 2026-10-12, under "Print the guide")')
    assert lines[month] == 'Month box (1): "Plan the review" (id SYNMNTH1, month plan for 2026-09-01)'
    assert lines[quarter] == 'Quarter box (1): "Ship the first edition" (id SYNQRTR1, quarter plan for 2026-07-01, under "Write the guide")'
    assert "Replan" not in _chat().format_context({"today": "2026-10-21"})


def test_the_context_names_the_three_year_box_and_clips_what_it_lists() -> None:
    plans = [{"id": "SYN3YR01" + "x" * 60, "title": "T" * 300, "column": "decade", "vertical": "decade",
              "anchor_date": "2026-01-01", "parent": "P" * 300}, {"title": "no id"}, "junk", None]
    context = _context(plans)
    assert "The plans that carried over on the board, 1 in all" in context
    line = next(line for line in context.splitlines() if line.startswith("3 years box (1): "))
    assert line == f'3 years box (1): "{"T" * 200}" (id {("SYN3YR01" + "x" * 60)[:40]}, 3-year plan for 2026-01-01, under "{"P" * 200}")'


def test_the_context_lists_at_most_two_hundred_plans_and_says_how_many_there_are() -> None:
    plans = [{"id": f"SYN{n:05d}", "title": f"Plan {n}", "column": "week", "vertical": "week", "anchor_date": "2026-10-05"}
             for n in range(250)]
    context = _context(plans)
    assert "The plans that carried over on the board, 250 in all, the first 200 listed, by the box each sits in:" in context
    assert "Week box (200): " in context and "SYN00199" in context and "SYN00200" not in context


def test_the_replan_context_carries_the_new_rules_and_the_old_task_keeps_its_own() -> None:
    chat = _chat()
    context = _context(PLANS)
    assert chat.REPLAN_ASK_RULES in context
    rules = " ".join(chat.REPLAN_ASK_RULES.split())
    for words in ("The owner clicked Replan: sort out every plan that carried over on the board, all columns at once",
                  "Read before you ask. Call board for today.",
                  "at most three questions about what matters now, each with two to four short options, your guess first",
                  "Ask with the AskUserQuestion tool when you have it, all the questions in one call.",
                  'end with: "Say go to take my guesses, or answer like 1b 3a."',
                  "Make one document with doc_create, path replan/<today>.md",
                  '"Keep this week · 6"', "[title](#goal/<id>)", '"Say go, or move a row in the document."',
                  "Keep with schedule (the column's scale, today's date), To Inbox with schedule (vertical and anchor_date null)",
                  "Delete with delete (cascade true only when the plan's own steps go with it)",
                  "Done with one update of ids with done true", "Move nothing before go."):
        assert words in rules, words
    assert "Goal | Summary | Next step | Your comment" not in context
    # The tasks made before Replan became a request keep the rules they were made with.
    old = chat.format_context({"today": "2026-10-21", "goal": {"id": "SYNTASK1", "title": chat.REPLAN_TITLE}})
    assert chat.REPLAN_RULES in old and chat.REPLAN_ASK_RULES not in old


def test_the_rules_call_the_tools_as_the_verticals_mcp_server_has_them() -> None:
    """The rules name `board`, `doc_create`, `schedule(id, vertical, anchor_date)`, `delete(id, cascade)` and `update(ids,
    done)`: each is a tool of the server with those arguments (verticals/mcp/tool_schemas.py, verticals/mcp/docs.py)."""
    from verticals.mcp import docs, tool_schemas
    assert set(tool_schemas.SCHEDULE_SCHEMA["required"]) == {"id", "vertical", "anchor_date"}
    assert None in tool_schemas.SCHEDULE_SCHEMA["properties"]["vertical"]["enum"]
    assert {"id", "cascade"} <= set(tool_schemas.DELETE_SCHEMA["properties"])
    assert {"ids", "done"} <= set(tool_schemas.UPDATE_SCHEMA["properties"])
    assert tool_schemas.BOARD_SCHEMA["required"] == ["date"]
    assert {"path", "title", "body"} <= set(docs.DOC_CREATE_SCHEMA["properties"])


def test_codex_hears_the_same_rules_and_their_fallback() -> None:
    """Codex has no AskUserQuestion: the rules, which reach every agent in the message's context, say how to ask without it."""
    chat = _chat()
    rules = " ".join(chat.REPLAN_ASK_RULES.split())
    assert "Without it, number the questions, letter the options" in rules


# ---------------------------------------------------------------- Claude's questions in the field

class _Cli(_Proc):
    """The CLI as the gateway starts it, with nothing behind it: what it is sent is kept, and it closes when told."""

    def close(self):
        pass


class _Host:
    """What ClaudeAgent needs of the chat, for an agent judged on its own."""
    workdir = Path(".")
    log = None

    def claude_config(self, session_id=None):
        return Path("mcp.json")


class _Field:
    """A conversation's side of the agent: the asks it shows, in order, and nothing else."""
    id = SESSION

    def __init__(self):
        self.asks = []

    def ask(self, agent, key, title, body, options, tool=None, tool_input=None):
        self.asks.append({"key": key, "title": title, "options": options, "tool": tool, "input": tool_input})

    def emit(self, event):
        pass

    def resolve(self, key, label):
        self.asks.append({"resolved": key, "label": label})


def _seat(settings, prompt=None):
    chat = _chat()
    chat.JsonProcess, chat.which = _Cli, lambda provider: "claude"
    field = _Field()
    return chat, chat.ClaudeAgent(_Host(), field, chat.clean_settings(settings), None, prompt=prompt), field


def _asked_questions(agent, rid="q-1", questions=QUESTIONS):
    agent.handle({"type": "control_request", "request_id": rid,
                  "request": {"subtype": "can_use_tool", "tool_name": "AskUserQuestion", "input": questions}})


def _answer(agent, field, value):
    then = agent.decide(field.asks[-1]["key"], value)
    if callable(then):
        then()


def test_ask_user_question_is_one_ask_per_question_and_one_allow_with_the_answers() -> None:
    _, agent, field = _seat({"permission": "board"})
    sent = len(agent.proc.sent)
    _asked_questions(agent)
    (first,) = field.asks
    assert first["title"] == "What matters most this week?" and first["tool"] == "AskUserQuestion"
    # The guess stays first; the others keep their order.
    assert [label for label, _ in first["options"]] == ["The guide (my guess)", "The launch", "Rest"]
    assert len(agent.proc.sent) == sent, "nothing goes back to Claude before every question is answered"
    _answer(agent, field, first["options"][0][1])
    second = field.asks[-1]
    assert second["title"] == "Which streams went quiet?" and second["key"] != first["key"]
    assert [label for label, _ in second["options"]] == ["Sport (Recommended)", "Reading", "Music"]
    assert len(agent.proc.sent) == sent
    _answer(agent, field, second["options"][2][1])
    (reply,) = agent.proc.sent[sent:]
    assert reply["type"] == "control_response" and reply["response"]["request_id"] == "q-1"
    assert reply["response"]["response"] == {"behavior": "allow", "updatedInput": {**QUESTIONS, "answers": {
        "What matters most this week?": "The guide (my guess)", "Which streams went quiet?": "Music"}}}


def test_several_labels_of_a_multi_select_question_are_joined_and_a_refusal_declines_the_tool() -> None:
    _, agent, field = _seat({"permission": "board"})
    _asked_questions(agent, questions={"questions": [QUESTIONS["questions"][1]]})
    _answer(agent, field, ["1", "2"])
    answers = agent.proc.sent[-1]["response"]["response"]["updatedInput"]["answers"]
    assert answers == {"Which streams went quiet?": "Reading, Music"}
    # A seat that answers every ask with "decline" (report_kind.py's quiet one) refuses the question, it does not answer it.
    _asked_questions(agent, rid="q-2")
    _answer(agent, field, "decline")
    assert _decision(agent) == "deny"


def test_a_question_cancelled_by_the_cli_leaves_the_field() -> None:
    _, agent, field = _seat({"permission": "board"})
    _asked_questions(agent)
    key = field.asks[-1]["key"]
    agent.handle({"type": "control_cancel_request", "request_id": "q-1"})
    assert field.asks[-1] == {"resolved": key, "label": "Cancelled"} and not agent.questions


def test_tools_carry_ask_user_question_only_in_verticals_only_mode() -> None:
    assert _flag(_seat({"permission": "board"})[1], "--tools") == "AskUserQuestion"
    for mode in MODES[1:]:  # Claude Code's own modes have its whole tool set, the question tool with it
        assert "--tools" not in _seat({"permission": mode})[1].proc.args, mode
    assert _flag(_seat({"permission": "board", "sources": "connected"})[1], "--tools") == ""  # the morning turn
    assert _flag(_seat({"permission": "board"}, prompt="A seat of its own.")[1], "--tools") == ""  # report_kind.py
    # In those modes the question is asked as the questions it is, not as a permission to use a tool.
    _, agent, field = _seat({"permission": "manual"})
    _asked_questions(agent)
    assert field.asks[-1]["title"] == "What matters most this week?"


# ---------------------------------------------------------------- the gateway: typed answers and Replan conversations

def _gateway(scratch_dir: Path):
    chat = _chat()
    chat.JsonProcess, chat.which = _Cli, lambda provider: "claude"
    return chat, chat.Chat(scratch_dir, "http://127.0.0.1:9/mcp", "tok-secret-0451", watch_every=0)


def _until(what, check, seconds=5.0):
    end = time.time() + seconds
    while time.time() < end:
        if check():
            return
        time.sleep(0.02)
    raise AssertionError(f"waited for {what}")


def _told(agent) -> int:
    """How many messages of the owner's an agent has been sent."""
    return len([m for m in agent.proc.sent if m.get("type") == "user"]) if agent else 0


def _started(gateway, session_id, text, context=None, settings=None):
    """A message sent the way the app sends it, and the agent that took its turn once it has the message."""
    s = gateway.session(session_id)
    before, told = s.agent, _told(s.agent)
    gateway.send(session_id, text, context or {}, settings or {"provider": "claude", "permission": "board"})
    _until("the turn to start", lambda: s.agent is not None and _told(s.agent) > (told if s.agent is before else 0))
    return s, s.agent


def _turn_ends(s):
    s.finish(False, "")


def test_words_typed_while_a_question_waits_answer_it_and_start_no_turn(scratch_dir) -> None:
    chat, gateway = _gateway(scratch_dir)
    try:
        s, agent = _started(gateway, SESSION, "Help me plan")
        _asked_questions(agent)
        first = next(key for key in s.asks)
        gateway.send(SESSION, "The garden, before the frost", {}, {"provider": "claude", "permission": "board"})
        events = [event for _, event in s.events]
        assert not s.queue, "the words answered the question; they wait for no turn"
        assert {"t": "permission_done", "requestId": first, "label": "Answered"} in events
        assert [e["text"] for e in events if e["t"] == "user"] == ["Help me plan", "The garden, before the frost"]
        second = next(key for key in s.asks)
        assert second != first and [e["title"] for e in events if e["t"] == "permission"] == [
            "What matters most this week?", "Which streams went quiet?"]
        gateway.send(SESSION, "1", {}, {"provider": "claude", "permission": "board"})  # typed, so the words "1"
        answers = agent.proc.sent[-1]["response"]["response"]["updatedInput"]["answers"]
        assert answers == {"What matters most this week?": "The garden, before the frost", "Which streams went quiet?": "1"}
        # With no question waiting, words sent during a turn wait for it as before.
        gateway.send(SESSION, "And then the rest", {}, {"provider": "claude", "permission": "board"})
        assert [text for text, _, _ in s.queue] == ["And then the rest"]
    finally:
        gateway.shutdown()
    log = (scratch_dir / "agent.log").read_text()
    assert "permission_done value=Answered" in log and "permission tool=AskUserQuestion" in log
    for private in ("The garden", "before the frost", "What matters", "Help me plan"):
        assert private not in log, private


def test_a_tapped_answer_is_told_done_before_the_next_question_is_asked(scratch_dir) -> None:
    chat, gateway = _gateway(scratch_dir)
    try:
        s, agent = _started(gateway, SESSION, "Help me plan")
        _asked_questions(agent)
        first = next(key for key in s.asks)
        gateway.decide(SESSION, first, "0")
        kinds = [(e["t"], e.get("requestId")) for _, e in s.events if e["t"] in ("permission", "permission_done")]
        second = next(key for key in s.asks)
        assert kinds == [("permission", first), ("permission_done", first), ("permission", second)]
    finally:
        gateway.shutdown()


def _plans_context():
    return {"today": "2026-10-21", "replan": {"plans": PLANS}}


def test_a_replan_conversation_runs_its_board_writes_without_asking_in_every_mode(scratch_dir) -> None:
    chat = _chat()
    for mode in MODES:
        (scratch_dir / mode).mkdir()
        _, gateway = _gateway(scratch_dir / mode)
        try:
            s, agent = _started(gateway, SESSION, "Sort out every plan", _plans_context(), {"provider": "claude", "permission": mode})
            allowed = _flag(agent, "--allowedTools").split(",")
            for write in WRITES:
                assert f"mcp__verticals__{write}" in allowed, (mode, write)
            assert not [t for t in allowed if not t.startswith("mcp__verticals__")], (mode, allowed)
            asked = len([e for _, e in s.events if e["t"] == "permission"])
            for write in WRITES:
                _tool(agent, f"mcp__verticals__{write}", {"id": "SYNWEEK1"})
                assert _decision(agent) == "allow", (mode, write)
            # Nothing else runs on its own: another Verticals write and any tool outside Verticals are as before.
            for other in ("mcp__verticals__create", "mcp__verticals__doc_delete", "mcp__chat__send_message", "Bash"):
                _tool(agent, other, {"id": "SYNWEEK1"})
                if mode == "board" and not other.startswith("mcp__verticals__"):
                    assert _decision(agent) == "deny", (mode, other)
            titles = [e["title"] for _, e in s.events if e["t"] == "permission"][asked:]
            expected = ["Allow Claude to use create?", "Allow Claude to use doc_delete?"]
            if mode != "board":
                expected += ["Allow Claude to use mcp__chat__send_message?", "Allow Claude to use Bash?"]
            assert titles == expected, (mode, titles)
        finally:
            gateway.shutdown()
    assert chat.REPLAN_WRITES == list(WRITES)


def test_the_replan_conversation_keeps_it_for_its_later_turns_and_after_a_restart(scratch_dir) -> None:
    chat, gateway = _gateway(scratch_dir)
    try:
        s, agent = _started(gateway, SESSION, "Sort out every plan", _plans_context())
        assert agent.replan
        _turn_ends(s)
        s, again = _started(gateway, SESSION, "go")
        assert again is agent, "the next turn goes on in the same agent: its settings did not change"
        _turn_ends(s)
    finally:
        gateway.shutdown()
    chat, restarted = _gateway(scratch_dir)
    try:
        s, resumed = _started(restarted, SESSION, "go")
        assert resumed.replan and "--resume" in resumed.proc.args
        assert "mcp__verticals__schedule" in _flag(resumed, "--allowedTools").split(",")
    finally:
        restarted.shutdown()


def test_an_ordinary_conversation_still_asks_for_every_write_even_when_replan_comes_later(scratch_dir) -> None:
    chat, gateway = _gateway(scratch_dir)
    try:
        s, agent = _started(gateway, OTHER, "Move my week")
        assert not agent.replan
        assert "mcp__verticals__schedule" not in _flag(agent, "--allowedTools").split(",")
        _tool(agent, "mcp__verticals__schedule", {"id": "SYNWEEK1", "vertical": "week", "anchor_date": "2026-10-19"})
        assert [e["title"] for _, e in s.events if e["t"] == "permission"] == ["Allow Claude to use schedule?"]
        _turn_ends(s)
        # A Replan context on a later message of a conversation that began otherwise does not make it one.
        s, same = _started(gateway, OTHER, "Sort out every plan", _plans_context())
        assert same is agent and not same.replan
    finally:
        gateway.shutdown()
    assert "replan" not in json.loads((scratch_dir / "chat-sessions.json").read_text())[OTHER]
