"""When the agent is signed out, the field signs it back in (docs/design/agent-sign-in.md). A turn that fails because Claude Code
(or Codex) is signed out on this Mac ends with one ask instead of the CLI's raw error; Sign in runs the CLI's own login under the
app's config folder, the gateway checks the sign-in every few moments, and once signed in the message that failed goes again, once,
with what it was sent with, and the messages that waited behind the ask go after it. The gateway is the real one; its agents are
the suite's fakes (tests/ui/fake_agent/claude, tests/static/fake_codex/codex), which can be signed out and are signed in by the
test, and the owner's own `~/.claude` and `~/.codex` never come into it."""

from __future__ import annotations

import json
import os
import shlex
import time
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path

from tests.static.sample_sessions import ROOT, chat_module, homes
from tests.static.test_task_sessions_gateway import _fake_open

FAKE_AGENTS = ROOT / "tests" / "ui" / "fake_agent"
FAKE_CODEX = ROOT / "tests" / "static" / "fake_codex"
CLAUDE = {"provider": "claude", "permission": "board"}
TITLE = "Claude Code is signed out on this Mac"
ASKED = "Sign in once and your message goes again."
WAITING = "Approve in the browser."
SIGN_IN = {"label": "Sign in", "value": "signin"}
TERMINAL = {"label": "Open in Terminal", "value": "terminal"}
PAGE = {"label": "Open the sign-in page", "value": "page"}
# What the fake says when signed out, the words the real CLI gave (tests/ui/fake_agent/claude).
EXPIRED = "Failed to authenticate: OAuth session expired and could not be refreshed"


@contextmanager
def gateway(scratch_dir: Path, codex: bool = False) -> Iterator[tuple[object, object, Path]]:
    """The real gateway over a state folder of its own, its `claude` (and `codex`) the fakes and `open` a stand-in that opens
    nothing and writes down what it was asked. The sign-in is checked every 50 ms instead of every two seconds."""
    chat = chat_module()
    state = scratch_dir / "state"
    state.mkdir(exist_ok=True)
    _fake_open(scratch_dir / "bin")
    saved = {name: os.environ.get(name) for name in ("PATH", "OPEN_LOG")}
    os.environ["PATH"] = ":".join([str(scratch_dir / "bin"), str(FAKE_AGENTS), *([str(FAKE_CODEX)] if codex else []), saved["PATH"] or ""])
    os.environ["OPEN_LOG"] = str(scratch_dir / "opened.log")
    gate = chat.Chat(state, "http://127.0.0.1:9/mcp", "tok", watch_every=0)
    gate.signin.every = 0.05
    try:
        yield chat, gate, gate.workdir
    finally:
        gate.shutdown()
        for name, value in saved.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


def signed_out(home: Path, **how) -> None:
    (home / "fake-auth.json").write_text(json.dumps({"signedOut": True, **how}))


def signed_in(home: Path) -> None:
    (home / "fake-auth.json").write_text(json.dumps({}))


def wait_for(found: Callable[[], object], what: str, seconds: float = 10) -> object:
    deadline = time.time() + seconds
    while not (value := found()):
        assert time.time() < deadline, f"never: {what}"
        time.sleep(0.02)
    return value


def events(gate, key: str) -> list[dict]:
    return [event for _, event in list(gate.session(key).events)]


def asks(gate, key: str) -> list[dict]:
    return [event for event in events(gate, key) if event["t"] == "permission"]


def the_ask(gate, key: str, **like) -> dict:
    """The last state of the conversation's ask, once it is as `like` says."""
    return wait_for(lambda: next((a for a in reversed(asks(gate, key)) if all(a.get(k) == v for k, v in like.items())), None),
                    f"an ask like {like}")


def answers(gate, key: str) -> list[dict]:
    return [event for event in events(gate, key) if event["t"] == "done" and not event.get("error")]


def calls(folder: Path) -> list[dict]:
    log = folder / "auth.log"
    return [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []


def logins(folder: Path, command: list[str]) -> list[dict]:
    return [call for call in calls(folder) if call["args"] == command]


def received(folder: Path) -> list[str]:
    log = folder / "received.log"
    return [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []


def alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    # A child that has ended but is not yet reaped still answers; its state says it is gone.
    with os.popen(f"ps -o stat= -p {pid}") as ps:
        return not ps.read().strip().startswith("Z")


def failed(gate, key: str, words: str = "Plan the week", context: dict | None = None, settings: dict | None = None) -> dict:
    """A message sent the way the app sends it, to an agent that is signed out: the conversation's ask, once it is there."""
    gate.send(key, words, context or {}, settings or CLAUDE)
    return the_ask(gate, key)


def test_a_turn_that_fails_because_claude_is_signed_out_ends_with_the_sign_in_ask(scratch_dir) -> None:
    """The raw error went into the field once per message. Now the turn ends with one ask, the field's own form, with one
    button; the CLI's words go only to the log. Nothing runs before the click but the check that it is signed out, made under
    the app's config folder."""
    with homes(scratch_dir) as home, gateway(scratch_dir) as (_, gate, workspace):
        signed_out(home["CLAUDE_CONFIG_DIR"])
        key = str(uuid.uuid4())
        ask = failed(gate, key)
        assert (ask["title"], ask["note"], ask["options"]) == (TITLE, ASKED, [SIGN_IN])
        (done,) = [event for event in events(gate, key) if event["t"] == "done"]
        assert done["error"] is True and done["detail"] == "" and done["signin"] is True
        assert not any(EXPIRED in json.dumps(event) for event in events(gate, key))
        assert logins(workspace, ["auth", "status"])[0]["config"] == str(home["CLAUDE_CONFIG_DIR"])
        assert not logins(workspace, ["auth", "login"])
        assert list(gate.session(key).asks) == [ask["requestId"]]
    log = (scratch_dir / "state" / "agent.log").read_text()
    assert "signin_needed provider=claude" in log and EXPIRED in log


def test_any_other_error_shows_as_it_does_today(scratch_dir) -> None:
    """Only a turn the CLI's words call signed out, and that `claude auth status` confirms, asks for the sign-in: the same
    words from a CLI that is signed in are the error they are."""
    with homes(scratch_dir), gateway(scratch_dir) as (_, gate, _workspace):
        for words, detail in (("Plan the week [fail]", "The fake agent failed on purpose."), ("Plan the week [authfail]", EXPIRED)):
            key = str(uuid.uuid4())
            gate.send(key, words, {}, CLAUDE)
            done = wait_for(lambda: next((e for e in events(gate, key) if e["t"] == "done"), None), "the turn's end")
            assert done["error"] is True and done["detail"] == detail and "signin" not in done, words
            assert not asks(gate, key), words


def test_sign_in_runs_the_login_under_the_apps_config_folder_and_links_the_page_it_prints(scratch_dir) -> None:
    with homes(scratch_dir) as home, gateway(scratch_dir) as (_, gate, workspace):
        signed_out(home["CLAUDE_CONFIG_DIR"])
        key = str(uuid.uuid4())
        ask = failed(gate, key)
        gate.decide(key, ask["requestId"], "signin")
        waiting = the_ask(gate, key, note=WAITING, options=[PAGE])
        # The same ask, changed: the page draws it in place of the one it was.
        assert waiting["requestId"] == ask["requestId"] and waiting["title"] == TITLE
        assert not [e for e in events(gate, key) if e["t"] == "permission_done"]
        (login,) = wait_for(lambda: logins(workspace, ["auth", "login"]), "the login")
        assert login["config"] == str(home["CLAUDE_CONFIG_DIR"]) and alive(login["pid"])
        gate.decide(key, ask["requestId"], "page")
        opened = wait_for(lambda: (scratch_dir / "opened.log").exists() and (scratch_dir / "opened.log").read_text(), "the page")
        assert opened == "ARG https://claude.ai/oauth/authorize?code=true&client_id=sample-client&state=sample-state\n"
        assert list(gate.session(key).asks) == [ask["requestId"]]  # still waiting for the sign-in


def test_once_signed_in_the_message_goes_again_once_with_what_it_was_sent_with(scratch_dir) -> None:
    """A Replan's context, the conversation's settings and its words: the turn that failed is the turn that runs, once."""
    context = {"today": "2026-10-07", "now": "2026-10-07 09:00",
               "replan": {"column": "year", "plans": [{"id": "SYNPLN01", "title": "Plan to sort"}]}}
    settings = {"provider": "claude", "permission": "manual"}
    with homes(scratch_dir) as home, gateway(scratch_dir) as (_, gate, workspace):
        signed_out(home["CLAUDE_CONFIG_DIR"])
        key = str(uuid.uuid4())
        ask = failed(gate, key, "Sort these plans", context, settings)
        gate.decide(key, ask["requestId"], "signin")
        the_ask(gate, key, note=WAITING)
        (login,) = wait_for(lambda: logins(workspace, ["auth", "login"]), "the login")
        signed_in(home["CLAUDE_CONFIG_DIR"])
        wait_for(lambda: answers(gate, key), "the answer")
        ended = [e for e in events(gate, key) if e["t"] == "permission_done"]
        assert ended == [{"t": "permission_done", "requestId": ask["requestId"], "label": "Signed in", "says": "Signed in"}]
        first, again = received(workspace)
        assert again == first and "The plans that carried over on the board, 1 in all" in again and again.endswith("Sort these plans")
        starts = [json.loads(line) for line in (workspace / "argv.log").read_text().splitlines()]
        assert len(starts) == 2 and all(start[start.index("--permission-mode") + 1] == "manual" for start in starts)
        assert answers(gate, key)[0]["detail"] == "" and wait_for(lambda: not alive(login["pid"]), "the login stopped")
        time.sleep(0.3)  # several checks later: once, not again
        assert len(received(workspace)) == 2 and len(answers(gate, key)) == 1 and not gate.session(key).asks
    log = (scratch_dir / "state" / "agent.log").read_text()
    assert "signin signed_in provider=claude" in log and "sample-state" not in log


def test_the_morning_turn_runs_again_as_the_morning_turn(scratch_dir) -> None:
    with homes(scratch_dir) as home, gateway(scratch_dir) as (_, gate, workspace):
        signed_out(home["CLAUDE_CONFIG_DIR"])
        key = str(uuid.uuid4())
        ask = failed(gate, key, "Make my morning report", {"now": "2026-10-07 07:00"}, {"provider": "claude", "sources": "connected"})
        gate.decide(key, ask["requestId"], "signin")
        the_ask(gate, key, note=WAITING)
        signed_in(home["CLAUDE_CONFIG_DIR"])
        wait_for(lambda: answers(gate, key), "the answer")
        starts = [json.loads(line) for line in (workspace / "argv.log").read_text().splitlines()]
        for start in starts:
            assert "## This turn: the morning report" in start[start.index("--append-system-prompt") + 1]
            assert json.loads(start[start.index("--settings") + 1])["permissions"] == {"ask": ["mcp__*"]}
        assert len(starts) == 2


def test_a_message_sent_while_the_ask_is_open_waits_and_goes_after_the_one_that_failed(scratch_dir) -> None:
    with homes(scratch_dir) as home, gateway(scratch_dir) as (_, gate, workspace):
        signed_out(home["CLAUDE_CONFIG_DIR"])
        key = str(uuid.uuid4())
        ask = failed(gate, key, "First")
        gate.send(key, "Second", {}, CLAUDE)
        gate.send(key, "Third", {}, CLAUDE, mode="now")
        time.sleep(0.3)
        assert len(received(workspace)) == 1 and len(asks(gate, key)) == 1  # no second failure, no second ask
        assert [e["text"] for e in events(gate, key) if e["t"] == "user"] == ["First", "Second", "Third"]
        gate.decide(key, ask["requestId"], "signin")
        signed_in(home["CLAUDE_CONFIG_DIR"])
        wait_for(lambda: len(answers(gate, key)) == 3, "three answers")
        assert [words.rsplit("\n\n", 1)[-1] for words in received(workspace)] == ["First", "First", "Second", "Third"]
        # The agent starts afresh for it and is told nothing of the messages that came after it as if they were before.
        assert "<previous_conversation>" not in received(workspace)[1]
        assert len({a["requestId"] for a in asks(gate, key)}) == 1


def test_a_login_that_ends_without_a_sign_in_brings_back_sign_in_and_open_in_terminal(scratch_dir) -> None:
    """Terminal runs the same command, under the app's config folder, for when the sign-in asks for a code to be typed; the
    checks go on while it is open, and the message goes again once signed in there."""
    with homes(scratch_dir) as home, gateway(scratch_dir) as (_, gate, workspace):
        signed_out(home["CLAUDE_CONFIG_DIR"], login="exit")
        key = str(uuid.uuid4())
        ask = failed(gate, key)
        gate.decide(key, ask["requestId"], "signin")
        again = the_ask(gate, key, options=[SIGN_IN, TERMINAL])
        assert again["note"] == ASKED and again["requestId"] == ask["requestId"]
        gate.decide(key, ask["requestId"], "terminal")
        opened = wait_for(lambda: (scratch_dir / "opened.log").exists() and (scratch_dir / "opened.log").read_text(),
                          "Terminal").splitlines()
        script = scratch_dir / "state" / "open" / "claude-sign-in.command"
        assert opened[:3] == ["ARG -a", "ARG Terminal", f"ARG {script}"]
        assert f"export CLAUDE_CONFIG_DIR={shlex.quote(str(home['CLAUDE_CONFIG_DIR']))}" in opened
        assert opened[-1] == f"exec {shlex.quote(str(FAKE_AGENTS / 'claude'))} auth login" and script.stat().st_mode & 0o777 == 0o700
        signed_in(home["CLAUDE_CONFIG_DIR"])
        wait_for(lambda: answers(gate, key), "the answer")
        assert len(logins(workspace, ["auth", "login"])) == 1  # Terminal's own run is not the app's


def test_after_five_minutes_the_login_stops_and_both_buttons_come_back(scratch_dir) -> None:
    with homes(scratch_dir) as home, gateway(scratch_dir) as (_, gate, workspace):
        signed_out(home["CLAUDE_CONFIG_DIR"], login="silent")
        gate.signin.limit = 0.6
        key = str(uuid.uuid4())
        ask = failed(gate, key)
        gate.decide(key, ask["requestId"], "signin")
        the_ask(gate, key, note=WAITING, options=[])  # no address printed: nothing to open
        (login,) = wait_for(lambda: logins(workspace, ["auth", "login"]), "the login")
        assert alive(login["pid"])
        the_ask(gate, key, note=ASKED, options=[SIGN_IN, TERMINAL])
        wait_for(lambda: not alive(login["pid"]), "the login stopped")
        assert not answers(gate, key) and len(received(workspace)) == 1


def test_two_conversations_get_an_ask_each_and_share_the_one_login(scratch_dir) -> None:
    with homes(scratch_dir) as home, gateway(scratch_dir) as (_, gate, workspace):
        signed_out(home["CLAUDE_CONFIG_DIR"])
        one, two = str(uuid.uuid4()), str(uuid.uuid4())
        first, second = failed(gate, one, "In the first"), failed(gate, two, "In the second")
        gate.decide(one, first["requestId"], "signin")
        the_ask(gate, one, note=WAITING)
        gate.decide(two, second["requestId"], "signin")
        the_ask(gate, two, note=WAITING, options=[PAGE])  # the address the running login printed
        assert len(logins(workspace, ["auth", "login"])) == 1
        signed_in(home["CLAUDE_CONFIG_DIR"])
        wait_for(lambda: answers(gate, one) and answers(gate, two), "both answers")
        assert sorted(words.rsplit("\n\n", 1)[-1] for words in received(workspace)) == [
            "In the first", "In the first", "In the second", "In the second"]


def test_closing_the_conversation_stops_the_login(scratch_dir) -> None:
    with homes(scratch_dir) as home, gateway(scratch_dir) as (_, gate, workspace):
        signed_out(home["CLAUDE_CONFIG_DIR"])
        key = str(uuid.uuid4())
        ask = failed(gate, key)
        gate.decide(key, ask["requestId"], "signin")
        the_ask(gate, key, note=WAITING)
        (login,) = wait_for(lambda: logins(workspace, ["auth", "login"]), "the login")
        gate.reset(key)
        wait_for(lambda: not alive(login["pid"]), "the login stopped")
        signed_in(home["CLAUDE_CONFIG_DIR"])
        time.sleep(0.3)
        assert len(received(workspace)) == 1  # nobody waits for it now


def test_codex_signs_in_the_same_way_with_its_own_commands(scratch_dir) -> None:
    """Codex is not on the machines these tests run on: its fake knows `codex login` and `codex login status`, whose exit code
    says signed in, and the gateway reaches both through the agent table, under Codex's own home."""
    settings = {"provider": "codex", "permission": "read-only"}
    with homes(scratch_dir) as home, gateway(scratch_dir, codex=True) as (_, gate, workspace):
        signed_out(home["CODEX_HOME"])
        key = str(uuid.uuid4())
        ask = failed(gate, key, "Plan the week", {"now": "2026-10-07 09:00"}, settings)
        assert (ask["title"], ask["note"], ask["options"]) == ("Codex is signed out on this Mac", ASKED, [SIGN_IN])
        assert logins(workspace, ["login", "status"])[0]["home"] == str(home["CODEX_HOME"])
        gate.decide(key, ask["requestId"], "signin")
        the_ask(gate, key, note=WAITING, options=[PAGE])
        (login,) = wait_for(lambda: logins(workspace, ["login"]), "the login")
        assert login["home"] == str(home["CODEX_HOME"])
        signed_in(home["CODEX_HOME"])
        wait_for(lambda: answers(gate, key), "the answer")
        first, again = received(workspace)
        assert again == first and again.endswith("Plan the week")
