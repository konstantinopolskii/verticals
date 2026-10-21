"""Three words over a carried plan (docs/design/carried-pills.md; the owner's sketch, 21 Oct 2026): pointing at a plan in a
carried box shows one capsule just above the plan's lit block, "Keep · Idk · Fuck it", in the block's own colour and the
title's own type. Keep puts the plan in the column's current period; Idk adds a line to its notes and sends it to the
Inbox; Fuck it deletes it; 1, 2 and 3 do the same. Each is one step of the board's history, and after one the plan that
rises under the still pointer has the capsule.

The server reads the real date for what is carried, so the plans are made relative to it, the page's clock is set to the
same moment, and the box that holds them (Week on most days, Month in a week that starts in the month before) is found on
the board."""

from __future__ import annotations

import base64
import re
from collections.abc import Iterator
from datetime import date, datetime, timedelta
from pathlib import Path

import psycopg
import pytest
from playwright.sync_api import Browser, Locator, Page, expect

from verticals.core import goals
from tests.ui.conftest import UiSession, _backend, _make_ui_session, _static_server
from tests.ui.undo_helpers import expect_notice, family, goal, keys, wait_for
from tests.ui.views import FIELD

WORDS = ["Keep", "Idk", "Fuck it"]
GREEN = "#92ce14"


def _monday_last_week() -> date:
    today = date.today()
    return today - timedelta(days=today.weekday()) - timedelta(days=7)


def _plans(conn: psycopg.Connection, n: int, *, vertical: str = "week", parent: str | None = None,
           title: str = "SYN carried plan", body: str = "") -> list[str]:
    """`n` plans of last week, newest first (the box lists the newest first)."""
    monday = _monday_last_week()
    return [
        goals.create(conn, owner="t1", title=f"{title} {i + 1}", vertical=vertical, anchor_date=monday + timedelta(days=n - 1 - i),
                     parent_id=parent, body=body).goal.id
        for i in range(n)
    ]


def _value(conn: psycopg.Connection, title: str = "SYN green value") -> str:
    return goals.create(conn, owner="t1", title=title, vertical="life", anchor_date=date.today(), color=GREEN).goal.id


def _open(session: UiSession) -> Page:
    """The board of today, with the page's clock on the server's date (`docs/E2E.md`'s pinned clock is another day)."""
    page = session.page
    page.clock.set_fixed_time(datetime.now())
    page.goto(f"{session.base_url}/h/{date.today().isoformat()}")
    page.wait_for_selector('[data-role="carried-group"] [data-goal-id]')
    return page


def _column_of(page: Page, plan: str) -> str:
    """The column whose carried box holds the plan."""
    vertical = page.evaluate(
        "id => document.querySelector(`[data-role=carried-group] [data-goal-id=\"${id}\"]`)"
        "?.closest('.pattern-vertical-board__column')?.dataset.vertical ?? null",
        plan,
    )
    assert vertical, f"{plan} is in no carried box"
    return vertical


def _box(page: Page, vertical: str) -> Locator:
    return page.locator(f'.pattern-vertical-board__column[data-vertical="{vertical}"] [data-role="carried-group"]')


def _row(box: Locator, plan: str) -> Locator:
    return box.locator(f'[data-section="carried"] > [data-goal-id="{plan}"] > .goal-card__row')


def _point(page: Page, box: Locator, plan: str) -> None:
    """The pointer onto a plan's row, at its right end: the capsule over the plan below may cover the rest of it."""
    r = _row(box, plan).bounding_box()
    assert r
    page.mouse.move(r["x"] + r["width"] - 30, r["y"] + r["height"] / 2, steps=3)


def _pills(page: Page, vertical: str) -> Locator:
    return page.locator(f'[data-role="carried-pills"][data-column="{vertical}"]')


def _capsule(page: Page, vertical: str) -> Locator:
    return _pills(page, vertical).locator(".carried-pills__set")


def _shown(page: Page) -> Locator:
    return page.locator('[data-role="carried-pills"]:visible')


def _block(box: Locator, plan: str) -> dict:
    """The plan's lit block as drawn: its row and the wash the row's light reaches past it by (goalCard.css)."""
    return _row(box, plan).evaluate(
        """row => { const r = row.getBoundingClientRect(); const k = r.height / row.offsetHeight || 1;
           const w = getComputedStyle(row, '::before');
           return { left: r.left + parseFloat(w.left) * k, top: r.top + parseFloat(w.top) * k,
                    bottom: r.bottom - parseFloat(w.bottom) * k } }"""
    )


PIXEL = """async (data) => {
  const img = new Image(); img.src = 'data:image/png;base64,' + data; await img.decode();
  const c = document.createElement('canvas'); c.width = img.width; c.height = img.height;
  const g = c.getContext('2d'); g.drawImage(img, 0, 0);
  return [...g.getImageData(Math.floor(img.width / 2), Math.floor(img.height / 2), 1, 1).data].slice(0, 3);
}"""


def _pixel(page: Page, x: float, y: float) -> list[int]:
    """The colour on the screen at a point, read off a screenshot in the page itself."""
    shot = page.screenshot(clip={"x": x - 1, "y": y - 1, "width": 3, "height": 3})
    return page.evaluate(PIXEL, base64.b64encode(shot).decode())


def _same_colour(page: Page, capsule: Locator, block: dict) -> None:
    """The capsule's fill and the plan's lit block are one colour on screen, read at the capsule's left end."""
    s = capsule.bounding_box()
    assert s
    x = s["x"] + 2.5
    ours, theirs = _pixel(page, x, s["y"] + s["height"] / 2), _pixel(page, x, (block["top"] + block["bottom"]) / 2)
    assert max(abs(a - b) for a, b in zip(ours, theirs)) <= 2, f"capsule {ours} against the lit block {theirs}"


def _in_box(box: Locator, plan: str) -> Locator:
    return box.locator(f'[data-section="carried"] > [data-goal-id="{plan}"]')


def _body(conn: psycopg.Connection, plan: str) -> str | None:
    row = conn.execute("SELECT body FROM goals WHERE id = %s", (plan,)).fetchone()
    return row[0] if row else None


def _short(d: date) -> str:
    return f"{d.day} {d.strftime('%b')}" + ("" if d.year == date.today().year else f" {d.year}")


def test_the_capsule_stands_above_a_carried_plan_in_its_light_and_on_no_other_card(ui_f2: UiSession) -> None:
    with psycopg.connect(ui_f2.backend.dsn, autocommit=True) as conn:
        value = _value(conn)
        first, second = _plans(conn, 2, parent=value)
        (plain,) = _plans(conn, 1, title="SYN plan with no colour")
        current = goals.create(conn, owner="t1", title="SYN plan of this week", vertical="week", anchor_date=date.today()).goal.id
    page = _open(ui_f2)
    vertical = _column_of(page, first)
    box, pills, capsule = _box(page, vertical), _pills(page, vertical), _capsule(page, vertical)
    expect(_shown(page)).to_have_count(0)

    _point(page, box, second)
    expect(pills).to_be_visible()
    expect(pills).to_have_attribute("data-for", second)
    expect(capsule.locator("button")).to_have_text(WORDS)
    page.wait_for_timeout(400)  # the box's lift and colour, 200 ms each
    s, block = capsule.bounding_box(), _block(box, second)
    assert s
    assert abs(s["x"] - block["left"]) <= 1, "the capsule's left edge is the lit block's"
    assert 2 <= block["top"] - (s["y"] + s["height"]) <= 6, "just above the lit block, with a little air"
    assert abs(s["height"] - 26) <= 0.5
    title = box.locator(f'[data-goal-id="{second}"] > .goal-card__row .goal-card__title')
    type_of = "el => { const s = getComputedStyle(el); return [s.fontFamily, s.fontSize, s.fontWeight, s.lineHeight, s.color] }"
    for word in capsule.locator("button").all():
        assert word.evaluate(type_of) == title.evaluate(type_of), "the words are the title's own type and colour"
        assert word.bounding_box()["height"] >= 24
    assert capsule.evaluate("el => getComputedStyle(el).boxShadow") == "none"
    _same_colour(page, capsule, block)

    # Onto the capsule: the box stays lifted in the plan's colour, past every wait the box has for a pointer that left.
    capsule.locator('[data-pill="idk"]').hover()
    page.wait_for_timeout(700)
    expect(pills).to_have_attribute("data-for", second)
    for state in ("carried-group--lit", "carried-group--lifted"):
        assert state in (box.get_attribute("class") or ""), f"the box lost {state} under the capsule"

    # The first plan: the capsule stands over the box's line. A plan with no colour: its own hover grey.
    _point(page, box, first)
    expect(pills).to_have_attribute("data-for", first)
    page.wait_for_timeout(300)
    assert capsule.bounding_box()["y"] < box.locator('[data-role="carried-notice"]').bounding_box()["y"] + 12
    _point(page, box, plain)
    expect(pills).to_have_attribute("data-for", plain)
    page.wait_for_timeout(300)
    _same_colour(page, capsule, _block(box, plain))

    # Nowhere else: a plan of this period, a value in Life, the box's own "N more" or line.
    for row in (
        page.locator(f'[data-section="planned"] [data-goal-id="{current}"] > .goal-card__row'),
        page.locator(f'[data-goal-id="{value}"] > .goal-card__row').first,
    ):
        row.hover()
        expect(_shown(page)).to_have_count(0)


def test_keep_puts_a_plan_in_its_columns_period_with_the_columns_scale(ui_f2: UiSession) -> None:
    with psycopg.connect(ui_f2.backend.dsn, autocommit=True) as conn:
        (plan,) = _plans(conn, 1, vertical="day", title="SYN carried day plan")
        page = _open(ui_f2)
        vertical = _column_of(page, plan)
        box = _box(page, vertical)
        key = box.evaluate("el => el.closest('[data-role=period-slide]').dataset.periodKey")
        before = goal(conn, plan)
        assert before[1] == "day" and vertical != "day"

        _point(page, box, plan)
        _capsule(page, vertical).locator('[data-pill="keep"]').click()
        wait_for(page, lambda: goal(conn, plan)[1:4], (vertical, date.today().isoformat(), key), "kept in the column's period")
        expect(box.locator(f'[data-goal-id="{plan}"]')).to_have_count(0)
        expect(page.locator(
            f'.pattern-vertical-board__column[data-vertical="{vertical}"] [data-section="planned"] [data-goal-id="{plan}"]'
        )).to_have_count(1)

        undo, _redo = keys(page)
        page.keyboard.press(undo)
        wait_for(page, lambda: goal(conn, plan), before, "⌘Z puts the plan back as it was")
        expect(_in_box(box, plan)).to_have_count(1)


def test_idk_notes_the_plan_needs_realigning_sends_it_to_the_inbox_and_cmd_z_takes_both_back(ui_f2: UiSession) -> None:
    notes = "What was meant by it.\nA second line."
    with psycopg.connect(ui_f2.backend.dsn, autocommit=True) as conn:
        (plan,) = _plans(conn, 1, parent=_value(conn), body=notes)
        page = _open(ui_f2)
        vertical = _column_of(page, plan)
        box = _box(page, vertical)
        before = goal(conn, plan)

        _point(page, box, plan)
        _capsule(page, vertical).locator('[data-pill="idk"]').click()
        line = f"Needs realigning. Moved from the week of {_short(_monday_last_week())} on {_short(date.today())}."
        wait_for(page, lambda: (goal(conn, plan)[1], goal(conn, plan)[3]), (None, None), "in the Inbox: no scale, no period")
        assert _body(conn, plan) == f"{notes}\n\n{line}", "the line follows the notes"
        expect(page.locator(f'.pattern-vertical-board [data-goal-id="{plan}"]')).to_have_count(0)

        undo, redo = keys(page)
        page.keyboard.press(undo)
        wait_for(page, lambda: goal(conn, plan), before, "⌘Z puts the plan back in its period")
        wait_for(page, lambda: _body(conn, plan), notes, "and its notes as they were")
        expect(_in_box(box, plan)).to_have_count(1)
        page.keyboard.press(redo)
        wait_for(page, lambda: _body(conn, plan), f"{notes}\n\n{line}", "⇧⌘Z writes the line again")
        wait_for(page, lambda: goal(conn, plan)[1], None, "and sends it to the Inbox again")


def test_fuck_it_puts_the_plan_in_the_trash_says_so_and_cmd_z_brings_it_back(ui_f2: UiSession) -> None:
    with psycopg.connect(ui_f2.backend.dsn, autocommit=True) as conn:
        (plan,) = _plans(conn, 1, title="SYN plan to delete")
        page = _open(ui_f2)
        vertical = _column_of(page, plan)
        box = _box(page, vertical)
        before = family(conn, plan)
        trashed = lambda: conn.execute("SELECT count(*) FROM goal_trash WHERE root_id = %s", (plan,)).fetchone()[0]  # noqa: E731

        _point(page, box, plan)
        _capsule(page, vertical).locator('[data-pill="delete"]').click()
        wait_for(page, lambda: family(conn, plan), [], "the plan is deleted")
        assert trashed() == 1, "the trash keeps it"
        expect(box.locator(f'[data-goal-id="{plan}"]')).to_have_count(0)
        expect_notice(page, "Deleted “SYN plan to delete 1”")

        undo, _redo = keys(page)
        page.keyboard.press(undo)
        wait_for(page, lambda: family(conn, plan), before, "⌘Z brings it back under its id")
        expect(_in_box(box, plan)).to_have_count(1)


def test_after_a_click_the_plan_that_rises_under_the_pointer_has_the_capsule(ui_f2: UiSession) -> None:
    with psycopg.connect(ui_f2.backend.dsn, autocommit=True) as conn:
        first, second, third = _plans(conn, 3, parent=_value(conn))
        page = _open(ui_f2)
        vertical = _column_of(page, first)
        box, pills, capsule = _box(page, vertical), _pills(page, vertical), _capsule(page, vertical)

        _point(page, box, first)
        expect(pills).to_have_attribute("data-for", first)
        page.wait_for_timeout(400)
        word = capsule.locator('[data-pill="idk"]').bounding_box()
        assert word
        x, y = word["x"] + word["width"] / 2, word["y"] + word["height"] / 2
        page.mouse.move(x, y)

        page.mouse.click(x, y)  # the pointer stays where it is from here on
        wait_for(page, lambda: goal(conn, first)[1], None, "the first plan is in the Inbox")
        expect(pills).to_have_attribute("data-for", second)
        expect(pills).to_be_visible()
        page.wait_for_timeout(300)
        block = _block(box, second)
        assert 2 <= block["top"] - (capsule.bounding_box()["y"] + capsule.bounding_box()["height"]) <= 6, "above the plan that rose"

        page.mouse.click(x, y)
        wait_for(page, lambda: goal(conn, second)[1], None, "the second plan is in the Inbox")
        expect(pills).to_have_attribute("data-for", third)
        assert goal(conn, third)[1] == "week", "a click is one plan"


def test_one_two_three_while_pointing_and_never_while_typing(ui_f2: UiSession) -> None:
    with psycopg.connect(ui_f2.backend.dsn, autocommit=True) as conn:
        first, second, third = _plans(conn, 3, parent=_value(conn))
        page = _open(ui_f2)
        vertical = _column_of(page, first)
        box, pills = _box(page, vertical), _pills(page, vertical)
        key = box.evaluate("el => el.closest('[data-role=period-slide]').dataset.periodKey")

        _point(page, box, first)
        expect(pills).to_have_attribute("data-for", first)
        page.keyboard.press("1")
        wait_for(page, lambda: goal(conn, first)[3], key, "1 keeps it")
        expect(pills).to_have_attribute("data-for", second)  # the plan that rose under the pointer
        page.keyboard.press("3")
        wait_for(page, lambda: family(conn, second), [], "3 deletes it")
        expect(pills).to_have_attribute("data-for", third)
        page.keyboard.press("2")
        wait_for(page, lambda: goal(conn, third)[1], None, "2 sends it to the Inbox")
        assert "Needs realigning." in (_body(conn, third) or "")

    with psycopg.connect(ui_f2.backend.dsn, autocommit=True) as conn:
        (fourth,) = _plans(conn, 1, title="SYN plan while typing")
    page.goto(page.url)
    page.wait_for_selector(f'[data-goal-id="{fourth}"]')
    page.locator(FIELD).focus()
    _point(page, _box(page, vertical), fourth)
    expect(_pills(page, vertical)).to_have_attribute("data-for", fourth)
    page.keyboard.type("1")
    page.wait_for_timeout(400)
    with psycopg.connect(ui_f2.backend.dsn, autocommit=True) as conn:
        assert goal(conn, fourth)[1] == "week", "a key typed in the field is the field's"
    assert "1" in page.locator(FIELD).input_value()


def test_none_while_the_plans_menu_is_open_or_on_an_open_plan(ui_f2: UiSession) -> None:
    with psycopg.connect(ui_f2.backend.dsn, autocommit=True) as conn:
        plan, other = _plans(conn, 2, parent=_value(conn))
    page = _open(ui_f2)
    vertical = _column_of(page, plan)
    box, pills = _box(page, vertical), _pills(page, vertical)

    _point(page, box, plan)
    expect(pills).to_be_visible()
    box.locator(f'[data-goal-id="{plan}"] [data-role="goal-actions-trigger"]').click()
    page.wait_for_selector('[data-role="goal-context-menu"]')
    expect(_shown(page)).to_have_count(0)
    page.keyboard.press("Escape")
    expect(page.locator('[data-role="goal-context-menu"]')).to_have_count(0)
    _point(page, box, other)
    expect(pills).to_have_attribute("data-for", other)
    expect(pills).to_be_visible()

    r = _row(box, plan).bounding_box()
    page.mouse.click(r["x"] + r["width"] - 30, r["y"] + r["height"] / 2)  # the plan opens: the box is its line, the plan alone
    expect(box).to_have_class(re.compile("carried-group--open"))
    _point(page, box, plan)
    page.wait_for_timeout(300)
    expect(_shown(page)).to_have_count(0)


def test_with_no_room_above_the_capsule_stands_just_below_the_plan(ui_f2: UiSession) -> None:
    with psycopg.connect(ui_f2.backend.dsn, autocommit=True) as conn:
        first, second = _plans(conn, 2, parent=_value(conn))
        for n in range(30):  # a column long enough to scroll
            goals.create(conn, owner="t1", title=f"SYN plan of this week {n}", vertical="week", anchor_date=date.today())
    page = _open(ui_f2)
    vertical = _column_of(page, first)
    box, pills, capsule = _box(page, vertical), _pills(page, vertical), _capsule(page, vertical)
    slide = page.locator(f'.pattern-vertical-board__column[data-vertical="{vertical}"] [data-role="period-slide"]').first
    top = _block(box, second)["top"]
    slide.evaluate("(el, by) => { el.scrollTop += by }", top - 24)  # the block 24 px under the window's top, below its line
    page.wait_for_timeout(200)
    _point(page, box, second)
    expect(pills).to_have_attribute("data-for", second)
    page.wait_for_timeout(300)
    block, s = _block(box, second), capsule.bounding_box()
    assert s and block["top"] < 30
    assert 2 <= s["y"] - block["bottom"] <= 6, "just below the lit block"


@pytest.fixture
def ui_dark(browser: Browser, f2_dsn: str, tmp_path: Path, request: pytest.FixtureRequest, web_dist: None,
            ui_reduced_motion: str) -> Iterator[UiSession]:
    """F2 in the dark appearance."""
    with _backend(f2_dsn, "t1", tmp_path) as backend:
        with _static_server(backend.base_url, tmp_path) as base_url:
            yield from _make_ui_session(browser=browser, backend=backend, static_base_url=base_url, request=request,
                                        reduced_motion=ui_reduced_motion, color_scheme="dark")


def test_in_the_dark_the_capsule_takes_the_cards_dark_light_and_ink(ui_dark: UiSession) -> None:
    with psycopg.connect(ui_dark.backend.dsn, autocommit=True) as conn:
        plan, _other = _plans(conn, 2, parent=_value(conn))
        (plain,) = _plans(conn, 1, title="SYN plan with no colour")
    page = _open(ui_dark)
    vertical = _column_of(page, plan)
    box, pills, capsule = _box(page, vertical), _pills(page, vertical), _capsule(page, vertical)
    for target in (plan, plain):
        _point(page, box, target)
        expect(pills).to_have_attribute("data-for", target)
        page.wait_for_timeout(400)
        _same_colour(page, capsule, _block(box, target))
        ink = box.locator(f'[data-goal-id="{target}"] > .goal-card__row .goal-card__title').evaluate("el => getComputedStyle(el).color")
        assert ink != "rgb(0, 0, 0)"
        for word in capsule.locator("button").all():
            assert word.evaluate("el => getComputedStyle(el).color") == ink, "the dark text the card uses"
