"""P-24: opened goal card entry, shell, cast, lifecycle, and write-safe boundary.

Fixture F2 only. The owner-account write rows are deliberately absent: P-24 measured them as
BLOCKED-ON-STAMP. P-21 owns hosted popovers and P-22 owns hosted subgoal rows.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from playwright.sync_api import Locator, Page

from tests.ui.conftest import UiSession


ROOT = Path(__file__).resolve().parents[2]
CARD = '[data-goal-id="SYNDAY01"]'
ROW = f"{CARD} > .goal-card__row"
TITLE = f"{CARD} .goal-card__title"
DOTS = f'{CARD} [aria-label="Goal actions"]'
MODAL = '#goal-detail[data-state="open"]'
DIALOG = f"{MODAL} .modal__dialog"
SCRIM = f"{MODAL} .modal__scrim"
BODY = f"{MODAL} .modal__body"
DRAWER = '[data-role="detail-drawer"][data-state="open"]'


def _box(locator: Locator) -> dict[str, float]:
    box = locator.bounding_box()
    assert box is not None, f"{locator} has no rectangle"
    return box


def _style(locator: Locator, *names: str) -> list[str]:
    return locator.evaluate(
        "(el,names) => names.map(name => getComputedStyle(el).getPropertyValue(name))",
        list(names),
    )


def _open(page: Page) -> Locator:
    page.locator(TITLE).click()
    surface = page.locator(MODAL)
    surface.wait_for(state="visible", timeout=5_000)
    # Desktop entry scales the whole measured card for 200 ms, so descendant client rects are
    # intentionally fractional until that animation finishes. Await its real completion rather
    # than racing it with a fixed sleep; settled checkbox geometry remains strictly 24 == 24.
    surface.evaluate(
        """surface => Promise.all(surface.getAnimations({subtree: true})
          .map(animation => animation.finished.catch(() => undefined)))"""
    )
    return surface


def _writes(session: UiSession, start: int) -> list[dict[str, Any]]:
    return [
        request for request in session.request_log[start:]
        if request["method"] not in {"GET", "HEAD", "OPTIONS"}
    ]


def test_p_24_pointer_entry_map_and_excluded_controls(ui_f2: UiSession) -> None:
    """ASSERT A1: whole row enters; checkbox, dots, and tag zones do not."""
    page = ui_f2.page
    row = page.locator(ROW)
    row.wait_for(state="visible", timeout=5_000)
    assert row.get_attribute("role") == "button"
    assert row.get_attribute("tabindex") == "0"

    page.locator(DOTS).click()
    assert page.locator(MODAL).count() == 0
    assert page.locator('#dropdownPortal [data-popover-surface][data-state="open"]').count() == 1
    page.keyboard.press("Escape")

    source = (ROOT / "web/src/components/GoalCard.vue").read_text()
    assert '@click.stop' in source and '@pointerdown.stop' in source
    assert "fromControl(event)" in source, "nested controls can bubble into card entry"

    row.click(position={"x": 100, "y": 8})
    page.locator(MODAL).wait_for(state="visible", timeout=5_000)
    assert page.evaluate("location.hash") == "#goal/SYNDAY01"


def test_p_24_keyboard_route_is_inline_edit_not_detail_or_menu(ui_f2: UiSession) -> None:
    """ASSERT A2: reference Enter edits the focused row; it does not open detail or dots."""
    page = ui_f2.page
    row = page.locator(ROW)
    row.wait_for(state="visible", timeout=5_000)
    row.focus()
    page.keyboard.press("Enter")
    page.wait_for_timeout(40)
    assert page.locator(MODAL).count() == 0
    assert page.locator('#dropdownPortal [data-popover-surface][data-state="open"]').count() == 0
    assert page.evaluate("document.activeElement?.tagName") == "TEXTAREA"


def test_p_24_fragment_cold_boot_reopens_the_card(ui_f2: UiSession) -> None:
    """ASSERT A3: D17 fragment adaptation is addressable on a fresh document."""
    page = ui_f2.context.new_page()
    try:
        page.goto(f"{ui_f2.base_url}/#goal/SYNDAY01", wait_until="domcontentloaded")
        page.locator(MODAL).wait_for(state="visible", timeout=5_000)
        assert page.evaluate("location.hash") == "#goal/SYNDAY01"
        assert page.locator(DIALOG).get_attribute("role") == "dialog"
    finally:
        page.close()


def test_p_24_desktop_shell_layer_and_geometry(ui_f2: UiSession) -> None:
    """ASSERT A4: desktop shell owns viewport scroll, layer, and 924px top-led card."""
    page = ui_f2.page
    page.set_viewport_size({"width": 1458, "height": 779})
    _open(page)
    dialog, scrim = page.locator(DIALOG), page.locator(SCRIM)
    box = _box(dialog)
    assert abs(box["x"] - 267) <= 1 and abs(box["y"] - 6) <= 1
    assert abs(box["width"] - 924) <= 1 and box["height"] >= 538
    assert _style(dialog, "padding", "border-width", "border-radius", "box-shadow") == [
        "0px", "0px", "6px", "none",
    ]
    assert _style(scrim, "background-color", "overflow-x", "overflow-y") == [
        "rgba(0, 0, 0, 0.6)", "scroll", "scroll",
    ]
    assert _style(page.locator(MODAL), "z-index", "overflow") == ["5000", "hidden"]
    assert page.evaluate("getComputedStyle(document.documentElement).overflow") == "hidden"
    assert page.evaluate("getComputedStyle(document.body).overflow") == "hidden"


def test_p_24_desktop_full_cast_order_geometry_and_type(ui_f2: UiSession) -> None:
    """ASSERT A5: period, checkbox/title, subgoals, body, metadata, and footer form one cast."""
    page = ui_f2.page
    _open(page)
    period = page.locator(f'{MODAL} [data-cap="schedule"]')
    checkbox = page.locator(f'{MODAL} [data-role="detail-complete"]')
    title = page.locator(f'{MODAL} [data-cap="edit-title"]')
    subgoals = page.locator(f'{MODAL} [data-role="subgoals"]')
    body = page.locator(f'{MODAL} [data-cap="edit-body"]')
    footer = page.locator(f'{MODAL} [data-role="detail-footer"]')

    assert period.count() == checkbox.count() == title.count() == subgoals.count() == body.count() == 1
    assert footer.count() == 1
    assert title.evaluate(
        """title => ['[data-role="subgoals"]','[data-cap="edit-body"]','[data-role="detail-footer"]']
          .map(selector => title.closest('#goal-detail').querySelector(selector))
          .every(part => !!part && !!(title.compareDocumentPosition(part) & Node.DOCUMENT_POSITION_FOLLOWING))"""
    )
    assert _style(title, "font-size", "font-weight", "line-height", "cursor") == [
        "36px", "600", "44px", "text",
    ]
    assert _box(checkbox)["width"] == 24 and _box(checkbox)["height"] == 24
    assert abs(_box(title)["x"] - _box(page.locator(DIALOG))["x"] - 76) <= 1
    assert _style(subgoals, "max-width", "padding-right", "margin-bottom") == [
        "534px", "80px", "36px",
    ]
    assert _style(footer, "position", "height", "padding", "z-index") == [
        "sticky", "73px", "20px 24px", "100",
    ]


def test_p_24_focus_selection_cursor_and_restore(ui_f2: UiSession) -> None:
    """ASSERT A6: preserve D8 focus containment/restore and D11 drag cursor adaptation."""
    page = ui_f2.page
    opener = page.locator(ROW)
    opener.focus()
    _open(page)
    assert page.evaluate("document.activeElement?.closest('#goal-detail') !== null")
    assert _style(page.locator(DIALOG), "user-select") == ["text"]
    assert _style(page.locator(f'{MODAL} [data-cap="schedule"]'), "cursor") == ["pointer"]
    assert _style(page.locator(f'{MODAL} [data-cap="edit-title"]'), "cursor") == ["text"]

    page.locator(f"{MODAL} .modal__close").click()
    page.wait_for_timeout(220)
    assert opener.evaluate("el => el === document.activeElement")
    assert _style(opener, "cursor") == ["grab"]


def test_p_24_internal_scroll_owner_and_sticky_footer(ui_f2: UiSession) -> None:
    """ASSERT A7: overlay scrolls the shell; editor body scrolls content; footer stays reachable."""
    page = ui_f2.page
    _open(page)
    footer = page.locator(f'{MODAL} [data-role="detail-footer"]')
    assert _style(page.locator(BODY), "min-height", "overflow-y") == ["400px", "visible"]
    assert _style(page.locator(SCRIM), "overflow-y") == ["scroll"]
    assert _style(footer, "position", "bottom", "background-color") == [
        "sticky", "0px", "rgb(255, 255, 255)",
    ]


def test_p_24_exact_694_to_693_drawer_cast(ui_f2: UiSession) -> None:
    """ASSERT A8: 694px is desktop; 693px is the measured full-viewport bottom drawer."""
    page = ui_f2.page
    page.set_viewport_size({"width": 694, "height": 900})
    _open(page)
    assert page.locator(MODAL).count() == 1 and page.locator(DRAWER).count() == 0
    page.locator(f"{MODAL} .modal__close").click()
    page.wait_for_timeout(220)

    page.set_viewport_size({"width": 693, "height": 900})
    page.locator(TITLE).click()
    drawer = page.locator(DRAWER)
    drawer.wait_for(state="visible", timeout=5_000)
    assert _box(drawer) == {"x": 0, "y": 0, "width": 693, "height": 900}
    content = drawer.locator('[data-role="drawer-content"]')
    card = drawer.locator('[data-role="drawer-card"]')
    assert _style(content, "padding-top", "overflow-y") == ["360px", "auto"]
    assert _style(card, "border-radius", "padding-top") == ["8px 8px 0px 0px", "8px"]
    assert _style(drawer.locator('[data-cap="edit-title"]'), "font-size", "font-weight", "line-height") == [
        "24px", "700", "30px",
    ]
    assert _style(drawer.locator('[data-role="drawer-footer"]'), "height", "position") == [
        "48px", "sticky",
    ]


def test_p_24_open_close_motion_tables(ui_f2: UiSession) -> None:
    """ASSERT A9: desktop actors use exact 200ms forward/reverse motion."""
    page = ui_f2.page
    page.emulate_media(reduced_motion="no-preference")
    page.locator(TITLE).click()
    page.locator(MODAL).wait_for(state="visible", timeout=5_000)
    animations = page.evaluate(
        """() => document.getAnimations().filter(a =>
          a.effect?.target?.closest?.('#goal-detail')).map(a => {
            const duration=a.effect.getTiming().duration;
            a.pause();
            a.currentTime=duration / 2;
            const midpointProgress=a.effect.getComputedTiming().progress;
            const frames=a.effect.getKeyframes().map(k => ({
              opacity:k.opacity ?? null,transform:k.transform ?? null
            }));
            a.play();
            return {target:[...a.effect.target.classList],duration,midpointProgress,frames};
          })"""
    )
    scrim = next(a for a in animations if "modal__scrim" in a["target"])
    dialog = next(a for a in animations if "modal__dialog" in a["target"])
    assert scrim["duration"] == 200 and abs(scrim["midpointProgress"] - 0.9146) <= 0.01
    assert [frame["opacity"] for frame in scrim["frames"]] == ["0", "1"]
    assert all(frame["transform"] is None for frame in scrim["frames"])
    assert [frame["opacity"] for frame in dialog["frames"]] == ["0", "1"]
    assert dialog["duration"] == 200 and abs(dialog["midpointProgress"] - 0.8024) <= 0.01
    assert dialog["frames"][0]["transform"] == "scale(0.9)"
    assert dialog["frames"][-1]["transform"] == "none"

    page.locator(f"{MODAL} .modal__close").click()
    page.wait_for_timeout(20)
    closing = page.evaluate(
        """() => document.getAnimations().filter(a => a.effect?.target?.closest?.('#goal-detail')).map(a => ({
          duration:a.effect.getTiming().duration,frames:a.effect.getKeyframes().map(k => ({
            opacity:k.opacity ?? null,transform:k.transform ?? null}))}))"""
    )
    assert all(a["duration"] == 200 for a in closing)
    assert any(a["frames"][-1]["transform"] == "scale(0.9)" for a in closing)
    page.wait_for_timeout(200)
    assert page.locator(MODAL).count() == 0


def test_p_24_hosted_bindings_and_read_only_lifecycle(ui_f2: UiSession) -> None:
    """ASSERT A10: P-21/P-22 remain bound and open/dismiss performs no write."""
    page = ui_f2.page
    start = len(ui_f2.request_log)
    _open(page)
    schedule = page.locator(f'{MODAL} [data-cap="schedule"]')
    assert schedule.count() == 1, "P-21 schedule consumer disappeared"
    assert page.locator(f'{MODAL} [data-role="subgoals"] .goal-detail__subgoal').count() >= 1
    assert _style(page.locator(f'{MODAL} [data-role="subgoals"]'), "max-width", "padding-right") == [
        "534px", "80px",
    ]
    page.locator(f"{MODAL} .modal__close").click()
    page.wait_for_timeout(220)
    assert _writes(ui_f2, start) == []
