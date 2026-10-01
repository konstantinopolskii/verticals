"""The goal's Move menu (docs/design-handoff S5.P5): Date opens its levels in place with ‹ back, Week lists the week
starts as a table, a specific date is the most basic calendar, and Under finds a goal by typing and makes this one its
step. F2, the browser clock pinned to 2026-08-08 (a Saturday)."""

from __future__ import annotations

import re

import psycopg
from playwright.sync_api import Page, expect

from tests.ui.conftest import UiSession, activate_column

MENU = '[data-role="goal-context-menu"]'
STEP = f'{MENU} [data-role="move-step"]'


def _menu(page: Page, goal_id: str, vertical: str) -> None:
    activate_column(page, vertical)
    page.locator(f'[data-goal-id="{goal_id}"] > .goal-card__row').first.click(button="right")
    page.wait_for_selector(MENU)


def _goal(ui: UiSession, goal_id: str) -> tuple:
    with psycopg.connect(ui.backend.dsn, autocommit=True) as conn:
        return conn.execute("SELECT vertical, period_key, anchor_date, parent_id FROM goals WHERE id = %s", (goal_id,)).fetchone()


def test_date_opens_its_levels_in_place_and_week_is_a_table(ui_f2: UiSession) -> None:
    """S5.P5.013-.016, .036: the levels, then the week starts: how far, the day, the month once; ← goes back."""
    page = ui_f2.page
    page.wait_for_selector('[data-goal-id="SYNORD01"]')
    _menu(page, "SYNORD01", "week")
    page.click(f'{MENU} [data-move="date"]')
    expect(page.locator(f"{STEP} .move-step__title")).to_have_text("Move to a date")
    assert [t.strip() for t in page.locator(f"{STEP} [data-level]").all_inner_texts()] == [
        "Week", "Month", "Quarter", "Year", "Specific date",
    ]
    page.click(f'{STEP} [data-level="week"]')
    rows = page.locator(f"{STEP} .move-step__row")
    expect(rows.first).to_have_text(re.compile(r"This\s*3\s*August"))
    expect(rows.nth(1)).to_have_text(re.compile(r"Next\s*10"))
    expect(rows.nth(1).locator(".move-step__name")).to_have_text("")
    expect(rows.first).to_have_class(re.compile("move-step__row--own"))
    page.keyboard.press("ArrowLeft")
    expect(page.locator(f"{STEP} .move-step__title")).to_have_text("Move to a date")
    page.click(f'{STEP} [data-level="week"]')
    with page.expect_response(lambda r: r.request.method == "PUT" and r.url.endswith("/api/goals/SYNORD01/schedule")):
        rows.nth(2).click()
    expect(page.locator(MENU)).to_have_count(0)
    vertical, period, anchor, _ = _goal(ui_f2, "SYNORD01")
    assert (vertical, period, str(anchor)) == ("week", "2026-W34", "2026-08-17")


def test_a_specific_date_is_a_calendar(ui_f2: UiSession) -> None:
    """S5.P5.017, .038, .040: headed Date, the month and ‹ › at the right, today filled, past days still pickable."""
    page = ui_f2.page
    page.wait_for_selector('[data-goal-id="SYNCOL01"]')
    _menu(page, "SYNCOL01", "day")
    page.click(f'{MENU} [data-move="date"]')
    page.click(f'{STEP} [data-level="calendar"]')
    expect(page.locator(f"{STEP} .move-step__title")).to_have_text("Date")
    expect(page.locator(f"{STEP} .move-step__month")).to_contain_text("Aug ’26")
    today = page.locator(f'{STEP} [data-date="2026-08-08"]')
    expect(today).to_have_class(re.compile("is-today"))
    expect(page.locator(f'{STEP} [data-date="2026-08-03"]')).to_have_class(re.compile("is-past"))
    with page.expect_response(lambda r: r.request.method == "PUT" and r.url.endswith("/api/goals/SYNCOL01/schedule")):
        page.click(f'{STEP} [data-date="2026-08-20"]')
    vertical, _, anchor, _ = _goal(ui_f2, "SYNCOL01")
    assert (vertical, str(anchor)) == ("day", "2026-08-20")


def test_under_finds_a_goal_by_typing_and_makes_this_one_its_step(ui_f2: UiSession) -> None:
    """S5.P5.011, .012, .037: the search icon left, the circled × right; typing narrows by name; a click reparents."""
    page = ui_f2.page
    page.wait_for_selector('[data-goal-id="SYNORD02"]')
    _menu(page, "SYNORD02", "week")
    page.click(f'{MENU} [data-move="under"]')
    search = page.locator(f'{STEP} [data-role="move-under-search"]')
    expect(search).to_be_focused()
    search.fill("bicycles")
    match = page.locator(f'{STEP} [data-parent-id="SYNSCH01"]')
    expect(match).to_have_count(1, timeout=5000)
    expect(match.locator("strong")).to_have_text(re.compile("bicycles", re.IGNORECASE))
    expect(match.locator(".move-step__vertical")).to_have_text("Month")
    expect(page.locator(f"{STEP} .move-step__clear")).to_have_count(1)
    with page.expect_response(lambda r: r.request.method == "PUT" and r.url.endswith("/api/goals/SYNORD02/parent")):
        match.click()
    assert _goal(ui_f2, "SYNORD02")[3] == "SYNSCH01"
