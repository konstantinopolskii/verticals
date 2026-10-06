"""D245/D246 hand-model drag redesign (KK rulings 2026-08-18, docs/parity/DECISIONS.md).

D245 replaces the old detach flow (reparent -> reload -> reorder -> reload, which rendered the
same goal twice during the reconciliation window — the "primary bug") with a hand model: the
drag source stays MOUNTED at its original tree position for the whole gesture, made invisible
and `pointer-events:none` (nested sources additionally carry `goal-card--nested-drag-hole` and
do NOT collapse to height 0 — only a top-level source does, via `goal-card--source-gap-closed`).
The flying visual is a separate cloned overlay element carrying no `[data-goal-id]`. Landing is
atomic: the full final placement applies client-side in one frame via the optimistic placement
layer (`lib/boardPlacement.ts`), with the network write trailing invisibly behind it and board
fetches epoch-guarded (`lib/boardEpoch.ts`) against stale in-flight responses. Live change-feed
reloads (D237) DEFER while a gesture or its settle is in flight and flush once after
(`lib/liveBoard.ts`'s `createDeferredRun`).

D246's dwell-expand is retired: every column keeps its width for the whole
gesture, landing included. HD-5 pins that.

D247 originally added spring-loaded card open: holding the dragged card nearly still over a
card with FOLDED children unfolded them under the hand so dropping between them was one gesture.
D253 (KK, 2026-08-21) retires the fold this timer existed to open — every card's children render
by default now, compact column or not — so the spring timer itself is deleted from
`lib/dragHover.ts`; the gesture's surviving intent ("drop between two of another card's subtasks,
choosing the exact position") still works, now with no hold-still precondition at all, since
`lib/dragSlots.ts::resolveReorderSlot`'s own nested-group bands (D249) resolve straight off the
already-rendered children. HD-6 below is re-choreographed to that surviving shape; HD-6b (D247's
fold-back half) is retired outright — there is nothing left to fold back.

Six scenarios (HD-1..HD-6): nested pickup leaves a hole, never-two-copies through settle, instant
landing, live reloads deferring under a held gesture, steady column widths, and drop-between-
subtasks in a compact column. All drive a real Chromium against the real built bundle and real
Postgres/FastAPI, per this repo's E2E-only law (no mocks).
"""

from __future__ import annotations

import time
from collections.abc import Callable

import httpx
import psycopg
from playwright.sync_api import Page, expect

from tests.ui.conftest import EXPANDED_COLUMN_CLASS, UiSession, activate_column

# conftest.py's own PINNED_CLOCK_ISO date — every seeded goal below anchors here so it lands in
# whichever column the pinned clock renders as "current" for that vertical.
ANCHOR_ISO = "2026-08-08"

# test_s135_column_drop.py / test_v2_subgoals.py's own grip point: the row is
# checkbox|text|schedule-trigger on one flex line: only the middle strip (past the checkbox
# inset, above any meta line) is inert and safe to grab.
GRIP = {"x": 50, "y": 6}

# lib/drag.ts's own exported constants (TS is not importable from pytest, so these are pinned
# copies — a change to either source would need this file updated too, which is the point: it
# forces the test to be re-justified against the ruling, not silently drift).
DRAG_THRESHOLD_PX = 5  # arms a desktop drag on the very next pointermove past this many px,
# independent of DESKTOP_HOLD_MS's alternate hold-still arming path (task brief's own note).
SETTLE_MAX_MS = 550  # lib/drag.ts SETTLE_MAX_MS
SETTLE_GRACE_MS = 50  # lib/drag.ts SETTLE_GRACE_MS -- settle's outer bound is MAX+GRACE = 600ms.
COLUMN_DWELL_MS = 200  # the retired D246 dwell: HD-5 waits past it to show nothing widens


def _row(goal_id: str) -> str:
    return f'[data-goal-id="{goal_id}"] > .goal-card__row'


def _card(goal_id: str) -> str:
    return f'[data-goal-id="{goal_id}"]'


def _create_goal(
    session: UiSession,
    title: str,
    vertical: str,
    parent_id: str | None = None,
    color: str | None = None,
    anchor_date: str = ANCHOR_ISO,
) -> str:
    """Seed over the API (test-craft law: httpx + session.backend.token, never raw SQL inserts),
    exactly like test_compact_board.py's/test_live_updates.py's/test_s69's own seeding calls."""
    payload: dict[str, object] = {"title": title, "vertical": vertical, "anchor_date": anchor_date}
    if parent_id is not None:
        payload["parent_id"] = parent_id
    if color is not None:
        payload["color"] = color
    resp = httpx.post(
        f"{session.backend.base_url}/api/goals",
        json=payload,
        headers={"Authorization": f"Bearer {session.backend.token}"},
        timeout=10,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _goal_row(conn: psycopg.Connection, goal_id: str) -> tuple[str | None, str]:
    return conn.execute(
        "SELECT parent_id, vertical FROM goals WHERE id = %s", (goal_id,)
    ).fetchone()


def _press(page: Page, source_locator, position: dict[str, float] = GRIP) -> None:
    """pointer down, no move yet — mirrors gesture_counter.py's own `GestureCounter.drag()` up
    through its `mouse.down()` call, no further. Pair with a single subsequent move straight to
    the real target (`_move_to`/`_move_to_settled`), the same one-motion shape `.drag()` itself
    uses and D243's own gesture (test_v2_subgoals.py) is proven stable with. Do NOT insert a
    separate stationary arm-move before it for a gesture headed at a real drop target: measured,
    reproducibly (this suite's own HD-2/HD-3 iteration) — a stationary arm computes `drag.target`
    and captures `rowRects` against that arm point and can leave the board mid a resort-preview
    transition (D245's own "drop indicator previews destination") by the time the real target's
    box gets measured next, which is exactly the staleness `_move_to_settled` exists to absorb
    but performed measurably better here without ever introducing it in the first place. Use
    `_press_and_arm` instead for scenarios that need to inspect an armed-but-not-yet-travelling
    drag (HD-1/HD-4/HD-5's "do not release yet" assertions)."""
    box = source_locator.bounding_box()
    assert box is not None, "drag source has no live bounding box"
    sx = box["x"] + position["x"]
    sy = box["y"] + position["y"]
    page.mouse.move(sx, sy)
    page.mouse.down()


def _press_and_arm(page: Page, source_locator, position: dict[str, float] = GRIP) -> tuple[float, float]:
    """pointer down -> move past DRAG_THRESHOLD_PX -> armed, still held. gesture_counter.py's own
    down/move/up recipe minus the final up(), so callers can inspect mid-gesture DOM state or
    control the exact release moment (GestureCounter.drag() always ends in mouse.up(), which is
    unusable for HD-1/HD-4/HD-5's "do not release yet" assertions)."""
    box = source_locator.bounding_box()
    assert box is not None, "drag source has no live bounding box"
    sx = box["x"] + position["x"]
    sy = box["y"] + position["y"]
    page.mouse.move(sx, sy)
    page.mouse.down()
    ax, ay = sx + DRAG_THRESHOLD_PX + 15, sy  # comfortably past the 5px threshold, same row
    page.mouse.move(ax, ay, steps=4)
    return ax, ay


def _move_to(
    page: Page, target_locator, position: dict[str, float] = GRIP, steps: int = 5
) -> tuple[float, float]:
    box = target_locator.bounding_box()
    assert box is not None, "drag move target has no live bounding box"
    tx = box["x"] + position["x"]
    ty = box["y"] + position["y"]
    page.mouse.move(tx, ty, steps=steps)
    return tx, ty


def _move_to_settled(
    page: Page,
    locate: Callable[[], object],
    position: dict[str, float] | Callable[[dict], tuple[float, float]] = GRIP,
    timeout_ms: int = 2000,
) -> tuple[float, float]:
    """Same as `_move_to`, but for a target the drag source is not already sitting next to:
    `computeDropTarget`'s own drop-indicator is a live resort preview (D245: "the drop indicator
    previews destination") that transform-translates nearby siblings for the duration of a CSS
    transition while the pointer is still travelling toward it — measured directly (F2 fixture
    board, repeatable via `[data-goal-id] > .goal-card__row` rects logged mid-gesture): a target
    row can still be sliding when a single steps= move lands on it, so the coordinates it read
    are already stale by the time the pointerup handler consults them. Re-locate and re-aim every
    poll tick — the same repeated-measurement idea gesture_counter.py's cross-column
    `_drag_into_column` uses for its own live-strip walk — but require THREE consecutive matching
    reads (not two): a card mid-transition can coast through one 80ms tick within the 0.5px
    tolerance without actually having stopped, so one match is not proof of rest.

    `position` is either a fixed top-left offset dict (`_move_to`'s own convention) or a
    `box -> (tx, ty)` callback for targets measured from another edge (a column body's bottom
    gap, say) — the box's OWN width/height are only known once it is actually read."""
    resolve = position if callable(position) else (lambda box: (box["x"] + position["x"], box["y"] + position["y"]))
    previous: dict | None = None
    consecutive = 0
    deadline = time.monotonic() + timeout_ms / 1000
    tx = ty = 0.0
    while time.monotonic() < deadline:
        box = locate().bounding_box()
        assert box is not None, "drag move target has no live bounding box"
        tx, ty = resolve(box)
        page.mouse.move(tx, ty, steps=3)
        if previous is not None and all(abs(box[k] - previous[k]) < 0.5 for k in box):
            consecutive += 1
            if consecutive >= 3:
                return tx, ty
        else:
            consecutive = 0
        previous = box
        page.wait_for_timeout(80)
    return tx, ty


def _move_to_column_gap_settled(page: Page, vertical: str, timeout_ms: int = 2000) -> tuple[float, float]:
    """The empty gap below every card in a column: `nearestInsertionPoint`'s own append case
    (`drag.ts`) — pointer below every sibling's midpoint resolves `insertBeforeId: null`, which
    `slotParentId` reads as a top-level slot exactly like a named top-level card's outer-quarter
    band would (`slot?.parent_id` is null either way). Unlike aiming at one specific fixture
    card's narrow band, nothing below the last row can be displaced by the live resort-preview
    (D245) that made a fixed-card target flaky (`_move_to_settled`'s own docstring), so this
    reads the bottom-most row's rect fresh via evaluate — not a Playwright locator's box, since
    WHICH element is bottom-most, not just its position, can itself change between reads — and
    waits for three consecutive stable reads before returning."""
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


def _move_to_gap_settled(
    page: Page, id_a: str, id_b: str, timeout_ms: int = 2000
) -> tuple[float, float]:
    """The midpoint between two specific rows — `id_a` directly above `id_b` — settled the same
    way `_move_to_settled` settles a single target: re-read both rows' live boxes every poll tick
    and re-aim, since the live reorder-preview reflow (D245: "the drop indicator previews
    destination") can still be sliding either one while the pointer travels toward the midpoint a
    single earlier read computed. Three consecutive stable reads before returning, same law as
    every other settle helper in this file."""
    previous: tuple[float, float] | None = None
    consecutive = 0
    deadline = time.monotonic() + timeout_ms / 1000
    tx = ty = 0.0
    while time.monotonic() < deadline:
        box_a = page.locator(_row(id_a)).bounding_box()
        box_b = page.locator(_row(id_b)).bounding_box()
        assert box_a is not None and box_b is not None, "gap rows have no live bounding box"
        tx = box_a["x"] + 50
        ty = ((box_a["y"] + box_a["height"] / 2) + (box_b["y"] + box_b["height"] / 2)) / 2
        page.mouse.move(tx, ty, steps=3)
        current = (box_a["y"], box_b["y"])
        if previous is not None and all(abs(current[i] - previous[i]) < 0.5 for i in range(2)):
            consecutive += 1
            if consecutive >= 3:
                return tx, ty
        else:
            consecutive = 0
        previous = current
        page.wait_for_timeout(80)
    return tx, ty


def _has_class(locator, class_name: str) -> bool:
    return class_name in (locator.get_attribute("class") or "").split()


def _wait_for_class(page: Page, locator, class_name: str, timeout_ms: int) -> bool:
    deadline = time.monotonic() + timeout_ms / 1000
    while time.monotonic() < deadline:
        if _has_class(locator, class_name):
            return True
        page.wait_for_timeout(25)
    return _has_class(locator, class_name)


# --- HD-1 ------------------------------------------------------------------------------------


def test_hd1_nested_pickup_leaves_a_hole(ui_f2: UiSession) -> None:
    """D245: nested drag sources stay MOUNTED, invisible, pointer-events:none, carrying
    `goal-card--nested-drag-hole` — NOT the top-level `source-gap-closed` height:0 collapse
    (GoalCard.vue's `isNestedDragHole`/`closesSourceGap`, gated on `depth`). Picking a nested
    subtask up must not resize its parent's family block or move an untouched sibling row: that
    resize-on-pickup is exactly the pre-D245 regression ("nested subtask collapses, parent card
    snaps shut") this pins against. Escape then restores the row (App.vue's own cancel path)."""
    session = ui_f2
    page = session.page
    parent_id = _create_goal(session, "SYN HD1 parent", "quarter")
    s1_id = _create_goal(session, "SYN HD1 sub one", "quarter", parent_id=parent_id)
    s2_id = _create_goal(session, "SYN HD1 sub two", "quarter", parent_id=parent_id)

    page.reload()
    activate_column(page, "quarter")  # D244: same-column subtasks mount only once expanded
    expect(page.locator(_row(s2_id))).to_be_visible()

    # `.goal-card__children` is a DOM SIBLING of the parent's own [data-goal-id] KCard
    # (GoalCard.vue's template is a fragment: KCard, then an optional deck-edge div, then
    # children). The deck-edge only renders when `deckLines` is truthy, which is 0 once the
    # column is active (Column.vue's cardProps zeroes deckCount for an active column) — so with
    # the column already expanded here, children is KCard's direct next sibling. The whole
    # family's footprint, not the parent's own row box, is what a collapsing nested source used
    # to shrink.
    children_block = page.locator(f'{_card(parent_id)} + .goal-card__children')
    before_box = children_block.bounding_box()
    assert before_box is not None, "expanded parent must render its children block"
    s2_before = page.locator(_row(s2_id)).bounding_box()
    assert s2_before is not None

    _press_and_arm(page, page.locator(_row(s1_id)))
    try:
        assert page.locator(_card(s1_id)).count() == 1, (
            "D245: the dragged nested source must stay mounted exactly once, not vanish"
        )
        classes = (page.locator(_card(s1_id)).get_attribute("class") or "").split()
        assert "goal-card--nested-drag-hole" in classes, (
            f"D245: nested drag source missing goal-card--nested-drag-hole, got {classes!r}"
        )
        expect(page.locator(_row(s1_id))).to_be_hidden()

        after_box = children_block.bounding_box()
        assert after_box is not None
        assert abs(after_box["height"] - before_box["height"]) <= 1, (
            "D245: the family block resized on pickup — "
            f"{before_box['height']} -> {after_box['height']}"
        )
        s2_after = page.locator(_row(s2_id)).bounding_box()
        assert s2_after is not None
        assert abs(s2_after["y"] - s2_before["y"]) <= 1, (
            f"D245: an untouched sibling moved on pickup — y {s2_before['y']} -> {s2_after['y']}"
        )
    finally:
        page.keyboard.press("Escape")  # App.vue's onWindowKeyDown: cancel while pending/armed
        page.mouse.up()

    # Cancel-settle sits inside drag.ts's own SETTLE_MIN_MS..SETTLE_MAX_MS+SETTLE_GRACE_MS band
    # (330..600ms); wait out the whole documented band plus headroom rather than a fixed guess.
    expect(page.locator(_row(s1_id))).to_be_visible(timeout=SETTLE_MAX_MS + SETTLE_GRACE_MS + 1000)


# --- HD-2 / HD-3: shared D243 detach-to-grandparent recipe ------------------------------------


def _seed_detach_chain(session: UiSession) -> tuple[str, str, str]:
    """The exact D243 seed stolen from test_v2_subgoals.py's own
    test_same_vertical_child_drag_detaches_on_top_level_slot: a colored life value, a day-vertical
    parent glued to it, and a day-vertical child glued to the parent."""
    value_id = _create_goal(session, "SYN HD hand value", "life", color="#955be0")
    parent_id = _create_goal(session, "SYN HD hand parent", "day", parent_id=value_id)
    child_id = _create_goal(session, "SYN HD hand child", "day", parent_id=parent_id)
    return value_id, parent_id, child_id


def _run_detach_drag(page: Page, child_id: str) -> None:
    """D243's own top-level-slot recipe (test_v2_subgoals.py's
    test_same_vertical_child_drag_detaches_on_top_level_slot), retargeted at the EMPTY gap below
    every card in the day column instead of a specific fixture row's top-quarter band. Both reads
    as a top-level slot to `slotParentId` — an empty-gap drop resolves `insertBeforeId: null`
    (`drag.ts::nearestInsertionPoint`'s own "pointer below every sibling" case) exactly as a
    named top-level card's outer-quarter band does (`slot?.parent_id` null either way) — but
    landing below EVERY card, not beside one specific one, needs no per-card pixel margin and
    cannot be displaced by `computeDropTarget`'s own live resort-preview (D245: "the drop
    indicator previews destination"): nothing exists below the last row for a preview to push
    down. Measured directly: aiming at a specific fixture row's narrow top-quarter band (SYNCOL01
    at y=2 of a 24px row) was reproducibly flaky under this exact resort preview; the empty-gap
    target was not, across repeated runs."""
    _press(page, page.locator(_row(child_id)))
    _move_to_column_gap_settled(page, "day")


def test_hd2_never_two_copies_pickup_to_settle(ui_f2: UiSession) -> None:
    """D245: landing is atomic with NO interim board reloads — the old detach flow's
    reparent -> reload -> reorder -> reload window is what rendered the same goal twice (the
    "primary bug" this whole redesign exists to kill). Sampled every ~60ms (task's 50-100ms
    band) from before release through 1.5s after (comfortably past SETTLE_MAX_MS+
    SETTLE_GRACE_MS = 600ms): the dragged card's own [data-goal-id] must count exactly 1 at
    every sample — never 2 (a duplicate render), never 0 (an accidental unmount mid-flight)."""
    session = ui_f2
    page = session.page
    value_id, parent_id, child_id = _seed_detach_chain(session)
    page.reload()
    activate_column(page, "day")
    expect(page.locator(_row(child_id))).to_be_visible()
    expect(page.locator('[data-goal-id="SYNCOL01"] > .goal-card__row')).to_be_visible()

    _run_detach_drag(page, child_id)

    def _count() -> int:
        return page.locator(_card(child_id)).count()

    for _ in range(3):
        assert _count() == 1, "duplicate/missing card while still held, before release"
        page.wait_for_timeout(60)

    requests_before = len(session.request_log)
    page.mouse.up()

    deadline = time.monotonic() + 1.5
    while time.monotonic() < deadline:
        count = _count()
        assert count == 1, f"card rendered {count} times mid-settle, expected exactly 1"
        page.wait_for_timeout(60)

    with psycopg.connect(session.backend.dsn, autocommit=True) as conn:
        row = _goal_row(conn, child_id)
        deadline = time.monotonic() + 5
        while row[0] != value_id and time.monotonic() < deadline:
            page.wait_for_timeout(50)
            row = _goal_row(conn, child_id)
        assert row == (value_id, "day"), f"D243: expected climb to grandparent, got {row!r}"

    reparent_requests = [
        r for r in session.request_log[requests_before:]
        if f"/api/goals/{child_id}/parent" in r["url"]
    ]
    assert reparent_requests, "no reparent write was ever issued after release"


def test_hd3_landing_is_instant(ui_f2: UiSession) -> None:
    """D245: 'the client applies the full final placement in one frame via the optimistic
    placement layer' — checked with a SINGLE page.evaluate immediately after mouse.up(), no
    page.wait_for_*/expect() retry loop in between, since a retrying assertion could not tell a
    genuinely-delayed placement from an instant one. The write is then confirmed to land AFTER
    (request_log), and the placement is re-read once it does, to confirm it did not move."""
    session = ui_f2
    page = session.page
    value_id, parent_id, child_id = _seed_detach_chain(session)
    page.reload()
    activate_column(page, "day")
    expect(page.locator(_row(child_id))).to_be_visible()
    expect(page.locator('[data-goal-id="SYNCOL01"] > .goal-card__row')).to_be_visible()

    _run_detach_drag(page, child_id)
    requests_before = len(session.request_log)
    page.mouse.up()

    placement = page.evaluate(
        """({ childId, parentId }) => {
             const child = document.querySelector(`[data-goal-id="${childId}"]`)
             const nestedUnderOldParent = document.querySelector(
               `[data-goal-id="${parentId}"] .goal-card__children [data-goal-id="${childId}"]`
             )
             return {
               count: document.querySelectorAll(`[data-goal-id="${childId}"]`).length,
               nestedUnderOldParent: !!nestedUnderOldParent,
               parentAttr: child ? child.getAttribute('data-parent-id') : null,
             }
           }""",
        {"childId": child_id, "parentId": parent_id},
    )
    assert placement["count"] == 1, placement
    assert not placement["nestedUnderOldParent"], (
        f"D245: still nested under the old parent immediately after mouse.up(): {placement}"
    )
    assert placement["parentAttr"] == value_id, (
        f"D245: not already showing the final grandparent immediately after mouse.up(): {placement}"
    )

    deadline = time.monotonic() + 5
    reparent_requests: list[dict] = []
    while time.monotonic() < deadline:
        reparent_requests = [
            r for r in session.request_log[requests_before:]
            if f"/api/goals/{child_id}/parent" in r["url"]
        ]
        if reparent_requests:
            break
        page.wait_for_timeout(30)
    assert reparent_requests, "the reparent write never landed"
    assert reparent_requests[-1]["status"] == 200, reparent_requests[-1]

    settled_parent = page.evaluate(
        "id => document.querySelector(`[data-goal-id=\"${id}\"]`)?.getAttribute('data-parent-id')",
        child_id,
    )
    assert settled_parent == value_id, (
        f"D245: placement changed after the write landed — was {placement['parentAttr']!r}, "
        f"now {settled_parent!r}"
    )
    with psycopg.connect(session.backend.dsn, autocommit=True) as conn:
        assert _goal_row(conn, child_id) == (value_id, "day")


# --- HD-4 --------------------------------------------------------------------------------------


def test_hd4_live_reloads_defer_during_a_gesture(ui_f2: UiSession) -> None:
    """D245 supersedes D237's unconditional reload: 'live change-feed reloads DEFER while a
    gesture or its settle is in flight and flush once after.' `lib/liveBoard.ts`'s
    `createDeferredRun` gates on `state.drag.id || state.drag.settling`, so a cancel-via-Escape
    still counts as busy through its own settle window — the doorbell that rings mid-gesture
    must not land until well after Escape, not merely after the drag.id clears."""
    session = ui_f2
    page = session.page
    source_id = _create_goal(session, "SYN HD4 source", "day")
    page.reload()
    expect(page.locator(_row(source_id))).to_be_visible()
    page.evaluate("window.__hd4Marker = 'armed'")

    _press_and_arm(page, page.locator(_row(source_id)))
    new_id: str | None = None
    try:
        created = httpx.post(
            f"{session.backend.base_url}/api/goals",
            json={"title": "SYN HD4 doorbell", "vertical": "month", "anchor_date": ANCHOR_ISO},
            headers={"Authorization": f"Bearer {session.backend.token}"},
            timeout=10,
        )
        assert created.status_code == 201, created.text
        new_id = created.json()["id"]

        # liveUpdates.ts's own DEBOUNCE_MS (200ms) rings well inside this window; the point is
        # that a rung doorbell still does not apply while the gesture holds.
        page.wait_for_timeout(1500)
        assert page.locator(_card(new_id)).count() == 0, (
            "D245: a live reload landed while the drag was still held"
        )
        assert page.evaluate("window.__hd4Marker") == "armed", "the page reloaded mid-gesture"
    finally:
        page.keyboard.press("Escape")
        page.mouse.up()

    assert new_id is not None
    # 5s (task's own bound) comfortably covers the settle window (SETTLE_MAX_MS+SETTLE_GRACE_MS
    # = 600ms) plus a local fetch round trip for the deferred flush.
    expect(page.locator(_card(new_id))).to_be_visible(timeout=5000)


# --- HD-5 --------------------------------------------------------------------------------------


def test_hd5_columns_keep_their_width(ui_f2: UiSession) -> None:
    """Resting a drag over other columns, past the retired D246 dwell, widens none of them."""
    session = ui_f2
    page = session.page
    source_id = _create_goal(session, "SYN HD5 source", "day")
    page.reload()
    expect(page.locator(_row(source_id))).to_be_visible()

    columns = page.locator(".pattern-vertical-board__column")
    widths = [columns.nth(i).bounding_box()["width"] for i in range(columns.count())]

    _press_and_arm(page, page.locator(_row(source_id)))
    try:
        for vertical in ("month", "quarter"):
            body = page.locator(f'[data-vertical="{vertical}"] .pattern-vertical-board__body')
            _move_to(page, body, position={"x": 20, "y": 20}, steps=6)
            page.wait_for_timeout(COLUMN_DWELL_MS * 3)
            column = page.locator(f'.pattern-vertical-board__column[data-vertical="{vertical}"]')
            assert not _has_class(column, EXPANDED_COLUMN_CLASS), f"{vertical} widened under a drag"
        now = [columns.nth(i).bounding_box()["width"] for i in range(columns.count())]
        assert now == widths, f"column widths changed under a drag: {widths} -> {now}"
    finally:
        page.keyboard.press("Escape")
        page.mouse.up()


# --- HD-6 ----------------------------------------------------------------------------------------
#
# HD-6b ("flying away without dropping folds it back") is RETIRED by D253 (KK, 2026-08-21): a
# card's same-column children are never folded any more, so D247's spring timer — and the
# fold-back half of it HD-6b pinned — no longer exists. There is nothing left to restore on
# fly-away, so the scenario has no surviving intent to re-choreograph; it is deleted rather than
# kept as a stub.


def test_hd6_drop_between_subtasks(ui_f2: UiSession) -> None:
    """D253 re-choreography of D247's own scenario. Surviving intent, verbatim from the original
    docstring: "drop a card between another card's subtasks in a compact column, choosing the
    exact position, adopting it as that card's child in one gesture." What changed: D247's own
    mechanism for reaching that gesture — hold the dragged card nearly still over the parent for
    SPRING_OPEN_MS to unfold its folded children — is gone along with the fold itself. P's
    children (S1, S2) are already rendered in the DOM at rest, compact column or not (D253), so
    the drop resolves the moment the pointer sits in the reorder band between them — no still-hold
    wait required.

    WP-E FOUND, WP-F FIXED (docs/parity/DECISIONS.md; this test is the one that caught it,
    pre-D253): the old `pointerUpDrag` (web/src/lib/dragActions.ts) only consulted the resolved
    slot's own group owner (`target.parentId`) inside `if (sameVerticalParent)`. X here is a plain
    top-level card with no existing same-vertical parent, so `sameVerticalParent` was falsy, that
    whole block was skipped entirely, and the drop fell through to the bare `reorderWrite` —
    which `verticals/core/moves.py`'s own `move_between` never writes `parent_id` from, so X was
    never adopted. The fix, still in place: `target.parentId` is consulted unconditionally (both
    for a nested source and a top-level one), and `adoptIntoSlot(id, parentId, target)` in
    dragActions.ts — `detachToSlot`'s mirror image, same D245 atomic shape — applies
    `reparentPlacement` synchronously first, computes `reorderWrite` off the already-updated board
    (the sibling group is now the new parent's children), applies `reorderPlacement`, then fires
    `apiReparentGoal` and `patchGoal` in order behind the landed picture — so X lands adopted AND
    ordered between S1 and S2 in one gesture. The landing no longer widens the column (D253's
    expand, dropped with D246): the assertion below pins that.

    Measured (this rewrite's own first pass): a single pre-computed midpoint, moved to in one
    big jump straight from X's own row, is NOT enough on its own — the same live reorder-preview
    reflow `_move_to_settled` exists for shifts S1/S2 while the pointer is still travelling across
    the intervening rows (P's own row included), so the coordinates read before the move are
    already stale by the time the pointer arrives. `_move_to_gap_settled` fixes this the same way
    every other settle helper here does: re-read and re-aim every poll tick until three
    consecutive reads agree."""
    session = ui_f2
    page = session.page
    parent_id = _create_goal(session, "SYN HD6 parent", "quarter")
    s1_id = _create_goal(session, "SYN HD6 sub one", "quarter", parent_id=parent_id)
    s2_id = _create_goal(session, "SYN HD6 sub two", "quarter", parent_id=parent_id)
    x_id = _create_goal(session, "SYN HD6 mover", "quarter")

    page.reload()
    quarter = page.locator('.pattern-vertical-board__column[data-vertical="quarter"]')
    expect(page.locator(_row(x_id))).to_be_visible()
    expect(page.locator(_row(parent_id))).to_be_visible()
    expect(page.locator(_row(s1_id))).to_be_visible()
    expect(page.locator(_row(s2_id))).to_be_visible()
    assert not _has_class(quarter, EXPANDED_COLUMN_CLASS)

    _press_and_arm(page, page.locator(_row(x_id)))
    try:
        _move_to_gap_settled(page, s1_id, s2_id)
        page.wait_for_timeout(100)
        page.mouse.up()
    except BaseException:
        page.keyboard.press("Escape")
        page.mouse.up()
        raise

    page.wait_for_timeout(SETTLE_MAX_MS + SETTLE_GRACE_MS)
    assert not _has_class(quarter, EXPANDED_COLUMN_CLASS), "a drop inside a card widened its column"

    with psycopg.connect(session.backend.dsn, autocommit=True) as conn:
        row = _goal_row(conn, x_id)
        deadline = time.monotonic() + 5
        while row[0] != parent_id and time.monotonic() < deadline:
            page.wait_for_timeout(50)
            row = _goal_row(conn, x_id)
        assert row[0] == parent_id, (
            "dropping between P's subtasks must adopt X as P's child — "
            f"got parent_id={row[0]!r} (X's own reorderWrite never touches parent_id if this "
            "falls through to the plain reorder branch; see dragActions.ts pointerUpDrag)"
        )
        # The reparent and reorder are two sequential writes behind the same landed placement
        # (adoptIntoSlot's own D245 shape) — give the second one the same deadline as the first
        # rather than reading `ordered` the instant the reparent alone has landed.
        ordered: list[str] = []
        deadline = time.monotonic() + 5
        while ordered != [s1_id, x_id, s2_id] and time.monotonic() < deadline:
            page.wait_for_timeout(50)
            ordered = [
                r[0] for r in conn.execute(
                    "SELECT id FROM goals WHERE parent_id = %s ORDER BY position", (parent_id,)
                ).fetchall()
            ]
        assert ordered == [s1_id, x_id, s2_id], (
            f"X must land ordered between S1 and S2, got {ordered!r}"
        )
