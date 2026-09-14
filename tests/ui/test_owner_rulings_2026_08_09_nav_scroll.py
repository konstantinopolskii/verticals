"""Coverage for two of the three owner rulings dated 2026-08-09 that this file does not already
prove elsewhere. (The third, ruling 1's board/Inbox split, is covered by
`test_s63_seven_columns.py`, `test_s65_capture_to_maybe.py`, `test_s102_exclusive_columns.py` and
`test_s106_inline_add.py` — those already-catalogued scenarios were narrowed/extended in place
rather than duplicated here.)

Function names deliberately do not follow the `test_s<NN>_...` convention
(`tests/harness/report.py::scenario_id_of`): neither ruling 2 (nav trim) nor ruling 3 (hidden
scrollbars) is a catalogued `docs/E2E.md` scenario — both are plain owner instructions with no
S-id, and minting new catalogue ids for them would require threading new rows through
`docs/E2E.md`, `docs/ACCEPTANCE.md` and `docs/IMPLEMENTATION.md` §9.1's ownership table (plus
`tests/harness/catalogue_index.py`'s six reconciliation checks) for scope the owner did not ask
for. `tests/harness/runner.py::pytest_sessionfinish` documents exactly this shape as a first-class,
accepted outcome: an unmatched test name is a printed notice, not a failure, and "this work package
does not own every test file under `tests/`, and cannot rename another WP's tests to fix it" reads
the same for "this ruling did not ask for a new catalogue id" as it does for cross-package
ownership.

Ruling 2 (owner, 2026-08-09): "Remove tabs days weeks months quarters and years from left menu."
Ruling 3 (owner, 2026-08-09): "Remove the scrollbars when I scroll inside columns."
"""

from __future__ import annotations

import httpx

from tests.ui.conftest import UiSession


def _create_day_overflow(session: UiSession) -> None:
    """Build ruling 3's overflow through the same HTTP boundary the browser uses."""
    for index in range(8):
        response = httpx.post(
            f"{session.backend.base_url}/api/goals",
            json={
                "title": f"Ruling 3 overflow probe {index + 1}",
                "vertical": "day",
                "anchor_date": "2026-08-08",
            },
            headers={"Authorization": f"Bearer {session.backend.token}"},
            timeout=10.0,
        )
        assert response.status_code == 201, (
            f"overflow setup create {index + 1} failed: "
            f"{response.status_code} {response.text}"
        )


def test_owner_ruling2_nav_items_trimmed(ui_f2: UiSession) -> None:
    session = ui_f2
    session.page.wait_for_selector("[data-goal-id]")

    # D111: compact navigation trimmed the vertical tabs; 3 years lives on the board. D250 adds
    # exactly one item back on purpose — Docs, the third resident view. The pinned set/order is
    # now Inbox, Verticals, Docs and nothing else.
    links = session.page.locator("[data-nav-item]")
    assert links.count() == 3, f"expected 3 nav items, found {links.count()}"
    found_keys = [links.nth(i).get_attribute("data-nav-item") for i in range(3)]
    assert found_keys == ["inbox", "verticals", "docs"], (
        f"nav items out of the specified set/order: {found_keys}"
    )
    for removed in ("days", "weeks", "months", "quarters", "years"):
        assert session.page.locator(f'[data-nav-item="{removed}"]').count() == 0, (
            f"ruling 2 (owner, 2026-08-09): [data-nav-item={removed}] must not exist"
        )

    # --- the two wired items still work: Verticals shows the board, Inbox shows the Maybe pile -------
    session.page.click('[data-nav-item="inbox"]')
    session.page.wait_for_selector('[data-cap="inbox"]')
    assert session.page.locator('[data-role="column-strip"]').count() == 0, (
        "Inbox must not render the board's own column strip"
    )
    assert session.page.locator('[data-vertical="maybe"] [data-goal-id]').count() > 0, (
        "Inbox must render the unverticaled (Maybe) goals F2 seeds"
    )

    session.page.click('[data-nav-item="verticals"]')
    session.page.wait_for_selector('[data-role="column-strip"]')
    assert session.page.locator('[data-cap="inbox"]').count() == 0, (
        "Verticals must not render the Inbox view once switched back"
    )
    assert session.page.locator('[data-vertical]').count() == 7, (
        "the board must draw its seven dated columns after switching back from Inbox"
    )

    assert session.page.locator('[data-nav-item="decades"]').count() == 0


def test_owner_ruling3_columns_scroll_without_visible_scrollbar(ui_f2: UiSession) -> None:
    session = ui_f2
    _create_day_overflow(session)
    session.page.reload()
    session.page.wait_for_selector("[data-goal-id]")

    # --- the horizontal strip and every column report a hidden native scrollbar ---------------------
    # `scrollbar-width`/`-ms-overflow-style` are readable back off `getComputedStyle` in every
    # engine that supports them at all (Chromium reports `scrollbar-width: none` even though it
    # is Firefox's own property name — the CSSOM does not gate a property's readback on which
    # engine originated it). The WebKit/Blink pseudo-element has no computed-style equivalent to
    # query directly, so that half is proven the other way below: by measuring the box the
    # scrollbar would otherwise have claimed.
    strip_style = session.page.locator('[data-role="column-strip"]').evaluate(
        "el => getComputedStyle(el).scrollbarWidth"
    )
    assert strip_style == "none", f"column strip must hide its scrollbar, got scrollbar-width: {strip_style!r}"

    day_scrollport = session.page.locator(
        '[data-vertical="day"] [data-role="period-slide"][data-state="current"]'
    )
    column_style = day_scrollport.evaluate(
        "el => getComputedStyle(el).scrollbarWidth"
    )
    assert column_style == "none", f"day scrollport must hide its scrollbar, got scrollbar-width: {column_style!r}"

    # --- the scroll itself still works: scenario setup gives the day column enough rows to have
    # real scrollable content, and its scrollTop actually moves in response to a wheel gesture -------
    day_metrics = day_scrollport.evaluate(
        "el => ({ scrollHeight: el.scrollHeight, clientHeight: el.clientHeight })"
    )
    assert day_metrics["scrollHeight"] > day_metrics["clientHeight"], (
        "ruling 3 setup must create more day content than fits, or the scroll test proves nothing"
    )
    day_box = day_scrollport.bounding_box()
    assert day_box is not None
    session.page.mouse.move(day_box["x"] + day_box["width"] / 2, day_box["y"] + day_box["height"] / 2)
    session.page.mouse.wheel(0, 400)
    session.page.wait_for_function(
        "() => document.querySelector('[data-vertical=\"day\"] "
        "[data-role=\"period-slide\"][data-state=\"current\"]').scrollTop > 0"
    )
    scroll_top = day_scrollport.evaluate("el => el.scrollTop")
    assert scroll_top > 0, "wheel scroll inside the day column must still move scrollTop"

    # --- keyboard focus still moves and still lands somewhere real, not swallowed by the hidden-
    # scrollbar rule --------------------------------------------------------------------------------
    # No property this ruling touches (`scrollbar-width`, `-ms-overflow-style`, the WebKit
    # pseudo-element) is a focus-visibility property, so this is a non-regression check, not a new
    # claim: Tab must still move `document.activeElement` off `<body>`, same as before this ruling.
    session.page.keyboard.press("Tab")
    moved = session.page.evaluate("() => document.activeElement !== document.body")
    assert moved, "Tab must still move focus off <body> after the scrollbar-hiding rule landed"


def test_owner_ruling_2026_08_10_horizontal_wheel_works_over_the_columns(ui_f2: UiSession) -> None:
    """Owner report 2026-08-10 asked for horizontal wheel routing because the strip used to
    overflow. D244 (compact board, KK 2026-08-17) removed the overflow itself: seven equal
    columns fill the viewport exactly, so there is nothing left to scroll and the original
    complaint cannot recur. What this scenario pins NOW is the superseding law — the strip
    never overflows at the suite viewport, and wheel deltas over a column (horizontal or
    vertical) never shift the strip sideways. `boardWheel.ts` survives as a no-op guard for
    the zero-travel case; a future layout that reintroduces overflow re-inherits the routing
    behaviour this test's pre-D244 version pinned (see git history)."""
    session = ui_f2
    session.page.wait_for_selector("[data-goal-id]")
    strip = session.page.locator('[data-role="column-strip"]')

    # D244/HC-1: the compact board FITS — the strip must not overflow horizontally.
    metrics = strip.evaluate("el => ({ sw: el.scrollWidth, cw: el.clientWidth })")
    assert metrics["sw"] <= metrics["cw"] + 1, (
        f"the compact board must never overflow horizontally (D244), got scrollWidth "
        f"{metrics['sw']} > clientWidth {metrics['cw']}"
    )

    # --- wheel deltas over a COLUMN leave the strip exactly where it is ---------------------------
    column = session.page.locator('[data-vertical="day"]')
    box = column.bounding_box()
    assert box is not None
    strip.evaluate("el => { el.scrollLeft = 0 }")
    session.page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
    session.page.mouse.wheel(240, 0)
    session.page.wait_for_timeout(120)
    assert strip.evaluate("el => el.scrollLeft") == 0, (
        "a horizontal wheel over a fitting strip has no travel to perform"
    )
    session.page.mouse.wheel(0, 400)
    session.page.wait_for_timeout(120)
    assert strip.evaluate("el => el.scrollLeft") == 0, (
        "a vertical wheel must scroll the hovered column, never the strip"
    )
