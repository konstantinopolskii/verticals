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
    # The opened-card cleanup (KK 27-28 Sep 2026): foil left the card, and "Remove from vertical" sits with the ways to
    # move a goal, below the actions. "Comment" starts a comment on a goal that has none (KK, 29 Sep 2026).
    assert _menu_items(session) == ["Details", "Comment", "Complete"]
    assert session.page.locator(f'{MENU} [data-menu-item="park"]').count() == 1
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


def test_right_click_uses_same_menu_and_details_action(ui_f2: UiSession) -> None:
    session = ui_f2
    card = session.page.locator(_card("SYNCOL03"))
    card.wait_for(state="visible")
    card.click(button="right")
    session.page.wait_for_selector(MENU)
    assert _menu_items(session) == ["Details", "Comment"]
    assert session.page.locator(f'{MENU} [data-menu-item="park"]').count() == 1
    assert session.page.locator(f'{MENU} [data-menu-item="complete"]').count() == 0
    assert session.page.locator(f'{MENU} [data-menu-item="ignore"]').count() == 0

    session.page.click(f'{MENU} [data-menu-item="details"]')
    session.page.wait_for_selector("#goal-detail")


def test_park_removes_card(ui_f2: UiSession) -> None:
    """Foil's half of this test left with foil (KK, 27 Sep 2026: "let's kill the foil option. It's a mess for now")."""
    session = ui_f2
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
