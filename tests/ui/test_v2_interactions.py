"""R4/R5/R6 card interactions through Chromium, live HTTP, and real Postgres."""

from __future__ import annotations

import psycopg

from playwright.sync_api import expect

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
    # The systematic menu (docs/design-handoff S5.P5.007): Discuss (only where an agent is), Comment, Complete, then Move.
    # Details left it (S5.P5.024): a click on the card opens it.
    assert _menu_items(session) == ["Comment", "Complete"]
    assert session.page.locator(f'{MENU} [data-move="inbox"]').count() == 1
    assert session.page.locator(f'{MENU} [data-menu-item="foil"]').count() == 0
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


def test_right_click_uses_same_menu_with_the_move_group(ui_f2: UiSession) -> None:
    """S5.P5.035: one grey "Move" over Tomorrow, Next week and Date, then Under and Inbox."""
    session = ui_f2
    card = session.page.locator(_card("SYNCOL03"))
    card.wait_for(state="visible")
    card.click(button="right")
    session.page.wait_for_selector(MENU)
    assert _menu_items(session) == ["Comment"]
    assert session.page.locator(f'{MENU} [data-menu-item="complete"]').count() == 0
    assert session.page.locator(f'{MENU} [data-menu-item="ignore"]').count() == 0
    assert session.page.locator(f'{MENU} [data-menu-item="details"]').count() == 0
    move = session.page.locator(f'{MENU} [data-menu-section="move"]')
    expect(move.locator(".goal-actions__heading")).to_have_text("Move")
    assert [t.strip() for t in move.locator("[data-move]").all_inner_texts()] == ["Tomorrow", "Next week", "Date", "Under", "Inbox"]
    assert session.page.locator(f'{MENU} [data-cap="park"]').count() == 0


def test_inbox_takes_the_goal_off_its_dates(ui_f2: UiSession) -> None:
    """S5.P5.004: "Inbox" under Move clears the goal's schedule; it leaves the board for the Inbox."""
    session = ui_f2
    card = session.page.locator(_card("SYNORD01"))
    card.wait_for(state="visible")
    activate_column(session.page, "week")
    card.click(button="right")
    with session.page.expect_response(
        lambda response: response.request.method == "PUT"
        and response.url.endswith("/api/goals/SYNORD01/schedule")
    ):
        session.page.click(f'{MENU} [data-move="inbox"]')
    session.page.wait_for_selector(_card("SYNORD01"), state="detached")

    with psycopg.connect(session.backend.dsn, autocommit=True) as conn:
        assert conn.execute(
            "SELECT vertical, period_key FROM goals WHERE id = 'SYNORD01'"
        ).fetchone() == (None, None)