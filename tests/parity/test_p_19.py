"""P-19: measured card hover, overflow actions, writes, and completion."""

from __future__ import annotations

import time
from typing import Any, Callable
from urllib.parse import urlsplit

from playwright.sync_api import Page

from tests.ui.conftest import UiSession


GOAL = "SYNORD01"
CARD = f'[data-goal-id="{GOAL}"]'
ROW = f"{CARD} > .goal-card__row"
TRIGGER = f'{CARD} [data-role="goal-actions-trigger"]'
MENU = '[data-role="goal-actions-menu"]'


def _box(page: Page, selector: str) -> dict[str, float]:
    box = page.locator(selector).bounding_box()
    assert box is not None, f"{selector!r} has no visible box"
    return box


def _style(page: Page, selector: str, name: str) -> str:
    return page.locator(selector).evaluate(
        "(el, propertyName) => getComputedStyle(el).getPropertyValue(propertyName)", name
    )


def _open_menu(page: Page, card: str = CARD) -> None:
    trigger = page.locator(f'{card} [data-role="goal-actions-trigger"]')
    trigger.hover()
    trigger.click()
    page.locator(MENU).wait_for(state="visible")


def _install_trace(page: Page, goal_id: str) -> None:
    page.evaluate(
        """goalId => {
          window.__p19Trace=[];
          const push=(kind, extra={}) => window.__p19Trace.push({kind, at:performance.now(), ...extra});
          const sample=kind => {
            const card=document.querySelector(`[data-goal-id="${CSS.escape(goalId)}"]`);
            const parent=card?.parentElement?.closest?.('[data-goal-id]');
            push(kind, {
              exists:!!card,
              vertical:card?.closest('[data-vertical]')?.getAttribute('data-vertical') ?? null,
              parentId:card?.getAttribute('data-parent-id') ?? parent?.getAttribute('data-goal-id') ?? null,
              background:card ? getComputedStyle(card).backgroundColor : null,
              checked:card?.querySelector('[data-cap="complete"]')?.getAttribute('aria-checked') ?? null,
            });
          };
          document.addEventListener('pointerup', () => push('pointerup'), true);
          new MutationObserver(() => sample('dom')).observe(document.body, {
            subtree:true, childList:true, attributes:true,
            attributeFilter:['class','style','checked','aria-checked','data-parent-id']
          });
          const realFetch=window.fetch.bind(window);
          window.fetch=async (input, init={}) => {
            const raw=typeof input === 'string' ? input : input.url;
            const url=new URL(raw, location.href);
            let body=null;
            try { body=init.body ? JSON.parse(init.body) : null; } catch {}
            const method=(init.method || (typeof input === 'string' ? 'GET' : input.method) || 'GET').toUpperCase();
            push('request', {method, path:url.pathname, query:url.search, body});
            const response=await realFetch(input, init);
            push('response', {method, path:url.pathname, status:response.status});
            return response;
          };
          sample('installed');
        }""",
        goal_id,
    )


def _trace(page: Page) -> list[dict[str, Any]]:
    trace = page.evaluate(
        "() => Array.isArray(window.__p19Trace) ? window.__p19Trace : []"
    )
    return [event for event in trace if isinstance(event, dict)]


def _wait_until(page: Page, predicate: Callable[[list[dict[str, Any]]], bool]) -> list[dict[str, Any]]:
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        trace = _trace(page)
        if predicate(trace):
            return trace
        page.wait_for_timeout(20)
    trace = _trace(page)
    raise AssertionError(f"trace condition not reached; event kinds={[event['kind'] for event in trace]}")


def _request(trace: list[dict[str, Any]], method: str, suffix: str) -> dict[str, Any]:
    matches = [
        event for event in trace
        if event["kind"] == "request" and event["method"] == method and event["path"].endswith(suffix)
    ]
    assert len(matches) == 1, f"expected one {method} *{suffix}, got {matches}"
    return matches[0]


def _assert_commit_precedes_response(
    trace: list[dict[str, Any]], suffix: str, state: Callable[[dict[str, Any]], bool]
) -> None:
    commit = next(event for event in trace if event["kind"] == "dom" and state(event))
    pointer = max(
        (event for event in trace if event["kind"] == "pointerup" and event["at"] <= commit["at"]),
        key=lambda event: event["at"],
    )
    response = next(
        event for event in trace if event["kind"] == "response" and event["path"].endswith(suffix)
    )
    assert commit["at"] >= pointer["at"], "visible commit preceded the committing pointer-up"
    assert commit["at"] < response["at"], "visible state waited for the mutation response"


def _assert_no_board_get(trace: list[dict[str, Any]]) -> None:
    gets = [
        event for event in trace
        if event["kind"] == "request" and event["method"] == "GET" and "/api/board" in event["path"]
    ]
    assert gets == [], f"writing action refetched the board: {gets}"


def test_p_19_hover_lifecycle_has_zero_layout_cost(ui_f2: UiSession) -> None:
    page = ui_f2.page
    page.wait_for_selector(TRIGGER, timeout=10000)
    page.mouse.move(2, 2)
    page.wait_for_timeout(350)
    card_before = _box(page, CARD)
    sibling_before = _box(page, '[data-goal-id="SYNORD02"]')
    rest_background = _style(page, CARD, "background-color")
    assert float(_style(page, TRIGGER, "opacity")) == 0

    page.locator(ROW).hover()
    page.wait_for_timeout(16)
    assert float(_style(page, TRIGGER, "opacity")) == 1, "hover reveal must snap by one frame"
    hover_background = _style(page, CARD, "background-color")
    assert hover_background != rest_background
    assert _box(page, CARD) == card_before and _box(page, '[data-goal-id="SYNORD02"]') == sibling_before

    colored = '[data-goal-id="SYNCOL01"]'
    colored_before = _style(page, colored, "background-color")
    page.locator(colored).hover()
    page.wait_for_timeout(16)
    assert _style(page, colored, "background-color") == colored_before

    page.mouse.move(2, 2)
    page.wait_for_timeout(150)
    opacity_mid = float(_style(page, TRIGGER, "opacity"))
    assert 0 < opacity_mid < 1
    page.wait_for_timeout(200)
    assert float(_style(page, TRIGGER, "opacity")) == 0

    _open_menu(page)
    page.mouse.move(2, 2)
    page.wait_for_timeout(350)
    assert float(_style(page, TRIGGER, "opacity")) == 1
    assert "goal-card--menu-open" in page.locator(CARD).get_attribute("class").split()


def test_p_19_dots_trigger_geometry_and_cursors(ui_f2: UiSession) -> None:
    page = ui_f2.page
    page.wait_for_selector(TRIGGER, timeout=10000)
    trigger = page.locator(TRIGGER)
    svg = trigger.locator("svg")
    circles = svg.locator("circle").evaluate_all(
        "els => els.map(el => [el.getAttribute('cx'), el.getAttribute('cy'), el.getAttribute('r')])"
    )
    trigger_box, row_box = _box(page, TRIGGER), _box(page, ROW)

    assert circles == [["16", "16", "2"], ["24", "16", "2"], ["8", "16", "2"]]
    assert svg.get_attribute("viewBox") == "0 0 32 32"
    assert abs(trigger_box["width"] - 24) <= 0.5 and abs(trigger_box["height"] - 24) <= 0.5
    assert abs(trigger_box["y"] - (row_box["y"] - 1)) <= 1
    assert abs(trigger_box["x"] + trigger_box["width"] - row_box["x"] - row_box["width"]) <= 1
    assert _style(page, TRIGGER, "padding") == "0px"
    assert _style(page, ROW, "cursor") == "grab"
    assert _style(page, TRIGGER, "cursor") == "pointer"


def test_p_19_portal_surface_and_open_motion(ui_f2: UiSession) -> None:
    page = ui_f2.page
    page.wait_for_selector(TRIGGER, timeout=10000)
    card_before = _box(page, CARD)
    sibling_before = _box(page, '[data-goal-id="SYNORD02"]')
    dialogs_before = page.get_by_role("dialog").count()
    _open_menu(page)
    menu = page.locator(MENU)
    menu_box = _box(page, MENU)
    trigger_box = _box(page, TRIGGER)
    motion = menu.evaluate(
        """el => ({
          easing:getComputedStyle(el).animationTimingFunction,
          animations:el.getAnimations().map(a => ({
            duration:a.effect.getTiming().duration,
            keyframes:a.effect.getKeyframes().map(frame => ({
              opacity:frame.opacity ?? null, transform:frame.transform ?? null
            }))
          }))
        })"""
    )
    x_overlap = min(menu_box["x"] + menu_box["width"], trigger_box["x"] + trigger_box["width"]) - max(
        menu_box["x"], trigger_box["x"]
    )
    if x_overlap > 0:
        anchor_gap = max(
            menu_box["y"] - trigger_box["y"] - trigger_box["height"],
            trigger_box["y"] - menu_box["y"] - menu_box["height"],
        )
    else:
        anchor_gap = max(
            menu_box["x"] - trigger_box["x"] - trigger_box["width"],
            trigger_box["x"] - menu_box["x"] - menu_box["width"],
        )
    first_item = menu.locator(":scope > [data-action] > .goal-actions__item").first

    assert menu.get_attribute("role") == "menu"
    assert menu.evaluate("el => el.closest('#dropdownPortal') !== null")
    assert float(_style(page, MENU, "min-width").removesuffix("px")) >= 200
    assert menu_box["height"] <= page.viewport_size["height"] - 10
    assert _style(page, MENU, "position") == "absolute"
    assert _style(page, MENU, "z-index") == "5000"
    assert _style(page, MENU, "border-radius") == "4px"
    assert _style(page, MENU, "background-color") == "rgb(27, 27, 27)"
    assert _style(page, MENU, "border-width") == "1px"
    assert _style(page, MENU, "box-shadow") != "none"
    assert 3 <= anchor_gap <= 5
    item_style = first_item.evaluate(
        "el => ({fontSize:getComputedStyle(el).fontSize, lineHeight:getComputedStyle(el).lineHeight, padding:getComputedStyle(el).padding})"
    )
    assert item_style == {"fontSize": "14px", "lineHeight": "24px", "padding": "4px 14px"}
    assert len(motion["animations"]) == 1
    assert motion["easing"] == "ease-out"
    assert motion["animations"][0]["duration"] == 120
    assert [frame["opacity"] for frame in motion["animations"][0]["keyframes"]] == ["0", "1"]
    assert all(frame["transform"] is None for frame in motion["animations"][0]["keyframes"])
    assert page.locator('[data-role="goal-actions-backdrop"]').count() == 0
    assert page.get_by_role("dialog").count() == dialogs_before
    assert page.locator(TRIGGER).get_attribute("aria-expanded") == "true"
    assert menu.evaluate("el => document.activeElement === el")
    assert _box(page, CARD) == card_before and _box(page, '[data-goal-id="SYNORD02"]') == sibling_before

    page.keyboard.press("Escape")
    page.emulate_media(reduced_motion="reduce")
    _open_menu(page)
    assert page.locator(MENU).evaluate("el => el.getAnimations().length") == 0


def test_p_19_menu_order_icons_and_dividers(ui_f2: UiSession) -> None:
    page = ui_f2.page
    page.wait_for_selector(TRIGGER, timeout=10000)
    _open_menu(page)
    menu = page.locator(MENU)
    actions = menu.locator(":scope > [data-action]").evaluate_all(
        "els => els.map(el => el.getAttribute('data-action'))"
    )
    icons = menu.locator(":scope > [data-action] [data-icon]").evaluate_all(
        "els => els.map(el => el.getAttribute('data-icon'))"
    )
    dividers = menu.locator(":scope > hr")

    assert menu.locator(':scope > [data-role="goal-color-picker"]').count() == 1
    assert menu.locator(':scope > [data-role="goal-color-picker"] [data-color]').count() == 7
    # P-29 measured Repeat as the fourth goal-menu action on 2026-08-10. P-19 predates that
    # measured addition, so retain its adapted cast and insert Repeat at the proven slot.
    assert actions == ["schedule", "inbox", "reparent", "repeat", "delete"]
    assert icons == ["calendar", "hierarchy", "repeat", "trash"]
    assert menu.locator('[data-action="inbox"] > [data-role="icon-spacer"]').count() == 1
    assert dividers.count() == 2
    assert menu.locator('[data-action="schedule"] [data-role="submenu-arrow"]').count() == 1
    assert menu.locator('[data-action="reparent"] [data-role="submenu-arrow"]').count() == 1
    assert menu.locator('[data-action="repeat"] [data-role="submenu-arrow"]').count() == 1
    assert not any(
        phrase in menu.inner_text()
        for phrase in ("Assign", "Time", "Board", "Space", "Share", "Follow")
    )

    schedule_submenu = page.locator('[data-role="goal-actions-schedule"]')
    menu.locator(':scope > [data-action="schedule"]').hover()
    page.wait_for_timeout(50)
    assert not schedule_submenu.is_visible(), "mouse submenu opened before the measured 75 ms delay"
    page.wait_for_timeout(50)
    assert schedule_submenu.is_visible(), "mouse submenu did not open after the measured 75 ms delay"

    page.keyboard.press("Escape")
    if page.locator(MENU).is_visible():
        page.keyboard.press("Escape")
    parent_card = '[data-goal-id="SYNLIF01"]'
    _open_menu(page, parent_card)
    parent_actions = page.locator(MENU).locator(":scope > [data-action]").evaluate_all(
        "els => els.map(el => el.getAttribute('data-action'))"
    )
    assert parent_actions == ["schedule", "inbox", "expand", "reparent", "delete"]


def test_p_19_keyboard_open_navigate_escape_and_slash(ui_f2: UiSession) -> None:
    page = ui_f2.page
    page.wait_for_selector(TRIGGER, timeout=10000)
    trigger = page.locator(TRIGGER)
    assert trigger.get_attribute("aria-label") == "Goal actions"
    assert trigger.get_attribute("aria-haspopup") == "menu"

    trigger.focus()
    page.keyboard.press("Enter")
    page.locator(MENU).wait_for(state="visible")
    assert page.locator(MENU).evaluate("el => document.activeElement === el")
    page.keyboard.press("ArrowDown")
    first_item = page.evaluate("document.activeElement?.outerHTML")
    assert page.evaluate("document.activeElement?.closest('[role=menu]')?.dataset.role") == "goal-actions-menu"
    page.keyboard.press("ArrowUp")
    assert page.evaluate("document.activeElement?.closest('[data-action]')?.dataset.action") == "delete"
    assert page.evaluate("document.activeElement?.outerHTML") != first_item
    assert page.evaluate("document.activeElement?.closest('[role=menu]')?.dataset.role") == "goal-actions-menu"
    page.keyboard.press("Escape")
    page.locator(MENU).wait_for(state="hidden")
    assert trigger.evaluate("el => document.activeElement === el")

    trigger.focus()
    page.keyboard.press("Space")
    page.locator(MENU).wait_for(state="visible")
    assert page.locator(TRIGGER).get_attribute("aria-expanded") == "true"
    page.keyboard.press("Escape")

    # LIVE2 resolved sweep 1's synthetic row-focus negative: Slash travels through the native
    # focused descendant/selected-card route and opens the same surface.
    trigger.focus()
    page.locator(ROW).hover()
    page.keyboard.press("Slash")
    page.locator(MENU).wait_for(state="visible")
    assert page.locator(MENU).evaluate("el => el === document.activeElement")
    assert trigger.get_attribute("aria-expanded") == "true"


def test_p_19_color_is_optimistic_and_has_one_patch(ui_f2: UiSession) -> None:
    page = ui_f2.page
    page.wait_for_selector(TRIGGER, timeout=10000)
    _install_trace(page, GOAL)
    _open_menu(page)
    swatch = page.locator(f'{MENU} [data-role="goal-color-picker"] [data-color="#df496d"]')
    expected_background = swatch.get_attribute("data-card-background")
    assert expected_background
    swatch.click()
    trace = _wait_until(page, lambda events: any(e["kind"] == "response" for e in events))
    request = _request(trace, "PATCH", f"/api/goals/{GOAL}")
    assert request["body"] == {"color": "#df496d"}
    _assert_commit_precedes_response(
        trace, f"/api/goals/{GOAL}", lambda event: event["background"] == expected_background
    )
    page.wait_for_timeout(250)
    trace = _trace(page)
    _assert_no_board_get(trace)


def test_p_19_schedule_and_inbox_are_optimistic_without_refetch(ui_f2: UiSession) -> None:
    page = ui_f2.page
    page.wait_for_selector(TRIGGER, timeout=10000)
    _install_trace(page, GOAL)
    _open_menu(page)
    page.locator(f'{MENU} [data-action="schedule"]').click()
    month = page.locator('[data-role="goal-actions-schedule"] [data-scale="month"] [data-period-key]').first
    month.click()
    page.wait_for_selector(f'[data-vertical="month"] {CARD}', timeout=5000)
    trace = _wait_until(
        page,
        lambda events: any(e["kind"] == "response" and e["path"].endswith("/schedule") for e in events),
    )
    request = _request(trace, "PUT", f"/api/goals/{GOAL}/schedule")
    assert set(request["body"]) == {"vertical", "anchor_date"}
    assert request["body"]["vertical"] == "month" and request["body"]["anchor_date"]
    _assert_commit_precedes_response(
        trace, f"/api/goals/{GOAL}/schedule", lambda event: event["vertical"] == "month"
    )
    page.wait_for_timeout(250)
    trace = _trace(page)
    _assert_no_board_get(trace)

    page.evaluate("window.__p19Trace=[]")
    moved_card = f'[data-vertical="month"] [data-goal-id="{GOAL}"]'
    _open_menu(page, moved_card)
    page.locator(f'{MENU} [data-action="inbox"]').click()
    page.wait_for_selector(moved_card, state="detached", timeout=5000)
    trace = _wait_until(
        page,
        lambda events: any(e["kind"] == "response" and e["path"].endswith("/schedule") for e in events),
    )
    request = _request(trace, "PUT", f"/api/goals/{GOAL}/schedule")
    assert request["body"] == {"vertical": None, "anchor_date": None}
    _assert_commit_precedes_response(
        trace, f"/api/goals/{GOAL}/schedule", lambda event: event["exists"] is False
    )
    page.wait_for_timeout(250)
    trace = _trace(page)
    _assert_no_board_get(trace)


def test_p_19_reparent_is_optimistic_without_refetch(ui_f2: UiSession) -> None:
    page = ui_f2.page
    goal_id, parent_id = "SYNORD04", "SYNQ1R01"
    card = f'[data-goal-id="{goal_id}"]'
    page.wait_for_selector(card, timeout=10000)
    _install_trace(page, goal_id)
    _open_menu(page, card)
    page.locator(f'{MENU} [data-action="reparent"]').click()
    page.locator(f'[data-role="goal-actions-reparent"] [data-parent-id="{parent_id}"]').click()
    page.wait_for_selector(f'{card}[data-parent-id="{parent_id}"]', timeout=5000)
    trace = _wait_until(page, lambda events: any(e["kind"] == "response" for e in events))
    request = _request(trace, "PUT", f"/api/goals/{goal_id}/parent")
    assert request["body"] == {"parent_id": parent_id}
    _assert_commit_precedes_response(
        trace, f"/api/goals/{goal_id}/parent", lambda event: event["parentId"] == parent_id
    )
    page.wait_for_timeout(250)
    trace = _trace(page)
    _assert_no_board_get(trace)


def test_p_19_delete_is_optimistic_without_refetch(ui_f2: UiSession) -> None:
    page = ui_f2.page
    goal_id = "SYNORD03"
    card = f'[data-goal-id="{goal_id}"]'
    page.wait_for_selector(card, timeout=10000)
    _install_trace(page, goal_id)
    _open_menu(page, card)
    page.locator(f'{MENU} [data-action="delete"]').click()
    page.wait_for_selector(card, state="detached", timeout=5000)
    trace = _wait_until(page, lambda events: any(e["kind"] == "response" for e in events))
    request = _request(trace, "DELETE", f"/api/goals/{goal_id}")
    assert request["body"] is None
    _assert_commit_precedes_response(
        trace, f"/api/goals/{goal_id}", lambda event: event["exists"] is False
    )
    page.wait_for_timeout(250)
    trace = _trace(page)
    _assert_no_board_get(trace)


def test_p_19_checkbox_motion_state_and_wire(ui_f2: UiSession) -> None:
    page = ui_f2.page
    page.wait_for_selector(CARD, timeout=10000)
    _install_trace(page, GOAL)
    checkbox = page.locator(f'{CARD} [data-cap="complete"]')
    box = checkbox.locator('[data-role="checkbox-box"]')
    assert checkbox.get_attribute("role") == "checkbox"
    assert checkbox.get_attribute("aria-checked") == "false"
    checkbox_box = box.bounding_box()
    assert checkbox_box and abs(checkbox_box["width"] - 20) <= 0.5 and abs(checkbox_box["height"] - 20) <= 0.5

    center = (checkbox_box["x"] + 10, checkbox_box["y"] + 10)
    page.mouse.move(*center)
    page.mouse.down()
    scale = box.evaluate("el => new DOMMatrix(getComputedStyle(el).transform).a")
    assert abs(scale - 1.1) <= 0.01
    page.mouse.up()
    page.wait_for_timeout(30)
    title = page.locator(f"{CARD} .goal-card__title")
    title_motion = title.evaluate(
        """el => { const style=getComputedStyle(el); return {
          property:style.transitionProperty,
          duration:style.transitionDuration,
          easing:style.transitionTimingFunction
        }}"""
    )
    animations = checkbox.evaluate(
        "el => el.getAnimations({subtree:true}).map(a => a.effect.getTiming().duration)"
    )
    assert animations and set(animations) == {200}
    assert title_motion == {"property": "color", "duration": "0.15s", "easing": "ease"}
    assert checkbox.get_attribute("aria-checked") == "true"
    assert _style(page, f"{CARD} .goal-card__title", "text-decoration-line") == "none"
    checkbox.evaluate(
        "el => Promise.all(el.getAnimations({subtree:true}).map(a => a.finished.catch(() => undefined)))"
    )
    title.evaluate(
        "el => Promise.all(el.getAnimations().map(a => a.finished.catch(() => undefined)))"
    )
    assert abs(float(_style(page, f"{CARD} .goal-card__title", "color").split(",")[-1].rstrip(") ")) - 0.6) <= 0.01
    assert float(_style(page, f'{CARD} [data-role="checkbox-box"]', "opacity")) == 0.5

    trace = _wait_until(page, lambda events: any(e["kind"] == "response" for e in events))
    request = _request(trace, "PATCH", f"/api/goals/{GOAL}")
    assert request["body"] == {"done": True}
    _assert_commit_precedes_response(
        trace, f"/api/goals/{GOAL}", lambda event: event["checked"] == "true"
    )
    page.wait_for_timeout(250)
    trace = _trace(page)
    _assert_no_board_get(trace)
    assert page.locator('[data-role="completion-animation"]').count() == 0


def test_p_19_last_open_child_runs_one_list_completion_animation(ui_f2: UiSession) -> None:
    page = ui_f2.page
    parent = '[data-goal-id="SYNDAY01"]'
    page.wait_for_selector(parent, timeout=10000)
    page.locator(f'{parent} [data-role="subgoal-toggle"]').click()
    child = '[data-goal-id="SYNSUB03"]'
    page.wait_for_selector(child, timeout=10000)
    for goal_id in ("SYNSUB01", "SYNSUB02"):
        checkbox = page.locator(f'[data-goal-id="{goal_id}"] [data-cap="complete"]')
        checkbox.click()
        page.wait_for_function(
            "element => element.getAttribute('aria-checked') === 'true'",
            arg=checkbox.element_handle(),
        )
    assert page.locator('[data-role="completion-animation"]').count() == 0
    siblings_before = page.locator('[data-goal-id="SYNDAY01"] > .goal-card__children > .goal-card').evaluate_all(
        "els => els.map(el => el.getBoundingClientRect().toJSON())"
    )
    page.locator(f'{child} [data-cap="complete"]').click()
    layer = page.locator('[data-role="completion-animation"]')
    layer.wait_for(state="visible", timeout=5000)
    animations = layer.evaluate(
        """el => el.getAnimations().map(a => {
          const duration=a.effect.getTiming().duration;
          a.pause();
          a.currentTime=duration / 2;
          const midpointProgress=a.effect.getComputedTiming().progress;
          const keyframes=a.effect.getKeyframes();
          a.play();
          return {duration,midpointProgress,keyframes};
        })"""
    )
    siblings_during = page.locator('[data-goal-id="SYNDAY01"] > .goal-card__children > .goal-card').evaluate_all(
        "els => els.map(el => el.getBoundingClientRect().toJSON())"
    )

    assert layer.count() == 1
    assert _style(page, '[data-role="completion-animation"]', "position") == "absolute"
    assert _style(page, '[data-role="completion-animation"]', "pointer-events") == "none"
    assert animations and animations[0]["duration"] == 5000
    assert abs(animations[0]["midpointProgress"] - 0.8024) <= 0.01
    opacities = [frame.get("opacity") for frame in animations[0]["keyframes"]]
    assert opacities == ["0", "1", "1", "0"]
    assert layer.locator('[data-loop="false"][data-autoplay="true"]').count() == 1
    assert siblings_during == siblings_before
    page.wait_for_timeout(6100)
    layer.wait_for(state="detached", timeout=1000)
