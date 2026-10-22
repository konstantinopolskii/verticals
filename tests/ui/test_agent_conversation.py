"""The circle and the agent (docs/design-handoff scope 2): the conversation over the board, the step bubble, the answer
in the circle, the agent's asks, message scroll, the chips under what the agent made, and the field with no agent. The
agent is `tests/ui/fake_agent/claude` behind the real desktop gateway and chat server; marks in the words steer it
(`[tool:NAME]`, `[slow]`, `[ask]`, `[long]`, `[make:ID|Title]`)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import psycopg
import pytest
from playwright.sync_api import Browser, Page, expect

from verticals.core import docs as core_docs
from verticals.core import goals
from verticals.core import morning as core_morning

from tests.ui.conftest import (
    F2_OWNER, PINNED_CLOCK_ISO, PINNED_DAY, REPO_ROOT, TEST_TOKEN, VIEWPORT, Server, UiSession, _backend, _free_port,
    _make_ui_session, _shutdown, _wait_http_ok,
)
from tests.ui.views import FIELD


@contextmanager
def _agent_gateway(
    backend: Server, tmp_path: Path, env: dict[str, str] | None = None, mcp_url: str | None = None,
) -> Iterator[str]:
    """The desktop gateway over this test's backend, its agent the fake one (`tests/ui/agent_gateway.py`). `env` adds to the
    gateway's environment (a short limit for a second agent that never answers). With `mcp_url` the agent's marked calls reach
    that MCP server."""
    port = _free_port()
    log_path = tmp_path / "gateway.log"
    with open(log_path, "w") as logfile:
        proc = subprocess.Popen(
            [sys.executable, str(REPO_ROOT / "tests" / "ui" / "agent_gateway.py"), str(port), str(backend.port),
             str(tmp_path / "desktop-state"), TEST_TOKEN, *([mcp_url] if mcp_url else [])],
            cwd=REPO_ROOT, stdout=logfile, stderr=subprocess.STDOUT, start_new_session=True, env={**os.environ, **(env or {})},
        )
    base_url = f"http://127.0.0.1:{port}"
    try:
        _wait_http_ok(f"{base_url}/healthz", proc, log_path)
        yield base_url
    finally:
        _shutdown(proc, port)


@pytest.fixture
def ui_agent(
    browser: Browser, f2_dsn: str, tmp_path: Path, request: pytest.FixtureRequest, web_dist: None,
    ui_reduced_motion: str,
) -> Iterator[UiSession]:
    """F2 served by the desktop gateway, with the conversation's server and a fake agent (docs/design-handoff S2). The
    pinned day's morning report is taken already, as if asked for: a scenario about something else gets no extra turn."""
    with psycopg.connect(f2_dsn, autocommit=True) as conn:
        core_morning.take(conn, owner=F2_OWNER, day=date.fromisoformat(PINNED_DAY))
    with _backend(f2_dsn, F2_OWNER, tmp_path) as backend:
        with _agent_gateway(backend, tmp_path) as base_url:
            yield from _make_ui_session(
                browser=browser, backend=backend, static_base_url=base_url, request=request,
                reduced_motion=ui_reduced_motion,
            )


CONVERSATION = '[data-role="agent-conversation"]'
BALLOON = "[data-balloon]"
CIRCLE = ".circle-field"
AGENT_BALLOON = f'{BALLOON}[data-who="agent"]'
ANSWER = '[data-role="circle-answer"]'
GOAL_CHIP = '[data-role="goal-chip"]'
DOC_CHIP = '[data-role="doc-chip"]'


def _send(page: Page, words: str) -> None:
    page.keyboard.press("Control+k")
    page.locator(FIELD).fill(words)
    page.keyboard.press("Enter")


def _answered(page: Page, text: str) -> None:
    expect(page.locator(f'{BALLOON}[data-who="agent"]', has_text=text).last).to_be_visible(timeout=10000)
    expect(page.locator('[data-role="agent-step"]')).to_have_count(0, timeout=10000)


# The pinned clock (conftest.PINNED_CLOCK_ISO, 09:00 at +03:00) as the server's clock reads it.
NOW = datetime(2026, 8, 8, 6, 0, tzinfo=timezone.utc)


def goal_made(dsn: str, title: str, *, vertical: str | None = "day", day: str | None = PINNED_DAY, parent: str | None = None,
              color: str | None = None, made: datetime = NOW - timedelta(seconds=20), changed: datetime | None = None,
              done: bool = False) -> str:
    """A goal of the owner's as the agent would have made it, made and last changed when the test says: the page's clock is
    pinned, so how long ago is the test's to say too."""
    with psycopg.connect(dsn, autocommit=True) as conn:
        goal = goals.create(conn, owner=F2_OWNER, title=title, parent_id=parent, vertical=vertical,
                            anchor_date=date.fromisoformat(day) if day else None, color=color).goal.id
        conn.execute("UPDATE goals SET created_at = %s, updated_at = %s, done_at = %s WHERE owner = %s AND id = %s",
                     (made, changed or made, NOW if done else None, F2_OWNER, goal))
    return goal


def close_the_conversation(page: Page) -> None:
    """A click on the board sends the conversation away; an answer that comes after it waits in the field."""
    page.locator('[data-role="out-of-focus"]').click(position={"x": 60, "y": 60})
    expect(page.locator(CONVERSATION)).to_have_count(0)


def test_sending_rises_into_the_conversation_and_the_agent_answers(ui_agent: UiSession) -> None:
    page = ui_agent.page
    page.wait_for_selector(".goal-card__row")
    _send(page, "Plan the week [tool:schedule] [slow]")

    # S2.P3.002: the words are your balloon, the field is the circle again, the board is out of focus.
    expect(page.locator(f'{BALLOON}[data-who="you"]')).to_have_text("Plan the week [tool:schedule] [slow]")
    expect(page.locator(FIELD)).to_have_value("")
    expect(page.locator(".app-content--out-of-focus")).to_have_count(1)
    # S2.P3.004: the step bubble names the step; the line turns while the agent works.
    expect(page.locator('[data-role="agent-step"]')).to_have_text("Setting the date", timeout=5000)
    expect(page.locator(CIRCLE)).to_have_attribute("data-state", "working")
    expect(page.locator(".circle-field__pivot.is-turning")).to_have_count(1)

    _answered(page, "Done: Plan the week")
    expect(page.locator(".circle-field__pivot.is-turning")).to_have_count(0)
    # S2.P4.036: with the conversation open, the answer is a balloon and the circle stays a circle.
    expect(page.locator(CIRCLE)).to_have_attribute("data-state", "rest")

    # S2.P1.011: a click on the board sends the conversation away; the field asks the agent now (S1.P1.015).
    page.locator('[data-role="out-of-focus"]').click(position={"x": 60, "y": 60})
    expect(page.locator(CONVERSATION)).to_have_count(0)
    expect(page.locator(".app-content--out-of-focus")).to_have_count(0)
    expect(page.locator(FIELD)).to_have_attribute("aria-label", "Ask the agent")


def test_an_answer_lands_in_the_circle_and_a_click_sends_it_up(ui_agent: UiSession) -> None:
    page = ui_agent.page
    page.wait_for_selector(".goal-card__row")
    _send(page, "Tell me more [long] [slow]")
    page.locator('[data-role="out-of-focus"]').click(position={"x": 60, "y": 60})
    expect(page.locator(CONVERSATION)).to_have_count(0)

    # S2.P4.030: the circle grows around the answer; a long one shows three lines at most.
    answer = page.locator('[data-role="circle-answer"]')
    expect(answer).to_contain_text("Here is the first part", timeout=10000)
    box = page.locator(".circle-field__shape").bounding_box()
    assert box is not None and box["width"] <= 464 and box["height"] <= 114

    # S2.P4.031: a click sends it up as the agent's last balloon, and the field has the caret.
    page.locator(".circle-field__shape").click()
    expect(page.locator(CONVERSATION)).to_have_count(1)
    expect(page.locator(f'{BALLOON}[data-who="agent"]').last).to_contain_text("The third part closes it")
    expect(page.locator(FIELD)).to_be_focused()
    expect(page.locator('[data-role="circle-answer"]')).to_have_count(0)


def test_an_answer_that_links_a_document_stands_in_the_field_as_its_chip(ui_agent: UiSession) -> None:
    """docs/design/agent-chips.md: an answer that links a document is the message in the field, a message's 24 px corners,
    its words and under them the document's chip (its first page, its name, when it was edited); a click on the words
    opens the conversation, where the same chip stands under the same words."""
    with psycopg.connect(ui_agent.backend.dsn, autocommit=True) as conn:
        doc = core_docs.create(conn, owner=F2_OWNER, path="reports/syn-note.md", title="SYN report — 8 August 2026").doc.id
    page = ui_agent.page
    page.wait_for_selector(".goal-card__row")
    _send(page, f"[slow] [say] Your report is ready.\n[SYN report — 8 August 2026](#doc/{doc})")
    page.locator('[data-role="out-of-focus"]').click(position={"x": 60, "y": 60})
    answer = page.locator(ANSWER)
    expect(answer).to_contain_text("Your report is ready.", timeout=10000)
    chip = answer.locator(f'{DOC_CHIP}[data-doc-id="{doc}"]')
    expect(chip).to_contain_text("SYN report — 8 August 2026")
    expect(chip.locator(".doc-page")).to_have_count(1)
    expect(answer.locator(".circle-field__answer-words")).to_have_text("Your report is ready.")  # the chip says the rest
    expect(page.locator(".circle-field__surface")).to_have_css("border-radius", "24px")  # once its corners have settled
    page.locator(".circle-field__answer-words").click()
    expect(page.locator(f'{BALLOON}[data-who="agent"] {DOC_CHIP}[data-doc-id="{doc}"]')).to_contain_text("SYN report — 8 August 2026")


def _is_the_chip(chip, square: str, title: str, line: str) -> None:
    """A goal chip: the board's own square, the goal's title, and the grey line of where it is and when."""
    expect(chip.locator(".goal-chip__name")).to_have_text(title)
    expect(chip.locator('[data-role="goal-chip-when"]')).to_have_text(line)
    expect(chip.locator('[data-role="goal-chip-square"]')).to_have_css("background-color", square)


def test_a_goal_the_agent_links_stands_under_its_words_as_a_chip_in_the_field_and_in_the_conversation(ui_agent: UiSession) -> None:
    """docs/design/agent-chips.md: the link in the agent's words becomes a chip under them, with the goal's square in the
    colour the board paints it, its title, and where it is and when ("Today · made just now"). The field's answer and
    the agent's balloon are the same message with the same chip, and the line that only linked the goal is not said twice."""
    dsn = ui_agent.backend.dsn
    value = goal_made(dsn, "SYN value in blue", vertical="life", day="2026-01-01", color="#278dea")
    goal = goal_made(dsn, "Plan the review", parent=value)
    page = ui_agent.page
    page.reload()
    page.wait_for_selector(f'[data-goal-id="{goal}"]')
    board_square = page.locator(f'[data-goal-id="{goal}"] [data-role="checkbox-box"]').first.evaluate("el => getComputedStyle(el).backgroundColor")
    assert board_square != "rgb(229, 229, 229)", board_square  # the board paints this goal in its value's colour
    _send(page, f"[slow] [say] Made the task.\n[Plan the review](#goal/{goal})")
    close_the_conversation(page)
    expect(page.locator(ANSWER)).to_contain_text("Made the task.", timeout=10000)
    expect(page.locator(ANSWER).locator(".circle-field__answer-words")).to_have_text("Made the task.")
    _is_the_chip(page.locator(f'{ANSWER} {GOAL_CHIP}[data-goal-id="{goal}"]'), board_square, "Plan the review", "Today · made just now")
    page.locator(".circle-field__answer-words").click()
    expect(page.locator(f'{BALLOON}[data-who="agent"] .agent-balloon__markdown')).to_have_text("Made the task.")
    _is_the_chip(page.locator(f'{BALLOON}[data-who="agent"] {GOAL_CHIP}[data-goal-id="{goal}"]'), board_square, "Plan the review", "Today · made just now")


@pytest.mark.parametrize("where", ["conversation", "field"])
def test_a_goal_chip_opens_the_goal_as_its_window(ui_agent: UiSession, where: str) -> None:
    """A chip opens what it names: a goal as its window, as the board opens one, from the balloon and from the field."""
    goal = goal_made(ui_agent.backend.dsn, "Plan the review")
    page = ui_agent.page
    page.reload()
    page.wait_for_selector(f'[data-goal-id="{goal}"]')
    _send(page, f"[slow] [say] Made the task.\n[Plan the review](#goal/{goal})")
    if where == "field":
        close_the_conversation(page)
        chip = page.locator(f'{ANSWER} {GOAL_CHIP}')
    else:
        chip = page.locator(f'{BALLOON}[data-who="agent"] {GOAL_CHIP}')
    expect(chip).to_have_count(1, timeout=10000)
    expect(page.locator(".vt-window")).to_have_count(0)
    chip.click()
    window = page.locator('.vt-window[data-window="goal"]')
    expect(window).to_have_count(1)
    expect(window.locator(f'.goal-card[data-goal-id="{goal}"]').first).to_contain_text("Plan the review", timeout=10000)


def test_the_morning_report_is_asked_once_a_day_by_the_server(ui_agent: UiSession) -> None:
    """Inbox and Documents redesign, final page; the agent's fixes, fix 3: past the morning hour (the pinned clock says
    09:00) the app asks the agent for the day's report by itself, once a day, and the server decides which ask is the
    day's: a cleared cache or another browser is told the day is taken. The ask is not your balloon; the answer lands in
    the field."""
    page = ui_agent.page
    page.wait_for_selector(".goal-card__row")
    with psycopg.connect(ui_agent.backend.dsn, autocommit=True) as conn:
        conn.execute("DELETE FROM idempotency WHERE owner = %s AND client_token LIKE 'morning:%%'", (F2_OWNER,))  # the day is open again
    page.reload()
    expect(page.locator('[data-role="circle-answer"]')).to_contain_text("Make my morning report for 2026-08-08", timeout=15000)
    with psycopg.connect(ui_agent.backend.dsn, autocommit=True) as conn:
        taken = [row[0] for row in conn.execute("SELECT client_token FROM idempotency WHERE owner = %s", (F2_OWNER,))]
        assert taken == [f"morning:{PINNED_DAY}"]
        # Fix 2: the ask names the one open task, made in the day before the agent was asked.
        task = _morning_tasks(conn)
        assert [(row[1], str(row[2]), row[3]) for row in task] == [("day", PINNED_DAY, "app")]
    expect(page.locator('[data-role="circle-answer"]')).to_contain_text(f"(id {task[0][0]})")
    page.locator(".circle-field__shape").click()
    expect(page.locator(f'{BALLOON}[data-who="agent"]')).to_have_count(1)
    expect(page.locator(f'{BALLOON}[data-who="you"]')).to_have_count(0)
    page.keyboard.press("Escape")
    # The same browser with nothing in its storage, and another browser altogether: the day is taken, they ask nothing.
    page.evaluate("() => { localStorage.clear(); sessionStorage.clear() }")
    other = ui_agent.context.browser.new_context(viewport=VIEWPORT, reduced_motion="reduce")
    other.add_init_script("try { localStorage.setItem('vt-chat:access-chosen', 'true') } catch {}")
    try:
        second = other.new_page()
        second.clock.set_fixed_time(PINNED_CLOCK_ISO)
        second.goto(ui_agent.base_url)
        page.reload()
        for window in (page, second):
            window.wait_for_selector(".goal-card__row")
        page.wait_for_timeout(1500)
        for window in (page, second):
            expect(window.locator('[data-role="circle-answer"]')).to_have_count(0)
    finally:
        other.close()


def _cli_starts(tmp_path: Path) -> list[list[str]]:
    """The arguments of every agent the gateway started for a conversation (the fake agent logs them), oldest first."""
    log = tmp_path / "desktop-state" / "chat-workspace" / "argv.log"
    starts = [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []
    return [args for args in starts if "--append-system-prompt" in args]


def _flag(args: list[str], name: str) -> str:
    return args[args.index(name) + 1]


def test_the_morning_turn_gets_its_guide_and_honors_full_access(ui_agent: UiSession, tmp_path: Path) -> None:
    """Morning and ordinary turns retain the chosen full access and their respective instructions."""
    page = ui_agent.page
    page.wait_for_selector(".goal-card__row")
    page.evaluate("() => localStorage.setItem('vt-chat:agent-prefs', JSON.stringify({ claude: { permission: 'bypassPermissions' } }))")
    with psycopg.connect(ui_agent.backend.dsn, autocommit=True) as conn:
        conn.execute("DELETE FROM idempotency WHERE owner = %s AND client_token LIKE 'morning:%%'", (F2_OWNER,))
    page.reload()
    expect(page.locator('[data-role="circle-answer"]')).to_contain_text("Make my morning report", timeout=15000)
    (morning,) = _cli_starts(tmp_path)
    assert _flag(morning, "--permission-mode") == "bypassPermissions" and "--add-dir" in morning and "--tools" not in morning
    assert "## This turn: the morning report" in _flag(morning, "--append-system-prompt")
    page.locator(".circle-field__shape").click()
    _send(page, "Hello")
    _answered(page, "Done: Hello")
    ordinary = _cli_starts(tmp_path)[-1]
    assert _flag(ordinary, "--permission-mode") == "bypassPermissions"
    assert "## This turn: the morning report" not in _flag(ordinary, "--append-system-prompt")
    for args in (morning, ordinary):
        instructions = _flag(args, "--append-system-prompt")
        assert "one or two short paragraphs" in instructions and "seven columns" in instructions
        assert "Report exact IDs" not in instructions
    # Fix 7: the gateway kept a log of both turns in its data folder, and no word of either is in it.
    log = (tmp_path / "desktop-state" / "agent.log").read_text()
    assert "send provider=claude permission=bypassPermissions morning=True" in log
    assert "send provider=claude permission=bypassPermissions morning=False" in log
    assert log.count("turn_start") == 2 and log.count("done error=False") == 2 and "agent_start" in log
    assert "Make my morning report" not in log and "Hello" not in log and "Done:" not in log


def _morning_tasks(conn: psycopg.Connection) -> list[tuple]:
    """The open "Morning report" tasks of the owner: id, scale, day, author."""
    return conn.execute(
        "SELECT id, vertical::text, anchor_date, origin::text FROM goals"
        " WHERE owner = %s AND title = 'Morning report' AND done_at IS NULL ORDER BY created_at", (F2_OWNER,),
    ).fetchall()


def test_the_next_morning_moves_the_one_task_to_its_day_instead_of_making_another(ui_agent: UiSession) -> None:
    """Fix 2: two mornings in a row ask the agent twice and leave one open "Morning report" task, the same one, in the
    second day."""
    page = ui_agent.page
    page.wait_for_selector(".goal-card__row")
    with psycopg.connect(ui_agent.backend.dsn, autocommit=True) as conn:
        conn.execute("DELETE FROM idempotency WHERE owner = %s AND client_token LIKE 'morning:%%'", (F2_OWNER,))
    page.reload()
    expect(page.locator('[data-role="circle-answer"]')).to_contain_text("Make my morning report for 2026-08-08", timeout=15000)
    with psycopg.connect(ui_agent.backend.dsn, autocommit=True) as conn:
        (first,) = _morning_tasks(conn)
    page.clock.set_fixed_time("2026-08-09T09:00:00+03:00")
    page.reload()
    expect(page.locator('[data-role="circle-answer"]')).to_contain_text("Make my morning report for 2026-08-09", timeout=15000)
    with psycopg.connect(ui_agent.backend.dsn, autocommit=True) as conn:
        (second,) = _morning_tasks(conn)
    assert (second[0], str(second[2])) == (first[0], "2026-08-09")


@pytest.mark.parametrize("report_day, finishes", [("2026-08-07", False), ("2026-08-08", True)])
def test_check_again_on_a_morning_report_finishes_the_task_only_for_the_day_it_stands_in(
    ui_agent: UiSession, report_day: str, finishes: bool,
) -> None:
    """Fix 2: the one task is linked to every morning's report, so Check again on an earlier report leaves it open and on the
    report of the day the task stands in (the pinned 2026-08-08) it is done. (This was "Ready?" before PR #45 put Check
    again in its place; the rule moved with it into `lib/checkAgain.ts`.)"""
    path = f"reports/morning/{report_day}.md"
    with psycopg.connect(ui_agent.backend.dsn, autocommit=True) as conn:
        task = goals.create(conn, owner=F2_OWNER, title="Morning report", vertical="day",
                            anchor_date=date.fromisoformat(PINNED_DAY), origin="app").goal.id
        doc = core_docs.create(conn, owner=F2_OWNER, path=path, title=f"Morning report — {report_day}").doc.id
        goals.update(conn, owner=F2_OWNER, id=task, body=f"[Morning report — {report_day}](doc:{path})")
    page = ui_agent.page
    page.reload()
    page.wait_for_selector(f'[data-goal-id="{task}"]')
    _send(page, f"[say] Your report: [the report](#doc/{doc}).")
    page.locator(f'{BALLOON}[data-who="agent"] a', has_text="the report").click()
    expect(page.locator('.vt-window[data-window="doc"]')).to_have_count(1)
    page.evaluate("id => window.dispatchEvent(new CustomEvent('verticals:doc-edited', { detail: { id } }))", doc)
    page.locator('[data-role="doc-check-again"]').click()
    expect(page.locator('[data-role="circle-answer"]')).to_contain_text("Changed the words you commented on", timeout=15000)

    def done() -> bool:
        with psycopg.connect(ui_agent.backend.dsn, autocommit=True) as conn:
            return conn.execute("SELECT done_at FROM goals WHERE id = %s", (task,)).fetchone()[0] is not None

    for attempt in range(25):  # it finishes within a moment, or stays open: wait the longer for the first
        if done() or (not finishes and attempt > 8):
            break
        page.wait_for_timeout(200)
    assert done() is finishes


def test_an_ask_is_the_agents_balloon_with_its_choices(ui_agent: UiSession) -> None:
    page = ui_agent.page
    page.wait_for_selector(".goal-card__row")
    _send(page, "Change it [ask]")
    ask = page.locator('[data-role="agent-ask"]')
    expect(ask).to_contain_text("Allow Claude to use update?", timeout=10000)
    # S2.P1.043: the line waits upright until you answer.
    expect(page.locator(".circle-field__pivot.is-turning")).to_have_count(0)
    ask.get_by_role("button", name="Allow once").click()
    _answered(page, "Done: Change it")
    expect(ask).to_have_count(0)


def _select(page: Page, words: str) -> None:
    """Select `words` inside the agent's last balloon, the way a drag across them would."""
    page.evaluate(
        """words => {
          const walker = document.createTreeWalker(document.querySelector('[data-balloon][data-who="agent"]'), NodeFilter.SHOW_TEXT)
          for (let node = walker.nextNode(); node; node = walker.nextNode()) {
            const at = node.textContent.indexOf(words)
            if (at < 0) continue
            const range = document.createRange()
            range.setStart(node, at)
            range.setEnd(node, at + words.length)
            const selection = getSelection()
            selection.removeAllRanges()
            selection.addRange(range)
            return
          }
          throw new Error('not found: ' + words)
        }""",
        words,
    )


def test_the_text_you_selected_goes_with_the_next_message_once(ui_agent: UiSession) -> None:
    """Fix 5: the prompt promises the selected text, so what you select on the page goes with the message you send next,
    even though the field takes the focus and the selection with it; only that message carries it."""
    page = ui_agent.page
    page.wait_for_selector(".goal-card__row")
    _send(page, "[say] The plan has three steps: write, test and ship.")
    _answered(page, "The plan has three steps")
    _select(page, "write, test and ship")
    _send(page, "[context]")
    _answered(page, "Selected text: write, test and ship")
    _send(page, "[context]")
    expect(page.locator(f'{BALLOON}[data-who="agent"]').last).to_contain_text("Today:", timeout=10000)
    expect(page.locator(f'{BALLOON}[data-who="agent"]').last).not_to_contain_text("Selected text")


def test_a_selection_you_pressed_away_from_is_not_sent(ui_agent: UiSession) -> None:
    """Fix 5: a press anywhere else but the field lets the selection go, and it goes unsent."""
    page = ui_agent.page
    page.wait_for_selector(".goal-card__row")
    _send(page, "[say] The plan has three steps: write, test and ship.")
    _answered(page, "The plan has three steps")
    _select(page, "write, test and ship")
    page.locator(BALLOON).first.click()  # your own balloon: a press that is not in the field
    page.evaluate("() => getSelection().removeAllRanges()")
    _send(page, "[context]")
    expect(page.locator(f'{BALLOON}[data-who="agent"]').last).to_contain_text("Today:", timeout=10000)
    expect(page.locator(f'{BALLOON}[data-who="agent"]').last).not_to_contain_text("Selected text")


CHANGES = '[data-role="agent-ask-changes"]'
ASK_SAYS = [
    ("schedule", "Draft the outline · Mon 10 Aug"),   # a day, as the goal cards say it
    ("week", "Draft the outline · 10–16 Aug"),        # a week, as its column header says it
    ("clear", "Draft the outline · No date"),
    ("create", "Plan the review · 10–16 Aug"),
    ("update", "Draft the outline"),                  # a write with no date says only the goal
    ("delete", "Draft the outline"),
    ("unknown", None),                                # a goal this board does not have: no line, and no error
]


def test_an_ask_says_the_goal_and_its_new_date(ui_agent: UiSession) -> None:
    """Fix 6 (docs/design/agent-fixes.md): the card said only "Allow Claude to use schedule?"; it now says which goal and
    which date, in the balloon's own type, so you answer about the change and not about a tool."""
    page = ui_agent.page
    page.wait_for_selector(".goal-card__row")
    for number, (mark, says) in enumerate(ASK_SAYS, start=1):
        _send(page, f"Change number {number} [ask:{mark}]")
        asks = page.locator('[data-role="agent-ask"]')
        expect(asks).to_have_count(1, timeout=10000)
        card = asks.last
        expect(card.get_by_role("button", name="Allow once")).to_be_enabled()
        if says is None:
            page.wait_for_timeout(600)  # the goal is looked for once, and is not there
            expect(card.locator(CHANGES)).to_have_count(0)
        else:
            expect(card.locator(CHANGES)).to_have_text(says)
            # the card's own type: the balloon's 15 px / 22 px regular, the question above it the 600 weight
            expect(card.locator(CHANGES)).to_have_css("font-weight", "400")
            expect(card.locator('.agent-balloon__ask-title')).to_have_css("font-weight", "600")
            expect(card.locator(CHANGES)).to_have_css("font-size", "15px")
        card.get_by_role("button", name="Allow once").click()
        _answered(page, f"Done: Change number {number}")


def test_an_ask_in_the_field_says_it_too(ui_agent: UiSession) -> None:
    """Fix 6: with the conversation closed the ask stands in the field; it says the same under its question."""
    page = ui_agent.page
    page.wait_for_selector(".goal-card__row")
    _send(page, "Move it [ask:schedule]")
    expect(page.locator('[data-role="agent-ask"]')).to_have_count(1, timeout=10000)
    page.locator('[data-role="out-of-focus"]').click(position={"x": 60, "y": 60})
    answer = page.locator('[data-role="circle-answer"]')
    expect(answer).to_contain_text("Allow Claude to use schedule?", timeout=10000)
    expect(answer.locator('[data-role="circle-ask-changes"]')).to_have_text("Draft the outline · Mon 10 Aug")
    page.wait_for_timeout(500)
    box = page.locator(".circle-field__shape").bounding_box()
    assert box is not None and box["height"] >= 24 * 2 + 22 * 2 + 44, box  # its question and its line, then the buttons
    answer.get_by_role("button", name="Allow once").click()
    expect(page.locator('[data-role="circle-answer"]')).to_contain_text("Done: Move it", timeout=10000)


def test_a_conversation_from_before_opens_with_its_messages(ui_agent: UiSession) -> None:
    """S2.P1.031, .040: the conversations stored under `vt-chat:*` are read as they are."""
    page = ui_agent.page
    thread = "5d2c3c3e-1b1a-4c8e-9e1f-0a6f3e3c9b01"
    events = [{"t": "user", "text": "An old question", "ts": 1}, {"t": "turn_start", "ts": 2},
              {"t": "text", "text": "An old answer", "ts": 3}, {"t": "done", "ts": 4}]
    page.evaluate(
        """([id, events]) => {
          localStorage.setItem('vt-chat:threads', JSON.stringify([{ id, title: 'Old', provider: 'claude', updatedAt: 1, status: 'idle' }]))
          localStorage.setItem('vt-chat:current', JSON.stringify(id))
          localStorage.setItem(`vt-chat:events:${id}`, JSON.stringify(events))
        }""",
        [thread, events],
    )
    page.reload()
    page.wait_for_selector(".goal-card__row")
    _send(page, "And a new one")
    expect(page.locator(BALLOON).first).to_have_text("An old question")
    expect(page.locator(BALLOON).nth(1)).to_have_text("An old answer")
    _answered(page, "Done: And a new one")
    stored = json.loads(page.evaluate(f"localStorage.getItem('vt-chat:events:{thread}')"))
    assert [e["t"] for e in stored][:4] == ["user", "turn_start", "text", "done"]


def test_balloons_go_out_at_the_ends_and_come_back(ui_agent: UiSession) -> None:
    """S2.P5.022: a balloon goes out as half of it passes an end, and comes back as half of it returns."""
    page = ui_agent.page
    page.wait_for_selector(".goal-card__row")
    for n in range(5):
        _send(page, f"Message {n} [long]")
        expect(page.locator(f'{BALLOON}[data-who="agent"]')).to_have_count(n + 1, timeout=10000)
        expect(page.locator('[data-role="agent-step"]')).to_have_count(0, timeout=10000)
    sides = lambda: page.locator(BALLOON).evaluate_all("els => els.map(el => el.dataset.side)")  # noqa: E731
    assert "top" in sides() and "bottom" not in sides() and sides()[-1] == "in"
    page.mouse.move(735, 400)
    page.mouse.wheel(0, -600)
    page.wait_for_function(
        "() => [...document.querySelectorAll('[data-balloon]')].some(el => el.dataset.side === 'bottom')", timeout=5000
    )
    page.mouse.wheel(0, 2000)
    page.wait_for_function(
        "() => [...document.querySelectorAll('[data-balloon]')].slice(-1)[0].dataset.side === 'in'", timeout=5000
    )


def test_the_tags_stay_while_the_field_has_the_caret_or_the_conversation_is_open(ui_agent: UiSession) -> None:
    """Not only under the pointer: the tags stay in while the field has the caret or the conversation is open."""
    page = ui_agent.page
    page.wait_for_selector(".goal-card__row")
    page.mouse.move(100, 300)
    tags = page.locator(".circle-tags.is-shown")
    expect(tags).to_have_count(0)
    page.keyboard.press("Control+k")
    expect(tags).to_have_count(1)
    page.keyboard.press("Escape")
    expect(tags).to_have_count(0)

    _send(page, "Hello")
    _answered(page, "")
    page.evaluate("() => document.activeElement?.blur()")
    expect(page.locator(CONVERSATION)).to_be_visible()
    expect(tags).to_have_count(1)
    page.keyboard.press("Control+k")
    page.keyboard.press("Escape")  # the conversation goes, the caret stays
    expect(page.locator(CONVERSATION)).to_have_count(0)
    expect(tags).to_have_count(1)
    page.keyboard.press("Escape")
    expect(tags).to_have_count(0)


def test_no_agent_the_field_only_finds(ui_f2: UiSession) -> None:
    """S2.P1.026: the web build has no gateway: ↵ does nothing, and the menu has no Agent group with Discuss in it."""
    page = ui_f2.page
    page.wait_for_selector('[data-goal-id="SYNDAY01"]')
    page.keyboard.press("Control+k")
    page.locator(FIELD).fill("cycl")
    page.keyboard.press("Enter")
    expect(page.locator(CONVERSATION)).to_have_count(0)
    expect(page.locator(FIELD)).to_have_value("cycl")
    page.keyboard.press("Escape")
    page.keyboard.press("Escape")
    page.click('[data-goal-id="SYNDAY01"] > .goal-card__row [data-role="goal-actions-trigger"]')
    menu = page.locator('[data-role="goal-actions-menu"]')
    expect(menu).to_be_visible()
    expect(menu.locator('[data-menu-section="agent"]')).to_have_count(0)
    expect(menu.get_by_text("Discuss")).to_have_count(0)


def _conversations(page: Page, goal: str) -> list[dict]:
    """The gateway's conversations about a goal, the latest first (what Discuss with agent asks)."""
    return page.evaluate("id => fetch('/__chat/goal?id=' + id).then(r => r.json())", goal)["conversations"]


def test_a_fresh_conversation_that_makes_a_task_becomes_the_tasks_conversation(ui_agent: UiSession, tmp_path: Path) -> None:
    """The conversation was about no goal; the agent made one in it, so it is now that goal's: the gateway keeps it, the app
    keeps it, what is said next carries the goal, and Discuss with agent on the goal goes on with this conversation after
    another has been started. A second goal made in it does not take it over."""
    dsn = ui_agent.backend.dsn
    goal = goal_made(dsn, "Plan the review")
    other = goal_made(dsn, "Another one")
    page = ui_agent.page
    page.reload()
    page.wait_for_selector(f'[data-goal-id="{goal}"]')
    assert _conversations(page, goal) == []
    _send(page, f"Make me a task [make:{goal}|Plan the review] [make:{other}|Another one] [say] Made it.\n[Plan the review](#goal/{goal})")
    _answered(page, "Made it.")
    session = json.loads(page.evaluate("localStorage.getItem('vt-chat:current')"))
    assert [c["session"] for c in _conversations(page, goal)] == [session]
    assert _conversations(page, other) == []
    threads = json.loads(page.evaluate("localStorage.getItem('vt-chat:threads')"))
    assert next(t for t in threads if t["id"] == session)["goal"] == {"id": goal, "title": "Plan the review"}
    # What is said next in it is about the task.
    _send(page, "[context]")
    expect(page.locator(AGENT_BALLOON).last).to_contain_text('about the goal "Plan the review"', timeout=10000)

    # Another conversation is started; the first is out of sight.
    page.locator(".circle-field__shape").hover()
    page.locator(".agent-tag").click()
    page.locator('[data-role="new-conversation"]').click()
    expect(page.locator(BALLOON)).to_have_count(0)
    close_the_conversation(page)
    assert json.loads(page.evaluate("localStorage.getItem('vt-chat:current')")) != session

    # Discuss on the task goes on with the first one, its messages and all.
    row = page.locator(f'[data-goal-id="{goal}"] > .goal-card__row').first
    row.hover()
    row.locator('[data-role="goal-actions-trigger"]').click()
    page.locator('[data-role="goal-context-menu"] [data-menu-item="discuss"]').click()
    expect(page.locator('.vt-window[data-window="goal"]')).to_have_count(1)
    expect(page.locator(f'{BALLOON}[data-who="you"]', has_text="Make me a task")).to_have_count(1, timeout=10000)
    assert json.loads(page.evaluate("localStorage.getItem('vt-chat:current')")) == session
    # The gateway kept saying so in its log, with no goal's name in it.
    log = (tmp_path / "desktop-state" / "agent.log").read_text()
    assert log.count("goal_bound") == 1 and goal not in log and "Plan the review" not in log
