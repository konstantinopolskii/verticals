"""The desktop app's task link and the lines that connect Claude Code and Codex (docs/design/task-sessions.md). The Swift is
`desktop/macos/AppLinks.swift`, compiled alone with `tests/static/app_links_check.swift` and run on fixed inputs: nothing is
launched, no window opens, and neither agent is run (`claude mcp add-json` and `codex mcp add` are only built as lines of words,
here, and read). What the window does with a link, and what the menu bar shows, can't be looked at without running the app: they
are the PR's owner checks."""

from __future__ import annotations

import json
import plistlib
import re
import shutil
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from tests.harness.report import gate
from tests.static.conftest import REPO_ROOT

SWIFT = REPO_ROOT / "desktop" / "macos" / "AppLinks.swift"
CHECK = REPO_ROOT / "tests" / "static" / "app_links_check.swift"
RELAY = REPO_ROOT / "desktop" / "chat" / "mcp_proxy.py"
MCP_URL = "http://127.0.0.1:8281/mcp"


@pytest.fixture(scope="module")
def checked(tmp_path_factory: pytest.TempPathFactory) -> dict:
    """What AppLinks.swift makes of the fixed inputs, as the checking program prints it. The folder of the state has a quote in
    its name: the line that reads the token has to quote it."""
    swiftc = shutil.which("swiftc")
    if swiftc is None:
        gate("no Swift compiler (swiftc) on this machine")
    work = tmp_path_factory.mktemp("app_links")
    program = work / "check"
    built = subprocess.run(
        [swiftc, "-parse-as-library", "-module-cache-path", str(work / "modules"), "-o", str(program), str(SWIFT), str(CHECK)],
        capture_output=True, text=True, timeout=600,
    )
    assert built.returncode == 0, built.stderr[-3000:]
    state = work / "it's a state folder"
    state.mkdir()
    headers = state / "mcp-headers.json"
    headers.write_text(json.dumps({"Authorization": "Bearer sample-token"}))
    ran = subprocess.run([str(program), str(headers)], capture_output=True, text=True, timeout=60)
    assert ran.returncode == 0, ran.stderr
    return {**json.loads(ran.stdout), "headers_file": headers}


def test_a_task_link_names_the_task_and_nothing_else(checked: dict) -> None:
    """`verticals://goal/<id>`: the id is letters, digits, `-` and `_` up to 100, the same as the link tool takes."""
    assert checked["accepted"] == ["AB12cd34", "x_y-z", "AB12cd34", "AB12cd34"]
    assert set(checked["refused"]) == {"-"} and len(checked["refused"]) == 13
    assert checked["longest"] == 100


def test_the_board_opens_a_task_by_its_own_address(checked: dict) -> None:
    """The page reads `#goal/<id>` at start and on `popstate` (web/src/lib/urlState.ts; tests/ui/test_task_sessions.py loads it)."""
    assert checked["fragment"] == "goal/AB12cd34"
    assert checked["board"] == "http://127.0.0.1:8288/#goal/AB12cd34"
    assert checked["boardOver"] == checked["board"]  # the path and fragment of the page it was on are not carried over
    assert checked["boardRefused"] == "-"


def test_claude_code_reads_the_token_from_the_owner_only_file_when_it_connects(checked: dict) -> None:
    """The line is the one the menu bar's "Connect Claude Code" has always run, under the new name; the token is not in it."""
    assert checked["claudeAdd"] == ["mcp", "add-json", "--scope", "user", "verticals-desktop"]
    assert checked["claudeRemove"] == ["mcp", "remove", "--scope", "user", "verticals-desktop"]
    server = checked["claudeServer"]
    assert (server["type"], server["url"]) == ("http", MCP_URL) and set(server) == {"type", "url", "headersHelper"}
    assert "sample-token" not in json.dumps(checked, default=str)
    # What Claude Code runs to get its headers prints the file, whatever the folder's name holds (a quote, spaces).
    printed = subprocess.run(["/bin/sh", "-c", server["headersHelper"]], capture_output=True, text=True, timeout=20)
    assert printed.returncode == 0 and json.loads(printed.stdout) == {"Authorization": "Bearer sample-token"}


def test_codex_is_given_the_relay_the_address_and_the_file_never_the_token(checked: dict) -> None:
    python = "/Applications/Verticals.app/Contents/Resources/python/bin/python3"
    relay = "/Applications/Verticals.app/Contents/Resources/desktop/chat/mcp_proxy.py"
    assert checked["codexAdd"] == [
        "mcp", "add", "verticals", "--env", f"VERTICALS_MCP_URL={MCP_URL}",
        "--env", f"VERTICALS_MCP_HEADERS={checked['headers_file']}", "--", python, relay,
    ]
    assert checked["codexRemove"] == ["mcp", "remove", "verticals"]
    # The name is not the one the app's own Codex keeps for itself (desktop/chat/chat.py refuses a config that uses it).
    chat_source = (REPO_ROOT / "desktop" / "chat" / "chat.py").read_text()
    assert "verticals_desktop" in chat_source and "verticals_desktop" not in checked["codexAdd"]


def test_agents_env_points_the_agents_at_a_sign_in_and_sets_nothing_else(checked: dict) -> None:
    """`agents.env` in the state folder: an app opened from Finder never sees the owner's shell, so this is how its Claude Code
    and Codex use another account's folder. Only those two variables, only absolute paths after `~` is the home folder."""
    assert checked["agentEnv"] == {"CLAUDE_CONFIG_DIR": "/Users/sample/.claude-personal", "CODEX_HOME": "/Users/sample/codex home"}
    assert checked["agentEnvRelative"] == {"CODEX_HOME": "/Users/sample"}


def test_the_bundle_registers_the_verticals_scheme_and_compiles_the_link_file() -> None:
    """Info.plist is written by desktop/macos/bundle.py: it names the scheme the app opens, and the compile line has AppLinks.swift."""
    source = (REPO_ROOT / "desktop" / "macos" / "bundle.py").read_text()
    plist = re.search(r'Info\.plist"\)\.write_text\(f"""(.*?)"""\)', source, re.S)
    assert plist, "the Info.plist template was not found in bundle.py"
    info = plistlib.loads(plist.group(1).replace("{VERSION}", "0.0.0").encode())
    assert info["CFBundleURLTypes"] == [{"CFBundleURLName": "app.verticals.desktop.task", "CFBundleURLSchemes": ["verticals"]}]
    assert '"AppLinks.swift"' in source


class _Mcp(BaseHTTPRequestHandler):
    """A local stand-in for the MCP endpoint: answers every JSON-RPC message and keeps the Authorization it came with."""

    seen: list[str] = []

    def log_message(self, *args: object) -> None:
        pass

    def do_POST(self) -> None:  # noqa: N802
        message = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        _Mcp.seen.append(self.headers.get("Authorization", ""))
        body = json.dumps({"jsonrpc": "2.0", "id": message["id"], "result": {"ok": True}}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def _ask_through_the_relay(env: dict[str, str], messages: int = 1) -> list[dict]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Mcp)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        env = {"VERTICALS_MCP_URL": f"http://127.0.0.1:{server.server_address[1]}/mcp", "PATH": "/usr/bin:/bin", **env}
        lines = "".join(json.dumps({"jsonrpc": "2.0", "id": i, "method": "ping"}) + "\n" for i in range(1, messages + 1))
        done = subprocess.run([sys.executable, str(RELAY)], input=lines, env=env, capture_output=True, text=True, timeout=30)
        return [json.loads(line) for line in done.stdout.splitlines()] if done.returncode == 0 else [{"exit": done.returncode, "err": done.stderr}]
    finally:
        server.shutdown()


def test_the_relay_takes_its_token_from_the_file_at_every_message(tmp_path: Path) -> None:
    """A Codex the owner connected from the menu bar knows the file, not the token: a new launch writes a new one."""
    _Mcp.seen.clear()
    headers = tmp_path / "mcp-headers.json"
    headers.write_text(json.dumps({"Authorization": "Bearer first-token"}))
    answers = _ask_through_the_relay({"VERTICALS_MCP_HEADERS": str(headers)})
    assert answers == [{"jsonrpc": "2.0", "id": 1, "result": {"ok": True}}] and _Mcp.seen == ["Bearer first-token"]


def test_the_relay_the_gateway_starts_still_takes_its_token_from_the_environment(tmp_path: Path) -> None:
    _Mcp.seen.clear()
    answers = _ask_through_the_relay({"VERTICALS_MCP_TOKEN": "env-token"})
    assert answers == [{"jsonrpc": "2.0", "id": 1, "result": {"ok": True}}] and _Mcp.seen == ["Bearer env-token"]


def test_the_relay_says_so_when_the_file_is_gone(tmp_path: Path) -> None:
    answers = _ask_through_the_relay({"VERTICALS_MCP_HEADERS": str(tmp_path / "gone.json")})
    assert len(answers) == 1 and answers[0]["error"]["message"].startswith("Verticals MCP unavailable")
    assert "gone.json" in answers[0]["error"]["message"] and "Bearer" not in json.dumps(answers)
    # With neither a token nor a file it does not start.
    assert _ask_through_the_relay({})[0].get("exit") == 1
