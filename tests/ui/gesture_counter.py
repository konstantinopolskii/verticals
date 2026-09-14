"""Real-pointer gesture harness for the UI suite."""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

from playwright.sync_api import Page


def _selector_vertical(page: Page, selector: str) -> str | None:
    locator = page.locator(selector).first
    if locator.count() == 0:
        return None
    return locator.evaluate("el => el.closest('[data-vertical]')?.dataset.vertical || null")


def _drag_into_column(
    page: Page, vertical: str, start_x: float, start_vertical: str | None
) -> None:
    """Move a held pointer across live deck strips until mouseenter activates target."""
    if vertical == "day":
        return
    column = page.locator(f'.pattern-vertical-board__column[data-vertical="{vertical}"]')
    target_box = column.bounding_box()
    viewport = page.viewport_size
    if target_box is None or viewport is None:
        raise AssertionError(f"drag target column {vertical!r} has no geometric context")

    active_class = "pattern-vertical-board__column--deck-active"
    verticals = ("day", "week", "month", "quarter", "year", "decade", "life")
    start_index = verticals.index(start_vertical) if start_vertical in verticals else 0
    target_index = verticals.index(vertical)
    direction = 1 if target_index >= start_index else -1
    walk = verticals[start_index + direction:target_index + direction:direction]
    strip = page.locator('[data-role="column-strip"]')
    x = start_x
    for walk_vertical in walk:
        walk_column = page.locator(
            f'.pattern-vertical-board__column[data-vertical="{walk_vertical}"]'
        )
        walk_box = walk_column.bounding_box()
        if walk_box is None:
            raise AssertionError(f"drag walk column {walk_vertical!r} has no box")
        if walk_box["x"] >= viewport["width"] or walk_box["x"] + walk_box["width"] <= 0:
            strip.evaluate(
                "(owner, h) => { const c = owner.querySelector(`[data-vertical=\\\"${h}\\\"]`); "
                "owner.scrollLeft += c.getBoundingClientRect().left - owner.getBoundingClientRect().left; }",
                walk_vertical,
            )
            walk_box = walk_column.bounding_box()
        if walk_box is None:
            raise AssertionError(f"drag walk column {walk_vertical!r} vanished")
        y = walk_box["y"] + walk_box["height"] / 2
        edge_x = page.evaluate(
            """({vertical, y}) => {
              for (let x = 1; x < innerWidth - 1; x += 1) {
                const hit = document.elementFromPoint(x, y)?.closest('[data-vertical]')?.dataset.vertical;
                if (hit === vertical) return x;
              }
              return null;
            }""",
            {"vertical": walk_vertical, "y": y},
        )
        if edge_x is None:
            raise AssertionError(f"drag found no native hit strip for {walk_vertical!r}")
        page.mouse.move(edge_x, y)
        x = edge_x
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline:
            if walk_vertical == "day" or active_class in (walk_column.get_attribute("class") or ""):
                break
            page.wait_for_timeout(25)
        else:
            hit = page.evaluate(
                "point => document.elementFromPoint(point.x, point.y)?.closest('[data-vertical]')?.dataset.vertical || null",
                {"x": edge_x, "y": y},
            )
            raise AssertionError(
                f"drag never entered {walk_vertical!r} column's live strip "
                f"(point=({edge_x}, {y}), hit={hit!r}, box={walk_box})"
            )
        previous = None
        stable_deadline = time.monotonic() + 2.0
        while time.monotonic() < stable_deadline:
            current = walk_column.bounding_box()
            if current is not None:
                live_x = page.evaluate(
                    """({vertical, y}) => {
                      for (let x = 1; x < innerWidth - 1; x += 1) {
                        const hit = document.elementFromPoint(x, y)?.closest('[data-vertical]')?.dataset.vertical;
                        if (hit === vertical) return x;
                      }
                      return null;
                    }""",
                    {"vertical": walk_vertical, "y": y},
                )
                if live_x is not None:
                    page.mouse.move(live_x, y)
                    x = live_x
            if (
                active_class in (walk_column.get_attribute("class") or "")
                and current is not None and previous is not None and all(
                abs(current[key] - previous[key]) < 0.5 for key in current
                )
            ):
                break
            previous = current
            page.wait_for_timeout(100)
        else:
            raise AssertionError(f"drag-active {walk_vertical!r} geometry did not settle")

    if active_class not in (column.get_attribute("class") or ""):
        y = target_box["y"] + target_box["height"] / 2
        while x < viewport["width"] - 1:
            x += min(6, viewport["width"] - 1 - x)
            page.mouse.move(x, y)
            if active_class in (column.get_attribute("class") or ""):
                break
            page.wait_for_timeout(10)
        else:
            raise AssertionError(f"drag never entered {vertical!r} column's live strip")

    previous = None
    deadline = time.monotonic() + 10.0
    while time.monotonic() < deadline:
        current = column.bounding_box()
        if current is None or active_class not in (column.get_attribute("class") or ""):
            previous = None
            page.wait_for_timeout(25)
            continue
        safe_x = float(viewport["width"]) * (0.8 if direction > 0 else 0.2)
        visible_left = max(current["x"], 0.0)
        visible_right = min(current["x"] + current["width"], float(viewport["width"]))
        follow_x = min(max(safe_x, visible_left + 2), visible_right - 2)
        follow_y = min(max(current["y"] + current["height"] / 2, 2.0), float(viewport["height"] - 2))
        page.mouse.move(follow_x, follow_y)
        hit = page.evaluate(
            "point => document.elementFromPoint(point.x, point.y)?.closest('[data-vertical]')?.dataset.vertical || null",
            {"x": follow_x, "y": follow_y},
        )
        if hit == vertical and previous is not None and all(
            abs(current[key] - previous[key]) < 0.5 for key in current
        ):
            return
        previous = current
        page.wait_for_timeout(100)
    raise AssertionError(f"drag-activated {vertical!r} column never reached stable geometry")


class GestureCounter:
    """Count committed gestures while preserving real pointer behavior."""

    def __init__(self, page: Page, activate_column: Callable[[Page, str], None]) -> None:
        self.page = page
        self.activate_column = activate_column
        self.count = 0

    def click(self, selector: str, **kwargs: Any) -> None:
        vertical = _selector_vertical(self.page, selector)
        if vertical is not None:
            self.activate_column(self.page, vertical)
        self.page.click(selector, **kwargs)
        self.count += 1

    def press_committing(self, selector: str, key: str) -> None:
        self.page.press(selector, key)
        self.count += 1

    def fill(self, selector: str, value: str) -> None:
        self.page.fill(selector, value)
        self.count += 1

    def drag(
        self,
        source: str,
        target: str,
        source_position: dict[str, float] | None = None,
        target_position: dict[str, float] | None = None,
    ) -> None:
        source_vertical = _selector_vertical(self.page, source)
        target_vertical = _selector_vertical(self.page, target)
        if source_vertical is not None:
            self.activate_column(self.page, source_vertical)
        src_box = self.page.locator(source).bounding_box()
        if src_box is None:
            raise AssertionError("drag source has no live bounding box")
        sx = src_box["x"] + (source_position["x"] if source_position else src_box["width"] / 2)
        sy = src_box["y"] + (source_position["y"] if source_position else src_box["height"] / 2)
        self.page.mouse.move(sx, sy)
        self.page.mouse.down()
        if target_vertical is not None and target_vertical != source_vertical:
            _drag_into_column(self.page, target_vertical, sx, source_vertical)
        tgt_box = self.page.locator(target).bounding_box()
        if tgt_box is None:
            self.page.mouse.up()
            raise AssertionError("drag target has no live bounding box")
        desired_tx = tgt_box["x"] + (target_position["x"] if target_position else tgt_box["width"] / 2)
        desired_ty = tgt_box["y"] + (target_position["y"] if target_position else tgt_box["height"] / 2)
        viewport = self.page.viewport_size
        if viewport is None:
            tx, ty = desired_tx, desired_ty
        else:
            visible_left = max(0.0, tgt_box["x"])
            visible_right = min(float(viewport["width"]), tgt_box["x"] + tgt_box["width"])
            visible_top = max(0.0, tgt_box["y"])
            visible_bottom = min(float(viewport["height"]), tgt_box["y"] + tgt_box["height"])
            if visible_right - visible_left < 4 or visible_bottom - visible_top < 4:
                self.page.mouse.up()
                raise AssertionError(f"drag target in {target_vertical!r} has no visible drop area")
            tx = min(max(desired_tx, visible_left + 2), visible_right - 2)
            ty = min(max(desired_ty, visible_top + 2), visible_bottom - 2)
            if target_vertical is not None:
                candidates = [{"x": tx, "y": ty}]
                for x_ratio in (0.25, 0.5, 0.75):
                    for y_ratio in (0.25, 0.5, 0.75):
                        candidates.append({
                            "x": visible_left + (visible_right - visible_left) * x_ratio,
                            "y": visible_top + (visible_bottom - visible_top) * y_ratio,
                        })
                for candidate in candidates:
                    hit = self.page.evaluate(
                        "point => document.elementFromPoint(point.x, point.y)?.closest('[data-vertical]')?.dataset.vertical || null",
                        candidate,
                    )
                    if hit == target_vertical:
                        tx, ty = candidate["x"], candidate["y"]
                        break
        self.page.mouse.move(tx, ty, steps=5)
        self.page.wait_for_timeout(50)
        if target_vertical is not None:
            hit_vertical = self.page.evaluate(
                "point => document.elementFromPoint(point.x, point.y)?.closest('[data-vertical]')?.dataset.vertical || null",
                {"x": tx, "y": ty},
            )
            if hit_vertical != target_vertical:
                self.page.mouse.up()
                raise AssertionError(
                    f"drag drop point hit {hit_vertical!r}, expected activated {target_vertical!r} column"
                )
            target_cues = self.page.locator(
                f'[data-vertical="{target_vertical}"] [data-role="drop-indicator"]'
            ).count()
            combine_cues = self.page.locator('[data-dnd-combine-target]').count()
            if source_vertical != target_vertical and target_cues == 0 and combine_cues == 0:
                self.page.mouse.up()
                raise AssertionError(f"drag reached {target_vertical!r} but app exposed no live drop target")
        self.page.mouse.up()
        self.count += 1
