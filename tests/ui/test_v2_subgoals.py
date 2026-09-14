"""R7 board display rule through Chromium, live HTTP, and real Postgres."""

from __future__ import annotations

from datetime import date
import time

import psycopg
from playwright.sync_api import expect

from verticals.core import goals, moves
from tests.ui.conftest import UiSession, activate_column

ANCHOR = date(2026, 8, 8)
GRIP = {"x": 50, "y": 6}
TOAST_TEXT = ".toast-stack .toast .toast__text"


def _wait_for_vertical(page, conn, goal_id: str, vertical: str, timeout: float = 5) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        row = conn.execute("SELECT vertical FROM goals WHERE id = %s", (goal_id,)).fetchone()
        if row and row[0] == vertical:
            return
        page.wait_for_timeout(50)


def _create(
    conn,
    title: str,
    vertical: str,
    parent_id: str | None = None,
    anchor: date = ANCHOR,
):
    return goals.create(
        conn, owner="t1", title=title, vertical=vertical, anchor_date=anchor,
        parent_id=parent_id,
    ).goal


def test_same_vertical_nests_lower_vertical_stands_alone_and_parked_is_absent(
    ui_f2: UiSession,
) -> None:
    session = ui_f2
    with psycopg.connect(session.backend.dsn, autocommit=True) as conn:
        parent = _create(conn, "SYN UI month parent", "month")
        same = _create(conn, "SYN UI same month", "month", parent.id)
        lower = _create(conn, "SYN UI lower week", "week", parent.id)
        parked = _create(conn, "SYN UI parked", "week", parent.id)
        off_column_parent = _create(
            conn, "SYN UI future month parent", "month", anchor=date(2026, 9, 8)
        )
        visible_without_parent = _create(
            conn, "SYN UI current month child", "month", off_column_parent.id
        )
        moves.park(conn, owner="t1", id=parked.id)

    session.page.reload()
    # D244: nested month rows render only in the expanded month column.
    activate_column(session.page, "month")
    parent_card = session.page.locator(f'[data-goal-id="{parent.id}"]')
    parent_card.wait_for(state="visible")
    # D179: same-vertical children stay nested; D142: hierarchy is always expanded.
    assert session.page.locator(f'[data-goal-id="{same.id}"]').count() == 1
    assert session.page.locator(f'[data-vertical="week"] [data-goal-id="{lower.id}"]').count() == 1
    assert session.page.locator(
        f'[data-vertical="month"] [data-goal-id="{visible_without_parent.id}"]'
    ).count() == 1
    assert session.page.locator(f'[data-goal-id="{off_column_parent.id}"]').count() == 0
    assert session.page.locator(f'[data-goal-id="{parked.id}"]').count() == 0

    nested = session.page.locator(
        f'[data-goal-id="{parent.id}"] + .goal-card__children [data-goal-id="{same.id}"]'
    )
    nested.wait_for(state="visible")
    assert session.page.locator(f'[data-goal-id="{same.id}"]').count() == 1
    assert parent_card.locator(f'[data-goal-id="{lower.id}"]').count() == 0
    assert session.page.locator(f'[data-goal-id="{parked.id}"]').count() == 0


def test_drag_parent_week_to_day_cascades_subtree_and_toasts(ui_f2: UiSession) -> None:
    session = ui_f2
    with psycopg.connect(session.backend.dsn, autocommit=True) as conn:
        parent = _create(conn, "SYN UI cascade parent", "week")
        child = _create(conn, "SYN UI cascade child", "week", parent.id)
        grandchild = _create(conn, "SYN UI cascade grandchild", "week", child.id)

    session.page.reload()
    parent_row = f'[data-goal-id="{parent.id}"] > .goal-card__row'
    day_body = '[data-vertical="day"] .pattern-vertical-board__body'
    expect(session.page.locator(parent_row)).to_be_visible()
    expect(session.page.locator(day_body)).to_be_visible()

    session.gestures.drag(parent_row, day_body, source_position=GRIP, target_position=GRIP)

    toast = session.page.locator(TOAST_TEXT)
    expect(toast).to_have_text("2 subgoals moved to Today with it", timeout=15000)
    day_parent = session.page.locator(f'[data-vertical="day"] [data-goal-id="{parent.id}"]')
    expect(day_parent).to_be_visible(timeout=15000)
    # D244: the cascaded subtree folds into the compact day stack; unfold to assert its shape.
    activate_column(session.page, "day")
    day_child = session.page.locator(
        f'[data-goal-id="{parent.id}"] + .goal-card__children [data-goal-id="{child.id}"]'
    )
    expect(day_child).to_be_visible()
    expect(session.page.locator(
        f'[data-goal-id="{child.id}"] + .goal-card__children [data-goal-id="{grandchild.id}"]'
    )).to_be_visible()

    with psycopg.connect(session.backend.dsn, autocommit=True) as conn:
        rows = conn.execute(
            "SELECT id, vertical, period_key FROM goals WHERE id = ANY(%s) ORDER BY id",
            ([parent.id, child.id, grandchild.id],),
        ).fetchall()
    assert {(row[1], row[2]) for row in rows} == {("day", "2026-08-08")}


def test_same_vertical_subgoal_has_no_independent_schedule_or_reparent_menu(ui_f2: UiSession) -> None:
    session = ui_f2
    with psycopg.connect(session.backend.dsn, autocommit=True) as conn:
        parent = _create(conn, "SYN UI day parent", "day")
        child = _create(conn, "SYN UI day child", "day", parent.id)

    session.page.reload()
    # D244: the nested day child renders only in the expanded day column.
    activate_column(session.page, "day")
    parent_card = session.page.locator(f'[data-goal-id="{parent.id}"]')
    expect(parent_card).to_be_visible()
    child_card = session.page.locator(
        f'[data-goal-id="{parent.id}"] + .goal-card__children [data-goal-id="{child.id}"]'
    )
    expect(child_card).to_be_visible()
    child_card.locator(
        ':scope > .goal-card__row [data-role="goal-actions-trigger"]'
    ).click(force=True)
    menu = session.page.locator('#dropdownPortal [data-role="goal-actions-menu"]')
    expect(menu).to_be_visible()
    # D179: same-vertical nested children have no independent schedule/detach/reparent paths.
    assert menu.locator('[data-action="schedule"]').count() == 0
    assert menu.locator('[data-action="inbox"]').count() == 0
    assert menu.locator('[data-action="reparent"]').count() == 0


def test_same_vertical_child_drag_detaches_on_top_level_slot(ui_f2: UiSession) -> None:
    """D241 (supersedes D179's block half): the exact gesture D179 swallowed — a nested
    same-vertical child dragged by its grip onto a top-level card's edge band in its own
    column — now detaches the child to the GRANDPARENT at that slot, not to nowhere (owner
    report 2026-08-17: the old full detach dropped the row out of its value chain and it
    rendered gray). The value root here is a colored life goal two links up; after the drag
    the child must hang off it directly and keep its D231-derived color."""
    session = ui_f2
    with psycopg.connect(session.backend.dsn, autocommit=True) as conn:
        value = goals.create(
            conn, owner="t1", title="SYN UI unglue value", vertical="life",
            anchor_date=ANCHOR, color="#955be0",
        ).goal
        parent = _create(conn, "SYN UI unglue parent", "day", value.id)
        child = _create(conn, "SYN UI unglue child", "day", parent.id)

    session.page.reload()
    # D244: the glued child is a drag source only once its column expands.
    activate_column(session.page, "day")
    parent_card = session.page.locator(f'[data-goal-id="{parent.id}"]')
    expect(parent_card).to_be_visible()
    child_row = (
        f'[data-goal-id="{child.id}"] > .goal-card__row'
    )
    expect(session.page.locator(child_row)).to_be_visible()

    # y=2, not GRIP's y=6: D236's centre combine band covers the middle 50% of the compact row,
    # so 6px is already "into this parent" — 2px stays in the top-quarter reorder band. SYNCOL01
    # sits ABOVE the dragged child, so the drag's source gap-close shifts nothing at the target.
    session.gestures.drag(
        child_row,
        '[data-goal-id="SYNCOL01"] > .goal-card__row',
        source_position=GRIP,
        target_position={"x": 50, "y": 2},
    )

    with psycopg.connect(session.backend.dsn, autocommit=True) as conn:
        row = (parent.id, "day")
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            row = conn.execute(
                "SELECT parent_id, vertical FROM goals WHERE id = %s", (child.id,)
            ).fetchone()
            if row[0] != parent.id:
                break
            session.page.wait_for_timeout(100)
    assert row == (value.id, "day"), (
        f"D241: top-level slot drop must climb to the grandparent, got {row!r}"
    )

    # D231: the chain to the value survived, so the card still wears the value's color —
    # the gray orphan of the 2026-08-17 report is exactly what this pin forbids.
    card = session.page.locator(f'[data-goal-id="{child.id}"]')
    expect(card).to_be_visible()
    expect(card).to_have_attribute("data-colored", "true", timeout=10_000)


def test_same_vertical_child_alt_drag_combines_into_another_parent(ui_f2: UiSession) -> None:
    """D241's other half: a glued child Alt-dragged onto ANOTHER card combines into it like any
    top-level card would (D236 semantics — new parent, inherited vertical). Pre-D241 the server
    refused this reparent outright."""
    session = ui_f2
    with psycopg.connect(session.backend.dsn, autocommit=True) as conn:
        # The adopter is created FIRST so it renders ABOVE the dragged child: a drag collapses
        # the source's footprint (goal-card--source-gap-closed), shifting every row below it up
        # one slot — a drop point computed pre-drag onto a below-source card lands one row off.
        adopter = _create(conn, "SYN UI adopting parent", "day")
        parent = _create(conn, "SYN UI adopt-from parent", "day")
        child = _create(conn, "SYN UI adopted child", "day", parent.id)

    session.page.reload()
    activate_column(session.page, "day")  # D244: unfold the glued child before dragging it
    child_row = f'[data-goal-id="{child.id}"] > .goal-card__row'
    adopter_row = f'[data-goal-id="{adopter.id}"] > .goal-card__row'
    expect(session.page.locator(child_row)).to_be_visible()
    expect(session.page.locator(adopter_row)).to_be_visible()

    session.page.keyboard.down("Alt")
    try:
        session.gestures.drag(
            child_row, adopter_row, source_position=GRIP, target_position=GRIP
        )
    finally:
        session.page.keyboard.up("Alt")

    with psycopg.connect(session.backend.dsn, autocommit=True) as conn:
        row = (parent.id, "day")
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            row = conn.execute(
                "SELECT parent_id, vertical FROM goals WHERE id = %s", (child.id,)
            ).fetchone()
            if row[0] == adopter.id:
                break
            session.page.wait_for_timeout(100)
    assert row == (adopter.id, "day"), f"D241: Alt-drag adopt failed, got {row!r}"


def test_same_vertical_child_drags_to_another_vertical_without_losing_parent(
    ui_f2: UiSession,
) -> None:
    session = ui_f2
    with psycopg.connect(session.backend.dsn, autocommit=True) as conn:
        parent = _create(conn, "SYN UI movable quarter parent", "quarter")
        child = _create(conn, "SYN UI movable quarter child", "quarter", parent.id)

    session.page.reload()
    activate_column(session.page, "quarter")  # D244: unfold the glued child before dragging it
    child_row = f'[data-goal-id="{child.id}"] > .goal-card__row'
    month_body = '[data-vertical="month"] .pattern-vertical-board__body'
    expect(session.page.locator(child_row)).to_be_visible()
    expect(session.page.locator(month_body)).to_be_visible()

    session.gestures.drag(child_row, month_body, source_position=GRIP, target_position=GRIP)

    moved = session.page.locator(f'[data-vertical="month"] [data-goal-id="{child.id}"]')
    expect(moved).to_be_visible(timeout=15000)
    with psycopg.connect(session.backend.dsn, autocommit=True) as conn:
        _wait_for_vertical(session.page, conn, child.id, "month")
        row = conn.execute(
            "SELECT parent_id, vertical, period_key FROM goals WHERE id = %s", (child.id,)
        ).fetchone()
    # D242 (KK, 2026-08-16): LEFTWARD (shorter vertical) is a slice of the parent — link stays.
    assert row == (parent.id, "month", "2026-08")


def test_same_vertical_child_drag_right_splits_to_grandparent(ui_f2: UiSession) -> None:
    """D242 (KK, 2026-08-16), the other side of the left/right law: a glued subtask dragged
    RIGHTWARD (a longer vertical) outgrows its parent — it detaches and wires to the parent's
    own parent, so the chain to the value survives one link up. Quarter grandparent -> day
    parent -> glued day child; the child dropped on the week column must land under the
    grandparent."""
    session = ui_f2
    with psycopg.connect(session.backend.dsn, autocommit=True) as conn:
        grandparent = _create(conn, "SYN UI split grandparent", "quarter")
        parent = _create(conn, "SYN UI split parent", "day", grandparent.id)
        child = _create(conn, "SYN UI split child", "day", parent.id)

    session.page.reload()
    activate_column(session.page, "day")  # D244: unfold the glued child before dragging it
    child_row = f'[data-goal-id="{child.id}"] > .goal-card__row'
    week_body = '[data-vertical="week"] .pattern-vertical-board__body'
    expect(session.page.locator(child_row)).to_be_visible()
    expect(session.page.locator(week_body)).to_be_visible()

    session.gestures.drag(child_row, week_body, source_position=GRIP, target_position=GRIP)

    with psycopg.connect(session.backend.dsn, autocommit=True) as conn:
        row = (parent.id, "day")
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            row = conn.execute(
                "SELECT parent_id, vertical FROM goals WHERE id = %s", (child.id,)
            ).fetchone()
            if row == (grandparent.id, "week"):
                break
            session.page.wait_for_timeout(100)
    assert row == (grandparent.id, "week"), f"D242: rightward split failed, got {row!r}"


def test_same_vertical_child_drag_right_without_grandparent_goes_top_level(
    ui_f2: UiSession,
) -> None:
    """D242's root case: the glued parent has no parent of its own, so the rightward split has
    no higher link to wire to — the child lands top-level in the target column."""
    session = ui_f2
    with psycopg.connect(session.backend.dsn, autocommit=True) as conn:
        parent = _create(conn, "SYN UI rootsplit parent", "day")
        child = _create(conn, "SYN UI rootsplit child", "day", parent.id)

    session.page.reload()
    activate_column(session.page, "day")  # D244: unfold the glued child before dragging it
    child_row = f'[data-goal-id="{child.id}"] > .goal-card__row'
    week_body = '[data-vertical="week"] .pattern-vertical-board__body'
    expect(session.page.locator(child_row)).to_be_visible()
    expect(session.page.locator(week_body)).to_be_visible()

    session.gestures.drag(child_row, week_body, source_position=GRIP, target_position=GRIP)

    with psycopg.connect(session.backend.dsn, autocommit=True) as conn:
        row = (parent.id, "day")
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            row = conn.execute(
                "SELECT parent_id, vertical FROM goals WHERE id = %s", (child.id,)
            ).fetchone()
            if row == (None, "week"):
                break
            session.page.wait_for_timeout(100)
    assert row == (None, "week"), f"D242: rootless rightward split failed, got {row!r}"


def test_child_title_click_transfers_inline_detail_host(ui_f2: UiSession) -> None:
    """D248: the child is now a real board GoalCard (D244's ordinary same-vertical nesting) — no
    parallel `#goal-detail` list survives to click into instead. Clicking the CHILD's own title,
    on its board-rendered card nested under the still-open parent, must transfer the inline host
    to the child: the parent's card loses `goal-card--detail-open`, the child's gains it, and the
    URL fragment follows (`store.openBoardGoal`'s own contract, same one every card-open click
    already uses)."""
    session = ui_f2
    with psycopg.connect(session.backend.dsn, autocommit=True) as conn:
        parent = _create(conn, "SYN UI open parent", "quarter")
        child = _create(conn, "SYN UI open child", "quarter", parent.id)
        goals.update(conn, owner="t1", ids=[child.id], body="SYN child body only")

    session.page.reload()
    session.gestures.activate_column(session.page, "quarter")
    parent_row = session.page.locator(f'[data-goal-id="{parent.id}"] > .goal-card__row')
    expect(parent_row).to_be_visible()
    parent_row.click()

    parent_host = session.page.locator(f'[data-goal-id="{parent.id}"].goal-card--detail-open')
    expect(parent_host).to_be_visible()

    child_title = session.page.locator(
        f'[data-goal-id="{parent.id}"] + .goal-card__children '
        f'[data-goal-id="{child.id}"] > .goal-card__row .goal-card__title'
    )
    expect(child_title).to_be_visible()
    child_title.click()

    child_host = session.page.locator(
        f'[data-goal-id="{child.id}"].goal-card--detail-open'
    )
    expect(child_host).to_be_visible(timeout=10000)
    expect(child_host.locator('#goal-detail [aria-label="Edit body"]')).to_contain_text(
        "SYN child body only"
    )
    assert session.page.locator(
        f'[data-goal-id="{parent.id}"].goal-card--detail-open'
    ).count() == 0
    assert session.page.url.endswith(f'#goal/{child.id}')
