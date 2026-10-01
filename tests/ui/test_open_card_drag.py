"""D248 — hand-model invariants with a card open; the coverage hole that let the two-render-world
bug ship.

D245-D247's hand model (`test_hand_drag.py`'s own docstring) measures the drag machinery against
the board's ONE render surface. Before D248, opening a card mounted a SECOND surface
(`#goal-detail`'s old `[data-role="linked-subgoals"]` list) that read a separately-fetched
`state.goalDetail` snapshot and rendered its own copies of the open goal's same-vertical children —
copies the hand model never touched, positioned, or kept in sync with the board's own DOM. Nothing
in `test_hand_drag.py` ever opened a card first and then dragged one of its children, so nothing
ever proved the two surfaces agreed, or even that only one of them existed. D248 deletes the
second surface outright: an opened card's same-vertical children are now the SAME `GoalCard`
instances the board already renders (`docs/parity/DECISIONS.md`), which means D245-D247's
invariants — one copy of a dragged card at all times, atomic landing, position-preserving
adoption — now apply to a nested child of an OPEN card exactly as they apply to any other card.
This file is the missing proof: OD-1 through OD-3 replay HD-2/HD-6's own choreography with a
parent card open first, OD-4 through OD-6 cover the three ways a card can now open in place at
all (hash boot, search across a period boundary, Inbox), and OD-7 is the WP-D "nested Maybe
subgoal" corner the task brief names directly (the fuller, F3-fixture-backed version of the same
corner lives in `tests/uidiff/test_s104_breadcrumb_chain.py`).

Helpers below are deliberately a duplicated, adapted copy of `test_hand_drag.py`'s own — this
package's established convention (`test_v2_subgoals.py`, `test_v2_open_card.py`, `test_hand_drag.py`
itself all keep their gesture helpers to themselves rather than importing across test modules) —
not an oversight.
"""

from __future__ import annotations

import time
from collections.abc import Callable

import httpx
import psycopg
from playwright.sync_api import Page, expect

from tests.ui.conftest import EXPANDED_COLUMN_CLASS, UiSession, activate_column
from tests.ui.views import FIELD, switch_view

# conftest.py's own PINNED_CLOCK_ISO date — matches test_hand_drag.py's ANCHOR_ISO exactly, so a
# goal anchored here lands in whichever column the pinned clock renders as "current" for its
# vertical (the initially-loaded board, no reload needed).
ANCHOR_ISO = "2026-08-08"

GRIP = {"x": 50, "y": 6}
DRAG_THRESHOLD_PX = 5
SETTLE_MAX_MS = 550
SETTLE_GRACE_MS = 50

DIALOG_SELECTORS = ['[role="dialog"]', '.modal__scrim']


def _row(goal_id: str) -> str:
    return f'[data-goal-id="{goal_id}"] > .goal-card__row'


def _card(goal_id: str) -> str:
    return f'[data-goal-id="{goal_id}"]'


def _create_goal(
    session: UiSession,
    title: str,
    vertical: str,
    parent_id: str | None = None,
    anchor_date: str = ANCHOR_ISO,
) -> str:
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


def _create_maybe(session: UiSession, title: str, parent_id: str | None = None) -> str:
    """AC-069's bare capture: vertical/anchor_date omitted entirely (not merely null), the same
    shape a real capture-box submission sends. `parent_id` set alongside this is the WP-D corner
    shape (a NESTED Maybe subgoal: vertical IS NULL, parent_id SET — NOT `core/board.py`'s
    `MAYBE_PREDICATE` top-level bucket, which additionally requires parent_id IS NULL)."""
    payload: dict[str, object] = {"title": title}
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


def _goal_row(conn: psycopg.Connection, goal_id: str) -> tuple[str | None, str | None]:
    return conn.execute(
        "SELECT parent_id, vertical FROM goals WHERE id = %s", (goal_id,)
    ).fetchone()


def _press(page: Page, source_locator, position: dict[str, float] = GRIP) -> None:
    """See test_hand_drag.py's own `_press` docstring for why this is a single down-then-move
    gesture rather than a separate stationary arm-move before travelling to a real target."""
    # The fixed bottom nav can cover a row that Playwright still considers "in viewport".
    # Centre the real pointer source in its scrolling period slide before pressing it.
    source_locator.evaluate("element => element.scrollIntoView({ block: 'center' })")
    box = source_locator.bounding_box()
    assert box is not None, "drag source has no live bounding box"
    sx = box["x"] + position["x"]
    sy = box["y"] + position["y"]
    page.mouse.move(sx, sy)
    page.mouse.down()


def _press_and_arm(page: Page, source_locator, position: dict[str, float] = GRIP) -> tuple[float, float]:
    box = source_locator.bounding_box()
    assert box is not None, "drag source has no live bounding box"
    sx = box["x"] + position["x"]
    sy = box["y"] + position["y"]
    page.mouse.move(sx, sy)
    page.mouse.down()
    ax, ay = sx + DRAG_THRESHOLD_PX + 15, sy
    page.mouse.move(ax, ay, steps=4)
    return ax, ay


def _move_to_settled(
    page: Page,
    locate: Callable[[], object],
    position: dict[str, float] | Callable[[dict], tuple[float, float]] = GRIP,
    timeout_ms: int = 2000,
) -> tuple[float, float]:
    """See test_hand_drag.py's own docstring: re-locate/re-aim every poll tick against a target
    that can still be sliding under `computeDropTarget`'s live resort preview, and require three
    consecutive stable reads before treating it as settled."""
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


def _has_class(locator, class_name: str) -> bool:
    return class_name in (locator.get_attribute("class") or "").split()


def _assert_no_dialog(page: Page) -> None:
    for selector in DIALOG_SELECTORS:
        assert page.locator(selector).count() == 0, f"{selector!r} must never appear (D248)"


def _wait_detail_settled(page: Page) -> None:
    """The inline panel swaps its "Loading…" line for the fetched editor one round-trip after the
    open click; that swap changes the open card's height and shifts every row below it. The drag
    engine freezes rowRects at PRESS time (press-time geometry law, `lib/drag.ts`), so a press
    that lands before the swap aims the whole gesture at geometry the swap then invalidates —
    OD-2 flaked exactly this way in a full-suite run (adoption read as a plain reorder). Every
    open-then-drag test must settle the panel before pressing."""
    expect(page.locator("#goal-detail")).to_be_visible()
    expect(page.locator("#goal-detail .goal-detail__loading")).to_have_count(0)
    page.wait_for_timeout(120)


# --- OD-1 --------------------------------------------------------------------------------------


def test_od1_drag_out_of_open_card_never_duplicates(ui_f2: UiSession) -> None:
    """D248 + D245, HD-2's own never-two-copies invariant replayed with the dragged card's PARENT
    already open: B is opened first (its `#goal-detail` mounts inside its own `[data-goal-id]`
    subtree), then C — B's own nested subtask — is dragged to the empty top-level gap in the SAME
    ("day") column, triggering D241/D243's climb-to-grandparent, the exact recipe
    `test_hand_drag.py`'s HD-2/HD-3 already prove for an UNOPENED parent (`_seed_detach_chain` /
    `_run_detach_drag`) — only the "parent already open" variable is new here.

    Tripwire: if GoalDetail.vue's inline mount (or any future change) ever renders so much as a
    read-only echo of C alongside the board's own nested GoalCard for C — the exact
    two-render-world shape D248's postmortem names — the `_count() == 1` assertions below start
    failing the instant both copies coexist, during the drag, before release, exactly where
    HD-2 already proved this must never happen for an unopened parent."""
    session = ui_f2
    page = session.page
    a_id = _create_goal(session, "SYN OD1 grandparent", "quarter")
    b_id = _create_goal(session, "SYN OD1 parent", "day", parent_id=a_id)
    c_id = _create_goal(session, "SYN OD1 child", "day", parent_id=b_id)

    page.reload()
    activate_column(page, "day")
    b_title = page.locator(f'{_card(b_id)} > .goal-card__row .goal-card__title')
    expect(b_title).to_be_visible()
    b_title.click()
    expect(page.locator(f'{_card(b_id)}.goal-card--detail-open')).to_be_visible()
    _wait_detail_settled(page)
    c_row = page.locator(_row(c_id))
    expect(c_row).to_be_visible()

    _press(page, c_row)
    _move_to_column_gap_settled(page, "day")

    def _count() -> int:
        return page.locator(_card(c_id)).count()

    for _ in range(3):
        assert _count() == 1, "duplicate/missing subtask card while held, with its parent open"
        page.wait_for_timeout(60)

    page.mouse.up()

    deadline = time.monotonic() + 1.5
    while time.monotonic() < deadline:
        count = _count()
        assert count == 1, f"subtask card rendered {count} times mid-settle under an open parent"
        page.wait_for_timeout(60)

    with psycopg.connect(session.backend.dsn, autocommit=True) as conn:
        deadline = time.monotonic() + 5
        row = _goal_row(conn, c_id)
        while row != (a_id, "day") and time.monotonic() < deadline:
            page.wait_for_timeout(50)
            row = _goal_row(conn, c_id)
        assert row == (a_id, "day"), (
            f"D241/D243: expected the child to climb to its grandparent {a_id!r} at vertical "
            f"'day', got {row!r}"
        )

    assert page.locator(
        f'{_card(b_id)} .goal-card__children [data-goal-id="{c_id}"]'
    ).count() == 0, "the dragged subtask must no longer be nested under the still-open parent"
    expect(page.locator(f'[data-vertical="day"] {_card(c_id)}')).to_be_visible()
    expect(page.locator(f'{_card(b_id)}.goal-card--detail-open')).to_be_visible()
    _wait_detail_settled(page)


# --- OD-2 --------------------------------------------------------------------------------------


def test_od2_drag_into_open_card_adopts_at_slot(ui_f2: UiSession) -> None:
    """`adoptIntoSlot` (D247), exercised with the target parent ALREADY open rather than reached
    via HD-6's drop-between-subtasks gesture. D253 retired the fold this test used to also prove
    an open card was already exempt from (`data-deck-count`/spring-open no longer exist anywhere
    — every card's children render by default now, open or not, compact column or not). D248
    still means an open card's column is always active (`Column.vue`'s `cardProps` forwards
    `goal.children` straight through), so its children are already in the DOM the moment it opens.
    Same `rowRects`-midpoint targeting HD-6 uses, same expected DB outcome (adopted, ordered
    between S1 and S2)."""
    session = ui_f2
    page = session.page
    p_id = _create_goal(session, "SYN OD2 parent", "quarter")
    s1_id = _create_goal(session, "SYN OD2 sub one", "quarter", parent_id=p_id)
    s2_id = _create_goal(session, "SYN OD2 sub two", "quarter", parent_id=p_id)
    x_id = _create_goal(session, "SYN OD2 mover", "quarter")

    page.reload()
    activate_column(page, "quarter")
    p_title = page.locator(f'{_card(p_id)} > .goal-card__row .goal-card__title')
    expect(p_title).to_be_visible()
    p_title.click()
    expect(page.locator(f'{_card(p_id)}.goal-card--detail-open')).to_be_visible()
    _wait_detail_settled(page)
    expect(page.locator(_row(s1_id))).to_be_visible()
    expect(page.locator(_row(s2_id))).to_be_visible()
    expect(page.locator(_row(x_id))).to_be_visible()

    _press_and_arm(page, page.locator(_row(x_id)))
    try:
        s1_box = page.locator(_row(s1_id)).bounding_box()
        s2_box = page.locator(_row(s2_id)).bounding_box()
        assert s1_box is not None and s2_box is not None, "S1/S2 rows have no live bounding box"
        target_x = s1_box["x"] + 50
        target_y = (
            (s1_box["y"] + s1_box["height"] / 2) + (s2_box["y"] + s2_box["height"] / 2)
        ) / 2
        page.mouse.move(target_x, target_y, steps=6)
        page.wait_for_timeout(100)
        page.mouse.up()
    except BaseException:
        page.keyboard.press("Escape")
        page.mouse.up()
        raise

    with psycopg.connect(session.backend.dsn, autocommit=True) as conn:
        deadline = time.monotonic() + 5
        row = _goal_row(conn, x_id)
        while row[0] != p_id and time.monotonic() < deadline:
            page.wait_for_timeout(50)
            row = _goal_row(conn, x_id)
        assert row[0] == p_id, f"D247: X must be adopted into the open parent, got {row!r}"

        ordered: list[str] = []
        deadline = time.monotonic() + 5
        while ordered != [s1_id, x_id, s2_id] and time.monotonic() < deadline:
            page.wait_for_timeout(50)
            ordered = [
                r[0] for r in conn.execute(
                    "SELECT id FROM goals WHERE parent_id = %s ORDER BY position", (p_id,)
                ).fetchall()
            ]
        assert ordered == [s1_id, x_id, s2_id], f"D247: expected X between S1/S2, got {ordered!r}"

    expect(page.locator(f'{_card(p_id)}.goal-card--detail-open')).to_be_visible()
    _wait_detail_settled(page)


# --- OD-3 --------------------------------------------------------------------------------------


def test_od3_resort_subtasks_of_open_card(ui_f2: UiSession) -> None:
    """Reordering an open card's own subtasks is an ordinary same-group drag among board GoalCards
    (D244) — exercised here specifically while the shared parent's `#goal-detail` panel is
    mounted inside the very `[data-goal-id]` subtree the drag machinery measures rects against,
    to prove that mount does not perturb sibling row geometry mid-gesture.

    Drags S2 UP to land just above S1 (`insertBeforeId` = a real sibling id). D249 makes the
    append slot of a nested group (`insertBeforeId: null`, below every rendered card in that
    group) a first-class, group-scoped reorder target in its own right (`lib/dragSlots.ts`'s
    `resolveReorderSlot`) rather than a detach trap — see `test_nested_sort.py` for coverage of
    that slot specifically."""
    session = ui_f2
    page = session.page
    p_id = _create_goal(session, "SYN OD3 parent", "quarter")
    s1_id = _create_goal(session, "SYN OD3 sub one", "quarter", parent_id=p_id)
    s2_id = _create_goal(session, "SYN OD3 sub two", "quarter", parent_id=p_id)

    page.reload()
    activate_column(page, "quarter")
    page.locator(f'{_card(p_id)} > .goal-card__row .goal-card__title').click()
    expect(page.locator(f'{_card(p_id)}.goal-card--detail-open')).to_be_visible()
    _wait_detail_settled(page)
    expect(page.locator(_row(s2_id))).to_be_visible()

    with psycopg.connect(session.backend.dsn, autocommit=True) as conn:
        before = [
            r[0] for r in conn.execute(
                "SELECT id FROM goals WHERE parent_id = %s ORDER BY position", (p_id,)
            ).fetchall()
        ]
        assert before == [s1_id, s2_id], f"seed order must be S1, S2 before the drag: {before!r}"

    # One-shot targeting, not `_move_to_settled`'s live re-aim: a nested source never collapses
    # (D245/test_hd1), so D249's nested indicator ADDS a row and shifts S1 mid-gesture — chasing
    # S1's live box follows that self-inflicted shift and can land on the source's own no-op slot
    # (this exact test flaked that way in two full-suite runs). `resolveReorderSlot` reads
    # press-time-frozen rowRects only, so the honest mirror is to read S1's box ONCE right after
    # the press (same instant the freeze happens), make one decisive move, and hold still —
    # `test_nested_sort.py::_move_to_row_once`'s own recipe, ported.
    _press(page, page.locator(_row(s2_id)))
    s1_box = page.locator(_row(s1_id)).bounding_box()
    assert s1_box is not None, "S1 row has no live bounding box"
    page.mouse.move(s1_box["x"] + 50, s1_box["y"] + s1_box["height"] * 0.15, steps=6)
    page.wait_for_timeout(500)
    page.mouse.up()

    with psycopg.connect(session.backend.dsn, autocommit=True) as conn:
        after: list[str] = []
        deadline = time.monotonic() + 5
        while after != [s2_id, s1_id] and time.monotonic() < deadline:
            page.wait_for_timeout(50)
            after = [
                r[0] for r in conn.execute(
                    "SELECT id FROM goals WHERE parent_id = %s ORDER BY position", (p_id,)
                ).fetchall()
            ]
        assert after == [s2_id, s1_id], f"expected S1 reordered after S2, got {after!r}"

    # The DB write above already confirmed the new order landed; give the client's own re-render
    # off that (a live-reload flush, or the optimistic placement's own reconcile) a moment to
    # catch up rather than reading the DOM at the exact instant the DB poll happened to return —
    # same reasoning as every other settle-poll in this file.
    dom_order: list[str] = []
    deadline = time.monotonic() + 5
    while dom_order != [s2_id, s1_id] and time.monotonic() < deadline:
        dom_order = page.locator(
            f'{_card(p_id)} + .goal-card__children > [data-goal-id]'
        ).evaluate_all("els => els.map(e => e.dataset.goalId)")
        if dom_order != [s2_id, s1_id]:
            page.wait_for_timeout(50)
    assert dom_order == [s2_id, s1_id], f"DOM order must match DB order after settle: {dom_order!r}"
    expect(page.locator(f'{_card(p_id)}.goal-card--detail-open')).to_be_visible()
    _wait_detail_settled(page)


# --- OD-4 --------------------------------------------------------------------------------------


def test_od4_hash_open_on_default_board(ui_f2: UiSession) -> None:
    """D248/main.ts: booting the app at `#goal/<id>` for a goal already on the pinned board's
    default period opens it in place — `store.navigateToGoal`'s `openViaBoardHost` branch, no
    reload, no modal, ever.

    Tripwire: if a future change reintroduces a boot-time modal/dialog surface for a hash-carried
    id (or the inline mount silently stops rendering while the open class is still applied by
    some other means), either the `.goal-detail-inline` visibility check or the
    `[role=dialog]`/`.modal__scrim` absence check below fails — the two together catch both "it
    silently stopped opening" and "it opened the wrong way".

    `page.goto` to a URL differing only in fragment from the current document does NOT reload
    the page (ordinary browser fragment-navigation behaviour), and it fires no `popstate` either
    — so neither of the two paths `lib/urlState.ts` reads the URL on (the boot `applyUrl`, the
    `popstate` listener) would run. `ui_f2` already booted the SPA once at a bare URL, so a
    same-document `goto` here would land on the ALREADY-RUNNING app instead of exercising the
    boot path at all. The `about:blank` hop forces a genuine cross-document navigation into the
    target URL, so the app actually boots fresh with the fragment present."""
    session = ui_f2
    g_id = _create_goal(session, "SYN OD4 hash target", "week")

    session.page.goto("about:blank")
    session.page.goto(f"{session.base_url}/#goal/{g_id}")
    week = session.page.locator('.pattern-vertical-board__column[data-vertical="week"]')
    host = session.page.locator(f'{_card(g_id)}.goal-card--detail-open')
    expect(host).to_be_visible(timeout=10000)
    # The notes end the open goal's piece, in the list right after its card (the opened-card cleanup, KK 27-28 Sep 2026).
    expect(host.locator("xpath=following-sibling::*[1]").locator(".goal-detail-inline")).to_be_visible()
    assert _has_class(week, EXPANDED_COLUMN_CLASS), "the goal's own column must expand on hash-open"
    _assert_no_dialog(session.page)
    assert session.page.url.endswith(f"#goal/{g_id}")


# --- OD-5 --------------------------------------------------------------------------------------


def test_od5_search_navigates_across_a_period_boundary_and_opens_in_place(ui_f2: UiSession) -> None:
    """D248: a search result for a goal OUTSIDE the initially-loaded board period reloads the
    board to that goal's own anchor_date (`navigateToGoal`'s branch (c): no board host on the
    CURRENT board -> `loadBoard(detail.anchor_date)` -> retry `openViaBoardHost`) and opens it in
    place — never the old global-detail fallback D186 named and D248 explicitly supersedes."""
    session = ui_f2
    g_id = _create_goal(session, "SYN OD5 search target", "month", anchor_date="2026-09-08")

    session.page.reload()
    assert session.page.locator(_card(g_id)).count() == 0, (
        "seed check: the target must NOT already be on the initially-loaded (August) board"
    )

    # Finding shows a goal of another period under its period's headline in its own column (docs/design-handoff S1.P3),
    # and a click on it moves the board to it ("Search simply moves u to vertical").
    field = session.page.locator(FIELD)
    session.page.keyboard.press("Control+k")
    field.fill("SYN OD5 search target")
    result = session.page.locator(f'[data-role="finding"] [data-goal-id="{g_id}"] > .goal-card__row')
    result.wait_for(state="visible", timeout=10_000)
    result.click()

    host = session.page.locator(f'{_card(g_id)}.goal-card--detail-open')
    expect(host).to_be_visible(timeout=10000)
    expect(host.locator("xpath=following-sibling::*[1]").locator(".goal-detail-inline")).to_be_visible()
    month = session.page.locator('.pattern-vertical-board__column[data-vertical="month"]')
    assert _has_class(month, EXPANDED_COLUMN_CLASS)
    _assert_no_dialog(session.page)
    assert session.page.url.endswith(f"#goal/{g_id}")


# --- OD-6 --------------------------------------------------------------------------------------


def test_od6_inbox_goal_expands_in_place(ui_f2: UiSession) -> None:
    """D248: Inbox cards expand in place exactly like board cards — `GoalCard.vue`'s
    `onOpenDetail` routes a maybe-vertical click straight through `store.openGoal(id, 'maybe',
    hostKey)` (its own `columnVertical !== 'maybe'` guard skips the board-only `openBoardGoal`
    path), same inline `#goal-detail` mount, no modal, ever."""
    session = ui_f2
    g_id = _create_maybe(session, "SYN OD6 inbox target")

    session.page.reload()
    switch_view(session.page, "inbox")
    title = session.page.locator(f'{_card(g_id)} > .goal-card__row .goal-card__title')
    expect(title).to_be_visible()
    title.click()

    host = session.page.locator(f'{_card(g_id)}.goal-card--detail-open')
    expect(host).to_be_visible(timeout=10000)
    expect(host.locator("xpath=following-sibling::*[1]").locator(".goal-detail-inline")).to_be_visible()
    _assert_no_dialog(session.page)


# --- OD-7: WP-D flagged corner ------------------------------------------------------------------


def test_od7_nested_maybe_subgoal_opens_readable_on_its_own(ui_f2: UiSession) -> None:
    """The WP-D corner, named directly in this suite's brief: `store.navigateToGoal` for a NESTED
    Maybe subgoal (vertical IS NULL, parent_id SET — outside `core/board.py`'s `MAYBE_PREDICATE`
    top-level bucket, which additionally requires parent_id IS NULL). `InboxView.vue` lists only
    the flat top-level Maybe column, so the goal has no card there. `lib/detailSurface.ts`'s
    `walkToGoal` step (b) now opens a goal the Inbox doesn't list on a host of its own
    (`search`) instead of holding open state nobody renders, and this scenario's old tripwire
    fired exactly as it said it would ("this corner has become renderable ... assert the chain is
    actually readable"). So it asserts that: the goal is open and its notes are on screen, no modal
    or dialog, the address unchanged. The session's own zero-console/page-error teardown gate
    still covers "never a crash".

    `page.goto` to a URL differing only in fragment does not reload an already-booted SPA, and
    fires no `popstate` (see OD-4's own note) — the `about:blank` hop forces a genuine boot so
    the fragment read in `lib/urlState.ts::applyUrl` (`store.navigateToGoal`) actually runs."""
    session = ui_f2
    top_id = _create_maybe(session, "SYN OD7 maybe top")
    nested_id = _create_maybe(session, "SYN OD7 nested subgoal", parent_id=top_id)

    session.page.goto("about:blank")
    session.page.goto(f"{session.base_url}/#goal/{nested_id}")

    host = session.page.locator(f'{_card(nested_id)}.goal-card--detail-open')
    expect(host).to_be_visible(timeout=10000)
    expect(host.locator("xpath=following-sibling::*[1]").locator(".goal-detail-inline")).to_be_visible()
    _assert_no_dialog(session.page)
    assert session.page.url.endswith(f"#goal/{nested_id}")
