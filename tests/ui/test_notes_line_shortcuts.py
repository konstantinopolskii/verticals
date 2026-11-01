"""A list or heading shortcut typed on a later line of a goal's notes turns only that line into a list or a heading. The
lines above it stay, on the page, in the saved body and after a reload."""

from __future__ import annotations

import psycopg
import pytest
from playwright.sync_api import Locator, expect

from tests.ui.conftest import UiSession
from tests.ui.test_board_undo import board
from tests.ui.test_cmd_z_in_text import GOAL, a_goals_notes
from tests.ui.undo_helpers import wait_for

SHORTCUTS = {"1. ": "ol li", "- ": "ul li", "## ": "h2"}


def body(conn: psycopg.Connection) -> str:
    return conn.execute("SELECT body FROM goals WHERE id = %s", (GOAL,)).fetchone()[0]


def shows(notes: Locator, made: str) -> None:
    expect(notes.locator(made)).to_have_text("item")
    expect(notes).to_contain_text("First line")


@pytest.mark.parametrize("saved", [False, True], ids=["new notes", "saved notes"])
@pytest.mark.parametrize("shortcut", list(SHORTCUTS))
def test_a_shortcut_on_a_later_line_keeps_the_lines_above(ui_f2: UiSession, shortcut: str, saved: bool) -> None:
    session = ui_f2
    page = board(session)
    with psycopg.connect(session.backend.dsn, autocommit=True) as conn:
        if saved:
            conn.execute("UPDATE goals SET body = 'First line' WHERE id = %s", (GOAL,))
            page.reload()
            board(session)
        notes = a_goals_notes(session, conn)
        if saved:
            page.keyboard.press("End")
        else:
            page.keyboard.type("First line")
        page.keyboard.press("Enter")
        page.keyboard.type(f"{shortcut}item")

        shows(notes, SHORTCUTS[shortcut])
        wait_for(page, lambda: body(conn), f"First line\n\n{shortcut}item", "the saved body keeps the first line")

        page.reload()
        board(session)
        page.locator(f'[data-goal-id="{GOAL}"] > .goal-card__row .goal-card__title').click()
        shows(page.locator(f'.goal-card--detail-open[data-goal-id="{GOAL}"] + .goal-card__children--open [data-cap="edit-body"]'),
              SHORTCUTS[shortcut])
