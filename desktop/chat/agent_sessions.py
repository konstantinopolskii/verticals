"""Where an agent's session lives on this Mac, when it last moved, and how it opens where it lives (docs/design/task-sessions.md).

A session is a file its agent writes: Claude Code's transcript, `projects/<folder>/<id>.jsonl`, and Codex's rollout,
`sessions/<year>/<month>/<day>/rollout-<time>-<id>.jsonl`, each under the agent's own home (`CLAUDE_CONFIG_DIR` and `CODEX_HOME`,
else `~/.claude` and `~/.codex`). Verticals reads a file's size and its modified time and never a byte of what is in it: no
model looks, no token is spent, and nothing said in a session reaches Verticals except through the tool that links it
(verticals/mcp/session.py). Claude says its transcripts are an internal format that changes between versions; a size and a time do
not."""
from __future__ import annotations

import os
import re
import shlex
from pathlib import Path

SESSION_ID = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")
GOAL_ID = re.compile(r"[A-Za-z0-9_-]{1,100}")
# A turn adds at least a prompt and an answer, a kilobyte or more of lines; the few small ones an idle agent may still append
# (a title for the session) are not "went on".
MIN_GROWTH = 1024
# A file written to in the last twenty seconds is a session at work.
WORKING_SECONDS = 20
# The lines an agent writes just after a turn Verticals drove are still that turn's.
DRIVEN_GRACE = 8
# Claude Code never tells a session its own id, so the one written to in the last minute in its folder is it, if it is the only one.
ACTIVE_SECONDS = 60


def is_session_id(value: object) -> bool:
    """An agent's session id is a UUID (Claude's `--session-id` must be one; Codex's thread ids are). Only one gets as far as
    a path, a glob or a command line."""
    return isinstance(value, str) and SESSION_ID.fullmatch(value) is not None


def task_link(goal_id: str) -> str:
    """The address of a task for anything outside the board: a session starts with it, the app opens it, and the link tool is
    told to look for it."""
    if not isinstance(goal_id, str) or not GOAL_ID.fullmatch(goal_id):
        raise ValueError("Not a goal's id")
    return f"verticals://goal/{goal_id}"


def agent_home(provider: str) -> Path:
    if provider == "claude":
        return Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude")
    return Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex")


def session_file(provider: str, session_id: object, known: Path | None = None) -> Path | None:
    """The file of a session, found by its id. A path found before is trusted while it answers: looking again means a walk of
    every project folder, and a session's file does not move unless Claude's `/cd` moves it."""
    if not is_session_id(session_id):
        return None
    if known is not None and known.is_file():
        return known
    home = agent_home(provider)
    found: list[tuple[float, Path]] = []
    if provider == "claude":
        try:
            folders = [Path(entry.path) for entry in os.scandir(home / "projects")]
        except OSError:
            return None
        candidates = (folder / f"{session_id}.jsonl" for folder in folders)
    else:
        candidates = (home / "sessions").rglob(f"rollout-*-{session_id}.jsonl")
    for path in candidates:
        try:
            found.append((path.stat().st_mtime, path))
        except OSError:
            continue
    return max(found, default=(0.0, None))[1]


def file_stat(path: Path) -> tuple[int, float] | None:
    """(size in bytes, modified time in seconds) of a file, or None when it is gone. That is all of a session Verticals knows."""
    try:
        stat = path.stat()
    except OSError:
        return None
    return stat.st_size, stat.st_mtime


def moved(provider: str, session_id: object, known: Path | None = None) -> tuple[int, float] | None:
    """The `file_stat` of a session's file, or None when there is no such file."""
    path = session_file(provider, session_id, known)
    return None if path is None else file_stat(path)


def claude_folder(cwd: str) -> str:
    """Claude's name for a working directory's project folder: every character that is not a letter or a digit becomes a dash."""
    return re.sub(r"[^a-zA-Z0-9]", "-", str(cwd))


def active_claude_sessions(cwd: object, now: float, within: float = ACTIVE_SECONDS) -> list[str]:
    """Ids of the Claude sessions of a folder written to within the last `within` seconds, the newest first. A name over 200
    characters is cut there and a hash of the whole path added (the docs don't say how), so that folder is found by its start."""
    if not isinstance(cwd, str) or not os.path.isabs(cwd):
        return []
    projects = agent_home("claude") / "projects"
    name = claude_folder(cwd)
    try:
        folders = ([projects / name] if len(name) <= 200
                   else [Path(entry.path) for entry in os.scandir(projects) if entry.name.startswith(name[:200])])
    except OSError:
        return []
    recent: list[tuple[float, str]] = []
    for folder in folders:
        try:
            transcripts = list(os.scandir(folder))
        except OSError:
            continue
        for entry in transcripts:
            stem = entry.name.removesuffix(".jsonl")
            if not entry.name.endswith(".jsonl") or not is_session_id(stem):
                continue
            try:
                at = entry.stat().st_mtime
            except OSError:
                continue
            if 0 <= now - at <= within:
                recent.append((at, stem))
    return [stem for _, stem in sorted(recent, reverse=True)]


def claude_app_home() -> Path:
    """Where the Claude app reads Claude Code's sessions: `~/.claude`. The app starts from macOS, not from Verticals, so a
    `CLAUDE_CONFIG_DIR` in agents.env (another account's folder for Verticals' own agents) never reaches it."""
    return Path.home() / ".claude"


def claude_app_sees_sessions() -> bool:
    """Whether Verticals' Claude keeps its sessions where the Claude app reads them: the same folder, whatever links lead to it."""
    return os.path.realpath(agent_home("claude").expanduser()) == os.path.realpath(claude_app_home())


def open_action(provider: str, session_id: object, cwd: str | None, in_claude_app: bool = True) -> dict:
    """How a session opens where it lives: by its app's link, a Codex thread in the Codex app (`codex://threads/<id>`) and a
    Claude session in the Claude app (`claude://resume?session=<id>`). The Claude app shows the session when it already holds
    it, and takes one begun in Terminal or by Verticals' agent into its list, with its whole history; either way one copy of
    Claude carries the conversation. `claude --resume <id>` in Terminal would start a second copy beside the app's, and two
    copies writing one conversation split it.

    A Claude session opens in Terminal, with `claude --resume <id>` from its own folder, when the Claude app does not read the
    folder it is kept in (`in_claude_app`, see claude_app_sees_sessions), and as the `fallback` when no app takes the link."""
    if not is_session_id(session_id):
        raise ValueError("Not a session's id")
    if provider == "codex":
        return {"kind": "url", "url": f"codex://threads/{session_id}", "app": "Codex"}
    terminal = {"kind": "terminal", "cwd": cwd or None, "command": ["claude", "--resume", str(session_id)]}
    if not in_claude_app:
        return terminal
    return {"kind": "url", "url": f"claude://resume?session={session_id}", "app": "Claude", "fallback": terminal}


# What macOS's `open` says when no app takes a link (kLSApplicationNotFoundErr): a Mac without the Claude app.
NO_APP = "-10814"


def terminal_script(action: dict, exe: str | None, config_dir: str | None = None, config_name: str = "CLAUDE_CONFIG_DIR") -> str:
    """The script Terminal runs for a `terminal` action: into the session's folder (home if it has gone), then the command, in
    place of the shell. `exe` is where `claude` was found; the folder and every word are quoted, whatever they hold.
    `config_dir` is the app's `CLAUDE_CONFIG_DIR`: Terminal starts from the owner's shell, not the app, so without it Claude
    would look for the session, and sign in, under another account's folder. The sign-in runs Codex's login the same way, its
    home under `CODEX_HOME` (`config_name`, docs/design/agent-sign-in.md)."""
    command = [exe or action["command"][0], *action["command"][1:]]
    lines = ["#!/bin/zsh"]
    if config_dir:
        lines.append(f"export {config_name}={shlex.quote(config_dir)}")
    if action.get("cwd"):
        lines.append(f"cd {shlex.quote(action['cwd'])} 2>/dev/null || cd ~")
    lines.append("exec " + " ".join(shlex.quote(word) for word in command))
    return "\n".join(lines) + "\n"
