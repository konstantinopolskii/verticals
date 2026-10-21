"""Three pills beside a carried plan (docs/design/carried-pills.md): pointing at a plan in a carried box shows "This week"
(the column's own period), "To Inbox" and "Delete" to the right of the box, level with the plan's first line, on the box's
own lit colour; each does what the card's menu does, as one step of the board's history; after a click the plan that
rises under the pointer has them, so a list is sorted click, click, click.

The server reads the real date for what is carried, so the plans are made relative to it, and the page's clock is set to
the same moment: the box that holds them (Week on most days, Month in a week that starts in the month before) is found on
the board, and its column decides the first pill."""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta

import psycopg
from playwright.sync_api import Locator, Page, expect

from verticals.core import goals
from tests.ui.conftest import UiSession
from tests.ui.undo_helpers import expect_notice, family, goal, keys, wait_for

KEEP = {
    "day": "Today", "week": "This week", "month": "This month", "quarter": "This quarter", "year": "This year",
    "decade": "These three years",
}
GREEN = "#92ce14"


def _plans(conn: psycopg.Connection, n: int, *, vertical: str = "week", parent: str | None = None,
           title: str = "SYN carried plan") -> list[str]:
    """`n` plans of last week, newest first (the box lists the newest first)."""
    today = date.today()
    monday = today - timedelta(days=today.weekday()) - timedelta(days=7)
    return [
        goals.create(conn, owner="t1", title=f"{title} {i + 1}", vertical=vertical, anchor_date=monday + timedelta(days=n - 1 - i),
                     parent_id=parent).goal.id
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


def _pills(page: Page, vertical: str) -> Locator:
    return page.locator(f'[data-role="carried-pills"][data-column="{vertical}"]')


def _set(page: Page, vertical: str) -> Locator:
    """The backing that holds the three pills."""
    return _pills(page, vertical).locator(".carried-pills__set")


def _shown(page: Page) -> Locator:
    return page.locator('[data-role="carried-pills"]:visible')


def _line(page: Page, box: Locator, plan: str) -> float:
    """The middle of the plan's first line as drawn (a lifted box is scaled)."""
    return box.locator(f'[data-goal-id="{plan}"] > .goal-card__row .goal-card__title').evaluate(
        "el => { const r = el.getBoundingClientRect(); const k = r.height / el.offsetHeight || 1;"
        " return r.top + parseFloat(getComputedStyle(el).lineHeight) * k / 2 }"
    )


def _middle(locator: Locator) -> float:
    b = locator.bounding_box()
    assert b is not None
    return b["y"] + b["height"] / 2


def _in_box(box: Locator, plan: str) -> int:
    return box.locator(f'[data-section="carried"] > [data-goal-id="{plan}"]').count()


def test_the_pills_come_beside_a_carried_plan_and_on_no_other_card(ui_f2: UiSession) -> None:
    with psycopg.connect(ui_f2.backend.dsn, autocommit=True) as conn:
        value = _value(conn)
        plan, _other = _plans(conn, 2, parent=value)
        (plain,) = _plans(conn, 1, title="SYN plan with no colour")
        current = goals.create(conn, owner="t1", title="SYN plan of this week", vertical="week", anchor_date=date.today()).goal.id
    page = _open(ui_f2)
    vertical = _column_of(page, plan)
    box, pills, backing = _box(page, vertical), _pills(page, vertical), _set(page, vertical)
    expect(_shown(page)).to_have_count(0)

    _row(box, plan).hover()
    expect(pills).to_be_visible()
    expect(pills).to_have_attribute("data-for", plan)
    expect(backing.locator("button")).to_have_text([KEEP[vertical], "To Inbox", "Delete"])
    page.wait_for_timeout(400)  # the box's lift and colour, 200 ms each
    b, s = box.bounding_box(), backing.bounding_box()
    assert b and s
    assert 0 <= s["x"] - (b["x"] + b["width"]) <= 16, "the pills stand right of the box, over the next column"
    type_of = lambda el: el.evaluate(  # noqa: E731
        "el => { const s = getComputedStyle(el); return [s.fontFamily, s.fontSize, s.fontWeight, s.lineHeight] }")
    title = type_of(box.locator(f'[data-goal-id="{plan}"] > .goal-card__row .goal-card__title'))
    for pill in backing.locator("button").all():
        assert type_of(pill) == title, "the pills speak in the type of the plan's own title"
        assert abs(pill.bounding_box()["height"] - 28) <= 0.5
    assert s["width"] <= b["width"] + 24, f"the pills are {s['width']}px wide: about one column, as the plan's own level"
    assert abs(_middle(backing) - _line(page, box, plan)) <= 1.5, "level with the plan's first line"
    colour = lambda el: el.evaluate("el => getComputedStyle(el).backgroundColor")  # noqa: E731
    assert colour(backing) == colour(box), "the backing is the box's own lit colour"
    assert colour(backing.locator("button").first) == "rgb(255, 255, 255)"
    delete = backing.locator('[data-pill="delete"]')
    assert delete.evaluate("el => getComputedStyle(el).color") == "rgb(201, 58, 91)", "Delete in the menu's red"

    # Onto the pills: the box stays lifted in the plan's colour, past every wait the box has for a pointer that left.
    backing.locator('[data-pill="inbox"]').hover()
    page.wait_for_timeout(700)
    expect(pills).to_be_visible()
    expect(pills).to_have_attribute("data-for", plan)
    for state in ("carried-group--lit", "carried-group--lifted"):
        assert state in (box.get_attribute("class") or ""), f"the box lost {state} under the pills"

    # Nowhere else: a plan of this period, a value in Life, the box's own line.
    for row in (
        page.locator(f'[data-section="planned"] [data-goal-id="{current}"] > .goal-card__row'),
        page.locator(f'[data-goal-id="{value}"] > .goal-card__row').first,
        box.locator('[data-role="carried-notice"]'),
    ):
        row.hover()
        expect(_shown(page)).to_have_count(0)
    _row(box, plan).hover()
    expect(pills).to_be_visible()

    # A plan with no colour: a white backing, never the box's grey ground, which vanished over a grey box.
    _row(box, plain).hover()
    expect(pills).to_have_attribute("data-for", plain)
    page.wait_for_timeout(300)
    assert colour(backing) == "rgb(255, 255, 255)"


def test_keep_puts_a_plan_in_its_columns_period_with_the_columns_scale(ui_f2: UiSession) -> None:
    with psycopg.connect(ui_f2.backend.dsn, autocommit=True) as conn:
        (plan,) = _plans(conn, 1, vertical="day", title="SYN carried day plan")
        page = _open(ui_f2)
        vertical = _column_of(page, plan)
        box = _box(page, vertical)
        key = box.evaluate("el => el.closest('[data-role=period-slide]').dataset.periodKey")
        before = goal(conn, plan)
        assert before[1] == "day" and vertical != "day"

        _row(box, plan).hover()
        _set(page, vertical).locator('[data-pill="keep"]').click()
        wait_for(page, lambda: goal(conn, plan)[1:4], (vertical, date.today().isoformat(), key), "kept in the column's period")
        expect(box.locator(f'[data-goal-id="{plan}"]')).to_have_count(0)
        expect(page.locator(
            f'.pattern-vertical-board__column[data-vertical="{vertical}"] [data-section="planned"] [data-goal-id="{plan}"]'
        )).to_have_count(1)

        undo, _redo = keys(page)
        page.keyboard.press(undo)
        wait_for(page, lambda: goal(conn, plan), before, "⌘Z puts the plan back as it was")
        expect(box.locator(f'[data-section="carried"] > [data-goal-id="{plan}"]')).to_have_count(1)


def test_to_inbox_takes_the_plan_out_of_the_board_and_cmd_z_brings_it_back(ui_f2: UiSession) -> None:
    with psycopg.connect(ui_f2.backend.dsn, autocommit=True) as conn:
        (plan,) = _plans(conn, 1, parent=_value(conn))
        page = _open(ui_f2)
        vertical = _column_of(page, plan)
        box = _box(page, vertical)
        before = goal(conn, plan)

        _row(box, plan).hover()
        _set(page, vertical).locator('[data-pill="inbox"]').click()
        wait_for(page, lambda: (goal(conn, plan)[1], goal(conn, plan)[3]), (None, None), "in the Inbox: no scale, no period")
        expect(page.locator(f'.pattern-vertical-board [data-goal-id="{plan}"]')).to_have_count(0)

        undo, _redo = keys(page)
        page.keyboard.press(undo)
        wait_for(page, lambda: goal(conn, plan), before, "⌘Z puts the plan back as it was")
        expect(box.locator(f'[data-section="carried"] > [data-goal-id="{plan}"]')).to_have_count(1)


def test_delete_puts_the_plan_in_the_trash_says_so_and_cmd_z_brings_it_back(ui_f2: UiSession) -> None:
    with psycopg.connect(ui_f2.backend.dsn, autocommit=True) as conn:
        (plan,) = _plans(conn, 1, title="SYN plan to delete")
        page = _open(ui_f2)
        vertical = _column_of(page, plan)
        box = _box(page, vertical)
        before = family(conn, plan)
        trashed = lambda: conn.execute("SELECT count(*) FROM goal_trash WHERE root_id = %s", (plan,)).fetchone()[0]  # noqa: E731

        _row(box, plan).hover()
        _set(page, vertical).locator('[data-pill="delete"]').click()
        wait_for(page, lambda: family(conn, plan), [], "the plan is deleted")
        assert trashed() == 1, "the trash keeps it"
        expect(box.locator(f'[data-goal-id="{plan}"]')).to_have_count(0)
        expect_notice(page, "Deleted “SYN plan to delete 1”")

        undo, _redo = keys(page)
        page.keyboard.press(undo)
        wait_for(page, lambda: family(conn, plan), before, "⌘Z brings it back under its id")
        expect(box.locator(f'[data-section="carried"] > [data-goal-id="{plan}"]')).to_have_count(1)


def test_after_a_click_the_plan_that_rises_under_the_pointer_has_the_pills(ui_f2: UiSession) -> None:
    with psycopg.connect(ui_f2.backend.dsn, autocommit=True) as conn:
        first, second, third = _plans(conn, 3, parent=_value(conn))
        page = _open(ui_f2)
        vertical = _column_of(page, first)
        box, pills, backing = _box(page, vertical), _pills(page, vertical), _set(page, vertical)

        _row(box, first).hover()
        expect(pills).to_have_attribute("data-for", first)
        page.wait_for_timeout(400)
        pill = backing.locator('[data-pill="inbox"]').bounding_box()
        assert pill
        x, y = pill["x"] + pill["width"] / 2, pill["y"] + pill["height"] / 2
        page.mouse.move(x, y)

        page.mouse.click(x, y)  # the pointer stays where it is from here on
        wait_for(page, lambda: goal(conn, first)[1], None, "the first plan is in the Inbox")
        expect(pills).to_have_attribute("data-for", second)
        expect(pills).to_be_visible()
        page.wait_for_timeout(300)
        assert abs(_middle(backing) - _line(page, box, second)) <= 1.5, "the pills stand on the plan that rose"

        page.mouse.click(x, y)
        wait_for(page, lambda: goal(conn, second)[1], None, "the second plan is in the Inbox")
        expect(pills).to_have_attribute("data-for", third)
        assert goal(conn, third)[1] == "week", "a click is one plan"


def test_none_while_the_plans_menu_is_open_or_on_an_open_plan(ui_f2: UiSession) -> None:
    with psycopg.connect(ui_f2.backend.dsn, autocommit=True) as conn:
        plan, other = _plans(conn, 2, parent=_value(conn))
    page = _open(ui_f2)
    vertical = _column_of(page, plan)
    box, pills = _box(page, vertical), _pills(page, vertical)

    _row(box, plan).hover()
    expect(pills).to_be_visible()
    box.locator(f'[data-goal-id="{plan}"] [data-role="goal-actions-trigger"]').click()
    page.wait_for_selector('[data-role="goal-context-menu"]')
    expect(_shown(page)).to_have_count(0)
    page.keyboard.press("Escape")
    expect(page.locator('[data-role="goal-context-menu"]')).to_have_count(0)
    _row(box, other).hover()
    expect(pills).to_have_attribute("data-for", other)
    expect(pills).to_be_visible()

    _row(box, plan).click()  # the plan opens: the box is its line, and the plan stands under it alone
    expect(box).to_have_class(re.compile("carried-group--open"))
    _row(box, plan).hover()
    page.wait_for_timeout(300)
    expect(_shown(page)).to_have_count(0)


def test_with_no_room_on_the_right_the_pills_stand_left_of_the_box_the_mild_one_nearest(ui_f2: UiSession) -> None:
    """Three years is the last column with a box; three pills are wider than the window leaves right of it, and over the
    card they would hide the plan they sort. F2's three-year plan of the 2020s is carried there."""
    page = _open(ui_f2)
    plan, vertical = "SYNDEC01", "decade"
    box, pills, backing = _box(page, vertical), _pills(page, vertical), _set(page, vertical)
    row = _row(box, plan).bounding_box()
    assert row
    page.mouse.move(row["x"] + 40, row["y"] + 150)
    page.mouse.move(row["x"] + 40, row["y"] + row["height"] / 2, steps=5)
    expect(pills).to_have_attribute("data-for", plan)
    page.wait_for_timeout(400)
    b, s = box.bounding_box(), backing.bounding_box()
    assert b and s
    assert 0 <= b["x"] - (s["x"] + s["width"]) <= 16, "left of the box, over the column before"
    assert abs(_middle(backing) - _line(page, box, plan)) <= 1.5
    x = {name: backing.locator(f'[data-pill="{name}"]').bounding_box()["x"] for name in ("keep", "inbox", "delete")}
    assert x["delete"] < x["inbox"] < x["keep"], "Keep nearest the card, Delete farthest"
    expect(backing.locator('[data-pill="keep"]')).to_have_text(KEEP[vertical])
    backing.locator('[data-pill="keep"]').hover()
    page.wait_for_timeout(700)
    expect(pills).to_have_attribute("data-for", plan)
    assert "carried-group--lifted" in (box.get_attribute("class") or "")
