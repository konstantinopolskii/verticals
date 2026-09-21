"""Dropping a card into another card's group before its child must show the final order at once
and land there on the server, whatever the child's position relative to its parent."""

from __future__ import annotations

import time

import httpx
import psycopg
from playwright.sync_api import Page

from tests.ui.conftest import UiSession, activate_column

ANCHOR = "2026-08-08"


def _api(session: UiSession, method: str, path: str, body: dict) -> dict:
    resp = httpx.request(
        method,
        f"{session.backend.base_url}{path}",
        json=body,
        headers={"Authorization": f"Bearer {session.backend.token}"},
        timeout=10,
    )
    assert resp.status_code in (200, 201), resp.text
    return resp.json()


def _create(session: UiSession, title: str, parent_id: str | None = None) -> str:
    body: dict = {"title": title, "vertical": "month", "anchor_date": ANCHOR}
    if parent_id:
        body["parent_id"] = parent_id
    return _api(session, "POST", "/api/goals", body)["id"]


def _row_box(page: Page, goal_id: str) -> dict:
    box = page.locator(f'[data-goal-id="{goal_id}"] > .goal-card__row').bounding_box()
    assert box is not None, f"{goal_id} has no rendered row"
    return box


def _kids(page: Page, parent_id: str) -> list[str]:
    return page.evaluate(
        "id => [...document.querySelectorAll(`[data-goal-id=\"${id}\"] + .goal-card__children > [data-goal-id]`)]"
        ".map(el => el.dataset.goalId)",
        parent_id,
    )


def _drag_before(page: Page, source: str, before: str) -> None:
    box = _row_box(page, source)
    x, y = box["x"] + 40, box["y"] + box["height"] / 2
    page.mouse.move(x, y)
    page.mouse.down()
    page.mouse.move(x, y + 8, steps=2)
    page.wait_for_timeout(300)
    for _ in range(600):
        target = _row_box(page, before)
        ty = target["y"] + target["height"] * 0.15
        if abs(ty - y) <= 2:
            break
        y += 2 if ty > y else -2
        page.mouse.move(x, y)
        page.wait_for_timeout(16)
    page.wait_for_timeout(300)
    page.mouse.up()


def _wait_patch(session: UiSession, goal_id: str, since: int) -> None:
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        if any(
            r["method"] == "PATCH" and r["url"].endswith(f"/api/goals/{goal_id}") and r["status"] == 200
            for r in session.request_log[since:]
        ):
            return
        session.page.wait_for_timeout(30)
    raise AssertionError("the reorder write never landed")


def _rows(session: UiSession, ids: list[str]) -> dict[str, tuple[str | None, int]]:
    with psycopg.connect(session.backend.dsn, autocommit=True) as conn:
        rows = conn.execute("SELECT id, parent_id, position FROM goals WHERE id = ANY(%s)", (ids,)).fetchall()
    return {goal_id: (parent_id, position) for goal_id, parent_id, position in rows}


def test_adopt_before_only_child_shows_final_order_at_once(ui_f2: UiSession) -> None:
    session = ui_f2
    page = session.page
    parent = _create(session, "Adopt parent")
    child = _create(session, "Adopt only child", parent)
    moved = _create(session, "Adopt moved")
    moved_child = _create(session, "Adopt moved child", moved)
    page.reload()
    activate_column(page, "month")
    assert _kids(page, parent) == [child]

    since = len(session.request_log)
    _drag_before(page, moved, child)
    assert _kids(page, parent) == [moved, child], "the moved card must show before the child at once"
    assert _kids(page, moved) == [moved_child]

    _wait_patch(session, moved, since)
    page.wait_for_timeout(1500)
    assert _kids(page, parent) == [moved, child]
    rows = _rows(session, [parent, child, moved])
    assert rows[moved][0] == parent
    assert rows[parent][1] < rows[moved][1] < rows[child][1], rows


def test_adopt_before_child_positioned_before_parent(ui_f2: UiSession) -> None:
    session = ui_f2
    page = session.page
    values = [
        _api(session, "POST", "/api/goals", {"title": f"Value {n}", "vertical": "life", "anchor_date": "2026-01-01"})["id"]
        for n in ("A", "B")
    ]
    other = _create(session, "Band A card", values[0])
    parent = _create(session, "Head parent", values[1])
    child = _create(session, "Head child", parent)
    _api(session, "PATCH", f"/api/goals/{child}", {"position": "first"})
    moved = _create(session, "Head moved")
    rows = _rows(session, [other, parent, child])
    assert rows[child][1] < rows[other][1] < rows[parent][1], rows
    page.reload()
    activate_column(page, "month")

    since = len(session.request_log)
    _drag_before(page, moved, child)
    _wait_patch(session, moved, since)
    rows = _rows(session, [parent, child, moved])
    assert rows[moved][0] == parent
    assert rows[moved][1] < rows[child][1], rows
    page.reload()
    activate_column(page, "month")
    assert _kids(page, parent) == [moved, child]
