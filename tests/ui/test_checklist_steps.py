"""A step's date decides where it shows (docs/design/checklist-steps.md).

The sample board (F1) with two steps added under its Week task: one with a date, the task's own week, and one with no
date. The dated step stands on the board under the task. The undated step is not on the board; the task, opened, lists it
after the dated one, and there it completes and opens as a step does. A step added inside the open task has no date and
stays inside it. The dated step's menu takes its date away like any goal's ("To Inbox"): it leaves the board, shows inside
the opened task and in the Inbox, and ⌘Z puts it back. No Hide / Show subtasks toggle is left. Each test runs in light and
in dark."""

from __future__ import annotations

import re
from collections.abc import Iterator
from datetime import date
from pathlib import Path

import httpx
import psycopg
import pytest
from playwright.sync_api import Browser, Page, expect

from tests.ui.conftest import F1_OWNER, UiSession, _backend, _make_ui_session, _static_server
from tests.ui.undo_helpers import keys, wait_for
from verticals.core import goals

DAY = date(2026, 8, 8)  # the pinned clock's day, in the sample board's own week
TASK = "SAMPLE04"  # "Sample week goal", the Week task
TOGGLE = re.compile(r"^(Hide|Show) \d+ subtasks?$")


@pytest.fixture(params=["light", "dark"])
def sample(
    browser: Browser, f1_dsn: str, tmp_path: Path, request: pytest.FixtureRequest, web_dist: None,
    ui_reduced_motion: str,
) -> Iterator[tuple[UiSession, dict[str, str]]]:
    with psycopg.connect(f1_dsn, autocommit=True) as conn:
        steps = {
            "dated": goals.create(conn, owner=F1_OWNER, title="Sample dated step", parent_id=TASK, vertical="week",
                                  anchor_date=DAY).goal.id,
            "undated": goals.create(conn, owner=F1_OWNER, title="Sample undated step", parent_id=TASK).goal.id,
        }
    with _backend(f1_dsn, F1_OWNER, tmp_path) as backend:
        with _static_server(backend.base_url, tmp_path) as base_url:
            for session in _make_ui_session(browser=browser, backend=backend, static_base_url=base_url,
                                            request=request, reduced_motion=ui_reduced_motion,
                                            color_scheme=request.param):
                session.page.wait_for_selector(f'.goal-card[data-goal-id="{TASK}"]')
                yield session, steps


def _card(page: Page, goal_id: str):
    return page.locator(f'.goal-card[data-goal-id="{goal_id}"]')


def _under(page: Page, parent: str, child: str):
    """`child` drawn as a step in `parent`'s own list."""
    return page.locator(f'.goal-card[data-goal-id="{parent}"] + .goal-card__children > .goal-card[data-goal-id="{child}"]')


def _steps(page: Page, parent: str) -> list[str]:
    return page.locator(f'.goal-card[data-goal-id="{parent}"] + .goal-card__children > .goal-card').evaluate_all(
        "els => els.map(el => el.dataset.goalId)")


def _open(page: Page, goal_id: str) -> None:
    page.locator(f'.goal-card[data-goal-id="{goal_id}"] > .goal-card__row .goal-card__title').first.click()
    page.wait_for_selector(f'.goal-card.goal-card--detail-open[data-goal-id="{goal_id}"]')


def _close(page: Page) -> None:
    page.keyboard.press("Escape")
    page.wait_for_selector(".goal-card.goal-card--detail-open", state="detached")


def _row(dsn: str, sql: str, *args: object) -> tuple | None:
    with psycopg.connect(dsn, autocommit=True) as conn:
        return conn.execute(sql, args).fetchone()


def _no_toggle(page: Page) -> None:
    expect(page.locator('[data-role="subtasks-toggle"]')).to_have_count(0)
    expect(page.get_by_role("button", name=TOGGLE)).to_have_count(0)


def test_a_dated_step_is_on_the_board_and_an_undated_one_is_not(sample) -> None:
    session, steps = sample
    page = session.page
    expect(_under(page, TASK, steps["dated"])).to_be_visible()
    expect(_card(page, steps["undated"])).to_have_count(0)
    _no_toggle(page)


def test_the_opened_task_lists_its_undated_step_after_the_dated_one_and_it_completes_there(sample) -> None:
    session, steps = sample
    page = session.page
    _open(page, TASK)
    expect(_under(page, TASK, steps["undated"])).to_be_visible()
    assert _steps(page, TASK) == [steps["dated"], steps["undated"]]
    _no_toggle(page)

    _under(page, TASK, steps["undated"]).locator(':scope > .goal-card__row [data-cap="complete"]').click()
    expect(_under(page, TASK, steps["undated"]).locator(':scope > .goal-card__row [data-cap="complete"]')).to_have_attribute(
        "aria-checked", "true")
    for _ in range(50):
        if _row(session.backend.dsn, "SELECT done_at FROM goals WHERE id = %s", steps["undated"])[0] is not None:
            break
        page.wait_for_timeout(100)
    assert _row(session.backend.dsn, "SELECT done_at FROM goals WHERE id = %s", steps["undated"])[0] is not None

    _close(page)
    expect(_card(page, steps["undated"])).to_have_count(0)
    expect(_under(page, TASK, steps["dated"])).to_be_visible()


def test_an_undated_step_opens_inside_its_task(sample) -> None:
    """One level in from the open task, and a link straight to the step: the task is the line above it."""
    session, steps = sample
    page = session.page
    _open(page, TASK)
    _open(page, steps["undated"])
    expect(page.locator(f'.goal-card.goal-card--path-line[data-goal-id="{TASK}"]')).to_be_visible()
    expect(_under(page, TASK, steps["undated"])).to_be_visible()

    page.goto(f"{session.base_url}/#goal/{steps['undated']}")
    page.wait_for_selector(f'.goal-card.goal-card--detail-open[data-goal-id="{steps["undated"]}"]')
    expect(_under(page, TASK, steps["undated"])).to_be_visible()


def test_a_step_added_inside_the_open_task_has_no_date_and_stays_inside(sample) -> None:
    session, _ = sample
    page = session.page
    _open(page, TASK)
    page.locator('[data-role="subgoal-add"]').click()
    editor = page.locator('[data-role="subgoal-add-editor"]')
    expect(editor).to_be_focused()
    editor.fill("Sample added step")
    editor.press("Enter")

    row = None
    for _ in range(50):
        row = _row(session.backend.dsn, "SELECT id, vertical, anchor_date FROM goals WHERE parent_id = %s AND title = %s",
                   TASK, "Sample added step")
        if row:
            break
        page.wait_for_timeout(100)
    assert row is not None and row[1:] == (None, None), row
    expect(_under(page, TASK, row[0])).to_be_visible()

    if editor.count():
        editor.press("Escape")  # the editor waits for the next step; Escape puts it away first
    _close(page)
    expect(_card(page, row[0])).to_have_count(0)


def test_a_dated_steps_menu_takes_its_date_away_and_cmd_z_puts_it_back(sample) -> None:
    """D179 kept Reschedule and To Inbox out of the menu of a step under a parent of its own column, as such a step then
    showed nowhere. It shows inside its parent now, so its menu is any goal's."""
    session, steps = sample
    page = session.page
    dsn = session.backend.dsn
    place = lambda: _row(dsn, "SELECT vertical::text, anchor_date::text, parent_id FROM goals WHERE id = %s", steps["dated"])  # noqa: E731

    _under(page, TASK, steps["dated"]).locator(":scope > .goal-card__row").click(button="right")
    menu = page.locator('[data-role="goal-context-menu"]')
    for item in ("tomorrow", "next-week", "date", "under", "inbox"):
        expect(menu.locator(f'[data-move="{item}"]')).to_have_count(1)
    menu.locator('[data-action="inbox"]').click()
    wait_for(page, lambda: place()[0], None, "the date is taken away")
    assert place()[2] == TASK  # still the task's step
    expect(_card(page, steps["dated"])).to_have_count(0)

    _open(page, TASK)
    expect(_under(page, TASK, steps["dated"])).to_be_visible()
    _close(page)
    inbox = httpx.get(f"{session.backend.base_url}/api/undated", headers={"Authorization": f"Bearer {session.backend.token}"})
    listed = {goal["id"]: goal for goal in inbox.json()["goals"]}  # what the Inbox draws
    assert listed[steps["dated"]]["parent"]["id"] == TASK

    undo, _ = keys(page)
    page.keyboard.press(undo)
    wait_for(page, place, ("week", DAY.isoformat(), TASK), "⌘Z puts the date back")
    expect(_under(page, TASK, steps["dated"])).to_be_visible()
