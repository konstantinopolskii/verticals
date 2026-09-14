"""P-22: measured subgoal presentation geometry on board and in goal detail."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from playwright.sync_api import Locator, Page

from tests.ui.conftest import UiSession


PARENT = '[data-goal-id="SYNDAY01"]'
CHILD = '[data-goal-id="SYNSUB01"]'
PARENT_ROW = f"{PARENT} > .goal-card__row"
CHILD_ROW = f"{CHILD} > .goal-card__row"
TOGGLE = f'{PARENT_ROW} [data-role="subgoal-toggle"]'
BOARD_ADD = f'{PARENT} > .goal-card__children [data-role="subgoal-add"]'
DETAIL = '#goal-detail [data-role="subgoals"]'
GOAL_CARD_SOURCE = Path(__file__).resolve().parents[2] / "web/src/components/GoalCard.vue"


def _box(locator: Locator) -> dict[str, float]:
    box = locator.bounding_box()
    assert box is not None, f"{locator} has no box"
    return box


def _style(locator: Locator, name: str, pseudo: str | None = None) -> str:
    return locator.evaluate(
        "(el, args) => getComputedStyle(el,args.pseudo).getPropertyValue(args.name)",
        {"name": name, "pseudo": pseudo},
    )


def _expand(page: Page) -> None:
    if page.locator(CHILD_ROW).count() == 0:
        assert page.locator(TOGGLE).count() == 1
        page.locator(TOGGLE).click()
        page.wait_for_selector(CHILD_ROW)


def _open_detail(page: Page) -> None:
    page.locator(f"{PARENT_ROW} .goal-card__title").click()
    page.wait_for_selector(f"{DETAIL} .goal-detail__subgoal")


def _wait_for_desktop_detail_entry(page: Page) -> None:
    page.locator("#goal-detail .modal__dialog").evaluate(
        "el => Promise.all(el.getAnimations().map(a => a.finished.catch(() => undefined)))"
    )


def _mutating_requests(session: UiSession, start: int) -> list[dict[str, Any]]:
    return [
        item
        for item in session.request_log[start:]
        if item["method"] not in {"GET", "HEAD", "OPTIONS"}
    ]


def test_p_22_board_toggle_entry_and_topology(ui_f2: UiSession) -> None:
    page = ui_f2.page
    page.wait_for_selector(PARENT_ROW)
    toggle = page.locator(TOGGLE)

    assert page.locator(CHILD_ROW).count() == 0, "board subgoal subtree starts collapsed"
    assert toggle.count() == 1 and toggle.inner_text().strip() == "3 subgoals"
    arrow = toggle.locator('[data-role="subgoal-arrow"]')
    assert _box(arrow)["width"] == 12 and _box(arrow)["height"] == 12
    assert _style(arrow, "transform") == "matrix(0, -1, 1, 0, 0, 0)"

    request_start = len(ui_f2.request_log)
    toggle.click()
    page.wait_for_selector(CHILD_ROW)
    animations = arrow.evaluate(
        """el => el.getAnimations().map(a => ({
          duration:a.effect.getTiming().duration,
          easing:getComputedStyle(a.effect.target).transitionTimingFunction
        }))"""
    )
    page.wait_for_timeout(50)
    assert animations == [
        {"duration": 300, "easing": "cubic-bezier(0.165, 0.84, 0.44, 1)"}
    ]
    assert _mutating_requests(ui_f2, request_start) == []

    page.wait_for_timeout(320)
    assert _style(arrow, "transform") == "matrix(0, 1, -1, 0, 0, 0)"
    toggle.click()
    collapse_animations = arrow.evaluate(
        """el => el.getAnimations().map(a => ({
          duration:a.effect.getTiming().duration,
          easing:getComputedStyle(a.effect.target).transitionTimingFunction
        }))"""
    )
    assert collapse_animations == [
        {"duration": 250, "easing": "cubic-bezier(0.165, 0.84, 0.44, 1)"}
    ]
    assert page.locator(CHILD_ROW).count() == 0, "collapse removes subtree rather than hiding a ghost"


def test_p_22_board_subgoal_alignment_grid(ui_f2: UiSession) -> None:
    page = ui_f2.page
    page.wait_for_selector(PARENT_ROW)
    _expand(page)
    parent_card = page.locator(PARENT)
    child_card = page.locator(CHILD)
    parent_row = page.locator(PARENT_ROW)
    child_row = page.locator(CHILD_ROW)
    parent_checkbox = parent_row.locator('label.checkbox')
    child_checkbox = child_row.locator('label.checkbox')
    parent_title = parent_row.locator('.goal-card__title')
    child_title = child_row.locator('.goal-card__title')

    parent_card_box, child_card_box = _box(parent_card), _box(child_card)
    parent_row_box, child_row_box = _box(parent_row), _box(child_row)
    assert abs(child_card_box["x"] - parent_card_box["x"]) <= 1
    assert abs(child_card_box["width"] - parent_card_box["width"]) <= 1
    assert abs(child_row_box["x"] - parent_row_box["x"]) <= 1
    assert abs(child_row_box["width"] - parent_row_box["width"]) <= 1
    assert abs(_box(child_checkbox)["x"] - _box(parent_checkbox)["x"]) <= 1
    assert abs((_box(child_title)["x"] - _box(parent_title)["x"]) - 14) <= 1
    assert _style(child_card, "padding") == "6px"
    assert _style(child_card, "border-radius") == "8px"


def test_p_22_board_depth_formula_guide_and_spacing(ui_f2: UiSession) -> None:
    page = ui_f2.page
    page.wait_for_selector(PARENT_ROW)
    _expand(page)
    children = page.locator(f"{PARENT} > .goal-card__children")
    guide = {name: _style(children, name, "::before") for name in (
        "content", "position", "margin-left", "border-left-width", "border-left-color"
    )}
    guide_formula_rule = page.evaluate(
        """() => {
          const walk=rules => {
            for (const rule of rules) {
              if (rule.cssRules) { const nested=walk(rule.cssRules); if (nested) return nested; }
              if (rule.selectorText?.includes('.goal-card__children') &&
                  rule.selectorText?.includes('::before') &&
                  rule.style?.left?.includes('--subgoal-depth')) return {
                    left:rule.style.left,
                    height:rule.style.height,
                  };
            }
            return null;
          };
          for (const sheet of document.styleSheets) {
            const found=walk(sheet.cssRules); if (found) return found;
          }
          return null;
        }"""
    )
    child_text_padding_rule = page.evaluate(
        """() => {
          const walk=rules => {
            for (const rule of rules) {
              if (rule.cssRules) { const nested=walk(rule.cssRules); if (nested) return nested; }
              if (rule.selectorText?.includes('.goal-card__children') &&
                  rule.selectorText?.includes('.goal-card__text') &&
                  rule.style?.paddingLeft?.includes('--subgoal-depth')) return rule.style.paddingLeft;
            }
            return null;
          };
          for (const sheet of document.styleSheets) {
            const found=walk(sheet.cssRules); if (found) return found;
          }
          return null;
        }"""
    )

    assert _style(children, "position") == "relative"
    assert _style(children, "padding") == "0px"
    assert _style(children, "margin-top") == "2px"
    assert _style(children, "margin-bottom") == "16px"
    assert _style(children, "row-gap") == "2px"
    assert guide == {
        "content": '""',
        "position": "absolute",
        "margin-left": "14px",
        "border-left-width": "2px",
        "border-left-color": "rgba(0, 0, 0, 0.07)",
    }
    assert guide_formula_rule == {
        "left": "calc(20px + 14px * var(--subgoal-depth))",
        "height": "calc(100% - 9px)",
    }
    assert child_text_padding_rule == "calc(22px + 14px * var(--subgoal-depth))"
    source = GOAL_CARD_SOURCE.read_text()
    assert ':children="child.children"' in source
    assert ':depth="depth + 1"' in source, "recursive renderer stopped before live depth six"


def test_p_22_board_row_type_columns_and_truncation(ui_f2: UiSession) -> None:
    page = ui_f2.page
    page.wait_for_selector(PARENT_ROW)
    _expand(page)
    row = page.locator(CHILD_ROW)
    title = row.locator('.goal-card__title')
    meta = row.locator('.goal-card__meta').first
    checkbox = row.locator('label.checkbox')

    assert (_box(checkbox)["width"], _box(checkbox)["height"]) == (20, 20)
    assert _style(checkbox, "--animation_duration") == "200ms"
    assert [_style(title, prop) for prop in ("font-size", "line-height", "font-weight")] == [
        "15px", "22px", "400"
    ]
    assert _style(title, "word-break") == "break-word"
    assert [_style(title, prop) for prop in ("white-space", "overflow", "text-overflow")] == [
        "normal", "visible", "clip"
    ]
    assert [_style(meta, prop) for prop in (
        "margin-top", "font-size", "line-height", "font-weight", "color",
        "white-space", "overflow", "text-overflow",
    )] == [
        "2px", "13px", "18px", "400", "rgba(45, 48, 54, 0.3)",
        "nowrap", "hidden", "ellipsis",
    ]
    assert _style(row, "border-width") in {"0px", "0px 0px 0px 0px"}


def test_p_22_board_row_hover_active_full_cast(ui_f2: UiSession) -> None:
    page = ui_f2.page
    page.wait_for_selector(PARENT_ROW)
    _expand(page)
    card, row = page.locator(CHILD), page.locator(CHILD_ROW)
    before = {"card": _box(card), "row": _box(row)}
    row.hover()
    hover = {"card": _box(card), "row": _box(row)}
    assert hover == before
    assert _style(card, "background-color") == "rgb(246, 246, 246)"
    assert _style(card, "transition-duration") == "0s"
    assert _style(row, "cursor") == "grab"  # D11 adaptation
    assert card.evaluate(
        "el => el.getAnimations().filter(a => a.effect?.target===el).length"
    ) == 0

    page.mouse.move(2, 2)
    return_animations = card.evaluate(
        """el => el.getAnimations().filter(a => a.effect?.target===el).map(a => ({
          duration:a.effect.getTiming().duration,
          easing:getComputedStyle(a.effect.target).transitionTimingFunction
        }))"""
    )
    assert return_animations == [
        {"duration": 300, "easing": "cubic-bezier(0.165, 0.84, 0.44, 1)"}
    ]
    assert _box(card) == before["card"] and _box(row) == before["row"]

    box = _box(row)
    page.mouse.move(box["x"] + box["width"] * 0.7, box["y"] + 4)
    page.mouse.down()
    assert _box(card) == before["card"] and _box(row) == before["row"]
    assert _style(card, "background-color") == "rgb(246, 246, 246)"
    page.mouse.up()


def test_p_22_detail_order_and_alignment_grid(ui_f2: UiSession) -> None:
    page = ui_f2.page
    page.wait_for_selector(PARENT_ROW)
    _open_detail(page)
    _wait_for_desktop_detail_entry(page)
    section = page.locator(DETAIL)
    body = page.locator('#goal-detail [data-cap="edit-body"]')
    row = section.locator('.goal-detail__subgoal').first
    checkbox, title = row.locator('label.checkbox'), row.locator('.goal-detail__subgoal-title')

    assert section.evaluate(
        "(section,body) => !!(section.compareDocumentPosition(body) & Node.DOCUMENT_POSITION_FOLLOWING)",
        body.element_handle(),
    ), "subgoal list belongs between hero title and notes"
    assert [_style(section, prop) for prop in (
        "max-width", "padding-right", "margin-top", "margin-bottom",
    )] == ["534px", "80px", "10px", "36px"]
    assert [_style(row, prop) for prop in (
        "display", "align-items", "padding", "border-radius", "background-color", "border-width",
    )] == ["flex", "flex-start", "6px", "8px", "rgb(255, 255, 255)", "0px"]
    row_box = _box(row)
    assert abs((_box(checkbox)["x"] - row_box["x"]) - 6) <= 1
    assert abs((_box(title)["x"] - row_box["x"]) - 34) <= 1


def test_p_22_detail_type_done_hover_and_active(ui_f2: UiSession) -> None:
    page = ui_f2.page
    page.wait_for_selector(PARENT_ROW)
    _open_detail(page)
    _wait_for_desktop_detail_entry(page)
    row = page.locator(f"{DETAIL} .goal-detail__subgoal").first
    checkbox, title = row.locator('label.checkbox'), row.locator('.goal-detail__subgoal-title')

    assert (_box(checkbox)["width"], _box(checkbox)["height"]) == (20, 20)
    assert [_style(title, prop) for prop in (
        "font-size", "line-height", "font-weight", "word-break", "text-decoration-line",
    )] == ["15px", "22px", "400", "break-word", "none"]
    before = _box(row)
    row.hover()
    assert _box(row) == before
    assert _style(row, "background-color") == "rgb(246, 246, 246)"
    assert _style(title, "text-decoration-line") == "none"

    title_box = _box(title)
    page.mouse.move(title_box["x"] + 2, title_box["y"] + 2)
    page.mouse.down()
    assert _style(row, "background-color") == "rgb(246, 246, 246)"
    assert _box(row) == before
    page.mouse.move(2, 2)
    page.mouse.up()

    row.evaluate("el => el.classList.add('goal-detail__subgoal--done')")
    assert _style(checkbox, "opacity") == "0.5"
    title.evaluate(
        "el => Promise.all(el.getAnimations().map(a => a.finished.catch(() => undefined)))"
    )
    assert _style(title, "color") == "rgba(45, 48, 54, 0.6)"
    assert _style(title, "text-decoration-line") == "none"


def test_p_22_inline_add_affordances(ui_f2: UiSession) -> None:
    page = ui_f2.page
    page.wait_for_selector(PARENT_ROW)
    _expand(page)
    board_add = page.locator(BOARD_ADD)
    assert board_add.count() == 1 and board_add.inner_text().strip() == "Add..."
    assert board_add.get_attribute("role") == "button"
    assert _style(board_add, "opacity") == "0.5"
    board_add.hover()
    assert _style(board_add, "opacity") == "0.75"
    request_start = len(ui_f2.request_log)
    board_add.click()
    board_editor = page.locator(f'{PARENT} [data-role="subgoal-add-editor"]')
    assert board_editor.count() == 1
    assert [_style(board_editor, prop) for prop in (
        "padding", "font-size", "line-height", "border-radius", "outline", "box-shadow",
    )] == ["6px", "15px", "22px", "8px", "rgb(215, 215, 215) solid 1px", "rgba(0, 0, 0, 0.07) 0px 3px 4px 0px"]
    assert _mutating_requests(ui_f2, request_start) == []

    page.keyboard.press("Escape")
    _open_detail(page)
    detail_add = page.locator(f'{DETAIL} [data-role="subgoal-add"]')
    actions = page.locator(f'{DETAIL} [data-role="subgoal-actions"]')
    assert detail_add.count() == 1 and detail_add.inner_text().strip() == "Add..."
    assert actions.count() == 1
    assert [_style(actions, prop) for prop in (
        "position", "right", "top", "width", "column-gap", "opacity",
    )] == ["absolute", "0px", "6px", "60px", "8px", "0"]
    assert actions.locator('[data-role="subgoal-add-to-top"]').count() == 1
    assert actions.locator('[data-role="subgoal-sort"]').count() == 1
    page.locator(DETAIL).hover()
    action_animations = actions.evaluate(
        """el => el.getAnimations().map(a => ({
          duration:a.effect.getTiming().duration,
          easing:getComputedStyle(a.effect.target).transitionTimingFunction
        }))"""
    )
    assert action_animations == [
        {"duration": 250, "easing": "cubic-bezier(0.165, 0.84, 0.44, 1)"}
    ]
    page.wait_for_timeout(270)
    assert _style(actions, "opacity") == "1"

    detail_list = page.locator(DETAIL)
    add_box = _box(detail_add)
    list_box = _box(detail_list)
    request_start = len(ui_f2.request_log)
    detail_add.click()
    detail_editor = page.locator(f'{DETAIL} [data-role="subgoal-add-editor"]')
    assert detail_editor.count() == 1
    assert _box(detail_editor) == add_box, "add editor did not replace its row in place"
    assert _box(detail_list) == list_box, "add-mode entry moved the surrounding list"
    assert detail_editor.evaluate("el => el.getAnimations({subtree:true}).length") == 0
    assert _mutating_requests(ui_f2, request_start) == []


def test_p_22_mobile_detail_keeps_normal_row_grid(ui_f2: UiSession) -> None:
    page = ui_f2.page
    page.set_viewport_size({"width": 693, "height": 900})
    page.wait_for_selector(PARENT_ROW)
    _open_detail(page)
    row = page.locator(f"{DETAIL} .goal-detail__subgoal").first
    checkbox = row.locator("label.checkbox")
    title = row.locator(".goal-detail__subgoal-title")

    assert (_box(checkbox)["width"], _box(checkbox)["height"]) == (20, 20)
    assert [_style(title, prop) for prop in ("font-size", "line-height", "font-weight")] == [
        "15px", "22px", "400",
    ]
    assert "goal-detail__subgoal--compact" not in (row.get_attribute("class") or "")


def test_p_22_feel_invariants_and_no_write_on_presentation_gestures(ui_f2: UiSession) -> None:
    page = ui_f2.page
    page.wait_for_selector(PARENT_ROW)
    start = len(ui_f2.request_log)
    _expand(page)
    row = page.locator(CHILD_ROW)
    before = _box(row)
    row.hover()
    assert _box(row) == before, "hover never moves checkbox/title/meta grid"
    page.locator(TOGGLE).click()
    page.wait_for_timeout(50)
    assert page.locator(CHILD_ROW).count() == 0, "collapse leaves no hidden hit target"
    assert _mutating_requests(ui_f2, start) == []
