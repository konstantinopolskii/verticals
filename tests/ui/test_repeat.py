"""Repeat configuration through the real browser, HTTP server, and Postgres."""

from __future__ import annotations

import psycopg

from tests.ui.conftest import UiSession


def test_repeat_menu_uses_nested_kit_surface_and_marks_the_card(ui_f2: UiSession) -> None:
    session = ui_f2
    card = '[data-goal-id="SYNCOL04"]'
    session.gestures.click(f'{card} [data-role="goal-actions-trigger"]')
    session.gestures.click('[data-role="goal-actions-menu"] [data-action="repeat"] button')

    menu = session.page.locator('[data-role="repeat-menu"]')
    menu.wait_for(state="visible")
    assert menu.get_attribute("role") == "menu"
    assert menu.locator('[role="dialog"]').count() == 0
    labels = menu.locator(':scope > button[role="menuitem"]').all_text_contents()
    assert labels[:6] == ["Daily", "Weekly", "Monthly", "Quarterly", "Yearly", "Every decade"]

    session.gestures.click('[data-role="repeat-menu"] button[role="menuitem"]:has-text("Daily")')
    session.page.wait_for_timeout(300)
    with psycopg.connect(session.backend.dsn, autocommit=True) as conn:
        (rule,) = conn.execute(
            "SELECT repeat_rule FROM goals WHERE owner = 't1' AND id = 'SYNCOL04'"
        ).fetchone()
    assert rule == {"frequency": "daily", "interval": 1}
    session.page.reload()
    session.page.wait_for_selector(f'{card} [data-role="repeat-indicator"]')

    # D89: the rule in force must show as the selected one when the menu is reopened. Postgres
    # hands jsonb back in its own key order, so the client's old stringify comparison marked
    # nothing — a defect no dict-equality assertion above can see. Read it off the DOM.
    session.gestures.click(f'{card} [data-role="goal-actions-trigger"]')
    session.gestures.click('[data-role="goal-actions-menu"] [data-action="repeat"] button')
    reopened = session.page.locator('[data-role="repeat-menu"]')
    reopened.wait_for(state="visible")
    active = reopened.locator(':scope > button[role="menuitem"]._active').all_text_contents()
    assert active == ["Daily"], active


def test_repeat_refused_on_a_parent_looks_refused(ui_f2: UiSession) -> None:
    """D91: the app refuses repeat on a goal with subgoals — the user has to be able to SEE that.

    `.dropdown__item:hover` carried no `:disabled` guard and nothing else styled the state, so the
    refused item highlighted exactly like a live one and said nothing until a native tooltip
    appeared. Two facts, both read off the rendered surface: it is dimmer than a live sibling, and
    hovering it paints no background.
    """
    session = ui_f2
    session.gestures.click('[data-goal-id="SYNDAY01"] > .goal-card__row [data-role="goal-actions-trigger"]')
    menu = session.page.locator('#dropdownPortal [data-role="goal-actions-menu"]')
    menu.wait_for(state="visible")

    refused = menu.locator('[data-action="repeat"]')
    assert refused.get_attribute("disabled") is not None, (
        "SYNDAY01 has subgoals — its repeat action must be disabled"
    )
    live = menu.locator('[data-action="delete"]')

    def ink(locator: object) -> str:
        return locator.evaluate("el => getComputedStyle(el).color")  # type: ignore[attr-defined]

    def paint(locator: object) -> str:
        return locator.evaluate("el => getComputedStyle(el).backgroundColor")  # type: ignore[attr-defined]

    assert ink(refused) != ink(live), (
        f"refused and live menu items render the same ink ({ink(refused)}) — nothing tells them apart"
    )

    refused.hover(force=True)  # a disabled control takes no real pointer events; force the state
    session.page.wait_for_timeout(100)
    hovered = paint(refused)
    assert hovered in ("rgba(0, 0, 0, 0)", "transparent"), (
        f"hovering the refused item painted {hovered} — it reads as clickable"
    )
