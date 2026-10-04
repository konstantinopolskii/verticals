"""The carried box changes what it shows as one movement (`web/src/lib/carriedMotion.ts`; KK, 4 Oct 2026, from a mockup:
its plans used to "appear out of nowhere"): what leaves fades out where it stood, what stays slides to its new place,
what arrives fades in. With reduced motion nothing slides, and what leaves and arrives cross-fades. Traced frame by frame
in the page, so a one-frame swap shows."""

from __future__ import annotations

import re
from datetime import date

import psycopg
import pytest
from playwright.sync_api import Page, expect

from verticals.core import goals
from tests.ui.conftest import UiSession

GROUP = '.pattern-vertical-board__column[data-vertical="year"] [data-role="carried-group"]'
SAMPLER = r"""(plan) => {
  const box = document.querySelector('.pattern-vertical-board__column[data-vertical="year"] [data-role="carried-group"]');
  const s = window.__box = { frames: [], on: false };
  const op = (el) => parseFloat(getComputedStyle(el).opacity);
  function frame() {
    if (!s.on) return;
    const b = box.getBoundingClientRect();
    const cards = [...box.querySelectorAll('[data-section="carried"] > .goal-card')];
    const mine = cards.find((c) => c.dataset.goalId === plan);
    const more = box.querySelector('[data-role="carried-more"]');
    s.frames.push({
      cards: cards.length, ops: cards.map(op),
      planTop: mine ? mine.getBoundingClientRect().top - b.top : null, planTf: mine ? getComputedStyle(mine).transform : null,
      ghosts: [...box.querySelectorAll('.carried-ghost')].map((g) => ({ o: op(g), ids: g.querySelectorAll('[data-goal-id]').length })),
      more: more ? { text: more.textContent.trim(), o: op(more) } : null,
    });
    requestAnimationFrame(frame);
  }
  s.start = () => { s.frames = []; s.on = true; requestAnimationFrame(frame); };
  s.stop = () => { s.on = false; return s.frames; };
}"""


@pytest.fixture
def ui_reduced_motion(request: pytest.FixtureRequest) -> str:
    return getattr(request, "param", "no-preference")


def _plan(conn: psycopg.Connection, title: str, month: int, day: int, parent: str | None = None) -> str:
    """A plan of last year, carried into this year's box; the box lists the newest first."""
    return goals.create(
        conn, owner="t1", title=title, vertical="year", anchor_date=date(date.today().year - 1, month, day), parent_id=parent,
    ).goal.id


def _board(session: UiSession) -> tuple[str, str]:
    """The box shows X, P, Y first (the newest plans of last year) and "N more"; P is the one plan of a value in Life, so
    pointing at the value leaves P alone in the box."""
    with psycopg.connect(session.backend.dsn, autocommit=True) as conn:
        value = goals.create(conn, owner="t1", title="SYN value with one carried plan", vertical="life", anchor_date=date.today(), color="#278dea").goal.id
        _plan(conn, "SYN newest carried plan", 12, 20)
        plan = _plan(conn, "SYN the value's carried plan", 12, 10, parent=value)
        _plan(conn, "SYN third carried plan", 12, 5)
        _plan(conn, "SYN older carried plan", 11, 1)
    page = session.page
    page.goto(f"{session.base_url}/h/{date.today().isoformat()}")
    page.wait_for_selector(GROUP)
    expect(page.locator(f"{GROUP} [data-section='carried'] > .goal-card")).to_have_count(3)
    return value, plan


def _trace(page: Page, act, wait_ms: int) -> list[dict]:
    page.evaluate("window.__box.start()")
    act()
    page.wait_for_timeout(wait_ms)
    return page.evaluate("window.__box.stop()")


def _change(frames: list[dict], cards: int) -> int:
    """The first frame that shows the new list."""
    return next(i for i, f in enumerate(frames) if f["cards"] == cards)


def _blank_week(page: Page) -> tuple[float, float]:
    box = page.locator('.pattern-vertical-board__column[data-vertical="week"]').bounding_box()
    return box["x"] + box["width"] / 2, min(box["y"] + box["height"] - 30, page.viewport_size["height"] - 120)


def test_what_stays_slides_what_leaves_fades_where_it_stood_and_what_arrives_fades_in(ui_f2: UiSession) -> None:
    value, plan = _board(ui_f2)
    page = ui_f2.page
    page.evaluate(SAMPLER, plan)
    total = int(page.locator(GROUP).get_attribute("data-count") or 0)
    second = page.locator(f'{GROUP} [data-goal-id="{plan}"]').evaluate(
        "(el) => el.getBoundingClientRect().top - el.closest('[data-role=\"carried-group\"]').getBoundingClientRect().top")

    frames = _trace(page, lambda: page.locator(f'[data-goal-id="{value}"] > .goal-card__row').hover(), 700)
    i = _change(frames, 1)
    moved = frames[i:]
    assert moved[0]["planTf"] != "none" and abs(moved[0]["planTop"] - second) < 4, "the plan that stays starts where it was"
    tops = [f["planTop"] for f in moved]
    assert all(b <= a + 0.5 for a, b in zip(tops, tops[1:])), f"it slides up without turning back: {tops[:12]}"
    assert tops[-1] < second - 20 and moved[-1]["planTf"] == "none", "it lands in the first place"
    assert len(moved[0]["ghosts"]) >= 2, "the two plans that leave stay where they stood, as copies"
    assert all(g["ids"] == 0 for f in moved for g in f["ghosts"]), "a copy is never taken for the plan"
    fading = [max((g["o"] for g in f["ghosts"]), default=0) for f in moved]
    assert all(b <= a + 0.01 for a, b in zip(fading, fading[1:])) and moved[-1]["ghosts"] == [], "they fade out and go"
    assert moved[0]["more"]["text"] == f"{total - 1} more" and moved[0]["more"]["o"] < 0.5, "the new last line fades in"
    assert moved[-1]["more"]["o"] == 1

    x, y = _blank_week(page)
    frames = _trace(page, lambda: page.mouse.move(x, y), 900)
    i = _change(frames, 3)
    back = frames[i:]
    assert back[0]["planTf"] != "none" and back[0]["planTop"] < second - 20, "back: the plan starts from the first place"
    tops = [f["planTop"] for f in back]
    assert all(b >= a - 0.5 for a, b in zip(tops, tops[1:])) and abs(tops[-1] - second) < 1, "and slides down to its own"
    assert min(back[0]["ops"]) < 0.5 and back[-1]["ops"] == [1, 1, 1], "the plans that come back fade in"
    expect(page.locator(GROUP)).not_to_have_attribute("style", re.compile("position"))


@pytest.mark.parametrize("ui_reduced_motion", ["reduce"], indirect=True)
def test_with_reduced_motion_nothing_slides_and_the_change_cross_fades(ui_f2: UiSession) -> None:
    value, plan = _board(ui_f2)
    page = ui_f2.page
    page.evaluate(SAMPLER, plan)
    frames = _trace(page, lambda: page.locator(f'[data-goal-id="{value}"] > .goal-card__row').hover(), 500)
    moved = frames[_change(frames, 1):]
    assert all(f["planTf"] == "none" for f in moved), "nothing slides"
    assert len(moved[0]["ghosts"]) >= 2 and moved[-1]["ghosts"] == [], "what leaves cross-fades out"
    assert moved[0]["more"]["o"] < 1 and moved[-1]["more"]["o"] == 1, "what arrives cross-fades in"
