"""Owner defect 2026-08-10, item 6: the board must follow the calendar across midnight.

Verbatim: "уверен, что завтра автоматически цель на завтра не перенесётся". The scheduling side
was never the problem — the server buckets a goal by its `anchor_date`, so a goal anchored on
tomorrow lands in tomorrow's day column the moment the board is fetched with tomorrow's date. The
problem was that the board was fetched with `todayIso()` exactly once, at mount, and every write
after that re-fetched the SAME anchor (`store.ts::reloadBoard`). A tab left open across midnight
kept naming yesterday "Today" forever.

D69. Fixture F2. The assertion is a network fact, not a pixel: after the clock crosses midnight,
the app must issue a board fetch for the NEW date on its own, without any user gesture.

Playwright's `set_fixed_time` freezes the clock rather than running it, so it advances time
without firing the 30 s interval. That is deliberate here: the interval is glue, and the trigger
this test drives — a `focus` event after a sleeping machine wakes up — is the one that actually
matters on a laptop, which is the case the interval alone cannot cover.
"""

from __future__ import annotations

import time

from tests.ui.conftest import UiSession, activate_column

PINNED_DAY = "2026-08-08"
NEXT_DAY = "2026-08-09"
MIDNIGHT_PAST = f"{NEXT_DAY}T00:00:05+03:00"


def _board_fetches(session: UiSession) -> list[str]:
    """Every date the app has asked the board for, in order.

    The parameter is `date` — `GET /api/board?date=…`, `lib/api.ts::fetchBoard`. There is no
    client-invented default, so every board the app has ever shown appears here by name.
    """
    return [
        req["url"].split("date=", 1)[1].split("&", 1)[0]
        for req in session.request_log
        if "/api/board" in req["url"] and "date=" in req["url"]
    ]


def test_owner_day_rollover(ui_f2: UiSession) -> None:
    session = ui_f2
    page = session.page

    page.wait_for_selector('[data-goal-id]')
    before = _board_fetches(session)
    assert before, "the app must have fetched a board at all"
    assert before[-1] == PINNED_DAY, f"board must start on the pinned day, got {before[-1]}"

    # Midnight passes while the machine is asleep: the clock jumps, no timer fires.
    page.clock.set_fixed_time(MIDNIGHT_PAST)
    page.evaluate("window.dispatchEvent(new Event('focus'))")

    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        if NEXT_DAY in _board_fetches(session):
            break
        page.wait_for_timeout(100)

    after = _board_fetches(session)
    assert after[-1] == NEXT_DAY, (
        "after midnight the board must re-anchor itself onto the new day; "
        f"fetch sequence was {after}"
    )

    # And it must do so exactly once — a watcher that re-fetches on every wake would hammer the
    # backend for the rest of the day.
    page.evaluate("window.dispatchEvent(new Event('focus'))")
    page.wait_for_timeout(300)
    assert _board_fetches(session).count(NEXT_DAY) == 1, "rollover must fetch the new day once"


def test_owner_day_rollover_leaves_a_navigated_board_alone(ui_f2: UiSession) -> None:
    """A user who navigated to another period stays there — only the clock moves on.

    The rollover exists to keep "Today" honest, not to drag the board away from wherever its
    reader deliberately put it.
    """
    session = ui_f2
    page = session.page

    page.wait_for_selector('[data-goal-id]')
    # One stepper per column, and the whole `.period-nav` row only renders on column hover
    # (`Column.vue`: `display:none` until `.pattern-vertical-board__column:hover`). Hover first,
    # then click — any column's stepper re-anchors the whole board.
    column = page.locator('[data-vertical="week"]')
    activate_column(page, "week")
    column.locator('[data-cap="period-prev"]').click()
    page.wait_for_timeout(400)
    navigated = _board_fetches(session)[-1]
    assert navigated != PINNED_DAY, "the precondition is a board that moved off today"

    page.clock.set_fixed_time(MIDNIGHT_PAST)
    page.evaluate("window.dispatchEvent(new Event('focus'))")
    page.wait_for_timeout(500)

    assert _board_fetches(session)[-1] == navigated, (
        "a board the user navigated must not be re-anchored by the rollover"
    )
