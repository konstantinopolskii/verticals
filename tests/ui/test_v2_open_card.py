"""R8/R9 parent and value details — D248 open-card canon (supersedes the 2026-08-13 inline-detail
round this file was originally written against).

D248 killed the goal-detail modal outright: an opened card is a board card in an expanded state,
never a second surface. There is no more parallel children list (`[data-role="linked-subgoals"]`
is gone along with the modal it lived in) — same-vertical children are the ordinary nested board
`GoalCard`s D244 already renders under a card once its column expands, open or not, so the full
D245-D247 drag machinery applies to them unchanged. Cross-vertical children stay in their own
columns exactly as before (D192) but now carry the D235 "open-related" wash
(`goal-card--open-related`) while an ancestor's card is open, in place of the old detail-only
list that used to hide them. Ideas/principles grouped sections (D207/legacy) had no equivalent in
the killed modal's board-hosted mode and have none here either — this file pins their continued
absence rather than re-inventing them.
"""

from __future__ import annotations

from datetime import date

from playwright.sync_api import expect
import psycopg

from verticals.core import goals, moves
from tests.ui.conftest import UiSession, activate_column

ANCHOR = date(2026, 8, 8)


def _create(conn, title: str, vertical: str, parent_id: str | None = None):
    return goals.create(
        conn, owner="t1", title=title, vertical=vertical, anchor_date=ANCHOR,
        parent_id=parent_id,
    ).goal


def _open(session: UiSession, goal_id: str) -> None:
    title = session.page.locator(
        f'[data-goal-id="{goal_id}"] > .goal-card__row .goal-card__title'
    )
    vertical = title.evaluate("el => el.closest('[data-vertical]').dataset.vertical")
    activate_column(session.page, vertical)
    title.click()
    session.page.wait_for_selector('#goal-detail[data-role="inline-detail"] [role="group"]')


def test_parent_open_card_nests_same_vertical_children_and_washes_cross_vertical(
    ui_f2: UiSession,
) -> None:
    session = ui_f2
    with psycopg.connect(session.backend.dsn, autocommit=True) as conn:
        parent = _create(conn, "SYN open year parent", "year")
        year = _create(conn, "SYN open year child", "year", parent.id)
        month = _create(conn, "SYN open month child", "month", parent.id)
        week = _create(conn, "SYN open week child", "week", parent.id)
        parked = _create(conn, "SYN open parked child", "week", parent.id)
        moves.park(conn, owner="t1", id=parked.id)

    session.page.reload()
    session.page.wait_for_selector(f'[data-goal-id="{parent.id}"]')
    _open(session, parent.id)

    inline = session.page.locator('#goal-detail[data-role="inline-detail"]')
    assert inline.evaluate("el => el.closest('[data-goal-id]').dataset.goalId") == parent.id
    assert "pattern-vertical-board__column--deck-main" in (
        session.page.locator('[data-vertical="year"]').get_attribute("class") or ""
    )
    assert "pattern-vertical-board__column--deck-main" not in (
        session.page.locator('[data-vertical="day"]').get_attribute("class") or ""
    )

    # D248: the same-vertical child is an ORDINARY board GoalCard nested under the open card's own
    # `[data-goal-id]` — no parallel render surface, no separate list, so the drag machinery that
    # already governs every other nested card applies to it too. It also wears the D235
    # open-related wash: it is a descendant of the open goal.
    nested_year = session.page.locator(
        f'[data-goal-id="{parent.id}"] + .goal-card__children [data-goal-id="{year.id}"]'
    )
    expect(nested_year).to_be_visible()
    assert "goal-card--open-related" in (nested_year.get_attribute("class") or "")

    # Cross-vertical children: NOT drawn inside the opened card (D192, unchanged by D248) — they
    # stay in their own columns, marked by the D235 open-related wash rather than duplicated into
    # a detail-only list (that list no longer exists at all, asserted below).
    for child in (month, week):
        own_column_card = session.page.locator(
            f'[data-vertical="{child.vertical}"] [data-goal-id="{child.id}"]'
        )
        expect(own_column_card).to_be_visible()
        assert "goal-card--open-related" in (own_column_card.get_attribute("class") or ""), (
            f"D235: cross-vertical child {child.id} must wear the open-related wash while its "
            "ancestor's card is open"
        )
        assert session.page.locator(
            f'[data-goal-id="{parent.id}"] .goal-card__children [data-goal-id="{child.id}"]'
        ).count() == 0, "a cross-vertical child must not be nested inside the opened card"

    # The killed modal's parallel render surface (D248 WP-C) does not exist anywhere on the page.
    assert session.page.locator('[data-role="linked-subgoals"]').count() == 0
    assert session.page.locator('[data-role="vertical-group"]').count() == 0
    assert session.page.locator('[data-role="vertical-label"]').count() == 0

    # Parked child: absent from the board entirely (R7), open or not.
    assert session.page.locator(f'[data-goal-id="{parked.id}"]').count() == 0

    session.page.keyboard.press("Escape")
    session.page.wait_for_selector('#goal-detail[data-role="inline-detail"]', state="detached")
    session.page.wait_for_function(
        """() => document.querySelector('[data-vertical="day"]')
            ?.classList.contains('pattern-vertical-board__column--deck-main')"""
    )
    assert "pattern-vertical-board__column--deck-main" in (
        session.page.locator('[data-vertical="day"]').get_attribute("class") or ""
    )
    # Closing clears the wash too — it tracks `store.state.openGoalId`, not a sticky flag.
    for child in (month, week):
        assert "goal-card--open-related" not in (
            session.page.locator(f'[data-vertical="{child.vertical}"] [data-goal-id="{child.id}"]')
            .get_attribute("class") or ""
        )


def test_value_open_card_nests_same_vertical_children_without_a_parallel_list(
    ui_f2: UiSession,
) -> None:
    session = ui_f2
    with psycopg.connect(session.backend.dsn, autocommit=True) as conn:
        value = _create(conn, "SYN open value", "life")
        principle = _create(conn, "SYN open principle", "life", value.id)
        context = _create(conn, "SYN open context", "life", value.id)
        year_idea = _create(conn, "SYN open year idea", "year", value.id)
        month_idea = _create(conn, "SYN open month idea", "month", context.id)
        moves.park(conn, owner="t1", id=month_idea.id)
        moves.park(conn, owner="t1", id=year_idea.id)

    session.page.reload()
    session.page.wait_for_selector(f'[data-goal-id="{value.id}"]')
    _open(session, value.id)

    # D248: same-vertical (life) children are the board's own nested GoalCards — the legacy
    # Principles section (a detail-only duplicate render) is gone outright, not relocated.
    for child in (principle, context):
        nested = session.page.locator(
            f'[data-goal-id="{value.id}"] + .goal-card__children [data-goal-id="{child.id}"]'
        )
        expect(nested).to_be_visible()
        assert "goal-card--open-related" in (nested.get_attribute("class") or "")
    assert session.page.locator('[data-role="principles-section"]').count() == 0
    assert session.page.locator('[data-role="linked-subgoals"]').count() == 0

    # Parked descendants: absent everywhere, board and detail alike (R7) — an ancestor's card
    # being open does not resurrect a parked row.
    for absent in (year_idea, month_idea):
        assert session.page.locator(f'[data-goal-id="{absent.id}"]').count() == 0
    assert session.page.locator('[data-role="ideas-section"]').count() == 0

    session.page.keyboard.press("Escape")
    session.page.wait_for_selector('#goal-detail[data-role="inline-detail"]', state="detached")
