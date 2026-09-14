"""R4/R5/R6 card interactions through Chromium, live HTTP, and real Postgres."""

from __future__ import annotations

import psycopg

from tests.ui.conftest import UiSession, activate_column

MENU = '[data-role="goal-context-menu"]'


def _card(goal_id: str) -> str:
    return f'[data-goal-id="{goal_id}"]'


def _affordance(goal_id: str) -> str:
    return f'{_card(goal_id)} [data-role="goal-affordance"]'


def _menu_items(session: UiSession) -> list[str]:
    return session.page.locator(
        f'{MENU} [data-menu-section="actions"] [role=menuitem]'
    ).all_text_contents()


def test_leaf_click_completes_but_parent_click_opens_unified_menu(ui_f2: UiSession) -> None:
    session = ui_f2
    session.page.wait_for_selector(_affordance("SYNCOL01"))
    assert session.page.locator(_affordance("SYNCOL01")).get_attribute("data-affordance") == "leaf"
    with session.page.expect_response(
        lambda response: response.request.method == "PATCH"
        and response.url.endswith("/api/goals/SYNCOL01")
    ):
        session.page.click(_affordance("SYNCOL01"))
    session.page.wait_for_selector(f'{_card("SYNCOL01")}.goal-card--done')

    before = len(session.request_log)
    assert session.page.locator(_affordance("SYNDAY01")).get_attribute("data-affordance") == "parent"
    session.page.click(_affordance("SYNDAY01"))
    session.page.wait_for_selector(MENU)
    session.page.wait_for_timeout(100)
    assert _menu_items(session) == ["Details", "Complete", "Foil", "Remove from vertical"]
    assert all(ord(ch) < 128 for text in _menu_items(session) for ch in text)
    assert not any(
        row["method"] == "PATCH" and row["url"].endswith("/api/goals/SYNDAY01")
        for row in session.request_log[before:]
    ), "parent affordance must not one-click complete"

    with psycopg.connect(session.backend.dsn, autocommit=True) as conn:
        assert conn.execute(
            "SELECT done_at FROM goals WHERE id = 'SYNDAY01'"
        ).fetchone() == (None,)

    with session.page.expect_response(
        lambda response: response.request.method == "PATCH"
        and response.url.endswith("/api/goals/SYNDAY01")
    ):
        session.page.click(f'{MENU} [data-menu-item="complete"]')
    with psycopg.connect(session.backend.dsn, autocommit=True) as conn:
        assert conn.execute(
            "SELECT done_at IS NOT NULL FROM goals WHERE id = 'SYNDAY01'"
        ).fetchone() == (True,)


def test_right_click_uses_same_menu_and_details_action(ui_f2: UiSession) -> None:
    session = ui_f2
    card = session.page.locator(_card("SYNCOL03"))
    card.wait_for(state="visible")
    card.click(button="right")
    session.page.wait_for_selector(MENU)
    assert _menu_items(session) == ["Details", "Foil", "Remove from vertical"]
    assert session.page.locator(f'{MENU} [data-menu-item="complete"]').count() == 0
    assert session.page.locator(f'{MENU} [data-menu-item="ignore"]').count() == 0

    session.page.click(f'{MENU} [data-menu-item="details"]')
    session.page.wait_for_selector("#goal-detail")


def test_foil_toggle_class_hook_and_park_removes_card(ui_f2: UiSession) -> None:
    session = ui_f2
    foil_card = session.page.locator(_card("SYNCOL04"))
    foil_card.wait_for(state="visible")
    foil_card.click(button="right")
    with session.page.expect_response(
        lambda response: response.request.method == "PATCH"
        and response.url.endswith("/api/goals/SYNCOL04")
    ):
        session.page.click(f'{MENU} [data-menu-item="foil"]')
    session.page.wait_for_selector(f'{_card("SYNCOL04")}.foil')

    with psycopg.connect(session.backend.dsn, autocommit=True) as conn:
        assert conn.execute("SELECT foil FROM goals WHERE id = 'SYNCOL04'").fetchone() == (True,)

    park_card = session.page.locator(_card("SYNORD01"))
    park_card.wait_for(state="visible")
    activate_column(session.page, "week")
    park_card.click(button="right")
    with session.page.expect_response(
        lambda response: response.request.method == "POST"
        and response.url.endswith("/api/goals/SYNORD01/park")
    ):
        session.page.click(f'{MENU} [data-menu-item="park"]')
    session.page.wait_for_selector(_card("SYNORD01"), state="detached")

    with psycopg.connect(session.backend.dsn, autocommit=True) as conn:
        assert conn.execute(
            "SELECT vertical, period_key, parked_from_vertical FROM goals WHERE id = 'SYNORD01'"
        ).fetchone() == (None, None, "week")
