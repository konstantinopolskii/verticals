"""The Inbox (Inbox and Documents redesign, final page, KK 7 Oct 2026) through Chromium, live HTTP and real Postgres:
what was written today on top, newest first, each with the goal it sits under above it, the last three and the rest
behind "N more"; then Earlier, the older tasks, and Documents, every document newest first, each a row that "Show all"
opens in place onto shelves (a task on the shelf of the column it left, `parked_from_vertical`). × goes back to the board.

The page's clock is pinned (`conftest.PINNED_CLOCK_ISO`) while the rows below are stamped by the database's clock, so
each scenario moves the page's clock to the database's day first: "today" means the same day on both sides, as in use.
"""

from __future__ import annotations

from datetime import date, datetime, timezone

import psycopg
from playwright.sync_api import expect

from verticals.core import docs as core_docs, goals as core_goals, moves as core_moves
from tests.ui.conftest import UiSession
from tests.ui.views import switch_view

OWNER = "t1"
DAY = date(2026, 8, 8)
TODAY = '[data-role="inbox-today"]'
CARD = '[data-role="inbox-card"]'


def _goal(conn: psycopg.Connection, title: str, **kwargs: object) -> str:
    return core_goals.create(conn, owner=OWNER, title=title, **kwargs).goal.id


def _written(conn: psycopg.Connection, goal_id: str, ago: str) -> None:
    conn.execute("UPDATE goals SET created_at = now() - %s::interval WHERE owner = %s AND id = %s", (ago, OWNER, goal_id))


def _open_inbox(session: UiSession) -> None:
    session.page.clock.set_fixed_time(datetime.now(timezone.utc))
    session.page.reload()
    switch_view(session.page, "inbox")


def test_today_stands_on_top_and_show_all_puts_the_rest_on_the_shelf_of_the_column_it_left(ui_f2: UiSession) -> None:
    session = ui_f2
    page = session.page
    with psycopg.connect(session.backend.dsn, autocommit=True) as conn:
        month = _goal(conn, "SYN Inbox month", vertical="month", anchor_date=DAY)
        loose = _goal(conn, "SYN Inbox thought of today")
        idea = _goal(conn, "SYN Inbox idea under the month", parent_id=month)
        _written(conn, loose, "1 minute")
        _written(conn, idea, "2 minutes")
        parked = _goal(conn, "SYN Inbox parked week task", vertical="week", anchor_date=DAY)
        core_moves.park(conn, owner=OWNER, id=parked)
        _written(conn, parked, "3 days")
        old = _goal(conn, "SYN Inbox old thought")
        _written(conn, old, "5 days")
        doc = core_docs.create(conn, owner=OWNER, path="syn-inbox/loose.md", title="SYN Inbox loose document").doc.id

    _open_inbox(session)
    cards = page.locator(f"{TODAY} {CARD}")
    expect(cards.nth(0)).to_have_attribute("data-goal-id", loose, timeout=10000)
    expect(cards.nth(1)).to_have_attribute("data-goal-id", idea)
    expect(cards.nth(1).locator('[data-role="inbox-goal"]')).to_have_text("SYN Inbox month")

    expect(page.locator(f'{TODAY} [data-goal-id="{parked}"], {TODAY} [data-goal-id="{old}"]')).to_have_count(0)

    earlier = page.locator('[data-role="inbox-earlier"]')
    expect(earlier.locator(f'[data-role="inbox-tile"][data-goal-id="{parked}"]')).to_contain_text("Week ·")
    expect(earlier.locator(f'[data-role="inbox-tile"][data-goal-id="{old}"]')).to_contain_text("Life ·")
    earlier.locator('[data-role="inbox-earlier-all"]').click()
    expect(earlier.locator('[data-role="inbox-earlier-all"]')).to_have_text("Show less")
    expect(page.locator(f'[data-shelf="week"] + .inbox-desk__grid [data-goal-id="{parked}"]')).to_be_visible()
    expect(page.locator(f'[data-shelf="life"] + .inbox-desk__grid [data-goal-id="{old}"]')).to_be_visible()

    # Every document is in the Inbox too, newest first: the one just made leads the Documents row.
    docs = page.locator('[data-role="inbox-docs"]')
    expect(docs.locator('[data-role="doc-chip"]').first).to_have_attribute("data-doc-id", doc)
    expect(docs.locator('[data-role="doc-chip"]').first).to_contain_text("SYN Inbox loose document")

    # The title and × stay at the top; × goes back to the board.
    page.locator('[data-cap="inbox"] [data-role="desk-close"]').click()
    expect(page.locator('[data-cap="inbox"]')).to_have_count(0)


def test_today_shows_its_last_three_and_the_rest_behind_n_more(ui_f2: UiSession) -> None:
    session = ui_f2
    page = session.page
    with psycopg.connect(session.backend.dsn, autocommit=True) as conn:
        ids = [_goal(conn, f"SYN Inbox today {i}") for i in range(5)]
        for i, goal_id in enumerate(ids):
            _written(conn, goal_id, f"{5 - i} minutes")

    _open_inbox(session)
    cards = page.locator(f"{TODAY} {CARD}")
    expect(cards.first).to_have_attribute("data-goal-id", ids[-1], timeout=10000)
    shown = cards.count()
    assert shown == 3, f"today shows its last three, not {shown}"
    more = page.locator('[data-role="inbox-more"]')
    hidden = int(more.inner_text().split()[0])
    assert hidden >= 2
    more.click()
    expect(cards).to_have_count(3 + hidden)
    expect(more).to_contain_text("Show fewer")
    more.click()
    expect(cards).to_have_count(3)


def test_a_card_written_today_has_no_goal_until_one_is_found(ui_f2: UiSession) -> None:
    """With no agent beside the app (this web build has none), a thought stays where it landed, a card with no goal
    line: nothing is planned, started or filed for it."""
    session = ui_f2
    page = session.page
    with psycopg.connect(session.backend.dsn, autocommit=True) as conn:
        loose = _goal(conn, "SYN Inbox thought with no goal")

    _open_inbox(session)
    card = page.locator(f'{TODAY} {CARD}[data-goal-id="{loose}"]')
    expect(card).to_be_visible(timeout=10000)
    expect(card.locator('[data-role="inbox-goal"]')).to_have_count(0)
    expect(card.locator('[data-role="inbox-finding"]')).to_have_count(0)
    with psycopg.connect(session.backend.dsn, autocommit=True) as conn:
        row = conn.execute("SELECT vertical, parent_id FROM goals WHERE owner = %s AND id = %s", (OWNER, loose)).fetchone()
    assert row == (None, None)
