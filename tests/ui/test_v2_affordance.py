"""V2 R3: neutral cards, value-colour affordances, and completed-last ordering."""

from __future__ import annotations

import httpx
from playwright.sync_api import expect

from tests.ui.conftest import UiSession, activate_column


VALUE_COLOR = "#278dea"
VALUE_COLOR_RGB = "rgb(39, 141, 234)"


def _patch(session: UiSession, goal_id: str, payload: dict) -> None:
    response = httpx.patch(
        f"{session.backend.base_url}/api/goals/{goal_id}",
        json=payload,
        headers={"Authorization": f"Bearer {session.backend.token}"},
        timeout=10,
    )
    assert response.status_code == 200, response.text


def _schedule_day(session: UiSession, goal_id: str) -> None:
    response = httpx.put(
        f"{session.backend.base_url}/api/goals/{goal_id}/schedule",
        json={"vertical": "day", "anchor_date": "2026-08-08"},
        headers={"Authorization": f"Bearer {session.backend.token}"},
        timeout=10,
    )
    assert response.status_code == 200, response.text


def test_v2_card_affordances_and_completed_last_order(ui_f2: UiSession) -> None:
    session = ui_f2
    page = session.page
    _patch(session, "SYNLIF01", {"color": VALUE_COLOR})
    # R7: parked children are ideas and no longer render in board subgoal lists. Recommit these
    # three to their parent's day vertical so this R3 test still exercises completed-last nesting.
    for child_id in ("SYNSUB01", "SYNSUB02", "SYNSUB03"):
        _schedule_day(session, child_id)
    _patch(session, "SYNSUB01", {"done": True})
    page.reload()
    # D244: the SYNSUB rows and the single-line row geometry this test measures live in the
    # EXPANDED day column (compact width wraps titles onto a second line, which would move the
    # first-text-line checkbox off the row centre this block asserts).
    activate_column(page, "day")

    parent = page.locator('[data-goal-id="SYNDAY01"]')
    ring = parent.locator(':scope > .goal-card__row [data-role="milestone-ring"]')
    expect(ring).to_be_visible(timeout=10_000)
    assert parent.locator(':scope > .goal-card__row [data-role="leaf-square"]').count() == 0

    leaf = page.locator('[data-goal-id="SYNCOL01"]')
    square = leaf.locator(':scope > .goal-card__row [data-role="leaf-square"]')
    expect(square).to_be_visible()
    assert leaf.locator(':scope > .goal-card__row [data-role="milestone-ring"]').count() == 0

    geometry = page.evaluate(
        """() => {
          const row = document.querySelector('[data-goal-id="SYNDAY01"] > .goal-card__row');
          const affordance = row.querySelector('[data-role="milestone-ring"]');
          const r = row.getBoundingClientRect();
          const a = affordance.getBoundingClientRect();
          return {rx:r.x, ry:r.y, rw:r.width, rh:r.height, ax:a.x, ay:a.y, aw:a.width, ah:a.height};
        }"""
    )
    # D132-D139: checkbox precedes title on the left and sits on the first text line.
    assert geometry["ax"] + geometry["aw"] / 2 < geometry["rx"] + geometry["rw"] / 2
    assert abs(
        geometry["ay"] + geometry["ah"] / 2 - (geometry["ry"] + geometry["rh"] / 2)
    ) <= 1

    colors = page.evaluate(
        """() => {
          const card = document.querySelector('[data-goal-id="SYNDAY01"]');
          const affordance = card.querySelector('[data-role="milestone-ring"]');
          const probe = document.createElement('div');
          probe.style.backgroundColor = 'var(--color-bg)';
          card.appendChild(probe);
              const result = {
                card: getComputedStyle(card).backgroundColor,
                neutral: getComputedStyle(probe).backgroundColor,
                affordance: getComputedStyle(affordance.querySelector('[data-role=checkbox-box]')).backgroundColor,
                siblingAffordance: getComputedStyle(document.querySelector(
                  '[data-goal-id="SYNSUB02"] [data-role=checkbox-box]'
                )).backgroundColor,
                neutralAffordance: getComputedStyle(document.querySelector(
                  '[data-goal-id="SYNCOL07"] [data-role=checkbox-box]'
                )).backgroundColor,
          };
          probe.remove();
          return result;
        }"""
    )
    assert colors["card"] == colors["neutral"]
    assert colors["card"] != VALUE_COLOR_RGB
    # D231 (KK, 2026-08-15) supersedes the own-colour half of D147-D157: the wash is bound to the
    # DERIVED value colour now. SYNDAY01 sits under SYNLIF01 (patched to the value colour above),
    # so its affordance leaves the neutral wash and matches every family member's — while
    # SYNCOL07 (no life root) stays neutral.
    assert colors["affordance"] != colors["neutralAffordance"]
    assert colors["affordance"] == colors["siblingAffordance"]

    assert square.locator("path").count() == 0
    assert square.locator("svg").count() == 0
    pseudo = square.locator('[data-role="checkbox-box"]').evaluate(
        "el => getComputedStyle(el, '::after').content"
    )
    assert pseudo in {'""', "none", "normal"}, f"unchecked square paints non-empty pseudo content: {pseudo}"

    day_order = page.locator(
        '[data-vertical="day"] [data-role="period-slide"][data-state="current"] '
        '.pattern-vertical-board__body > .card-stack > .goal-card'
    ).evaluate_all("cards => cards.map(card => card.classList.contains('goal-card--done'))")
    assert day_order and any(day_order) and not all(day_order)
    assert day_order == sorted(day_order), "completed day cards must follow every open day card"

    # D142: always expanded; completed nesting order is immediately observable.
    assert page.locator('[data-role="subgoal-toggle"]').count() == 0
    child_order = page.locator(
        '[data-goal-id="SYNDAY01"] + .goal-card__children > .goal-card'
    ).evaluate_all("cards => cards.map(card => card.classList.contains('goal-card--done'))")
    assert child_order == [False, False, True]
