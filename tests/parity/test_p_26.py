"""P-26: compact board-card alignment grid inside vertical columns."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from playwright.sync_api import Locator, Page

from tests.ui.conftest import UiSession
from tools.parity.probe_p26_card_grid import decode_reference


ROOT = Path(__file__).resolve().parents[2]
COLUMN_SOURCE = ROOT / "web/src/components/Column.vue"
GOAL_CARD_SOURCE = ROOT / "web/src/components/GoalCard.vue"
BOARD_SOURCE = ROOT / "web/src/components/Board.vue"


def _column(vertical: str) -> str:
    return f'[data-vertical="{vertical}"]'


def _current(vertical: str) -> str:
    return f'{_column(vertical)} [data-role="period-slide"][data-state="current"]'


def _stack(vertical: str) -> str:
    return f'{_current(vertical)} .pattern-vertical-board__body > .card-stack'


def _top_cards(page: Page, vertical: str) -> Locator:
    return page.locator(f'{_stack(vertical)} > .goal-card')


def _box(locator: Locator) -> dict[str, float]:
    box = locator.bounding_box()
    assert box is not None, f"{locator} has no rectangle"
    return box


def _style(locator: Locator, name: str, pseudo: str | None = None) -> str:
    return locator.evaluate(
        "(el,args) => getComputedStyle(el,args.pseudo).getPropertyValue(args.name)",
        {"name": name, "pseudo": pseudo},
    )


def _same_rect(actual: dict[str, float], expected: dict[str, float], tolerance: float = 0.5) -> None:
    for key in ("x", "y", "width", "height"):
        assert abs(actual[key] - expected[key]) <= tolerance, (key, actual, expected)


def _mutating_requests(session: UiSession, start: int) -> list[dict[str, Any]]:
    return [
        item for item in session.request_log[start:]
        if item["method"] not in {"GET", "HEAD", "OPTIONS"}
    ]


def _css_rule(page: Page, selector_fragment: str, property_name: str) -> str | None:
    return page.evaluate(
        """([fragment,property]) => {
          const walk=rules=>{for(const rule of rules){
            if(rule.cssRules){const nested=walk(rule.cssRules);if(nested!==null)return nested;}
            if(rule.selectorText?.includes(fragment)&&rule.style?.getPropertyValue(property))
              return rule.style.getPropertyValue(property);
          }return null;};
          for(const sheet of document.styleSheets){try{const found=walk(sheet.cssRules);if(found!==null)return found;}catch{}}
          return null;
        }""",
        [selector_fragment, property_name],
    )


def test_p_26_reference_grid_is_pinned_to_bundle_and_selector_chains() -> None:
    """ASSERT A1: pinned assets encode column, card, inner-grid, nesting, and state facts."""
    reference = decode_reference()
    assert reference["topology"] == {
        "column": ".VerticalsView-column > div[100% x 100%] > .Swiper > .Swiper-wrap > .Swiper-slide > .Panel",
        "scroll_owner": ".Swiper-slide",
        "padding_owner": ".Panel-children (6px inline) and its direct .Goals (80px block-start)",
        "card_list": ".Goals-list > .GoalRowWrapper > .GoalRow",
        "empty_and_single_tail": "normal InlineAddGoalRow follows .Goals-list; noncompact hover area follows add row",
    }
    assert reference["columnGrid"]["card_inset_px"] == {"inline": 6, "top_from_column": 80}
    assert reference["columnGrid"]["inactive_width"] == {
        "min_px": 225, "max_px": 400, "basis": "calc((100% - 27%) / 5)", "grow": 1,
    }
    assert reference["columnGrid"]["active_width"] == {
        "min_px": 400, "max_px": 600, "basis": "27%", "grow": 1,
    }
    assert reference["cardGrid"]["wrapper_bottom_spacing_px"] == 2
    assert reference["cardGrid"]["top_level_and_nested_spacing_equal"] is True
    assert reference["internalGrid"] == {
        "checkbox_px": 20,
        "checkbox_top_from_content_px": 1,
        "title_x_from_card_px": 34,
        "title_column_formula": "card width - 46px",
        "title": {"font_px": 15, "line_px": 22, "weight": 400, "wrap": "word-break:break-word", "clamp": None},
        "meta": {"margin_top_px": 2, "font_px": 13, "line_px": 18, "overflow": "hidden ellipsis"},
        "one_two_three_line_card_heights_without_meta_px": [34, 56, 78],
        "one_two_three_line_card_heights_with_one_meta_px": [54, 76, 98],
    }
    chains = reference["selectorChains"]
    assert ".VerticalsView-column" in chains["36a012a6d5-useUserStartupNotifications-CnLPtg6B.css"]
    assert ".Panel-children>.Goals" in chains["1e1bffbb6c-index-Bz4DOylZ.css"]
    assert ".GoalRow" in chains["575420cb93-reference-9KLbKQmz.css"]


def test_p_26_scroll_owner_header_and_first_card_grid(ui_f2: UiSession) -> None:
    """ASSERT A2: each period slide owns vertical scroll; cards begin at (6,80), not (6,144)."""
    page = ui_f2.page
    page.wait_for_selector('[data-goal-id="SYNDAY01"]')
    column = page.locator(_column("day"))
    slide = page.locator(_current("day"))
    header = slide.locator(".pattern-vertical-board__header")
    body = slide.locator(".pattern-vertical-board__body")
    card = page.locator('[data-goal-id="SYNDAY01"]')
    column_box, slide_box, card_box = _box(column), _box(slide), _box(card)

    assert _style(column, "overflow-y") == "hidden"
    assert _style(slide, "overflow-y") == "auto"
    assert _style(slide, "overscroll-behavior-y") == "contain"
    assert abs(slide_box["height"] - column_box["height"]) <= 1
    assert _style(header, "position") == "absolute"
    assert [_style(header, side) for side in (
        "padding-top", "padding-right", "padding-bottom", "padding-left",
    )] == ["24px", "8px", "0px", "12px"]
    assert abs(card_box["x"] - column_box["x"] - 6) <= 1
    assert abs(column_box["x"] + column_box["width"] - card_box["x"] - card_box["width"] - 6) <= 1
    assert abs(card_box["y"] - column_box["y"] - 80) <= 1
    assert [_style(body, side) for side in ("padding-right", "padding-bottom", "padding-left")] == [
        "6px", "64px", "6px",
    ]


def test_p_26_column_width_rule_and_breakpoint_source(ui_f2: UiSession) -> None:
    """ASSERT A3: desktop width source uses reference formula; existing 390px full-page fork stays."""
    page = ui_f2.page
    page.wait_for_selector(_column("day"))
    day, week = page.locator(_column("day")), page.locator(_column("week"))
    assert "flex: 1 0 calc((100% - 27%) / 5);" in COLUMN_SOURCE.read_text()
    assert _css_rule(page, ".pattern-vertical-board__column", "flex-basis") == "14.6%"
    assert [_style(day, prop) for prop in ("min-width", "max-width", "flex-basis", "flex-grow")] == [
        "400px", "600px", "27%", "1",
    ]
    assert [_style(week, prop) for prop in ("min-width", "max-width", "flex-basis", "flex-grow")] == [
        "225px", "400px", "14.6%", "1",
    ]

    page.set_viewport_size({"width": 390, "height": 844})
    assert [_style(page.locator(_column("day")), prop) for prop in (
        "width", "min-width", "max-width", "flex-basis",
    )] == ["390px", "100%", "none", "100%"]


def test_p_26_top_level_and_nested_gutter_are_same_two_pixels(ui_f2: UiSession) -> None:
    """ASSERT A4: wrappers own one 2px pitch; nesting adds no different gap or width inset."""
    page = ui_f2.page
    page.wait_for_selector('[data-goal-id="SYNORD01"]')
    first = page.locator('[data-goal-id="SYNORD01"]')
    second = page.locator('[data-goal-id="SYNORD02"]')
    a, b = _box(first), _box(second)
    assert abs(b["y"] - (a["y"] + a["height"]) - 2) <= 1
    assert _style(page.locator(_stack("week")), "row-gap") == "2px"
    assert _style(first, "margin") == "0px"
    assert _style(first, "border-width") == "0px"
    assert _style(first, "box-shadow") == "none"

    toggle = page.locator('[data-goal-id="SYNDAY01"] [data-role="subgoal-toggle"]')
    toggle.click()
    children = page.locator('[data-goal-id="SYNDAY01"] > .goal-card__children')
    child_cards = children.locator(":scope > .goal-card")
    child_a, child_b = _box(child_cards.nth(0)), _box(child_cards.nth(1))
    assert abs(child_b["y"] - (child_a["y"] + child_a["height"]) - 2) <= 1
    assert _style(children, "row-gap") == "2px"


def test_p_26_one_line_card_box_and_action_overlay(ui_f2: UiSession) -> None:
    """ASSERT A5: one-line card is 34px; absolute actions consume no title width or row height."""
    page = ui_f2.page
    page.wait_for_selector('[data-goal-id="SYNORD01"]')
    card = page.locator('[data-goal-id="SYNORD01"]')
    row = card.locator(":scope > .goal-card__row")
    text = row.locator(":scope > .goal-card__text")
    tools = row.locator(":scope > .goal-card__tools")
    card_box, row_box, text_box = _box(card), _box(row), _box(text)

    assert card_box["height"] == 34
    assert row_box["height"] == 22
    assert [_style(card, prop) for prop in (
        "width", "padding", "border-radius", "border-width", "box-shadow",
    )] == [_style(page.locator(_stack("week")), "width"), "6px", "8px", "0px", "none"]
    assert abs(text_box["width"] - (card_box["width"] - 32)) <= 1
    assert _style(tools, "position") == "absolute"
    assert _box(tools)["height"] <= 24
    assert _style(card, "background-color") == "rgb(255, 255, 255)"
    assert _style(page.locator('[data-goal-id="SYNORD02"]'), "background-color") == "rgb(255, 255, 255)"


def test_p_26_checkbox_title_meta_baselines_and_natural_wrap(ui_f2: UiSession) -> None:
    """ASSERT A6: checkbox is +1px; title/meta use 22/18px rails and never clamp long words."""
    page = ui_f2.page
    page.wait_for_selector('[data-goal-id="SYNDAY01"]')
    card = page.locator('[data-goal-id="SYNDAY01"]')
    row = card.locator(":scope > .goal-card__row")
    checkbox = row.locator(":scope > .goal-card__checkbox")
    text = row.locator(":scope > .goal-card__text")
    title = text.locator(":scope > .goal-card__title")
    meta = text.locator(":scope > .goal-card__meta").first
    card_box, checkbox_box, title_box, meta_box = _box(card), _box(checkbox), _box(title), _box(meta)

    assert abs(checkbox_box["y"] - title_box["y"] - 1) <= 1
    assert abs(title_box["x"] - card_box["x"] - 34) <= 1
    assert abs(meta_box["y"] - title_box["y"] - title_box["height"] - 2) <= 1
    assert [_style(title, prop) for prop in (
        "font-size", "line-height", "font-weight", "word-break", "white-space", "overflow",
    )] == ["15px", "22px", "400", "break-word", "normal", "visible"]
    assert [_style(meta, prop) for prop in (
        "margin-top", "font-size", "line-height", "white-space", "overflow", "text-overflow",
    )] == ["2px", "13px", "18px", "nowrap", "hidden", "ellipsis"]

    original = title.text_content()
    title.evaluate("(el) => { el.textContent='x'.repeat(300) }")
    assert _box(title)["height"] >= 88, "unbroken word was clamped before four lines"
    assert title.evaluate("el => el.scrollHeight") == round(_box(title)["height"])
    # SYNDAY01 renders 62px of secondary actors: parent meta 20px, toggle 22px, progress 20px.
    # Card height is title height + those actors + 12px vertical padding: 176 + 62 + 12 = 250.
    assert _box(card)["height"] == _box(title)["height"] + 62 + 12
    title.evaluate("(el,text) => { el.textContent=text }", original)


def test_p_26_board_nesting_indents_text_only(ui_f2: UiSession) -> None:
    """ASSERT A7: nested board cards keep full card/row/checkbox rails; titles step 14px."""
    page = ui_f2.page
    page.wait_for_selector('[data-goal-id="SYNDAY01"]')
    parent = page.locator('[data-goal-id="SYNDAY01"]')
    parent.locator('[data-role="subgoal-toggle"]').click()
    child = page.locator('[data-goal-id="SYNSUB01"]')
    parent_row, child_row = parent.locator(":scope > .goal-card__row"), child.locator(":scope > .goal-card__row")
    parent_box, child_box = _box(parent), _box(child)
    parent_row_box, child_row_box = _box(parent_row), _box(child_row)
    assert abs(child_box["x"] - parent_box["x"]) <= 1
    assert abs(child_box["width"] - parent_box["width"]) <= 1
    assert abs(child_row_box["x"] - parent_row_box["x"]) <= 1
    assert abs(child_row_box["width"] - parent_row_box["width"]) <= 1
    parent_checkbox = parent_row.locator(":scope > .goal-card__checkbox")
    child_checkbox = child_row.locator(":scope > .goal-card__checkbox")
    parent_title = parent_row.locator(":scope > .goal-card__text > .goal-card__title")
    child_title = child_row.locator(":scope > .goal-card__text > .goal-card__title")
    assert abs(_box(child_checkbox)["x"] - _box(parent_checkbox)["x"]) <= 1
    assert abs(
        _box(child_title)["x"] - _box(parent_title)["x"] - 14
    ) <= 1


@pytest.mark.skip(
    reason=(
        "BLOCKED-ON-STAMP (D43): F2 has no empty column; unblock by moving and returning "
        "existing cards until one column is empty and one has one card"
    )
)
def test_p_26_empty_and_single_card_columns_keep_same_entry_rail(ui_f2: UiSession) -> None:
    """ASSERT A8: empty/single columns use one resting Add... row at the same (6,80) rail."""
    page = ui_f2.page
    page.wait_for_selector('[data-goal-id="SYNDAY01"]')
    day_card = page.locator('[data-goal-id="SYNDAY01"]')
    day_add = page.locator(f'{_stack("day")} > [data-role="column-add"]')
    assert day_add.count() == 1
    assert abs(_box(day_add)["y"] - (_box(day_card)["y"] + _box(day_card)["height"]) - 2) <= 1

    page.goto(f"{ui_f2.base_url}/h/2025-01-06")
    page.wait_for_selector(_current("day"))
    assert _top_cards(page, "day").count() == 0
    empty_add = page.locator(f'{_stack("day")} > [data-role="column-add"]')
    column = page.locator(_column("day"))
    assert empty_add.count() == 1 and empty_add.inner_text().strip() == "Add..."
    assert empty_add.get_attribute("role") == "button"
    add_box, column_box = _box(empty_add), _box(column)
    assert abs(add_box["x"] - column_box["x"] - 6) <= 1
    assert abs(add_box["y"] - column_box["y"] - 80) <= 1
    assert abs(add_box["width"] - column_box["width"] + 12) <= 1
    assert add_box["height"] == 34
    assert _style(empty_add, "opacity") == "0.5"

    start = len(ui_f2.request_log)
    before = _box(empty_add)
    empty_add.click()
    editor = page.locator(f'{_stack("day")} > [data-role="column-add-editor"]')
    _same_rect(_box(editor), before)
    assert _mutating_requests(ui_f2, start) == []


def test_p_26_hover_press_and_static_state_full_cast(ui_f2: UiSession) -> None:
    """ASSERT A9: hover/press/state alter paint only; no grid actor or sibling moves."""
    page = ui_f2.page
    page.wait_for_selector('[data-goal-id="SYNORD01"]')
    card = page.locator('[data-goal-id="SYNORD01"]')
    row = card.locator(":scope > .goal-card__row")
    actors = [
        page.locator(_column("week")), page.locator(f'{_current("week")} .pattern-vertical-board__header'),
        page.locator(f'{_current("week")} .pattern-vertical-board__body'), card, row,
        card.locator(".goal-card__checkbox"), card.locator(".goal-card__text"),
        card.locator(".goal-card__title"), card.locator(".goal-card__tools"),
        page.locator('[data-goal-id="SYNORD02"]'),
    ]
    before = [_box(actor) for actor in actors]
    start = len(ui_f2.request_log)
    card.hover()
    hover = [_box(actor) for actor in actors]
    for actual, expected in zip(hover, before, strict=True):
        _same_rect(actual, expected)
    assert _style(card, "background-color") == "rgb(246, 246, 246)"
    assert _style(card, "transition-duration") == "0s"
    assert card.evaluate("el => el.getAnimations().filter(a=>a.effect?.target===el).length") == 0
    assert _style(row, "cursor") == "grab"

    original_style = card.get_attribute("style") or ""
    card.evaluate("el => el.classList.add('goal-card--done')")
    _same_rect(_box(card), before[3])
    card.evaluate("el => {el.classList.remove('goal-card--done');el.classList.add('goal-card--colored');el.dataset.colored='true';el.style.setProperty('--goal-card-background','#ecce32')}")
    coloured = _box(card)
    card.hover()
    _same_rect(_box(card), coloured)
    assert _style(card, "background-color") == "rgb(236, 206, 50)"
    card.evaluate(
        "(el,style) => {el.classList.remove('goal-card--colored');el.dataset.colored='false';el.setAttribute('style',style)}",
        original_style,
    )
    page.mouse.move(2, 2)
    card.hover()

    box = _box(row)
    page.mouse.move(box["x"] + box["width"] * 0.7, box["y"] + box["height"] - 2)
    page.mouse.down()
    pressed = [_box(actor) for actor in actors]
    for actual, expected in zip(pressed, before, strict=True):
        _same_rect(actual, expected)
    assert _style(card, "background-color") == "rgb(246, 246, 246)"
    assert _style(row, "cursor") == "grab"
    page.mouse.up()
    assert _mutating_requests(ui_f2, start) == []


def test_p_26_feel_invariants_source_and_no_write_boundary(ui_f2: UiSession) -> None:
    """ASSERT A10: natural-height CSS has no clamp/fixed card height; presentation writes nothing."""
    page = ui_f2.page
    page.wait_for_selector('[data-goal-id="SYNORD01"]')
    source = GOAL_CARD_SOURCE.read_text()
    board_source = BOARD_SOURCE.read_text()
    assert "line-clamp" not in source
    assert "-webkit-line-clamp" not in source
    assert ".goal-card.goal-card {" in source
    assert "width: 100%;" in source
    assert "box-sizing: border-box;" in source
    assert ".goal-card.goal-card > .goal-card__row" in source
    assert "cursor: grab;" in source and "cursor: grabbing;" not in source
    assert "body.pattern-vertical-board__no-select" in board_source
    assert "cursor: grabbing !important;" in board_source

    start = len(ui_f2.request_log)
    card = page.locator('[data-goal-id="SYNORD01"]')
    card.hover()
    row = card.locator(":scope > .goal-card__row")
    box = _box(row)
    page.mouse.move(box["x"] + box["width"] * 0.7, box["y"] + box["height"] - 2)
    page.mouse.down()
    page.mouse.up()
    assert _mutating_requests(ui_f2, start) == []
