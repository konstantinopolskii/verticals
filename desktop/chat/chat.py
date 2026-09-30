"""Verticals desktop chat backend: runs the local agent CLIs (Claude Code, Codex) with the Verticals MCP server.

Ported from Enjoy's agent clients: Claude over `claude --print` stream-json with permission
prompts answered here, Codex over `codex app-server` JSON-RPC. Both are normalised into one
event stream for the chat UI. Agent settings (model, effort, speed, permissions) are chosen
per message, like Enjoy's composer; switching agents starts a fresh agent session and hands
it the conversation so far.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import threading
import time
import tomllib
import uuid
from pathlib import Path

HERE = Path(__file__).resolve().parent
SKILL = HERE.parents[1] / ".agents" / "skills" / "verticals-operator"


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
MAX_EVENTS = 5000
HANDOFF_CHARS = 12000
# Parent-session variables must not leak into the agents (credentials excepted).
ENV_KEEP = {"CLAUDE_CODE_OAUTH_TOKEN", "CLAUDE_CONFIG_DIR", "CLAUDE_CODE_USE_BEDROCK",
            "CLAUDE_CODE_USE_VERTEX", "CLAUDE_CODE_USE_FOUNDRY"}
READ_TOOLS = ["board", "goal", "outline", "search", "evidence_due", "tags", "size_report",
              "doc_get", "doc_tree", "doc_history", "doc_revision", "comments"]

# Agent descriptors: labels and details are Enjoy's own (see its provider registry).
AGENTS = {
    "claude": {
        "label": "Claude Code", "exe": "claude", "image": "claude.svg", "order": 10,
        "efforts": [["low", "Low"], ["medium", "Medium"], ["high", "High"], ["xhigh", "xHigh"],
                    ["max", "Max"], ["ultracode", "Ultracode"]],
        "defaultEffort": "medium",
        "fast": "Faster responses on supported models. Uses paid usage credits or API billing.",
        "permissions": [
            ["manual", "Manual", "Ask before file edits and commands that are not already allowed."],
            ["acceptEdits", "Accept edits", "Approve project file edits and common file commands. Ask before other actions."],
            ["plan", "Plan", "Explore and propose a plan before changing your source files."],
            ["auto", "Auto", "Claude reviews actions automatically. Availability depends on your model, account, and organization."],
            ["dontAsk", "Don't ask", "Run only pre-approved tools. Deny anything that would need permission."],
            ["bypassPermissions", "Bypass permissions", "Skip permission checks. Use only in an isolated environment you trust."],
        ],
        "defaultPermission": "auto",
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
    """`claude --print` stream-json; mirrors Enjoy's Claude client."""

    provider = "claude"

    def __init__(self, chat, s, settings, resume_id):
        self.chat, self.s, self.settings = chat, s, settings
        self.session_id = resume_id or str(uuid.uuid4())
        self.streamed = False
        self.pending = {}
        effort = settings.get("effort")
        claude_settings = {"fastMode": bool(settings.get("fast")), "ultracode": effort == "ultracode"}
        args = [which("claude"), "--print", "--verbose", "--include-partial-messages",
                "--input-format", "stream-json", "--output-format", "stream-json",
                "--permission-mode", settings.get("permission") or "auto",
                "--permission-prompts", "host", "--permission-prompt-tool", "stdio",
                "--strict-mcp-config", "--mcp-config", str(chat.claude_mcp),
                "--settings", json.dumps(claude_settings),
                "--tools", "", "--allowedTools", ",".join(f"mcp__verticals__{t}" for t in READ_TOOLS),
                "--append-system-prompt", PROMPT,
                "--resume" if resume_id else "--session-id", self.session_id]
        if settings.get("model") and settings["model"] != "default":
            args += ["--model", settings["model"]]
        if effort and effort != "default":
            args += ["--effort", "xhigh" if effort == "ultracode" else effort]
        self.proc = JsonProcess(args, chat.workdir, child_env(), self.handle, self.exited)
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
        tool_input = self.pending.pop(rid, None)
        response = {"behavior": "allow", "updatedInput": tool_input} if option == "accept" else \
            {"behavior": "deny", "message": "The user declined this action."}
        self.proc.send({"type": "control_response",
                        "response": {"subtype": "success", "request_id": rid, "response": response}})

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
                    s.emit({"t": "tool", "id": block.get("id"), "name": name, "title": name,
                            "input": block.get("input", {})})
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
            if not tool.startswith("mcp__verticals__"):
                self.pending[rid] = tool_input
                return self.decide(rid, "decline")
            self.pending[rid] = tool_input
            s.ask(self, rid, f"Allow Claude to use {short(tool)}?",
                  "\n\n".join(filter(None, [req.get("decision_reason"), json.dumps(tool_input, indent=2, ensure_ascii=False)])),
                  [("Allow once", "accept"), ("Decline", "decline")])
        elif kind == "control_cancel_request":
            s.resolve(msg.get("request_id"), "Cancelled")
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


def codex_args(chat):
    """Keep the user's CLI sign-in, but expose only this desktop's MCP server.

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
    overrides = []
    for group in ("mcp_servers", "plugins"):
        for name in config.get(group, {}):
            overrides += ["-c", f"{group}.{name}.enabled=false"]
    for event, handlers in config.get("hooks", {}).items():
        if isinstance(handlers, list):
            overrides += ["-c", f"hooks.{event}=[]"]
    overrides += ["-c", "notify=[]", "-c", "features.apps=false", "-c", "features.shell_tool=false",
                  "-c", "features.multi_agent=false", "-c", 'web_search="disabled"',
                  "-c", f"mcp_servers.verticals_desktop.command={q(sys.executable)}",
                  "-c", f"mcp_servers.verticals_desktop.args={q([str(HERE / 'mcp_proxy.py')])}",
                  "-c", 'mcp_servers.verticals_desktop.env_vars=["VERTICALS_MCP_URL","VERTICALS_MCP_TOKEN"]',
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
    if result.returncode or enabled != {"verticals_desktop"}:
        raise ChatError("Could not isolate Codex to the local Verticals desktop MCP server")
    return [which("codex"), "app-server", *overrides]


class CodexAgent:
    """`codex app-server`; mirrors Enjoy's Codex client."""

    provider = "codex"

    def __init__(self, chat, s, settings, resume_id):
        self.chat, self.s, self.settings = chat, s, settings
        self.thread_id, self.turn_id = None, None
        self.approvals = {}      # request id -> [(label, response)]
        self.streamed = set()    # agentMessage item ids that got deltas
        env = child_env({"VERTICALS_MCP_URL": chat.mcp_url, "VERTICALS_MCP_TOKEN": chat.token})
        self.proc = RpcProcess(codex_args(chat), chat.workdir, env, self.notify, self.request, self.exited)
        self.proc.request("initialize", {"clientInfo": {"name": "verticals-desktop", "title": "Verticals", "version": "0.1.0"},
                                         "capabilities": {"experimentalApi": True}})
        self.proc.notify("initialized", {})
        params = {**codex_policy(settings.get("permission") or "auto-review"), "cwd": str(chat.workdir),
                  "developerInstructions": PROMPT.replace('server "verticals"', 'server "verticals_desktop"'),
                  "config": {"sandbox_workspace_write.network_access": False, "features.multi_agent": False},
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
        params = {**codex_policy(settings.get("permission") or "auto-review", str(self.chat.workdir)),
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
        self.cond = threading.Condition()
        self.running = False
        self.queue = []                  # (text, context, settings) sent after the current turn
        self.asks = {}                   # request key -> agent
        self.settings = {}
        self.started_at = None
        self.reply = ""                  # text of the agent's current reply, for handoffs

    # -- events

    def emit(self, event):
        with self.cond:
            self.seq += 1
            self.events.append((self.seq, event))
            del self.events[:-MAX_EVENTS]
            self.cond.notify_all()
        if event["t"] == "text":
            self.reply += event["text"]
        elif event["t"] == "text_start" and self.reply:
            self.reply += "\n\n"

    def since(self, seq, timeout):
        with self.cond:
            if not any(s > seq for s, _ in self.events):
                self.cond.wait(timeout)
            return [(s, e) for s, e in self.events if s > seq]

    def ask(self, agent, key, title, body, options):
        self.asks[key] = agent
        self.emit({"t": "permission", "requestId": key, "title": title, "body": body,
                   "options": [{"label": label, "value": value} for label, value in options]})

    def resolve(self, key, label):
        if key is not None and self.asks.pop(str(key), None):
            self.emit({"t": "permission_done", "requestId": str(key), "label": label})

    # -- lifecycle

    def turn_done(self, error, detail):
        if not self.running:
            return
        self.running = False
        ms = int((time.time() - (self.started_at or time.time())) * 1000)
        self.chat.record(self.id, "assistant", self.reply)
        at = time.time()
        self.chat.update(self.id, lastTurnAt=at)
        self.emit({"t": "done", "error": bool(error), "detail": detail or "", "ms": ms, "at": at})
        for key in list(self.asks):
            self.resolve(key, "Expired")
        if self.queue:
            text, context, settings = self.queue.pop(0)
            threading.Thread(target=self.chat.start_turn, args=(self, text, context, settings), daemon=True).start()

    def agent_exited(self, agent, code, detail):
        if self.agent is not agent:
            return
        self.agent = None
        if self.running:
            self.running = False
            self.emit({"t": "exit", "code": code, "detail": detail if code else ""})
        self.queue.clear()


class Chat:
    def __init__(self, state_dir: Path, mcp_url: str, token: str):
        self.state_dir, self.mcp_url, self.token = state_dir, mcp_url, token
        self.sessions: dict[str, Session] = {}
        self.lock = threading.Lock()
        self.store_path = state_dir / "chat-sessions.json"
        self.models, self.probes = {}, {}
        self.claude_mcp = state_dir / "chat-mcp.json"
        # Owner-only file: the MCP bearer token must not appear in `ps` output.
        self.claude_mcp.unlink(missing_ok=True)
        fd = os.open(self.claude_mcp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as f:
            json.dump({"mcpServers": {"verticals": {"type": "http", "url": mcp_url,
                                                   "headers": {"Authorization": f"Bearer {token}"}}}}, f)
        # The agents' working directory: empty, writable, outside the app bundle.
        self.workdir = state_dir / "chat-workspace"
        self.workdir.mkdir(exist_ok=True)

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

    def goal_conversations(self, goal_id):
        """A goal's conversations, the latest turn first: Discuss with agent continues the first (docs/design-handoff
        S3.P1)."""
        found = [{"session": id, "provider": entry.get("provider"), "title": (entry.get("goal") or {}).get("title", ""),
                  "lastTurnAt": entry.get("lastTurnAt") or 0}
                 for id, entry in self.load().items()
                 if isinstance(entry, dict) and (entry.get("goal") or {}).get("id") == goal_id]
        return sorted(found, key=lambda c: c["lastTurnAt"], reverse=True)

    def session(self, id) -> Session:
        try:
            uuid.UUID(str(id))
        except ValueError:
            raise ChatError("Invalid conversation")
        with self.lock:
            if id not in self.sessions:
                self.sessions[id] = Session(self, id)
            return self.sessions[id]

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
        if not isinstance(text, str) or not text.strip():
            raise ChatError("Empty message")
        s = self.session(id)
        settings = clean_settings(settings)
        goal = context.get("goal") if isinstance(context, dict) else None
        if isinstance(goal, dict) and isinstance(goal.get("id"), str) and len(goal["id"]) < 100:
            self.update(id, goal={"id": goal["id"], "title": str(goal.get("title", ""))[:300]})
        if not which(settings["provider"]):
            raise ChatError(f"{AGENTS[settings['provider']]['label']} is not installed.")
        s.emit({"t": "user", "text": text, "provider": settings["provider"], "model": settings.get("model"),
                "effort": settings.get("effort")})
        self.record(id, "user", text)
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

    def start_turn(self, s: Session, text, context, settings):
        s.running, s.started_at, s.reply = True, time.time(), ""
        s.settings = settings
        stored = self.load().get(s.id, {})
        provider = settings["provider"]
        handoff = ""
        try:
            agent = s.agent
            changed_provider = agent is not None and agent.provider != provider or \
                (agent is None and stored.get("provider") not in (None, provider))
            if agent and (agent.provider != provider or agent.signature() != AGENT_CLASSES[provider].signature_of(settings)):
                s.agent = None
                agent.close()
                agent = None
            if agent is None:
                resume = None if changed_provider else stored.get("sessionId")
                if changed_provider or (resume is None and stored.get("transcript")):
                    handoff = format_handoff(stored.get("transcript") or [], text)
            s.emit({"t": "turn_start", "provider": provider, "model": settings.get("model"),
                    "effort": settings.get("effort")})
            if agent is None:
                s.emit({"t": "activity", "label": "Starting…"})
                agent = AGENT_CLASSES[provider](self, s, settings, resume)
                s.agent = agent
                self.update(s.id, provider=provider, sessionId=agent.session_id)
            body = f"<app_context>\n{format_context(context)}\n</app_context>\n\n"
            if handoff:
                body += handoff + "\n\n"
            agent.send(body + text)
        except (ChatError, OSError) as e:
            s.running = False
            s.emit({"t": "done", "error": True, "detail": str(e), "ms": 0})

    def decide(self, id, request_id, value):
        s = self.session(id)
        agent = s.asks.pop(str(request_id), None)
        if agent is None:
            raise ChatError("This request is no longer active")
        agent.decide(str(request_id), value)
        s.emit({"t": "permission_done", "requestId": str(request_id), "value": value})

    def stop(self, id):
        s = self.session(id)
        s.queue.clear()
        if s.running and s.agent:
            s.agent.interrupt()

    def reset(self, id):
        s = self.sessions.pop(id, None)
        if s and s.agent:
            s.agent.close()

    def shutdown(self):
        for s in list(self.sessions.values()):
            if s.agent:
                s.agent.close()


ClaudeAgent.signature_of = staticmethod(lambda settings: settings)
CodexAgent.signature_of = staticmethod(lambda settings: {})


def clean_settings(raw):
    raw = raw if isinstance(raw, dict) else {}
    provider = raw.get("provider") if raw.get("provider") in AGENTS else "claude"
    agent = AGENTS[provider]
    efforts = {v for v, _ in agent["efforts"]} | {"default"}
    permissions = {v for v, _, _ in agent["permissions"]}
    model = raw.get("model") if isinstance(raw.get("model"), str) and len(raw["model"]) < 200 else ""
    return {"provider": provider, "model": model,
            "effort": raw.get("effort") if raw.get("effort") in efforts else agent["defaultEffort"],
            "fast": bool(raw.get("fast")),
            "permission": raw.get("permission") if raw.get("permission") in permissions else agent["defaultPermission"]}


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
    """Earlier turns for an agent that did not take part in them (agent switch or lost session)."""
    lines, total = [], 0
    for role, text in reversed(transcript[:-1] if transcript and transcript[-1] == ["user", current[:4000]] else transcript):
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


def result_text(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(c.get("text", "") for c in content if isinstance(c, dict))
    return ""


def format_context(ctx):
    ctx = ctx if isinstance(ctx, dict) else {}
    lines = [f"Today: {str(ctx.get('today', time.strftime('%Y-%m-%d')))[:40]}"
             + (f" ({str(ctx.get('tz'))[:60]})" if ctx.get("tz") else "")]
    for key, label, limit in (("url", "Screen", 500), ("title", "Screen title", 300), ("heading", "Open item", 300),
                              ("selection", "Selected text", 2000)):
        if ctx.get(key):
            lines.append(f"{label}: {str(ctx[key])[:limit]}")
    goal = ctx.get("goal")
    if isinstance(goal, dict) and isinstance(goal.get("id"), str) and len(goal["id"]) < 100:
        about = f"This conversation is about the goal \"{str(goal.get('title', ''))[:300]}\" (id {goal['id']}, link #goal/{goal['id']})."
        changes = str(ctx.get("changes") or "")[:4000]
        if changes:
            lines.append(f"{about} You know it from the earlier turns; what changed on it since your last turn:\n{changes}")
        elif ctx.get("continuing"):
            lines.append(f"{about} You know it from the earlier turns; nothing changed on it since.")
        else:
            lines.append(f"{about} Read it with the goal tool before answering.")
    return "\n".join(lines)
