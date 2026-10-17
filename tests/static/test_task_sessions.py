"""Task sessions at the desktop gateway (docs/design/task-sessions.md): where a Claude or Codex session lives on this Mac, when
it last moved, and how it opens where it lives. Sample session files in a temporary home: nothing here reads or writes the
owner's own `~/.claude` or `~/.codex`, and no session's contents are ever read (the sample files are made unreadable)."""

from __future__ import annotations

import os
import re
import shlex
import time

from tests.static.sample_sessions import (
    CLAUDE_SESSION, CODEX_THREAD, FOLDER, OTHER_CLAUDE, agent_sessions as _agent_sessions, claude_file, codex_file, homes,
)


def test_a_claude_session_is_found_by_its_id_whichever_folder_it_lives_in(scratch_dir) -> None:
    sessions = _agent_sessions()
    with homes(scratch_dir):
        elsewhere = claude_file(scratch_dir, "/Users/sample/other", CLAUDE_SESSION)
        claude_file(scratch_dir, FOLDER, OTHER_CLAUDE)
        assert sessions.session_file("claude", CLAUDE_SESSION) == elsewhere
        assert sessions.session_file("claude", "9d3c1b2a-0000-4000-8000-000000000000") is None
        assert sessions.session_file("codex", CLAUDE_SESSION) is None


def test_a_codex_thread_is_found_by_its_id_under_the_dated_folders(scratch_dir) -> None:
    sessions = _agent_sessions()
    with homes(scratch_dir):
        rollout = codex_file(scratch_dir, CODEX_THREAD)
        codex_file(scratch_dir, "0198f2c4-7b1e-7a35-b3d2-000000000000", day="2026/10/09")
        assert sessions.session_file("codex", CODEX_THREAD) == rollout


def test_a_session_file_is_looked_for_by_a_real_id_only(scratch_dir) -> None:
    """An id from outside (the link tool's) is part of a path and of a command: only a UUID gets that far."""
    sessions = _agent_sessions()
    with homes(scratch_dir):
        for bad in ("../../etc/passwd", "*", "", None, 7, f"{CLAUDE_SESSION}/../x", "5f0c6a52", f"{CLAUDE_SESSION}; rm -rf ~"):
            assert not sessions.is_session_id(bad), bad
            assert sessions.session_file("claude", bad) is None and sessions.session_file("codex", bad) is None
        assert sessions.is_session_id(CLAUDE_SESSION) and sessions.is_session_id(CODEX_THREAD)


def test_when_a_session_moved_is_its_files_size_and_time_and_the_file_is_never_read(scratch_dir) -> None:
    sessions = _agent_sessions()
    long_ago = time.time() - 3 * 86400
    with homes(scratch_dir):
        path = claude_file(scratch_dir, FOLDER, CLAUDE_SESSION, size=2100, at=long_ago)
        assert not os.access(path, os.R_OK) or os.geteuid() == 0, "the sample file is unreadable, so a read would fail"
        size, moved = sessions.moved("claude", CLAUDE_SESSION)
        assert size == path.stat().st_size and abs(moved - long_ago) < 1
        # It follows the file: a session that went on is bigger and newer.
        path.chmod(0o600)
        with open(path, "ab") as grown:
            grown.write(b"more\n" * 400)
        path.chmod(0)
        bigger, newer = sessions.moved("claude", CLAUDE_SESSION)
        assert bigger > size and newer > moved
        assert sessions.moved("codex", CODEX_THREAD) is None  # no file: nothing to say


def test_a_known_file_is_not_looked_for_again_until_it_goes(scratch_dir) -> None:
    """`/cd` moves a Claude session to another folder's storage: the path the gateway kept stops answering and is found again."""
    sessions = _agent_sessions()
    with homes(scratch_dir):
        first = claude_file(scratch_dir, FOLDER, CLAUDE_SESSION)
        assert sessions.session_file("claude", CLAUDE_SESSION) == first
        moved_to = claude_file(scratch_dir, "/Users/sample/elsewhere", CLAUDE_SESSION)
        first.chmod(0o600)
        first.unlink()
        assert sessions.session_file("claude", CLAUDE_SESSION, known=first) == moved_to
        assert sessions.session_file("claude", CLAUDE_SESSION, known=moved_to) == moved_to


def test_a_claude_agent_is_the_only_transcript_of_its_folder_written_in_the_last_minute(scratch_dir) -> None:
    """Claude Code does not tell a session its own id, so the link tool is given the folder it works in; the session is the
    one written to just now in it, and only when there is one."""
    sessions = _agent_sessions()
    now = time.time()
    with homes(scratch_dir):
        claude_file(scratch_dir, FOLDER, OTHER_CLAUDE, at=now - 3600)
        assert sessions.active_claude_sessions(FOLDER, now) == []            # nothing written to just now
        claude_file(scratch_dir, FOLDER, CLAUDE_SESSION, at=now - 5)
        assert sessions.active_claude_sessions(FOLDER, now) == [CLAUDE_SESSION]
        claude_file(scratch_dir, "/Users/sample/Sample Project", "7a1f0c3e-0000-4000-8000-00000000000a", at=now - 2)
        assert sessions.active_claude_sessions(FOLDER, now) == [CLAUDE_SESSION]  # another folder's session is not this folder's
        claude_file(scratch_dir, FOLDER, "7a1f0c3e-0000-4000-8000-00000000000b", at=now - 1)
        assert sessions.active_claude_sessions(FOLDER, now) == ["7a1f0c3e-0000-4000-8000-00000000000b", CLAUDE_SESSION]
        assert sessions.active_claude_sessions("relative/folder", now) == []  # a folder is an absolute path


def test_a_long_folder_name_is_found_by_its_first_two_hundred_letters(scratch_dir) -> None:
    """Claude cuts a project folder's name at 200 characters and adds a hash of the whole path to it (the docs don't say how
    the hash is made), so the folder is found by its start."""
    sessions = _agent_sessions()
    now = time.time()
    folder = "/Users/sample/" + "very-long-project-name/" * 12
    name = re.sub(r"[^a-zA-Z0-9]", "-", folder)
    assert len(name) > 200
    with homes(scratch_dir):
        path = scratch_dir / "claude" / "projects" / f"{name[:200]}-9f3a2c1b" / f"{CLAUDE_SESSION}.jsonl"
        path.parent.mkdir(parents=True)
        path.write_bytes(b"sample\n")
        os.utime(path, (now - 3, now - 3))
        assert sessions.active_claude_sessions(folder, now) == [CLAUDE_SESSION]


def test_a_session_opens_where_it_lives() -> None:
    """A Codex thread opens by its link (developers.openai.com/codex/app/commands, "Deep links"); a Claude session opens in
    Terminal with `claude --resume <id>` from its folder (code.claude.com/docs/en/sessions, "Resume by session ID or name")."""
    sessions = _agent_sessions()
    assert sessions.open_action("codex", CODEX_THREAD, None) == {"kind": "url", "url": f"codex://threads/{CODEX_THREAD}"}
    assert sessions.open_action("claude", CLAUDE_SESSION, FOLDER) == {
        "kind": "terminal", "cwd": FOLDER, "command": ["claude", "--resume", CLAUDE_SESSION]}
    assert sessions.open_action("claude", CLAUDE_SESSION, None)["cwd"] is None
    for provider, bad in (("codex", "../x"), ("claude", "x; reboot"), ("claude", "")):
        try:
            sessions.open_action(provider, bad, None)
        except ValueError:
            continue
        raise AssertionError(f"{provider} {bad!r} was opened")


def test_the_terminal_script_changes_to_the_sessions_folder_and_quotes_what_it_was_given() -> None:
    sessions = _agent_sessions()
    action = sessions.open_action("claude", CLAUDE_SESSION, FOLDER)
    script = sessions.terminal_script(action, "/Users/sample/.local/bin/claude")
    lines = script.splitlines()
    assert lines[0] == "#!/bin/zsh"
    assert f"cd {shlex.quote(FOLDER)} 2>/dev/null || cd ~" in lines
    assert lines[-1] == f"exec /Users/sample/.local/bin/claude --resume {CLAUDE_SESSION}"
    # No folder: Claude finds the session by its id from wherever it runs (the docs' "from any directory").
    plain = sessions.terminal_script(sessions.open_action("claude", CLAUDE_SESSION, None), None)
    assert "cd " not in plain and plain.splitlines()[-1] == f"exec claude --resume {CLAUDE_SESSION}"
    # A folder with a quote or a dollar in it stays one word.
    odd = sessions.terminal_script(sessions.open_action("claude", CLAUDE_SESSION, "/Users/sample/it's $HOME"), None)
    assert shlex.split(next(line for line in odd.splitlines() if line.startswith("cd ")).split(" 2>/dev/null")[0])[1] == "/Users/sample/it's $HOME"
    assert "CLAUDE_CONFIG_DIR" not in script


def test_the_terminal_script_keeps_the_apps_claude_sign_in() -> None:
    """Terminal starts from the owner's shell, so the app's `CLAUDE_CONFIG_DIR` (agents.env) is set again before `claude` runs."""
    sessions = _agent_sessions()
    action = sessions.open_action("claude", CLAUDE_SESSION, FOLDER)
    lines = sessions.terminal_script(action, None, "/Users/sample/my claude").splitlines()
    assert lines[1] == "export CLAUDE_CONFIG_DIR='/Users/sample/my claude'"
    assert lines[-1] == f"exec claude --resume {CLAUDE_SESSION}"


def test_a_task_has_a_link_the_app_opens() -> None:
    """`verticals://goal/<id>`: what a session starts with and what the link tool is told to look for; the app's URL handler
    turns it into the board's own `#goal/<id>` address (desktop/macos/AppLinks.swift)."""
    sessions = _agent_sessions()
    assert sessions.task_link("AB12cd34") == "verticals://goal/AB12cd34"
    for bad in ("a b/../c", "", "x" * 101, "a#b", "a?b"):
        try:
            sessions.task_link(bad)
        except ValueError:
            continue
        raise AssertionError(f"{bad!r} was made a task link")
