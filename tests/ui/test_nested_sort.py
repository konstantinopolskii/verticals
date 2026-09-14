"""D249 — nested subtasks under a same-vertical parent must sort freely inside their own group.

KK (2026-08-19), the confirmed defect this file exists to close: "The key issue with the
sub-tasks under the parent in the same vertical is that you can't drag and sort them inside."

Root cause (`lib/drag.ts` before this fix): `computeDropTarget` resolved a reorder slot against
the column's own FLAT top-level candidate list only, then re-INFERRED which group the resolved
`insertBeforeId` belonged to after the fact (the now-deleted `slotParentId`), whose own doc
comment declared "an append slot is always top-level". Hovering below the LAST rendered member of
a nested group had no valid slot inside that group under that law — the drop resolved top-level
instead and detached the card. `lib/dragSlots.ts::resolveReorderSlot` (D249) fixes this by
deciding group ownership and position TOGETHER, at resolution time, checking every rendered
nested group's own band (extended past its last child to the next rendered row) before falling
back to the column's own top level — so a nested group's append slot is now a first-class target
exactly like any other position in that group.

Coverage strategy — bounded, not a literal N-source x N-target cross product: a literal matrix
for a 4-member group is 4 sources x 4 target positions, each a full press/drag/settle/DB-poll
gesture; that many real browser gestures per group size, times three group sizes, is a lot of
wall-clock for marginal extra confidence once the underlying resolver is a pure function of
(board, pointer Y, row rects) exercised by a handful of representative pointer positions. Instead:

  * Size 1 gets its own dedicated no-op test (`reorderWrite`'s "only member of its own group:
    nowhere to move to" rule, plus `resolveReorderSlot` matching the group ONLY to itself).
  * Sizes 2 and 4 each get a bounded ROTATION matrix (`test_nested_group_rotation_matrix`):
    Phase A drags the current FIRST child to the group's own APPEND slot, `size` times in a row
    -- a left-rotation-by-one repeated `size` times, which cycles back to the seed order and, by
    construction, drags every single child into the append slot exactly once (the specific
    previously-broken case). Phase B drags the current LAST child to the FIRST position, `size`
    times -- a right-rotation-by-one, exercising a real-id `insertBeforeId` (not append) for
    every child. DB order, DOM order and `parent_id` (unchanged throughout -- every move stays
    inside the same group) are asserted after EVERY individual drag, not just at the end.
  * A representative case (`test_open_card_render_path_also_sorts`) proves the SAME machinery
    also works when the parent is rendered via D248's open-card path rather than merely an
    expanded column -- `Column.vue`'s `cardProps` makes an open card's own column active
    regardless of the header toggle, so its children render the same way either path reaches.
  * `test_indicator_location_nested_vs_top_level` and `test_adopt_into_group_append_slot` and
    `test_combine_band_narrows_for_same_group_siblings` each cover one specific piece of the
    design the rotation matrix does not touch directly: where the drop indicator renders, that a
    TOP-LEVEL card dropped on a group's append slot gets adopted there (not just a same-group
    sibling reordering within it), and the D236 combine-band refinement.

Helpers below are a duplicated, adapted copy of `test_open_card_drag.py`/`test_hand_drag.py`'s
own -- this package's established convention (those two files' own header comments), not an
oversight.
"""

from __future__ import annotations

import time
from collections.abc import Callable

import httpx
import psycopg
import pytest
from playwright.sync_api import Page, expect

from tests.ui.conftest import UiSession, activate_column

# conftest.py's own PINNED_CLOCK_ISO date -- matches test_hand_drag.py/test_open_card_drag.py's
# own anchor exactly, so a goal anchored here lands in whichever column the pinned clock renders
# as "current" for its vertical (the initially-loaded board, no reload needed).
ANCHOR_ISO = "2026-08-08"

GRIP = {"x": 50, "y": 6}


def _create_goal(
    session: UiSession,
    title: str,
    vertical: str,
    parent_id: str | None = None,
    anchor_date: str = ANCHOR_ISO,
) -> str:
    """Duplicated from `test_open_card_drag.py`'s own -- this package's established convention
    (that file's own header comment), not an oversight."""
    payload: dict[str, object] = {"title": title, "vertical": vertical, "anchor_date": anchor_date}
    if parent_id is not None:
        payload["parent_id"] = parent_id
    resp = httpx.post(
        f"{session.backend.base_url}/api/goals",
        json=payload,
        headers={"Authorization": f"Bearer {session.backend.token}"},
        timeout=10,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _row(goal_id: str) -> str:
    return f'[data-goal-id="{goal_id}"] > .goal-card__row'


def _card(goal_id: str) -> str:
    return f'[data-goal-id="{goal_id}"]'


def _goal_row(conn: psycopg.Connection, goal_id: str) -> tuple[str | None, str | None]:
    return conn.execute(
        "SELECT parent_id, vertical FROM goals WHERE id = %s", (goal_id,)
    ).fetchone()


def _children_order(conn: psycopg.Connection, parent_id: str) -> list[str]:
    return [
        r[0] for r in conn.execute(
            "SELECT id FROM goals WHERE parent_id = %s ORDER BY position", (parent_id,)
        ).fetchall()
    ]


def _dom_children_order(page: Page, parent_id: str) -> list[str]:
    return page.locator(
        f'{_card(parent_id)} + .goal-card__children > [data-goal-id]'
    ).evaluate_all("els => els.map(e => e.dataset.goalId)")


def _press(page: Page, source_locator, position: dict[str, float] = GRIP) -> None:
    """See test_hand_drag.py's own `_press` docstring for why this is a single down-then-move
    gesture rather than a separate stationary arm-move before travelling to a real target."""
    box = source_locator.bounding_box()
    assert box is not None, "drag source has no live bounding box"
    sx = box["x"] + position["x"]
    sy = box["y"] + position["y"]
    page.mouse.move(sx, sy)
    page.mouse.down()


def _move_to_row_once(
    page: Page,
    locate: Callable[[], object],
    position: dict[str, float] | Callable[[dict], tuple[float, float]] = GRIP,
    steps: int = 6,
    settle_ms: int = 500,
) -> tuple[float, float]:
    """A SAME-GROUP nested target needs the opposite recipe from `test_hand_drag.py`'s own
    `_move_to_settled` (re-locate/re-aim every poll tick): that helper is correct for a
    TOP-LEVEL target because a top-level source always collapses (`closesSourceGap`), so the
    live resort preview's indicator height is exactly cancelled and every other row's position
    stays stable -- chasing the live box converges. A nested source never collapses (D245's own
    `test_hd1_nested_pickup_leaves_a_hole`), so inserting/moving the nested indicator ADDS a full
    row with nothing compensating it; re-locating and re-aiming at a same-group sibling's LIVE
    box on every poll chases that self-inflicted shift and can converge on the wrong candidate or
    never settle cleanly (confirmed empirically: `resolveReorderSlot`'s own band/candidate math
    is stable and correct given whatever `pointerY` it receives -- the wrong values were coming
    from this exact chase, not from the resolver). `resolveReorderSlot` only ever consults
    press-time-frozen row rects (`lib/drag.ts::captureRowRects`, called once from
    `armPointerDown` on `mousedown`, this file's own D249 header) -- so the correct mirror is to
    read the target's box ONCE, at the SAME pre-drag instant that freeze happens (right after
    `_press`'s own `mouse.down()`, before any travel toward the target could shift anything),
    make one decisive move, then just wait for the DOM to catch up without moving the mouse
    again -- exactly what a real user's own un-programmatic cursor does."""
    resolve = position if callable(position) else (lambda box: (box["x"] + position["x"], box["y"] + position["y"]))
    box = locate().bounding_box()
    assert box is not None, "drag move target has no live bounding box"
    tx, ty = resolve(box)
    page.mouse.move(tx, ty, steps=steps)
    page.wait_for_timeout(settle_ms)
    return tx, ty


def _move_to_column_gap_settled(page: Page, vertical: str, timeout_ms: int = 2000) -> tuple[float, float]:
    """test_hand_drag.py's own empty-gap target: below every card in a column, immune to the live
    resort preview a specific fixture row's narrow band would be displaced by."""
    previous: tuple[float, float, float] | None = None
    consecutive = 0
    deadline = time.monotonic() + timeout_ms / 1000
    tx = ty = 0.0
    while time.monotonic() < deadline:
        info = page.evaluate(
            """vertical => {
                 const column = document.querySelector(
                   `.pattern-vertical-board__column[data-vertical="${vertical}"]`
                 )
                 if (!column) return null
                 const colRect = column.getBoundingClientRect()
                 const rows = [...column.querySelectorAll('[data-goal-id] > .goal-card__row')]
                 const bottoms = rows.map(r => r.getBoundingClientRect().bottom)
                 const lastBottom = bottoms.length ? Math.max(...bottoms) : colRect.top + 40
                 return { x: colRect.left + colRect.width / 2, bottom: lastBottom }
               }""",
            vertical,
        )
        assert info is not None, f"column {vertical!r} not found"
        tx = info["x"]
        ty = info["bottom"] + 16
        page.mouse.move(tx, ty, steps=3)
        current = (info["x"], info["bottom"], ty)
        if previous is not None and all(abs(current[i] - previous[i]) < 0.5 for i in range(3)):
            consecutive += 1
            if consecutive >= 3:
                return tx, ty
        else:
            consecutive = 0
        previous = current
        page.wait_for_timeout(80)
    return tx, ty


_APPEND_SLOT_SCRIPT = """parentId => {
    const block = document.querySelector(`[data-goal-id="${parentId}"] + .goal-card__children`)
    if (!block) return null
    const ownCards = [...block.querySelectorAll(':scope > [data-goal-id]')]
    const ownRows = ownCards
      .map(card => card.querySelector(':scope > .goal-card__row'))
      .filter(Boolean)
    if (!ownRows.length) return null
    const ownIds = new Set(ownCards.map(card => card.dataset.goalId))
    const bottom = Math.max(...ownRows.map(row => row.getBoundingClientRect().bottom))
    const column = block.closest('.pattern-vertical-board__column') || document
    const allRows = [...column.querySelectorAll('[data-goal-id] > .goal-card__row')]
    let nextTop = Infinity
    for (const row of allRows) {
      const card = row.closest('[data-goal-id]')
      const id = card ? card.dataset.goalId : null
      if (!id || ownIds.has(id) || id === parentId) continue
      const rect = row.getBoundingClientRect()
      if (rect.top >= bottom && rect.top < nextTop) nextTop = rect.top
    }
    const extendedBottom = nextTop === Infinity ? bottom + 24 : (bottom + nextTop) / 2
    const blockRect = block.getBoundingClientRect()
    return { x: blockRect.left + blockRect.width / 2, y: (bottom + extendedBottom) / 2 }
  }"""


def _move_to_group_append_once(
    page: Page, parent_id: str, steps: int = 6, settle_ms: int = 500
) -> tuple[float, float]:
    """The group's own append slot (D249): past the bottom of every rendered child of
    `parent_id`, extended to the midpoint before whatever rendered row comes next in the SAME
    column -- `lib/dragSlots.ts::extendBandBottom`'s own geometry, replayed here in JS so the
    aimed-at point always lands inside the intended band regardless of how tight
    `goalCard.css`'s 2px row-gap makes it. Read ONCE, right after `_press` -- see
    `_move_to_row_once`'s own docstring for why a same-group nested target must be read once
    against the pre-drag static layout rather than re-located/re-aimed on every poll tick."""
    info = page.evaluate(_APPEND_SLOT_SCRIPT, parent_id)
    assert info is not None, f"parent {parent_id!r} has no rendered children block"
    tx, ty = info["x"], info["y"]
    page.mouse.move(tx, ty, steps=steps)
    page.wait_for_timeout(settle_ms)
    return tx, ty


def _assert_settled(session: UiSession, parent_id: str, expected: list[str], timeout: float = 5.0) -> None:
    page = session.page
    with psycopg.connect(session.backend.dsn, autocommit=True) as conn:
        deadline = time.monotonic() + timeout
        db_order = _children_order(conn, parent_id)
        while db_order != expected and time.monotonic() < deadline:
            page.wait_for_timeout(50)
            db_order = _children_order(conn, parent_id)
        assert db_order == expected, f"DB order mismatch under {parent_id!r}: got {db_order!r}, want {expected!r}"

    deadline = time.monotonic() + timeout
    dom_order = _dom_children_order(page, parent_id)
    while dom_order != expected and time.monotonic() < deadline:
        page.wait_for_timeout(50)
        dom_order = _dom_children_order(page, parent_id)
    assert dom_order == expected, f"DOM order mismatch under {parent_id!r}: got {dom_order!r}, want {expected!r}"
    # DOM/DB order already match above; drain the 200ms FLIP settle animation GoalCard.vue's own
    # `nestedInsertionSlot` watch still has in flight so the NEXT `_press` in the same test always
    # starts from a fully at-rest board, never a still-sliding one.
    page.wait_for_timeout(300)


def _assert_parent_unchanged(session: UiSession, goal_id: str, parent_id: str) -> None:
    with psycopg.connect(session.backend.dsn, autocommit=True) as conn:
        row = _goal_row(conn, goal_id)
    assert row is not None and row[0] == parent_id, (
        f"{goal_id!r} must stay under {parent_id!r} for the whole drag, got parent {row!r}"
    )


def _drag_row_to_append(session: UiSession, parent_id: str, moving_id: str) -> None:
    page = session.page
    _press(page, page.locator(_row(moving_id)))
    _move_to_group_append_once(page, parent_id)
    page.wait_for_timeout(100)
    page.mouse.up()


def _drag_row_to_before(session: UiSession, moving_id: str, before_id: str) -> None:
    page = session.page
    _press(page, page.locator(_row(moving_id)))
    _move_to_row_once(
        page,
        lambda: page.locator(_row(before_id)),
        position=lambda box: (box["x"] + 50, box["y"] + box["height"] * 0.15),
    )
    page.wait_for_timeout(100)
    page.mouse.up()


def _is_combine_target(page: Page, goal_id: str) -> bool:
    return page.locator(f'[data-goal-id="{goal_id}"] > .goal-card__row[data-dnd-combine-target]').count() == 1


# --- size 1: the no-op ---------------------------------------------------------------------


def test_size1_group_drag_is_a_noop(ui_f2: UiSession) -> None:
    """A group of exactly one subtask has nowhere else to go inside its own group --
    `resolveReorderSlot` matches the group's own single child against ITSELF (excluded from its
    own candidate list) and produces `insertBeforeId: null` under the SAME parent; `reorderWrite`
    then reads zero other siblings ("only member of its own group: nowhere to move to") and
    returns null, so `pointerUpDrag` never issues a write at all. Confirmed here by DB row
    identity (parent_id AND position both byte-identical before/after) and by the network log:
    zero new requests to this goal's own PATCH endpoint."""
    session = ui_f2
    page = session.page
    p_id = _create_goal(session, "SYN NS solo parent", "quarter")
    s1_id = _create_goal(session, "SYN NS solo child", "quarter", parent_id=p_id)

    page.reload()
    activate_column(page, "quarter")
    expect(page.locator(_row(s1_id))).to_be_visible()

    with psycopg.connect(session.backend.dsn, autocommit=True) as conn:
        before = conn.execute(
            "SELECT parent_id, position FROM goals WHERE id = %s", (s1_id,)
        ).fetchone()

    requests_before = len(session.request_log)
    _drag_row_to_append(session, p_id, s1_id)
    page.wait_for_timeout(300)

    with psycopg.connect(session.backend.dsn, autocommit=True) as conn:
        after = conn.execute(
            "SELECT parent_id, position FROM goals WHERE id = %s", (s1_id,)
        ).fetchone()
    assert after == before, f"a size-1 group's only child must be a true no-op, got {before!r} -> {after!r}"

    patch_requests = [
        r for r in session.request_log[requests_before:]
        if r["method"] == "PATCH" and f"/api/goals/{s1_id}" in r["url"]
    ]
    assert not patch_requests, f"a size-1 group drag must issue no network write, got {patch_requests!r}"
    assert page.locator(_card(s1_id)).count() == 1, "no duplicate/missing card after the no-op"


# --- sizes 2 and 4: rotation matrix ----------------------------------------------------------


@pytest.mark.parametrize("size", [2, 4])
def test_nested_group_rotation_matrix(ui_f2: UiSession, size: int) -> None:
    """See this file's own module docstring for the rotation methodology. Both phases stay
    entirely inside the same group (`_assert_parent_unchanged` after every single drag) and both
    end by re-confirming the seed order -- a correctness check that falls out of the rotation
    shape for free."""
    session = ui_f2
    page = session.page
    p_id = _create_goal(session, f"SYN NS rot{size} parent", "quarter")
    child_ids = [
        _create_goal(session, f"SYN NS rot{size} child {i}", "quarter", parent_id=p_id)
        for i in range(size)
    ]

    page.reload()
    activate_column(page, "quarter")
    for cid in child_ids:
        expect(page.locator(_row(cid))).to_be_visible()

    with psycopg.connect(session.backend.dsn, autocommit=True) as conn:
        seed_order = _children_order(conn, p_id)
    assert seed_order == child_ids, f"seed order must match creation order: {seed_order!r}"

    # Phase A: append rotation -- every child dragged into the group's own append slot once.
    order = list(child_ids)
    for _ in range(size):
        moving = order[0]
        _drag_row_to_append(session, p_id, moving)
        order = order[1:] + [moving]
        _assert_settled(session, p_id, order)
        _assert_parent_unchanged(session, moving, p_id)
    assert order == child_ids, f"append rotation must cycle back to the seed order, got {order!r}"

    # Phase B: prepend rotation -- every child dragged to the front once (a real-id
    # `insertBeforeId`, not append).
    order = list(child_ids)
    for _ in range(size):
        moving = order[-1]
        before = order[0]
        _drag_row_to_before(session, moving, before)
        order = [moving] + order[:-1]
        _assert_settled(session, p_id, order)
        _assert_parent_unchanged(session, moving, p_id)
    assert order == child_ids, f"prepend rotation must cycle back to the seed order, got {order!r}"


# --- open-card render path (D248) --------------------------------------------------------------


def test_open_card_render_path_also_sorts(ui_f2: UiSession) -> None:
    """The same `resolveReorderSlot` machinery, reached via D248's open-card path rather than
    merely an expanded column -- `Column.vue`'s `cardProps` makes an open card's own column
    active regardless of the header toggle, so nothing about how the children got rendered
    should matter to `lib/dragSlots.ts`, which only ever reads press-time row rects and the board
    payload. One representative append-rotation drag, parent already open (`#goal-detail`
    mounted inside the dragged siblings' own ancestor subtree, `test_od3`'s own setup)."""
    session = ui_f2
    page = session.page
    p_id = _create_goal(session, "SYN NS open parent", "quarter")
    s1_id = _create_goal(session, "SYN NS open sub one", "quarter", parent_id=p_id)
    s2_id = _create_goal(session, "SYN NS open sub two", "quarter", parent_id=p_id)

    page.reload()
    activate_column(page, "quarter")
    page.locator(f'{_card(p_id)} > .goal-card__row .goal-card__title').click()
    expect(page.locator(f'{_card(p_id)}.goal-card--detail-open')).to_be_visible()
    expect(page.locator('#goal-detail .goal-detail__loading')).to_have_count(0)
    page.wait_for_timeout(120)
    expect(page.locator(_row(s2_id))).to_be_visible()

    _drag_row_to_append(session, p_id, s1_id)
    _assert_settled(session, p_id, [s2_id, s1_id])
    _assert_parent_unchanged(session, s1_id, p_id)
    expect(page.locator(f'{_card(p_id)}.goal-card--detail-open')).to_be_visible()


# --- indicator location --------------------------------------------------------------------


def test_indicator_location_nested_vs_top_level(ui_f2: UiSession) -> None:
    """The nested drop indicator renders inside the group's OWN `.goal-card__children` list
    (`GoalCard.vue`, mirroring `Column.vue`'s own indicator markup byte-for-byte) exactly when
    the resolved slot belongs to that card's own group; a top-level slot's indicator renders in
    the column's own track, never inside any card's children list. Before D249 there was no
    nested indicator at all -- a same-group drag gave no visual feedback whatsoever."""
    session = ui_f2
    page = session.page
    p_id = _create_goal(session, "SYN NS indicator parent", "quarter")
    s1_id = _create_goal(session, "SYN NS indicator sub one", "quarter", parent_id=p_id)
    s2_id = _create_goal(session, "SYN NS indicator sub two", "quarter", parent_id=p_id)
    t_id = _create_goal(session, "SYN NS indicator top", "quarter")

    page.reload()
    activate_column(page, "quarter")
    for gid in (s1_id, s2_id, t_id):
        expect(page.locator(_row(gid))).to_be_visible()

    # Nested: drag S1 to the group's append slot (below S2) -- the previously-broken slot.
    _press(page, page.locator(_row(s1_id)))
    _move_to_group_append_once(page, p_id)
    page.wait_for_timeout(150)
    assert page.locator('[data-dnd-placeholder]').count() == 1, "exactly one indicator while held"
    assert page.locator(
        f'{_card(p_id)} + .goal-card__children [data-dnd-placeholder]'
    ).count() == 1, "nested slot's indicator must render inside the group's own children list"
    page.wait_for_timeout(80)
    page.mouse.up()
    _assert_settled(session, p_id, [s2_id, s1_id])

    # Top-level: drag T to the empty gap below everything in the column -- an ordinary top-level
    # slot; its indicator must NOT be inside any card's children list.
    _press(page, page.locator(_row(t_id)))
    _move_to_column_gap_settled(page, "quarter")
    page.wait_for_timeout(150)
    assert page.locator('[data-dnd-placeholder]').count() == 1, "exactly one indicator while held"
    inside_children = page.evaluate(
        "() => { const el = document.querySelector('[data-dnd-placeholder]'); "
        "return !!el && !!el.closest('.goal-card__children') }"
    )
    assert not inside_children, "a top-level slot's indicator must not render inside a children list"
    page.wait_for_timeout(80)
    page.mouse.up()


# --- adopt at the group's own append slot -----------------------------------------------------


def test_adopt_into_group_append_slot(ui_f2: UiSession) -> None:
    """D247's `adoptIntoSlot`, extended to a group's OWN append slot (D249) -- the confirmed
    defect `dragActions.ts`'s own WP-E comment names: a plain TOP-LEVEL card dropped below
    another card's LAST nested subtask used to read as a top-level slot under the old "append is
    always top-level" law and fall straight through to a bare reorder, never adopting it.
    Extends OD-2's own between-S1-and-S2 adopt-at-slot coverage to the LAST position
    specifically."""
    session = ui_f2
    page = session.page
    p_id = _create_goal(session, "SYN NS adopt parent", "quarter")
    s1_id = _create_goal(session, "SYN NS adopt sub one", "quarter", parent_id=p_id)
    s2_id = _create_goal(session, "SYN NS adopt sub two", "quarter", parent_id=p_id)
    x_id = _create_goal(session, "SYN NS adopt mover", "quarter")

    page.reload()
    activate_column(page, "quarter")
    for gid in (s1_id, s2_id, x_id):
        expect(page.locator(_row(gid))).to_be_visible()

    _press(page, page.locator(_row(x_id)))
    _move_to_group_append_once(page, p_id)
    page.wait_for_timeout(100)
    page.mouse.up()

    with psycopg.connect(session.backend.dsn, autocommit=True) as conn:
        deadline = time.monotonic() + 5
        row = _goal_row(conn, x_id)
        while (row is None or row[0] != p_id) and time.monotonic() < deadline:
            page.wait_for_timeout(50)
            row = _goal_row(conn, x_id)
        assert row is not None and row[0] == p_id, (
            f"D249: X must be adopted at the group's append slot, got {row!r}"
        )

    _assert_settled(session, p_id, [s1_id, s2_id, x_id])
    is_nested = page.evaluate(
        "id => { const el = document.querySelector(`[data-goal-id=\"${id}\"]`); "
        "return !!el && !!el.closest('.goal-card__children') }",
        x_id,
    )
    assert is_nested, "X must render nested inside a children list once adopted, not top-level"


# --- D236 combine-band refinement -----------------------------------------------------------


def test_combine_band_narrows_for_same_group_siblings(ui_f2: UiSession) -> None:
    """D236 refinement (this task): the centre combine band for a drag hovering ANOTHER card
    narrows from 50% of that card's row height to 25% when the hit card is a rendered SIBLING of
    the dragged card in the same group (`lib/drag.ts::computeDropTarget`'s `bandFraction`, 0.25
    -> 0.375 measured from each edge -- band height = `height * (1 - 2*bandFraction)`). A small
    sibling subtask row left the old 50% band covering nearly the whole row, making an ordinary
    same-group reorder drag land on 'combine' almost by accident. Checked two ways against the
    SAME pair of same-group siblings: a pointer at 30% of the hit row's own height (inside the
    OLD 50% band [25%, 75%], outside the NEW 25% one [37.5%, 62.5%]) must not combine; dead
    centre (50%) must still combine."""
    session = ui_f2
    page = session.page
    p_id = _create_goal(session, "SYN NS band parent", "quarter")
    s1_id = _create_goal(session, "SYN NS band sub one", "quarter", parent_id=p_id)
    s2_id = _create_goal(session, "SYN NS band sub two", "quarter", parent_id=p_id)

    page.reload()
    activate_column(page, "quarter")
    expect(page.locator(_row(s1_id))).to_be_visible()
    expect(page.locator(_row(s2_id))).to_be_visible()

    _press(page, page.locator(_row(s1_id)))
    _move_to_row_once(
        page,
        lambda: page.locator(_row(s2_id)),
        position=lambda box: (box["x"] + 50, box["y"] + box["height"] * 0.30),
    )
    page.wait_for_timeout(120)
    narrowed = _is_combine_target(page, s2_id)
    page.mouse.up()
    assert not narrowed, "30%-height hover over a same-group sibling must not combine (D236 refinement)"

    with psycopg.connect(session.backend.dsn, autocommit=True) as conn:
        deadline = time.monotonic() + 5
        after_reorder = _goal_row(conn, s1_id)
        while after_reorder is None and time.monotonic() < deadline:
            page.wait_for_timeout(50)
            after_reorder = _goal_row(conn, s1_id)
    assert after_reorder is not None and after_reorder[0] == p_id, (
        "the 30%-height drop must still land as an ordinary same-group reorder, not a detach"
    )
    # This first drop was itself a no-op (S1 was already right before S2, HD-1's own no-op rule
    # renders no indicator for it) -- `releasePointerDrag` still starts a real settle/flying-card
    # overlay animation regardless (`lib/drag.ts::settleDuration`, floor SETTLE_MIN_MS=330ms plus
    # SETTLE_GRACE_MS=50ms with zero travel distance), and that overlay sits on top of S1's own
    # row with pointer-events enabled for its whole duration. Pressing S1 again before it clears
    # lands the next `mousedown` on the overlay instead of the real row -- `armPointerDown` never
    # fires, so gesture 2 silently never arms (confirmed via `DEBUG_ARM`/`DEBUG_TRACK` console
    # instrumentation during this fix: gesture 2 had zero drag-state calls at all). Drain the full
    # settle window before starting the second gesture.
    page.wait_for_timeout(600)

    _press(page, page.locator(_row(s1_id)))
    _move_to_row_once(
        page,
        lambda: page.locator(_row(s2_id)),
        position=lambda box: (box["x"] + 50, box["y"] + box["height"] * 0.50),
    )
    page.wait_for_timeout(120)
    centred = _is_combine_target(page, s2_id)
    page.mouse.up()
    assert centred, "dead-centre hover over a same-group sibling must still combine"

    with psycopg.connect(session.backend.dsn, autocommit=True) as conn:
        deadline = time.monotonic() + 5
        combined = _goal_row(conn, s1_id)
        while (combined is None or combined[0] != s2_id) and time.monotonic() < deadline:
            page.wait_for_timeout(50)
            combined = _goal_row(conn, s1_id)
        assert combined is not None and combined[0] == s2_id, (
            f"dead-centre combine must actually nest S1 under S2, got {combined!r}"
        )

