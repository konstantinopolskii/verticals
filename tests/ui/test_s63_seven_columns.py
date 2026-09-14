"""S-63 — L2: all seven columns on one screen, no mode switch.

docs/E2E.md, S-63. Fixture F2. Steps: load F2, screenshot the board.
Required by J1, L2.

Renamed from `test_s63_eight_columns.py` (ruling 1, owner, 2026-08-09: "There's no need to show
Maybe as a left column. Make it same tab as inbox"). `ARCHITECTURE.md`:445's original "an eighth
column, pinned left of Day, labelled Maybe" is superseded — `Board.vue` now draws the seven dated
columns only (its own `dated` computed drops `vertical === 'maybe'` before rendering), and the
Maybe bucket is reached through the Inbox nav view instead. `tests/ui/test_s65_capture_to_maybe.py`
covers the Inbox screen's own inline-add; this file stays scoped to the board, matching S-63's own
(updated) steps.

R2 adds the fixed triennium as the 3-year column's period caption. Day retains its calendar-date
caption; the other five columns remain title-only.
"""

from __future__ import annotations

from tests.harness.report import artifact, scenario_id_of
from tests.ui.conftest import ARTIFACTS_ROOT, REPO_ROOT, UiSession

# The board's own seven dated columns — Maybe is no longer among them (ruling 1). Order verbatim
# from `verticals/core/board.py::COLUMN_ORDER` with the `maybe` entry dropped, matching
# `Board.vue`'s own `dated` computed.
EXPECTED_VERTICALS = ("day", "week", "month", "quarter", "year", "decade", "life")
EXPECTED_HEADLINES = ("Day", "Week", "Month", "Quarter", "Year", "3 years", "Life")


def test_s63_seven_columns(ui_f2: UiSession, request) -> None:
    session = ui_f2

    # --- wait for the board to actually be the thing in the screenshot ---------------------------
    # `ui_f2`'s own `page.goto(static_base_url)` (conftest.py) waits only for the `load` event —
    # correct for it, since every *other* scenario in this package drives the page through
    # Playwright locator actions (`.click`, `.fill`, `expect(...).to_be_checked`, etc.), which
    # auto-wait for their target to exist. This test is the one exception: a bare
    # `page.screenshot()` has no target to wait for, so nothing was forcing the board's own async
    # `fetch('/api/board')` (fired from a Vue onMounted hook, strictly after the `load` event this
    # SPA's own shell fires on) to have resolved and painted first. Confirmed live via a 20-run
    # batch of this exact call site: 15/20 screenshots showed every card's checkbox and "Schedule"
    # button but a *blank* `.goal-card__title` (a live pixel-crop diff against a known-good
    # capture, both exactly reproduced down to the byte, confirms this isn't a viewing artifact),
    # 3/20 showed a fully blank board (screenshot landed before the fetch resolved at all), and
    # only 2/20 happened to land late enough to show everything. The 15/20 case is a real font
    # race, not a data race: `.goal-card__title` is the one 400-weight (`font-weight: 400`) text
    # run on the whole board — every header (`.t-title`, bold) and the "Schedule" button label
    # (kit default, semibold) sit on weights that were already resolved, so they painted every
    # time; Inter Regular is requested later and, per a `document.fonts.status` probe at the same
    # call site, was still `'loading'` on a supermajority of runs. Waiting for a real card to
    # exist closes the data race; waiting for `document.fonts.ready` closes the font race — both
    # are required, confirmed by re-running this exact test 20 times after adding them with zero
    # blank-title recurrences (see this file's own history / WP-22 final report for the batch).
    session.page.wait_for_selector("[data-goal-id]")
    session.page.evaluate("() => document.fonts.ready")
    session.page.wait_for_function("() => document.fonts.status === 'loaded'", timeout=5000)

    # --- screenshot the board (S-63's own step 2) -----------------------------------------------
    scenario_id = scenario_id_of(request.node.name) or "S-63"
    shot_dir = ARTIFACTS_ROOT / scenario_id
    shot_dir.mkdir(parents=True, exist_ok=True)
    shot_path = shot_dir / "board.png"
    session.page.screenshot(path=str(shot_path))
    artifact(request, str(shot_path.relative_to(REPO_ROOT)))

    # --- 7 column headers, exact `data-vertical` set, in the specified order, no `maybe` ------------
    headers = session.page.locator("[data-vertical]")
    assert headers.count() == 7, f"expected 7 [data-vertical] columns, found {headers.count()}"
    found_order = [headers.nth(i).get_attribute("data-vertical") for i in range(7)]
    assert found_order == list(EXPECTED_VERTICALS), (
        f"data-vertical values out of the specified set/order: {found_order}"
    )
    assert session.page.locator('[data-vertical="maybe"]').count() == 0, (
        "ruling 1 (owner, 2026-08-09): the board must render no [data-vertical=maybe] column at all"
    )

    # --- every column has a non-zero bounding box -------------------------------------------------
    for vertical in EXPECTED_VERTICALS:
        box = session.page.locator(f'[data-vertical="{vertical}"]').bounding_box()
        assert box is not None, f"{vertical} column has no bounding box (not rendered)"
        assert box["width"] > 0 and box["height"] > 0, f"{vertical} column has a zero-area bounding box: {box}"

    # --- no horizontal page scroll: the column strip scrolls inside its own container -------------
    overflow = session.page.evaluate(
        "() => ({ scrollWidth: document.body.scrollWidth, innerWidth: window.innerWidth })"
    )
    assert overflow["scrollWidth"] <= overflow["innerWidth"] + 1, (
        f"document.body.scrollWidth ({overflow['scrollWidth']}) exceeds window.innerWidth "
        f"({overflow['innerWidth']}) + 1 — the page itself is scrolling horizontally"
    )

    # D171-D173: every header has a generic scale headline and quiet period label.
    for vertical, headline in zip(EXPECTED_VERTICALS, EXPECTED_HEADLINES, strict=True):
        title_el = session.page.locator(f'[data-vertical="{vertical}"] .pattern-vertical-board__header .t-title')
        assert title_el.count() == 1, f"{vertical} column: expected exactly one .t-title, found {title_el.count()}"
        assert title_el.inner_text().strip() == headline

    for vertical in EXPECTED_VERTICALS:
        caption = session.page.locator(f'[data-vertical="{vertical}"] .pattern-vertical-board__header .t-caption')
        assert caption.count() == 1, f"{vertical} column: expected one period label, found {caption.count()}"
        assert caption.inner_text().strip(), f"{vertical} column: period label is empty"

    # --- reaching the life column required 0 navigations ------------------------------------------
    url_before = session.page.url
    life_box = session.page.locator('[data-vertical="life"]').bounding_box()
    assert life_box is not None
    # Scrolling the column strip's own internal container into view is not a page navigation —
    # confirmed by re-reading `page.url()` unchanged afterward, matching S-63's own wording
    # ("no route change: `page.url()` unchanged").
    session.page.locator('[data-vertical="life"]').scroll_into_view_if_needed()
    assert session.page.url == url_before, (
        f"reaching the life column changed page.url(): {url_before!r} -> {session.page.url!r}"
    )

    # --- no modal opened by any of the above --------------------------------------------------------
    assert session.dialog_records() == [], f"dialog(s) recorded during S-63: {session.dialog_records()}"
