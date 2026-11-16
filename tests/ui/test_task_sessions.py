"""Every task has its session, in Verticals, Claude or Codex (docs/design/task-sessions.md): Start work, Open in ›, the row that
says a session went on in Claude or Codex, the card's turning line, and the task's link. The agent is `tests/ui/fake_agent/claude`
and `open` is `tests/ui/fake_agent/open`, behind the real desktop gateway; the sessions of Claude and Codex are sample files in the
gateway's own state folder (never the owner's `~/.claude` or `~/.codex`), and what the app learns of them is each file's size and
time. F2, the browser clock pinned to 2026-08-08 09:00 (+03:00): a file's time is set against that clock, so "5 min ago" is exact."""

from __future__ import annotations

import json
import os
import shlex
import urllib.request
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import TypeVar

from playwright.sync_api import Page, expect

from tests.harness.report import gate
from tests.static.sample_sessions import CLAUDE_SESSION, CODEX_THREAD, OTHER_CLAUDE, claude_file, codex_file, grow_file
from tests.ui.conftest import PINNED_CLOCK_ISO, UiSession
from tests.ui.test_agent_conversation import CONVERSATION, _answered, _send, ui_agent  # noqa: F401  (the fixture)

TASK = "SYNDAY01"  # "Draft the outline", a day goal of 8 Aug 2026
NO_SESSION = "SYNCOL03"
LINK = f"verticals://goal/{TASK}"
MENU = '[data-role="goal-context-menu"]'
SUBMENU = '[data-role="session-menu"]'
MARK = f'[data-goal-id="{TASK}"] > .goal-card__row > [data-role="session-mark"]'
START = "Start work on this task."
#: The page's clock, as the seconds a file's time is counted from.
PAGE_NOW = datetime.fromisoformat(PINNED_CLOCK_ISO).timestamp()

T = TypeVar("T")


class Desktop:
    """The gateway's state folder of one test: where the agents keep their files, and what the fake agent and `open` logged."""

    def __init__(self, ui: UiSession, tmp_path: Path) -> None:
        self.ui, self.state = ui, tmp_path / "desktop-state"
        self.claude, self.codex = self.state / "claude-config", self.state / "codex-home"
        self.workspace = self.state / "chat-workspace"
        self.project = tmp_path / "project"
        self.project.mkdir()

    def claude_session(self, session: str = CLAUDE_SESSION, ago: float = 1800, size: int = 2048) -> Path:
        return claude_file(self.state, str(self.project), session, size=size, at=PAGE_NOW - ago, home=self.claude)

    def codex_thread(self, thread: str = CODEX_THREAD, ago: float = 300) -> Path:
        return codex_file(self.state, thread, at=PAGE_NOW - ago, home=self.codex)

    def link(self, provider: str, session: str, goal: str = TASK, title: str = "Draft the outline") -> dict:
        """What the MCP tool does when an agent in a session calls it: the gateway is told which task the session belongs to."""
        request = urllib.request.Request(
            f"{self.ui.base_url}/__chat/link", method="POST", headers={"Content-Type": "application/json"},
            data=json.dumps({"goal": {"id": goal, "title": title}, "provider": provider, "session": session,
                             "cwd": str(self.project)}).encode(),
        )
        with urllib.request.urlopen(request, timeout=10) as reply:
            return json.loads(reply.read())

    def logged(self, name: str, folder: Path | None = None) -> list:
        log = (folder or self.workspace) / name
        return [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []

    def sessions(self) -> dict:
        return self.ui.page.evaluate("() => fetch('/__chat/sessions').then(r => r.json())")["goals"]


def until(page: Page, what: str, check: Callable[[], T], seconds: float = 12) -> T:
    """Wait for something outside the page (a log, the gateway's list), yielding to the browser between looks."""
    for _ in range(int(seconds * 10)):
        found = check()
        if found:
            return found
        page.wait_for_timeout(100)
    raise AssertionError(f"timed out waiting for {what}")


def open_menu(page: Page, goal: str) -> None:
    row = page.locator(f'[data-goal-id="{goal}"] > .goal-card__row').first
    row.hover()
    row.locator('[data-role="goal-actions-trigger"]').click()
    page.wait_for_selector(MENU)


def open_in(page: Page, goal: str = TASK) -> None:
    """The menu with Open in › pointed at: the list of the task's sessions stands beside it."""
    open_menu(page, goal)
    page.locator(f'{MENU} [data-menu-item="open-in"]').hover()
    expect(page.locator(SUBMENU)).to_be_visible()


def open_task(page: Page, goal: str = TASK) -> None:
    page.locator(f'[data-goal-id="{goal}"] > .goal-card__row .goal-card__title').click()
    expect(page.locator(f'[data-goal-id="{goal}"].goal-card--detail-open')).to_be_visible()


def session_rows(page: Page, goal: str = TASK):
    return page.locator(f'[data-goal-id="{goal}"].goal-card--detail-open + .goal-card__children--open [data-link-kind="conversation"]')


def test_start_work_begins_a_session_of_its_own_that_starts_with_the_tasks_link(ui_agent: UiSession, tmp_path: Path) -> None:
    desk, page = Desktop(ui_agent, tmp_path), ui_agent.page
    page.wait_for_selector(f'[data-goal-id="{TASK}"]')
    assert TASK not in desk.sessions()
    open_menu(page, TASK)
    page.locator(f'{MENU} [data-menu-item="start-work"]').click()
    expect(page.locator(MENU)).to_have_count(0)
    # The conversation stays shut; the field says what the agent did.
    expect(page.locator('[data-role="circle-answer"]')).to_contain_text(f"Done: {START}", timeout=15000)
    expect(page.locator(CONVERSATION)).to_have_count(0)

    (sent,) = desk.logged("received.log")
    assert sent.startswith(f"{LINK}\n\n<app_context>") and sent.endswith(START) and 'about the goal "Draft the outline"' in sent
    (first,) = desk.sessions()[TASK]["sessions"]
    assert first["provider"] == "claude" and first["title"] == "Draft the outline" and first["outside"] is False
    stored = json.loads((desk.state / "chat-sessions.json").read_text())[first["session"]]
    assert stored["goal"] == {"id": TASK, "title": "Draft the outline"} and stored["sessionId"] == first["agentSession"]

    # Start work again: another session of its own, with the link at its start; both are the task's.
    open_menu(page, TASK)
    page.locator(f'{MENU} [data-menu-item="start-work"]').click()
    until(page, "the second session's message", lambda: len(desk.logged("received.log")) == 2)
    second = desk.logged("received.log")[1]
    assert second.startswith(f"{LINK}\n\n<app_context>")
    ids = until(page, "two sessions", lambda: len(desk.sessions()[TASK]["sessions"]) == 2 and desk.sessions()[TASK]["sessions"])
    assert len({s["session"] for s in ids}) == 2 and {s["provider"] for s in ids} == {"claude"}
    starts = [args for args in desk.logged("argv.log") if "--append-system-prompt" in args]
    assert len(starts) == 2 and all("--session-id" in args for args in starts)


def _claude_starts(desk: "Desktop") -> list[list[str]]:
    return [args for args in desk.logged("argv.log") if "--append-system-prompt" in args]


def test_start_work_runs_in_the_permission_mode_the_chat_is_set_to(ui_agent: UiSession, tmp_path: Path) -> None:
    desk, page = Desktop(ui_agent, tmp_path), ui_agent.page
    page.wait_for_selector(f'[data-goal-id="{TASK}"]')
    page.evaluate("() => localStorage.setItem('vt-chat:agent-prefs', JSON.stringify({ claude: { permission: 'bypassPermissions' } }))")
    page.reload()
    page.wait_for_selector(f'[data-goal-id="{TASK}"]')
    open_menu(page, TASK)
    page.locator(f'{MENU} [data-menu-item="start-work"]').click()
    (start,) = until(page, "the agent's start", lambda: _claude_starts(desk))
    assert start[start.index("--permission-mode") + 1] == "bypassPermissions"


def test_start_work_goes_to_an_agent_that_is_there_when_the_one_the_task_last_worked_with_is_not(ui_agent: UiSession, tmp_path: Path) -> None:
    """The newest session of the task is Codex's, and there is no Codex on this computer: Claude takes the task, and the task has both."""
    desk, page = Desktop(ui_agent, tmp_path), ui_agent.page
    agents = page.evaluate("() => fetch('/__chat/agents').then(r => r.json())")["agents"]
    if next(agent for agent in agents if agent["id"] == "codex")["available"]:
        gate("Codex is installed on this computer, and Start work would run it")
    desk.codex_thread(ago=60)
    desk.link("codex", CODEX_THREAD)
    page.reload()
    page.wait_for_selector(f'[data-goal-id="{TASK}"]')
    open_menu(page, TASK)
    page.locator(f'{MENU} [data-menu-item="start-work"]').click()
    until(page, "the agent's message", lambda: desk.logged("received.log"))
    found = until(page, "both sessions", lambda: len(desk.sessions()[TASK]["sessions"]) == 2 and desk.sessions()[TASK]["sessions"])
    assert sorted(s["provider"] for s in found) == ["claude", "codex"]


def test_open_in_is_pale_for_a_task_with_no_session(ui_agent: UiSession) -> None:
    page = ui_agent.page
    page.wait_for_selector(f'[data-goal-id="{NO_SESSION}"]')
    open_menu(page, NO_SESSION)
    item = page.locator(f'{MENU} [data-menu-item="open-in"]')
    expect(item).to_be_disabled()
    expect(item).to_have_attribute("title", "Start work or Discuss begins a session")  # what makes it available
    # The pale of every refused item of the menu (Repeat on a goal with steps): the ink at 35%.
    assert item.evaluate("el => getComputedStyle(el).color") == "rgba(0, 0, 0, 0.35)"
    item.hover(force=True)
    page.wait_for_timeout(300)
    expect(page.locator(SUBMENU)).to_have_count(0)
    assert page.locator(f'{MENU} [data-menu-item="discuss"]').evaluate("el => getComputedStyle(el).color") == "rgb(0, 0, 0)"


def test_open_in_lists_the_sessions_newest_first_and_opens_each_where_it_lives(ui_agent: UiSession, tmp_path: Path) -> None:
    desk, page = Desktop(ui_agent, tmp_path), ui_agent.page
    desk.claude_session(ago=2 * 3600)
    desk.codex_thread(ago=5 * 60)
    desk.link("claude", CLAUDE_SESSION)
    desk.link("codex", CODEX_THREAD)
    page.reload()
    page.wait_for_selector(f'[data-goal-id="{TASK}"]')
    open_in(page)
    items = page.locator(f'{SUBMENU} [data-role="session-item"]')
    expect(items).to_have_count(2)
    assert [t.strip() for t in items.all_inner_texts()] == ["Codex · 5 min ago", "Claude · 2 hours ago"]
    assert [items.nth(i).get_attribute("data-provider") for i in range(2)] == ["codex", "claude"]
    for i in range(2):  # each with its agent's own mark
        assert items.nth(i).locator("img.session-menu__mark").get_attribute("src")
    marks = {items.nth(i).get_attribute("data-provider"): items.nth(i).locator("img").get_attribute("src") for i in range(2)}
    assert marks["codex"] != marks["claude"]

    # A Codex thread opens in the Codex app by its link.
    items.nth(0).click()
    expect(page.locator(MENU)).to_have_count(0)
    until(page, "Codex's link opened", lambda: desk.logged("open.log"))
    assert desk.logged("open.log") == [{"args": [f"codex://threads/{CODEX_THREAD}"], "script": None}]

    # A Claude session opens in the Claude app by the app's link: the app shows the session it holds, or takes it in.
    open_in(page)
    page.locator(f'{SUBMENU} [data-session="{CLAUDE_SESSION}"]').click()
    opened = until(page, "Claude's link opened", lambda: len(desk.logged("open.log")) == 2 and desk.logged("open.log")[1])
    assert opened == {"args": [f"claude://resume?session={CLAUDE_SESSION}"], "script": None}
    script_path = desk.state / "open" / f"claude-{CLAUDE_SESSION}.command"
    assert not script_path.exists()

    # On a Mac with no app for the link, it opens in Terminal with `claude --resume`, from the folder it lives in.
    (desk.workspace / "no-claude-app").touch()
    open_in(page)
    page.locator(f'{SUBMENU} [data-session="{CLAUDE_SESSION}"]').click()
    tried, opened = until(page, "Terminal's script", lambda: len(desk.logged("open.log")) == 4 and desk.logged("open.log")[2:])
    assert tried == {"args": [f"claude://resume?session={CLAUDE_SESSION}"], "script": None}
    assert opened["args"] == ["-a", "Terminal", str(script_path)] and script_path.stat().st_mode & 0o777 == 0o700
    lines = opened["script"].splitlines()
    assert lines[0] == "#!/bin/zsh" and f"cd {shlex.quote(str(desk.project))} 2>/dev/null || cd ~" in lines
    assert lines[-1].endswith(f"/fake_agent/claude --resume {CLAUDE_SESSION}")
    expect(page.locator(".toast-stack .toast__text")).to_have_count(0)  # the open went through: nothing to say


def test_a_long_list_of_sessions_scrolls_inside_the_window_and_its_rows_keep_their_height(ui_agent: UiSession, tmp_path: Path) -> None:
    desk, page = Desktop(ui_agent, tmp_path), ui_agent.page
    threads = [f"0198f2c4-7b1e-7a35-b3d2-{n:012d}" for n in range(1, 41)]
    for n, thread in enumerate(threads):
        desk.codex_thread(thread, ago=60 * (n + 1))
        desk.link("codex", thread)
    page.reload()
    page.wait_for_selector(f'[data-goal-id="{TASK}"]')
    open_in(page)
    items = page.locator(f'{SUBMENU} [data-role="session-item"]')
    expect(items).to_have_count(40)
    assert items.nth(0).get_attribute("data-session") == threads[0]  # the newest first
    box = page.locator(SUBMENU).bounding_box()
    assert box and box["y"] >= 0 and box["y"] + box["height"] <= page.viewport_size["height"]
    assert page.locator(SUBMENU).evaluate("el => el.scrollHeight > el.clientHeight")
    assert {round(items.nth(i).bounding_box()["height"]) for i in (0, 20, 39)} == {32}


def test_a_session_row_says_when_it_moved_and_opens_where_it_lives(ui_agent: UiSession, tmp_path: Path) -> None:
    desk, page = Desktop(ui_agent, tmp_path), ui_agent.page
    desk.codex_thread(ago=2 * 86400)
    desk.link("codex", CODEX_THREAD)
    page.reload()
    page.wait_for_selector(f'[data-goal-id="{TASK}"]')
    open_task(page)
    # The open card's facts line offers Discuss; its menu's Agent section holds the other two.
    page.click(f'[data-goal-id="{TASK}"].goal-card--detail-open [data-role="goal-actions-trigger"]')
    page.wait_for_selector(MENU)
    agent = page.locator(f'{MENU} [data-menu-section="agent"] [role="menuitem"]')
    assert [t.strip() for t in agent.all_inner_texts()] == ["Start work", "Open in"]
    page.keyboard.press("Escape")
    expect(page.locator(MENU)).to_have_count(0)
    expect(session_rows(page)).to_have_count(1, timeout=10000)  # the page's first look at the gateway's list
    row = session_rows(page).first
    expect(row.locator('[data-role="session-when"]')).to_have_text("2 days ago")
    expect(row.locator(".goal-links__title")).to_have_text("Draft the outline")
    open_arrow = row.locator("xpath=following-sibling::button[@data-role='open-session']")
    expect(open_arrow).to_have_attribute("aria-label", "Open in Codex")
    open_arrow.click()
    until(page, "the thread opened", lambda: desk.logged("open.log"))
    assert desk.logged("open.log") == [{"args": [f"codex://threads/{CODEX_THREAD}"], "script": None}]


def test_a_session_that_goes_on_outside_marks_its_row_and_the_card_and_discuss_resumes_it(ui_agent: UiSession, tmp_path: Path) -> None:
    desk, page = Desktop(ui_agent, tmp_path), ui_agent.page
    path = desk.claude_session(ago=1800)
    desk.link("claude", CLAUDE_SESSION)
    page.reload()
    page.wait_for_selector(f'[data-goal-id="{TASK}"]')
    open_task(page)
    expect(session_rows(page)).to_have_count(1, timeout=10000)  # the page's first look at the gateway's list
    row = session_rows(page).first
    expect(row.locator('[data-role="session-when"]')).to_have_text("30 min ago")
    expect(page.locator(MARK)).to_have_count(0)

    # The owner goes on in Claude Code: the file is bigger, three minutes before the page's clock. Nothing is told to Verticals.
    grow_file(path, 4096, at=PAGE_NOW - 180)
    mark = page.locator(MARK)
    expect(mark).to_have_attribute("data-state", "outside", timeout=12000)
    expect(mark).to_have_attribute("data-provider", "claude")
    expect(mark).to_have_attribute("aria-label", "Continued in Claude · 3 min ago")
    expect(row.locator('[data-role="session-when"]')).to_have_text("Continued in Claude · 3 min ago")
    assert desk.sessions()[TASK]["outside"] == {"provider": "claude", "at": PAGE_NOW - 180}

    # Another session of the task, older, with a few bytes more: an idle agent may still write a line, and that is not "went on".
    other = desk.claude_session(OTHER_CLAUDE, ago=900, size=1400)
    desk.link("claude", OTHER_CLAUDE)
    grow_file(other, 300, at=PAGE_NOW - 400)
    page.wait_for_timeout(1500)
    assert [s["outside"] for s in desk.sessions()[TASK]["sessions"] if s["agentSession"] == OTHER_CLAUDE] == [False]

    # Discuss (the open card's facts line has it) goes on with the session that moved last, the one in Claude, resumed in its
    # own folder by the same agent.
    page.locator(f'[data-goal-id="{TASK}"].goal-card--detail-open [data-cap="discuss"]').click()
    page.wait_for_selector(CONVERSATION)
    _send(page, "Where were we?")
    _answered(page, "Done: Where were we?")
    (start,) = [args for args in desk.logged("argv.log", desk.project) if "--append-system-prompt" in args]
    assert start[start.index("--resume") + 1] == CLAUDE_SESSION and "--session-id" not in start
    assert start[start.index("--system-prompt-snapshot") + 1] == "off"
    (sent,) = desk.logged("received.log", desk.project)
    assert not sent.startswith("verticals://") and sent.endswith("Where were we?")
    # Verticals drives it again: it is no longer "continued outside".
    expect(page.locator(MARK)).to_have_count(0, timeout=12000)
    assert desk.sessions()[TASK]["outside"] is None


def test_the_card_shows_the_turning_line_while_a_session_works_and_the_agents_mark_after(ui_agent: UiSession, tmp_path: Path) -> None:
    desk, page = Desktop(ui_agent, tmp_path), ui_agent.page
    path = desk.claude_session(ago=1800)
    desk.link("claude", CLAUDE_SESSION)
    page.reload()
    page.wait_for_selector(f'[data-goal-id="{TASK}"]')
    # The file is being written to now (its time is the computer's, not the page's pinned clock).
    grow_file(path, 4096)
    mark = page.locator(MARK)
    expect(mark).to_have_attribute("data-state", "working", timeout=12000)
    expect(mark).to_have_attribute("aria-label", "Claude is working on this")
    expect(mark.locator(".circle-field__pivot.is-turning")).to_have_count(1)
    disc = mark.locator(".session-mark__disc")
    assert disc.evaluate("el => getComputedStyle(el).backgroundColor") == "rgb(0, 0, 0)"
    assert mark.locator(".circle-field__line").evaluate("el => getComputedStyle(el).backgroundColor") == "rgb(255, 255, 255)"
    # It rests: the line stops, and the agent's own mark says where it went on.
    os.utime(path, (PAGE_NOW - 60, PAGE_NOW - 60))
    expect(mark).to_have_attribute("data-state", "outside", timeout=12000)
    expect(mark.locator(".circle-field__pivot")).to_have_count(0)
    expect(mark.locator("img.session-mark__agent")).to_have_count(1)
    assert desk.sessions()[TASK]["working"] is False


def test_a_conversation_about_the_task_turns_the_line_on_its_card_while_the_agent_answers(ui_agent: UiSession) -> None:
    page = ui_agent.page
    page.wait_for_selector(f'[data-goal-id="{TASK}"]')
    open_menu(page, TASK)
    page.locator(f'{MENU} [data-menu-item="discuss"]').click()
    page.wait_for_selector(CONVERSATION)
    _send(page, "Think about it [slow]")
    on_card = page.locator(f'.vt-window[data-window="goal"] [data-goal-id="{TASK}"] [data-role="session-mark"]')
    expect(on_card.first).to_have_attribute("data-state", "working", timeout=5000)
    _answered(page, "Done: Think about it")
    expect(on_card).to_have_count(0, timeout=10000)


def test_a_tasks_link_opens_the_task(ui_agent: UiSession) -> None:
    """`verticals://goal/<id>` is turned into the board's own address by the app (desktop/macos/AppLinks.swift); this is the page
    it lands on, from a cold start and over a page that is open already."""
    page = ui_agent.page
    page.goto("about:blank")
    page.goto(f"{ui_agent.base_url}/#goal/{TASK}")
    expect(page.locator(f'[data-goal-id="{TASK}"].goal-card--detail-open')).to_be_visible(timeout=10000)
    expect(page.locator(f'[data-goal-id="{TASK}"] .goal-card__title-text').first).to_have_text("Draft the outline")
    page.evaluate(f"() => {{ location.hash = '#goal/{NO_SESSION}' }}")
    expect(page.locator(f'[data-goal-id="{NO_SESSION}"].goal-card--detail-open')).to_be_visible(timeout=10000)
