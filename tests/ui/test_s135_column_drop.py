"""S-135 — L1: dragging a card onto a column reassigns its vertical in one gesture.

docs/E2E.md S-135. Fixture F2. Required by AC-102b. Serves L1, Stage 2.

Owner instruction, 2026-08-09 — "you didn't add drag n drop between columns in the verticals, it
should automatically assign the needed vertical after release" — restated exactly by
`docs/PLANNER_DND.md` §2: a column drop sets the vertical *and* anchors the date to that
period's start, one gesture, no prompt. `store.ts::dropOnColumn` is the write; `Column.vue`'s
`onColumnMouseUp` is the DOM half, a bubble-phase mouseup that only fires once every card row
under it has had first refusal.

Four sub-cases, matching this file's own module docstring in `store.ts`:

  1. Cross-column drop assigns vertical and anchor date, leaves `parent_id` untouched.
  2. Alt-drop onto a card still reparents — the measured S-67 gesture, unregressed, and does not
     touch vertical.
  3. Drop-in-place (same column, same period) is a no-op: zero requests, zero toast.
  4. A drop that would create a cycle is refused — server-side, by `move()`'s full-ancestor-chain
     guard (`verticals/core/tree.py`), not by any client-side check. Exercised with a *non-immediate*
     ancestor/descendant pair (`SYNYRR01` onto `SYNDAY01`, three hops apart) specifically because
     an immediate-parent-only guard would also happen to refuse the trivial one-hop case — this
     pair is the one that actually distinguishes "checks the whole chain" from "checks one hop".

Two capabilities `docs/PLANNER_DND.md` §7 names as the owner's own call, not this pass's, and
neither is asserted here because neither shipped: whether the drag sound should fire on
drag-update instead of on drop, and whether Inbox becomes a drop target for un-scheduling.
"""

from __future__ import annotations

import time

import psycopg
from playwright.sync_api import Page, expect

from tests.ui.conftest import UiSession, activate_column

# `> .goal-card__row` (direct child), matching every other scenario's own reasoning
# (`test_s67_reparent_two_gestures.py`): a card with visible children holds their rows a few
# levels down, and Playwright's strict mode refuses the ambiguity a bare descendant selector
# would create.
ORD01_ROW = '[data-goal-id="SYNORD01"] > .goal-card__row'
ORD02_ROW = '[data-goal-id="SYNORD02"] > .goal-card__row'
DAY01_ROW = '[data-goal-id="SYNDAY01"] > .goal-card__row'
Q1_ROW = '[data-goal-id="SYNQ1R01"] > .goal-card__row'
YRR01_ROW = '[data-goal-id="SYNYRR01"] > .goal-card__row'

# The column's own scrollable body — not a card, not the header, not the inline-add row's own
# input (which would arm a text-capture gesture instead). A drop that lands here has, by
# construction, not landed on any card's own drop target, which is exactly `dropOnColumn`'s own
# "gap, header, inline-add row" case (`store.ts`'s own doc comment).
MONTH_BODY = '[data-vertical="month"] .pattern-vertical-board__body'
DAY_BODY = '[data-vertical="day"] .pattern-vertical-board__body'

# The grip point in card-local pixels — `test_s67_reparent_two_gestures.py`'s own `GRIP` and its
# stated reason: a card row is `checkbox | text | schedule trigger` on one flex line, and only the
# middle strip is inert.
GRIP = {"x": 50, "y": 6}

TOAST_TEXT = ".toast-stack .toast .toast__text"


def _row(conn: psycopg.Connection, goal_id: str) -> tuple:
    return conn.execute(
        "SELECT parent_id, vertical, anchor_date, period_key FROM goals WHERE id = %s", (goal_id,)
    ).fetchone()


def _wait_for_parent(
    page: Page, conn: psycopg.Connection, goal_id: str, parent_id: str, timeout: float = 5
) -> None:
    """Yield to Playwright while the optimistic reparent becomes durable."""
    deadline = time.monotonic() + timeout
    while _row(conn, goal_id)[0] != parent_id and time.monotonic() < deadline:
        page.wait_for_timeout(50)


def _wait_for_vertical(
    page: Page, conn: psycopg.Connection, goal_id: str, vertical: str, timeout: float = 5
) -> None:
    deadline = time.monotonic() + timeout
    while _row(conn, goal_id)[1] != vertical and time.monotonic() < deadline:
        page.wait_for_timeout(50)


def test_s135_cross_column_drop_assigns_vertical_and_anchor(ui_f2: UiSession) -> None:
    session = ui_f2
    page = session.page
    page.wait_for_selector('[data-goal-id="SYNDAY01"]', timeout=10000)

    conn = psycopg.connect(session.backend.dsn, autocommit=True)
    try:
        parent_id, vertical, _anchor, _period = _row(conn, "SYNORD01")
        assert parent_id is None and vertical == "week", "SYNORD01 must start parentless, in week"

        expect(page.locator(ORD01_ROW)).to_be_visible()
        expect(page.locator(MONTH_BODY)).to_be_visible()

        before = session.gestures.count
        session.gestures.drag(ORD01_ROW, MONTH_BODY, source_position=GRIP, target_position=GRIP)
        assert session.gestures.count - before == 1, "a column drop must cost exactly 1 gesture"

        page.wait_for_selector(f'[data-vertical="month"] [data-goal-id="SYNORD01"]', timeout=5000)
        _wait_for_vertical(page, conn, "SYNORD01", "month")
        assert session.dialog_records() == [], (
            f"a modal opened on the column drop: {session.dialog_records()}"
        )

        new_parent_id, new_vertical, new_anchor, new_period = _row(conn, "SYNORD01")
        assert new_vertical == "month", f"expected vertical 'month', got {new_vertical!r}"
        assert new_period == "2026-08", f"expected period_key '2026-08', got {new_period!r}"
        # The pinned clock's own date (E2E.md §1 entry 3) — `scheduleGrid.anchorDate('month', ...)`
        # resolves to `today` for the month containing it, the same value the month column's own
        # header label is built from (`columnTitle`), never a second, independently derived date.
        assert str(new_anchor) == "2026-08-08", f"expected anchor_date 2026-08-08, got {new_anchor}"
        assert new_parent_id is None, (
            f"a column drop must never write parent_id, got {new_parent_id!r}"
        )

        assert page.locator(f'[data-vertical="week"] [data-goal-id="SYNORD01"]').count() == 0, (
            "SYNORD01 still rendered in its old week column after the drop"
        )
    finally:
        conn.close()


def test_s135_drop_onto_card_still_reparents(ui_f2: UiSession) -> None:
    """Regression check against §4's combine semantics: dropping onto a *card* must still perform
    the pre-existing reparent (S-67's own gesture), not the column-level schedule write — the
    card row's own mouseup (`GoalCard.vue::onRowMouseUp`) must consume the drop and clear
    `dragSourceId` before it ever reaches the column's bubble-phase handler."""
    session = ui_f2
    page = session.page
    page.wait_for_selector('[data-goal-id="SYNDAY01"]', timeout=10000)

    conn = psycopg.connect(session.backend.dsn, autocommit=True)
    try:
        parent_id, vertical, _anchor, _period = _row(conn, "SYNORD02")
        assert parent_id is None and vertical == "week", "SYNORD02 must start parentless, in week"

        expect(page.locator(ORD02_ROW)).to_be_visible()
        expect(page.locator(Q1_ROW)).to_be_visible()

        page.keyboard.down("Alt")
        try:
            session.gestures.drag(ORD02_ROW, Q1_ROW, source_position=GRIP, target_position=GRIP)
        finally:
            page.keyboard.up("Alt")

        # D110 retires board parent lines; DB state remains the durable reparent evidence.
        # D236 (KK, 2026-08-15): a combine drop now INHERITS the target parent's vertical and
        # anchor — reparent and reschedule in one gesture — so SYNORD02 lands in QUARTER, the
        # column SYNQ1R01 lives in. The original point of this scenario still holds in its
        # updated form: the CARD consumed the drop (dropOnto ran, never dropOnColumn) — which is
        # exactly why the vertical is the parent's, not the drop column's.
        assert session.dialog_records() == [], (
            f"a modal opened on the card-onto-card drop: {session.dialog_records()}"
        )

        _wait_for_parent(page, conn, "SYNORD02", "SYNQ1R01")
        # D244: the fresh subtask folds into SYNQ1R01's compact stack; unfold to see the row.
        activate_column(page, "quarter")
        card = page.locator('[data-vertical="quarter"] [data-goal-id="SYNORD02"]')
        expect(card).to_be_visible()
        assert card.locator("[data-role=parent-line]").count() == 0
        new_parent_id, new_vertical, _anchor, _period = _row(conn, "SYNORD02")
        assert new_parent_id == "SYNQ1R01", f"SYNORD02.parent_id is {new_parent_id!r}, expected 'SYNQ1R01'"
        assert new_vertical == "quarter", f"a combine drop inherits the parent vertical (D236), got {new_vertical!r}"
    finally:
        conn.close()


def test_s135_drop_in_place_is_a_noop(ui_f2: UiSession) -> None:
    """§6: picking a card up and putting it back exactly where it started must write nothing —
    zero HTTP requests, no toast, no changed `updated_at`. `SYNDAY01` is already anchored to the
    `day` column's own current period, so dragging it back onto that same column's gap is the
    no-op case `dropOnColumn` compares `(vertical, anchor_date)` to detect."""
    session = ui_f2
    page = session.page
    page.wait_for_selector('[data-goal-id="SYNDAY01"]', timeout=10000)

    conn = psycopg.connect(session.backend.dsn, autocommit=True)
    try:
        _parent_id, vertical, anchor, _period = _row(conn, "SYNDAY01")
        assert vertical == "day" and str(anchor) == "2026-08-08", (
            "SYNDAY01 must already be anchored to the day column's own current period"
        )
        (before_updated_at,) = conn.execute(
            "SELECT updated_at FROM goals WHERE id = 'SYNDAY01'"
        ).fetchone()

        expect(page.locator(DAY01_ROW)).to_be_visible()
        expect(page.locator(DAY_BODY)).to_be_visible()

        requests_before = len(session.request_log)
        session.gestures.drag(DAY01_ROW, DAY_BODY, source_position=GRIP, target_position=GRIP)

        # No re-render to wait on (nothing changes), so the settle is a short poll on the request
        # log instead of a selector wait — `page.wait_for_timeout`, matching `UiSession`'s own
        # documented reason a bare `time.sleep` never lets a fired-but-pending request land.
        page.wait_for_timeout(500)

        # D226 introduced an idle-time read-only detail prefetch, so background GETs against any
        # goal are sanctioned traffic; the no-op claim is about writes.
        api_requests = [
            r
            for r in session.request_log[requests_before:]
            if "/api/goals/SYNDAY01" in r["url"] and r["method"] != "GET"
        ]
        assert api_requests == [], f"a drop-in-place issued mutating request(s): {api_requests}"
        assert page.locator(TOAST_TEXT).count() == 0, "a drop-in-place must not toast"

        (after_updated_at,) = conn.execute(
            "SELECT updated_at FROM goals WHERE id = 'SYNDAY01'"
        ).fetchone()
        assert after_updated_at == before_updated_at, "a drop-in-place must not touch updated_at"
    finally:
        conn.close()


def test_s135_cycle_refused_by_full_ancestor_chain(ui_f2: UiSession) -> None:
    """A column drop can never express a cycle (it carries no `parent_id` at all — this refusal
    belongs to the card-onto-card path, `dropOnto`/`reparent`). `SYNYRR01` is `SYNDAY01`'s
    great-grandparent, not its immediate parent (`SYNYRR01` -> `SYNQ1R01` -> `SYNQ2R01` ->
    `SYNDAY01`), so refusing this pair specifically exercises `move()`'s
    `new_parent.path LIKE this.path || '%'` guard against the *whole* materialised path
    (`verticals/core/tree.py`), not a check that only compares one hop."""
    session = ui_f2
    session.expects_network_failures = True  # the refused PUT is this scenario's own subject
    page = session.page
    page.wait_for_selector('[data-goal-id="SYNDAY01"]', timeout=10000)

    conn = psycopg.connect(session.backend.dsn, autocommit=True)
    try:
        yrr_parent_id, _h, _a, _p = _row(conn, "SYNYRR01")

        expect(page.locator(YRR01_ROW)).to_be_visible()
        expect(page.locator(DAY01_ROW)).to_be_visible()

        page.keyboard.down("Alt")
        try:
            session.gestures.drag(YRR01_ROW, DAY01_ROW, source_position=GRIP, target_position=GRIP)
        finally:
            page.keyboard.up("Alt")

        # The refusal is a rejected PUT, surfaced as a toast (`store.ts::reparent`'s own catch) —
        # poll for it rather than a selector wait tied to a DOM change that never happens.
        #
        # 15 s, not 5 (D96). The claim is "the refusal reaches the user", not "within five seconds":
        # nothing in S-135 asserts latency, and the toast waits on a full round trip (optimistic
        # paint, PUT, server-side ancestor-chain check, rejection, catch). 5 s was enough on a quiet
        # box and timed out inside a full run — a deadline that fails on the load the suite makes
        # for itself reports the box. A real regression here does not produce a slow toast, it
        # produces none at all, and 15 s says that just as clearly.
        page.wait_for_selector(TOAST_TEXT, timeout=15000)

        deadline = time.monotonic() + 5
        refused = [r for r in session.request_log if "/api/goals/SYNYRR01/parent" in r["url"]]
        while not refused and time.monotonic() < deadline:
            page.wait_for_timeout(100)
            refused = [r for r in session.request_log if "/api/goals/SYNYRR01/parent" in r["url"]]
        assert refused, "no PUT .../SYNYRR01/parent was ever issued"
        assert refused[-1]["status"] == 409, f"expected 409, got {refused[-1]['status']}"

        new_parent_id, _h, _a, _p = _row(conn, "SYNYRR01")
        assert new_parent_id == yrr_parent_id, (
            f"SYNYRR01.parent_id changed despite the refusal: {yrr_parent_id!r} -> {new_parent_id!r}"
        )
        # The tree the refusal protected is still exactly what it was — no partial rewrite, no
        # board reload masking a half-applied write.
        day_parent_id, _h, _a, _p = _row(conn, "SYNDAY01")
        assert day_parent_id == "SYNQ2R01", f"SYNDAY01.parent_id unexpectedly changed: {day_parent_id!r}"
    finally:
        conn.close()
