"""Carried-over plans (docs/design-handoff scope 4): the group on top of a column opens in place, lights for the family
under the pointer, and "Replan" opens the sorting task as a goal's window with our first message sent."""

from __future__ import annotations

import re
from datetime import date

import psycopg
from playwright.sync_api import Page, expect

from verticals.core import goals, replan
from tests.ui.conftest import UiSession
from tests.ui.test_agent_conversation import ui_agent  # noqa: F401  (the fixture)
from tests.ui.views import FIELD

GROUP = '.pattern-vertical-board__column[data-vertical="year"] [data-role="carried-group"]'
FIRST = "Read this task and help me sort these plans out: where each goes, based on when I planned it and what it belongs to."


def _last_year(conn: psycopg.Connection, title: str, parent: str | None = None) -> str:
    today = date.today()
    return goals.create(
        conn, owner="t1", title=title, vertical="year", anchor_date=date(today.year - 1, 6, 15), parent_id=parent,
    ).goal.id


def _goto_today(page: Page, base_url: str) -> None:
    page.goto(f"{base_url}/h/{date.today().isoformat()}")
    page.wait_for_selector(GROUP)


def test_more_opens_the_rest_in_place_newest_first(ui_f2: UiSession) -> None:
    """S4.P2.010, .037: three in view, "N more" on the titles' line; opened, the rest in place and "Show fewer"."""
    with psycopg.connect(ui_f2.backend.dsn, autocommit=True) as conn:
        for n in range(4):
            _last_year(conn, f"SYN carried {n}")
    page = ui_f2.page
    _goto_today(page, ui_f2.base_url)
    group = page.locator(GROUP)
    total = int(group.get_attribute("data-count") or 0)
    rows = group.locator('[data-section="carried"] > .goal-card')
    expect(rows).to_have_count(3)
    more = group.locator('[data-role="carried-more"]')
    expect(more).to_have_text(f"{total - 3} more")
    more.click()
    expect(rows).to_have_count(total)
    expect(more).to_have_text("Show fewer")
    more.click()
    expect(rows).to_have_count(3)


def test_pointing_at_a_goal_lights_its_family_in_the_box(ui_f2: UiSession) -> None:
    """S4.P3.021-.023: the box takes the goal's colour and shows its family's plans, keeps about its height, and goes
    back to rest when the pointer leaves."""
    with psycopg.connect(ui_f2.backend.dsn, autocommit=True) as conn:
        value = goals.create(conn, owner="t1", title="SYN value with carried plans", vertical="life", anchor_date=date.today(), color="#92ce14").goal.id
        mine = _last_year(conn, "SYN the value's carried plan", parent=value)
        _last_year(conn, "SYN someone else's carried plan")
    page = ui_f2.page
    _goto_today(page, ui_f2.base_url)
    group = page.locator(GROUP)
    height = group.bounding_box()["height"]
    page.locator(f'[data-goal-id="{value}"] > .goal-card__row').hover()
    expect(group).to_have_class(re.compile("carried-group--lit"))
    expect(group.locator('[data-section="carried"] > .goal-card')).to_have_count(1)
    expect(group.locator(f'[data-goal-id="{mine}"]')).to_have_count(1)
    assert abs(group.bounding_box()["height"] - height) <= 2
    page.mouse.move(5, 5)
    expect(group).not_to_have_class(re.compile("carried-group--lit"))


def test_replan_opens_the_task_as_a_window_with_our_first_message(ui_agent: UiSession) -> None:  # noqa: F811
    """S4.P4.028: the task pops out as a goal's window, our first message sent, the agent answering under it."""
    with psycopg.connect(ui_agent.backend.dsn, autocommit=True) as conn:
        _last_year(conn, "SYN plan to sort")
        with conn.transaction():
            task = replan.run(conn, owner="t1", today=date.today())
    page = ui_agent.page
    _goto_today(page, ui_agent.base_url)
    page.locator(GROUP).locator('[data-role="replan"]').click()
    window = page.locator('.vt-window[data-window="goal"]')
    expect(window).to_have_count(1)
    expect(window.locator(f'.goal-card[data-goal-id="{task}"]')).to_have_count(1)
    expect(page.locator('[data-balloon][data-who="you"]').first).to_have_text(FIRST)
    expect(page.locator('[data-balloon][data-who="agent"]')).to_have_count(1, timeout=10000)
    page.mouse.click(window.bounding_box()["x"] + 40, window.bounding_box()["y"] + 40)
    expect(window.locator('[data-role="goal-made"]')).to_have_text(re.compile(r"^made \w{3} \d{1,2} \w{3}$"))
    expect(window.locator("table")).to_contain_text("SYN plan to sort")
    # S4.P4.010: every turn in the task tells the agent how its table is worked.
    page.keyboard.press("Control+k")
    page.locator(FIELD).fill("[context]")
    page.keyboard.press("Enter")
    expect(page.locator('[data-balloon][data-who="agent"]').last).to_contain_text("Your comment, one row per plan", timeout=10000)

    # A browser that has never seen the task's conversation continues it: our first message goes only once.
    page.evaluate("() => localStorage.clear()")
    _goto_today(page, ui_agent.base_url)
    page.locator(GROUP).locator('[data-role="replan"]').click()
    expect(page.locator('[data-balloon][data-who="agent"]').last).to_contain_text("Your comment, one row per plan", timeout=10000)
    page.wait_for_timeout(500)
    expect(page.locator('[data-balloon][data-who="you"]', has_text=FIRST)).to_have_count(1)
