"""P-21: shared popover positioning, topology, lifecycle, motion, and nesting contract."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from playwright.sync_api import Page

from tests.ui.conftest import UiSession
from tools.parity.probe_p21_popover import decode_reference


DETAIL_CARD = '[data-goal-id="SYNSCH01"] > .goal-card__row'
TRIGGER = '[data-cap="schedule"]'
OPEN_SURFACE = '[data-popover-surface][data-state="open"], .dropdown__popover[data-state="open"]'
ITEM = f':is({OPEN_SURFACE}) [role="menuitem"]'
PORTAL = "#dropdownPortal"
POPOVER_ENGINE = Path(__file__).resolve().parents[2] / "web/src/components/PopoverEngine.vue"


def _open_detail(session: UiSession) -> Page:
    page = session.page
    page.locator(DETAIL_CARD).wait_for(state="visible", timeout=10_000)
    page.locator(DETAIL_CARD).click(position={"x": 80, "y": 20})
    page.locator(".modal__dialog").wait_for(state="visible", timeout=5_000)
    page.locator(TRIGGER).wait_for(state="visible")
    page.wait_for_timeout(220)
    return page


def _open(page: Page) -> Any:
    page.locator(TRIGGER).click()
    surface = page.locator(OPEN_SURFACE).first
    surface.wait_for(state="visible", timeout=2_000)
    return surface


def _rect(page: Page, selector: str) -> dict[str, float]:
    box = page.locator(selector).first.bounding_box()
    assert box is not None, f"{selector!r} has no rectangle"
    return box


def _computed(page: Page, selector: str) -> dict[str, str]:
    return page.locator(selector).first.evaluate(
        """el => { const s=getComputedStyle(el); return {
          position:s.position, zIndex:s.zIndex, minWidth:s.minWidth, maxHeight:s.maxHeight,
          overflow:s.overflow, padding:s.padding, border:s.border, borderRadius:s.borderRadius,
          background:s.backgroundColor, boxShadow:s.boxShadow, userSelect:s.userSelect,
          animationName:s.animationName, animationDuration:s.animationDuration,
          animationTimingFunction:s.animationTimingFunction, cursor:s.cursor}; }"""
    )


def test_p_21_reference_placement_spec_from_pinned_bundles() -> None:
    """ASSERT A1: pinned public assets mechanically encode the reusable placement algorithm."""
    reference = decode_reference()
    engine = reference["engine"]
    assert engine["strategy"] == "absolute transform coordinates"
    assert engine["default_placement"] == (
        "auto across top/right/bottom/left and start/end variants"
    )
    assert engine["explicit_placement_fallback"] == "flip bestFit with main and cross axes"
    assert engine["shift"] == {"padding_css_px": 8, "main_axis": True, "cross_axis": False}
    assert engine["offset"] == {
        "root_main_css_px": 4,
        "root_alignment_css_px": 0,
        "nested_main_css_px": 4,
        "nested_alignment_css_px": -8,
    }
    assert engine["size"] == {
        "collision_padding_css_px": 8,
        "max_height_subtraction_css_px": 16,
    }
    assert engine["updates"] == [
        "ancestor scroll", "ancestor resize", "element resize", "layout shift"
    ]


def test_p_21_root_opens_on_mousedown_and_uses_portal(ui_f2: UiSession) -> None:
    """ASSERT A2+A4: root topology, open phase, entry target, portal, and scrim absence."""
    page = _open_detail(ui_f2)
    trigger = page.locator(TRIGGER)
    box = _rect(page, TRIGGER)
    page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
    page.mouse.down()
    try:
        page.wait_for_timeout(20)
        surface = page.locator(OPEN_SURFACE).first
        assert surface.count() == 1 and surface.is_visible(), "root must open on mousedown"
        assert page.locator(PORTAL).count() == 1
        assert surface.evaluate("el => el.closest('#dropdownPortal') !== null")
        assert surface.get_attribute("role") == "menu"
        assert surface.get_attribute("data-popover-surface") is not None
        assert trigger.get_attribute("data-is-menu-reference") == "true"
        assert "Menu-target" in (trigger.get_attribute("class") or "")
        assert "_open" in (trigger.get_attribute("class") or "")
        assert page.locator(f"{PORTAL} .dropdown__scrim, {PORTAL} [data-role='scrim']").count() == 0
    finally:
        page.mouse.up()


def test_p_21_surface_geometry_and_layer(ui_f2: UiSession) -> None:
    """ASSERT A3: engine-owned surface geometry matches the reference menu layer."""
    page = _open_detail(ui_f2)
    _open(page)
    style = _computed(page, OPEN_SURFACE)
    width = _rect(page, OPEN_SURFACE)["width"]
    assert style["position"] == "absolute"
    assert style["zIndex"] == "5000"
    assert width >= 200
    assert style["padding"] == "8px 0px"
    assert style["borderRadius"] == "4px"
    assert style["background"] == "rgb(27, 27, 27)"
    assert style["boxShadow"] in {
        "rgba(0, 0, 0, 0.35) 0px 2px 9px 0px",
        "rgba(0, 0, 0, 0.35) 0px 2px 9px",
    }
    assert style["overflow"] == "auto"
    assert style["userSelect"] == "none"


def test_p_21_edge_collision_and_live_anchor_reconciliation(ui_f2: UiSession) -> None:
    """ASSERT A1+A8: clamp at 8px and update on layout shift without reopening."""
    page = _open_detail(ui_f2)
    anchor = page.locator(".schedule-popover-anchor").first
    anchor.evaluate(
        "el => {el.style.position='fixed';el.style.left='1200px';el.style.top='700px';"
        "el.style.zIndex='1000'}"
    )
    surface = _open(page)
    page.wait_for_timeout(60)
    first = _rect(page, OPEN_SURFACE)
    viewport = page.evaluate("({width:innerWidth,height:innerHeight})")
    assert first["x"] >= 8
    assert first["y"] >= 8
    assert first["x"] + first["width"] <= viewport["width"] - 8 + 1
    assert first["y"] + first["height"] <= viewport["height"] - 8 + 1
    placement = surface.get_attribute("data-placement")
    assert placement in {
        "top", "top-start", "top-end", "right", "right-start", "right-end",
        "bottom", "bottom-start", "bottom-end", "left", "left-start", "left-end",
    }

    anchor.evaluate("el => {el.style.left='100px';el.style.top='100px'}")
    page.wait_for_timeout(100)
    moved = _rect(page, OPEN_SURFACE)
    assert abs(moved["x"] - first["x"]) > 50 or abs(moved["y"] - first["y"]) > 50
    assert moved["x"] >= 8 and moved["y"] >= 8
    assert moved["x"] + moved["width"] <= viewport["width"] - 8 + 1
    assert moved["y"] + moved["height"] <= viewport["height"] - 8 + 1


def test_p_21_outside_pointerdown_and_escape_are_isolated(ui_f2: UiSession) -> None:
    """ASSERT A4: pointerdown/Escape close only the root menu and Escape restores trigger."""
    page = _open_detail(ui_f2)
    surface = _open(page)
    assert surface.evaluate("el => el === document.activeElement")
    page.locator(".modal__body").dispatch_event("pointerdown")
    page.wait_for_timeout(30)
    assert page.locator(OPEN_SURFACE).count() == 0, "outside pointerdown must unmount surface"
    assert page.locator(".modal__dialog").is_visible(), "menu dismissal must not close consumer"
    assert not page.locator(TRIGGER).evaluate("el => el === document.activeElement")

    surface = _open(page)
    assert surface.evaluate("el => el === document.activeElement")
    page.keyboard.press("ArrowDown")
    assert page.locator(ITEM).first.evaluate("el => el === document.activeElement")
    page.keyboard.press("Escape")
    page.wait_for_timeout(30)
    assert page.locator(OPEN_SURFACE).count() == 0
    assert page.locator(".modal__dialog").is_visible(), "Escape must not bubble into outer modal"
    assert page.locator(TRIGGER).evaluate("el => el === document.activeElement")


def test_p_21_motion_is_opacity_only_and_reduced_motion_is_none(ui_f2: UiSession) -> None:
    """ASSERT A5: exact entry motion, immediate exit, and reduced-motion rule."""
    page = _open_detail(ui_f2)
    page.emulate_media(reduced_motion="no-preference")
    surface = _open(page)
    animations = surface.evaluate(
        """el => el.getAnimations().map(a => ({
          timing:a.effect.getTiming(), frames:a.effect.getKeyframes().map(f => ({
            opacity:f.opacity ?? null, transform:f.transform ?? null, easing:f.easing}))}))"""
    )
    assert len(animations) == 1
    animation = animations[0]
    assert animation["timing"]["duration"] == 120
    assert [frame["opacity"] for frame in animation["frames"]] == ["0", "1"]
    assert all(frame["transform"] is None for frame in animation["frames"])
    assert all(frame["easing"] == "ease-out" for frame in animation["frames"])
    page.keyboard.press("Escape")
    page.wait_for_timeout(20)
    assert page.locator(OPEN_SURFACE).count() == 0, "exit has no retained leave-animation node"

    page.emulate_media(reduced_motion="reduce")
    _open(page)
    reduced_style = _computed(page, OPEN_SURFACE)
    assert reduced_style["animationName"] == "none"


def test_p_21_full_cast_and_microstates(ui_f2: UiSession) -> None:
    """ASSERT A6: target, consumer, viewport, and body remain stable around portal insertion."""
    page = _open_detail(ui_f2)
    before = {
        "trigger": _rect(page, TRIGGER),
        "modal": _rect(page, ".modal__dialog"),
        "body_overflow": page.evaluate("getComputedStyle(document.body).overflow"),
        "scroll": page.evaluate("({x:scrollX,y:scrollY})"),
    }
    _open(page)
    page.wait_for_timeout(130)
    after = {
        "trigger": _rect(page, TRIGGER),
        "modal": _rect(page, ".modal__dialog"),
        "body_overflow": page.evaluate("getComputedStyle(document.body).overflow"),
        "scroll": page.evaluate("({x:scrollX,y:scrollY})"),
    }
    for actor in ("trigger", "modal"):
        for key in ("x", "y", "width", "height"):
            assert abs(after[actor][key] - before[actor][key]) <= 1
    assert after["body_overflow"] == before["body_overflow"]
    assert after["scroll"] == before["scroll"]
    assert page.locator(TRIGGER).evaluate("el => getComputedStyle(el).cursor") == "pointer"
    assert page.locator(OPEN_SURFACE).evaluate("el => getComputedStyle(el).userSelect") == "none"


def test_p_21_nested_and_inline_reference_contract() -> None:
    """ASSERT A7: pinned facts and our engine cover every nested lifecycle branch."""
    mechanics = decode_reference()["mechanics"]
    assert mechanics["nested_default_placement"] == "right"
    assert mechanics["nested_mouse_open_delay_ms"] == 75
    assert mechanics["nested_safe_polygon"] is True
    assert mechanics["nested_safe_polygon_blocks_pointer_events"] is True
    assert mechanics["inline_viewport_width_below_css_px"] == 694
    assert mechanics["inline_child_reuses_root_anchor"] is True
    assert mechanics["inline_child_hides_parent_and_adds_back_item"] is True

    source = POPOVER_ENGINE.read_text()
    assert "parentState.activeChild?.close()" in source, "a sibling did not replace the open child"
    assert "popover-safe-pointer-block" in source and "pointInSafePolygon" in source
    assert "if (parentState.activeChild && !parentState.activeChild.inline) return" in source
    assert 'class="dropdown__item popover-engine__back"' in source and "backToParent" in source


def test_p_21_engine_gestures_never_write(ui_f2: UiSession) -> None:
    """ASSERT A8: opening and dismissing the engine generate no goal mutation to reconcile."""
    page = _open_detail(ui_f2)
    n0 = len(ui_f2.request_log)
    _open(page)
    page.locator(".modal__body").dispatch_event("click")
    page.wait_for_timeout(30)
    writes = [
        request for request in ui_f2.request_log[n0:]
        if request["method"] in {"POST", "PUT", "PATCH", "DELETE"}
        and "/api/goals" in request["url"]
    ]
    assert writes == []
