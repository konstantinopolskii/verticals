"""S-73 — Body is content, never structure.

`docs/E2E.md` §6, S-73 (line 1741). Required by AC-117 (and the negative row AC-186; AC-109's
"checkbox lines inside a body never change it" is the same property read from the card side).

    Steps: set a body containing three `- [ ] something` lines; reload.
    Assert: `SELECT count(*) FROM goals WHERE parent_id='<that id>'` is 0; the rendered body
    shows a markdown list; the card's subgoal count still reads the real child count.

Target row is `SYNSCH04` (F2, G4): month column of the pinned 2026-08-08 board, zero children,
already carries a plain-prose body — so "count(*) is 0" is a real assertion about what the write
did *not* create, and the card's real child count (0) is what "still reads the real child count"
means for it. A row with children would contradict the scenario's own literal `is 0`.

The body is set over HTTP (`PATCH /api/goals/{id}`), not by writing SQL behind the API: §4's rule
is "sanitize on render, not on write", and a body that never travelled through the write path
would not exercise the half of that rule this scenario is about.
"""

from __future__ import annotations

import psycopg
from playwright.sync_api import expect

from tests.ui.conftest import UiSession, activate_column

TARGET = "SYNSCH04"

# Three checkbox lines — the exact GFM task-list shape a body-parsing implementation would be
# tempted to turn into three child rows (the "line octarine failed to cross", §4).
BODY = "- [ ] first thing\n- [ ] second thing\n- [ ] third thing"

CARD = f'[data-goal-id="{TARGET}"]'
CARD_ROW = f"{CARD} > .goal-card__row"
TITLE = f"{CARD_ROW} .goal-card__title"
DETAIL_BODY = ".goal-detail__body"


def test_s73_body_is_content_never_structure(ui_f2: UiSession) -> None:
    session = ui_f2
    page = session.page
    conn = psycopg.connect(session.backend.dsn, autocommit=True)
    try:
        (children_before,) = conn.execute(
            "SELECT count(*) FROM goals WHERE parent_id = %s", (TARGET,)
        ).fetchone()
        assert children_before == 0, (
            f"{TARGET} must start childless for this scenario's own `count(*) ... is 0` to mean "
            f"anything; found {children_before}"
        )
        (rows_before,) = conn.execute("SELECT count(*) FROM goals").fetchone()

        # --- step 1: set the body, over the real write path -----------------------------------
        res = page.request.patch(
            f"{session.base_url}/api/goals/{TARGET}",
            headers={
                "Authorization": f"Bearer {session.backend.token}",
                "Content-Type": "application/json",
            },
            data={"body": BODY},
        )
        assert res.status == 200, f"PATCH body failed: {res.status} {res.text()}"

        # --- step 2: reload -------------------------------------------------------------------
        page.reload()
        expect(page.locator(TITLE)).to_be_visible()

        # --- assert 1: zero child rows created ------------------------------------------------
        (children_after,) = conn.execute(
            "SELECT count(*) FROM goals WHERE parent_id = %s", (TARGET,)
        ).fetchone()
        assert children_after == 0, (
            f"writing three `- [ ] …` lines into {TARGET}.body created {children_after} child "
            f"row(s) — body is content, never structure (AC-117, AC-186)"
        )
        (rows_after,) = conn.execute("SELECT count(*) FROM goals").fetchone()
        assert rows_after == rows_before, (
            f"the body write changed the row count of the whole table ({rows_before} -> "
            f"{rows_after}) — something parsed structure out of a body"
        )
        (stored,) = conn.execute("SELECT body FROM goals WHERE id = %s", (TARGET,)).fetchone()
        assert stored == BODY, "the stored body is not what was sent (store raw, §4)"

        # --- assert 2: the rendered body shows a markdown list --------------------------------
        activate_column(page, "month")
        page.click(TITLE)
        body_el = page.locator(DETAIL_BODY)
        expect(body_el).to_be_visible()
        items = body_el.locator("ul > li")
        expect(items).to_have_count(3)
        texts = items.all_inner_texts()
        assert [t.strip() for t in texts] == [
            "[ ] first thing",
            "[ ] second thing",
            "[ ] third thing",
        ], (
            f"the three lines must render as three list items carrying their literal text — the "
            f"`[ ]` is content, not a widget the renderer invents: {texts}"
        )
        # No structure was invented on the render side either: a checkbox line must not become a
        # real checkbox control inside the body.
        assert body_el.locator("input").count() == 0, (
            "the rendered body contains an <input> — a `- [ ] …` line became a control"
        )

        # --- assert 3: the card's subgoal count still reads the real child count --------------
        # `GoalCard.vue` renders `.goal-card__meta` with "N subgoals" only when `subgoalCount` is
        # truthy; the real child count here is 0, so the correct render is no such line at all.
        # Asserted as "no meta line claims subgoals", not as "no meta line" — a parent line
        # (`data-role=parent-line`) is a different, legitimate meta line and this row has none.
        page.keyboard.press("Escape")
        expect(page.locator(DETAIL_BODY)).to_be_hidden()
        row_text = page.locator(CARD_ROW).inner_text()
        assert "subgoal" not in row_text.lower(), (
            f"{TARGET} has 0 children, so its card must claim no subgoals; card row reads: "
            f"{row_text!r}"
        )
    finally:
        conn.close()
