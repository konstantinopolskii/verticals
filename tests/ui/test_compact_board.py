"""Compact board (docs/COMPACT_BOARD_HANDOFF.md, KK rulings 2026-08-17) — HC-1..HC-11.

Fixture F2 throughout. Real browser, real backend, psycopg seeds — the suite's standing shape.
Each test names the acceptance criteria it pins; HC-12 ("existing laws hold") is the rest of the
ui package staying green, not a test here.

D253 (KK, 2026-08-21, docs/parity/DECISIONS.md): §4's stacks retire outright — "remove the change
we've done with the sub-tasks in collapsed columns ... let's show all sub-task by default now".
HC-3/HC-4/HC-5 (stack census, deck-edge line counts, deck-edge inertness) and HC-10 (stack face
swap) pinned DOM that no longer exists; `test_stack_census_and_deck_edge` below is rewritten to
its surviving intent — every subtask renders in every column, compact or expanded, and the deck
edge is gone everywhere, not merely reachable a different way. `test_chain_hover_wash_and_face_
swap` keeps HC-9 (the wash) and drops HC-10 (the swap it used to also exercise). §3's layout law
(HC-1/HC-2/HC-6/HC-7) and the wash mechanism (D235) are untouched by this ruling — those tests
stand as written.
"""

from __future__ import annotations

from datetime import date

import psycopg
from playwright.sync_api import expect

from verticals.core import goals
from tests.ui.conftest import UiSession

ANCHOR = date(2026, 8, 8)

COLUMN = ".pattern-vertical-board__column"
EXPANDED_CLASS = "pattern-vertical-board__column--active"
HEADER = ".pattern-vertical-board__header"
# D253: the deck edge is retired; the selector survives only to assert its own absence.
DECK_EDGE = '[data-role="deck-edge"]'
WASH_CLASS = "goal-card--ancestor-hover"
# setHoverChain's clear grace (store.ts HOVER_CLEAR_GRACE_MS) plus headroom: how long a test must
# wait after moving the pointer away before asserting the wash is gone.
HOVER_CLEAR_WAIT_MS = 450
# The wash waits for the pointer to rest on a card (lib/pointerRest.ts: 50 ms still or slow, KK 2026-10-03 and
# 2026-10-04; at most lib/boardViewState.ts HOVER_REST_MS, 250 ms) plus headroom: how long a test must rest on a
# card before asserting the wash is there.
HOVER_REST_WAIT_MS = 450


def _create(conn, title: str, vertical: str, parent_id: str | None = None,
            color: str | None = None, anchor: date = ANCHOR):
    return goals.create(
        conn, owner="t1", title=title, vertical=vertical, anchor_date=anchor,
        parent_id=parent_id, color=color,
    ).goal


def _column(page, vertical: str):
    return page.locator(f'{COLUMN}[data-vertical="{vertical}"]')


def _is_expanded(page, vertical: str) -> bool:
    return EXPANDED_CLASS in (_column(page, vertical).get_attribute("class") or "")


def _expand_via_header(page, vertical: str) -> None:
    _column(page, vertical).locator(HEADER).first.click()
    page.wait_for_function(
        """vertical => document.querySelector(
             `.pattern-vertical-board__column[data-vertical="${vertical}"]`
           )?.classList.contains('pattern-vertical-board__column--active')""",
        arg=vertical,
        timeout=5000,
    )


def _has_wash(page, goal_id: str) -> bool:
    classes = page.locator(f'[data-goal-id="{goal_id}"]').first.get_attribute("class") or ""
    return WASH_CLASS in classes.split()


# --- HC-1 / HC-2: fit and equal widths ---------------------------------------------------------


def test_compact_fit(ui_f2: UiSession) -> None:
    page = ui_f2.page
    for width in (1280, 1440, 1512):
        page.set_viewport_size({"width": width, "height": 779})
        page.wait_for_timeout(100)
        cols = page.locator(COLUMN)
        assert cols.count() == 7, f"expected 7 columns at {width}px, got {cols.count()}"

        # HC-1: no horizontal scroll anywhere — neither the document nor the strip itself.
        assert page.evaluate(
            "document.documentElement.scrollWidth <= window.innerWidth + 1"
        ), f"document overflows horizontally at {width}px"
        assert page.evaluate(
            """() => { const b = document.querySelector('.pattern-vertical-board');
                       return b.scrollWidth <= b.clientWidth + 1 }"""
        ), f"board strip scrolls horizontally at {width}px"

        boxes = [cols.nth(i).bounding_box() for i in range(7)]
        assert all(b is not None for b in boxes)
        boxes.sort(key=lambda b: b["x"])
        for b in boxes:
            assert b["x"] >= -0.5 and b["x"] + b["width"] <= width + 0.5, (
                f"column out of viewport at {width}px: {b}"
            )

        # HC-1: dead right gutter no wider than the inter-column gap.
        inter_gap = boxes[1]["x"] - (boxes[0]["x"] + boxes[0]["width"])
        right_gutter = width - (boxes[-1]["x"] + boxes[-1]["width"])
        assert right_gutter <= inter_gap + boxes[0]["x"] + 1.0, (
            f"right gutter {right_gutter:.1f}px exceeds inter-column gap {inter_gap:.1f}px "
            f"(+left inset {boxes[0]['x']:.1f}px) at {width}px"
        )

        # HC-2: all compact widths within 1px of each other.
        widths = [b["width"] for b in boxes]
        assert max(widths) - min(widths) <= 1.1, f"unequal compact widths at {width}px: {widths}"


# --- D253: every subtask renders by default, no deck edge anywhere -----------------------------


def test_subtasks_visible_no_deck_edge(ui_f2: UiSession) -> None:
    """D253 (KK, 2026-08-21) retires D244 §4's stacks outright: "let's show all sub-task by
    default now". This replaces the old HC-3/HC-4/HC-5 (stack census, deck-edge line counts,
    deck-edge inertness) with their surviving intent — a compact (non-active) column renders
    every card's full nested subtree exactly like the active column always has, and the deck
    edge — the fold affordance those criteria pinned — does not exist anywhere on the board."""
    session = ui_f2
    page = session.page
    with psycopg.connect(session.backend.dsn, autocommit=True) as conn:
        p0 = _create(conn, "SYN HC no kids", "quarter")
        p1 = _create(conn, "SYN HC one kid", "quarter")
        k1 = _create(conn, "SYN HC kid 1of1", "quarter", p1.id)
        p2 = _create(conn, "SYN HC two kids", "quarter")
        k2a = _create(conn, "SYN HC kid 1of2", "quarter", p2.id)
        k2b = _create(conn, "SYN HC kid 2of2", "quarter", p2.id)
        p5 = _create(conn, "SYN HC five deep", "quarter")
        k5a = _create(conn, "SYN HC kid a", "quarter", p5.id)
        k5b = _create(conn, "SYN HC kid b", "quarter", p5.id)
        k5c = _create(conn, "SYN HC kid c", "quarter", p5.id)
        _create(conn, "SYN HC grandkid a1", "quarter", k5a.id)
        _create(conn, "SYN HC grandkid a2", "quarter", k5a.id)

    page.reload()
    quarter = _column(page, "quarter")
    expect(quarter.locator(f'[data-goal-id="{p0.id}"]')).to_be_visible()
    assert not _is_expanded(page, "quarter"), "quarter must still be compact — no header click yet"

    # Every same-column sub-task renders, unfolded, in the compact (non-active) column — the new
    # law: nothing is ever hidden behind a face card.
    for visible in (k1, k2a, k2b, k5a, k5b, k5c):
        expect(quarter.locator(f'[data-goal-id="{visible.id}"]')).to_be_visible()

    # No fold affordance anywhere on the loaded board.
    assert page.locator(DECK_EDGE).count() == 0, "a deck edge rendered — the fold affordance is retired"


# --- HC-6: expand toggle, exclusivity, reload reset --------------------------------------------


def test_expand_toggle_and_reload(ui_f2: UiSession) -> None:
    page = ui_f2.page
    expect(page.locator(COLUMN).first).to_be_visible()
    assert page.locator(f"{COLUMN}.{EXPANDED_CLASS}").count() == 0, "a column starts expanded"

    _expand_via_header(page, "quarter")
    assert _is_expanded(page, "quarter")
    assert page.locator(f"{COLUMN}.{EXPANDED_CLASS}").count() == 1

    # Expanding another column collapses the first — at most one expanded, ever.
    _expand_via_header(page, "year")
    assert _is_expanded(page, "year")
    assert not _is_expanded(page, "quarter")
    assert page.locator(f"{COLUMN}.{EXPANDED_CLASS}").count() == 1

    # Second click on the expanded header returns all-compact.
    _column(page, "year").locator(HEADER).first.click()
    page.wait_for_timeout(100)
    assert page.locator(f"{COLUMN}.{EXPANDED_CLASS}").count() == 0

    # Session-only: a reload comes back all-compact.
    _expand_via_header(page, "month")
    page.reload()
    expect(page.locator(COLUMN).first).to_be_visible()
    assert page.locator(f"{COLUMN}.{EXPANDED_CLASS}").count() == 0, "expansion survived a reload"


# --- HC-7: card click = expand + open, one gesture ---------------------------------------------


def test_card_click_expands_and_opens(ui_f2: UiSession) -> None:
    session = ui_f2
    page = session.page
    with psycopg.connect(session.backend.dsn, autocommit=True) as conn:
        parent = _create(conn, "SYN HC click parent", "quarter")
        _create(conn, "SYN HC click kid", "quarter", parent.id)

    page.reload()
    card_row = page.locator(f'[data-goal-id="{parent.id}"] > .goal-card__row')
    expect(card_row).to_be_visible()
    assert not _is_expanded(page, "quarter")

    card_row.click()
    expect(page.locator(f'[data-goal-id="{parent.id}"].goal-card--detail-open')).to_be_visible(
        timeout=10000
    )
    assert _is_expanded(page, "quarter"), "card click did not expand the column"
    assert page.url.endswith(f"#goal/{parent.id}")


# --- HC-8: compact AND expanded columns render the pre-redesign inline structure ----------------


def test_expanded_matches_inline_rendering(ui_f2: UiSession) -> None:
    """D253: HC-8's premise ("an expanded column unfolds to the pre-redesign inline rendering")
    now holds for a COMPACT column too — there is nothing left to unfold. The nested
    adjacent-sibling children block renders before any header click, and expanding the column
    changes nothing about that structure (only the column's own width/active state, per D244
    §3, which this test does not otherwise touch)."""
    session = ui_f2
    page = session.page
    with psycopg.connect(session.backend.dsn, autocommit=True) as conn:
        parent = _create(conn, "SYN HC unfold parent", "quarter")
        kid = _create(conn, "SYN HC unfold kid", "quarter", parent.id)

    page.reload()
    quarter = _column(page, "quarter")
    expect(quarter.locator(f'[data-goal-id="{parent.id}"]')).to_be_visible()

    # The exact DOM shape the pre-redesign subgoal tests pin: adjacent-sibling children block —
    # present in the still-compact column, no header click yet.
    nested = quarter.locator(
        f'[data-goal-id="{parent.id}"] + .goal-card__children [data-goal-id="{kid.id}"]'
    )
    expect(nested).to_be_visible()
    assert not _is_expanded(page, "quarter")

    # Expanding the column changes nothing about that structure — the kid stays exactly where it
    # was, still nested under its parent.
    _expand_via_header(page, "quarter")
    expect(nested).to_be_visible()
    assert quarter.locator(DECK_EDGE).count() == 0, "the deck edge is retired (D253)"


# --- HC-9: chain wash (HC-10's stack face swap retired by D253 — nothing is ever hidden) --------


def _seed_chain(session: UiSession):
    """A colored life value -> year -> month parent -> month sub-task."""
    with psycopg.connect(session.backend.dsn, autocommit=True) as conn:
        value = _create(conn, "SYN HC chain value", "life", color="#92ce14")
        year = _create(conn, "SYN HC chain year", "year", value.id)
        mparent = _create(conn, "SYN HC chain month parent", "month", year.id)
        mchild = _create(conn, "SYN HC chain month child", "month", mparent.id)
        bystander = _create(conn, "SYN HC bystander", "year")
    return value, year, mparent, mchild, bystander


def test_chain_hover_wash(ui_f2: UiSession) -> None:
    """HC-9: hovering any chain member washes every board-visible member of that chain, deriving
    the wash color from the chain's own value color (D231/D235). D253 retires HC-10 (the stack
    face swap) along with the stacks it swapped faces on — `mparent` and `mchild` are both
    directly rendered now, with no fold and nothing to swap, so both simply carry the wash
    together for the hover's duration; clicking either opens that card directly (ordinary HC-7
    card-click behavior, not a swapped-face special case)."""
    session = ui_f2
    page = session.page
    value, year, mparent, mchild, bystander = _seed_chain(session)

    page.reload()
    year_row = page.locator(f'[data-goal-id="{year.id}"] > .goal-card__row')
    expect(year_row).to_be_visible()
    month = _column(page, "month")
    expect(month.locator(f'[data-goal-id="{mparent.id}"]')).to_be_visible()
    expect(month.locator(f'[data-goal-id="{mchild.id}"]')).to_be_visible()

    # --- a card the pointer only passes lights nothing: the wash waits for a rest ----------------
    # One quick stroke down the column over the card, in a single call: the pointer never stops on it.
    row_box = year_row.bounding_box()
    assert row_box is not None
    stroke_x = row_box["x"] + row_box["width"] / 2
    page.mouse.move(stroke_x, row_box["y"] - 40)
    page.mouse.move(stroke_x, row_box["y"] + row_box["height"] + 40, steps=8)
    page.mouse.move(5, 5)
    assert not _has_wash(page, value.id), "a card the pointer only passed lit its chain"
    page.wait_for_timeout(HOVER_CLEAR_WAIT_MS)
    assert not _has_wash(page, value.id), "a card the pointer only passed lit its chain"

    # --- rest on the year member: wash on every board-visible chain member ----------------------
    year_row.hover()
    page.wait_for_timeout(HOVER_REST_WAIT_MS)
    assert _has_wash(page, value.id), "life value card missed the chain wash"
    assert _has_wash(page, mparent.id), "month parent missed the chain wash"
    assert _has_wash(page, mchild.id), "month child missed the chain wash"
    assert not _has_wash(page, bystander.id), "unrelated card caught the chain wash"

    # The wash derives from the chain's value color (D231) — the card carries the derived color,
    # and the wash variable is set from it.
    assert page.locator(f'[data-goal-id="{mchild.id}"]').get_attribute("data-colored") == "true"

    # --- mouse-out: wash gone (after the clear grace) --------------------------------------------
    page.mouse.move(5, 5)
    page.wait_for_timeout(HOVER_CLEAR_WAIT_MS)
    assert not _has_wash(page, value.id), "wash survived mouse-out"
    assert not _has_wash(page, mchild.id), "wash survived mouse-out"


# --- HC-11: view state makes no requests -------------------------------------------------------


def test_view_state_makes_no_requests(ui_f2: UiSession) -> None:
    session = ui_f2
    page = session.page
    value, year, mparent, mchild, bystander = _seed_chain(session)
    page.reload()
    year_row = page.locator(f'[data-goal-id="{year.id}"] > .goal-card__row')
    expect(year_row).to_be_visible()
    page.wait_for_timeout(500)  # let any post-load prefetch sweep settle

    before = len(session.request_log)
    _expand_via_header(page, "quarter")
    _column(page, "quarter").locator(HEADER).first.click()  # collapse again
    year_row.hover()
    month = _column(page, "month")
    expect(month.locator(f'[data-goal-id="{mchild.id}"]')).to_be_visible(timeout=5000)
    page.mouse.move(5, 5)
    page.wait_for_timeout(HOVER_CLEAR_WAIT_MS)

    new_requests = [
        r for r in session.request_log[before:]
        # The D226 detail prefetch sweep is background machinery with its own laws; HC-11 is
        # about the VIEW STATE issuing zero writes/reads of its own.
        if "prefetch=1" not in r["url"] and "/api/events" not in r["url"]
    ]
    assert new_requests == [], f"view-state changes issued requests: {new_requests}"
