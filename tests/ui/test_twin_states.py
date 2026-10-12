"""Twin states (`tests/harness/twin.py`): each test brings the app into one state the way a person does and captures
it, so another build of the app can be compared with this one state by state:

    VERTICALS_WEB_DIR=web       pytest tests/ui/test_twin_states.py
    VERTICALS_WEB_DIR=web-react pytest tests/ui/test_twin_states.py
    python -m tests.harness.twin web web-react

The app is F2 served by the desktop gateway, as the desktop app serves it (`ui_agent`): it serves any package's
`dist/` with no `vite preview` in between. The steps are the ones the scenarios that own each surface take; the
captures assert nothing beyond those steps."""

from __future__ import annotations

import psycopg
from playwright.sync_api import Page, expect

from verticals.core import docs as core_docs
from tests.harness.twin import capture
from tests.ui.conftest import UiSession, activate_column
from tests.ui.test_agent_conversation import ui_agent  # noqa: F401  (the fixture)
from tests.ui.views import FIELD, show_tags, switch_view

GOAL = "SYNORD01"  # on the week column
UNSCHEDULED = "SYNMAY01"  # in the Inbox
ROW = f'[data-goal-id="{GOAL}"] > .goal-card__row'
MENU = '[data-role="goal-context-menu"]'
STEP = f'{MENU} [data-role="move-step"]'
SCHEDULE = '.goal-card--detail-open .goal-facts [data-cap="schedule"]'
POPOVER = '#dropdownPortal [data-popover-surface][data-state="open"]:has(.schedule-popover__row)'


def _board(session: UiSession) -> Page:
    session.page.wait_for_selector(f'[data-goal-id="{GOAL}"]')
    return session.page


SETTLED = """async () => {
  const frame = () => new Promise((done) => requestAnimationFrame(done))
  const passing = /-(enter|leave)-(from|active|to)$/
  const moving = () => document.getAnimations().some((a) => a.playState === 'running'
    && a.effect?.getComputedTiming().endTime !== Infinity)
    || [...document.querySelectorAll('[class]')].some((el) => [...el.classList].some((name) => passing.test(name)))
  const until = performance.now() + 2000
  await frame()
  await frame()
  while (moving() && performance.now() < until) await frame()
  await frame()
  await frame()
}"""


def _settled(page: Page) -> Page:
    """Whatever the last step started has finished moving (animations, and Vue's transition classes, which a
    transition with nothing to animate wears until its timer ends) and been drawn, so a capture never lands mid-way."""
    page.evaluate(SETTLED)
    return page


def _doc(session: UiSession, path: str, title: str, body: str) -> str:
    with psycopg.connect(session.backend.dsn, autocommit=True) as conn:
        return core_docs.create(conn, owner="t1", path=path, title=title, body=body).doc.id


def test_twin_board(ui_agent: UiSession) -> None:
    capture(_settled(_board(ui_agent)), "board")


def test_twin_week_open(ui_agent: UiSession) -> None:
    page = _board(ui_agent)
    activate_column(page, "week")
    capture(_settled(page), "week-open")


def test_twin_tags(ui_agent: UiSession) -> None:
    page = _board(ui_agent)
    show_tags(page)
    capture(_settled(page), "tags")


def test_twin_goal_open(ui_agent: UiSession) -> None:
    page = _board(ui_agent)
    activate_column(page, "week")
    page.locator(f"{ROW} .goal-card__title").click()
    expect(page.locator(f'[data-goal-id="{GOAL}"].goal-card--detail-open')).to_be_visible()
    capture(_settled(page), "goal-open")


def test_twin_goal_menu_and_move_step(ui_agent: UiSession) -> None:
    page = _board(ui_agent)
    activate_column(page, "week")
    page.locator(ROW).first.click(button="right")
    page.wait_for_selector(MENU)
    capture(_settled(page), "goal-menu")
    page.click(f'{MENU} [data-move="date"]')
    expect(page.locator(f"{STEP} .move-step__title")).to_have_text("Move to a date")
    capture(_settled(page), "move-step")


def test_twin_field_search(ui_agent: UiSession) -> None:
    page = _board(ui_agent)
    page.keyboard.press("Control+k")
    expect(page.locator(FIELD)).to_be_focused()
    page.locator(FIELD).fill("cy")
    page.wait_for_timeout(600)  # two letters filter the board on screen, with no request
    capture(_settled(page), "field-search")


def test_twin_inbox_goal_window_and_schedule(ui_agent: UiSession) -> None:
    page = _board(ui_agent)
    switch_view(page, "inbox")
    capture(_settled(page), "inbox")
    page.click(f'[data-cap="inbox"] [data-goal-id="{UNSCHEDULED}"]')
    page.wait_for_selector(SCHEDULE)
    capture(_settled(page), "goal-window")
    page.click(SCHEDULE)
    page.locator(POPOVER).wait_for(state="visible")
    capture(_settled(page), "schedule-popover")


def test_twin_docs_and_doc(ui_agent: UiSession) -> None:
    session = ui_agent
    doc_id = _doc(session, "syn-twin/plan.md", "SYN Twin plan",
                  "# SYN Twin plan\n\nA paragraph with **bold** words and a [link](https://example.org).\n\n"
                  "- one\n- two\n\n## A part\n\nMore text.")
    _doc(session, "syn-twin/notes.md", "SYN Twin notes", "Short notes.")
    page = _board(session)
    switch_view(page, "docs")
    capture(_settled(page), "docs")
    page.goto("about:blank")
    page.goto(f"{session.base_url}/#doc/{doc_id}")
    expect(page.locator('[data-cap="docs"] [data-role="doc-detail"]')).to_be_visible(timeout=10000)
    capture(_settled(page), "doc")


def test_twin_drag_held(ui_agent: UiSession) -> None:
    page = _board(ui_agent)
    activate_column(page, "week")
    box = page.locator(ROW).bounding_box()
    assert box is not None
    x, y = box["x"] + 50, box["y"] + 6  # the row's inert middle strip (test_hand_drag.py's GRIP)
    page.mouse.move(x, y)
    page.mouse.down()
    try:
        page.mouse.move(x + 20, y, steps=4)
        page.mouse.move(x + 20, y + 60, steps=5)
        capture(_settled(page), "drag-held")
    finally:
        page.keyboard.press("Escape")
        page.mouse.up()
    expect(page.locator(ROW)).to_be_visible(timeout=2000)
