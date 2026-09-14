"""Due acknowledgment from the ghost card's three-dots menu (migration 011) through Chromium.

R10 revised (KK ruling 2026-08-16): a ghost exists only on the wall-clock current period, so
the pinned browser clock (2026-08-08) alone can no longer surface one — the server sees that
as a time-traveled request. Each scenario therefore anchors its ghost in the previous REAL ISO
week and navigates to `/h/<real today>`, the one board the ghost can appear on; the server's
dueness check (`core/due_ack.py`, real current date) agrees with that board by construction.
The native control is created in the current real week for the same reason — F2's frozen rows
are all time-traveled now and never ghost."""

from __future__ import annotations

from datetime import date, timedelta

import psycopg

from verticals.core import goals, vertical
from tests.ui.conftest import UiSession, activate_column

CONTEXT_MENU = '[data-role="goal-context-menu"]'


def _old_week(conn, title: str):
    return goals.create(
        conn, owner="t1", title=title, vertical="week",
        anchor_date=date.today() - timedelta(days=7),
    ).goal


def _native_week(conn, title: str):
    return goals.create(
        conn, owner="t1", title=title, vertical="week", anchor_date=date.today()
    ).goal


def _goto_today(session: UiSession) -> None:
    session.page.goto(f"{session.base_url}/h/{date.today().isoformat()}")


def _open_menu(session: UiSession, goal_id: str):
    activate_column(session.page, "week")
    session.page.locator(f'[data-goal-id="{goal_id}"]').click(button="right")
    menu = session.page.locator(CONTEXT_MENU)
    menu.wait_for(state="visible")
    return menu


def test_acknowledge_due_removes_ghost_and_stores_overdue_verdict(ui_f2: UiSession) -> None:
    session = ui_f2
    with psycopg.connect(session.backend.dsn, autocommit=True) as conn:
        ghost = _old_week(conn, "SYN UI acked ghost")
        control = _native_week(conn, "SYN UI native control")

    _goto_today(session)
    card = session.page.locator(f'[data-goal-id="{ghost.id}"]')
    card.wait_for(state="visible")
    assert card.get_attribute("data-ghost") == "true"

    # Both verdict entries are ghost-only, same gate as Ignore.
    native_menu = _open_menu(session, control.id)
    assert native_menu.locator('[data-menu-item="due-ack"]').count() == 0
    assert native_menu.locator('[data-menu-item="due-done"]').count() == 0
    session.page.keyboard.press("Escape")

    menu = _open_menu(session, ghost.id)
    assert menu.locator('[data-menu-item="due-ack"]').count() == 1
    assert menu.locator('[data-menu-item="due-done"]').count() == 1

    with session.page.expect_response(
        lambda response: response.request.method == "POST"
        and response.url.endswith(f"/api/goals/{ghost.id}/due_ack")
    ) as response_info:
        menu.locator('[data-menu-item="due-ack"]').click()
    assert response_info.value.status == 200
    session.page.wait_for_selector(f'[data-goal-id="{ghost.id}"]', state="detached")

    with psycopg.connect(session.backend.dsn, autocommit=True) as conn:
        assert conn.execute(
            "SELECT done_at FROM goals WHERE id = %s", (ghost.id,)
        ).fetchone() == (None,), "overdue verdict must not complete the goal"
        verdict, period_key = conn.execute(
            "SELECT verdict, period_key FROM due_acknowledgements WHERE goal_id = %s",
            (ghost.id,),
        ).fetchone()
    assert verdict == "overdue"
    assert period_key == vertical.period_key("week", date.today() - timedelta(days=7))


def test_was_done_on_time_completes_goal_and_removes_ghost(ui_f2: UiSession) -> None:
    session = ui_f2
    with psycopg.connect(session.backend.dsn, autocommit=True) as conn:
        ghost = _old_week(conn, "SYN UI done-on-time ghost")

    _goto_today(session)
    session.page.locator(f'[data-goal-id="{ghost.id}"]').wait_for(state="visible")

    menu = _open_menu(session, ghost.id)
    with session.page.expect_response(
        lambda response: response.request.method == "POST"
        and response.url.endswith(f"/api/goals/{ghost.id}/due_ack")
    ) as response_info:
        menu.locator('[data-menu-item="due-done"]').click()
    assert response_info.value.status == 200
    session.page.wait_for_selector(f'[data-goal-id="{ghost.id}"]', state="detached")

    with psycopg.connect(session.backend.dsn, autocommit=True) as conn:
        (done_at,) = conn.execute(
            "SELECT done_at FROM goals WHERE id = %s", (ghost.id,)
        ).fetchone()
        (verdict,) = conn.execute(
            "SELECT verdict FROM due_acknowledgements WHERE goal_id = %s", (ghost.id,)
        ).fetchone()
    assert done_at is not None, "done_on_time verdict completes the goal"
    assert verdict == "done_on_time"
