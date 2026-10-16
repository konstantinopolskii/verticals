"""Which of the agent's MCP servers answer (docs/design/sources.md, "Every connection too"): the app runs
`claude mcp list` with no model and reads one line per server. The document called Connections holds the check
(`{"kind": "connections"}`, written only by the app); this module is what runs it.

The format is the CLI's own (read from its code, version 2.1.282, and from real output):

    Checking MCP server health…

    name: https://host/mcp (HTTP) - ✓ Connected
    name: npx -y some-server - ✓ Connected
    name: https://host/mcp (HTTP) - ! Needs authentication
    name: https://host/mcp (HTTP) - ✗ Failed to connect
    name: .mcp.json server - ⏸ Pending approval (run `claude` to approve)

Read by the words after the last " - ", never by the glyph in front of them: the CLI has drawn the check mark two ways.
A server that fails to connect, needs sign-in or has a tool list that failed counts against the source; a server that is
disabled, rejected or waiting for approval is not in use and does not.

**Codex has no equivalent.** Its documented `mcp list` shows which servers are configured, enabled and signed in, not
whether one answers, so there is nothing to ask it. Only `claude` is asked.
"""

from __future__ import annotations

import re
import threading
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from verticals.core.sources import Result
from verticals.sources.runner import CLAUDE_ENV, clean_env, find_exe, run_argv, search_path, shown

ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")
SECONDS = 90.0  # a health check starts every stdio server the CLI knows
LABEL = {"failed": "failed to connect", "sign_in": "needs sign-in"}


@dataclass(frozen=True)
class Server:
    name: str
    state: str   # answers, failed, sign_in, off or unknown
    status: str  # the words the CLI used


def classify(status: str) -> str:
    low = status.lower()
    if "needs authentication" in low:
        return "sign_in"
    if "failed to connect" in low or "connection error" in low or "fetch failed" in low:
        return "failed"
    if any(word in low for word in ("pending approval", "disabled", "rejected", "not configured")):
        return "off"
    if re.search(r"(?<![a-z])connected", low):
        return "answers"
    return "unknown"


def parse(text: str) -> list[Server]:
    """One `Server` for each line of the CLI's list that has a name, a target and a status."""
    servers = []
    for line in re.split(r"\r\n|\r|\n", ANSI.sub("", text)):
        line = line.strip()
        head, _, status = line.rpartition(" - ")
        name, _, target = head.partition(": ")
        if name and target and status.strip():
            servers.append(Server(name=name.strip(), state=classify(status), status=status.strip()))
    return servers


def check(
    agents: Sequence[str],
    *,
    home: Path,
    stop: threading.Event,
    environ: Mapping[str, str],
    path: str | None = None,
) -> Result:
    """Ask each agent in `agents` which of its servers answer; today that is `claude`."""
    if "claude" not in agents:
        return Result(False, "no agent is set up to ask")
    exe = find_exe("claude", home=home, path=path if path is not None else environ.get("PATH"))
    if exe is None:
        return Result(False, "Claude Code was not found on this Mac")
    env = clean_env(environ, home, also=CLAUDE_ENV)
    if path is not None:
        env["PATH"] = search_path(path, home)
    code, output, why = run_argv([exe, "mcp", "list"], env=env, cwd=home, seconds=SECONDS, stop=stop)
    raw = shown(output)
    if why is not None:
        return Result(False, f"claude mcp list: {why}", raw=raw)
    if code != 0:
        return Result(False, f"claude mcp list exited with code {code}", raw=raw)
    servers = [s for s in parse(output) if s.state != "off"]
    if not servers:
        if "No MCP servers configured" in output or not output.strip():
            return Result(True, "no MCP servers are set up", value=0, raw=raw)
        if not parse(output):
            return Result(False, "could not read the list from claude", raw=raw)
        return Result(True, "no MCP server is in use", value=0, raw=raw)
    answering = [s for s in servers if s.state == "answers"]
    down = [s for s in servers if s.state != "answers"]
    # The names of the servers that answer are in the line: the Inbox tells the owner, while they have no source yet, which
    # servers the agent reaches, and the agent reads the same line.
    reached = ", ".join(s.name for s in answering)
    if not down:
        return Result(True, f"all {len(servers)} answer: {reached}", value=float(len(answering)), raw=raw)
    names = ", ".join(f"{s.name} ({LABEL.get(s.state, shown(s.status, 30))})" for s in down)
    head = f"{len(answering)} of {len(servers)} answer" + (f": {reached}" if reached else "")
    return Result(False, f"{head}; not answering: {names}", value=float(len(answering)), raw=raw)
