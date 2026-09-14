"""P-27: card-subtree expand/collapse entry, topology, reflow, motion, and lifetime."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from playwright.sync_api import Locator, Page

from tests.ui.conftest import UiSession


ROOT = Path(__file__).resolve().parents[2]
GOAL_CARD_SOURCE = ROOT / "web/src/components/GoalCard.vue"
STORE_SOURCE = ROOT / "web/src/store.ts"
PARENT = '[data-goal-id="SYNDAY01"]'
ROW = f"{PARENT} > .goal-card__row"
TOGGLE = f'{ROW} [data-role="subgoal-toggle"]'
ARROW = f'{TOGGLE} [data-role="subgoal-arrow"]'
SUBTREE = f"{PARENT} > .goal-card__children"
CHILD = '[data-goal-id="SYNSUB01"]'
LEAF = '[data-goal-id="SYNCOL01"]'
CURVE = "cubic-bezier(0.165, 0.84, 0.44, 1)"


def _box(locator: Locator) -> dict[str, float]:
    box = locator.bounding_box()
    assert box is not None
    return box


def _style(locator: Locator, name: str) -> str:
    return locator.evaluate("(el,name)=>getComputedStyle(el).getPropertyValue(name)", name)


def _mutating_requests(session: UiSession, start: int) -> list[dict[str, Any]]:
    return [
        request for request in session.request_log[start:]
        if request["method"] not in {"GET", "HEAD", "OPTIONS"}
    ]


def _set_collapsed(page: Page) -> None:
    page.wait_for_selector(TOGGLE)
    if page.locator(TOGGLE).get_attribute("aria-expanded") == "true":
        page.locator(TOGGLE).click()
        page.wait_for_timeout(320)
    assert page.locator(SUBTREE).count() == 0


def _cast(page: Page) -> dict[str, Any]:
    return page.locator(PARENT).evaluate(
        """parent => {
          const rect=el=>{const r=el.getBoundingClientRect();
            return {x:r.x,y:r.y,width:r.width,height:r.height}};
          const stack=parent.parentElement;
          const cards=[...stack.children].filter(el=>el.matches('.goal-card'));
          const at=cards.indexOf(parent);
          const scrollOwner=parent.closest('[data-role="period-slide"]');
          return {parent:rect(parent),row:rect(parent.querySelector(':scope > .goal-card__row')),
            following:cards.slice(at+1).map(el=>({rect:rect(el),transform:getComputedStyle(el).transform,
              opacity:getComputedStyle(el).opacity,animations:el.getAnimations({subtree:true}).length})),
            scrollOwner:{scrollTop:scrollOwner.scrollTop,scrollHeight:scrollOwner.scrollHeight,
              clientHeight:scrollOwner.clientHeight,overflowY:getComputedStyle(scrollOwner).overflowY}};
        }"""
    )


def _arrow_animations(page: Page) -> list[dict[str, Any]]:
    return page.locator(ARROW).evaluate(
        """el=>el.getAnimations().map(a=>({
          duration:a.effect.getTiming().duration,
          easing:getComputedStyle(a.effect.target).transitionTimingFunction,
          keyframes:a.effect.getKeyframes().map(k=>k.transform)
        }))"""
    )


def test_p_27_entry_marker_hit_area_and_leaf_absence(ui_f2: UiSession) -> None:
    page = ui_f2.page
    _set_collapsed(page)
    toggle, arrow = page.locator(TOGGLE), page.locator(ARROW)
    row = page.locator(ROW)
    checkbox, title = row.locator(".goal-card__checkbox"), row.locator(".goal-card__title")
    svg, path = arrow.locator("svg"), arrow.locator("path")

    assert toggle.evaluate("el=>el.tagName") == "BUTTON"  # accessibility adaptation
    assert (_box(arrow)["width"], _box(arrow)["height"]) == (12, 12)
    assert _style(arrow, "margin-left") == "4px"
    assert _style(arrow, "top") == "2px"
    assert _style(toggle, "height") == "18px"
    assert _style(toggle, "padding") == "0px"
    assert _style(toggle, "cursor") == "pointer"
    assert _style(arrow, "color") == _style(toggle, "color")
    assert abs(_box(toggle)["x"] - _box(title)["x"]) <= 1
    assert abs((_box(toggle)["x"] - _box(checkbox)["x"]) - 28) <= 1
    assert _box(toggle)["width"] >= _box(arrow)["width"] + 4
    assert page.locator(f"{LEAF} [data-role='subgoal-toggle']").count() == 0

    # M7: exact rounded reference chevron, not a merely similar 12px triangle.
    assert svg.get_attribute("viewBox") == "0 0 24 24"
    assert path.get_attribute("d") == "M15 5L8 12L15 19"
    assert path.get_attribute("stroke") == "currentColor"
    assert path.get_attribute("stroke-width") == "2"
    assert path.get_attribute("stroke-linecap") == "round"
    assert path.get_attribute("stroke-linejoin") == "round"
    assert path.get_attribute("fill") == "none"


def test_p_27_toggle_inserts_removes_dom_and_never_writes(ui_f2: UiSession) -> None:
    page = ui_f2.page
    _set_collapsed(page)
    page.evaluate(
        """selector=>{
          const parent=document.querySelector(selector); window.__p27Mutations=[];
          window.__p27Observer=new MutationObserver(ms=>{
            for(const m of ms) if(m.type==='childList' && m.target===parent)
              window.__p27Mutations.push({added:[...m.addedNodes].map(n=>n.nodeType===1?n.className:'#comment'),
                removed:[...m.removedNodes].map(n=>n.nodeType===1?n.className:'#comment')});
          });
          window.__p27Observer.observe(parent,{childList:true});
        }""",
        PARENT,
    )
    start = len(ui_f2.request_log)
    page.locator(TOGGLE).click()
    page.wait_for_selector(CHILD)
    expanded_mutations = page.evaluate("window.__p27Mutations")
    assert page.locator(SUBTREE).count() == 1
    assert any("goal-card__children" in " ".join(m["added"]) for m in expanded_mutations)

    page.evaluate("window.__p27Mutations=[]")
    page.locator(TOGGLE).click()
    assert page.locator(SUBTREE).count() == 0
    collapsed_mutations = page.evaluate("window.__p27Mutations")
    assert any("goal-card__children" in " ".join(m["removed"]) for m in collapsed_mutations)
    assert _mutating_requests(ui_f2, start) == []


def test_p_27_parent_fixed_and_full_cast_jumps_one_delta(ui_f2: UiSession) -> None:
    page = ui_f2.page
    page.emulate_media(reduced_motion="no-preference")
    _set_collapsed(page)
    before = _cast(page)
    page.locator(TOGGLE).click()
    page.wait_for_selector(CHILD)
    after = _cast(page)
    subtree_height = _box(page.locator(SUBTREE))["height"]
    # Flow delta includes the subtree's 202px border box plus its 2px/16px block margins.
    subtree_flow_delta = subtree_height + 2 + 16

    assert after["row"] == before["row"], "parent's own box must not move or resize"
    assert abs((after["parent"]["height"] - before["parent"]["height"]) - subtree_flow_delta) <= 1
    assert len(after["following"]) == len(before["following"]) > 1
    shifts = [
        after_row["rect"]["y"] - before_row["rect"]["y"]
        for before_row, after_row in zip(before["following"], after["following"], strict=True)
    ]
    assert all(abs(shift - subtree_flow_delta) <= 1 for shift in shifts)
    assert all(row["transform"] == "none" and row["opacity"] == "1" for row in after["following"])
    assert all(row["animations"] == 0 for row in after["following"])


def test_p_27_period_slide_owns_overflow_range_and_clamps_scrolltop(ui_f2: UiSession) -> None:
    page = ui_f2.page
    _set_collapsed(page)
    before = _cast(page)
    page.locator(TOGGLE).click()
    page.wait_for_selector(CHILD)
    expanded = _cast(page)
    assert before["scrollOwner"]["scrollHeight"] == 779
    assert expanded["scrollOwner"]["scrollHeight"] == 820
    assert expanded["scrollOwner"]["overflowY"] == "auto"
    assert expanded["scrollOwner"]["scrollHeight"] > expanded["scrollOwner"]["clientHeight"]
    assert _style(page.locator('[data-vertical="day"]'), "overflow-y") == "hidden"

    scroll_owner = page.locator(
        '[data-vertical="day"] [data-role="period-slide"][data-state="current"]'
    )
    scroll_owner.evaluate("el=>el.scrollTop=20")
    assert scroll_owner.evaluate("el=>el.scrollTop") == 20
    page.locator(TOGGLE).evaluate("el=>el.click()")  # no Playwright auto-scroll
    collapsed = _cast(page)
    assert collapsed["scrollOwner"]["scrollTop"] == 0
    assert collapsed["scrollOwner"]["scrollHeight"] == 779


def test_p_27_motion_table_normal_and_reduced(ui_f2: UiSession) -> None:
    page = ui_f2.page
    page.emulate_media(reduced_motion="no-preference")
    _set_collapsed(page)
    page.locator(TOGGLE).click()
    assert _arrow_animations(page) == [{
        "duration": 300, "easing": CURVE,
        "keyframes": ["rotate(270deg)", "rotate(90deg)"],
    }]
    assert page.locator(SUBTREE).evaluate("el=>el.getAnimations().length") == 0
    page.wait_for_timeout(320)
    page.locator(TOGGLE).click()
    assert _arrow_animations(page) == [{
        "duration": 250, "easing": CURVE,
        "keyframes": ["rotate(90deg)", "rotate(270deg)"],
    }]

    # D21: explicit reduced-motion half. Reference has no reduced override for this arrow.
    page.wait_for_timeout(270)
    page.emulate_media(reduced_motion="reduce")
    page.locator(TOGGLE).click()
    assert _arrow_animations(page) == [{
        "duration": 300, "easing": CURVE,
        "keyframes": ["rotate(270deg)", "rotate(90deg)"],
    }]


def test_p_27_pointer_hover_focus_and_keyboard(ui_f2: UiSession) -> None:
    page = ui_f2.page
    _set_collapsed(page)
    toggle = page.locator(TOGGLE)
    before = {
        "box": _box(toggle),
        "color": _style(toggle, "color"),
        "background": _style(toggle, "background-color"),
        "opacity": _style(toggle, "opacity"),
    }
    toggle.hover()
    assert _box(toggle) == before["box"]
    assert _style(toggle, "cursor") == "pointer"
    assert _style(toggle, "color") == before["color"]
    assert _style(toggle, "background-color") == before["background"]
    assert _style(toggle, "opacity") == before["opacity"]

    start = len(ui_f2.request_log)
    toggle.focus()
    assert toggle.evaluate("el=>document.activeElement===el")
    page.keyboard.press("Space")
    assert toggle.get_attribute("aria-expanded") == "true" and page.locator(SUBTREE).count() == 1
    assert toggle.evaluate("el=>document.activeElement===el")
    page.keyboard.press("Enter")
    assert toggle.get_attribute("aria-expanded") == "false" and page.locator(SUBTREE).count() == 0
    assert _mutating_requests(ui_f2, start) == []


def test_p_27_component_lifetime_persistence(ui_f2: UiSession) -> None:
    page = ui_f2.page
    _set_collapsed(page)
    page.locator(TOGGLE).click()
    assert page.locator(TOGGLE).get_attribute("aria-expanded") == "true"

    # D37: app-global reactive expansion survives Board unmount/remount.
    page.locator('[data-nav-item="inbox"]').click()
    page.wait_for_selector(".inbox-view")
    page.locator('[data-nav-item="verticals"]').click()
    page.wait_for_selector(TOGGLE)
    assert page.locator(TOGGLE).get_attribute("aria-expanded") == "true"

    store_source = STORE_SOURCE.read_text()
    component_source = GOAL_CARD_SOURCE.read_text()
    assert "expanded: string[]" in store_source
    assert "state.expanded" in store_source
    assert "localStorage" not in store_source and "sessionStorage" not in store_source
    assert 'v-if="children.length && !isCollapsed"' in component_source

    page.reload()
    page.wait_for_selector(TOGGLE)
    assert page.locator(TOGGLE).get_attribute("aria-expanded") == "false"
