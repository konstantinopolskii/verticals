"""R10 ghost treatment, Ignore expiry, and drag reschedule through Chromium.

R10 revised (KK ruling 2026-08-16): a ghost exists only on the wall-clock current period. The
ui suite's pinned browser clock (2026-08-08) therefore no longer produces ghosts by itself —
the pinned "today" is a time-traveled request to the server, whose own clock is real. So these
scenarios seed rows RELATIVE TO RUNTIME TODAY and navigate to `/h/<real today>` explicitly: the
one board ghosts can appear on. The old "returns next period" arc (goto a later date) is
restated without a time machine as an already-expired ignore, which is the exact state a live
board wakes up to after the ignored week rolls over."""

from __future__ import annotations

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


def _native_week(conn, title: str):
    """The native control: anchored in the current ISO week, never a ghost."""
    return goals.create(
        conn, owner="t1", title=title, vertical="week", anchor_date=date.today()
    ).goal


def test_ghost_is_dimmed_due_ignore_is_ghost_only_and_expired_ignore_returns(
    ui_f2: UiSession,
) -> None:
    session = ui_f2
    today = date.today()
    week_start, week_end = _week_bounds(today)
    with psycopg.connect(session.backend.dsn, autocommit=True) as conn:
        ghost = _old_week(conn, "SYN UI ignored ghost")
        control = _native_week(conn, "SYN UI native control")

    session.page.goto(f"{session.base_url}/h/{today.isoformat()}")
    card = session.page.locator(f'[data-goal-id="{ghost.id}"]')
    card.wait_for(state="visible")
    assert card.get_attribute("data-ghost") == "true"
    # D125/D127: due state is an inline, punctuated title prefix.
    assert card.locator('.goal-card__due').text_content() == "Due. "
    native = session.page.locator(f'[data-goal-id="{control.id}"]')
    assert native.get_attribute("data-ghost") is None
    assert native.locator('.goal-card__due').count() == 0
    # D168: carryover cards stay opaque.
    assert card.evaluate("el => getComputedStyle(el).opacity") == native.evaluate(
        "el => getComputedStyle(el).opacity"
    )

    activate_column(session.page, "week")
    native.click(button="right")
    assert session.page.locator('[data-role="goal-context-menu"] [data-menu-item="ignore"]').count() == 0
    session.page.keyboard.press("Escape")
    activate_column(session.page, "week")
    card.click(button="right")
    menu = session.page.locator('[data-role="goal-context-menu"]')
    menu.wait_for(state="visible")
    assert menu.locator('[data-menu-item="ignore"]').count() == 1
    with session.page.expect_response(
        lambda response: response.request.method == "PATCH"
        and response.url.endswith(f"/api/goals/{ghost.id}")
    ):
        menu.locator('[data-menu-item="ignore"]').click()
    session.page.wait_for_selector(f'[data-goal-id="{ghost.id}"]', state="detached")

    with psycopg.connect(session.backend.dsn, autocommit=True) as conn:
        assert conn.execute(
            "SELECT done_at, carryover_ignored_until FROM goals WHERE id = %s", (ghost.id,)
        ).fetchone() == (None, week_end)

        # The "returns next period" half without a time machine: expire the ignore as the next
        # rollover would leave it, then re-read the same live board.
        conn.execute(
            "UPDATE goals SET carryover_ignored_until = %s WHERE id = %s",
            (week_start - timedelta(days=1), ghost.id),
        )

    session.page.reload()
    returned = session.page.locator(f'[data-goal-id="{ghost.id}"]')
    returned.wait_for(state="visible")
    assert returned.get_attribute("data-ghost") == "true"


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
