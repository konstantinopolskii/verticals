"""Hide Completed Goals (docs/design/hide-completed.md): ⇧⌘H (Ctrl+Shift+H elsewhere) takes the done goals off the board and
brings them back, steps under a goal included; a done goal's open steps stay; a goal checked off keeps its place while its
check draws, then leaves, and Undo brings it back; the choice survives a reload; the keyboard guide lists the keys; the
desktop app's View menu reaches the same switch and is told the answer. F2, owner `t1`: SYNDON01 "Shipped today" is the
day's done goal, SYNCOL01 "Color check yellow" an open one."""

from __future__ import annotations

import psycopg
import pytest
from playwright.sync_api import Page, expect

from tests.ui.conftest import UiSession
from tests.ui.test_agent_conversation import goal_made

KEYS = "ControlOrMeta+Shift+KeyH"
DONE = "SYNDON01"
OPEN = "SYNCOL01"


@pytest.fixture
def ui_reduced_motion() -> str:
    """The check draws and then the row leaves: the order of the two is part of what is tested."""
    return "no-preference"


def card(page: Page, goal: str):
    return page.locator(f'[data-goal-id="{goal}"]')


def board(session: UiSession) -> Page:
    session.page.wait_for_selector('[data-goal-id="SYNDAY01"]', timeout=10000)
    return session.page


def test_the_keys_take_done_goals_off_the_board_and_bring_them_back(ui_f2: UiSession, f2_dsn: str) -> None:
    trip = goal_made(f2_dsn, "Pack for the trip")
    bought = goal_made(f2_dsn, "Buy a charger", parent=trip, done=True)
    booked = goal_made(f2_dsn, "Book the hotel", parent=trip)
    page = board(ui_f2)
    page.reload()
    board(ui_f2)
    for goal in (DONE, bought, booked):
        expect(card(page, goal)).to_have_count(1)

    page.keyboard.press(KEYS)
    expect(card(page, DONE)).to_have_count(0)
    expect(card(page, bought)).to_have_count(0)  # a done step under an open goal
    expect(card(page, booked)).to_have_count(1)
    expect(card(page, booked)).to_be_visible()
    # A goal's steps are the list right after its card.
    under = f"el => el.closest('.goal-card__children')?.previousElementSibling?.getAttribute('data-goal-id') === '{trip}'"
    assert card(page, booked).evaluate(under), "the open step stays under its goal"

    page.reload()  # remembered on this device
    board(ui_f2)
    expect(card(page, DONE)).to_have_count(0)
    expect(card(page, bought)).to_have_count(0)

    page.keyboard.press(KEYS)
    expect(card(page, DONE)).to_have_count(1)
    expect(card(page, bought)).to_have_count(1)


def test_a_done_goal_leaves_its_open_steps_on_the_board(ui_f2: UiSession, f2_dsn: str) -> None:
    old = goal_made(f2_dsn, "Old plan", done=True)
    left = goal_made(f2_dsn, "Still to do", parent=old)
    page = board(ui_f2)
    page.reload()
    board(ui_f2)
    page.keyboard.press(KEYS)
    expect(card(page, old)).to_have_count(0)
    expect(card(page, left)).to_be_visible()


def test_a_goal_checked_off_keeps_its_place_while_its_check_draws_then_leaves(ui_f2: UiSession) -> None:
    page = board(ui_f2)
    page.keyboard.press(KEYS)
    expect(card(page, OPEN)).to_be_visible()
    ui_f2.gestures.click(f'[data-goal-id="{OPEN}"] > .goal-card__row label.checkbox')
    # In the same moment as the click: still on the board, checked, where it was.
    assert page.evaluate(f"""() => {{
      const box = document.querySelector('[data-goal-id="{OPEN}"] > .goal-card__row input.checkbox__input')
      return !!box && box.checked
    }}"""), "the goal left before its check was drawn"
    expect(card(page, OPEN)).to_have_count(0, timeout=3000)
    with psycopg.connect(ui_f2.backend.dsn, autocommit=True) as conn:
        for _ in range(30):
            (done_at,) = conn.execute("SELECT done_at FROM goals WHERE id = %s", (OPEN,)).fetchone()
            if done_at is not None:
                break
            page.wait_for_timeout(100)
    assert done_at is not None

    page.keyboard.press("ControlOrMeta+KeyZ")  # Undo brings it back, open
    expect(card(page, OPEN)).to_be_visible()
    expect(page.locator(f'[data-goal-id="{OPEN}"] > .goal-card__row input.checkbox__input')).not_to_be_checked()


def test_the_keyboard_guide_lists_the_keys(ui_f2: UiSession) -> None:
    page = board(ui_f2)
    # ? on a goal opens the guide, with or without a button for it on the board.
    page.locator(".goal-card__row").first.focus()
    page.keyboard.press("?")
    binding = page.locator(".keyboard-guide__binding", has_text="Hide or show completed goals")
    expect(binding).to_have_count(1)
    assert [k.strip() for k in binding.locator("kbd").all_inner_texts()][1:] == ["Shift", "H"]


def test_the_desktop_menu_switches_it_and_is_told_the_answer(ui_f2: UiSession) -> None:
    """The app's View menu item calls `verticalsToggleHideDone`; the page answers through the `hideDone` message, by which
    the item ticks itself (desktop/macos/Verticals.swift). Here a recorder stands where the app's message handler is."""
    page = ui_f2.page
    page.add_init_script("window.told = []; window.webkit = { messageHandlers: { hideDone: { postMessage: (on) => window.told.push(on) } } }")
    page.reload()
    board(ui_f2)
    assert page.evaluate("window.told") == [False]
    page.evaluate("window.verticalsToggleHideDone()")
    expect(card(page, DONE)).to_have_count(0)
    page.keyboard.press(KEYS)
    expect(card(page, DONE)).to_have_count(1)
    assert page.evaluate("window.told") == [False, True, False]
