"""P-23 motion vocabulary for board and detail.

Fixture F2 only. Tests record roles, synthetic ids, styles, timings, and request shape; no
owner-account content is used. The completion latency probe replaces ``window.fetch`` after
the board has loaded, so its synthetic PATCH answers never reach the fixture backend.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from playwright.sync_api import Page

from tests.parity.css import split_css_list
from tests.ui.conftest import UiSession


ROOT = Path(__file__).resolve().parents[2]
GOAL_CARD = ROOT / "web/src/components/GoalCard.vue"
GOAL_TOOLS = ROOT / "web/src/components/GoalCardTools.vue"
BOARD = ROOT / "web/src/components/Board.vue"
COLUMN = ROOT / "web/src/components/Column.vue"
STORE = ROOT / "web/src/store.ts"
DRAG = ROOT / "web/src/lib/drag.ts"
KIT_CSS = ROOT / "web/node_modules/@konstantinopolskii/design-system/style.css"
KIT_VARS = ROOT / "web/node_modules/@konstantinopolskii/design-system/vars.css"

CARD = '[data-goal-id="SYNORD01"]'
ROW = f"{CARD} > .goal-card__row"
TOOLS = f"{CARD} .goal-card__tools"
CHECK = f"{CARD} [data-cap=complete]"
CHECK_INPUT = f'{CHECK} input[type="checkbox"]'
CHECK_BOX = f"{CARD} .checkbox__box"
TITLE = f"{CARD} .goal-card__title"
PROGRESS = '[data-goal-id="SYNLIF01"] [data-role=progress]'
MODAL = ".modal[data-state=open]"
SCRIM = f"{MODAL} .modal__scrim"
DIALOG = f"{MODAL} .modal__dialog"
DRAWER = '[data-role="detail-drawer"][data-state="open"]'
DRAWER_CONTENT = f'{DRAWER} [data-role="drawer-content"]'
DRAWER_OVERLAY = f'{DRAWER} [data-role="drawer-overlay"]'
PORTAL = "#dropdownPortal"
POPOVER = f"{PORTAL} [data-popover-surface]"
OPEN_POPOVER = f'{POPOVER}[data-state="open"]'

QUART = "cubic-bezier(0.165, 0.84, 0.44, 1)"
SORT_EASING = "cubic-bezier(0.2, 0, 0, 1)"
SETTLE_EASING = "cubic-bezier(0.2, 1, 0.1, 1)"


def _source(*paths: Path) -> str:
    return "\n".join(path.read_text() for path in paths)


def _style(page: Page, selector: str, pseudo: str | None = None) -> dict[str, str]:
    return page.locator(selector).evaluate(
        """(el, pseudo) => {
          const s=getComputedStyle(el,pseudo);
          return {
            backgroundColor:s.backgroundColor, opacity:s.opacity, transform:s.transform,
            transitionProperty:s.transitionProperty,
            transitionDuration:s.transitionDuration,
            transitionTimingFunction:s.transitionTimingFunction,
            transitionDelay:s.transitionDelay, animationName:s.animationName,
            animationDuration:s.animationDuration,
            animationTimingFunction:s.animationTimingFunction,
            display:s.display, borderRadius:s.borderRadius, boxShadow:s.boxShadow,
            overflow:s.overflow
          };
        }""",
        pseudo,
    )


def _animations(page: Page) -> list[dict]:
    return page.evaluate(
        """() => document.getAnimations().map(a => {
          const timing=a.effect?.getTiming?.();
          return {
            name:a.animationName || null, property:a.transitionProperty || null,
            duration:timing?.duration,
            target:a.effect?.target instanceof Element ? [...a.effect.target.classList] : [],
            animationTimingFunction:a.effect?.target
              ? getComputedStyle(a.effect.target).animationTimingFunction : null,
            keyframes:a.effect?.getKeyframes?.().map(k => ({
              opacity:k.opacity,transform:k.transform,backgroundColor:k.backgroundColor,
              easing:k.easing
            })) || []
          };
        })"""
    )


def _open_detail(page: Page) -> None:
    page.locator(TITLE).click()
    page.wait_for_selector(MODAL, timeout=5000)


def test_p_23_card_crud_has_no_invented_motion() -> None:
    source = _source(BOARD, COLUMN, GOAL_CARD)
    css = _source(GOAL_CARD, GOAL_TOOLS, KIT_CSS)

    assert "<Transition" not in source and "<transition" not in source
    assert "TransitionGroup" not in source and "<transition-group" not in source
    assert not re.search(r"@keyframes\s+[^\s{]*(?:goal|card)[^\s{]*-(?:in|out|enter|leave)", css, re.I)


def test_p_23_card_hover_motion(ui_f2: UiSession) -> None:
    page = ui_f2.page
    page.wait_for_selector(ROW, timeout=5000)
    before_row = page.locator(ROW).bounding_box()
    before_card = page.locator(CARD).bounding_box()
    rest_background = _style(page, CARD)["backgroundColor"]

    page.locator(ROW).hover()
    page.wait_for_timeout(20)
    hover_background = _style(page, CARD)["backgroundColor"]
    hover_tools = _style(page, TOOLS)
    hover_row = page.locator(ROW).bounding_box()
    hover_card = page.locator(CARD).bounding_box()

    page.mouse.move(1400, 760)
    page.wait_for_timeout(20)
    leave_card = _style(page, CARD)
    leave_tools = _style(page, TOOLS)

    page.locator(f"{TOOLS} button").first.focus()
    focus_tools = _style(page, TOOLS)

    assert before_row == hover_row and before_card == hover_card
    assert hover_background != rest_background, "hover surface must visibly change"
    assert hover_tools["opacity"] == "1" and hover_tools["transitionDuration"] == "0s"
    assert leave_card["transitionDuration"] == "0.3s"
    assert leave_card["transitionTimingFunction"] == QUART
    assert leave_tools["transitionDuration"] == "0.3s"
    assert leave_tools["transitionTimingFunction"] == QUART
    assert focus_tools["opacity"] == "1"


def test_p_23_completion_motion(ui_f2: UiSession) -> None:
    page = ui_f2.page
    page.wait_for_selector(CHECK_BOX, timeout=5000)
    box = _style(page, CHECK_BOX)
    check = _style(page, CHECK_BOX, "::after")
    title = _style(page, TITLE)
    progress = _style(page, PROGRESS)

    assert set(split_css_list(box["transitionDuration"])) == {"0.2s"}
    transition_properties = split_css_list(box["transitionProperty"])
    assert split_css_list(box["transitionTimingFunction"]) == [QUART] * len(
        transition_properties
    )
    assert "transform" in transition_properties
    assert check["transitionDuration"] == "0.2s"
    assert check["transitionTimingFunction"] == QUART
    assert title["transitionProperty"] == "color"
    assert title["transitionDuration"] == "0.15s"
    assert title["transitionTimingFunction"] == "ease"
    assert progress["transitionDuration"] == "0.1s"
    assert progress["transitionTimingFunction"] == QUART

    page.locator(CHECK).hover()
    page.mouse.down()
    active = _style(page, CHECK_BOX)["transform"]
    page.mouse.up()
    assert active.startswith("matrix(1.1"), "active checkbox must reach scale(1.1)"


FETCH_INTERCEPT = r"""
() => {
  const realFetch=window.fetch.bind(window);
  window.__p23Patches=[];
  window.__p23Resolve=null;
  window.fetch=(input,init={}) => {
    const url=typeof input === 'string' ? input : input.url;
    if (init.method === 'PATCH' && /\/api\/goals\//.test(url)) {
      window.__p23Patches.push({url,method:init.method,body:JSON.parse(init.body)});
      return new Promise(resolve => { window.__p23Resolve=(status,doneAt) => resolve(
        new Response(JSON.stringify(status < 400 ? {done_at:doneAt} : {error:'probe failure'}), {
          status,headers:{'Content-Type':'application/json'}
        })
      ); });
    }
    return realFetch(input,init);
  };
}
"""


def test_p_23_completion_commit_latency_and_reconcile(ui_f2: UiSession) -> None:
    page = ui_f2.page
    page.wait_for_selector(CHECK_INPUT, timeout=5000)
    page.evaluate(FETCH_INTERCEPT)
    checkbox = page.locator(CHECK_INPUT)
    initial = checkbox.is_checked()

    page.locator(CHECK).click()
    page.wait_for_function("() => window.__p23Patches.length === 1")
    assert checkbox.is_checked() is (not initial), "optimistic paint waited for transport"
    first = page.evaluate("() => window.__p23Patches[0]")
    assert first["method"] == "PATCH" and first["body"] == {"done": not initial}

    done_at = "2026-08-08T06:00:00Z" if not initial else None
    page.evaluate("([status,doneAt]) => window.__p23Resolve(status,doneAt)", [200, done_at])
    page.wait_for_timeout(50)
    assert checkbox.is_checked() is (not initial)
    assert len([r for r in ui_f2.request_log if "/api/board" in r["url"]]) == 1

    page.locator(CHECK).click()
    page.wait_for_function("() => window.__p23Patches.length === 2")
    assert checkbox.is_checked() is initial
    page.evaluate("() => window.__p23Resolve(503,null)")
    page.locator(".toast-stack .toast").wait_for(state="visible", timeout=5000)
    assert checkbox.is_checked() is (not initial), "failure did not restore previous state"
    assert page.locator(".toast-stack .toast button").filter(has_text="Retry").count() == 1


def test_p_23_drag_motion_vocabulary() -> None:
    column = COLUMN.read_text()
    board = BOARD.read_text()
    drag = DRAG.read_text()

    assert "duration: 200" in column
    assert "cubic-bezier(0.2, 0, 0, 1)" in column
    assert "SETTLE_EASING = 'cubic-bezier(.2,1,.1,1)'" in drag
    assert "SETTLE_MIN_MS = 330" in drag and "SETTLE_MAX_MS = 550" in drag
    assert "SETTLE_GRACE_MS = 50" in drag
    # The settle transition is a joined list since the size morph landed (2026-08-10): position
    # AND box travel on the one duration and the one measured curve, so the vocabulary is asserted
    # per property rather than as one literal string.
    for prop in ("left", "top", "width", "height"):
        assert f"`{prop} ${{duration}}ms ${{SETTLE_EASING}}`" in board, (
            f"settle must animate {prop} on the measured duration and easing"
        )


def test_p_23_detail_modal_motion_and_geometry(ui_f2: UiSession) -> None:
    page = ui_f2.page
    page.wait_for_selector(TITLE, timeout=5000)
    opener = page.locator(TITLE)
    opener.evaluate("el => el.tabIndex=-1")
    opener.focus()
    baseline_overflow = page.evaluate("() => getComputedStyle(document.documentElement).overflow")
    _open_detail(page)
    dialog_width = page.locator(DIALOG).evaluate("el => el.offsetWidth")
    scrim = _style(page, SCRIM)
    dialog = _style(page, DIALOG)
    active = _animations(page)

    assert abs(dialog_width - 924) <= 1
    assert dialog["borderRadius"] in {"6px", "8px"}
    assert scrim["backgroundColor"] == "rgba(0, 0, 0, 0.6)"
    assert scrim["boxShadow"] == dialog["boxShadow"] == "none"
    assert page.evaluate("() => getComputedStyle(document.documentElement).overflow") == baseline_overflow
    scrim_animation = next(a for a in active if "modal__scrim" in a["target"])
    dialog_animation = next(a for a in active if "modal__dialog" in a["target"])
    assert scrim_animation["duration"] == 200
    assert [k["opacity"] for k in scrim_animation["keyframes"]] == ["0", "1"]
    assert dialog_animation["duration"] == 200
    assert dialog_animation["animationTimingFunction"] == "ease"
    assert any(k["transform"] == "scale(0.9)" for k in dialog_animation["keyframes"])

    page.locator(f"{MODAL} .modal__close").click()
    page.wait_for_timeout(20)
    assert page.locator(".modal[data-state=closed]").count() == 1
    assert _style(page, ".modal[data-state=closed]")["display"] != "none"
    closing = _animations(page)
    assert any(a["duration"] == 200 for a in closing), "detail close cut without reverse motion"
    page.wait_for_timeout(220)
    assert page.locator(MODAL).count() == 0
    assert page.evaluate("() => getComputedStyle(document.documentElement).overflow") == baseline_overflow
    assert opener.evaluate("el => el === document.activeElement")


def test_p_23_detail_switches_to_drawer_below_694(ui_f2: UiSession) -> None:
    page = ui_f2.page
    page.set_viewport_size({"width": 694, "height": 900})
    page.wait_for_selector(TITLE, timeout=5000)
    _open_detail(page)
    assert page.locator(MODAL).count() == 1 and page.locator(DRAWER).count() == 0
    page.locator(f"{MODAL} .modal__close").click()
    page.wait_for_selector(MODAL, state="detached")

    page.set_viewport_size({"width": 693, "height": 900})
    page.locator(TITLE).click()
    page.locator(DRAWER).wait_for(state="visible", timeout=5000)
    page.wait_for_timeout(320)
    drawer_box = page.locator(DRAWER).bounding_box()
    content_box = page.locator(DRAWER_CONTENT).bounding_box()
    assert drawer_box == {"x": 0, "y": 0, "width": 693, "height": 900}
    assert content_box == {"x": 0, "y": 0, "width": 693, "height": 852}
    assert _style(page, DRAWER_OVERLAY)["opacity"] == "1"
    page.keyboard.press("Escape")
    page.wait_for_timeout(20)
    assert page.locator(DRAWER).count() == 1, "live mobile Escape is a no-op"

    page.locator(f'{DRAWER} [data-role="drawer-close-area"]').click()
    page.wait_for_timeout(20)
    closing = _animations(page)
    assert any(
        a["duration"] == 300
        and a["keyframes"]
        and a["animationTimingFunction"] == "ease"
        for a in closing
    )
    page.wait_for_timeout(320)
    assert page.locator(DRAWER).count() == 0


def test_p_23_popover_motion(ui_f2: UiSession) -> None:
    page = ui_f2.page
    page.wait_for_selector(TITLE, timeout=5000)
    _open_detail(page)
    page.wait_for_timeout(220)
    trigger = page.locator(f"{MODAL} [data-cap=schedule]").first
    trigger.click()
    popover = page.locator(OPEN_POPOVER).first
    popover.wait_for(state="visible", timeout=5000)
    animations = popover.evaluate(
        """el => el.getAnimations().map(a => ({
          timing:a.effect.getTiming(),
          frames:a.effect.getKeyframes().map(k => ({
            opacity:k.opacity ?? null, transform:k.transform ?? null, easing:k.easing
          }))
        }))"""
    )
    assert len(animations) == 1
    assert animations[0]["timing"]["duration"] == 120
    assert [frame["opacity"] for frame in animations[0]["frames"]] == ["0", "1"]
    assert all(frame["transform"] is None for frame in animations[0]["frames"])
    assert all(frame["easing"] == "ease-out" for frame in animations[0]["frames"])

    page.keyboard.press("Escape")
    page.wait_for_timeout(20)
    assert page.locator(MODAL).count() == 1, "popover Escape closed its parent detail"
    assert page.locator(POPOVER).count() == 0, "popover Escape must detach every portal node"
    assert trigger.evaluate("el => el === document.activeElement")


def test_p_23_column_motion_contract(ui_f2: UiSession) -> None:
    page = ui_f2.page
    page.wait_for_selector("[data-role=column-strip]", timeout=5000)
    control = page.locator('[data-cap="period-next"], [data-cap="column-next"]')
    if control.count() == 0:
        pytest.skip("P-20 has not made reference period navigation reachable")

    identities = page.locator(".pattern-vertical-board__column").evaluate_all(
        "els => els.map((el,index) => { el.dataset.p23Identity=String(index); return index; })"
    )
    control.first.locator("xpath=ancestor::*[@data-vertical][1]").hover()
    control.first.click()
    page.locator('[data-role="period-slide"][data-state="incoming"]').first.wait_for(
        state="attached", timeout=5000
    )
    strip_animations = _animations(page)
    assert any(
        a["duration"] == 350
        and a["keyframes"]
        and a["animationTimingFunction"] == "ease"
        for a in strip_animations
    )
    assert page.locator(".pattern-vertical-board__column").evaluate_all(
        "els => els.map(el => Number(el.dataset.p23Identity))"
    ) == identities


def test_p_23_loading_motion() -> None:
    board = BOARD.read_text()
    styles = _source(BOARD, KIT_CSS)

    # LIVE2 found progressive reference rows and no `_loading` class on a delayed full reload.
    # Our complete-mount gate is the explicit TARGET adaptation; the dim rule is reserved for a
    # later refresh after a complete board already exists.
    assert 'v-if="store.state.loading && !dated.length"' in board
    assert 'v-if="dated.length"' in board, "initial load may not mount a partial strip"
    assert ':class="{ _loading: store.state.loading }"' in board
    loading_rule = re.search(
        r"\.pattern-vertical-board[^{}]*\._loading\s*\{(?P<body>[^}]*)\}", styles
    )
    assert loading_rule, "rendered-board loading state is absent"
    body = loading_rule.group("body")
    assert "opacity: 0.5" in body or "opacity:.5" in body
    assert "300ms" in body and "ease-in" in body and "1s" in body
    assert re.search(r"(?:spinner|Spinner)[^{]*\{[^}]*700ms[^}]*linear", styles, re.I | re.S)


def test_p_23_reduced_motion_collapses_durations() -> None:
    variables = KIT_VARS.read_text()
    css = KIT_CSS.read_text()

    reduced = variables[variables.index("@media (prefers-reduced-motion: reduce)") :]
    for token in ("--dur-fast", "--dur-base", "--dur-slow", "--dur-long"):
        assert re.search(rf"{re.escape(token)}:\s*0\.01ms", reduced)
    assert "animation: modal-scrim-in var(--dur-base) var(--ease-out)" in css
    assert "animation: modal-dialog-in var(--dur-base) var(--ease-out)" in css
    assert "animation: dropdown-in var(--dur-fast) var(--ease-out)" in css
    assert "transition: background-color var(--dur-fast) var(--ease-out)" in css
