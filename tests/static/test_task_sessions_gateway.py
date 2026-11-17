"""The gateway and the sessions of tasks (docs/design/task-sessions.md): a task's sessions listed newest first with when each
moved, a session begun in Claude or Codex linked to its task by the link tool, one that went on outside noticed from its file's
size and time, and a session opened where it lives. The gateway is the real one; its agents' files are samples in a temporary
home, unreadable, so a read of a session's contents would fail the test."""

from __future__ import annotations

import os
import shlex
import stat
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from tests.static.sample_sessions import (
    CLAUDE_SESSION, CODEX_THREAD, FOLDER, OTHER_CLAUDE, chat_module, claude_file, codex_file, homes,
)

GOAL = "SYN00001"
TITLE = "Plan the review"
THIRD_CLAUDE = "7a1f0c3e-0000-4000-8000-00000000000b"


@contextmanager
def gateway(scratch_dir: Path, watch_every: float = 0) -> Iterator[tuple[object, object]]:
    chat = chat_module()
    state = scratch_dir / "state"
    state.mkdir(exist_ok=True)
    gate = chat.Chat(state, "http://127.0.0.1:9/mcp", "tok-secret-0451", watch_every=watch_every)
    try:
        yield chat, gate
    finally:
        gate.shutdown()


def known(gate, key: str, provider: str, session: str, goal: str = GOAL, **fields) -> None:
    """A session of a task as the gateway keeps it once it has been talked in."""
    gate.update(key, provider=provider, sessionId=session, goal={"id": goal, "title": TITLE}, **fields)


def test_a_tasks_sessions_are_listed_newest_first_with_when_each_moved(scratch_dir) -> None:
    now = time.time()
    with homes(scratch_dir), gateway(scratch_dir) as (_, gate):
        claude_file(scratch_dir, FOLDER, CLAUDE_SESSION, at=now - 300)
        codex_file(scratch_dir, CODEX_THREAD, at=now - 2 * 86400)
        known(gate, "11111111-1111-4111-8111-111111111111", "claude", CLAUDE_SESSION, lastTurnAt=now - 400, cwd=FOLDER)
        known(gate, "22222222-2222-4222-8222-222222222222", "codex", CODEX_THREAD, lastTurnAt=now - 2 * 86400)
        # A conversation Verticals had with a session of another task, and one whose agent never wrote a file.
        known(gate, "33333333-3333-4333-8333-333333333333", "claude", OTHER_CLAUDE, goal="SYN00002", lastTurnAt=now)
        known(gate, "44444444-4444-4444-8444-444444444444", "claude", THIRD_CLAUDE, lastTurnAt=now - 3600)
        found = gate.goal_conversations(GOAL)
        assert [c["provider"] for c in found] == ["claude", "claude", "codex"]
        assert [round(now - c["movedAt"]) for c in found] == [300, 3600, 2 * 86400]  # a file's time, else Verticals' last turn
        assert found[0]["cwd"] == FOLDER and found[0]["agentSession"] == CLAUDE_SESSION
        assert found[0]["session"] == "11111111-1111-4111-8111-111111111111" and found[0]["title"] == TITLE
        assert not any(c["outside"] or c["working"] for c in found)
        assert gate.goal_conversations("SYN00404") == []


def test_a_session_begun_outside_is_linked_by_the_agent_that_is_in_it(scratch_dir) -> None:
    """Codex gives its thread id; Claude Code, which is never told its own, gives the folder it works in. The session is then
    one of the task's, listed with the others, and a second call changes nothing."""
    now = time.time()
    with homes(scratch_dir), gateway(scratch_dir) as (chat, gate):
        codex_file(scratch_dir, CODEX_THREAD, at=now - 30)
        linked = gate.link_session({"id": GOAL, "title": TITLE}, "codex", CODEX_THREAD, "/Users/sample/app")
        assert linked == {"session": CODEX_THREAD, "provider": "codex", "goal": {"id": GOAL, "title": TITLE}, "same": True}
        claude_file(scratch_dir, FOLDER, CLAUDE_SESSION, at=now - 4)
        assert gate.link_session({"id": GOAL, "title": TITLE}, "claude", None, FOLDER)["session"] == CLAUDE_SESSION
        found = gate.goal_conversations(GOAL)
        assert {(c["provider"], c["agentSession"]) for c in found} == {("codex", CODEX_THREAD), ("claude", CLAUDE_SESSION)}
        assert next(c for c in found if c["provider"] == "claude")["cwd"] == FOLDER
        # Again: the same link, once. And another task asking for a session that has one keeps the first.
        assert gate.link_session({"id": GOAL, "title": TITLE}, "codex", CODEX_THREAD)["same"] is True
        kept = gate.link_session({"id": "SYN00002", "title": "Another"}, "codex", CODEX_THREAD)
        assert kept["goal"]["id"] == GOAL and kept["same"] is False
        assert gate.goal_conversations("SYN00002") == [] and len(gate.goal_conversations(GOAL)) == 2


def test_the_link_tool_says_what_it_needs_when_it_cannot_tell_which_session_it_is(scratch_dir) -> None:
    now = time.time()
    with homes(scratch_dir), gateway(scratch_dir) as (chat, gate):
        task = {"id": GOAL, "title": TITLE}
        for provider, session, folder, words in (
            ("codex", None, FOLDER, "CODEX_THREAD_ID"),                  # Codex has no folder to find a thread by
            ("claude", None, None, "folder"),
            ("claude", None, FOLDER, "No Claude session was written to in that folder in the last minute"),
            ("claude", "not-an-id", FOLDER, "not an id"),
            ("gemini", CLAUDE_SESSION, FOLDER, "claude or codex"),
        ):
            try:
                gate.link_session(task, provider, session, folder)
            except chat.ChatError as e:
                assert words in str(e), (provider, str(e))
            else:
                raise AssertionError(f"{provider} {session} was linked")
        claude_file(scratch_dir, FOLDER, CLAUDE_SESSION, at=now - 3)
        claude_file(scratch_dir, FOLDER, OTHER_CLAUDE, at=now - 2)
        try:
            gate.link_session(task, "claude", None, FOLDER)
        except chat.ChatError as e:
            assert "2 Claude sessions were written to in that folder in the last minute: give your session id" == str(e)
        else:
            raise AssertionError("one of two active sessions was picked")
        for goal in ({"id": "a b"}, {"id": ""}, None, "SYN00001"):
            try:
                gate.link_session(goal, "claude", CLAUDE_SESSION, FOLDER)
            except chat.ChatError:
                continue
            raise AssertionError(f"{goal!r} was taken for a task")
        assert gate.goal_conversations(GOAL) == []


def test_a_session_file_that_grows_while_verticals_is_not_driving_it_marks_the_session(scratch_dir) -> None:
    """The signal: size and time of the file, a stat each look. A turn Verticals runs, the lines an agent leaves just after it
    and a few small ones appended later are not "went on"; a turn's worth of lines in Claude is."""
    now = time.time()
    with homes(scratch_dir), gateway(scratch_dir) as (chat, gate):
        path = claude_file(scratch_dir, FOLDER, CLAUDE_SESSION, size=3000, at=now - 3600)
        key = "11111111-1111-4111-8111-111111111111"
        known(gate, key, "claude", CLAUDE_SESSION, lastTurnAt=now - 3600, cwd=FOLDER)
        gate.look()                                        # first sight: this is where it stands
        assert gate.goal_conversations(GOAL)[0]["outside"] is False

        def grow(by: int) -> None:
            path.chmod(stat.S_IRUSR | stat.S_IWUSR)
            with open(path, "ab") as grown:
                grown.write(b"x" * by)
            path.chmod(0)

        grow(300)                                          # a title line or two
        gate.look()
        assert gate.goal_conversations(GOAL)[0]["outside"] is False
        gate.update(key, lastTurnAt=time.time())           # Verticals has just finished a turn in it
        grow(4000)
        gate.look()
        assert gate.goal_conversations(GOAL)[0]["outside"] is False
        gate.update(key, lastTurnAt=time.time() - 3600)    # long ago again
        grow(300)
        gate.look()
        assert gate.goal_conversations(GOAL)[0]["outside"] is False  # what was Verticals' own is the reference now
        grow(2500)                                         # the owner went on in Claude
        gate.look()
        found = gate.goal_conversations(GOAL)[0]
        assert found["outside"] is True and found["working"] is True  # written just now
        state = gate.sessions_state()["goals"][GOAL]
        assert state["working"] is True and state["outside"]["provider"] == "claude"
        assert [c["session"] for c in state["sessions"]] == [key]
        # A while later it is quiet: still continued outside, no longer working.
        os.utime(path, (time.time() - 120, time.time() - 120))
        gate.look()
        state = gate.sessions_state()["goals"][GOAL]
        assert state["working"] is False and state["outside"]["provider"] == "claude"
        log = (scratch_dir / "state" / "agent.log").read_text()
        assert log.count("outside provider=claude") == 1 and GOAL not in log and CLAUDE_SESSION not in log


def test_what_went_on_outside_is_noticed_after_the_gateway_was_away(scratch_dir) -> None:
    """The reference is kept in the store, so a session that grew while Verticals was not running is marked at its next look."""
    now = time.time()
    with homes(scratch_dir):
        path = claude_file(scratch_dir, FOLDER, CLAUDE_SESSION, size=3000, at=now - 7200)
        key = "11111111-1111-4111-8111-111111111111"
        with gateway(scratch_dir) as (chat, gate):
            known(gate, key, "claude", CLAUDE_SESSION, lastTurnAt=now - 7200)
            gate.look()
        path.chmod(0o600)
        with open(path, "ab") as grown:
            grown.write(b"x" * 5000)
        path.chmod(0)
        with gateway(scratch_dir) as (chat, gate):
            assert gate.goal_conversations(GOAL)[0]["outside"] is False
            gate.look()
            assert gate.goal_conversations(GOAL)[0]["outside"] is True


def test_the_lines_an_agent_writes_as_verticals_closes_it_are_not_went_on(scratch_dir) -> None:
    """The app quits, or a conversation is reset, while its agent is alive: Verticals closes the CLI, which writes its last
    lines to the session's file as it exits. That write is Verticals' own, also when the gateway that next looks at the file
    is a new one, started again after the app (21 Oct 2026: a task got Claude's mark after the app was restarted). What grows
    later is still noticed."""
    now = time.time()
    with homes(scratch_dir):
        path = claude_file(scratch_dir, FOLDER, CLAUDE_SESSION, size=3000, at=now - 7200)
        key = "11111111-1111-4111-8111-111111111111"

        def grow(by: int) -> None:
            path.chmod(stat.S_IRUSR | stat.S_IWUSR)
            with open(path, "ab") as grown:
                grown.write(b"x" * by)
            path.chmod(0)

        class Exiting:
            """An agent whose CLI writes its closing lines when it is closed."""
            provider = "claude"

            def close(self) -> None:
                grow(4000)

        with gateway(scratch_dir) as (chat, gate):
            known(gate, key, "claude", CLAUDE_SESSION, lastTurnAt=now - 7200, cwd=FOLDER)
            gate.look()
            gate.session(key).agent = Exiting()
        with gateway(scratch_dir) as (chat, gate):         # the app started again
            gate.look()
            assert gate.goal_conversations(GOAL)[0]["outside"] is False
            assert gate.load()[key]["closedAt"] >= now
            gate.update(key, closedAt=time.time() - 3600)  # an hour has passed since
            grow(2500)                                     # the owner went on in Claude
            gate.look()
            assert gate.goal_conversations(GOAL)[0]["outside"] is True


def test_the_watcher_looks_by_itself_and_stops_with_the_gateway(scratch_dir) -> None:
    now = time.time()
    with homes(scratch_dir):
        path = claude_file(scratch_dir, FOLDER, CLAUDE_SESSION, size=3000, at=now - 7200)
        with gateway(scratch_dir, watch_every=0.05) as (chat, gate):
            known(gate, "11111111-1111-4111-8111-111111111111", "claude", CLAUDE_SESSION, lastTurnAt=now - 7200)
            time.sleep(0.3)
            path.chmod(0o600)
            with open(path, "ab") as grown:
                grown.write(b"x" * 5000)
            path.chmod(0)
            for _ in range(60):
                if gate.goal_conversations(GOAL)[0]["outside"]:
                    break
                time.sleep(0.05)
            assert gate.goal_conversations(GOAL)[0]["outside"] is True
        assert gate.stopping.is_set()


FAKE_OPEN = r"""#!/bin/sh
for a in "$@"; do echo "ARG $a" >> "$OPEN_LOG"; case "$a" in *.command) cat "$a" >> "$OPEN_LOG";; esac; done
case "$1" in claude:*)
  if [ -n "$NO_CLAUDE_APP" ]; then
    echo "No application knows how to open URL $1 (Error Domain=NSOSStatusErrorDomain Code=-10814 \"kLSApplicationNotFoundErr\")." >&2
    exit 1
  fi
  if [ -n "$OPEN_FAILS" ]; then echo "$OPEN_FAILS" >&2; exit 1; fi;;
esac
"""


def _fake_open(folder: Path) -> Path:
    """A stand-in for macOS `open` first on the PATH: it opens nothing and writes down what it was asked, and for a script
    what the script says. With `NO_CLAUDE_APP` it answers a Claude link as `open` does on a Mac without the Claude app, and with
    `OPEN_FAILS` it fails one with those words."""
    folder.mkdir(parents=True, exist_ok=True)
    script = folder / "open"
    script.write_text(FAKE_OPEN)
    script.chmod(0o755)
    return script


def test_a_session_opens_where_it_lives(scratch_dir) -> None:
    """A Codex thread in the Codex app and a Claude session in the Claude app, each by its app's link. A Claude session opens in
    Terminal from its folder, by a script of the app's own, on a Mac with no app for the link, and when Verticals' Claude keeps
    its sessions in a folder the Claude app does not read (another account's, from agents.env)."""
    log = scratch_dir / "opened.log"
    saved = {name: os.environ.get(name) for name in ("PATH", "OPEN_LOG", "NO_CLAUDE_APP", "OPEN_FAILS")}
    _fake_open(scratch_dir / "bin")
    os.environ["PATH"] = f"{scratch_dir / 'bin'}:{os.environ['PATH']}"
    os.environ["OPEN_LOG"] = str(log)
    claude_key, codex_key = "11111111-1111-4111-8111-111111111111", "22222222-2222-4222-8222-222222222222"
    script = scratch_dir / "state" / "open" / f"claude-{CLAUDE_SESSION}.command"

    def opened() -> list[str]:
        lines = log.read_text().splitlines()
        log.unlink()
        return lines

    try:
        with homes(scratch_dir) as home, gateway(scratch_dir) as (chat, gate):
            known(gate, claude_key, "claude", CLAUDE_SESSION, cwd=FOLDER)
            known(gate, codex_key, "codex", CODEX_THREAD)
            assert gate.open_session(codex_key) == {"kind": "url"}
            assert opened() == [f"ARG codex://threads/{CODEX_THREAD}"]

            # Verticals' Claude and the Claude app keep their sessions in one folder, `~/.claude`: the app opens the session.
            os.environ["CLAUDE_CONFIG_DIR"] = str(home["HOME"] / ".claude")
            assert gate.open_session(claude_key) == {"kind": "url"}
            assert opened() == [f"ARG claude://resume?session={CLAUDE_SESSION}"]
            assert not script.exists()

            # No app takes the link: Terminal, from the session's folder.
            os.environ["NO_CLAUDE_APP"] = "1"
            assert gate.open_session(claude_key) == {"kind": "terminal"}
            lines = opened()
            assert lines[:4] == [f"ARG claude://resume?session={CLAUDE_SESSION}", "ARG -a", "ARG Terminal", f"ARG {script}"]
            assert f"cd '{FOLDER}' 2>/dev/null || cd ~" in lines and lines[-1].endswith(f"claude --resume {CLAUDE_SESSION}")
            assert script.stat().st_mode & 0o777 == 0o700
            del os.environ["NO_CLAUDE_APP"]

            # The app is there and fails: its words, and no second copy of Claude in Terminal.
            os.environ["OPEN_FAILS"] = "LSOpenURLsWithRole() failed with error -600"
            try:
                gate.open_session(claude_key)
            except chat.ChatError as e:
                assert str(e) == "Claude did not open it: LSOpenURLsWithRole() failed with error -600"
            else:
                raise AssertionError("a failed open went unsaid")
            assert opened() == [f"ARG claude://resume?session={CLAUDE_SESSION}"]
            del os.environ["OPEN_FAILS"]

            # Another account's folder (the test's own `<scratch>/claude`), which the Claude app does not read: Terminal, which
            # is told that folder.
            os.environ["CLAUDE_CONFIG_DIR"] = str(home["CLAUDE_CONFIG_DIR"])
            script.unlink()
            assert gate.open_session(claude_key) == {"kind": "terminal"}
            lines = opened()
            assert lines[:3] == ["ARG -a", "ARG Terminal", f"ARG {script}"]
            assert f"export CLAUDE_CONFIG_DIR={shlex.quote(str(home['CLAUDE_CONFIG_DIR']))}" in lines
            assert lines[-1].endswith(f"claude --resume {CLAUDE_SESSION}")
            try:
                gate.open_session("99999999-9999-4999-8999-999999999999")
            except chat.ChatError as e:
                assert str(e) == "No such session"
            else:
                raise AssertionError("a session nobody knows was opened")
    finally:
        for name, value in saved.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
