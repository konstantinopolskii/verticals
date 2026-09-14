"""S-67 — L1: reparent in at most two gestures.

docs/E2E.md §6 S-67 (line 1629). Fixture F2. Required by AC-102. Serves L1, Stage 2, RESEARCH §8g.

The v2 card face removed the old action-menu trigger. Reparent remains a direct drag capability;
two independent cards prove the route twice, each in one gesture and therefore inside the
catalogue's at-most-two budget. Neither may open a modal.

Two cards, not one: a reparent is not idempotent against a second run of itself (the second target
would already be an ancestor of the first), and re-seeding mid-test would make the second half run
against a board the first half did not produce. `SYNORD03` takes the drag, `SYNORD04` takes the
menu — both start as parentless *week*-vertical rows (`tests/fixtures/f2_synth.sql`, G2 ordering),
not `SYNMAY02`/`SYNMAY03` (the file's original choice, before Ruling 1 took the Maybe column off
the board). `store.ts::toCardData` nests only vertical-NULL children into a parent card's own DOM
subtree ("a scheduled child... occupies no column and is not a card" is the *only* case that
recurses — `store.ts`'s own `toCardData` comment); a card that carries its own vertical is always
drawn top-level, in its own column, no matter what `parent_id` says, and gets `store.ts::parentTitle`'s
muted parent-line instead (unconditional on any `parent_id`, nested or not). `SYNORD03`/`SYNORD04`
keep their own `week` vertical through the reparent below — the assertions read them as top-level
cards inside `[data-vertical="week"]`, not as DOM descendants of the new parent's card. Both are
already verticaled and parentless in the fixture as shipped — no setup write needed.
"""

from __future__ import annotations

import time

import psycopg
from playwright.sync_api import Page, expect

from tests.ui.conftest import UiSession, activate_column

# Direct child (`>`), never a bare descendant: a card that has nested children holds their
# `.goal-card__row` elements a few levels deeper, and Playwright's strict mode refuses the
# ambiguity. Same reasoning `test_s64_complete_one_gesture.py` records for its own checkbox
# selector.
DRAG_SOURCE = '[data-goal-id="SYNORD03"] > .goal-card__row'
DRAG_TARGET = '[data-goal-id="SYNQ1R01"] > .goal-card__row'
DRAG_SOURCE_2 = '[data-goal-id="SYNORD04"] > .goal-card__row'
DRAG_TARGET_2 = '[data-goal-id="SYNQ1R01"] > .goal-card__row'

# The grip point, in card-local pixels. A card row is `checkbox | text | schedule trigger` on one
# flex line; the default centre grip lands on a different one of those three depending on how long
# the title is, and only the middle one is inert. `x=50` clears the 20px checkbox and the 8px text
# inset; `y=6` is the first text line, above the meta lines and the control cluster below them.
GRIP = {"x": 50, "y": 6}

# `f2_synth.sql`'s own chain: SYNLIF01 -> SYNDEC01 -> SYNYRR01 -> SYNQ1R01 -> SYNQ2R01.
Q1_PATH = "/SYNLIF01/SYNDEC01/SYNYRR01/SYNQ1R01/"


def _row(conn: psycopg.Connection, goal_id: str) -> tuple:
    return conn.execute(
        "SELECT parent_id, path, depth FROM goals WHERE id = %s", (goal_id,)
    ).fetchone()


def _wait_for_parent(
    page: Page, conn: psycopg.Connection, goal_id: str, parent_id: str, timeout: float = 5
) -> None:
    """Yield to Playwright while the optimistic reparent becomes durable."""
    deadline = time.monotonic() + timeout
    while _row(conn, goal_id)[0] != parent_id and time.monotonic() < deadline:
        page.wait_for_timeout(50)


def test_s67_reparent_two_gestures(ui_f2: UiSession) -> None:
    session = ui_f2
    page = session.page
    page.wait_for_selector('[data-goal-id="SYNDAY01"]', timeout=10000)

    conn = psycopg.connect(session.backend.dsn, autocommit=True)
    try:
        # --- preconditions: both cards start parentless, at the root of their own path ----------
        for goal_id in ("SYNORD03", "SYNORD04"):
            parent_id, path, depth = _row(conn, goal_id)
            assert parent_id is None, f"{goal_id} must start parentless; parent_id={parent_id!r}"
            assert path == f"/{goal_id}/", f"{goal_id} must start at the root of its path: {path!r}"
            assert depth == 0, f"{goal_id} must start at depth 0, not {depth}"

        # ==================================================================================
        # Path 1 — drag. "A drag is one gesture" (E2E.md §6's own definition).
        # ==================================================================================
        expect(page.locator(DRAG_SOURCE)).to_be_visible()
        expect(page.locator(DRAG_TARGET)).to_be_visible()
        before = session.gestures.count
        page.keyboard.down("Alt")
        try:
            session.gestures.drag(
                DRAG_SOURCE, DRAG_TARGET, source_position=GRIP, target_position=GRIP
            )
        finally:
            page.keyboard.up("Alt")
        assert session.gestures.count - before == 1, (
            f"the drag path must cost exactly 1 gesture, it cost {session.gestures.count - before}"
        )

        assert session.dialog_records() == [], (
            f"a modal opened on the drag reparent: {session.dialog_records()}"
        )

        _wait_for_parent(page, conn, "SYNORD03", "SYNQ1R01")
        # D236: the Alt combine inherits the parent's vertical, so SYNORD03 renders NESTED under
        # SYNQ1R01 in the QUARTER column (the old week-column visibility line pinned the
        # optimistic pre-refresh frame, which D244's expand wait now outlives). D244: nested rows
        # show once the quarter column unfolds.
        activate_column(page, "quarter")
        card = page.locator(
            '[data-goal-id="SYNQ1R01"] + .goal-card__children [data-goal-id="SYNORD03"]'
        )
        expect(card).to_be_visible(timeout=10000)
        assert card.locator("[data-role=parent-line]").count() == 0
        parent_id, path, depth = _row(conn, "SYNORD03")
        assert parent_id == "SYNQ1R01", f"SYNORD03.parent_id is {parent_id!r}, expected 'SYNQ1R01'"
        assert path == Q1_PATH + "SYNORD03/", f"SYNORD03.path was not recomputed: {path!r}"
        assert depth == 4, f"SYNORD03.depth was not recomputed: {depth} (expected 4)"

        # ==================================================================================
        # Path 2 — v2's remaining reparent route: drag a second card to a second parent.
        # ==================================================================================
        before = session.gestures.count
        page.keyboard.down("Alt")
        try:
            session.gestures.drag(
                DRAG_SOURCE_2, DRAG_TARGET_2, source_position=GRIP, target_position=GRIP
            )
        finally:
            page.keyboard.up("Alt")
        assert session.gestures.count - before == 1, (
            f"the v2 reparent path must stay within 2 gestures; it cost "
            f"{session.gestures.count - before}"
        )

        assert session.dialog_records() == [], (
            f"a modal opened on the second drag reparent: {session.dialog_records()}"
        )

        _wait_for_parent(page, conn, "SYNORD04", "SYNQ1R01")
        # Same D236/D244 reading as path 1: durable home is nested-under-SYNQ1R01, quarter.
        activate_column(page, "quarter")
        moved = page.locator(
            '[data-goal-id="SYNQ1R01"] + .goal-card__children [data-goal-id="SYNORD04"]'
        )
        expect(moved).to_be_visible(timeout=10000)
        assert moved.locator("[data-role=parent-line]").count() == 0
        parent_id, path, depth = _row(conn, "SYNORD04")
        assert parent_id == "SYNQ1R01", f"SYNORD04.parent_id is {parent_id!r}, expected 'SYNQ1R01'"
        assert path == Q1_PATH + "SYNORD04/", f"SYNORD04.path was not recomputed: {path!r}"
        assert depth == 4, f"SYNORD04.depth was not recomputed: {depth} (expected 4)"
    finally:
        conn.close()
