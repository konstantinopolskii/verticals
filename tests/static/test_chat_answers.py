"""The chat gateway marks each answer for the MCP server (docs/design/agent-answer-undo.md): a turn is one answer, opened at the
server before the agent hears the words and closed before the page hears of the end, and every call of an agent carries its
conversation, which is how the server tells whose write it is. What is run here is the gateway's own code against real local
HTTP servers standing in for the MCP server, and a stand-in `codex` command: no model, no network, no database.

Codex is covered here and only here: its CLI is not on this machine, so what is proved is what the gateway does around it: the
conversation is in the environment its stdio proxy gets, the proxy forwards it on every request, and the isolation check that
runs `codex mcp list` is passed the same names."""

from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
import threading
import types
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from tests.static.test_chat_gateway import _chat

ROOT = Path(__file__).resolve().parents[2]
SESSION = "00000000-0000-4000-8000-0000000000aa"


class Standin:
    """A real HTTP server on a free port that remembers what it was asked and answers what it was told to."""

    def __init__(self, reply: dict | None = None, recent: list | None = None, echo: bool = False) -> None:
        self.requests: list[dict] = []
        standin = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
                headers = {k.lower(): v for k, v in self.headers.items()}  # urllib capitalises names its own way
                standin.requests.append({"path": self.path, "body": body, "headers": headers})
                if echo:  # a JSON-RPC server: the answer carries the id of the request
                    payload = {"jsonrpc": "2.0", "id": body.get("id"), "result": {}}
                else:
                    payload = {"answers": recent or []} if self.path.endswith("/recent") else (reply or {"ok": True})
                answer = json.dumps(payload).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(answer)))
                self.send_header("Mcp-Session-Id", "server-side-session")
                self.end_headers()
                self.wfile.write(answer)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}/mcp"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def routes(self) -> list[str]:
        return [r["path"].removeprefix("/answers/") for r in self.requests if r["path"].startswith("/answers/")]

    def stop(self) -> None:
        self.server.shutdown()
        self.server.server_close()  # the port refuses at once, as a server that is gone does


@pytest.fixture
def mcp_server() -> Iterator[Standin]:
    standin = Standin()
    yield standin
    standin.stop()


class _Agent:
    """The agent of a turn: when it is sent the words it notes what the MCP server had heard by then, and ends the turn."""

    provider = "claude"

    def __init__(self, seen: list, standin: Standin, chat, session, settings, resume) -> None:
        self.seen, self.standin, self.session = seen, standin, session
        self.session_id = "agent-session"

    def signature(self):
        return {}

    def send(self, text):
        self.seen.append(list(self.standin.routes()))
        self.session.turn_done(False, "")


def _turn(chat_module, standin: Standin, tmp_path: Path):
    """A conversation whose one turn runs against `standin`, with the events it emitted and what the server had heard when the
    agent was sent the words and when `done` was emitted."""
    chat = chat_module.Chat(tmp_path, standin.url, "tok")
    chat_module.which = lambda provider: "claude"
    seen: list = []
    # The gateway starts an agent in its session's folder (`cwd`, `rebuild_prompt`: docs/design/task-sessions.md).
    chat_module.AGENT_CLASSES = {"claude": lambda c, s, settings, resume, **_: _Agent(seen, standin, c, s, settings, resume)}
    chat_module.AGENT_CLASSES["claude"].signature_of = staticmethod(lambda settings: {})
    session = chat.session(SESSION)
    emitted = session.emit
    heard_at_done: list = []

    def emit(event):
        if event["t"] == "done":
            heard_at_done.append(list(standin.routes()))
        emitted(event)

    session.emit = emit
    chat.start_turn(session, "Plan the week", {}, chat_module.clean_settings({}))
    return session, seen, heard_at_done


def test_a_turn_is_one_answer_opened_before_the_agent_hears_the_words_and_closed_before_the_page_hears_the_end(
    mcp_server: Standin, tmp_path: Path,
) -> None:
    session, at_send, at_done = _turn(_chat(), mcp_server, tmp_path)

    start = next(e for _, e in session.events if e["t"] == "turn_start")
    end = next(e for _, e in session.events if e["t"] == "done")
    assert start["answer"] and start["answer"] == end["answer"], "the page can tell which answer began and which ended"
    assert at_send == [["open"]], "opened at the server before the agent was sent the words"
    assert at_done == [["open", "close"]], "closed at the server before `done` was emitted"
    opened, closed = mcp_server.requests
    assert opened["body"] == {"session": SESSION, "answer": start["answer"]} and closed["body"] == {"answer": start["answer"]}
    assert opened["headers"]["authorization"] == "Bearer tok", "under the token the server asks for"


def test_the_next_turn_is_another_answer(mcp_server: Standin, tmp_path: Path) -> None:
    chat_module = _chat()
    session, _, _ = _turn(chat_module, mcp_server, tmp_path)
    first = [e for _, e in session.events if e["t"] == "done"][-1]["answer"]
    session.chat.start_turn(session, "And again", {}, chat_module.clean_settings({}))

    second = [e for _, e in session.events if e["t"] == "done"][-1]["answer"]
    assert second and second != first
    assert mcp_server.routes() == ["open", "close", "open", "close"]


def test_a_turn_runs_when_there_is_no_server_to_keep_the_answer(tmp_path: Path) -> None:
    gone = Standin()
    gone.stop()  # the port is closed again: the record cannot be reached
    session, at_send, _ = _turn(_chat(), gone, tmp_path)

    done = next(e for _, e in session.events if e["t"] == "done")
    assert done["error"] is False and done["answer"], "the conversation went on as it did"
    assert at_send == [[]]


def test_a_turn_that_cannot_start_is_closed_too(mcp_server: Standin, tmp_path: Path) -> None:
    chat_module = _chat()
    chat = chat_module.Chat(tmp_path, mcp_server.url, "tok")

    def broken(c, s, settings, resume, **_):
        raise chat_module.ChatError("The agent is not running")

    chat_module.which = lambda provider: "claude"
    chat_module.AGENT_CLASSES = {"claude": broken}
    session = chat.session(SESSION)
    chat.start_turn(session, "Plan the week", {}, chat_module.clean_settings({}))

    done = next(e for _, e in session.events if e["t"] == "done")
    assert done["error"] is True and done["answer"]
    assert mcp_server.routes() == ["close"], "never opened, so there is only the close that makes sure"


def test_an_agent_that_exits_during_a_turn_ends_its_answer(mcp_server: Standin, tmp_path: Path) -> None:
    chat_module = _chat()
    chat = chat_module.Chat(tmp_path, mcp_server.url, "tok")
    session = chat.session(SESSION)
    agent = types.SimpleNamespace()
    session.agent, session.running, session.answer = agent, True, "abc123"

    session.agent_exited(agent, 1, "boom")

    exit_event = next(e for _, e in session.events if e["t"] == "exit")
    assert exit_event["answer"] == "abc123" and mcp_server.requests[-1]["body"] == {"answer": "abc123"}


def test_the_page_is_handed_what_the_server_says_ended_and_what_became_of_an_answer_is_told_to_it(tmp_path: Path) -> None:
    ended = [{"id": "a1", "session": SESSION, "state": "standing", "writes": [{"seq": 1, "tool": "update", "changes": []}]}]
    standin = Standin(recent=ended)
    try:
        chat = _chat().Chat(tmp_path, standin.url, "tok")
        assert chat.recent_answers() == ended
        assert chat.recent_answers() == ended, "reading takes nothing away"
        assert standin.requests[-1]["path"] == "/answers/recent" and standin.requests[-1]["headers"]["authorization"] == "Bearer tok"
        chat.answer_state("a1", "undone")
        assert standin.requests[-1]["path"] == "/answers/state" and standin.requests[-1]["body"] == {"answer": "a1", "state": "undone"}
        chat.answer_state(None, "undone")  # not an answer: nothing is sent
        chat.answer_state("a1", 7)
        assert standin.routes().count("state") == 1
    finally:
        standin.stop()
    assert chat.recent_answers() == [], "no server, nothing handed over, and no error"
    chat.answer_state("a1", "standing")  # and nothing raised


def test_claude_connects_with_its_conversation_in_the_headers_in_a_private_file(tmp_path: Path) -> None:
    chat_module = _chat()
    chat = chat_module.Chat(tmp_path, "http://127.0.0.1:8281/mcp", "tok")

    path = chat.claude_config(SESSION)

    assert stat.S_IMODE(path.stat().st_mode) == 0o600, "the token is in it"
    config = json.loads(path.read_text())["mcpServers"]["verticals"]
    assert config["url"] == "http://127.0.0.1:8281/mcp"
    assert config["headers"] == {"Authorization": "Bearer tok", "X-Verticals-Session": SESSION}
    assert chat.claude_config(SESSION) == path and chat.claude_config("00000000-0000-4000-8000-0000000000bb") != path

    chat.reset(SESSION)
    assert not path.exists(), "a conversation that is reset takes its connection file with it"
    chat.claude_config(SESSION)
    chat.shutdown()
    assert not list(tmp_path.glob("chat-mcp-*.json")), "and none stays behind when the gateway stops"


def test_claude_is_started_on_the_file_of_its_own_conversation(tmp_path: Path) -> None:
    chat_module = _chat()
    started: list = []

    class Process:
        def __init__(self, args, cwd, env, handle, exited):
            started.append(args)

        def send(self, message):
            pass

    chat_module.JsonProcess, chat_module.which = Process, lambda provider: "claude"
    chat = chat_module.Chat(tmp_path, "http://127.0.0.1:8281/mcp", "tok")
    session = types.SimpleNamespace(id=SESSION, emit=lambda event: None)
    chat_module.ClaudeAgent(chat, session, chat_module.clean_settings({}), None)

    args = started[0]
    assert args[args.index("--mcp-config") + 1] == str(tmp_path / f"chat-mcp-{SESSION}.json")


# --- Codex ---------------------------------------------------------------------------------------------------------


def test_codex_is_given_its_conversation_in_the_environment_its_proxy_reads(tmp_path: Path) -> None:
    chat_module = _chat()
    made: list = []

    class Rpc:
        def __init__(self, argv, cwd, env, on_notify, on_request, on_exit):
            made.append({"argv": argv, "env": env})

        def request(self, method, params, timeout=45):
            return {"thread": {"id": "thread-1"}} if method == "thread/start" else {}

        def notify(self, method, params):
            pass

    chat_module.RpcProcess, chat_module.which = Rpc, lambda provider: "codex"
    chat_module.codex_args = lambda chat, settings=None, reads=None: ["codex", "app-server"]
    chat = chat_module.Chat(tmp_path, "http://127.0.0.1:8281/mcp", "tok")
    session = types.SimpleNamespace(id=SESSION, settings={}, emit=lambda event: None)

    chat_module.CodexAgent(chat, session, chat_module.clean_settings({"provider": "codex"}), None)

    env = made[0]["env"]
    assert (env["VERTICALS_MCP_URL"], env["VERTICALS_MCP_TOKEN"], env["VERTICALS_MCP_SESSION"]) == (
        "http://127.0.0.1:8281/mcp", "tok", SESSION,
    )


def test_codexs_connection_lets_the_conversation_through_to_the_proxy(tmp_path: Path) -> None:
    """`codex_args` runs for real against a stand-in `codex` that answers `mcp list --json` and notes its command line."""
    chat_module = _chat()
    bin_dir, noted = tmp_path / "bin", tmp_path / "argv.json"
    bin_dir.mkdir()
    script = bin_dir / "codex"
    script.write_text(
        "#!/usr/bin/env python3\nimport json, sys\n"
        f"open({str(noted)!r}, 'w').write(json.dumps(sys.argv[1:]))\n"
        "print(json.dumps([{'name': 'verticals_desktop', 'enabled': True}]))\n"
    )
    script.chmod(0o755)
    home = tmp_path / "codex-home"
    home.mkdir()
    (home / "config.toml").write_text("")
    chat = chat_module.Chat(tmp_path, "http://127.0.0.1:8281/mcp", "tok")
    saved = {k: os.environ.get(k) for k in ("PATH", "CODEX_HOME")}
    os.environ["PATH"], os.environ["CODEX_HOME"] = f"{bin_dir}:{saved['PATH']}", str(home)
    try:
        args = chat_module.codex_args(chat)
    finally:
        for key, value in saved.items():
            os.environ.pop(key, None) if value is None else os.environ.__setitem__(key, value)

    assert args[1] == "app-server"
    expected = 'mcp_servers.verticals_desktop.env_vars=["VERTICALS_MCP_URL", "VERTICALS_MCP_TOKEN", "VERTICALS_MCP_SESSION"]'
    assert expected in args, "the proxy is let see the conversation it belongs to"
    assert expected in json.loads(noted.read_text()), "and the isolation check was run with the same names"


def test_the_proxy_puts_the_conversation_and_the_token_on_every_request_it_relays(tmp_path: Path) -> None:
    standin = Standin(echo=True)
    env = dict(os.environ) | {"VERTICALS_MCP_URL": standin.url, "VERTICALS_MCP_TOKEN": "tok", "VERTICALS_MCP_SESSION": SESSION}
    try:
        proc = subprocess.run(
            [sys.executable, str(ROOT / "desktop" / "chat" / "mcp_proxy.py")], env=env, capture_output=True, text=True, timeout=30,
            input="\n".join(json.dumps({"jsonrpc": "2.0", "id": n, "method": method, "params": {}}) for n, method in
                            ((1, "initialize"), (2, "tools/call"))) + "\n",
        )
    finally:
        standin.stop()

    assert proc.returncode == 0, proc.stderr
    assert len(standin.requests) == 2
    for request in standin.requests:
        assert request["headers"]["authorization"] == "Bearer tok"
        assert request["headers"]["x-verticals-session"] == SESSION
    assert "mcp-session-id" not in standin.requests[0]["headers"] and standin.requests[1]["headers"]["mcp-session-id"] == "server-side-session"
    assert [json.loads(line)["id"] for line in proc.stdout.splitlines()] == [1, 2], "and the answers come back on stdout"


def test_the_proxy_without_a_conversation_sends_none(tmp_path: Path) -> None:
    standin = Standin(echo=True)
    env = {k: v for k, v in os.environ.items() if k != "VERTICALS_MCP_SESSION"} | {"VERTICALS_MCP_URL": standin.url, "VERTICALS_MCP_TOKEN": "tok"}
    try:
        subprocess.run([sys.executable, str(ROOT / "desktop" / "chat" / "mcp_proxy.py")], env=env, capture_output=True, text=True,
                       timeout=30, input=json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {}}) + "\n")
    finally:
        standin.stop()

    assert "x-verticals-session" not in standin.requests[0]["headers"], "an agent outside the app is nobody's answer"


def test_codex_full_access_keeps_connected_tools_and_approves_their_calls(tmp_path, monkeypatch):
    module = _chat()
    home = tmp_path / "codex-home"
    home.mkdir()
    (home / "config.toml").write_text('''[mcp_servers.notes]
command = "notes-server"
default_tools_approval_mode = "prompt"
[mcp_servers.notes.tools.read]
approval_mode = "prompt"
[plugins.sample]
enabled = true
''')
    monkeypatch.setenv("CODEX_HOME", str(home))
    module.which = lambda _: "codex"
    host = module.Chat(tmp_path, "http://127.0.0.1:9/mcp", "synthetic-token")
    script = tmp_path / "codex"
    script.write_text("#!/usr/bin/env python3\nimport json\nprint(json.dumps([{'name': 'verticals_desktop', 'enabled': True}]))\n")
    script.chmod(0o755)
    module.which = lambda _: str(script)
    made = []
    requests = []
    class Rpc:
        def __init__(self, argv, *rest):
            made.append(argv)
        def request(self, method, params):
            requests.append((method, params))
            return {"thread": {"id": "thread-1"}} if method == "thread/start" else {}
        def notify(self, *args):
            pass
    module.RpcProcess = Rpc
    session = types.SimpleNamespace(id=SESSION, settings={}, emit=lambda event: None)
    module.CodexAgent(host, session, module.clean_settings({"provider": "codex", "permission": "full-access"}), None)
    args = made[0]
    assert "mcp_servers.notes.enabled=false" not in args
    assert "plugins.sample.enabled=false" not in args
    assert 'mcp_servers.verticals_desktop.default_tools_approval_mode="approve"' in args
    assert 'mcp_servers.notes.default_tools_approval_mode="approve"' in args
    assert 'mcp_servers.notes.tools.read.approval_mode="approve"' in args
    assert "features.shell_tool=false" not in args
    start = next(params for method, params in requests if method == "thread/start")
    assert start["approvalPolicy"] == "never" and start["sandbox"] == "danger-full-access"
    assert start["config"]["features.shell_tool"] is True
