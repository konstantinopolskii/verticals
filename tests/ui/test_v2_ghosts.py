"""R10 carried plans in their group (docs/design-handoff S4.P2) and drag reschedule through Chromium.

R10 revised (KK ruling 2026-08-16): a ghost exists only on the wall-clock current period. The
ui suite's pinned browser clock (2026-08-08) therefore no longer produces ghosts by itself —
the pinned "today" is a time-traveled request to the server, whose own clock is real. So these
scenarios seed rows RELATIVE TO RUNTIME TODAY and navigate to `/h/<real today>` explicitly: the
one board ghosts can appear on."""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta

import psycopg
from playwright.sync_api import expect

from verticals.core import goals, vertical
from tests.ui.conftest import UiSession, activate_column


def _week_bounds(today: date) -> tuple[date, date]:
    start = today - timedelta(days=today.isoweekday() - 1)
    return start, start + timedelta(days=6)


def _old_week(conn, title: str):
    """A week row anchored in the previous ISO week — overdue on today's live board."""
    return goals.create(
        conn, owner="t1", title=title, vertical="week",
        anchor_date=date.today() - timedelta(days=7),
    ).goal


def test_carried_plans_stand_in_one_group_on_top_of_their_column(ui_f2: UiSession) -> None:
    """docs/design-handoff S4.P2.035-.037, S4.P1.020: the group on top with its notice and "Replan", no date after a
    title, no red line, and no Ignore or acknowledgement in the menu. A year's plan from last year stays in Year
    whatever day the suite runs on (S4.P1.007)."""
    session = ui_f2
    today = date.today()
    with psycopg.connect(session.backend.dsn, autocommit=True) as conn:
        ghost = goals.create(
            conn, owner="t1", title="SYN UI last year's plan", vertical="year", anchor_date=date(today.year - 1, 6, 15),
        ).goal
        control = goals.create(conn, owner="t1", title="SYN UI this year's plan", vertical="year", anchor_date=today).goal

    session.page.goto(f"{session.base_url}/h/{today.isoformat()}")
    card = session.page.locator(f'[data-goal-id="{ghost.id}"]')
    card.wait_for(state="visible")
    assert card.get_attribute("data-ghost") == "true"
    year = session.page.locator('.pattern-vertical-board__column[data-vertical="year"]')
    group = year.locator('[data-role="carried-group"]')
    expect(group).to_have_count(1)
    assert group.locator(f'[data-goal-id="{ghost.id}"]').count() == 1
    assert group.locator(f'[data-goal-id="{control.id}"]').count() == 0
    # F2's own plans from 2020 share the group, so its notice names the oldest's way (S4.P2.028).
    expect(group.locator('[data-role="carried-notice"]')).to_have_text(re.compile(r"^\d+ from earlier years$"))
    expect(group.locator('[data-role="replan"]')).to_have_text("Replan")
    first = year.locator(".pattern-vertical-board__body > *").first
    assert first.get_attribute("data-role") == "carried-place" and first.locator('[data-role="carried-group"]').count() == 1
    assert session.page.locator('[data-role="now-line"], .goal-card__planned-period, .goal-card__due').count() == 0
    # D168: carryover cards stay opaque.
    native = session.page.locator(f'[data-goal-id="{control.id}"]')
    assert card.evaluate("el => getComputedStyle(el).opacity") == native.evaluate("el => getComputedStyle(el).opacity")

    activate_column(session.page, "year")
    card.click(button="right")
    menu = session.page.locator('[data-role="goal-context-menu"]')
    menu.wait_for(state="visible")
    for item in ("ignore", "due-ack", "due-done"):
        assert menu.locator(f'[data-menu-item="{item}"]').count() == 0


def test_dragging_ghost_into_current_column_reschedules_without_changing_identity(
    ui_f2: UiSession,
) -> None:
    session = ui_f2
    today = date.today()
    week_start, week_end = _week_bounds(today)
    with psycopg.connect(session.backend.dsn, autocommit=True) as conn:
        ghost = _old_week(conn, "SYN UI dragged ghost")

    # The drop's new anchor comes from the frontend's schedule grid, which is built around the
    # BROWSER clock — pinned to 2026-08-08 by the suite. On the real-today board that pin makes
    # the drop fall back to a still-overdue anchor and the ghost never clears, a divergence that
    # cannot happen in production (browser and server clocks agree). Re-pin to real now so the
    # grid and the server describe the same week; still frozen, so no mid-test drift.
    session.page.clock.set_fixed_time(datetime.now())
    session.page.goto(f"{session.base_url}/h/{today.isoformat()}")
    source = f'[data-goal-id="{ghost.id}"] > .goal-card__row'
    session.page.wait_for_selector(source)
    with session.page.expect_response(
        lambda response: response.request.method == "PUT"
        and response.url.endswith(f"/api/goals/{ghost.id}/schedule")
    ):
        session.gestures.drag(
            source,
            '[data-vertical="week"] .pattern-vertical-board__body',
            source_position={"x": 48, "y": 12},
            target_position={"x": 80, "y": 120},
        )

    card = session.page.locator(f'[data-goal-id="{ghost.id}"]')
    card.wait_for(state="visible")
    expect(card).not_to_have_attribute("data-ghost", "true", timeout=10_000)
    with psycopg.connect(session.backend.dsn, autocommit=True) as conn:
        vertical_key, period_key, anchor = conn.execute(
            "SELECT vertical, period_key, anchor_date FROM goals WHERE id = %s", (ghost.id,)
        ).fetchone()
    assert (vertical_key, period_key) == ("week", vertical.period_key("week", today))
    assert week_start <= anchor <= week_end
