"""S-71 — L10: bulk complete is one request, and the board has no selection gesture.

docs/E2E.md §6 S-71. Fixture F2. Required by AC-115. Serves L10, Stage 2.

Reshaped by the owner ruling of 2026-08-09 ("why tasks are still can be selected if I click them
and shitty stuff on the top appears? I don't need it"): the click-select gesture, the shift-click
range and the bulk bar are gone — a plain click on a card opens the detail surface, the
incumbent's behaviour. Bulk update is NOT a lost capability; it is an HTTP/MCP-only one (the F5
manifest records it with `ui_selector: null`), and the half of AC-115 that was always the point —
**one** `PATCH /api/goals` with the ids, never a loop of single-id PATCHes — is still asserted
here, over the wire the capability actually lives on.

Two halves:
1. The board half: clicking a card's body opens the detail surface, sets no `aria-selected`
   anywhere, and summons no bulk bar — the ruling, asserted as UI behaviour.
2. The wire half: one `PATCH /api/goals` with three ids closes exactly those three rows
   atomically (`core.goals.update`'s own transaction), and no fourth row changes. Issued with
   `page.request` (Playwright's APIRequestContext — off the page's network stack, so "exactly
   one request" holds by construction); the page-side network log is used the other way round,
   to assert the UI itself issued ZERO mutations across the whole scenario.

The three target rows are adjacent in position order (`SYNCOL01`=2048, `SYNCOL02`=3072,
`SYNCOL03`=4096 in `tests/fixtures/f2_synth.sql`, all in the day column) with real neighbours
above (`SYNDAY01`=1024) and below (`SYNCOL04..07`) for the "no fourth row changed" assertion to
catch an off-by-one against.
"""

from __future__ import annotations

import psycopg
from playwright.sync_api import expect

from tests.ui.conftest import UiSession

TARGETS = ("SYNCOL01", "SYNCOL02", "SYNCOL03")
# Everything else in the day column, above and below the range.
UNTOUCHED = ("SYNDAY01", "SYNCOL04", "SYNCOL05", "SYNCOL06", "SYNCOL07")

# The card's text block, clicked in its own left inset (`padding: 0 6px 0 8px` in `GoalCard.vue`)
# so the click lands on the block itself and not on the title paragraph inside it — both open the
# detail surface since the 2026-08-09 ruling, but the block is the surface the old selection
# gesture lived on, so it is the one whose new behaviour this scenario must witness.
INSET = {"x": 3, "y": 6}


def _card_body(goal_id: str) -> str:
    return f'[data-goal-id="{goal_id}"] > .goal-card__row > .goal-card__text'


def test_s71_bulk_select_one_action(ui_f2: UiSession) -> None:
    session = ui_f2
    page = session.page
    page.wait_for_selector('[data-goal-id="SYNCOL03"]', timeout=10000)

    # Bodies are not carried by `conftest.py`'s request log (it records method/url/status/headers),
    # and this scenario has to count mutations. One listener, this test's own. `page.request`
    # calls below originate from the same browser context, so they land here too.
    mutations: list[dict] = []
    page.on(
        "request",
        lambda req: mutations.append(
            {"method": req.method, "url": req.url, "body": req.post_data}
        )
        if req.method in ("POST", "PATCH", "PUT", "DELETE")
        else None,
    )

    conn = psycopg.connect(session.backend.dsn, autocommit=True)
    try:
        # F2 ships one already-closed row of its own (`SYNMAY06`), so the assertion below is a
        # delta against the starting set, never "nothing else is closed" — which would be a claim
        # about the fixture rather than about this gesture.
        closed_before = {
            row[0]
            for row in conn.execute(
                "SELECT id FROM goals WHERE done_at IS NOT NULL"
            ).fetchall()
        }
        assert not closed_before & set(TARGETS), (
            f"the three target rows must start open; already closed: {closed_before & set(TARGETS)}"
        )

        # --- board half: a click OPENS, and selects nothing (owner ruling 2026-08-09) ------------
        # The strongest form of "no selection chrome": the attributes and elements the old gesture
        # produced do not exist anywhere in the document, before or after the click.
        assert page.locator("[aria-selected]").count() == 0, (
            "no element may carry aria-selected — the selection state itself was removed, "
            "not merely restyled (owner ruling 2026-08-09)"
        )
        assert page.locator("[data-role=bulk-bar]").count() == 0
        assert page.locator("[data-cap=bulk]").count() == 0
        assert "Nothing selected" not in page.inner_text("body")

        page.click(_card_body("SYNCOL01"), position=INSET)
        # The editable title is the open-marker. Since D187 the opened card's own compact row is
        # the editor's identity rail, so `[data-cap=edit-title]` lives on the HOST CARD's title,
        # outside the `#goal-detail` container that expands beneath it — scope by the card.
        expect(
            page.locator('[data-goal-id="SYNCOL01"] [data-cap=edit-title]')
        ).to_be_visible(timeout=5000)
        assert page.locator("[aria-selected]").count() == 0, (
            "clicking a card must open the detail surface and select nothing"
        )
        assert page.locator("[data-role=bulk-bar]").count() == 0, (
            "no bulk bar may appear on click — the click's one meaning is 'open'"
        )
        page.keyboard.press("Escape")
        page.wait_for_selector(
            '#goal-detail[data-role="inline-detail"]', state="detached", timeout=5000
        )

        # --- wire half: one PATCH /api/goals with three ids, atomic --------------------------------
        # `page.request` is Playwright's APIRequestContext — it does NOT ride the page's network
        # stack, so it never appears in this test's own `page.on("request")` log (verified: the
        # log stayed empty while the PATCH landed). "Exactly one request" therefore holds by
        # construction — this test issues exactly one call and reads the atomic result out of the
        # database — and what the log is FOR here is the other direction: the UI itself must have
        # issued zero mutations across the click-open and everything after (the click's one
        # meaning is "open", and there is no selection machinery left to write anything).
        mutations.clear()
        response = page.request.patch(
            f"{session.backend.base_url}/api/goals",
            headers={"Authorization": f"Bearer {session.backend.token}"},
            data={"ids": list(TARGETS), "patch": {"done": True}},
        )
        assert response.ok, f"bulk PATCH failed: {response.status} {response.text()}"

        # A short settle so a straggler (were the UI ever to regrow a write on open/close) has
        # room to show up and fail this rather than arriving after the assertion.
        page.wait_for_timeout(300)
        assert mutations == [], (
            f"the UI issued {len(mutations)} mutating request(s) of its own — a plain click and "
            f"an Escape must write nothing: {[(m['method'], m['url']) for m in mutations]}"
        )

        # --- three rows closed, and no fourth ----------------------------------------------------
        closed_after = {
            row[0]
            for row in conn.execute(
                "SELECT id FROM goals WHERE done_at IS NOT NULL"
            ).fetchall()
        }
        assert closed_after - closed_before == set(TARGETS), (
            f"expected exactly {sorted(TARGETS)} newly closed, the database closed "
            f"{sorted(closed_after - closed_before)}"
        )
        assert closed_before - closed_after == set(), (
            f"rows that were already closed were reopened: {sorted(closed_before - closed_after)}"
        )
    finally:
        conn.close()
