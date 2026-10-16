"""Running a check (docs/design/sources.md, `verticals/sources/runner.py`): the five kinds against local fixtures only, a
tiny HTTP server, a real MCP server on a free port, harmless programs (`/bin/echo`, `/bin/sleep`, `/usr/bin/env`), files
in a temporary home and a fake `claude` for the connections. Nothing here reaches a service that is not made in the test."""

from __future__ import annotations

import json
import os
import secrets
import socket
import stat
import subprocess
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from verticals.core.source_checks import Check
from verticals.sources import connections, runner

STATUS = {"status": "ok", "count": 3, "nested": {"items": [{"n": 7}]}}


def run(raw: dict, **kwargs):
    return runner.run_check(Check.from_dict(raw), **kwargs)


# --- an address ------------------------------------------------------------------------------------------------------


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/slow":
            time.sleep(3)
        if self.path == "/redirect":
            self.send_response(302)
            self.send_header("Location", "/ok")
            self.end_headers()
            return
        status = 503 if self.path == "/down" else 200
        body = b"hello, not json" if self.path == "/text" else json.dumps(STATUS).encode()
        if self.path == "/big":
            body = b"x" * (2 * 1024 * 1024)
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        try:
            self.wfile.write(body)
        except OSError:
            pass

    def log_message(self, *args: object) -> None:
        pass


@pytest.fixture
def web() -> Iterator[str]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()


def test_an_address_that_answers_passes_with_its_status(web: str) -> None:
    result = run({"kind": "http", "url": f"{web}/ok"})
    assert (result.ok, result.detail) == (True, "HTTP 200")
    assert result.ms is not None and result.raw.startswith("HTTP 200 OK")


def test_a_field_of_the_answer_is_checked_and_a_number_is_read_from_it(web: str) -> None:
    ok = run({"kind": "http", "url": f"{web}/ok", "expect": {"status": "ok"}, "value": "nested.items.0.n", "min": 1, "max": 10})
    assert (ok.ok, ok.value, ok.detail) == (True, 7.0, 'HTTP 200, status="ok", nested.items.0.n=7')
    wrong = run({"kind": "http", "url": f"{web}/ok", "expect": {"status": "fine"}})
    assert (wrong.ok, wrong.detail) == (False, 'status is "ok", wanted "fine"')
    over = run({"kind": "http", "url": f"{web}/ok", "value": "count", "max": 2})
    assert (over.ok, over.value, over.detail) == (False, 3.0, "HTTP 200, count=3, over the limit 2")
    said = run({"kind": "http", "url": f"{web}/ok", "value": "count", "max": 2, "say": "{v} jobs waiting"})
    assert (said.ok, said.detail) == (False, "3 jobs waiting, over the limit 2")
    fine = run({"kind": "http", "url": f"{web}/ok", "value": "count", "max": 5, "say": "{v} jobs waiting"})
    assert (fine.ok, fine.detail) == (True, "3 jobs waiting")
    absent = run({"kind": "http", "url": f"{web}/ok", "value": "missing.path"})
    assert (absent.ok, absent.detail) == (False, "missing.path is null, not a number")


def test_a_wrong_status_or_an_answer_that_is_not_json_fails_with_why(web: str) -> None:
    assert run({"kind": "http", "url": f"{web}/down"}).detail == "HTTP 503"
    assert run({"kind": "http", "url": f"{web}/ok", "status": 204}).detail == "HTTP 200, wanted 204"
    assert run({"kind": "http", "url": f"{web}/down", "status": 503}).ok is True
    text = run({"kind": "http", "url": f"{web}/text", "expect": {"status": "ok"}})
    assert (text.ok, text.detail) == (False, "HTTP 200, the answer is not JSON")


def test_a_redirect_is_not_followed_and_a_huge_answer_is_cut(web: str) -> None:
    assert run({"kind": "http", "url": f"{web}/redirect"}).detail == "HTTP 302"
    big = run({"kind": "http", "url": f"{web}/big"})
    assert big.ok is True and len(big.raw) <= runner.RAW


def test_no_answer_says_so_and_does_not_wait_longer_than_the_timeout(web: str) -> None:
    started = time.monotonic()
    slow = run({"kind": "http", "url": f"{web}/slow", "timeout": 1})
    assert time.monotonic() - started < 2.5
    assert (slow.ok, slow.detail) == (False, "no answer in 1 s")
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        closed = probe.getsockname()[1]
    refused = run({"kind": "http", "url": f"http://127.0.0.1:{closed}/"})
    assert refused.ok is False and refused.detail.startswith("no answer (")


# --- a command -------------------------------------------------------------------------------------------------------


@pytest.fixture
def home(tmp_path: Path) -> Path:
    path = tmp_path / "home"
    path.mkdir()
    return path


def test_a_command_exits_well_and_a_number_in_its_output_stays_within_limits(home: Path) -> None:
    check = {"kind": "cmd", "argv": ["/bin/echo", "Filesystem 100%  used 71% of 228G"], "parse": r"(\d+)% of", "max": 90}
    ok = run(check, home=home)
    assert (ok.ok, ok.value, ok.detail) == (True, 71.0, "71 from '71% of'")
    assert ok.raw.strip() == "Filesystem 100%  used 71% of 228G", "the raw output stands beside the number"
    over = run({**check, "max": 50}, home=home)
    assert (over.ok, over.value, over.detail) == (False, 71.0, "71 from '71% of', over the limit 50")
    under = run({**check, "min": 80, "max": 90}, home=home)
    assert (under.ok, under.detail) == (False, "71 from '71% of', under the limit 80")
    none = run({**check, "parse": r"(\d+) GB"}, home=home)
    assert (none.ok, none.detail) == (False, "no number found by the pattern")
    nan = run({**check, "parse": r"(Filesystem)"}, home=home)
    assert (nan.ok, nan.detail) == (False, "'Filesystem' is not a number")
    # The first percentage on that line is another column's: a check reads the right one only if its pattern says which,
    # which is why a new check is shown once beside its raw output.
    wrong = run({**check, "parse": r"(\d+)%"}, home=home)
    assert (wrong.value, wrong.ok) == (100.0, False)
    said = run({**check, "max": 50, "say": "last exit code {v}"}, home=home)
    assert said.detail == "last exit code 71, over the limit 50"


def test_a_command_that_exits_badly_or_is_missing_says_so(home: Path) -> None:
    assert run({"kind": "cmd", "argv": ["/usr/bin/false"]}, home=home).detail == "last exit code 1"
    assert run({"kind": "cmd", "argv": ["/usr/bin/false"], "exit": 1}, home=home).ok is True
    assert run({"kind": "cmd", "argv": ["/bin/sh", "-c", "exit 3"], "exit": 1}, home=home).detail == "exit code 3, wanted 1"
    assert run({"kind": "cmd", "argv": ["no-such-program-here"]}, home=home).detail == "command not found: no-such-program-here"
    assert run({"kind": "cmd", "argv": [str(home / "absent")]}, home=home).detail.startswith("command not found")
    plain = run({"kind": "cmd", "argv": ["/bin/echo", "hi"]}, home=home)
    assert (plain.ok, plain.detail) == (True, "exit code 0")


def _length() -> str:
    """A sleep no other run of these tests has, so `pgrep` finds this process and no other."""
    return f"{20 + secrets.randbelow(9)}.{secrets.randbelow(10**6):06d}"


def _running(length: str) -> bool:
    return subprocess.run(["pgrep", "-f", f"sleep {length}"], capture_output=True).returncode == 0


def test_a_command_is_stopped_at_its_deadline_and_is_gone_when_the_call_returns(home: Path) -> None:
    length = _length()
    started = time.monotonic()
    result = run({"kind": "cmd", "argv": ["/bin/sleep", length], "timeout": 0.3}, home=home)
    assert time.monotonic() - started < 2
    assert (result.ok, result.detail) == (False, "no answer in 0.3 s")
    assert not _running(length), "killed and waited for, not left to die"


def test_a_command_that_prints_without_end_is_stopped(home: Path) -> None:
    result = run({"kind": "cmd", "argv": ["/usr/bin/yes"], "timeout": 10}, home=home)
    assert (result.ok, result.detail) == (False, "output over 256 KB")


def test_the_app_stopping_ends_a_running_command_and_is_not_answered_until_it_is_gone(home: Path) -> None:
    length = _length()
    stop = threading.Event()
    threading.Timer(0.3, stop.set).start()
    started = time.monotonic()
    assert run({"kind": "cmd", "argv": ["/bin/sleep", length], "timeout": 30}, home=home, stop=stop) is None
    assert time.monotonic() - started < 2
    assert not _running(length), "no waiting afterwards: the stop returns only when the command is gone"


def test_a_stop_ends_the_whole_group_and_a_command_that_closed_its_output_and_ran_on(home: Path) -> None:
    # Two shapes the read loop alone would miss: a child of the command (the group, not just the first process), and a
    # command that closed its output and kept running (the wait after the output is over).
    for script in ("/bin/sleep {n} & wait", "exec 1>&- 2>&-; exec /bin/sleep {n}"):
        length = _length()
        stop = threading.Event()
        threading.Timer(0.4, stop.set).start()
        started = time.monotonic()
        argv = ["/bin/sh", "-c", script.format(n=length)]
        assert run({"kind": "cmd", "argv": argv, "timeout": 30}, home=home, stop=stop) is None, script
        assert time.monotonic() - started < 2, script
        assert not _running(length), script


def test_kill_live_ends_what_is_still_running_when_the_app_closes(home: Path) -> None:
    length = _length()
    done: list = []
    worker = threading.Thread(
        target=lambda: done.append(run({"kind": "cmd", "argv": ["/bin/sleep", length], "timeout": 30}, home=home)), daemon=True)
    worker.start()
    deadline = time.monotonic() + 5
    while not _running(length):
        assert time.monotonic() < deadline, "the command never started"
        time.sleep(0.05)
    assert runner.kill_live() == 1
    assert not _running(length), "gone when kill_live returns"
    worker.join(5)
    assert not worker.is_alive() and done, "and the check that ran it comes back"


def test_a_command_is_given_a_clean_environment_in_the_home_folder(home: Path) -> None:
    environ = {"PATH": "/usr/bin:/bin", "HOME": str(home), "VERTICALS_TOKEN": "secret-token", "VERTICALS_DATABASE_URL": "postgresql://x",
               "SOME_API_KEY": "key", "LANG": "en_US.UTF-8"}
    seen = run({"kind": "cmd", "argv": ["/usr/bin/env"]}, home=home, environ=environ).raw
    assert f"HOME={home}" in seen and "LANG=en_US.UTF-8" in seen and "PATH=/usr/bin:/bin:" in seen
    assert "secret-token" not in seen and "VERTICALS" not in seen and "SOME_API_KEY" not in seen
    where = run({"kind": "cmd", "argv": ["/bin/pwd"]}, home=home, environ=environ).raw.strip()
    assert os.path.realpath(where) == os.path.realpath(home)


def test_a_command_is_found_where_the_apps_agents_find_theirs(home: Path) -> None:
    extra = home / ".local" / "bin"
    extra.mkdir(parents=True)
    tool = extra / "my-tool"
    tool.write_text("#!/bin/sh\necho found\n")
    tool.chmod(tool.stat().st_mode | stat.S_IXUSR)
    assert run({"kind": "cmd", "argv": ["my-tool"]}, home=home, environ={"PATH": "/usr/bin:/bin", "HOME": str(home)}).ok is True
    assert runner.find_exe("my-tool", home=home, path="/usr/bin") == str(tool)
    assert runner.find_exe("no-such-program-here", home=home) is None


# --- a file ----------------------------------------------------------------------------------------------------------


def _file(home: Path, name: str, text: str, *, hours: float = 0.0) -> str:
    path = home / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    old = time.time() - hours * 3600
    os.utime(path, (old, old))
    return f"~/{name}"


def test_a_file_is_fresh_and_its_last_line_says_the_right_thing(home: Path) -> None:
    path = _file(home, "logs/sync.log", "start\nwork\nOK synced 12 items\n\n", hours=1.5)
    check = {"kind": "file", "path": path, "max_age_hours": 2, "last_line": "^OK"}
    ok = run(check, home=home)
    assert (ok.ok, ok.value, ok.detail) == (True, 1.5, "1.5 h old, last line 'OK synced 12 items'")
    assert ok.raw.splitlines()[-1] == "OK synced 12 items"
    old = run({**check, "max_age_hours": 1}, home=home)
    assert (old.ok, old.detail) == (False, "1.5 h old, wanted 1 h at most")
    bad = run({**check, "last_line": "^DONE"}, home=home)
    assert (bad.ok, bad.detail) == (False, "1.5 h old, last line 'OK synced 12 items' does not match")
    assert run({"kind": "file", "path": path}, home=home).ok is True


def test_a_file_is_read_only_inside_the_home_folder(home: Path, tmp_path: Path) -> None:
    outside = tmp_path / "outside.txt"
    outside.write_text("secret\n")
    assert run({"kind": "file", "path": str(outside)}, home=home).detail == "the file is outside the home folder"
    (home / "link").symlink_to(outside)
    assert run({"kind": "file", "path": "~/link"}, home=home).detail == "the file is outside the home folder"
    assert run({"kind": "file", "path": "~/../outside.txt"}, home=home).detail == "the file is outside the home folder"
    assert run({"kind": "file", "path": "~/absent.log"}, home=home).detail == "file not found"
    (home / "folder").mkdir()
    assert run({"kind": "file", "path": "~/folder"}, home=home).detail == "not a file"


def test_a_big_file_is_read_by_its_tail(home: Path) -> None:
    path = _file(home, "big.log", "noise\n" * 200_000 + "FINAL LINE ok\n")
    result = run({"kind": "file", "path": path, "last_line": "FINAL LINE"}, home=home)
    assert result.ok is True and "FINAL LINE ok" in result.detail


# --- a host name -----------------------------------------------------------------------------------------------------


def test_a_host_name_resolves_or_does_not() -> None:
    ok = run({"kind": "dns", "host": "localhost"})
    assert ok.ok is True and ok.detail.startswith("resolves to ")
    gone = run({"kind": "dns", "host": "no-such-host.invalid"})
    assert gone.ok is False and gone.detail.startswith("does not resolve (")


# --- an MCP tool -----------------------------------------------------------------------------------------------------


@contextmanager
def _mcp_server() -> Iterator[str]:
    import uvicorn
    from mcp import types
    from mcp.server.lowlevel import Server

    async def list_tools(_ctx, _params) -> types.ListToolsResult:
        schema = {"type": "object", "properties": {}}
        return types.ListToolsResult(tools=[types.Tool(name=n, description=n, input_schema=schema) for n in ("get_status", "get_broken")])

    async def call_tool(_ctx, params) -> types.CallToolResult:
        if params.name != "get_status":
            text = "the backend is down" if params.name == "get_broken" else f"unknown tool {params.name}"
            return types.CallToolResult(content=[types.TextContent(type="text", text=text)], is_error=True)
        return types.CallToolResult(content=[types.TextContent(type="text", text=json.dumps(STATUS))],
                                    structured_content=STATUS, is_error=False)

    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    server = Server("fixture", version="1.0.0", on_list_tools=list_tools, on_call_tool=call_tool)
    app = uvicorn.Server(uvicorn.Config(server.streamable_http_app(host="127.0.0.1"), host="127.0.0.1", port=port, log_level="error"))
    thread = threading.Thread(target=app.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not app.started and time.monotonic() < deadline:
        time.sleep(0.05)
    assert app.started, "the fixture MCP server did not start"
    try:
        yield f"http://127.0.0.1:{port}/mcp"
    finally:
        app.should_exit = True
        thread.join(5)


def test_an_mcp_tool_answers_with_the_right_field_and_a_number() -> None:
    with _mcp_server() as url:
        ok = run({"kind": "mcp", "url": url, "tool": "get_status", "expect": {"status": "ok"}, "value": "count", "min": 1})
        assert (ok.ok, ok.value, ok.detail) == (True, 3.0, 'answered, status="ok", count=3')
        assert json.loads(ok.raw)["count"] == 3
        wrong = run({"kind": "mcp", "url": url, "tool": "get_status", "expect": {"count": 4}})
        assert (wrong.ok, wrong.detail) == (False, "count is 3, wanted 4")
        broken = run({"kind": "mcp", "url": url, "tool": "get_broken"})
        assert (broken.ok, broken.detail) == (False, "the tool reported an error: the backend is down")
        missing = run({"kind": "mcp", "url": url, "tool": "get_nothing"})
        assert missing.ok is False


def test_an_mcp_server_that_is_not_there_does_not_answer() -> None:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        closed = probe.getsockname()[1]
    gone = run({"kind": "mcp", "url": f"http://127.0.0.1:{closed}/mcp", "tool": "get_status", "timeout": 3})
    assert gone.ok is False and gone.detail.startswith("no answer")


# --- every connection ------------------------------------------------------------------------------------------------

LIST = """Checking MCP server health…

mail: https://mail.example.test/mcp (HTTP) - ✓ Connected
calendar: https://cal.example.test/mcp (HTTP) - ✔ Connected
notes: npx -y @example/notes-server - ✓ Connected
board: http://127.0.0.1:9000/mcp (HTTP) - ✗ Failed to connect
chat: https://chat.example.test/mcp (HTTP) - ! Needs authentication
plugin:files:files: https://files.example.test/mcp (HTTP) - ✓ Connected
project-only: ./server - ⏸ Pending approval (run `claude` to approve)
old: ./old - ⊘ Disabled for this project (re-enable via /mcp)
"""


def test_the_cli_list_is_read_by_the_words_after_the_last_dash() -> None:
    servers = {s.name: s.state for s in connections.parse(LIST)}
    assert servers == {"mail": "answers", "calendar": "answers", "notes": "answers", "board": "failed", "chat": "sign_in",
                       "plugin:files:files": "answers", "project-only": "off", "old": "off"}
    assert [s.name for s in connections.parse("\x1b[32mmail: https://x.test (HTTP) - ✓ Connected\x1b[0m\r\n")] == ["mail"]
    assert connections.parse("Checking MCP server health…\n\nNo MCP servers configured. Use `claude mcp add` to add a server.") == []
    assert connections.classify("! Connected — tools fetch failed") == "failed"
    assert connections.classify("Disconnected") == "unknown"
    assert connections.classify("✓ Connected") == "answers"


def _fake_claude(directory: Path, output: str, *, code: int = 0, sleep: float = 0, note: Path | None = None) -> str:
    directory.mkdir(parents=True, exist_ok=True)
    script = directory / "claude"
    lines = ["#!/bin/sh"]
    if note is not None:
        lines.append(f'echo "$@" > "{note}.args"; env > "{note}.env"')
    if sleep:
        lines.append(f"sleep {sleep}")
    lines.append(f"cat <<'END'\n{output}\nEND")
    lines.append(f"exit {code}")
    script.write_text("\n".join(lines) + "\n")
    script.chmod(script.stat().st_mode | stat.S_IXUSR)
    return f"{directory}:/usr/bin:/bin"  # the fake first, then what a script needs


def _ask(home: Path, path: str, *, environ: dict | None = None, stop: threading.Event | None = None, agents=("claude",)):
    return runner.run_check(Check.from_dict({"kind": "connections"}, app=True), home=home, connections=list(agents), path=path,
                            environ={} if environ is None else environ, stop=stop)


def test_the_connections_check_names_what_is_not_answering(home: Path, tmp_path: Path) -> None:
    note = tmp_path / "note"
    path = _fake_claude(tmp_path / "bin", LIST, note=note)
    result = _ask(home, path, environ={"PATH": "/usr/bin:/bin", "HOME": str(home), "VERTICALS_TOKEN": "secret-token",
                                       "CLAUDE_CONFIG_DIR": "/some/config"})
    assert result.ok is False
    assert result.detail == ("4 of 6 answer: mail, calendar, notes, plugin:files:files; "
                             "not answering: board (failed to connect), chat (needs sign-in)")
    assert result.value == 4.0 and "Needs authentication" in result.raw
    assert (tmp_path / "note.args").read_text().strip() == "mcp list"
    seen = (tmp_path / "note.env").read_text()
    assert "secret-token" not in seen and "VERTICALS" not in seen, "the app's own token never reaches the CLI"
    assert "CLAUDE_CONFIG_DIR=/some/config" in seen, "the owner's sign-in does"


def test_every_server_answering_passes_and_a_cli_that_fails_is_a_failure(home: Path, tmp_path: Path) -> None:
    good = _fake_claude(tmp_path / "good", "Checking MCP server health…\n\na: https://a.test (HTTP) - ✓ Connected\nb: ./b - ✓ Connected")
    ok = _ask(home, good)
    assert (ok.ok, ok.detail, ok.value) == (True, "all 2 answer: a, b", 2.0)
    none = _fake_claude(tmp_path / "none", "No MCP servers configured. Use `claude mcp add` to add a server.")
    empty = _ask(home, none)
    assert (empty.ok, empty.detail) == (True, "no MCP servers are set up")
    broke = _fake_claude(tmp_path / "broke", "boom", code=2)
    failed = _ask(home, broke)
    assert (failed.ok, failed.detail) == (False, "claude mcp list exited with code 2")
    nonsense = _fake_claude(tmp_path / "odd", "this is not a list")
    odd = _ask(home, nonsense)
    assert (odd.ok, odd.detail) == (False, "could not read the list from claude")
    off = _ask(home, good, agents=())
    assert off.ok is False and off.detail == "no agent is set up to ask"


def test_a_cli_that_does_not_come_back_is_given_up_on(home: Path, tmp_path: Path) -> None:
    slow = _fake_claude(tmp_path / "slow", "never read", sleep=30)
    stop = threading.Event()
    threading.Timer(0.4, stop.set).start()
    started = time.monotonic()
    assert _ask(home, slow, stop=stop) is None
    assert time.monotonic() - started < 3
