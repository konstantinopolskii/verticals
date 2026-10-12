"""In the Inbox a carried task waits in the field through MovingStack, as a goal does in Move
(docs/design/inbox-carry-stack.md). Press a task, carry it onto the field and let go: it waits there as the board's goal
does, the same card drawn by `MovingStack.vue`, the field saying "Find a goal"; Backspace, Tab, Esc, typing and dragging the
card out work as they do in Move (`tests/ui/test_moving.py`). The big tile that used to stand beside the field is gone.
F2, the browser clock moved to the database's day (as `test_inbox_view.py` does)."""

from __future__ import annotations

import re
from datetime import date, datetime, timezone

import psycopg
import pytest
from playwright.sync_api import Page, expect

from verticals.core import goals as core_goals, privacy as core_privacy
from tests.harness.web import WEB_DIR
from tests.ui.conftest import UiSession
from tests.ui.test_agent_conversation import ui_agent  # noqa: F401  (the fixture)
from tests.ui.test_moving import (  # noqa: F401  (ui_reduced_motion is the fixture)
    MONTH_GOAL, _assert_the_card_is_what_it_will_be_in_every_frame, _frames_while_the_field_widens, _layout, _open_weeks,
    ui_reduced_motion,
)
from tests.ui.views import FIELD, switch_view, tick

OWNER = "t1"
DAY = date(2026, 8, 8)
TODAY = '[data-role="inbox-today"]'
CARD = '[data-role="inbox-card"]'
EARLIER_TILE = '[data-role="inbox-earlier"] [data-role="inbox-tile"]'
STACK = '[data-role="moving-stack"]'
WAITING = '[data-role="moving-goal"]'
SHAPE = ".circle-field__shape"
HAND = '[data-role="inbox-carried"]'
OLD_TILE = '[data-role="inbox-beside"], .inbox-beside'
MAYBE_TASK = "SYNMAY01"  # F2's first Maybe candidate: an older task, a tile in Earlier's row
SRC = WEB_DIR / "src"


def _written(conn: psycopg.Connection, goal_id: str, ago: str) -> None:
    conn.execute("UPDATE goals SET created_at = now() - %s::interval WHERE owner = %s AND id = %s", (ago, OWNER, goal_id))


def _seed(session: UiSession) -> dict[str, str]:
    """The last three tasks written today, which Today shows: one under a goal, one loose, one under a value of a colour."""
    with psycopg.connect(session.backend.dsn, autocommit=True) as conn:
        month = core_goals.create(conn, owner=OWNER, title="SYN Carry month goal", vertical="month", anchor_date=DAY).goal.id
        under = core_goals.create(conn, owner=OWNER, title="SYN Carry task under a goal", parent_id=month).goal.id
        loose = core_goals.create(conn, owner=OWNER, title="SYN Carry loose task").goal.id
        value = core_goals.create(conn, owner=OWNER, title="SYN Carry blue value", vertical="life", anchor_date=DAY, color="#278dea").goal.id
        valued = core_goals.create(conn, owner=OWNER, title="SYN Carry task under a value", parent_id=value).goal.id
        for goal_id, ago in ((under, "1 minute"), (loose, "2 minutes"), (valued, "3 minutes")):
            _written(conn, goal_id, ago)
    return {"under": under, "loose": loose, "valued": valued}


def _open_inbox(session: UiSession) -> None:
    session.page.clock.set_fixed_time(datetime.now(timezone.utc))
    session.page.reload()
    switch_view(session.page, "inbox")
    expect(session.page.locator(f"{TODAY} {CARD}").first).to_be_visible(timeout=10000)
    session.page.mouse.move(40, 300)  # the hand away from the field


def _glide(page: Page, a: tuple[float, float], b: tuple[float, float], steps: int = 12) -> None:
    for i in range(1, steps + 1):
        page.mouse.move(a[0] + (b[0] - a[0]) * i / steps, a[1] + (b[1] - a[1]) * i / steps)
        page.wait_for_timeout(16)


def _centre(page: Page, selector: str) -> tuple[float, float]:
    box = page.locator(selector).first.bounding_box()
    assert box is not None, selector
    return box["x"] + box["width"] / 2, box["y"] + box["height"] / 2


def _press(page: Page, selector: str) -> tuple[float, float]:
    """The hand goes down on a task's words (never its square) and moves a little: past the threshold, so it is carried."""
    box = page.locator(selector).first.bounding_box()
    assert box is not None, selector
    at = (box["x"] + min(box["width"] / 2, 120), box["y"] + box["height"] / 2)
    page.mouse.move(*at)
    page.mouse.down()
    _glide(page, at, (at[0] + 14, at[1] - 14), 3)
    return at[0] + 14, at[1] - 14


def _carry_onto_the_field(page: Page, selector: str) -> None:
    held = _press(page, selector)
    _glide(page, held, _centre(page, SHAPE))
    page.mouse.up()


def _carry_and_wait(page: Page, goal_id: str) -> None:
    """A task from Today, carried onto the field and let go there; it waits."""
    _carry_onto_the_field(page, f'{TODAY} {CARD}[data-goal-id="{goal_id}"]')
    expect(page.locator(WAITING)).to_have_count(1)


def _in_its_place(page: Page, goal_id: str) -> None:
    expect(page.locator(f'{TODAY} {CARD}[data-goal-id="{goal_id}"]')).to_be_visible()
    expect(page.locator(STACK)).to_have_count(0)
    expect(page.locator(FIELD)).to_have_attribute("aria-label", "Write to inbox")


def test_a_task_let_go_over_the_field_waits_in_it_through_the_moving_stack(ui_f2: UiSession) -> None:
    """The one card of Move: `MovingStack` draws it, with the field's caption "Find a goal" and no view's name beside it."""
    page = ui_f2.page
    ids = _seed(ui_f2)
    _open_inbox(ui_f2)
    _carry_and_wait(page, ids["under"])

    waiting = page.locator(f"{STACK} {WAITING}")
    expect(waiting).to_have_count(1)
    expect(waiting).to_have_attribute("data-goal-id", ids["under"])
    expect(waiting).to_contain_text("SYN Carry task under a goal")
    expect(page.locator('[data-role="moving-view"]')).to_have_count(0)  # no spans in the Inbox, nothing to name
    expect(page.locator(FIELD)).to_have_attribute("aria-label", "Find a goal")
    expect(page.locator(".circle-field__caption")).to_have_text("Find a goal")
    expect(page.locator(".circle-field")).to_have_attribute("data-state", "moving")
    shape = page.locator(SHAPE).bounding_box()
    assert shape is not None and round(shape["width"]) in (300, 434)  # the field the board has in Move

    # The task left its place and nothing else stands for it: no tile beside the field, no hand.
    expect(page.locator(f'[data-goal-id="{ids["under"]}"]')).to_have_count(1)
    expect(page.locator(f'{TODAY} [data-goal-id="{ids["under"]}"]')).to_have_count(0)
    expect(page.locator(OLD_TILE)).to_have_count(0)
    expect(page.locator(HAND)).to_have_count(0)
    # The card stands above the field's left end, 4 px in, as the board's does (MovingStack.vue's CSS), right of the buttons
    # that stand there while the field holds the keys, even with the hand away from it.
    page.mouse.move(40, 300)
    buttons = page.locator(".circle-tags")
    expect(buttons).to_have_class(re.compile("is-shown"))
    card, field, row = waiting.bounding_box(), page.locator(SHAPE).bounding_box(), buttons.bounding_box()
    assert card is not None and field is not None and row is not None
    assert card["y"] + card["height"] <= field["y"], (card, field)
    assert abs(card["x"] - (field["x"] + 4 + row["width"] + 8)) <= 1, (card, field, row)


def test_the_field_keeps_its_width_for_the_buttons_and_the_task_when_the_hand_leaves(ui_f2: UiSession) -> None:
    """As on the board: the field holds the keys after the let-go, so its buttons stay and the card stands right of them; the
    field is as wide as both need whether the hand is on it or away."""
    page = ui_f2.page
    ids = _seed(ui_f2)
    _open_inbox(ui_f2)
    _carry_and_wait(page, ids["under"])
    page.mouse.move(*_centre(page, SHAPE))
    page.wait_for_timeout(300)
    on = _layout(page)
    assert on["buttons"] is not None and on["card"] is not None and on["card"][2] == 34, on
    page.mouse.move(40, 300)
    page.wait_for_timeout(300)
    expect(page.locator(".circle-tags")).to_have_class(re.compile("is-shown"))  # the field holds the keys: its buttons stay
    assert _layout(page) == on


def test_an_older_task_from_earlier_waits_the_same_way(ui_f2: UiSession) -> None:
    page = ui_f2.page
    _seed(ui_f2)
    _open_inbox(ui_f2)
    tile = f'{EARLIER_TILE}[data-goal-id="{MAYBE_TASK}"]'
    page.locator(tile).scroll_into_view_if_needed()
    _carry_onto_the_field(page, tile)
    expect(page.locator(f"{STACK} {WAITING}")).to_contain_text("Maybe candidate one")
    expect(page.locator(f'[data-goal-id="{MAYBE_TASK}"]')).to_have_count(1)
    expect(page.locator(OLD_TILE)).to_have_count(0)
    # Backspace twice and it is on its shelf again.
    page.locator(FIELD).focus()
    page.keyboard.press("Backspace")
    page.keyboard.press("Backspace")
    expect(page.locator(STACK)).to_have_count(0)
    expect(page.locator(f"{EARLIER_TILE}[data-goal-id=\"{MAYBE_TASK}\"]")).to_be_visible()


def test_backspace_picks_the_waiting_task_and_a_second_puts_it_back(ui_f2: UiSession) -> None:
    """S5.P4.002 as in Move: one Backspace lifts the card, a second takes it off and the field writes to the Inbox again."""
    page = ui_f2.page
    ids = _seed(ui_f2)
    _open_inbox(ui_f2)
    _carry_and_wait(page, ids["loose"])
    waiting = page.locator(WAITING)
    page.locator(FIELD).focus()
    page.keyboard.press("Backspace")
    expect(waiting).to_have_class(re.compile("is-picked"))
    expect(waiting).to_have_count(1)
    page.keyboard.press("Backspace")
    expect(waiting).to_have_count(0)
    _in_its_place(page, ids["loose"])
    # A third has nothing left to pick: the empty field simply stays empty.
    page.keyboard.press("Backspace")
    expect(page.locator(FIELD)).to_have_value("")
    expect(page.locator(STACK)).to_have_count(0)


def test_tab_picks_the_waiting_task_and_escape_lets_go_then_ends_the_move(ui_f2: UiSession) -> None:
    """S5.P4.003, .013 as in Move: Tab picks the card, Esc lets go of the pick, a second Esc takes the card off."""
    page = ui_f2.page
    ids = _seed(ui_f2)
    _open_inbox(ui_f2)
    _carry_and_wait(page, ids["valued"])
    waiting = page.locator(WAITING)
    page.locator(FIELD).focus()
    page.keyboard.press("Tab")
    expect(waiting).to_have_class(re.compile("is-picked"))
    expect(page.locator(FIELD)).to_be_focused()  # Tab picked; it did not leave the field
    page.keyboard.press("Escape")
    expect(waiting).not_to_have_class(re.compile("is-picked"))
    expect(waiting).to_have_count(1)
    page.keyboard.press("Escape")
    expect(waiting).to_have_count(0)
    _in_its_place(page, ids["valued"])


def test_typing_while_a_task_waits_works_as_on_the_board(ui_f2: UiSession) -> None:
    """The field grows around the words and the card keeps waiting; clearing the words gives "Find a goal" back."""
    page = ui_f2.page
    ids = _seed(ui_f2)
    _open_inbox(ui_f2)
    _carry_and_wait(page, ids["under"])
    page.locator(FIELD).fill("Which goal does it go under?")
    expect(page.locator(".circle-field")).to_have_attribute("data-state", "typing")
    expect(page.locator(WAITING)).to_have_count(1)
    expect(page.locator(WAITING)).not_to_have_class(re.compile("is-picked"))
    # Backspace with words in the field deletes a letter; it does not pick the card.
    page.keyboard.press("Backspace")
    expect(page.locator(FIELD)).to_have_value("Which goal does it go under")
    expect(page.locator(WAITING)).not_to_have_class(re.compile("is-picked"))
    page.locator(FIELD).fill("")
    expect(page.locator(".circle-field")).to_have_attribute("data-state", "moving")
    expect(page.locator(FIELD)).to_have_attribute("aria-label", "Find a goal")
    expect(page.locator(WAITING)).to_have_count(1)


def test_backspace_works_the_moment_the_card_is_let_go(ui_f2: UiSession) -> None:
    """Nothing before the key: no click on the field, no letter, no ⌘K. The field takes the keys when the card is let go."""
    page = ui_f2.page
    ids = _seed(ui_f2)
    _open_inbox(ui_f2)
    _carry_and_wait(page, ids["loose"])
    expect(page.locator(FIELD)).to_be_focused()
    waiting = page.locator(WAITING)
    page.keyboard.press("Backspace")
    expect(waiting).to_have_class(re.compile("is-picked"))
    page.keyboard.press("Backspace")
    expect(waiting).to_have_count(0)
    _in_its_place(page, ids["loose"])


def test_tab_and_escape_work_the_moment_the_card_is_let_go(ui_f2: UiSession) -> None:
    page = ui_f2.page
    ids = _seed(ui_f2)
    _open_inbox(ui_f2)
    _carry_and_wait(page, ids["under"])
    waiting = page.locator(WAITING)
    page.keyboard.press("Tab")
    expect(waiting).to_have_class(re.compile("is-picked"))
    page.keyboard.press("Escape")
    expect(waiting).not_to_have_class(re.compile("is-picked"))
    expect(waiting).to_have_count(1)
    page.keyboard.press("Escape")
    expect(waiting).to_have_count(0)
    _in_its_place(page, ids["under"])


def test_typing_works_the_moment_the_card_is_let_go(ui_f2: UiSession) -> None:
    page = ui_f2.page
    ids = _seed(ui_f2)
    _open_inbox(ui_f2)
    _carry_and_wait(page, ids["under"])
    page.keyboard.type("Which goal?")
    expect(page.locator(FIELD)).to_have_value("Which goal?")
    expect(page.locator(".circle-field")).to_have_attribute("data-state", "typing")
    expect(page.locator(WAITING)).to_have_count(1)
    expect(page.locator(WAITING)).not_to_have_class(re.compile("is-picked"))


def test_the_field_does_not_take_the_keys_from_a_text_field_that_has_them(ui_f2: UiSession) -> None:
    """A card let go in the field takes the keys, but not from a text field the person is typing in."""
    page = ui_f2.page
    ids = _seed(ui_f2)
    _open_inbox(ui_f2)
    page.evaluate("""() => {
      const probe = document.createElement('input');
      probe.id = 'probe';
      probe.style.cssText = 'position: fixed; left: 8px; top: 8px; width: 120px; z-index: 1000';
      document.body.appendChild(probe);
    }""")
    held = _press(page, f'{TODAY} {CARD}[data-goal-id="{ids["loose"]}"]')
    page.evaluate("document.getElementById('probe').focus()")  # a press moves the focus; the person is typing there
    _glide(page, held, _centre(page, SHAPE))
    page.mouse.up()
    expect(page.locator(WAITING)).to_have_count(1)
    expect(page.locator("#probe")).to_be_focused()
    page.keyboard.type("abc")
    expect(page.locator("#probe")).to_have_value("abc")
    expect(page.locator(FIELD)).to_have_value("")
    expect(page.locator(WAITING)).not_to_have_class(re.compile("is-picked"))


def test_words_sent_while_a_task_waits_carry_it_to_the_agent(ui_agent: UiSession) -> None:  # noqa: F811
    """S5.P3.041, .042 as in Move: ↵ sends a new task with the move's context, and the move ends: the card goes back."""
    page = ui_agent.page
    ids = _seed(ui_agent)
    _open_inbox(ui_agent)
    _carry_and_wait(page, ids["under"])
    page.locator(FIELD).fill("[context]")
    page.keyboard.press("Enter")
    answer = page.locator('[data-balloon][data-who="agent"]').last
    expect(answer).to_contain_text("moving a goal", timeout=10000)
    expect(answer).to_contain_text("SYN Carry task under a goal")
    expect(page.locator(STACK)).to_have_count(0)


def test_the_waiting_task_dragged_out_goes_back_to_its_place_when_let_go_elsewhere(ui_f2: UiSession) -> None:
    """Dragging the card out of the field: the Inbox's own drag takes it (no board is in view to land on). In the hand it is
    the tile a task is in the Inbox, the card stays out of the field's stack while it is held and the field stays the pill
    that takes it; let go on the desk, it is back in its place and the move is over."""
    page = ui_f2.page
    ids = _seed(ui_f2)
    _open_inbox(ui_f2)
    _carry_and_wait(page, ids["loose"])
    page.mouse.move(40, 300)

    held = _press(page, WAITING)
    expect(page.locator(HAND)).to_have_count(1)
    expect(page.locator(f"{HAND} [data-goal-id]")).to_have_attribute("data-goal-id", ids["loose"])
    expect(page.locator(WAITING)).to_have_class(re.compile("is-in-hand"))
    # The tile in the hand is a task's size in the Inbox, a quarter of the desk, as Earlier's row has it: not the card's.
    wide = page.locator(f"{HAND} .inbox-tile").evaluate("el => el.offsetWidth")
    assert abs(wide - page.locator(EARLIER_TILE).first.evaluate("el => el.offsetWidth")) <= 1
    _glide(page, held, (500, 250))
    expect(page.locator(".circle-field")).to_have_attribute("data-holding", "")
    shape = page.locator(SHAPE).bounding_box()
    assert shape is not None and round(shape["width"]) == 120
    page.mouse.up()
    expect(page.locator(HAND)).to_have_count(0)
    _in_its_place(page, ids["loose"])


def test_escape_while_the_waiting_task_is_dragged_out_puts_it_back(ui_f2: UiSession) -> None:
    page = ui_f2.page
    ids = _seed(ui_f2)
    _open_inbox(ui_f2)
    _carry_and_wait(page, ids["valued"])
    held = _press(page, WAITING)
    _glide(page, held, (500, 250))
    page.keyboard.press("Escape")
    expect(page.locator(HAND)).to_have_count(0)
    _in_its_place(page, ids["valued"])
    page.mouse.up()
    _in_its_place(page, ids["valued"])


def test_the_waiting_task_dragged_out_and_let_go_over_the_field_waits_again(ui_f2: UiSession) -> None:
    page = ui_f2.page
    ids = _seed(ui_f2)
    _open_inbox(ui_f2)
    _carry_and_wait(page, ids["loose"])
    held = _press(page, WAITING)
    _glide(page, held, (500, 250))
    _glide(page, (500, 250), _centre(page, SHAPE))
    page.mouse.up()
    expect(page.locator(HAND)).to_have_count(0)
    expect(page.locator(WAITING)).to_have_count(1)
    expect(page.locator(WAITING)).not_to_have_class(re.compile("is-in-hand"))
    expect(page.locator(f'[data-goal-id="{ids["loose"]}"]')).to_have_count(1)


def test_a_press_on_the_waiting_card_that_does_not_move_carries_nothing(ui_f2: UiSession) -> None:
    """The drag starts past a small threshold, so a press that stays put is a click: nothing is in the hand."""
    page = ui_f2.page
    ids = _seed(ui_f2)
    _open_inbox(ui_f2)
    _carry_and_wait(page, ids["loose"])
    at = _centre(page, WAITING)
    page.mouse.move(*at)
    page.mouse.down()
    page.wait_for_timeout(120)
    expect(page.locator(HAND)).to_have_count(0)
    expect(page.locator(WAITING)).not_to_have_class(re.compile("is-in-hand"))
    page.mouse.up()
    expect(page.locator(HAND)).to_have_count(0)


def test_a_click_after_the_let_go_keeps_the_card_and_a_tap_picks_it(ui_f2: UiSession) -> None:
    """S5.P4.017 as in Move: a click is not a release. On the field it leaves the card waiting; a tap on the card picks
    it and a second tap lets go of the pick."""
    page = ui_f2.page
    ids = _seed(ui_f2)
    _open_inbox(ui_f2)
    _carry_and_wait(page, ids["loose"])
    waiting = page.locator(WAITING)
    page.mouse.click(*_centre(page, SHAPE))
    expect(waiting).to_have_count(1)
    tick(page)
    waiting.click()
    expect(waiting).to_have_class(re.compile("is-picked"))
    waiting.click()
    expect(waiting).not_to_have_class(re.compile("is-picked"))
    expect(waiting).to_have_count(1)
    expect(page.locator(f'{TODAY} [data-goal-id="{ids["loose"]}"]')).to_have_count(0)


def test_a_carry_that_ends_elsewhere_swallows_no_later_click(ui_f2: UiSession) -> None:
    """"A press that became a carry is not a click" holds for that click only: the first click on another task, later,
    opens it."""
    page = ui_f2.page
    ids = _seed(ui_f2)
    _open_inbox(ui_f2)
    held = _press(page, f'{TODAY} {CARD}[data-goal-id="{ids["loose"]}"]')
    _glide(page, held, (900, 120))
    page.mouse.up()  # let go on the desk: back in its place
    expect(page.locator(HAND)).to_have_count(0)
    tick(page)
    page.locator(f'{TODAY} {CARD}[data-goal-id="{ids["valued"]}"] .inbox-card__words').click()
    expect(page.locator('[data-role="goal-window"]')).to_have_count(1, timeout=5000)


_LOOK = """el => {
  const pick = (node, props) => Object.fromEntries(props.map((p) => [p, getComputedStyle(node)[p]]));
  const title = el.querySelector('.moving-stack__title'), box = el.querySelector('.moving-stack__box');
  const rect = el.getBoundingClientRect(), shape = document.querySelector('.circle-field__shape').getBoundingClientRect();
  return {
    classes: [...el.classList].filter((c) => !c.startsWith('is-')).sort(),
    parts: [...el.querySelectorAll('*')].map((node) => node.className),
    parked: el.hasAttribute('data-parked'),
    card: pick(el, ['display', 'paddingTop', 'paddingLeft', 'borderRadius', 'maxWidth', 'cursor', 'touchAction']),
    title: pick(title, ['fontSize', 'fontWeight', 'lineHeight', 'color']),
    box: pick(box, ['width', 'height', 'borderRadius']),
    height: Math.round(rect.height),
    above: Math.round(shape.top - rect.bottom),
  };
}"""


def test_the_waiting_card_is_the_boards_card(ui_f2: UiSession) -> None:
    """One component: in the Inbox the waiting task has the markup, the sizes and the type of the goal waiting in Move."""
    page = ui_f2.page
    page.wait_for_selector(f'[data-goal-id="{MONTH_GOAL}"]')
    # On the board: the goal let go over the field while the weeks are open.
    dots = _open_weeks(page)
    _glide(page, dots, _centre(page, SHAPE))
    page.wait_for_timeout(200)
    page.mouse.up()
    expect(page.locator(WAITING)).to_have_count(1)
    on_the_board = page.locator(WAITING).evaluate(_LOOK)
    page.locator(FIELD).focus()
    page.keyboard.press("Escape")
    expect(page.locator(STACK)).to_have_count(0)

    ids = _seed(ui_f2)
    _open_inbox(ui_f2)
    _carry_and_wait(page, ids["under"])
    in_the_inbox = page.locator(WAITING).evaluate(_LOOK)
    assert in_the_inbox == on_the_board
    assert on_the_board["title"]["fontSize"] == "12px" and on_the_board["title"]["fontWeight"] == "500"
    assert on_the_board["card"]["borderRadius"] == "8px" and on_the_board["card"]["paddingLeft"] == "12px"
    assert on_the_board["above"] == 16 and on_the_board["height"] == 34  # 8 px over the field's line, 8 + 18 + 8 tall


def test_a_task_under_a_value_waits_lit_in_the_values_colour(ui_f2: UiSession) -> None:
    """As a goal on the board waits lit from under in its colour (`goalLight`): the Inbox's `value_color` reaches it."""
    page = ui_f2.page
    ids = _seed(ui_f2)
    _open_inbox(ui_f2)
    _carry_and_wait(page, ids["loose"])
    assert "--vt-tint" not in (page.locator(WAITING).get_attribute("style") or "")
    page.locator(FIELD).focus()
    page.keyboard.press("Escape")
    page.keyboard.press("Escape")
    expect(page.locator(STACK)).to_have_count(0)
    _carry_and_wait(page, ids["valued"])
    style = page.locator(WAITING).get_attribute("style") or ""
    assert "--vt-tint" in style and "--vt-pale" in style, style
    box = page.locator(f"{WAITING} .moving-stack__box")
    assert box.evaluate("el => getComputedStyle(el).backgroundColor") != "rgb(210, 210, 210)"


def test_a_private_task_waits_with_its_words_hidden(ui_f2: UiSession) -> None:
    """Privacy mode hides a private task's words in the Inbox; the card in the field keeps them hidden."""
    page = ui_f2.page
    ids = _seed(ui_f2)
    with psycopg.connect(ui_f2.backend.dsn, autocommit=True) as conn:
        core_goals.update(conn, owner=OWNER, id=ids["loose"], private=True)
        core_privacy.set_mode(conn, owner=OWNER, mode=True)
    _open_inbox(ui_f2)
    _carry_and_wait(page, ids["loose"])
    title = page.locator(f"{WAITING} .moving-stack__title")
    assert title.evaluate("el => getComputedStyle(el).color") == "rgba(0, 0, 0, 0)"
    assert title.evaluate("el => getComputedStyle(el).backgroundColor") == "rgb(228, 228, 228)"


@pytest.mark.parametrize("ui_reduced_motion", ["no-preference"], indirect=True)
def test_the_card_arrives_in_the_field_as_on_the_board_with_no_entrance_of_its_own(ui_f2: UiSession) -> None:
    """Move has no entrance for the waiting card (the field widens round it); the Inbox adds none."""
    page = ui_f2.page
    assert page.evaluate("matchMedia('(prefers-reduced-motion: reduce)').matches") is False  # motion is on
    ids = _seed(ui_f2)
    _open_inbox(ui_f2)
    _carry_and_wait(page, ids["loose"])
    animations = page.locator(WAITING).evaluate("el => el.getAnimations({ subtree: true }).map((a) => a.animationName || a.transitionProperty)")
    assert animations == [], animations
    names = page.evaluate("[...document.styleSheets].flatMap((s) => [...s.cssRules]).filter((r) => r.type === 7).map((r) => r.name)")
    assert not [name for name in names if "beside" in name], names


@pytest.mark.parametrize("ui_reduced_motion", ["no-preference"], indirect=True)
def test_the_waiting_task_is_the_same_card_in_every_frame_while_the_field_widens(ui_f2: UiSession) -> None:
    """As on the board: the field is the 120 px pill that takes the task; let go, it widens round it. The card has the lines
    it has at rest from the first frame, not the room that is left in a field that has not widened yet."""
    page = ui_f2.page
    ids = _seed(ui_f2)
    _open_inbox(ui_f2)
    held = _press(page, f'{TODAY} {CARD}[data-goal-id="{ids["under"]}"]')
    _glide(page, held, _centre(page, SHAPE))
    page.wait_for_function("() => Math.round(document.querySelector('.circle-field__shape').getBoundingClientRect().width) === 120")
    frames = _frames_while_the_field_widens(page, page.mouse.up)
    _assert_the_card_is_what_it_will_be_in_every_frame(frames)


def test_nothing_of_the_tile_beside_the_field_is_left() -> None:
    """The tile beside the field was a second way to wait; `lib/inboxCarry.ts` keeps only the drag."""
    left = [path.relative_to(SRC).as_posix() for path in sorted(SRC.rglob("*"))
            if path.suffix in {".vue", ".ts", ".tsx", ".css"} and re.search(r"inbox-beside|carry\.beside", path.read_text(encoding="utf-8"))]
    assert left == [], f"the tile beside the field is still in {left}"
