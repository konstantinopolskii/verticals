"""Carried-over plans (docs/design-handoff scope 4): the group on top of a column opens in place, lights for the family
under the pointer, keeps that filter until another goal takes it, the pointer leaves its way, or "N more" is clicked
(S4.P3, KK 2026-10-02), keeps its place under a goal of its own column with a mascot in the empty space, and "Replan"
opens the sorting task as a goal's window with our first message sent."""

from __future__ import annotations

import re
from datetime import date

import psycopg
from playwright.sync_api import Page, expect

from verticals.core import goals, replan
from tests.ui.conftest import UiSession
from tests.ui.test_agent_conversation import ui_agent  # noqa: F401  (the fixture)
from tests.ui.views import FIELD

GROUP = '.pattern-vertical-board__column[data-vertical="year"] [data-role="carried-group"]'
PLACE = '.pattern-vertical-board__column[data-vertical="year"] [data-role="carried-place"]'
GAP = f'{PLACE} [data-role="carried-gap"]'
SHY = ("Ignore me", "You didn't see this", "Nevermind")
FIRST = "Read this task and help me sort these plans out: where each goes, based on when I planned it and what it belongs to."


def _last_year(conn: psycopg.Connection, title: str, parent: str | None = None) -> str:
    today = date.today()
    return goals.create(
        conn, owner="t1", title=title, vertical="year", anchor_date=date(today.year - 1, 6, 15), parent_id=parent,
    ).goal.id


def _goto_today(page: Page, base_url: str) -> None:
    page.goto(f"{base_url}/h/{date.today().isoformat()}")
    page.wait_for_selector(GROUP)


def _row(goal_id: str) -> str:
    return f'[data-goal-id="{goal_id}"] > .goal-card__row'


def _blank(page: Page, vertical: str) -> tuple[float, float]:
    """A point low in a column, where no goal stands."""
    box = page.locator(f'.pattern-vertical-board__column[data-vertical="{vertical}"]').bounding_box()
    return box["x"] + box["width"] / 2, min(box["y"] + box["height"] - 30, page.viewport_size["height"] - 120)


def _lit(group) -> bool:
    return "carried-group--lit" in (group.get_attribute("class") or "")


def _carried_cards(group):
    return group.locator('[data-section="carried"] > .goal-card')


def _value_with_plan(conn: psycopg.Connection, title: str, color: str) -> tuple[str, str]:
    """A value in Life and one carried plan of the year under it: the plan's family is the value's."""
    value = goals.create(conn, owner="t1", title=title, vertical="life", anchor_date=date.today(), color=color).goal.id
    return value, _last_year(conn, f"{title}: carried plan", parent=value)


def _others(conn: psycopg.Connection, n: int = 4) -> None:
    for i in range(n):
        _last_year(conn, f"SYN other carried plan {i}")


def test_more_opens_the_rest_in_place_newest_first(ui_f2: UiSession) -> None:
    """S4.P2.010, .037: three in view, "N more" on the titles' line; opened, the rest in place and "Show fewer"."""
    with psycopg.connect(ui_f2.backend.dsn, autocommit=True) as conn:
        for n in range(4):
            _last_year(conn, f"SYN carried {n}")
    page = ui_f2.page
    _goto_today(page, ui_f2.base_url)
    group = page.locator(GROUP)
    total = int(group.get_attribute("data-count") or 0)
    rows = group.locator('[data-section="carried"] > .goal-card')
    expect(rows).to_have_count(3)
    more = group.locator('[data-role="carried-more"]')
    expect(more).to_have_text(f"{total - 3} more")
    more.click()
    expect(rows).to_have_count(total)
    expect(more).to_have_text("Show fewer")
    more.click()
    expect(rows).to_have_count(3)


def test_pointing_at_a_goal_lights_its_family_in_the_box(ui_f2: UiSession) -> None:
    """S4.P3.021-.023: the box takes the goal's colour and shows its family's plans, gets as short as they are, and goes
    back to rest when the pointer leaves."""
    with psycopg.connect(ui_f2.backend.dsn, autocommit=True) as conn:
        value = goals.create(conn, owner="t1", title="SYN value with carried plans", vertical="life", anchor_date=date.today(), color="#92ce14").goal.id
        mine = _last_year(conn, "SYN the value's carried plan", parent=value)
        _last_year(conn, "SYN someone else's carried plan")
        _last_year(conn, "SYN another carried plan")
    page = ui_f2.page
    _goto_today(page, ui_f2.base_url)
    group = page.locator(GROUP)
    height = group.bounding_box()["height"]
    page.locator(f'[data-goal-id="{value}"] > .goal-card__row').hover()
    expect(group).to_have_class(re.compile("carried-group--lit"))
    expect(group.locator('[data-section="carried"] > .goal-card')).to_have_count(1)
    expect(group.locator(f'[data-goal-id="{mine}"]')).to_have_count(1)
    page.wait_for_timeout(400)  # 200 ms of height, and the frames to draw it
    assert group.bounding_box()["height"] < height - 20
    page.mouse.move(5, 5)
    expect(group).not_to_have_class(re.compile("carried-group--lit"))
    page.wait_for_timeout(400)
    assert abs(group.bounding_box()["height"] - height) <= 2


def test_the_notice_counts_the_plans(ui_f2: UiSession) -> None:
    """S4.P2.014-.018, S4.P3.030: "8 from Sep": how many, and from when; it doesn't change with the filter."""
    with psycopg.connect(ui_f2.backend.dsn, autocommit=True) as conn:
        value, _plan = _value_with_plan(conn, "SYN counted value", "#92ce14")
        _others(conn)
    page = ui_f2.page
    _goto_today(page, ui_f2.base_url)
    group = page.locator(GROUP)
    total = int(group.get_attribute("data-count") or 0)
    notice = group.locator('[data-role="carried-notice"]')
    expect(notice).to_have_text(f"{total} from earlier years")
    page.locator(_row(value)).hover()
    expect(group).to_have_class(re.compile("carried-group--lit"))
    expect(notice).to_have_text(f"{total} from earlier years")


def test_a_goal_in_the_boxs_own_column_keeps_its_place_and_the_mascot_moves_in(ui_f2: UiSession) -> None:
    """S4.P3.004, .022, .031: the goal stands under the box, so the box changes inside the place it had: shorter, with the empty
    rest left clear, and the shy mascot in it; a click on it says something else and moves nothing."""
    with psycopg.connect(ui_f2.backend.dsn, autocommit=True) as conn:
        value = goals.create(conn, owner="t1", title="SYN value of a goal in the column", vertical="life", anchor_date=date.today(), color="#278dea").goal.id
        mine = goals.create(conn, owner="t1", title="SYN goal of this year", vertical="year", anchor_date=date.today(), parent_id=value).goal.id
        plan = _last_year(conn, "SYN the goal's carried plan", parent=mine)
        goals.create(conn, owner="t1", title="SYN goal below it", vertical="year", anchor_date=date.today())
        _others(conn)
    page = ui_f2.page
    _goto_today(page, ui_f2.base_url)
    group, place = page.locator(GROUP), page.locator(PLACE)
    kept = place.bounding_box()["height"]
    below = page.locator('.pattern-vertical-board__column[data-vertical="year"] [data-section="planned"] .goal-card').last
    below_at = below.evaluate("el => el.offsetTop")
    page.locator(_row(mine)).hover()
    expect(group).to_have_class(re.compile("carried-group--lit"))
    expect(_carried_cards(group)).to_have_count(1)
    expect(page.locator(f'{GROUP} [data-goal-id="{plan}"]')).to_have_count(1)
    page.wait_for_timeout(500)
    assert abs(place.bounding_box()["height"] - kept) <= 2, "the place keeps its height"
    assert group.bounding_box()["height"] < kept - 52, "the box is shorter inside it"
    assert below.evaluate("el => el.offsetTop") == below_at, "nothing under the box moved"
    expect(page.locator(GAP)).to_have_class(re.compile("carried-gap--on"))
    words = page.locator(f"{GAP} [data-role='carried-words']")
    assert words.inner_text() in SHY
    page.locator(f"{GAP} [data-role='carried-mascot']").click()
    expect(words).to_have_text("Layout fix deployed")
    page.wait_for_timeout(700)
    assert abs(place.bounding_box()["height"] - kept) <= 2 and below.evaluate("el => el.offsetTop") == below_at
    page.locator(f"{GAP} [data-role='carried-mascot']").click()
    expect(words).to_have_text("Edge case, handled")
    # out of the column: the box goes back to everything and the place is not held any more
    x, y = _blank(page, "week")
    page.mouse.move(x, y)
    expect(group).not_to_have_class(re.compile("carried-group--lit"))
    expect(_carried_cards(group)).to_have_count(3)
    expect(page.locator(GAP)).not_to_have_class(re.compile("carried-gap--on"))


def test_a_goal_without_plans_in_its_own_column_leaves_the_header_and_see_all(ui_f2: UiSession) -> None:
    """S4.P3.016, .029: nothing of this goal in the box: the box keeps its place with only its header and "See all", clear
    of colour; "See all" shows everything."""
    with psycopg.connect(ui_f2.backend.dsn, autocommit=True) as conn:
        bare = goals.create(conn, owner="t1", title="SYN goal with no carried plan", vertical="year", anchor_date=date.today()).goal.id
        _others(conn)
    page = ui_f2.page
    _goto_today(page, ui_f2.base_url)
    group, place = page.locator(GROUP), page.locator(PLACE)
    total = int(group.get_attribute("data-count") or 0)
    kept = place.bounding_box()["height"]
    page.locator(_row(bare)).hover()
    expect(_carried_cards(group)).to_have_count(0)
    more = group.locator('[data-role="carried-more"]')
    expect(more).to_have_text("See all")
    assert not _lit(group)
    assert abs(place.bounding_box()["height"] - kept) <= 2
    more.click()
    expect(_carried_cards(group)).to_have_count(total)
    expect(more).to_have_text("Show fewer")


def test_the_filter_stays_on_its_way_and_ends_off_it(ui_f2: UiSession) -> None:
    """S4.P3.024, .025: the filter lives while the pointer is in the columns from its goal to its box, on empty ground
    too; off them, or off the board, the box returns to everything."""
    with psycopg.connect(ui_f2.backend.dsn, autocommit=True) as conn:
        value, plan = _value_with_plan(conn, "SYN way value", "#92ce14")
        _others(conn)
    page = ui_f2.page
    _goto_today(page, ui_f2.base_url)
    group = page.locator(GROUP)
    page.locator(_row(value)).hover()
    expect(group).to_have_class(re.compile("carried-group--lit"))
    expect(_carried_cards(group)).to_have_count(1)
    x, y = _blank(page, "decade")                      # between the goal's column and the box's: on the way
    page.mouse.move(x, y)
    page.wait_for_timeout(900)
    assert _lit(group) and _carried_cards(group).count() == 1
    x, y = _blank(page, "week")                        # out of the way
    page.mouse.move(x, y)
    expect(group).not_to_have_class(re.compile("carried-group--lit"))
    expect(_carried_cards(group)).to_have_count(3)
    page.locator(_row(value)).hover()
    expect(_carried_cards(group)).to_have_count(1)
    page.mouse.move(5, 5)                              # off the board
    expect(_carried_cards(group)).to_have_count(3)


def test_the_box_follows_the_goal_the_pointer_rests_on_not_one_it_passes(ui_f2: UiSession) -> None:
    """S4.P3.026, .027: a goal the pointer rests on, 250 ms, takes a filtered box; passing over a goal on the way to the
    box changes nothing; a goal with nothing in the box sends it back to everything."""
    with psycopg.connect(ui_f2.backend.dsn, autocommit=True) as conn:
        a, a_plan = _value_with_plan(conn, "SYN value A", "#92ce14")
        b, b_plan = _value_with_plan(conn, "SYN value B", "#df496d")
        bare = goals.create(conn, owner="t1", title="SYN decade goal with nothing in the box", vertical="decade", anchor_date=date.today()).goal.id
        _others(conn)
    page = ui_f2.page
    _goto_today(page, ui_f2.base_url)
    group = page.locator(GROUP)
    page.locator(_row(a)).hover()
    expect(group.locator(f'[data-goal-id="{a_plan}"]')).to_have_count(1)
    bx, by = (lambda r: (r["x"] + 60, r["y"] + 8))(page.locator(_row(b)).bounding_box())
    page.mouse.move(bx, by)                            # over B, and away again before it counts as a rest
    page.wait_for_timeout(120)
    x, y = _blank(page, "decade")
    page.mouse.move(x, y)
    page.wait_for_timeout(700)
    expect(group.locator(f'[data-goal-id="{a_plan}"]')).to_have_count(1)
    page.mouse.move(bx, by)                            # a rest on B
    expect(group.locator(f'[data-goal-id="{b_plan}"]')).to_have_count(1)
    expect(group.locator(f'[data-goal-id="{a_plan}"]')).to_have_count(0)
    page.locator(_row(bare)).hover()                   # nothing of it in the box
    expect(_carried_cards(group)).to_have_count(3)
    assert not _lit(group)


def test_more_ends_the_filter_and_it_stays_ended(ui_f2: UiSession) -> None:
    """S4.P3.029: "N more" in a filtered box shows everything and ends the filter; the pointer leaving doesn't bring it
    back."""
    with psycopg.connect(ui_f2.backend.dsn, autocommit=True) as conn:
        value, _plan = _value_with_plan(conn, "SYN released value", "#92ce14")
        _others(conn)
    page = ui_f2.page
    _goto_today(page, ui_f2.base_url)
    group = page.locator(GROUP)
    total = int(group.get_attribute("data-count") or 0)
    page.locator(_row(value)).hover()
    more = group.locator('[data-role="carried-more"]')
    expect(more).to_have_text(f"{total - 1} more")
    more.click()
    expect(_carried_cards(group)).to_have_count(total)
    expect(more).to_have_text("Show fewer")
    assert not _lit(group)
    x, y = _blank(page, "week")
    page.mouse.move(x, y)
    page.wait_for_timeout(700)
    expect(_carried_cards(group)).to_have_count(total)


def test_the_box_lifts_as_one_piece_in_its_plans_colour_and_never_into_the_margin(ui_f2: UiSession) -> None:
    """S4.P3.011, .028: pointing at a plan in the box lifts the whole box, not the plan, and lights it in the plan's
    colour; a tall box grows by no more than the room under it."""
    with psycopg.connect(ui_f2.backend.dsn, autocommit=True) as conn:
        value, plan = _value_with_plan(conn, "SYN lifted value", "#278dea")
        _others(conn)
        goals.create(conn, owner="t1", title="SYN goal under the box", vertical="year", anchor_date=date.today())
    page = ui_f2.page
    _goto_today(page, ui_f2.base_url)
    group = page.locator(GROUP)
    group.locator('[data-role="carried-more"]').click()      # everything open: a tall box
    page.mouse.move(5, 5)
    page.wait_for_timeout(700)
    row = group.locator(f'[data-goal-id="{plan}"] > .goal-card__row')
    row.hover()
    expect(group).to_have_class(re.compile("carried-group--lifted"))
    expect(group).to_have_class(re.compile("carried-group--lit"))
    assert "goal-card--lifted" not in (group.locator(f'[data-goal-id="{plan}"]').get_attribute("class") or "")
    page.wait_for_timeout(500)
    grown = group.evaluate("el => el.getBoundingClientRect().height - el.offsetHeight")
    assert 0 < grown <= 8.5, f"the box grew {grown}px: the margin under it is 12"
    below = page.locator('.pattern-vertical-board__column[data-vertical="year"] [data-section="planned"] .goal-card').first
    gap = below.bounding_box()["y"] - (group.bounding_box()["y"] + group.bounding_box()["height"])
    assert gap >= 4, f"{gap}px left under a lifted box"


def test_replan_opens_the_task_as_a_window_with_our_first_message(ui_agent: UiSession) -> None:  # noqa: F811
    """S4.P4.028: the task pops out as a goal's window, our first message sent, the agent answering under it."""
    with psycopg.connect(ui_agent.backend.dsn, autocommit=True) as conn:
        _last_year(conn, "SYN plan to sort")
        with conn.transaction():
            task = replan.run(conn, owner="t1", today=date.today())
    page = ui_agent.page
    _goto_today(page, ui_agent.base_url)
    page.locator(GROUP).locator('[data-role="replan"]').click()
    window = page.locator('.vt-window[data-window="goal"]')
    expect(window).to_have_count(1)
    expect(window.locator(f'.goal-card[data-goal-id="{task}"]')).to_have_count(1)
    expect(page.locator('[data-balloon][data-who="you"]').first).to_have_text(FIRST)
    expect(page.locator('[data-balloon][data-who="agent"]')).to_have_count(1, timeout=10000)
    page.mouse.click(window.bounding_box()["x"] + 40, window.bounding_box()["y"] + 40)
    expect(window.locator('[data-role="goal-made"]')).to_have_text(re.compile(r"^made \w{3} \d{1,2} \w{3}$"))
    expect(window.locator("table")).to_contain_text("SYN plan to sort")
    # S4.P4.010: every turn in the task tells the agent how its table is worked.
    page.keyboard.press("Control+k")
    page.locator(FIELD).fill("[context]")
    page.keyboard.press("Enter")
    expect(page.locator('[data-balloon][data-who="agent"]').last).to_contain_text("Your comment, one row per plan", timeout=10000)

    # A browser that has never seen the task's conversation continues it: our first message goes only once.
    page.evaluate("() => localStorage.clear()")
    _goto_today(page, ui_agent.base_url)
    page.locator(GROUP).locator('[data-role="replan"]').click()
    expect(page.locator('[data-balloon][data-who="agent"]').last).to_contain_text("Your comment, one row per plan", timeout=10000)
    page.wait_for_timeout(500)
    expect(page.locator('[data-balloon][data-who="you"]', has_text=FIRST)).to_have_count(1)
