"""P-02: measured card-drag physics and our adapted schedule/reorder wire."""

from __future__ import annotations

from typing import Any
from urllib.parse import urlsplit

from playwright.sync_api import Page

from tests.parity.css import split_css_list
from tests.ui.conftest import UiSession


ORD01 = '[data-goal-id="SYNORD01"] > .goal-card__row'
ORD02 = '[data-goal-id="SYNORD02"] > .goal-card__row'
ORD03 = '[data-goal-id="SYNORD03"] > .goal-card__row'
MONTH01 = '[data-goal-id="SYNSCH01"] > .goal-card__row'
MONTH02 = '[data-goal-id="SYNSCH02"] > .goal-card__row'
MONTH03 = '[data-goal-id="SYNSCH03"] > .goal-card__row'
MONTH_BODY = '[data-vertical="month"] .pattern-vertical-board__body'
OVERLAY = '[data-role="drag-overlay"]'
INDICATOR = '[data-role="drop-indicator"]'
GRIP = {"x": 50, "y": 6}
REFERENCE_CROSS_COMMIT_MS = 40.3


def _box(page: Page, selector: str) -> dict[str, float]:
    box = page.locator(selector).bounding_box()
    assert box is not None, f"{selector!r} has no box"
    return box


def _begin(page: Page, selector: str, distance: float = 8) -> tuple[dict[str, float], float, float]:
    box = _box(page, selector)
    x, y = box["x"] + GRIP["x"], box["y"] + GRIP["y"]
    page.mouse.move(x, y)
    page.mouse.down()
    page.mouse.move(x + distance, y)
    page.wait_for_timeout(50)
    return box, x, y


def _cancel_at_origin(page: Page, x: float, y: float) -> None:
    page.mouse.move(x, y)
    page.wait_for_timeout(30)
    page.mouse.up()
    page.wait_for_timeout(100)


def _write_recorder(page: Page) -> list[dict[str, Any]]:
    writes: list[dict[str, Any]] = []

    def record(request: Any) -> None:
        path = urlsplit(request.url).path
        if not path.startswith("/api/goals/") or request.method not in {"PUT", "PATCH"}:
            return
        writes.append(
            {"method": request.method, "path": path, "body": request.post_data_json}
        )

    page.on("request", record)
    return writes


def _style(page: Page, selector: str, property_name: str) -> str:
    return page.locator(selector).evaluate(
        "(el, propertyName) => getComputedStyle(el).getPropertyValue(propertyName)",
        property_name,
    )


def _active_transform_targets(page: Page, selectors: list[str]) -> list[str]:
    return page.evaluate(
        """selectors => document.getAnimations().flatMap(animation => {
          const target=animation.effect?.target;
          if (!(target instanceof Element) || !selectors.some(selector => target.matches(selector))) return [];
          const keyframes=animation.effect?.getKeyframes?.() || [];
          return keyframes.some(frame => frame.transform && frame.transform !== 'none')
            ? [target.closest('[data-goal-id]')?.getAttribute('data-goal-id') || 'unknown'] : [];
        })""",
        selectors,
    )


def _drag_to_edge(page: Page, source: str, target: str, edge_fraction: float) -> None:
    _source_box, sx, sy = _begin(page, source)
    target_box = _box(page, target)
    tx = target_box["x"] + min(GRIP["x"], target_box["width"] * 0.45)
    ty = target_box["y"] + target_box["height"] * edge_fraction
    page.mouse.move((sx + tx) / 2, (sy + ty) / 2, steps=5)
    page.mouse.move(tx, ty, steps=5)
    page.wait_for_timeout(50)
    page.mouse.up()
    page.wait_for_timeout(500)


def test_p_02_strict_pointer_threshold(ui_f2: UiSession) -> None:
    page = ui_f2.page
    page.wait_for_selector(ORD01, timeout=10000)
    _source_box, x, y = _begin(page, ORD01, distance=5)
    overlay_at_five = page.locator(OVERLAY).count()
    page.mouse.move(x + 6, y)
    page.wait_for_timeout(50)
    overlay_at_six = page.locator(OVERLAY).count()
    _cancel_at_origin(page, x, y)

    assert overlay_at_five == 0, "exactly 5 CSS px must remain an unarmed click"
    assert overlay_at_six == 1, "6 CSS px must arm one drag overlay"


def test_p_02_hidden_source_and_full_card_visual(ui_f2: UiSession) -> None:
    page = ui_f2.page
    page.wait_for_selector(ORD01, timeout=10000)
    source_box, x, y = _begin(page, ORD01)
    source = page.locator(ORD01)
    overlay = page.locator(OVERLAY)
    overlay_box = overlay.bounding_box()
    opacity = float(source.evaluate("el => getComputedStyle(el).opacity"))
    visibility = source.evaluate("el => getComputedStyle(el).visibility")
    pointer_events = source.evaluate("el => getComputedStyle(el).pointerEvents")
    aria_hidden = source.get_attribute("aria-hidden")
    overlay_pointer_events = overlay.evaluate("el => getComputedStyle(el).pointerEvents")
    overlay_opacity = float(overlay.evaluate("el => getComputedStyle(el).opacity"))
    overlay_shadow = overlay.evaluate("el => getComputedStyle(el).boxShadow")
    cloned_controls = overlay.locator('[data-cap="complete"]').count()
    _cancel_at_origin(page, x, y)

    assert overlay_box is not None, "armed drag must render the complete moving card visual"
    assert abs(overlay_box["width"] - source_box["width"]) <= 1
    assert abs(overlay_box["height"] - source_box["height"]) <= 1
    assert aria_hidden == "true" and (opacity == 0 or visibility == "hidden")
    assert pointer_events == "none", "source footprint must not remain a visible ghost or hit target"
    assert overlay_pointer_events == "none"
    assert overlay_opacity == 1 and overlay_shadow == "none"
    assert cloned_controls == 1, "moving visual must contain the complete rendered card row"


def test_p_02_placeholder_is_invisible_footprint(ui_f2: UiSession) -> None:
    page = ui_f2.page
    page.wait_for_selector(ORD01, timeout=10000)
    # Measured BEFORE the drag arms: once armed, the source card is ghosted and its own box is no
    # longer the footprint that was vacated.
    card_box = _box(page, '[data-goal-id="SYNORD01"]')
    source_box, x, y = _begin(page, ORD01)
    target_box = _box(page, ORD02)
    page.mouse.move(target_box["x"] + 50, target_box["y"] + target_box["height"] * 0.15)
    page.wait_for_timeout(50)
    indicator_count = page.locator(INDICATOR).count()
    indicator_box = page.locator(INDICATOR).bounding_box() if indicator_count else None
    indicator = page.locator(INDICATOR)
    background = _style(page, INDICATOR, "background-color") if indicator_count else None
    shadow = _style(page, INDICATOR, "box-shadow") if indicator_count else None
    border_width = _style(page, INDICATOR, "border-width") if indicator_count else None
    aria_hidden = indicator.get_attribute("aria-hidden") if indicator_count else None
    _cancel_at_origin(page, x, y)

    assert indicator_count == 1 and indicator_box is not None
    # The placeholder reserves the vacated CARD, not the row inside it. Pinning it to the row box
    # (`ORD01` is `... > .goal-card__row`) left it 12px short of the card, so every card below
    # jumped up the instant a drag armed — owner-reported 2026-08-10, measured at -12px, D63.
    # The invariant that matters: picking a card up moves nothing else on the board.
    assert abs(indicator_box["width"] - card_box["width"]) <= 1
    assert abs(indicator_box["height"] - card_box["height"]) <= 1
    assert aria_hidden == "true"
    assert background == "rgba(0, 0, 0, 0)" and shadow == "none"
    assert border_width in {"0px", "0px 0px 0px 0px"}


def test_p_02_source_siblings_resort_live(ui_f2: UiSession) -> None:
    page = ui_f2.page
    page.wait_for_selector(ORD02, timeout=10000)
    before = _box(page, ORD01)
    source_box, x, y = _begin(page, ORD02)
    dom_order_before = page.locator('[data-vertical="week"] > * [data-goal-id]').evaluate_all(
        "els => els.filter(el => !el.parentElement.closest('[data-goal-id]')).map(el => el.dataset.goalId)"
    )
    target = _box(page, ORD01)
    page.mouse.move(target["x"] + GRIP["x"], target["y"] + 2, steps=8)
    page.wait_for_timeout(30)
    animated = _active_transform_targets(page, [
        '[data-goal-id="SYNORD01"]', '[data-goal-id="SYNORD03"]',
    ])
    page.wait_for_timeout(220)
    live = _box(page, ORD01)
    dom_order_during = page.locator('[data-vertical="week"] > * [data-goal-id]').evaluate_all(
        "els => els.filter(el => !el.parentElement.closest('[data-goal-id]')).map(el => el.dataset.goalId)"
    )
    _cancel_at_origin(page, x, y)

    assert animated, "at least one displaced source sibling must animate its transform live"
    assert live["y"] - before["y"] >= source_box["height"] - 2
    assert dom_order_during == dom_order_before, "visual re-sort must precede DOM-order commit"


def test_p_02_destination_siblings_resort_live(ui_f2: UiSession) -> None:
    page = ui_f2.page
    page.wait_for_selector(ORD01, timeout=10000)
    before = {selector: _box(page, selector) for selector in (MONTH01, MONTH02, MONTH03)}
    _source_box, x, y = _begin(page, ORD01)
    target = _box(page, MONTH02)
    page.mouse.move(target["x"] + GRIP["x"], target["y"] + 2, steps=12)
    page.wait_for_timeout(30)
    animated = _active_transform_targets(page, [
        '[data-goal-id="SYNSCH01"]', '[data-goal-id="SYNSCH02"]',
        '[data-goal-id="SYNSCH03"]',
    ])
    page.wait_for_timeout(220)
    live = {selector: _box(page, selector) for selector in (MONTH01, MONTH02, MONTH03)}
    target_shadow = _style(page, MONTH02, "box-shadow")
    _cancel_at_origin(page, x, y)

    assert animated, "destination rows must animate toward their prospective cross-column order"
    assert any(abs(live[s]["y"] - before[s]["y"]) > 1 for s in live)
    assert target_shadow == "none", "cross-column ordering is not a combine highlight"


def test_p_02_cursor_micro_states(ui_f2: UiSession) -> None:
    page = ui_f2.page
    page.wait_for_selector(ORD01, timeout=10000)
    box = _box(page, ORD01)
    x, y = box["x"] + GRIP["x"], box["y"] + GRIP["y"]
    page.mouse.move(x, y)
    hover_cursor = _style(page, ORD01, "cursor")
    page.mouse.down()
    press_cursor = _style(page, ORD01, "cursor")
    press_focus = page.evaluate(
        "() => document.activeElement?.closest('[data-goal-id]')?.getAttribute('data-goal-id')"
    )
    press_outline = _style(page, ORD01, "outline-style")
    page.mouse.move(x + 8, y)
    page.wait_for_timeout(50)
    drag_cursor = _style(page, "body", "cursor")
    drag_focus = page.evaluate("() => document.activeElement?.localName")
    selection = page.evaluate(
        "() => ({type:getSelection()?.type, ranges:getSelection()?.rangeCount, text:String(getSelection() || '')})"
    )
    board_user_select = _style(page, ".pattern-vertical-board", "user-select")
    month = _box(page, MONTH_BODY)
    page.mouse.move(month["x"] + 30, month["y"] + month["height"] * 0.7, steps=8)
    cross_cursor = _style(page, "body", "cursor")
    page.keyboard.press("Escape")
    page.mouse.up()
    page.wait_for_timeout(700)
    settled_cursor = _style(page, "body", "cursor")

    assert hover_cursor == press_cursor == "grab"
    assert drag_cursor == cross_cursor == "grabbing"
    assert settled_cursor == "auto"
    assert press_focus == "SYNORD01" and press_outline == "none"
    assert drag_focus == "body"
    assert selection == {"type": "None", "ranges": 0, "text": ""}
    assert board_user_select == "none"


def test_p_02_full_cast_stability(ui_f2: UiSession) -> None:
    page = ui_f2.page
    page.wait_for_selector(ORD01, timeout=10000)
    columns = page.locator(".pattern-vertical-board__column")
    before_columns = [columns.nth(i).bounding_box() for i in range(columns.count())]
    unrelated_before = _box(page, ORD03)
    _source_box, x, y = _begin(page, ORD01)
    target = _box(page, MONTH02)
    page.mouse.move(target["x"] + GRIP["x"], target["y"] + 2, steps=12)
    page.wait_for_timeout(250)
    after_columns = [columns.nth(i).bounding_box() for i in range(columns.count())]
    unrelated_after = _box(page, ORD03)
    column_opacities = [
        float(columns.nth(i).evaluate("el => getComputedStyle(el).opacity"))
        for i in range(columns.count())
    ]
    _cancel_at_origin(page, x, y)

    assert before_columns == after_columns and column_opacities == [1.0] * columns.count()
    assert unrelated_after["x"] == unrelated_before["x"]


def test_p_02_drop_settle_animation_and_cleanup(ui_f2: UiSession) -> None:
    page = ui_f2.page
    page.wait_for_selector(ORD01, timeout=10000)
    source_box, x, y = _begin(page, ORD01)
    target = _box(page, MONTH02)
    page.mouse.move(target["x"] + GRIP["x"], target["y"] + 2, steps=12)
    page.keyboard.press("Escape")
    page.wait_for_timeout(20)
    timings = page.locator(OVERLAY).evaluate(
        """el => el.getAnimations().map(animation => {
          const timing=animation.effect.getTiming();
          return {
            duration:timing.duration,
            easing:getComputedStyle(animation.effect.target).transitionTimingFunction
          };
        })"""
    )
    page.mouse.up()
    page.wait_for_timeout(650)
    source = page.locator(ORD01)

    assert timings and all(330 <= row["duration"] <= 550 for row in timings)
    assert all(
        set(split_css_list(row["easing"])) == {"cubic-bezier(0.2, 1, 0.1, 1)"}
        for row in timings
    )
    assert page.locator(OVERLAY).count() == 0
    assert abs(_box(page, ORD01)["x"] - source_box["x"]) <= 1
    assert float(source.evaluate("el => getComputedStyle(el).opacity")) == 1
    assert source.evaluate("el => getComputedStyle(el).pointerEvents") != "none"


def test_p_02_cross_column_request_shape(ui_f2: UiSession) -> None:
    session = ui_f2
    page = session.page
    page.wait_for_selector(ORD01, timeout=10000)
    writes = _write_recorder(page)

    session.gestures.drag(ORD01, MONTH_BODY, source_position=GRIP, target_position=GRIP)
    page.wait_for_timeout(500)

    # ONE write, no refetch — the law this scenario exists to hold. The body carries the ordered
    # slot as well as the destination since the 2026-08-10 owner report ("place it first place to
    # the other column before other card ... goes to the end"): a drop names a column AND a place
    # in it, and splitting that into two requests would put a second round-trip inside the drop
    # tail FIDELITY.md dimension 8 measures. `position`/`after_id` is asserted as *whatever slot
    # this drop actually released over*, not pinned to one value, because the gesture's landing
    # row is geometry, not a constant.
    assert len(writes) == 1, f"a cross-column drop must be one write, got {writes}"
    write = writes[0]
    assert write["method"] == "PUT"
    assert write["path"] == "/api/goals/SYNORD01/schedule"
    body = dict(write["body"])
    ordering = {k: body.pop(k) for k in ("position", "after_id") if k in body}
    assert body == {"vertical": "month", "anchor_date": "2026-08-08"}
    assert len(ordering) <= 1, f"position and after_id are one reorder, not two: {ordering}"


def test_p_02_drop_tail_commits_within_reference_without_refetch(ui_f2: UiSession) -> None:
    page = ui_f2.page
    page.wait_for_selector(ORD01, timeout=10000)
    page.evaluate(
        """({sourceId, destinationVertical}) => {
          const tail={pointerUpAt:null,firstCommitAt:null,requests:[]};
          const originalFetch=window.fetch;
          window.fetch=async function(input, init) {
            const method=String(init?.method || input?.method || 'GET').toUpperCase();
            const url=typeof input === 'string' ? input : (input?.url || String(input));
            const request={method,url,startAt:performance.now(),endAt:null};
            tail.requests.push(request);
            try {
              const response=await originalFetch.apply(this, arguments);
              request.endAt=performance.now();
              return response;
            } catch (error) {
              request.endAt=performance.now();
              throw error;
            }
          };
          const committed = () => document
            .querySelector(`[data-goal-id="${CSS.escape(sourceId)}"]`)
            ?.closest('.pattern-vertical-board__column')
            ?.getAttribute('data-vertical') === destinationVertical;
          const observer=new MutationObserver(() => {
            if (tail.pointerUpAt !== null && tail.firstCommitAt === null && committed()) {
              tail.firstCommitAt=performance.now();
            }
          });
          observer.observe(document.querySelector('.pattern-vertical-board'), {
            subtree:true,childList:true,attributes:true,characterData:true,
          });
          document.addEventListener('pointerup', event => {
            tail.pointerUpAt=event.timeStamp;
            if (committed()) tail.firstCommitAt=performance.now();
          }, {capture:true,once:true});
          window.__p02DropTail=tail;
        }""",
        {"sourceId": "SYNORD01", "destinationVertical": "month"},
    )

    source = _box(page, ORD01)
    destination = _box(page, MONTH_BODY)
    sx, sy = source["x"] + GRIP["x"], source["y"] + GRIP["y"]
    page.mouse.move(sx, sy)
    page.mouse.down()
    page.mouse.move(sx + 8, sy)
    page.mouse.move(
        destination["x"] + GRIP["x"],
        destination["y"] + GRIP["y"],
        steps=12,
    )
    page.mouse.up()
    page.wait_for_function("window.__p02DropTail.firstCommitAt !== null", timeout=2000)
    page.wait_for_timeout(500)
    tail = page.evaluate(
        """() => ({
          commitMs:window.__p02DropTail.firstCommitAt-window.__p02DropTail.pointerUpAt,
          boardRefetches:window.__p02DropTail.requests.filter(request =>
            request.startAt >= window.__p02DropTail.pointerUpAt
            && request.method === 'GET'
            && new URL(request.url, location.href).pathname === '/api/board'
          ).length,
        })"""
    )
    failures = []
    if tail["commitMs"] > REFERENCE_CROSS_COMMIT_MS:
        failures.append(
            f"committed placement took {tail['commitMs']:.1f} ms; reference is "
            f"{REFERENCE_CROSS_COMMIT_MS:.1f} ms"
        )
    if tail["boardRefetches"]:
        failures.append(f"drop tail issued {tail['boardRefetches']} GET /api/board refetch")
    assert not failures, "; ".join(failures)


def test_p_02_reorder_after_id_request_shape(ui_f2: UiSession) -> None:
    page = ui_f2.page
    page.wait_for_selector(ORD01, timeout=10000)
    writes = _write_recorder(page)

    _drag_to_edge(page, ORD01, ORD02, edge_fraction=0.85)

    assert writes == [
        {
            "method": "PATCH",
            "path": "/api/goals/SYNORD01",
            "body": {"after_id": "SYNORD02"},
        }
    ]


def test_p_02_reorder_first_request_shape(ui_f2: UiSession) -> None:
    page = ui_f2.page
    page.wait_for_selector(ORD01, timeout=10000)
    writes = _write_recorder(page)

    _drag_to_edge(page, ORD02, ORD01, edge_fraction=0.15)

    assert writes == [
        {
            "method": "PATCH",
            "path": "/api/goals/SYNORD02",
            "body": {"position": "first"},
        }
    ]


def test_p_02_alt_combine_reparents(ui_f2: UiSession) -> None:
    page = ui_f2.page
    page.wait_for_selector(ORD01, timeout=10000)
    writes = _write_recorder(page)
    _source_box, _sx, _sy = _begin(page, ORD01)

    for fraction in (0.08, 0.5, 0.92):
        target = _box(page, ORD03)
        tx = target["x"] + min(GRIP["x"], target["width"] * 0.45)
        ty = target["y"] + target["height"] * fraction
        page.mouse.move(tx, ty, steps=6)
        page.wait_for_timeout(50)

        assert page.locator(INDICATOR).count() == 1, (
            f"plain hover at {fraction:.0%} must remain an ordered slot"
        )
        assert page.locator("[data-dnd-combine-target]").count() == 0

        page.keyboard.down("Alt")
        page.wait_for_timeout(50)
        assert page.locator(INDICATOR).count() == 0, (
            f"Alt hover at {fraction:.0%} must remove the ordering footprint"
        )
        assert page.locator('[data-goal-id="SYNORD03"] > [data-dnd-combine-target]').count() == 1

        page.keyboard.up("Alt")
        page.wait_for_timeout(50)
        assert page.locator(INDICATOR).count() == 1, "releasing Alt must restore sortable targeting"
        assert page.locator("[data-dnd-combine-target]").count() == 0

    target = _box(page, ORD03)
    page.mouse.move(
        target["x"] + min(GRIP["x"], target["width"] * 0.45),
        target["y"] + target["height"] * 0.5,
        steps=6,
    )
    page.keyboard.down("Alt")
    page.wait_for_timeout(50)
    page.mouse.up()
    page.keyboard.up("Alt")
    page.wait_for_timeout(500)

    assert writes == [
        {
            "method": "PUT",
            "path": "/api/goals/SYNORD01/parent",
            "body": {"parent_id": "SYNORD03"},
        }
    ]


def test_p_02_pickup_moves_nothing_else_on_the_board(ui_f2: UiSession) -> None:
    """Owner ruling 2026-08-10 (D63): a drag vacates exactly the footprint it occupied.

    The placeholder used to be built from the dragged ROW's box while the card it replaced is
    that row plus 6px of card padding on every side — so arming a drag collapsed the column by
    12px and every card below jumped up under the pointer. Measured before the fix: card 78,
    placeholder 66, siblings -12.0px. Nothing on the board may move until the pointer does.
    """
    page = ui_f2.page
    page.wait_for_selector(ORD01, timeout=10000)
    siblings = page.evaluate(
        "() => Array.from(document.querySelectorAll('[data-vertical=\"week\"] [data-goal-id]'))"
        ".filter(e => e.parentElement.closest('[data-goal-id]') === null)"
        ".map(e => e.dataset.goalId)"
    )
    below = [g for g in siblings if g != "SYNORD01"]
    tops_before = page.evaluate(
        "(ids) => ids.map(id => document.querySelector(`[data-goal-id=\"${id}\"]`)"
        ".getBoundingClientRect().top)",
        below,
    )
    card_box = _box(page, '[data-goal-id="SYNORD01"]')

    _, x, y = _begin(page, ORD01)
    page.mouse.move(x, y)  # back to the exact grab point: the card is "still where it was"
    page.wait_for_timeout(60)
    tops_during = page.evaluate(
        "(ids) => ids.map(id => document.querySelector(`[data-goal-id=\"${id}\"]`)"
        ".getBoundingClientRect().top)",
        below,
    )
    indicator_box = page.locator(INDICATOR).bounding_box()
    _cancel_at_origin(page, x, y)

    assert indicator_box is not None
    assert abs(indicator_box["height"] - card_box["height"]) <= 1
    assert abs(indicator_box["width"] - card_box["width"]) <= 1
    shifts = [round(after - before, 1) for before, after in zip(tops_before, tops_during)]
    assert all(abs(s) <= 1 for s in shifts), f"cards below moved on pick-up: {shifts}"
