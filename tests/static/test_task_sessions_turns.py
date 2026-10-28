"""A session for a task, turn by turn (docs/design/task-sessions.md): it begins with the task's link, it lives in the folder it
began in, and one that went on in Claude or Codex is resumed by a fresh agent, so what the agent knows is what the session
holds. The agent is the suite's fake `claude` (tests/ui/fake_agent), which writes down how it was started and what it was
sent; the sessions' files are samples in a temporary home."""

from __future__ import annotations

import json
import os
import stat
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from tests.static.sample_sessions import CLAUDE_SESSION, ROOT, chat_module, claude_file, homes

FAKE_AGENTS = ROOT / "tests" / "ui" / "fake_agent"
GOAL = "SYN00001"
TASK = {"id": GOAL, "title": "Plan the review"}


@contextmanager
def gateway(scratch_dir: Path) -> Iterator[tuple[object, object, Path]]:
    """The real gateway, whose `claude` is the fake one, over a state folder of its own."""
    chat = chat_module()
    state = scratch_dir / "state"
    state.mkdir(exist_ok=True)
    saved = os.environ["PATH"]
    os.environ["PATH"] = f"{FAKE_AGENTS}:{saved}"
    gate = chat.Chat(state, "http://127.0.0.1:9/mcp", "tok", watch_every=0)
    try:
        yield chat, gate, gate.workdir
    finally:
        gate.shutdown()
        os.environ["PATH"] = saved


def talk(gate, key: str, words: str, goal: dict | None = None) -> None:
    """Send a message the way the app does and wait until the agent has answered it."""
    session = gate.session(key)
    ended = lambda: sum(1 for _, event in list(session.events) if event["t"] == "done")  # noqa: E731
    before = ended()
    gate.send(key, words, {"goal": goal} if goal else {}, {"provider": "claude", "permission": "board"})
    deadline = time.time() + 20
    while ended() == before:
        assert time.time() < deadline, "the fake agent did not answer"
        time.sleep(0.02)


def starts(folder: Path) -> list[list[str]]:
    return [json.loads(line) for line in (folder / "argv.log").read_text().splitlines()]


def received(folder: Path) -> list[str]:
    return [json.loads(line) for line in (folder / "received.log").read_text().splitlines()]


def grow(path: Path, by: int) -> None:
    path.chmod(stat.S_IRUSR | stat.S_IWUSR)
    with open(path, "ab") as grown:
        grown.write(b"x" * by)
    path.chmod(0)


def test_a_session_begun_for_a_task_begins_with_the_tasks_link(scratch_dir) -> None:
    """Whoever opens the session in Claude or Codex sees which task it belongs to, and an agent that finds the link there can
    link the session. Only the first message of a session carries it, and a conversation about no task has none."""
    with homes(scratch_dir), gateway(scratch_dir) as (_, gate, workspace):
        key, other = str(uuid.uuid4()), str(uuid.uuid4())
        talk(gate, key, "Start work on this task.", TASK)
        talk(gate, key, "And now?", TASK)
        talk(gate, other, "Hello")
        first, second, third = received(workspace)
        assert first.startswith(f"verticals://goal/{GOAL}\n\n<app_context>\n")
        assert first.endswith("</app_context>\n\nStart work on this task.")
        assert second.startswith("<app_context>\n") and third.startswith("<app_context>\n")
        # The agent is told the link is made, so it does not call the tool for a session Verticals started.
        assert 'about the goal "Plan the review"' in first and "linked to the goal already: don't call session_link" in first
        assert gate.load()[key]["cwd"] == str(workspace)
        assert len(starts(workspace)) == 2  # one agent per session, kept for the next turn


def test_a_session_that_went_on_outside_is_resumed_by_a_fresh_agent(scratch_dir) -> None:
    """A process Verticals kept for the session has not heard what was said in Claude: the next turn starts the agent again
    with `--resume`, so it reads the session's file and knows everything. Verticals driving the session again clears the mark."""
    with homes(scratch_dir), gateway(scratch_dir) as (_, gate, workspace):
        key = str(uuid.uuid4())
        talk(gate, key, "Start work on this task.", TASK)
        agent_session = gate.load()[key]["sessionId"]
        path = claude_file(scratch_dir, str(workspace), agent_session, size=3000, at=time.time() - 7200)
        gate.update(key, lastTurnAt=time.time() - 7200)
        gate.look()
        grow(path, 4000)  # the owner went on in Claude Code, in the folder the session lives in
        gate.look()
        assert gate.goal_conversations(GOAL)[0]["outside"] is True
        talk(gate, key, "Continue.", TASK)
        first, second = starts(workspace)
        assert "--session-id" in first and agent_session in first
        assert "--resume" in second and agent_session in second
        assert second[second.index("--system-prompt-snapshot") + 1] == "off", "resumes use this turn's instructions"
        assert gate.goal_conversations(GOAL)[0]["outside"] is False
        talk(gate, key, "Once more.", TASK)
        assert len(starts(workspace)) == 2  # not marked again: the same agent goes on


def test_a_session_begun_outside_is_resumed_from_its_own_folder_with_the_prompt_built_again(scratch_dir) -> None:
    """Claude keeps a session with the folder it began in, and a resume keeps the system prompt the session recorded on its
    first request: Verticals starts the agent in the session's folder and tells Claude to build its own prompt again."""
    with homes(scratch_dir), gateway(scratch_dir) as (chat, gate, workspace):
        project = scratch_dir / "Sample Project"
        project.mkdir()
        path = claude_file(scratch_dir, str(project), CLAUDE_SESSION, size=3000, at=time.time() - 7200)
        gate.link_session(TASK, "claude", CLAUDE_SESSION, str(project))
        grow(path, 4000)
        gate.look()
        found = gate.goal_conversations(GOAL)[0]
        assert found["session"] == CLAUDE_SESSION and found["outside"] is True and found["cwd"] == str(project)
        talk(gate, CLAUDE_SESSION, "What did we decide?", TASK)
        (args,) = starts(project)
        assert args[args.index("--resume") + 1] == CLAUDE_SESSION
        assert args[args.index("--system-prompt-snapshot") + 1] == "off"
        assert not (workspace / "argv.log").exists()
        # It is resumed, not begun: no link first, and the mark is gone.
        (message,) = received(project)
        assert message.startswith("<app_context>\n") and message.endswith("What did we decide?")
        assert gate.goal_conversations(GOAL)[0]["outside"] is False


def test_a_session_whose_folder_has_gone_is_resumed_from_the_gateways_own(scratch_dir) -> None:
    with homes(scratch_dir), gateway(scratch_dir) as (_, gate, workspace):
        claude_file(scratch_dir, "/Users/sample/gone", CLAUDE_SESSION)
        gate.link_session(TASK, "claude", CLAUDE_SESSION, "/Users/sample/gone")
        talk(gate, CLAUDE_SESSION, "Hello again", TASK)
        (args,) = starts(workspace)
        assert "--resume" in args and CLAUDE_SESSION in args
        assert gate.load()[CLAUDE_SESSION]["cwd"] == str(workspace)
