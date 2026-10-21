"""Verticals desktop chat backend: runs the local agent CLIs (Claude Code, Codex) with the Verticals MCP server.

Ported from Enjoy's agent clients: Claude over `claude --print` stream-json with permission
prompts answered here, Codex over `codex app-server` JSON-RPC. Both are normalised into one
event stream for the chat UI. Agent settings (model, effort, speed, permissions) are chosen
per message, like Enjoy's composer; switching agents starts a fresh agent session and hands
it the conversation so far.
"""
from __future__ import annotations

import json
import logging
import os
import re
import secrets
import shutil
import subprocess
import sys
import threading
import time
import tomllib
import urllib.error
import urllib.request
import uuid
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path
from zoneinfo import ZoneInfo

HERE = Path(__file__).resolve().parent
# The gateway's own modules live beside this file: the morning report's turns, and where a task's sessions live. Found whether
# the gateway is started through the launcher (which puts this folder on the path) or this file is loaded by its path (the
# tests do).
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
import agent_sessions  # noqa: E402  (where a session lives, when it moved, how it opens: docs/design/task-sessions.md)
import agent_signin  # noqa: E402  (a signed-out agent signed back in from the field: docs/design/agent-sign-in.md)
from morning_flow import MorningFlow  # noqa: E402

SKILL = HERE.parents[1] / ".agents" / "skills" / "verticals-operator"
MORNING_SKILL = HERE.parents[1] / ".agents" / "skills" / "verticals-morning-report"


def load_prompt():
    """The chat's system prompt: its own intro plus the repository's operator skill, read live so
    changes to the skill reach the chat without copying it."""
    parts = [(HERE / "prompt-intro.md").read_text().strip(),
             'The operating guide below comes from the Verticals repository (skill "verticals-operator").']
    skill = SKILL / "SKILL.md"
    if skill.exists():
        text = skill.read_text()
        parts.append(text.split("---", 2)[2].strip() if text.startswith("---") else text.strip())
        for ref, title in (("mcp-operations.md", "MCP operations"), ("evidence.md", "evidence")):
            if (SKILL / "references" / ref).exists():
                parts.append(f"## Reference: {title}\n\n" + (SKILL / "references" / ref).read_text().strip())
    return "\n\n".join(parts) + "\n"


PROMPT = load_prompt()
# "Verticals only" keeps a Claude turn to the board; every other permission mode is Claude Code's own: its tools, the
# owner's MCP servers and the home folder, each action outside Verticals asked in the chat unless the mode allows it.
BOARD_ONLY = "board"
ASK_FIRST = "manual"  # Claude Code's mode that asks for every tool it was not told to allow
ACCESS_PROMPT = {
    False: "In this conversation Verticals is all you reach: you have no shell, files or web.",
    True: "In this conversation you also have Claude Code's own tools (shell, files, web) and the owner's other MCP "
          "servers, under the permission mode the owner chose; an action outside Verticals is asked in the chat "
          "unless that mode allows it.",
}


def full_access(settings):
    return (settings.get("permission") or BOARD_ONLY) != BOARD_ONLY


def load_morning_prompt():
    """The morning report's turn (web lib/morning.ts): its own rules, then the repository's morning-report skill with the
    two references a run follows, read live as the operator skill is."""
    parts = [(HERE / "prompt-morning.md").read_text().strip()]
    skill = MORNING_SKILL / "SKILL.md"
    if skill.exists():
        text = skill.read_text()
        parts.append(text.split("---", 2)[2].strip() if text.startswith("---") else text.strip())
        for ref, title in (("source-reconciliation.md", "source reconciliation"), ("report-contract.md", "report contract"),
                           ("second-check.md", "the second check")):
            if (MORNING_SKILL / "references" / ref).exists():
                parts.append(f"## Reference: {title}\n\n" + (MORNING_SKILL / "references" / ref).read_text().strip())
    return "\n\n".join(parts) + "\n"


def load_check_prompt():
    """The second agent's turn (desktop/chat/morning_flow.py): its own rules, then the morning-report skill's contract for the
    report's shape and its ten checks. It does not get the skill's own guide for writing a report: it does not write one."""
    parts = [(HERE / "prompt-check.md").read_text().strip()]
    for ref, title in (("source-reconciliation.md", "source reconciliation"), ("report-contract.md", "report contract"),
                       ("second-check.md", "the second check")):
        if (MORNING_SKILL / "references" / ref).exists():
            parts.append(f"## Reference: {title}\n\n" + (MORNING_SKILL / "references" / ref).read_text().strip())
    return "\n\n".join(parts) + "\n"


MORNING_PROMPT = load_morning_prompt()
CHECK_PROMPT = load_check_prompt()


# ---------------------------------------------------------------- reports (docs/design/bug-reports.md)

# The folders people clone Verticals into, looked in after the person's own word for where it is. A checkout is a git
# repository with this project's pyproject.toml and the desktop launcher in it.
SOURCE_PLACES = ("verticals", "Verticals", "Developer/verticals", "Projects/verticals", "Code/verticals", "src/verticals",
                 "GitHub/verticals", "Documents/GitHub/verticals")


def is_checkout(path):
    """Whether `path` is a git checkout of Verticals' source."""
    try:
        return ((path / ".git").exists() and (path / "desktop" / "launcher.py").is_file()
                and re.search(r'^name\s*=\s*"verticals"', (path / "pyproject.toml").read_text(), re.M) is not None)
    except OSError:
        return False


def find_source(state_dir=None, home=None, code_root=None, explicit_only=False):
    """A checkout of Verticals' source on this Mac, or None. The agent that makes a change and opens its pull request needs
    one; the installed app ships without. In this order: the person's word for it, `VERTICALS_SOURCE` or `source` in the app's
    config.json (nothing else of that file is read); the repository this code runs from, when it runs from a checkout; the
    folders people clone into. A report's task and its documents come without one, and only the pull request waits."""
    home = Path(home) if home else Path.home()
    named = [os.environ.get("VERTICALS_SOURCE")]
    try:
        config = json.loads((Path(state_dir) / "config.json").read_text()) if state_dir else {}
        named.append(config.get("source") if isinstance(config, dict) else None)
    except (OSError, ValueError):
        pass
    candidates = [Path(n).expanduser() for n in named if isinstance(n, str) and n.strip()]
    if not explicit_only:
        candidates += [Path(code_root) if code_root else HERE.parents[1], *(home / place for place in SOURCE_PLACES)]
    return next((c for c in candidates if is_checkout(c)), None)


def shaping_skills(home=None):
    """The names of the skills for shaping a change that this Mac's agents have, found by the word in their folder's name. The
    prompt names them only when they are there, so it never sends an agent to a skill it does not have."""
    home = Path(home) if home else Path.home()
    folders = (Path(os.environ.get("CLAUDE_CONFIG_DIR") or home / ".claude"), home / ".agents",
               Path(os.environ.get("CODEX_HOME") or home / ".codex"))
    found = set()
    for folder in folders:
        try:
            found.update(p.name for p in (folder / "skills").iterdir() if "shaping" in p.name.lower() and (p / "SKILL.md").is_file())
        except OSError:
            continue
    return sorted(found)


def report_prompt(state_dir=None, full=False, home=None, code_root=None):
    """The chat's instructions for the reports the app makes, with the checkout it found and, in a conversation that has the
    agent's own tools, the shaping skills this Mac has (docs/design/bug-reports.md)."""
    skills = shaping_skills(home) if full else []
    use = (f"Use these skills for it: {', '.join(skills)}." if skills
           else "Use the skills you have for shaping and design, if there are any.")
    source = find_source(state_dir, home, code_root)
    where = (f"The source of Verticals on this Mac is a git checkout at {source}." if source else
             "No checkout of Verticals' source was found on this Mac. Ask where it is; if there is none, say the pull request must wait.")
    return (HERE / "prompt-report.md").read_text().strip().replace("{skills}", use) + "\n\n" + where + "\n"


# The one value a message's `sources` may take: the morning report's turn (web lib/morning.ts), which gets the morning
# guide and its own rules. `clean_settings` passes exactly this value on and nothing else (docs/design/agent-fixes.md, fix 1).
CONNECTED = "connected"
# The Verticals writes the morning report makes on its own, unattended: its document and the document's link to its task, and
# the evidence of what it closes. The task is the server's, made or moved to today before the ask (core/morning.py,
# docs/design/agent-fixes.md, fix 2), so `create` and `schedule` are not among them: a second task or a move would ask the
# owner first. Closing what is done is one more, by what it is called with and not by its name (`closes_only`).
MORNING_WRITES = ["doc_create", "doc_save", "doc_link", "evidence_update"]
# The second agent's seat in the morning flow (morning_flow.py): it reads and answers, and writes nothing.
CHECKER = "checker"
# Every MCP tool a morning turn calls comes to this gateway to be judged, whoever allowed it. The turn keeps the owner's own
# settings, servers and tools (the sources' tools are theirs), and `--settings` on the command line adds one `ask` rule that
# matches all of them: `mcp__*` is the docs' glob for every MCP tool. Rule lists from several settings files are combined, and
# the CLI checks deny rules first, then ask, then allow, the first match deciding (Claude Code docs: Settings, "Lists merge
# instead of overriding"; Permissions, "Manage permissions"), so an allow rule in the owner's own files cannot let a tool run
# on its own. A deny rule of the owner's still blocks. The gateway's judgement of each ask is `ClaudeAgent.handle`.
MORNING_ASKS = ["mcp__*"]
# A tool as Claude Code names it, `mcp__<server>__<tool>`: what a source's check block may name for reading it
# (verticals/core/source_checks.py::reading_tools says it again at the server, where it is written).
TOOL_NAME = re.compile(r"^mcp__([A-Za-z0-9][A-Za-z0-9_.\-]{0,80}?)__([A-Za-z0-9][A-Za-z0-9_.\-]{0,120})$")


def declared_reads(chat):
    """The tools the morning turn may call outside Verticals: those a source document names for reading it, each with the
    source's name (`{tool: title}`). Only a source whose check the owner has approved counts (the tools are in the block the
    owner approves, and a changed block asks again), and never a tool of Verticals itself, whatever a document says. Anything
    else is asked of the owner, or declined for the second agent. Read from the server when the turn starts; a server that cannot
    be reached declares nothing."""
    try:
        listed = chat.api("GET", "/api/sources")
    except Exception as e:  # noqa: BLE001 — no list, no tools: the turn then asks for each
        if getattr(chat, "log", None):
            chat.log.warning("declared reads unavailable %s", clip(e, 160))
        return {}
    tools = {}
    for source in listed.get("sources") or []:
        if not isinstance(source, dict) or not (source.get("approved") or source.get("needs_approval") is False):
            continue
        for tool in source.get("reads") or []:
            found = TOOL_NAME.match(tool) if isinstance(tool, str) else None
            if found and not found.group(1).lower().startswith("verticals"):
                tools.setdefault(tool, str(source.get("title") or source.get("path") or "a source")[:80])
    return tools


def closes_only(tool_input):
    """An `update` that only ticks goals done: one id or several, `done` true, nothing else. The morning report closes what the
    sources show is done; any other change to a goal is asked of the owner."""
    if not isinstance(tool_input, dict):
        return False
    keys = set(tool_input)
    return tool_input.get("done") is True and keys <= {"id", "ids", "done", "client_token"} and ("id" in keys) != ("ids" in keys)


MAX_EVENTS = 5000
WATCH_SECONDS = 2  # how often the files of the sessions of tasks are looked at (a stat each)
MISSING_SECONDS = 20  # how long a session with no file is left alone before it is searched for again
HANDOFF_CHARS = 12000
# Parent-session variables must not leak into the agents (credentials excepted).
ENV_KEEP = {"CLAUDE_CODE_OAUTH_TOKEN", "CLAUDE_CONFIG_DIR", "CLAUDE_CODE_USE_BEDROCK",
            "CLAUDE_CODE_USE_VERTEX", "CLAUDE_CODE_USE_FOUNDRY"}
# A whole day's `board` runs past Claude Code's default cap on one tool's answer (25,000 tokens). Over the cap the CLI puts
# the answer in a file, and a seat with no file tools cannot open it.
MCP_OUTPUT_TOKENS = "100000"
READ_TOOLS = ["board", "goal", "outline", "search", "evidence_due", "tags", "size_report",
              "doc_get", "doc_image", "doc_tree", "doc_history", "doc_revision", "comments",
              "privacy", "sources"]
# Replan over the whole board (docs/design/replan-whole-board.md): the owner says go to the whole document once, and the
# answer's Undo takes all of it back (docs/design/agent-answer-undo.md), so a conversation a Replan message started makes
# these Verticals writes without a question for each, in every permission mode. Nothing outside Verticals is among them.
REPLAN_WRITES = ["schedule", "delete", "update", "reparent", "doc_create", "doc_save", "doc_link"]
# Claude's own question tool. Its call comes to the gateway as a permission request (its permission check always asks), and
# the field shows each question as an ask; the answers go back in the call's input, keyed by each question's words
# (Claude Agent SDK docs, "Handle approvals and user input"; the CLI reads `answers[question]` as text).
QUESTION_TOOL = "AskUserQuestion"
# An option the agent marks as its guess stays first, where one tap takes it.
GUESS_MARKS = ("(my guess)", "(recommended)")

# Agent descriptors: labels and details are Enjoy's own (see its provider registry). `signin` is how the field signs a signed-out
# agent back in (agent_signin.py, docs/design/agent-sign-in.md): its login command, its status command and how the status is read
# (`json`, the key that says it in the JSON it prints; else the exit code), the variable that holds its home, and words of its
# errors beyond the common ones.
AGENTS = {
    "claude": {
        "label": "Claude Code", "exe": "claude", "image": "claude.svg", "order": 10,
        "efforts": [["low", "Low"], ["medium", "Medium"], ["high", "High"], ["xhigh", "xHigh"],
                    ["max", "Max"], ["ultracode", "Ultracode"]],
        "defaultEffort": "medium",
        "fast": "Faster responses on supported models. Uses paid usage credits or API billing.",
        "permissions": [
            ["board", "Verticals only", "Work with the board alone: no shell, files, web or other MCP servers."],
            ["manual", "Manual", "Ask before file edits and commands that are not already allowed."],
            ["acceptEdits", "Accept edits", "Approve project file edits and common file commands. Ask before other actions."],
            ["plan", "Plan", "Explore and propose a plan before changing your source files."],
            ["auto", "Auto", "Claude reviews actions automatically. Availability depends on your model, account, and organization."],
            ["dontAsk", "Don't ask", "Run only pre-approved tools. Deny anything that would need permission."],
            ["bypassPermissions", "Bypass permissions", "Skip permission checks. Use only in an isolated environment you trust."],
        ],
        "defaultPermission": "board",
        "signin": {"login": ["auth", "login"], "status": ["auth", "status"], "json": "loggedIn", "home": "CLAUDE_CONFIG_DIR"},
    },
    "codex": {
        "label": "Codex", "exe": "codex", "image": "codex.png", "order": 20,
        "efforts": [["low", "Low"], ["medium", "Medium"], ["high", "High"], ["xhigh", "Extra high"],
                    ["max", "Max"], ["ultra", "Ultra"]],
        "defaultEffort": "medium",
        "fast": "Faster responses with higher credit usage or API cost.",
        "permissions": [
            ["read-only", "Read-only", "Explore files without changing them. Ask before actions outside the read-only sandbox."],
            ["default", "Ask for approval", "Work within the project. Ask before network access or actions outside the workspace."],
            ["auto-review", "Approve for me", "Work within the project. Auto-review checks requests for additional access."],
            ["full-access", "Full access", "Run commands and edit files anywhere, with network access and no approval prompts."],
        ],
        "defaultPermission": "auto-review",
        "signin": {"login": ["login"], "status": ["login", "status"], "home": "CODEX_HOME", "words": ["codex login", "unauthorized"]},
    },
}
CODEX_MODELS = {  # Enjoy's curated presentation for Codex models
    "gpt-5.5": ("GPT-5.5", "A new class of intelligence for coding and professional work.", "gpt-5.5.png"),
    "gpt-6-astra": ("Astra", "OpenAI’s most capable model, built for the hardest end-to-end work", "gpt-6-astra.png"),
    "gpt-5.6-sol": ("Sol", "Flagship model for complex professional work", "gpt-5.6-sol.png"),
    "gpt-5.6-terra": ("Terra", "GPT-5.6 model that balances intelligence and cost", "gpt-5.6-terra.png"),
    "gpt-5.6-luna": ("Luna", "GPT-5.6 model optimized for cost-sensitive workloads", "gpt-5.6-luna.png"),
}
CLAUDE_USAGE = {"five_hour": "5 hours", "seven_day": "Weekly", "seven_day_oauth_apps": "Weekly · apps",
                "seven_day_opus": "Weekly · Opus", "seven_day_sonnet": "Weekly · Sonnet"}


def child_env(extra=None):
    env = {k: v for k, v in os.environ.items()
           if not (k.startswith("CLAUDE") and k not in ENV_KEEP) and not k.startswith(("VERTICALS_", "PYTHON"))}
    extra_path = [str(Path.home() / ".local/bin"), "/opt/homebrew/bin", "/usr/local/bin"]
    path = env.get("PATH", "").split(":")
    env["PATH"] = ":".join(path + [p for p in extra_path if p not in path])
    env.update(extra or {})
    return env


def which(provider):
    return shutil.which(AGENTS[provider]["exe"], path=child_env()["PATH"])


class ChatError(Exception):
    pass


def window(label, used, resets=None):
    if not isinstance(used, (int, float)):
        return None
    return {"label": label, "remainingPercent": max(0, min(100, round(100 - used)))}


def usage_state(windows, missing):
    windows = [w for w in windows if w]
    return {"state": "ready", "windows": windows} if windows else {"state": "unavailable", "message": missing}


# ---------------------------------------------------------------- the gateway's log

# The agent's side of a bug report (docs/design/agent-fixes.md, fix 7): one small rotating file in the app's data folder,
# beside api.log and mcp.log. A report may carry its last lines, so a line holds what happened and never what was said:
# event kinds, tool names, flags, durations and the CLI's own exit details; not your words, the agent's, a tool's inputs
# or results, a title, an ID or the token.
LOG_FILE = "agent.log"
LOG_BYTES = 200_000
LOG_BACKUPS = 2  # three files at most, about 600 kB all told


def open_log(state_dir, max_bytes=LOG_BYTES, backups=LOG_BACKUPS):
    """The gateway's log. A logger of its own, not in the process-wide tree, so two gateways in one process (the tests) never
    write each other's lines. A log that cannot be opened (a read-only folder, a full disk) is no reason to stop the chat: the
    logger then has no handler and says nothing."""
    log = logging.Logger("verticals.agent")
    log.setLevel(logging.INFO)
    try:
        handler = RotatingFileHandler(Path(state_dir) / LOG_FILE, maxBytes=max_bytes, backupCount=backups, encoding="utf-8")
    except OSError:
        return log
    handler.setFormatter(logging.Formatter("%(asctime)s %(message)s", "%Y-%m-%dT%H:%M:%S%z"))
    log.addHandler(handler)
    return log


def clip(text, limit=300):
    """One line of a CLI's own words (an error, an exit): whitespace folded, cut at `limit`."""
    flat = " ".join(str(text or "").split())
    return flat if len(flat) <= limit else flat[:limit - 1] + "…"


def log_line(session, event):
    """The log's line for an event of a conversation, or None for the many that say nothing the log needs (the agent's
    words, a tool's result when it went well). Only fields that carry no content are read."""
    kind = event.get("t")
    who = f"session={str(session)[:8]}"
    if kind == "turn_start":
        return f"turn_start provider={event.get('provider')} model={event.get('model') or '-'} effort={event.get('effort') or '-'} {who}"
    if kind == "tool":
        return f"tool name={event.get('name')} {who}"
    if kind == "tool_result" and event.get("error"):
        return f"tool_error id={event.get('id')} {who}"
    if kind == "goal":
        return f"goal_bound {who}"
    if kind == "permission":
        return f"permission tool={event.get('tool') or '-'} {who}"
    if kind == "permission_done":
        return f"permission_done value={event.get('value', event.get('label', '-'))} {who}"
    if kind == "done":
        return f"done error={bool(event.get('error'))} ms={event.get('ms')} {who}" + (f" detail={clip(event.get('detail'))}" if event.get("detail") else "")
    if kind == "exit":
        return f"exit code={event.get('code')} {who}" + (f" detail={clip(event.get('detail'))}" if event.get("detail") else "")
    return None


# ---------------------------------------------------------------- line-delimited JSON processes

class JsonProcess:
    """A child speaking newline-delimited JSON on stdin/stdout."""

    def __init__(self, argv, cwd, env, on_message, on_exit):
        self.proc = subprocess.Popen(argv, cwd=cwd, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                     stderr=subprocess.PIPE, start_new_session=True)
        self.lock = threading.Lock()
        self.stderr = []
        self.on_message, self.on_exit = on_message, on_exit
        threading.Thread(target=self._read, daemon=True).start()
        threading.Thread(target=self._read_err, daemon=True).start()

    def _read(self):
        for raw in self.proc.stdout:
            try:
                msg = json.loads(raw)
            except ValueError:
                continue
            try:
                self.on_message(msg)
            except Exception as e:  # noqa: BLE001 — one bad message must not stop the stream
                self.stderr.append(f"chat: {e}")
        code = self.proc.wait()
        self.on_exit(code, "\n".join(self.stderr[-6:]))

    def _read_err(self):
        for raw in self.proc.stderr:
            self.stderr = (self.stderr + [raw.decode("utf-8", "replace").rstrip()])[-30:]

    def send(self, message):
        if self.proc.poll() is not None:
            raise ChatError("The agent is not running")
        with self.lock:
            self.proc.stdin.write((json.dumps(message) + "\n").encode())
            self.proc.stdin.flush()

    def alive(self):
        return self.proc.poll() is None

    def close(self):
        try:
            self.proc.stdin.close()  # both CLIs exit on stdin EOF
            self.proc.wait(timeout=3)
        except (OSError, subprocess.TimeoutExpired):
            self.proc.terminate()


class RpcProcess(JsonProcess):
    """JSON-RPC over JsonProcess (codex app-server: no "jsonrpc" field, integer ids)."""

    def __init__(self, argv, cwd, env, on_notify, on_request, on_exit):
        self.next_id, self.pending = 0, {}
        self.on_notify, self.on_request = on_notify, on_request
        super().__init__(argv, cwd, env, self._dispatch, self._exited(on_exit))

    def _exited(self, on_exit):
        def done(code, detail):
            for slot in list(self.pending.values()):
                slot["error"] = detail or f"The agent exited ({code})"
                slot["done"].set()
            on_exit(code, detail)
        return done

    def _dispatch(self, msg):
        if "id" in msg and "method" not in msg:
            slot = self.pending.pop(msg["id"], None)
            if slot:
                slot["result"], slot["error"] = msg.get("result"), (msg.get("error") or {}).get("message")
                slot["done"].set()
        elif "id" in msg:
            self.on_request(msg)
        else:
            self.on_notify(msg.get("method"), msg.get("params") or {})

    def request(self, method, params, timeout=45):
        with self.lock:
            self.next_id += 1
            rid = self.next_id
        slot = {"done": threading.Event(), "result": None, "error": None}
        self.pending[rid] = slot
        self.send({"id": rid, "method": method, "params": params})
        if not slot["done"].wait(timeout):
            self.pending.pop(rid, None)
            raise ChatError(f"{method} timed out")
        if slot["error"]:
            raise ChatError(slot["error"])
        return slot["result"] or {}

    def notify(self, method, params):
        self.send({"method": method, "params": params})

    def reply(self, rid, result=None, error=None):
        self.send({"id": rid, "error": error} if error else {"id": rid, "result": result})


# ---------------------------------------------------------------- agents

class ClaudeAgent:
    """`claude --print` stream-json; mirrors Enjoy's Claude client. `prompt` replaces the chat's own system prompt for a
    conversation that is not the chat's (report_kind.py)."""

    provider = "claude"

    def __init__(self, chat, s, settings, resume_id, cwd=None, rebuild_prompt=False, prompt=None):
        self.chat, self.s, self.settings = chat, s, settings
        self.session_id = resume_id or str(uuid.uuid4())
        self.streamed = False
        self.pending = {}
        effort = settings.get("effort")
        claude_settings = {"fastMode": bool(settings.get("fast")), "ultracode": effort == "ultracode"}
        # The morning report's turn (web lib/morning.ts) also reaches the owner's own connected tools, read-only, and
        # saves its document in Verticals without asking. Nobody watches it, so it never runs in the chat's mode:
        # "Bypass permissions" or "Auto" would let a tool of another server run before this gateway could judge it. It
        # always asks first, and every MCP tool it calls comes here (`MORNING_ASKS`): handle() runs the tools its sources
        # declare for reading them and Verticals' own reading tools, closes what is done, and puts any other tool to the
        # owner; the second agent has nobody to ask and is declined (docs/design/morning-quality.md). It keeps the owner's
        # own settings and servers, so the sources' tools are there to call.
        self.connected = settings.get("sources") == CONNECTED
        self.checker = self.connected and settings.get("role") == CHECKER
        if self.connected:
            claude_settings["permissions"] = {"ask": MORNING_ASKS}
        self.full = full_access(settings) and not self.connected
        self.reads = declared_reads(chat) if self.connected else {}
        # A conversation a Replan message started (Chat._send) writes on the board without asking (REPLAN_WRITES).
        self.replan = bool(settings.get("replan")) and not self.connected and prompt is None
        self.questions = {}  # the ask of each question that waits -> the question call it belongs to
        self.asking = {}     # a question call -> its questions, the answers so far and the ask on show
        allowed = READ_TOOLS + (MORNING_WRITES if self.connected and not self.checker else []) + (
            REPLAN_WRITES if self.replan else [])
        # What this seat runs without a question: on the command line, and again in handle() for when the CLI asks anyway.
        self.allowed = [f"mcp__verticals__{t}" for t in allowed] + list(self.reads)
        mode = ASK_FIRST if self.connected else settings.get("permission") or BOARD_ONLY
        # What this conversation is told on top of the board prompt: a morning turn's guide; in any other, the reports'
        # instructions and what its access reaches (docs/design/bug-reports.md). A conversation of another kind (report_kind.py)
        # brings its whole prompt.
        brief = (CHECK_PROMPT if self.checker else MORNING_PROMPT) if self.connected else (
            report_prompt(getattr(chat, "state_dir", None), self.full) + "\n" + ACCESS_PROMPT[self.full])
        args = [which("claude"), "--print", "--verbose", "--include-partial-messages",
                "--input-format", "stream-json", "--output-format", "stream-json",
                "--permission-mode", ASK_FIRST if mode == BOARD_ONLY else mode,
                "--permission-prompts", "host", "--permission-prompt-tool", "stdio",
                *([] if self.connected or self.full else ["--strict-mcp-config"]), "--mcp-config", str(chat.claude_config(getattr(s, "id", None))),
                "--settings", json.dumps(claude_settings),
                # "Verticals only" has none of Claude Code's tools but its question tool, which reaches nothing (QUESTION_TOOL);
                # the morning's seats and a conversation of another kind (report_kind.py) have none at all.
                *(["--add-dir", str(Path.home())] if self.full else
                  ["--tools", "" if self.connected or prompt is not None else QUESTION_TOOL]),
                "--allowedTools", ",".join(self.allowed),
                "--append-system-prompt", prompt if prompt is not None else PROMPT + "\n" + brief,
                "--resume" if resume_id else "--session-id", self.session_id]
        if settings.get("model") and settings["model"] != "default":
            args += ["--model", settings["model"]]
        if effort and effort != "default":
            args += ["--effort", "xhigh" if effort == "ultracode" else effort]
        if rebuild_prompt:
            # A session that began outside Verticals recorded its own system prompt on its first request, and a resume keeps
            # that one unless told to build it again (code.claude.com/docs/en/cli-reference, "--system-prompt-snapshot").
            args += ["--system-prompt-snapshot", "off"]
        env = child_env()
        env.setdefault("MAX_MCP_OUTPUT_TOKENS", MCP_OUTPUT_TOKENS)
        self.proc = JsonProcess(args, cwd or chat.workdir, env, self.handle, self.exited)
        self.proc.send({"type": "control_request", "request_id": "initialize", "request": {"subtype": "initialize"}})

    def signature(self):
        return self.settings

    def send(self, text):
        self.streamed = False
        self.proc.send({"type": "user", "session_id": self.session_id,
                        "message": {"role": "user", "content": [{"type": "text", "text": text}]}})

    def interrupt(self):
        self.proc.send({"type": "control_request", "request_id": str(uuid.uuid4()), "request": {"subtype": "interrupt"}})

    def decide(self, rid, option):
        if rid in self.questions:
            return self.answer(rid, option)
        tool_input = self.pending.pop(rid, None)
        response = {"behavior": "allow", "updatedInput": tool_input} if option == "accept" else \
            {"behavior": "deny", "message": "The user declined this action."}
        self.respond(rid, response)

    def respond(self, rid, response):
        self.proc.send({"type": "control_response",
                        "response": {"subtype": "success", "request_id": rid, "response": response}})

    # -- Claude's questions (QUESTION_TOOL, docs/design/replan-whole-board.md)

    def ask_questions(self, rid, tool_input):
        """A question call: its questions are asked one at a time, as the field's asks, and answered to Claude once."""
        questions = [q for q in (tool_input.get("questions") if isinstance(tool_input, dict) else None) or []
                     if isinstance(q, dict) and str(q.get("question") or "").strip()]
        if not questions:
            return self.respond(rid, {"behavior": "allow", "updatedInput": {**(tool_input or {}), "answers": {}}})
        self.asking[rid] = {"input": tool_input, "questions": questions, "answers": {}, "at": 0, "key": None, "labels": []}
        self.ask_next(rid)

    def ask_next(self, rid):
        call = self.asking.get(rid)
        if call is None:
            return
        number = call["at"]
        q = call["questions"][number]
        options = [o for o in q.get("options") or [] if isinstance(o, dict) and str(o.get("label") or "").strip()]
        options.sort(key=lambda o: not str(o["label"]).strip().lower().endswith(GUESS_MARKS))
        call["key"], call["labels"] = f"{rid}:q{number + 1}", [str(o["label"]) for o in options]
        self.questions[call["key"]] = rid
        body = "\n".join(filter(None, [str(q.get("header") or ""), *(
            f"{o['label']}: {o['description']}" if o.get("description") else str(o["label"]) for o in options)]))
        self.s.ask(self, call["key"], str(q["question"])[:500], body,
                   [(label[:120], str(i)) for i, label in enumerate(call["labels"])], tool=QUESTION_TOOL,
                   tool_input={"question": q["question"], "header": q.get("header"), "multiSelect": bool(q.get("multiSelect")),
                               "options": options})

    def answer(self, key, value, typed=False):
        """One question answered: by a tap (the option's number, or several numbers for a multi-select question, whose
        labels are joined with ", ", as the SDK docs say) or by the owner's own words (`typed`). The next question is asked
        by what this returns, once the field was told this one is done (Chat.decide); after the last, Claude gets every
        answer. An answer that is neither, the refusal a quiet seat gives every ask (report_kind.py), declines the call."""
        rid = self.questions.pop(key, None)
        call = self.asking.get(rid)
        if call is None:
            return None
        labels = call["labels"]
        picked = value if isinstance(value, list) else [value]
        if typed:
            words = str(value).strip()
        elif picked and all(isinstance(v, str) and v.isdigit() and int(v) < len(labels) for v in picked):
            words = ", ".join(labels[int(v)] for v in picked)
        else:
            self.asking.pop(rid)
            return self.respond(rid, {"behavior": "deny", "message": "The user did not answer."})
        call["answers"][str(call["questions"][call["at"]]["question"])] = words
        call["at"] += 1
        if call["at"] < len(call["questions"]):
            return lambda: self.ask_next(rid)
        self.asking.pop(rid)
        self.respond(rid, {"behavior": "allow", "updatedInput": {**call["input"], "answers": call["answers"]}})
        return None

    def handle(self, msg):
        s, kind = self.s, msg.get("type")
        if kind == "stream_event":
            ev = msg.get("event", {})
            if ev.get("type") == "message_start":
                self.streamed = False
            elif ev.get("type") == "content_block_start":
                block = ev.get("content_block", {})
                if block.get("type") == "text":
                    s.emit({"t": "text_start"})
                elif block.get("type") == "thinking":
                    s.emit({"t": "activity", "label": "Thinking…"})
            elif ev.get("type") == "content_block_delta" and ev.get("delta", {}).get("type") == "text_delta":
                if not self.streamed:
                    s.emit({"t": "activity", "label": "Writing…"})
                self.streamed = True
                s.emit({"t": "text", "text": ev["delta"]["text"]})
        elif kind == "assistant":
            for block in msg.get("message", {}).get("content", []):
                if block.get("type") == "tool_use":
                    name = short(block.get("name", ""))
                    # A declared tool reads one of the sources: the field says which (web lib/agentChat.ts).
                    step = {"step": f"Reading {self.reads[name]}"} if name in self.reads else {}
                    s.emit({"t": "tool", "id": block.get("id"), "name": name, "title": name,
                            "input": block.get("input", {}), **step})
                    s.emit({"t": "activity", "label": f"Using {name}"})
                elif block.get("type") == "text" and not self.streamed and block.get("text"):
                    s.emit({"t": "text_start"})
                    s.emit({"t": "text", "text": block["text"]})
        elif kind == "user":
            content = msg.get("message", {}).get("content")
            for block in content if isinstance(content, list) else []:
                if block.get("type") == "tool_result":
                    s.emit({"t": "tool_result", "id": block.get("tool_use_id"), "error": bool(block.get("is_error")),
                            "summary": result_text(block.get("content"))[:1500]})
        elif kind == "control_request" and msg.get("request", {}).get("subtype") == "can_use_tool":
            req, rid = msg["request"], msg.get("request_id")
            tool, tool_input = req.get("tool_name", ""), req.get("input", {})
            if tool == QUESTION_TOOL and not self.connected:
                return self.ask_questions(rid, tool_input)
            self.pending[rid] = tool_input
            if self.replan and tool in self.allowed:
                return self.decide(rid, "accept")  # REPLAN_WRITES, should the CLI ask about them anyway (plan mode does)
            if self.connected:
                # Every MCP tool of a morning turn comes here (`MORNING_ASKS`). What the seat may run is what is on its command
                # line: Verticals' reading tools, the tools its approved sources declare, and for the agent that writes the
                # report its own writes. That agent also closes what is done. The second agent has nobody to ask and is declined
                # for anything else; the agent that writes puts a tool no source lists, or a write in Verticals beyond the
                # report, to the reader. It has no shell, files or web (`--tools ""`), so anything that is not an MCP tool is
                # declined and not asked about.
                if tool in self.allowed:
                    return self.decide(rid, "accept")
                if self.checker or not tool.startswith("mcp__"):
                    return self.decide(rid, "decline")
                if tool == "mcp__verticals__update" and closes_only(tool_input):
                    return self.decide(rid, "accept")
            elif not tool.startswith("mcp__verticals__") and not self.full:
                return self.decide(rid, "decline")
            s.ask(self, rid, f"Allow Claude to use {short(tool)}?",
                  "\n\n".join(filter(None, [req.get("decision_reason"), json.dumps(tool_input, indent=2, ensure_ascii=False)])),
                  [("Allow once", "accept"), ("Decline", "decline")], tool=short(tool), tool_input=tool_input)
        elif kind == "control_cancel_request":
            call = self.asking.pop(msg.get("request_id"), None)
            if call:  # a question call: the ask on show is its own
                self.questions.pop(call["key"], None)
            s.resolve(call["key"] if call else msg.get("request_id"), "Cancelled")
        elif kind == "control_response" and msg.get("response", {}).get("request_id") == "initialize":
            models = (msg["response"].get("response") or {}).get("models") or []
            self.chat.remember_models("claude", models)
        elif kind == "result":
            s.turn_done(bool(msg.get("is_error")), msg.get("result") if msg.get("is_error") else "")
        elif kind == "system" and msg.get("subtype") == "init":
            s.emit({"t": "ready", "provider": "claude", "model": msg.get("model")})

    def exited(self, code, detail):
        self.s.agent_exited(self, code, detail)

    def close(self):
        self.proc.close()


def codex_mode(settings):
    """The permission mode a Codex turn runs in: the chat's own, except the morning turn, which only reads."""
    return "read-only" if settings.get("sources") == CONNECTED else settings.get("permission") or "auto-review"


def codex_policy(mode, cwd=None):
    """Enjoy's sO(): permission mode -> Codex approval policy and sandbox."""
    out = {"approvalPolicy": "never" if mode == "full-access" else "on-request",
           "approvalsReviewer": "auto_review" if mode == "auto-review" else "user"}
    if cwd is None:
        out["sandbox"] = {"full-access": "danger-full-access", "read-only": "read-only"}.get(mode, "workspace-write")
    else:
        out["sandboxPolicy"] = ({"type": "dangerFullAccess"} if mode == "full-access" else
                                {"type": "readOnly", "networkAccess": False} if mode == "read-only" else
                                {"type": "workspaceWrite", "writableRoots": [cwd], "networkAccess": False})
    return out


def codex_instructions(settings, state_dir=None):
    """What Codex is told at the start of a thread: the board prompt, the morning turn's guide after it (or, in any other turn,
    the reports' instructions), and Verticals under the name Codex knows its server by."""
    morning = CHECK_PROMPT if settings.get("role") == CHECKER else MORNING_PROMPT
    text = PROMPT + ("\n" + morning if settings.get("sources") == CONNECTED else "\n" + report_prompt(state_dir))
    return text.replace('server "verticals"', 'server "verticals_desktop"')


# What the stdio proxy reads from its environment: where the MCP server is, its token and the conversation its calls belong to
# (the server keeps what each answer of a conversation wrote, `verticals/mcp/answers.py`).
PROXY_ENV = ["VERTICALS_MCP_URL", "VERTICALS_MCP_TOKEN", "VERTICALS_MCP_SESSION"]


def codex_args(chat, reads=None):
    """Expose the desktop and, for morning turns, approved source readers.

    CLI overrides merge tables; setting mcp_servers={} neither removes inherited servers
    nor clears an existing HTTP transport when a stdio command is added under its name.
    """
    q = json.dumps
    config_path = Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex"))) / "config.toml"
    try:
        config = tomllib.loads(config_path.read_text()) if config_path.exists() else {}
    except (OSError, ValueError) as e:
        raise ChatError("Cannot read Codex configuration to isolate the desktop connection") from e
    servers = config.get("mcp_servers", {})
    if "verticals_desktop" in servers:
        raise ChatError("Codex configuration already uses the reserved verticals_desktop server name")
    source_tools = {}
    for tool in reads or ():
        match = TOOL_NAME.fullmatch(tool)
        if match and not match.group(1).lower().startswith("verticals"):
            name, method = match.groups()
            if name in servers and servers[name].get("enabled", True):
                source_tools.setdefault(name, set()).add(method)
    key = lambda name: name if re.fullmatch(r"[A-Za-z0-9_-]+", name) else q(name)
    overrides = []
    for group in ("mcp_servers", "plugins"):
        for name in config.get(group, {}):
            if group == "mcp_servers" and name in source_tools:
                prefix = f"mcp_servers.{key(name)}"
                overrides += ["-c", f"{prefix}.enabled=true",
                              "-c", f"{prefix}.enabled_tools={q(sorted(source_tools[name]))}",
                              "-c", f'{prefix}.default_tools_approval_mode="prompt"']
                for method in sorted(source_tools[name]):
                    overrides += ["-c", f'{prefix}.tools.{key(method)}.approval_mode="approve"']
            else:
                overrides += ["-c", f"{group}.{key(name)}.enabled=false"]
    for event, handlers in config.get("hooks", {}).items():
        if isinstance(handlers, list):
            overrides += ["-c", f"hooks.{event}=[]"]
    overrides += ["-c", "notify=[]", "-c", "features.apps=false", "-c", "features.shell_tool=true",
                  "-c", "features.multi_agent=false", "-c", 'web_search="disabled"',
                  "-c", f"mcp_servers.verticals_desktop.command={q(sys.executable)}",
                  "-c", f"mcp_servers.verticals_desktop.args={q([str(HERE / 'mcp_proxy.py')])}",
                  "-c", f"mcp_servers.verticals_desktop.env_vars={q(PROXY_ENV)}",
                  "-c", 'mcp_servers.verticals_desktop.default_tools_approval_mode="writes"']
    # Includes system/project layers and plugin servers; fail closed if one escaped the overrides.
    try:
        result = subprocess.run([which("codex"), *overrides, "mcp", "list", "--json"], cwd=chat.workdir,
                                env=child_env(), capture_output=True, text=True, timeout=20)
    except subprocess.TimeoutExpired as e:
        raise ChatError("Codex connection isolation check timed out; retry when the CLI responds") from e
    try:
        enabled = {s["name"] for s in json.loads(result.stdout) if s.get("enabled", True)}
    except (ValueError, KeyError, TypeError):
        enabled = set()
    if result.returncode or enabled != {"verticals_desktop", *source_tools}:
        raise ChatError("Could not isolate Codex to Verticals and its approved source readers")
    return [which("codex"), "app-server", *overrides]


class CodexAgent:
    """`codex app-server`; mirrors Enjoy's Codex client."""

    provider = "codex"

    def __init__(self, chat, s, settings, resume_id, cwd=None, rebuild_prompt=False):
        self.chat, self.s, self.settings = chat, s, settings
        self.cwd = cwd or chat.workdir  # `rebuild_prompt` is Claude's: Codex is given its instructions at every thread/resume
        self.thread_id, self.turn_id = None, None
        self.approvals = {}      # request id -> [(label, response)]
        self.pending_mcp = {}
        self.reads = declared_reads(chat) if settings.get("sources") == CONNECTED else {}
        self.streamed = set()    # agentMessage item ids that got deltas
        # The conversation its calls belong to (docs/design/agent-answer-undo.md); a seat that is no conversation (the morning
        # report's second agent, morning_flow.py) has none, and its calls are nobody's answer.
        conversation = getattr(s, "id", None)
        env = child_env({"VERTICALS_MCP_URL": chat.mcp_url, "VERTICALS_MCP_TOKEN": chat.token,
                         **({"VERTICALS_MCP_SESSION": conversation} if conversation else {})})
        args = (codex_args(chat, declared_reads(chat)) if settings.get("sources") == CONNECTED else codex_args(chat))
        self.proc = RpcProcess(args, self.cwd, env, self.notify, self.request, self.exited)
        self.proc.request("initialize", {"clientInfo": {"name": "verticals-desktop", "title": "Verticals", "version": "0.1.0"},
                                         "capabilities": {"experimentalApi": True}})
        self.proc.notify("initialized", {})
        params = {**codex_policy(codex_mode(settings)), "cwd": str(self.cwd),
                  "developerInstructions": codex_instructions(settings, chat.state_dir),
                  "config": {"sandbox_workspace_write.network_access": False, "features.multi_agent": False,
                             "features.shell_tool": settings.get("sources") != CONNECTED},
                  "serviceTier": "fast" if settings.get("fast") else None}
        if settings.get("model"):
            params["model"] = settings["model"]
        if resume_id:
            params.update(threadId=resume_id, excludeTurns=True)
        try:
            result = self.proc.request("thread/resume" if resume_id else "thread/start", params)
        except ChatError:
            if not resume_id:
                raise
            params.pop("threadId"), params.pop("excludeTurns")
            result = self.proc.request("thread/start", params)
        self.thread_id = result["thread"]["id"]
        self.session_id = self.thread_id
        s.emit({"t": "ready", "provider": "codex", "model": result.get("model") or settings.get("model")})

    def signature(self):
        # Codex takes model, effort, speed and permissions per turn: only the agent itself matters.
        return {}

    def send(self, text):
        settings = self.settings = self.s.settings
        self.pending_mcp.clear()
        params = {**codex_policy(codex_mode(settings), str(self.cwd)),
                  "serviceTier": "fast" if settings.get("fast") else None, "threadId": self.thread_id,
                  "input": [{"type": "text", "text": text, "text_elements": []}]}
        if settings.get("model"):
            params["model"] = settings["model"]
        if settings.get("effort") and settings["effort"] != "default":
            params["effort"] = settings["effort"]

        def start():
            try:
                self.turn_id = self.proc.request("turn/start", params)["turn"]["id"]
            except ChatError as e:
                self.s.turn_done(True, str(e))
        threading.Thread(target=start, daemon=True).start()

    def interrupt(self):
        if self.turn_id:
            threading.Thread(target=lambda: self._quiet("turn/interrupt", {"threadId": self.thread_id, "turnId": self.turn_id}),
                             daemon=True).start()

    def _quiet(self, method, params):
        try:
            self.proc.request(method, params, timeout=5)
        except ChatError:
            pass

    def notify(self, method, p):
        s = self.s
        if p.get("threadId") not in (None, self.thread_id):
            return
        item = p.get("item") or {}
        kind = item.get("type")
        if method == "item/agentMessage/delta":
            if p.get("itemId") not in self.streamed:
                self.streamed.add(p.get("itemId"))
                s.emit({"t": "text_start"})
                s.emit({"t": "activity", "label": "Writing…"})
            s.emit({"t": "text", "text": p.get("delta", "")})
        elif method in ("item/reasoning/textDelta", "item/reasoning/summaryTextDelta"):
            s.emit({"t": "activity", "label": "Thinking…"})
        elif method == "item/started":
            if kind == "commandExecution":
                s.emit({"t": "tool", "id": item.get("id"), "name": "command", "title": item.get("command", ""),
                        "input": {"command": item.get("command"), "cwd": item.get("cwd")}})
                s.emit({"t": "activity", "label": "Working…"})
            elif kind == "fileChange":
                paths = [c.get("path") for c in item.get("changes") or []]
                s.emit({"t": "tool", "id": item.get("id"), "name": "files", "title": ", ".join(filter(None, paths)),
                        "input": {"changes": paths}})
                s.emit({"t": "activity", "label": "Making changes…"})
            elif kind == "mcpToolCall":
                self.pending_mcp[item.get("id")] = item
                s.emit({"t": "tool", "id": item.get("id"), "name": item.get("tool", ""), "title": item.get("tool", ""),
                        "input": item.get("arguments") or {}})
                s.emit({"t": "activity", "label": f"Using {item.get('tool', 'a tool')}"})
            elif kind == "reasoning":
                s.emit({"t": "activity", "label": "Thinking…"})
        elif method == "item/completed":
            if kind == "agentMessage" and item.get("id") not in self.streamed and item.get("text"):
                s.emit({"t": "text_start"})
                s.emit({"t": "text", "text": item["text"]})
            elif kind == "mcpToolCall":
                self.pending_mcp.pop(item.get("id"), None)
                result = item.get("result") or {}
                failed = item.get("status") == "failed" or bool(item.get("error"))
                s.emit({"t": "tool_result", "id": item.get("id"), "error": failed,
                        "summary": (result_text(result.get("content")) or str(item.get("error") or ""))[:1500]})
            elif kind in ("commandExecution", "fileChange"):
                failed = item.get("status") == "failed" or item.get("exitCode") not in (None, 0)
                s.emit({"t": "tool_result", "id": item.get("id"), "error": failed,
                        "summary": str(item.get("aggregatedOutput") or "")[:1500]})
        elif method == "turn/completed":
            turn = p.get("turn") or {}
            ok = turn.get("status") == "completed"
            s.turn_done(not ok, "" if ok else ((turn.get("error") or {}).get("message") or f"Work {turn.get('status')}"))
        elif method == "serverRequest/resolved":
            s.resolve(p.get("requestId"), "Resolved")

    def request(self, msg):
        method, p, rid = msg.get("method"), msg.get("params") or {}, msg.get("id")
        persist = (p.get("_meta") or {}).get("persist") or []
        if method in ("item/commandExecution/requestApproval", "item/fileChange/requestApproval"):
            decisions = p.get("availableDecisions") or ["accept", "acceptForSession", "decline"]
            labels = {"accept": "Allow once", "acceptForSession": "Allow for this session", "decline": "Decline",
                      "cancel": "Cancel"}
            options = [(labels.get(d, str(d)) if isinstance(d, str) else "Allow with policy change", {"decision": d})
                       for d in decisions]
            title = ("Allow network access?" if p.get("networkApprovalContext") else
                     "Allow this action?" if "command" in method else "Allow these file changes?")
        elif method == "item/permissions/requestApproval":
            perms = {k: v for k, v in (p.get("permissions") or {}).items() if v is not None}
            options = [("Allow once", {"permissions": perms, "scope": "turn"}),
                       ("Allow for this session", {"permissions": perms, "scope": "session"}),
                       ("Decline", {"permissions": {}, "scope": "turn"})]
            title = "Allow additional access?"
        elif method == "mcpServer/elicitation/request":
            meta = p.get("_meta") or {}
            candidates = [call for call in self.pending_mcp.values()
                          if call.get("server") == p.get("serverName")
                          and "tool_params" in meta and call.get("arguments") == meta["tool_params"]]
            allowed = READ_TOOLS + (MORNING_WRITES if self.settings.get("role") != CHECKER else [])
            morning_read = self.settings.get("sources") == CONNECTED and candidates and all(
                (call.get("server") == "verticals_desktop" and call.get("tool") in allowed)
                or f"mcp__{call.get('server')}__{call.get('tool')}" in self.reads for call in candidates)
            full = self.settings.get("permission") == "full-access" and self.settings.get("role") != CHECKER
            if (p.get("mode") == "form" and meta.get("codex_approval_kind") == "mcp_tool_call"
                    and (full or morning_read)):
                return self.proc.reply(rid, {"action": "accept", "content": {}, "_meta": None})
            options = [("Allow once", {"action": "accept", "content": {}, "_meta": None})]
            options += [("Allow for this session" if k == "session" else "Always allow",
                         {"action": "accept", "content": {}, "_meta": {"persist": k}})
                        for k in ("session", "always") if k in persist]
            options.append(("Decline", {"action": "decline", "content": None, "_meta": None}))
            title = "Allow app access?"
        elif method == "item/tool/requestUserInput":
            questions = p.get("questions") or []
            if not questions:
                return self.proc.reply(rid, {"answers": {}})
            q = questions[0]
            options = [(o.get("label", ""), {"answers": {q.get("id"): {"answers": [o.get("label", "")]}}})
                       for o in q.get("options") or []] or [("OK", {"answers": {q.get("id"): {"answers": []}}})]
            title = q.get("header") or q.get("question") or "Answer"
            p = {"message": q.get("question")}
        else:
            return self.proc.reply(rid, error={"code": -32601, "message": "This operation is not supported by Verticals"})
        body = "\n\n".join(filter(None, [p.get("message"), p.get("reason"),
                                         " ".join(p["command"]) if isinstance(p.get("command"), list) else p.get("command"),
                                         json.dumps(p.get("input"), indent=2, ensure_ascii=False) if p.get("input") else None]))
        key = str(rid)
        self.approvals[key] = (rid, [o[1] for o in options])
        self.s.ask(self, key, title, body, [(label, str(i)) for i, (label, _) in enumerate(options)])

    def decide(self, key, option):
        rid, responses = self.approvals.pop(key, (None, []))
        if rid is None:
            return
        try:
            self.proc.reply(rid, responses[int(option)])
        except (ValueError, IndexError):
            self.proc.reply(rid, responses[-1])  # last option is always the refusal

    def exited(self, code, detail):
        self.s.agent_exited(self, code, detail)

    def close(self):
        self.proc.close()


AGENT_CLASSES = {"claude": ClaudeAgent, "codex": CodexAgent}


# ---------------------------------------------------------------- conversations

class Session:
    def __init__(self, chat, id):
        self.chat, self.id = chat, id
        self.agent = None
        self.events, self.seq = [], 0
        self.flow = None                 # the morning report's turns, while there are several (morning_flow.py)
        self.holding = None              # the flow keeps a turn's words here until it knows which turn is the last
        self.cond = threading.Condition()
        self.running = False
        self.queue = []                  # (text, context, settings) sent after the current turn
        self.turn = None                 # (text, context, settings) of the message the running turn answers: what goes again
        self.asks = {}                   # request key -> agent
        self.settings = {}
        self.started_at = None
        self.reply = ""                  # text of the agent's current reply, for handoffs
        self.tools = {}                  # tool call id -> (name, input) until its result comes
        self.answer = None               # id of the answer the running turn is: what its writes are kept under

    # -- events

    def emit(self, event):
        if self.holding is not None and event["t"] in ("text", "text_start"):
            self.holding.append(event)
            return
        with self.cond:
            self.seq += 1
            self.events.append((self.seq, event))
            del self.events[:-MAX_EVENTS]
            self.cond.notify_all()
        if line := log_line(self.id, event):
            self.chat.log.info(line)
        if event["t"] == "text":
            self.reply += event["text"]
        elif event["t"] == "text_start" and self.reply:
            self.reply += "\n\n"
        elif event["t"] == "tool":
            self.tools[event.get("id")] = (event.get("name"), event.get("input") or {})
        elif event["t"] == "tool_result":
            name, tool_input = self.tools.pop(event.get("id"), (None, {}))
            goal_id = made_goal(event.get("summary")) if name == "create" and not event.get("error") else None
            if goal_id:
                title = tool_input.get("title") if isinstance(tool_input, dict) else None
                self.chat.bind_goal(self, goal_id, title if isinstance(title, str) else "")

    def since(self, seq, timeout):
        with self.cond:
            if not any(s > seq for s, _ in self.events):
                self.cond.wait(timeout)
            return [(s, e) for s, e in self.events if s > seq]

    def ask(self, agent, key, title, body, options, tool=None, tool_input=None, note=None):
        """`tool` and `tool_input` are the write the agent wants to make, as it calls it: the app draws what will change from
        them (web lib/askDetail.ts, docs/design/agent-fixes.md, fix 6), where `body` is only stored. `note` is the line an ask
        the app makes of its own shows under its title (the sign-in, agent_signin.py)."""
        self.asks[key] = agent
        self.emit({"t": "permission", "requestId": key, "title": title, "body": body,
                   "options": [{"label": label, "value": value} for label, value in options],
                   **({"tool": tool, "input": tool_input or {}} if tool else {}), **({"note": note} if note else {})})

    def resolve(self, key, label):
        if key is not None and self.asks.pop(str(key), None):
            self.emit({"t": "permission_done", "requestId": str(key), "label": label})

    def open_question(self):
        """The ask of the agent's question that waits, if one does: words sent now answer it (Chat._send)."""
        return next((key for key, agent in self.asks.items() if key in getattr(agent, "questions", {})), None)

    # -- lifecycle

    def turn_done(self, error, detail):
        if not self.running:
            return
        # The morning report is several turns (writing, checking, fixing); the flow takes each turn's end and ends the answer.
        if self.flow is not None and self.flow.took(error, detail):
            return
        self.finish(error, detail)

    def finish(self, error, detail, signed_out=None):
        """The answer ends: its words are recorded, the owner is told it is done, and the next queued message starts. A turn that
        failed because its agent is signed out ends with the sign-in's ask instead of the error, and the queue waits behind it
        (agent_signin.py); `signed_out` is that, when the caller knows it already."""
        if not self.running:
            return
        if signed_out is None:
            signed_out = bool(error) and self.chat.signin.signed_out(self, detail)
        waiting = self.chat.signin.hold(self) if signed_out else None
        self.running = False
        self.tools.clear()
        ms = int((time.time() - (self.started_at or time.time())) * 1000)
        self.chat.record(self.id, "assistant", self.reply)
        at = time.time()
        self.chat.update(self.id, lastTurnAt=at)
        answer, self.answer = self.answer, None
        # The answer ends at the MCP server before the page is told: it asks for the answer as soon as it hears of its end.
        self.chat.close_answer(answer)
        self.emit({"t": "done", "error": bool(error), "detail": "" if waiting else detail or "", "ms": ms, "at": at,
                   "answer": answer, **({"signin": True} if waiting else {})})
        for key in list(self.asks):
            self.resolve(key, "Expired")
        if waiting is not None:
            return self.chat.signin.show(waiting)
        if self.queue:
            text, context, settings = self.queue.pop(0)
            threading.Thread(target=self.chat.start_turn, args=(self, text, context, settings), daemon=True).start()

    def agent_exited(self, agent, code, detail):
        if self.agent is not agent:
            return
        self.agent = None
        if self.flow is not None:
            self.flow.abandon()
        if self.running and code and self.chat.signin.signed_out(self, detail):
            return self.finish(True, detail, signed_out=True)  # a CLI that stops because it is signed out asks as a turn does
        if self.running:
            self.running = False
            answer, self.answer = self.answer, None
            self.chat.close_answer(answer)
            self.emit({"t": "exit", "code": code, "detail": detail if code else "", "answer": answer})
        self.queue.clear()


class Chat:
    def __init__(self, state_dir: Path, mcp_url: str, token: str, api_url: str | None = None, watch_every: float | None = None):
        self.state_dir, self.mcp_url, self.token = state_dir, mcp_url, token
        # The Verticals API the gateway itself talks to: the sources the morning turn reads, and the second agent's verdict
        # (morning_flow.py). Without it the morning report is made as before, with no second check.
        self.api_url = api_url.rstrip("/") if api_url else None
        self.log = open_log(state_dir)
        self.log.info("gateway start pid=%d", os.getpid())
        self.sessions: dict[str, Session] = {}
        self.lock = threading.Lock()
        self.store_path = state_dir / "chat-sessions.json"
        self.models, self.probes = {}, {}
        # What the sessions of tasks look like on disk (docs/design/task-sessions.md): where each file was found, its size and
        # time at the last look, and the store as it was when its own file last changed.
        self.files: dict[tuple, Path] = {}
        self.missing: dict[tuple, float] = {}
        self.moved: dict[str, tuple[int, float]] = {}
        self._cached, self._stamp = {}, None
        self.stopping = threading.Event()
        # A signed-out agent is signed back in from the field (docs/design/agent-sign-in.md): the asks, and one login per agent.
        self.signin = agent_signin.SignIn(self, AGENTS, lambda provider: which(provider), lambda: child_env())
        # The MCP server also answers the record of what each answer wrote, beside its /mcp endpoint.
        self.answers_url = mcp_url.removesuffix("/mcp")
        for stale in state_dir.glob("chat-mcp*.json"):
            stale.unlink(missing_ok=True)
        # A writable default outside the app; an explicitly selected checkout replaces it.
        self.workdir = state_dir / "chat-workspace"
        self.workdir.mkdir(exist_ok=True)
        self.workdir = find_source(state_dir, explicit_only=True) or self.workdir
        every = float(os.environ.get("VERTICALS_WATCH_SECONDS", WATCH_SECONDS)) if watch_every is None else watch_every
        if every > 0:
            threading.Thread(target=self._watch, args=(every,), daemon=True).start()

    # -- the agents' connection to the MCP server

    def claude_config(self, session_id=None):
        """One conversation's Claude connects to the app's MCP server with the token and the conversation's id in its headers: every
        call it makes says whose it is, and the server keeps what the answers of that conversation wrote. A seat that is no
        conversation (the morning report's second agent, morning_flow.py) connects with none, and its calls are nobody's answer.
        Owner-only files: the MCP bearer token must not appear in `ps` output."""
        path = self.state_dir / (f"chat-mcp-{session_id}.json" if session_id else "chat-mcp.json")
        if not path.exists():
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "w") as f:
                json.dump({"mcpServers": {"verticals": {"type": "http", "url": self.mcp_url, "headers": {
                    "Authorization": f"Bearer {self.token}", **({"X-Verticals-Session": session_id} if session_id else {})}}}}, f)
        return path

    # -- the record of what each answer wrote (verticals/mcp/answers.py, docs/design/agent-answer-undo.md)

    def answers_call(self, route, body=None, timeout=3):
        """A call to the MCP server's record of the answers. Best effort: without it an answer has no Undo, and the conversation
        goes on as it did."""
        request = urllib.request.Request(
            f"{self.answers_url}/answers/{route}", data=json.dumps(body or {}).encode(), method="POST",
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {self.token}"})
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return json.loads(response.read() or b"{}")
        except (OSError, ValueError):
            return None

    def open_answer(self, session_id, answer):
        self.answers_call("open", {"session": session_id, "answer": answer})

    def close_answer(self, answer):
        if answer:
            self.answers_call("close", {"answer": answer})

    def recent_answers(self):
        """The answers that have ended, the last few, each with what its writes changed (what the page makes its Undo of). Reading
        takes nothing away: a window that opens later finds the answers given while it was closed."""
        got = self.answers_call("recent", {"limit": 20}, timeout=10)
        answers = got.get("answers") if isinstance(got, dict) else None
        return answers if isinstance(answers, list) else []

    def answer_state(self, answer, state):
        """What became of an answer (`standing`, `undone`, `spent`): kept with it, so a page that opens again shows Redo where it
        showed Redo."""
        if isinstance(answer, str) and isinstance(state, str):
            self.answers_call("state", {"answer": answer, "state": state})

    # -- persistence: agent session ids and a short transcript per conversation

    def load(self):
        try:
            data = json.loads(self.store_path.read_text())
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def save(self, data):
        tmp = self.store_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data))
        os.replace(tmp, self.store_path)

    def update(self, id, **fields):
        with self.lock:
            data = self.load()
            data.setdefault(id, {}).update(fields)
            self.save(data)

    def record(self, id, role, text):
        if not text.strip():
            return
        with self.lock:
            data = self.load()
            log = data.setdefault(id, {}).setdefault("transcript", [])
            log.append([role, text[:4000]])
            del log[:-40]
            self.save(data)

    def entries(self):
        """The store as a dict, read again only when its file has changed: the watcher asks every few seconds."""
        try:
            stat = self.store_path.stat()
        except OSError:
            return {}
        stamp = (stat.st_mtime_ns, stat.st_size)
        if stamp != self._stamp:
            self._cached, self._stamp = self.load(), stamp
        return self._cached

    # -- sessions of tasks: where each lives, when it moved, whether it went on outside (docs/design/task-sessions.md)

    def stat_of(self, provider, session_id):
        """(size, modified time) of a session's file, which is all Verticals ever knows of it: nothing in it is read."""
        key, now = (provider, session_id), time.time()
        if now - self.missing.get(key, 0) < MISSING_SECONDS:
            return None
        path = agent_sessions.session_file(provider, session_id, self.files.get(key))
        if path is None:
            self.files.pop(key, None)
            self.missing[key] = now  # a session that has no file (yet) is not searched for at every look
            return None
        self.files[key] = path
        return agent_sessions.file_stat(path)

    def conversation(self, key, entry, now):
        """One session of a task as the app lists it: when it last moved is the later of its file's time and Verticals' own
        last turn in it; it is working while Verticals drives it or while a file that went on outside is still being written."""
        known = entry.get("provider") in AGENTS and entry.get("sessionId")
        stat = self.moved.get(key) or (self.stat_of(entry["provider"], entry["sessionId"]) if known else None)
        turn = entry.get("lastTurnAt") or 0
        live = self.sessions.get(key)
        outside = bool(entry.get("outside"))
        return {"session": key, "provider": entry.get("provider"), "title": (entry.get("goal") or {}).get("title", ""),
                "lastTurnAt": turn, "agentSession": entry.get("sessionId"), "cwd": entry.get("cwd"),
                "movedAt": max(turn, stat[1] if stat else 0), "outside": outside,
                "working": bool(live and live.running) or (outside and bool(stat) and now - stat[1] < agent_sessions.WORKING_SECONDS)}

    def api(self, method, path, body=None, timeout=20):
        """One call to the Verticals API as the owner's app, answered as JSON. Raises ChatError with what the server said."""
        if not self.api_url:
            raise ChatError("The Verticals API is not known to the gateway")
        request = urllib.request.Request(
            self.api_url + path, method=method, data=None if body is None else json.dumps(body).encode(),
            headers={"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return json.loads(response.read() or b"{}")
        except urllib.error.HTTPError as e:
            try:
                said = json.loads(e.read() or b"{}").get("message") or e.reason
            except ValueError:
                said = e.reason
            raise ChatError(f"{method} {path.split('?')[0]}: {e.code} {said}") from e
        except (OSError, ValueError) as e:
            raise ChatError(f"{method} {path.split('?')[0]}: {e}") from e

    def describe(self, context):
        """What an agent is told about the screen and the day, as `format_context` writes it."""
        return format_context(context)

    def make_agent(self, seat, settings, resume=None):
        """An agent of the settings' kind seated in `seat` (a conversation, or the second agent's quiet seat)."""
        return AGENT_CLASSES[settings["provider"]](self, seat, settings, resume)

    def goal_conversations(self, goal_id):
        """A goal's sessions, the one that moved last first: Discuss with agent continues the first (docs/design-handoff S3.P1,
        docs/design/task-sessions.md), and Open in lists them all."""
        now = time.time()
        found = [self.conversation(key, entry, now) for key, entry in self.entries().items()
                 if isinstance(entry, dict) and (entry.get("goal") or {}).get("id") == goal_id]
        return sorted(found, key=lambda c: c["movedAt"], reverse=True)

    def sessions_state(self):
        """What the board needs of every task that has a session: its sessions, whether one works now, and the agent of the
        newest session that went on outside, whose mark the card shows."""
        now, goals = time.time(), {}
        for key, entry in self.entries().items():
            goal = entry.get("goal") if isinstance(entry, dict) else None
            if isinstance(goal, dict) and goal.get("id") and entry.get("provider"):
                goals.setdefault(goal["id"], []).append(self.conversation(key, entry, now))
        out = {}
        for goal_id, found in goals.items():
            found.sort(key=lambda c: c["movedAt"], reverse=True)
            outside = next((c for c in found if c["outside"]), None)
            out[goal_id] = {"sessions": found, "working": any(c["working"] for c in found),
                            "outside": {"provider": outside["provider"], "at": outside["movedAt"]} if outside else None}
        return {"goals": out}

    def look(self):
        """One look at the files of the sessions that belong to a task: a stat each, no model, no token. A file that grew while
        Verticals was not driving its session means the owner went on in Claude or Codex: the session is marked, and the card
        and the row say so. What Verticals itself writes (a turn running, or just ended) is not that."""
        now = time.time()
        for key, entry in list(self.entries().items()):
            goal = entry.get("goal") if isinstance(entry, dict) else None
            if not (isinstance(goal, dict) and goal.get("id") and entry.get("sessionId") and entry.get("provider") in AGENTS):
                continue
            stat = self.stat_of(entry["provider"], entry["sessionId"])
            if stat is None:
                self.moved.pop(key, None)
                continue
            self.moved[key] = stat
            now_seen, seen = {"size": stat[0], "mtime": stat[1]}, entry.get("seen") or {}
            live = self.sessions.get(key)
            driven = bool(live and live.running) or now - (entry.get("lastTurnAt") or 0) < agent_sessions.DRIVEN_GRACE
            if driven or not seen or stat[0] < seen.get("size", 0):
                # Its own writes, a first sight or a file that was replaced: this is the new reference.
                if seen != now_seen:
                    self.update(key, seen=now_seen)
            elif stat[0] - seen["size"] >= agent_sessions.MIN_GROWTH:
                self.update(key, seen=now_seen, outside=True)
                self.log.info("outside provider=%s session=%s", entry["provider"], str(key)[:8])

    def _watch(self, every):
        while not self.stopping.wait(every):
            try:
                self.look()
            except Exception as e:  # noqa: BLE001 - one bad file must not stop the watch
                self.log.warning("look_failed %s", clip(e))

    def link_session(self, goal, provider, session=None, cwd=None):
        """A session begun in Claude or Codex, tied to a task by the agent that is in it (the link tool,
        verticals/mcp/session.py). Claude Code is never told its own id, so it gives the folder it works in and the session is
        the one written to in the last minute there. A session already tied to a task keeps it, as a conversation that made a
        goal does (bind_goal)."""
        if not isinstance(goal, dict) or not agent_sessions.GOAL_ID.fullmatch(str(goal.get("id") or "")):
            raise ChatError("Not a task of Verticals")
        if provider not in AGENTS:
            raise ChatError("Not an agent Verticals knows: claude or codex")
        cwd = cwd if isinstance(cwd, str) and os.path.isabs(cwd) and len(cwd) < 2000 else None
        if not session:
            if provider != "claude":
                raise ChatError("Codex: give your thread id, the CODEX_THREAD_ID of your shell")
            if not cwd:
                raise ChatError("Claude Code: give the folder you work in as cwd, or your session id")
            found = agent_sessions.active_claude_sessions(cwd, time.time())
            if len(found) != 1:
                raise ChatError(("%d Claude sessions were written to in that folder in the last minute" % len(found)
                                 if found else "No Claude session was written to in that folder in the last minute")
                                + ": give your session id")
            session = found[0]
        if not agent_sessions.is_session_id(session):
            raise ChatError("The session id is not an id")
        self.missing.pop((provider, session), None)
        stat = self.stat_of(provider, session)
        with self.lock:
            data = self.load()
            key = next((k for k, e in data.items() if isinstance(e, dict) and e.get("sessionId") == session), None)
            entry = data.setdefault(key or session, {})
            if not entry.get("goal"):
                entry["goal"] = {"id": goal["id"], "title": str(goal.get("title") or "")[:300]}
            entry.setdefault("provider", provider)
            entry["sessionId"] = session
            if cwd and not entry.get("cwd"):
                entry["cwd"] = cwd
            if key is None:
                entry["external"] = True
            if stat and not entry.get("seen"):
                entry["seen"] = {"size": stat[0], "mtime": stat[1]}
            self.save(data)
            kept = dict(entry["goal"])
        self.log.info("session_linked provider=%s known=%s", entry["provider"], key is not None)
        return {"session": key or session, "provider": entry["provider"], "goal": kept, "same": kept["id"] == goal["id"]}

    def open_session(self, key):
        """Open a session where it lives (docs/design/task-sessions.md): a Codex thread by its link, a Claude session in Terminal
        with `claude --resume <id>` from its folder, by a script of the app's own that Terminal runs."""
        entry = self.entries().get(key)
        if not isinstance(entry, dict) or not entry.get("sessionId") or entry.get("provider") not in AGENTS:
            raise ChatError("No such session")
        action = agent_sessions.open_action(entry["provider"], entry["sessionId"], entry.get("cwd"))
        opener = shutil.which("open", path=child_env()["PATH"])
        if not opener:
            raise ChatError("This computer has no way to open it")
        if action["kind"] == "terminal":
            folder = self.state_dir / "open"
            folder.mkdir(mode=0o700, exist_ok=True)
            script = folder / f"claude-{entry['sessionId']}.command"
            script.write_text(agent_sessions.terminal_script(action, which("claude"), os.environ.get("CLAUDE_CONFIG_DIR")))
            script.chmod(0o700)
            argv = [opener, "-a", "Terminal", str(script)]
        else:
            argv = [opener, action["url"]]
        try:
            done = subprocess.run(argv, cwd=self.workdir, env=child_env(), capture_output=True, text=True, timeout=15)
        except (OSError, subprocess.SubprocessError) as e:
            raise ChatError(f"Could not open it: {clip(e)}") from e
        self.log.info("open provider=%s kind=%s code=%d session=%s", entry["provider"], action["kind"], done.returncode, str(key)[:8])
        if done.returncode:
            app = "Terminal" if action["kind"] == "terminal" else AGENTS[entry["provider"]]["label"]
            raise ChatError(f"{app} did not open it" + (f": {clip(done.stderr)}" if done.stderr.strip() else ""))
        return {"kind": action["kind"]}

    def bind_goal(self, s, goal_id, title):
        """A conversation about no goal that makes one becomes that goal's conversation (docs/design/agent-chips.md): Discuss
        with agent on the new goal goes on with it. The first goal made is the one; a conversation that already has a goal
        keeps it. The app is told (a `goal` event) so its own record of the conversation says the same."""
        with self.lock:
            data = self.load()
            entry = data.setdefault(s.id, {})
            if entry.get("goal"):
                return
            entry["goal"] = {"id": goal_id, "title": title[:300]}
            self.save(data)
        s.emit({"t": "goal", "id": goal_id, "title": title[:300]})

    def session(self, id) -> Session:
        try:
            uuid.UUID(str(id))
        except ValueError:
            raise ChatError("Invalid conversation")
        with self.lock:
            if id not in self.sessions:
                self.sessions[id] = Session(self, id)
            return self.sessions[id]

    def busy(self):
        """Whether an agent is in the middle of a turn: the app's Restart waits for it."""
        with self.lock:
            return any(s.running for s in self.sessions.values())

    # -- agents, models, usage

    def agents(self):
        out = []
        for id, a in sorted(AGENTS.items(), key=lambda kv: kv[1]["order"]):
            out.append({"id": id, "label": a["label"], "image": a["image"], "available": bool(which(id)),
                        "efforts": [{"value": v, "label": l} for v, l in a["efforts"]],
                        "defaultEffort": a["defaultEffort"], "fast": a["fast"],
                        "permissions": [{"value": v, "label": l, "detail": d} for v, l, d in a["permissions"]],
                        "defaultPermission": a["defaultPermission"]})
        return out

    def remember_models(self, provider, raw):
        models = [{"value": m.get("value"), "label": m.get("displayName") or m.get("value"),
                   "detail": m.get("description") or ""} for m in raw if isinstance(m, dict) and m.get("value")]
        if models:
            self.models[provider] = (time.time(), models)

    def probe(self, provider):
        """Models and usage for the agent picker; cached for a minute like Enjoy's model list."""
        if provider not in AGENTS:
            raise ChatError("Unknown agent")
        cached = self.probes.get(provider)
        if cached and time.time() - cached[0] < 60:
            return cached[1]
        if not which(provider):
            return {"available": False, "models": [], "usage": {"state": "unavailable", "message": "Not installed"}}
        try:
            result = self._probe_claude() if provider == "claude" else self._probe_codex()
        except (ChatError, OSError, subprocess.SubprocessError) as e:
            result = {"available": True, "models": [], "modelsError": "Could not load models from this agent.",
                      "usage": {"state": "unavailable", "message": str(e)[:200]}}
        self.probes[provider] = (time.time(), result)
        return result

    def _probe_claude(self):
        got, done = {}, threading.Event()

        def on_message(msg):
            if msg.get("type") != "control_response":
                return
            resp = msg.get("response") or {}
            got[resp.get("request_id")] = resp.get("response") or {}
            if "initialize" in got and "usage" in got:
                done.set()

        # A throwaway process: nothing it does may show up in the user's Claude history.
        proc = JsonProcess([which("claude"), "--print", "--verbose", "--input-format", "stream-json",
                            "--output-format", "stream-json", "--strict-mcp-config", "--mcp-config",
                            '{"mcpServers":{}}', "--tools", "", "--no-session-persistence"],
                           self.workdir, child_env(), on_message, lambda *_: done.set())
        try:
            proc.send({"type": "control_request", "request_id": "initialize", "request": {"subtype": "initialize"}})
            proc.send({"type": "control_request", "request_id": "usage",
                       "request": {"subtype": "get_usage", "skip_behaviors": True}})
            done.wait(20)
        finally:
            proc.close()
        self.remember_models("claude", (got.get("initialize") or {}).get("models") or [])
        raw = got.get("usage") or {}
        limits = raw.get("rate_limits") or {}
        windows = [window(label, (limits.get(key) or {}).get("utilization")) for key, label in CLAUDE_USAGE.items()]
        for m in limits.get("model_scoped") or []:
            if isinstance(m, dict) and isinstance(m.get("display_name"), str):
                windows.append(window(f"Weekly · {m['display_name']}", m.get("utilization")))
        missing = ("Subscription quota unavailable for this Claude account." if raw.get("rate_limits_available") is False
                   else "Claude did not return usage. Reopen to retry.")
        models = self.models.get("claude", (0, []))[1]
        return {"available": True, "models": models, "usage": usage_state(windows, missing),
                **({} if models else {"modelsError": "This agent did not provide a model list."})}

    def _probe_codex(self):
        proc = RpcProcess(codex_args(self), self.workdir,
                          child_env({"VERTICALS_MCP_URL": self.mcp_url, "VERTICALS_MCP_TOKEN": self.token}),
                          lambda *_: None, lambda msg: None, lambda *_: None)
        try:
            proc.request("initialize", {"clientInfo": {"name": "verticals-desktop", "title": "Verticals", "version": "0.1.0"},
                                        "capabilities": {"experimentalApi": True}}, timeout=20)
            proc.notify("initialized", {})
            models, cursor, seen = [], None, set()
            for _ in range(20):
                page = proc.request("model/list", {"cursor": cursor, "includeHidden": False}, timeout=20)
                for m in page.get("data") or []:
                    value = m.get("model")
                    if not value or value in seen or m.get("hidden"):
                        continue
                    seen.add(value)
                    label, detail, image = CODEX_MODELS.get(value, (m.get("displayName") or value, m.get("description") or "", None))
                    models.append({"value": value, "label": label, "detail": detail, **({"image": image} if image else {})})
                cursor = page.get("nextCursor")
                if not cursor:
                    break
            try:
                usage = codex_usage(proc.request("account/rateLimits/read", {}, timeout=15))
            except ChatError as e:
                usage = {"state": "unavailable", "message": str(e)[:200]}
        finally:
            proc.close()
        return {"available": True, "models": models, "usage": usage,
                **({} if models else {"modelsError": "This agent did not provide a model list."})}

    # -- turns

    def send(self, id, text, context=None, settings=None, mode="send"):
        try:
            self._send(id, text, context, settings, mode)
        except ChatError as e:
            self.log.warning("refused %s session=%s", clip(e), str(id)[:8])
            raise

    def _send(self, id, text, context, settings, mode):
        if not isinstance(text, str) or not text.strip():
            raise ChatError("Empty message")
        s = self.session(id)
        settings = clean_settings(settings)
        goal = context.get("goal") if isinstance(context, dict) else None
        if isinstance(goal, dict) and isinstance(goal.get("id"), str) and len(goal["id"]) < 100:
            self.update(id, goal={"id": goal["id"], "title": str(goal.get("title", ""))[:300]})
        if isinstance(context, dict) and isinstance(context.get("replan"), dict) and not self.load().get(id, {}).get("sessionId"):
            # A conversation that Replan starts stays a Replan conversation for its later turns, and after the gateway starts
            # again (start_turn reads it): its writes run without a question for each (REPLAN_WRITES).
            self.update(id, replan=True)
        if not which(settings["provider"]):
            raise ChatError(f"{AGENTS[settings['provider']]['label']} is not installed.")
        self.log.info("send provider=%s permission=%s morning=%s chars=%d mode=%s queued=%s session=%s",
                      settings["provider"], settings["permission"], "sources" in settings, len(text), mode, s.running, str(id)[:8])
        s.emit({"t": "user", "text": text, "provider": settings["provider"], "model": settings.get("model"),
                "effort": settings.get("effort")})
        self.record(id, "user", text)
        question = s.open_question()
        if question is not None:
            # Words typed while the agent's question waits are its answer, in the owner's words: no turn starts for them.
            self.decide(id, question, text, typed=True)
            return
        if self.signin.holds(s.id):
            # Behind a sign-in every message waits, in the order sent, and goes after the one that failed (agent_signin.py).
            s.queue.append((text, context, settings))
            return
        if s.running:
            # Enjoy: Enter queues after the current turn; "send now" interrupts it first.
            if mode == "now":
                s.queue.insert(0, (text, context, settings))
                if s.agent:
                    s.agent.interrupt()
            else:
                s.queue.append((text, context, settings))
            return
        threading.Thread(target=self.start_turn, args=(s, text, context, settings), daemon=True).start()

    def start_turn(self, s: Session, text, context, settings, stage=None):
        # A later turn of the morning report (the fixing turn, `stage`) goes on with the answer the ask began: its writes join
        # that answer, which ends when the report is told (docs/design/morning-quality.md: the whole morning's changes are
        # taken back at once from the report's answer).
        s.running, s.reply = True, ""
        if stage is None:
            s.turn = (text, context, settings)
            s.started_at = time.time()
            s.answer = secrets.token_hex(8)  # this turn is one answer, and what its writes change is kept under this id
        stored = self.load().get(s.id, {})
        if stored.get("replan"):
            settings = {**settings, "replan": True}  # a Replan conversation's every turn (_send), so its agent stays the same
        s.settings = settings
        provider = settings["provider"]
        handoff, fresh = "", False
        try:
            agent = s.agent
            changed_provider = agent is not None and agent.provider != provider or \
                (agent is None and stored.get("provider") not in (None, provider))
            # A session that went on in Claude or Codex has said things this process never heard: its agent is started again
            # from the session's own file, so what it knows is what the session holds (docs/design/task-sessions.md).
            went_on = bool(stored.get("outside")) and not changed_provider
            if agent and (agent.provider != provider or went_on
                          or agent.signature() != AGENT_CLASSES[provider].signature_of(settings)):
                s.agent = None
                agent.close()
                agent = None
            if agent is None:
                resume = None if changed_provider else stored.get("sessionId")
                if changed_provider or (resume is None and stored.get("transcript")):
                    handoff = format_handoff(stored.get("transcript") or [], text)
            s.emit({"t": "turn_start", "provider": provider, "model": settings.get("model"),
                    "effort": settings.get("effort"), "answer": s.answer, **({"stage": stage} if stage else {})})
            if agent is None:
                s.emit({"t": "activity", "label": "Starting…"})
                self.log.info("agent_start provider=%s resume=%s handoff=%d session=%s", provider, bool(resume), len(handoff),
                              str(s.id)[:8])
                # The session lives in the folder it began in; one that began outside Verticals keeps the system prompt it
                # recorded unless Claude is told to build it again.
                folder = Path(stored["cwd"]) if resume and stored.get("cwd") and Path(stored["cwd"]).is_dir() else self.workdir
                if folder == self.state_dir / "chat-workspace":
                    folder = self.workdir
                agent = AGENT_CLASSES[provider](self, s, settings, resume, cwd=folder,
                                                rebuild_prompt=bool(resume and stored.get("external")))
                s.agent, fresh = agent, resume is None
                self.update(s.id, provider=provider, sessionId=agent.session_id, cwd=str(folder))
                self.missing.pop((provider, agent.session_id), None)
            if stored.get("outside"):
                self.update(s.id, outside=None)  # Verticals drives it again: it is no longer "continued outside"
            body = f"<app_context>\n{format_context(context)}\n</app_context>\n\n"
            goal = context.get("goal") if isinstance(context, dict) else None
            if fresh and isinstance(goal, dict) and agent_sessions.GOAL_ID.fullmatch(str(goal.get("id") or "")):
                # A session begun for a task begins with the task's link (docs/design/task-sessions.md): whoever opens it in
                # Claude or Codex sees which task it belongs to, and the agent that finds the link there can link it.
                body = agent_sessions.task_link(goal["id"]) + "\n\n" + body
            if handoff:
                body += handoff + "\n\n"
            if stage is None and settings.get("sources") == CONNECTED:
                # The morning report: written, checked by a second agent, fixed once if a check fails, and told when it is ready.
                flow = MorningFlow.begin(self, s, settings, context, text)
                s.flow, s.holding = flow, [] if flow else None
            if stage is None:
                self.open_answer(s.id, s.answer)  # before the agent hears the words: every call it makes after is this answer's
            agent.send(body + text)
        except (ChatError, OSError) as e:
            s.flow, s.holding = None, None
            if self.signin.signed_out(s, str(e)):
                return s.finish(True, str(e), signed_out=True)
            s.running = False
            self.log.warning("turn_failed_to_start %s session=%s", clip(e), str(s.id)[:8])
            answer, s.answer = s.answer, None
            self.close_answer(answer)
            s.emit({"t": "done", "error": True, "detail": str(e), "ms": 0, "answer": answer})

    def decide(self, id, request_id, value, typed=False):
        """An ask answered: by one of its options (`value`), or, for a question of the agent's, by the owner's own words
        (`typed`), which the event and the log never carry. A question that has another after it asks that one once the field
        knows this one is done."""
        s = self.session(id)
        agent = s.asks.pop(str(request_id), None)
        if agent is None:
            self.log.warning("refused permission no longer active session=%s", str(id)[:8])
            raise ChatError("This request is no longer active")
        then = agent.answer(str(request_id), value, typed=True) if typed else agent.decide(str(request_id), value)
        if agent is not self.signin:  # the sign-in's ask stays open after a click, and says itself how it ends
            s.emit({"t": "permission_done", "requestId": str(request_id), **({"label": "Answered"} if typed else {"value": value})})
        if callable(then):
            then()

    def stop(self, id):
        s = self.session(id)
        s.queue.clear()
        self.signin.drop(s)
        if s.flow is not None:
            s.flow.stop()
        if s.running and s.agent:
            s.agent.interrupt()

    def reset(self, id):
        s = self.sessions.pop(id, None)
        if s:
            self.signin.drop(s)
        if s and s.flow is not None:
            s.flow.abandon()
        if s and s.agent:
            s.agent.close()
        (self.state_dir / f"chat-mcp-{id}.json").unlink(missing_ok=True)

    def shutdown(self):
        self.stopping.set()
        self.signin.close()
        for s in list(self.sessions.values()):
            if s.flow is not None:
                s.flow.abandon()
            if s.agent:
                s.agent.close()
        for config in self.state_dir.glob("chat-mcp*.json"):
            config.unlink(missing_ok=True)
        self.log.info("gateway stop")
        for handler in list(self.log.handlers):
            handler.close()
            self.log.removeHandler(handler)


ClaudeAgent.signature_of = staticmethod(lambda settings: settings)
CodexAgent.signature_of = staticmethod(lambda settings: {})


def clean_settings(raw):
    raw = raw if isinstance(raw, dict) else {}
    provider = raw.get("provider") if raw.get("provider") in AGENTS else "claude"
    agent = AGENTS[provider]
    efforts = {v for v, _ in agent["efforts"]} | {"default"}
    permissions = {v for v, _, _ in agent["permissions"]}
    model = raw.get("model") if isinstance(raw.get("model"), str) and len(raw["model"]) < 200 else ""
    cleaned = {"provider": provider, "model": model,
               "effort": raw.get("effort") if raw.get("effort") in efforts else agent["defaultEffort"],
               "fast": bool(raw.get("fast")),
               "permission": raw.get("permission") if raw.get("permission") in permissions else agent["defaultPermission"]}
    # The morning report's turn is the one that sends `sources`; the gateway gives it its own guide and rules (CONNECTED).
    if raw.get("sources") == CONNECTED:
        cleaned["sources"] = CONNECTED
    return cleaned


def codex_usage(raw):
    raw = raw if isinstance(raw, dict) else {}
    limits = list((raw.get("rateLimitsByLimitId") or {}).items()) or [("codex", raw.get("rateLimits") or {})]
    windows = []
    for key, limit in limits:
        limit = limit if isinstance(limit, dict) else {}
        name = limit.get("limitName") or key
        for part in ("primary", "secondary"):
            w = limit.get(part) or {}
            mins = w.get("windowDurationMins")
            base = ("Weekly" if mins and mins >= 10080 else f"{round(mins / 60)} hours" if mins and mins >= 60 else
                    ("Session" if part == "primary" else "Weekly"))
            windows.append(window(base if key == "codex" else f"{name} · {base}", w.get("usedPercent")))
    return usage_state(windows, "No subscription quota reported for this Codex account.")


def format_handoff(transcript, current):
    """Earlier turns for an agent that did not take part in them (agent switch or lost session): those before the current
    message. The transcript holds it already, and the messages sent after it to wait their turn too: a message that goes again
    once its agent is signed in has the ones that waited behind it there (docs/design/agent-sign-in.md)."""
    lines, total = [], 0
    sent = ["user", current[:4000]]
    cut = max((at for at, said in enumerate(transcript) if said == sent), default=len(transcript))
    for role, text in reversed(transcript[:cut]):
        entry = f"{'User' if role == 'user' else 'Assistant'}: {text}"
        if total + len(entry) > HANDOFF_CHARS:
            break
        lines.append(entry)
        total += len(entry)
    if not lines:
        return ""
    return ("<previous_conversation>\nThis conversation started with another agent session. Earlier messages:\n\n"
            + "\n\n".join(reversed(lines)) + "\n</previous_conversation>")


def short(tool):
    return tool.removeprefix("mcp__verticals__")


# What the Verticals MCP server's `create` answers (verticals/mcp/tools.py `_handle_create`): "Created 'Plan the review'
# [AB12CD34]", then " + 3 descendant(s)" for a plan with steps and " (replayed)" for a retry. tests/mcp pins the words. An
# agent that hands on the result's structured content instead gives {"goal": {"id": "AB12CD34", ...}, ...}.
MADE_GOAL = re.compile(r"^Created .* \[([A-Za-z0-9_-]+)\](?: \+ \d+ descendant\(s\))?(?: \(replayed\))?$", re.S)
MADE_GOAL_JSON = re.compile(r'^\{\s*"goal"\s*:\s*\{\s*"id"\s*:\s*"([A-Za-z0-9_-]+)"')


def made_goal(summary):
    """The id of the goal a `create` result names, or None."""
    text = str(summary or "").strip()
    match = MADE_GOAL.match(text) or MADE_GOAL_JSON.match(text)
    return match.group(1) if match else None


def result_text(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(c.get("text", "") for c in content if isinstance(c, dict))
    return ""


def clock(ctx):
    """The time now in the owner's zone, to the minute: the morning report ends each source's window at the time it began. The
    app says it (`now`, from the owner's own clock); without it the zone it names, else this Mac's clock."""
    said = str(ctx.get("now") or "")
    if re.fullmatch(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}", said):
        return said
    try:
        zone = ZoneInfo(str(ctx.get("tz"))[:60]) if ctx.get("tz") else None
    except Exception:  # noqa: BLE001 — a name this Mac does not know is the Mac's own clock
        zone = None
    return (datetime.now(zone) if zone else datetime.now().astimezone()).strftime("%Y-%m-%d %H:%M")


def format_context(ctx):
    ctx = ctx if isinstance(ctx, dict) else {}
    lines = [f"Today: {str(ctx.get('today', time.strftime('%Y-%m-%d')))[:40]}"
             + (f" ({str(ctx.get('tz'))[:60]})" if ctx.get("tz") else ""), f"Now: {clock(ctx)}"]
    for key, label, limit in (("url", "Screen", 500), ("title", "Screen title", 300), ("heading", "Open item", 300),
                              ("selection", "Selected text", 2000)):
        if ctx.get(key):
            lines.append(f"{label}: {str(ctx[key])[:limit]}")
    goal = ctx.get("goal")
    if isinstance(goal, dict) and isinstance(goal.get("id"), str) and len(goal["id"]) < 100:
        about = (f"This conversation is about the goal \"{str(goal.get('title', ''))[:300]}\" (id {goal['id']}, link #goal/{goal['id']}). "
                 "It is linked to the goal already: don't call session_link.")
        changes = str(ctx.get("changes") or "")[:4000]
        if changes:
            lines.append(f"{about} You know it from the earlier turns; what changed on it since your last turn:\n{changes}")
        elif ctx.get("continuing"):
            lines.append(f"{about} You know it from the earlier turns; nothing changed on it since.")
        else:
            lines.append(f"{about} Read it with the goal tool before answering.")
        if goal.get("title") == REPLAN_TITLE:
            lines.append(REPLAN_RULES)
    replan = ctx.get("replan")
    if isinstance(replan, dict):
        # "Replan" clicked in any box: every plan that carried over on the board (docs/design/replan-whole-board.md).
        lines.append(replan_plans(replan) + "\n" + REPLAN_ASK_RULES)
    move = ctx.get("move")
    if isinstance(move, dict):
        # Words sent while the owner moves a goal on the board (docs/design-handoff S5.P3.041).
        held = move.get("goal") if isinstance(move.get("goal"), dict) else None
        spans = [str(s)[:120] for s in move.get("spans") or []][:12]
        lines.append(
            f"The owner was moving a goal on the board, in the {str(move.get('view') or 'board')[:40]} view"
            + (f", showing: {'; '.join(spans)}" if spans else "")
            + (f"; the goal waiting to be placed: \"{str(held.get('title') or '')[:300]}\" (id {str(held.get('id'))[:40]})" if held else "")
            + ". Their words are about that move; the move itself was cancelled when they sent them."
        )
    return "\n".join(lines)


# The boxes carried plans sit in, in the board's order, and what each is called on the board.
REPLAN_BOXES = {"day": "Day", "week": "Week", "month": "Month", "quarter": "Quarter", "year": "Year", "decade": "3 years"}
REPLAN_PLANS = 200


def replan_plans(replan):
    """The carried plans the app sent with Replan, by the box each sits in: its title and id, its own scale and planned
    date, and what it belongs to. At most REPLAN_PLANS of them, ids and titles clipped."""
    plans = [p for p in replan.get("plans") or [] if isinstance(p, dict) and isinstance(p.get("id"), str)]
    boxes = {}
    for plan in plans[:REPLAN_PLANS]:
        boxes.setdefault(str(plan.get("column") or "")[:20], []).append(plan)

    def one(plan):
        scale = str(plan.get("vertical") or "")[:20]
        scale = "3-year" if scale == "decade" else scale
        when = str(plan.get("anchor_date") or "")[:20]
        said = [f"id {plan['id'][:40]}", f"{scale} plan" + (f" for {when}" if when else "") if scale else ""]
        if plan.get("parent"):
            said.append(f"under \"{str(plan['parent'])[:200]}\"")
        return f"\"{str(plan.get('title') or '')[:200]}\" ({', '.join(filter(None, said))})"

    order = [box for box in REPLAN_BOXES if box in boxes] + [box for box in boxes if box not in REPLAN_BOXES]
    listed = [f"{REPLAN_BOXES.get(box) or box.capitalize() or 'Other'} box ({len(boxes[box])}): "
              + "; ".join(one(plan) for plan in boxes[box]) for box in order]
    head = (f"The plans that carried over on the board, {len(plans)} in all"
            + (f", the first {REPLAN_PLANS} listed" if len(plans) > REPLAN_PLANS else "") + ", by the box each sits in:")
    return "\n".join([head, *listed])


# Replan over the whole board (docs/design/replan-whole-board.md; the owner, 21 Oct 2026: "refresh the whole due list", the
# whole batch in "like 5 minutes max"): the board read before asking, at most three questions with the guesses first, then
# one document sorted by decision, applied on go.
REPLAN_ASK_RULES = (
    "The owner clicked Replan: sort out every plan that carried over on the board, all columns at once, so they decide the "
    "whole list in about five minutes with as little thinking as possible. 1. Read before you ask. Call board for today. "
    "Look at what the owner did lately: the goals done, added or moved in the last two weeks, and the documents they worked "
    "on; if this conversation reaches their calendar and messages, the next two weeks and the last few days. From that, "
    "guess what matters most now and which streams went quiet. 2. Your first answer: two short lines on what the board "
    "holds now (this week and this month), how many plans carried over and from which streams; then at most three "
    "questions about what matters now, each with two to four short options, your guess first and marked \"(my guess)\". "
    "Ask with the AskUserQuestion tool when you have it, all the questions in one call. Without it, number the questions, "
    "letter the options and end with: \"Say go to take my guesses, or answer like 1b 3a.\" Ask nothing the board or their "
    "recent work already tells you. 3. With the answers, sort every plan into one of: Keep (it's fine: into the current "
    "period of the column it carried into: this week, this month, this quarter), Idk (not now, not dead: to the Inbox, "
    "the date taken away, with a note), Fuck it (dead: deleted), Done (it already happened; say by what evidence). Decide a "
    "whole stream at once where its plans share a fate. Make one document with doc_create, path replan/<today>.md, or "
    "replan/<today>-2.md (then -3 and on) when that path is taken: never overwrite an earlier document. Title it "
    "\"Replan — <d Month YYYY>\": a section per decision with its count in the heading, \"Keep · N\", \"Idk · N\", "
    "\"Fuck it · N\", \"Done · N\", inside it the plans grouped by what they belong to, each linked as [title](#goal/<id>) "
    "with a few words of why. Then answer in one line with the counts and \"Say go, or move a row in the document.\", and "
    "end with the document's link on its own line, as [title](#doc/<id>). 4. On go, apply the document as it stands then: "
    "Keep with schedule (the column's scale, today's date); Idk with schedule (vertical and anchor_date null), then one "
    "update of its id whose body is its notes as they are (read them with goal) and, after them, the line \"Needs "
    "realigning. Moved from <its planned period, such as the week of 5 Oct> on <today, such as 21 Oct>.\"; Fuck it with "
    "delete (cascade true only when the plan's own steps go with it); Done with one update of ids with done true. Then one "
    "line on what changed. Move nothing before go."
)

# The app's sorting task (docs/design-handoff S4.P4.010, .011): how its table is worked. Its words are the agent's own.
# Kept for the tasks made before Replan became a request (round 8); the app makes no new one.
REPLAN_TITLE = "Replan carried-over plans"
REPLAN_RULES = (
    "This is the app's task for plans that carried over. Its notes link its document, and the document holds a markdown "
    "table: Goal | Summary | Next step | Your comment, one row per plan, linked. Read the document with doc_get and write "
    "it with doc_save. Fill Summary from each plan's own notes, and under its planned time in "
    "Next step put where it should go (Move to this week, Move to next week, Move to the Inbox, Move to next month). "
    "When the owner writes in Your comment, save those words verbatim as a comment on that plan, confirm with them, "
    "apply it with schedule, reparent or update, clear the cell and leave the receipt in Next step, such as "
    "\"Moved to next week, as you wrote.\" Move nothing until the owner says go. Skip a plan whose link no longer "
    "opens a goal. Edit only the cells you change. When every row is done, mark this task done."
)
