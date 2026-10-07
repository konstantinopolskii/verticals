"""URL ↔ state (`web/src/lib/urlState.ts`): Back/Forward walk the app, not only the address bar.

Grammar under test: the path carries the board date (`/`, `/h/<date>`), the fragment carries the
rest (`#inbox`, `#docs`, `#goal/<id>`, `#doc/<id>`); the query is never used. Every scenario
drives the real browser history (`page.go_back`/`go_forward`) and asserts what renders, since a
URL that moves while the screen does not is exactly the bug this module fixes.

Helpers are a local copy of `test_open_card_drag.py`'s, per this package's convention of keeping
gesture helpers per module.
"""

from __future__ import annotations

import re
from urllib.parse import urlsplit

import httpx
from playwright.sync_api import Page, expect

from tests.ui.conftest import UiSession, activate_column
from tests.ui.views import expect_view, open_page, switch_view, tick

# conftest.py's PINNED_CLOCK_ISO date: the board `/` renders.
ANCHOR_ISO = "2026-08-08"


def _card(goal_id: str) -> str:
    return f'[data-goal-id="{goal_id}"]'


def _title(goal_id: str) -> str:
    return f"{_card(goal_id)} > .goal-card__row .goal-card__title"


def _open_host(goal_id: str) -> str:
    return f"{_card(goal_id)}.goal-card--detail-open"


def _post(session: UiSession, path: str, payload: dict[str, object]) -> str:
    resp = httpx.post(
        f"{session.backend.base_url}{path}",
        json=payload,
        headers={"Authorization": f"Bearer {session.backend.token}"},
        timeout=10,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _create_goal(session: UiSession, title: str, vertical: str = "week") -> str:
    return _post(session, "/api/goals", {"title": title, "vertical": vertical, "anchor_date": ANCHOR_ISO})


def _create_maybe(session: UiSession, title: str) -> str:
    return _post(session, "/api/goals", {"title": title})


def _path_and_fragment(page: Page) -> tuple[str, str]:
    parts = urlsplit(page.url)
    assert parts.query == "", f"the query is never part of the grammar, got {page.url!r}"
    return parts.path, parts.fragment


def _open_board_goal(page: Page, goal_id: str) -> None:
    page.locator(_title(goal_id)).click()
    expect(page.locator(_open_host(goal_id))).to_be_visible(timeout=10000)


def _nav_current(page: Page, item: str) -> None:
    expect_view(page, item)


# --- UH-1 ---------------------------------------------------------------------------------------


def test_uh1_back_closes_goal_and_forward_reopens_it(ui_f2: UiSession) -> None:
    page = ui_f2.page
    g_id = _create_goal(ui_f2, "SYN UH1 target")
    page.reload()
    activate_column(page, "week")

    _open_board_goal(page, g_id)
    assert _path_and_fragment(page) == ("/", f"goal/{g_id}")

    page.go_back()
    expect(page.locator(_open_host(g_id))).to_have_count(0)
    assert _path_and_fragment(page) == ("/", "")

    page.go_forward()
    expect(page.locator(_open_host(g_id))).to_be_visible(timeout=10000)
    assert _path_and_fragment(page) == ("/", f"goal/{g_id}")


# --- UH-2 ---------------------------------------------------------------------------------------


def test_uh2_close_rewinds_instead_of_stacking_an_entry(ui_f2: UiSession) -> None:
    """Escape on a goal this session opened goes back to the entry it was opened from: the history
    does not grow, and Forward re-opens the goal."""
    page = ui_f2.page
    g_id = _create_goal(ui_f2, "SYN UH2 target")
    page.reload()
    activate_column(page, "week")

    _open_board_goal(page, g_id)
    length_open = page.evaluate("history.length")

    page.keyboard.press("Escape")
    expect(page.locator(_open_host(g_id))).to_have_count(0)
    expect(page).to_have_url(re.compile(r"/$"))
    assert page.evaluate("history.length") == length_open, "closing stacked a new history entry"

    page.go_forward()
    expect(page.locator(_open_host(g_id))).to_be_visible(timeout=10000)
    assert _path_and_fragment(page) == ("/", f"goal/{g_id}")


# --- UH-3 ---------------------------------------------------------------------------------------


def test_uh3_close_after_goal_to_goal_does_not_rewind_onto_the_first_goal(ui_f2: UiSession) -> None:
    """A → B → close: the previous entry is A, not the board, so the close must push the board
    rather than rewind — otherwise closing B would re-open A."""
    page = ui_f2.page
    a_id = _create_goal(ui_f2, "SYN UH3 first")
    b_id = _create_goal(ui_f2, "SYN UH3 second")
    page.reload()
    activate_column(page, "week")

    _open_board_goal(page, a_id)
    _open_board_goal(page, b_id)
    assert _path_and_fragment(page) == ("/", f"goal/{b_id}")

    page.keyboard.press("Escape")
    expect(page.locator(_open_host(b_id))).to_have_count(0)
    expect(page.locator(_open_host(a_id))).to_have_count(0)
    assert _path_and_fragment(page) == ("/", "")

    page.go_back()
    expect(page.locator(_open_host(b_id))).to_be_visible(timeout=10000)
    assert _path_and_fragment(page) == ("/", f"goal/{b_id}")


# --- UH-4 ---------------------------------------------------------------------------------------


def test_uh4_inbox_goal_window_is_an_entry(ui_f2: UiSession) -> None:
    """Since the Inbox and Documents redesign (round 7) a goal in the Inbox opens as a window over it (S3.P4). `#goal/<id>`
    carries no view: for a goal with no date, `navigateToGoal` opens that same window over the Inbox, so Back and
    Forward close and reopen it."""
    page = ui_f2.page
    g_id = _create_maybe(ui_f2, "SYN UH4 inbox target")
    page.reload()
    window = page.locator(f'[data-role="goal-window"][data-goal-id-window="{g_id}"]')

    switch_view(page, "inbox")
    _nav_current(page, "inbox")
    assert _path_and_fragment(page) == ("/", "inbox")

    page.locator(f'[data-cap="inbox"] [data-goal-id="{g_id}"]').click()
    expect(window).to_be_visible(timeout=10000)
    expect(page).to_have_url(re.compile(rf"#goal/{g_id}$"))

    page.go_back()
    expect(window).to_have_count(0)
    _nav_current(page, "inbox")
    assert _path_and_fragment(page) == ("/", "inbox")

    page.go_forward()
    expect(window).to_be_visible(timeout=10000)
    _nav_current(page, "inbox")
    assert _path_and_fragment(page) == ("/", f"goal/{g_id}")

    tick(page)
    page.locator('[data-role="window-close"]').click()
    expect(window).to_have_count(0)
    _nav_current(page, "inbox")
    assert _path_and_fragment(page) == ("/", "inbox")


# --- UH-5 ---------------------------------------------------------------------------------------


def test_uh5_period_step_is_a_history_entry(ui_f2: UiSession) -> None:
    page = ui_f2.page
    page.wait_for_selector("[data-goal-id]")
    week = page.locator('.pattern-vertical-board__column[data-vertical="week"]')
    key_today = week.get_attribute("data-period-key")

    activate_column(page, "week")
    week.locator('[data-cap="period-next"]').click()
    expect(page).to_have_url(re.compile(r"/h/\d{4}-\d{2}-\d{2}$"))
    expect(week).not_to_have_attribute("data-period-key", key_today or "")
    key_next = week.get_attribute("data-period-key")

    page.go_back()
    expect(week).to_have_attribute("data-period-key", key_today or "")
    assert _path_and_fragment(page) == ("/", "")

    page.go_forward()
    expect(week).to_have_attribute("data-period-key", key_next or "")
    expect(page).to_have_url(re.compile(r"/h/\d{4}-\d{2}-\d{2}$"))


# --- UH-6 ---------------------------------------------------------------------------------------


def test_uh6_docs_view_is_an_entry_and_a_page_window_is_not(ui_f2: UiSession) -> None:
    """Documents is an entry. Since the Inbox and Documents redesign (rounds 2 and 7) a page opened from the desk is a
    window over it (S3.P4), and a window is never an address; `#doc/<id>` still opens a document in Documents itself
    (UH-8, UH-9)."""
    page = ui_f2.page
    doc_id = _post(ui_f2, "/api/docs", {"path": "syn-uh6.md", "title": "SYN UH6 doc", "body": ""})
    page.reload()

    switch_view(page, "docs")
    _nav_current(page, "docs")
    assert _path_and_fragment(page) == ("/", "docs")

    open_page(page, doc_id)
    assert _path_and_fragment(page) == ("/", "docs")
    page.locator('.vt-window[data-window="doc"] [aria-label="Close"]').click()
    expect(page.locator('[data-role="doc-window"]')).to_have_count(0)

    page.go_back()
    _nav_current(page, "verticals")
    assert _path_and_fragment(page) == ("/", "")

    page.go_forward()
    _nav_current(page, "docs")
    assert _path_and_fragment(page) == ("/", "docs")


# --- UH-7 ---------------------------------------------------------------------------------------


def test_uh7_boot_keeps_search_and_hand_typed_today_paths(ui_f2: UiSession) -> None:
    """Addresses that already mean the loaded board are not rewritten at boot: `/search/<q>` stays
    while the search surface is open, and a hand-typed `/h/<today>` is not collapsed to `/`.
    The `about:blank` hop forces a real boot (see OD-4's note in `test_open_card_drag.py`)."""
    session = ui_f2
    page = session.page

    page.goto("about:blank")
    page.goto(f"{session.base_url}/search/cycl")
    page.wait_for_selector("[data-goal-id]")
    page.wait_for_timeout(500)
    assert urlsplit(page.url).path == "/search/cycl"

    page.goto("about:blank")
    page.goto(f"{session.base_url}/h/{ANCHOR_ISO}")
    page.wait_for_selector("[data-goal-id]")
    page.wait_for_timeout(500)
    assert _path_and_fragment(page) == (f"/h/{ANCHOR_ISO}", "")


# --- UH-8 / UH-9: doc ↔ goal ---------------------------------------------------------------------

# A week outside the pinned board's, so the doc's link takes `navigateToGoal`'s step (c): reload the
# board at the goal's own date, then open it.
OFF_BOARD_ISO = "2026-09-16"


def _doc_linking_goal(session: UiSession, slug: str) -> tuple[str, str]:
    g_id = _post(
        session, "/api/goals", {"title": f"SYN {slug} goal", "vertical": "week", "anchor_date": OFF_BOARD_ISO},
    )
    doc_id = _post(
        session, "/api/docs",
        {"path": f"syn-{slug.lower()}.md", "title": f"SYN {slug} doc", "body": f"[SYN {slug} goal](goal:{g_id})"},
    )
    return g_id, doc_id


def test_uh8_doc_to_off_board_goal_is_one_entry_and_forward_reopens_it(ui_f2: UiSession) -> None:
    """The board reload on the way to the goal must not leave its own stop ("the doc over the
    goal's week"), and Forward after Back must open the goal — not keep Docs on screen because the
    goal is still open behind it."""
    page = ui_f2.page
    g_id, doc_id = _doc_linking_goal(ui_f2, "UH8")
    page.reload()

    # The document in Documents itself, by its address (a page from the desk is a window and no address, UH-6).
    page.goto("about:blank")
    page.goto(f"{ui_f2.base_url}/#doc/{doc_id}")
    expect(page.locator('[data-role="doc-detail"]')).to_be_visible(timeout=10000)
    length_doc = page.evaluate("history.length")

    page.locator('[data-role="doc-detail"] a[data-link-kind="goal"]').click()
    expect(page.locator(_open_host(g_id))).to_be_visible(timeout=10000)
    # The address is written once the whole jump settles (the goal's detail fetch included).
    expect(page).to_have_url(re.compile(rf"/h/{OFF_BOARD_ISO}#goal/{g_id}$"))
    assert page.evaluate("history.length") == length_doc + 1, "the jump to the goal left more than one entry"

    page.go_back()
    _nav_current(page, "docs")
    expect(page.locator('[data-role="doc-detail"]')).to_be_visible(timeout=10000)
    assert _path_and_fragment(page) == ("/", f"doc/{doc_id}")

    page.go_forward()
    _nav_current(page, "verticals")
    expect(page.locator(_open_host(g_id))).to_be_visible(timeout=10000)
    assert _path_and_fragment(page) == (f"/h/{OFF_BOARD_ISO}", f"goal/{g_id}")


def test_uh9_goal_to_doc_chip_back_reopens_goal(ui_f2: UiSession) -> None:
    """The mirror case: the doc chip leaves the goal open behind Docs, so Back to `#goal/<id>` has to
    bring the goal back on screen rather than find it "already open" and stay on the doc."""
    session = ui_f2
    page = session.page
    g_id, doc_id = _doc_linking_goal(session, "UH9")

    page.goto(f"{session.base_url}/h/{OFF_BOARD_ISO}#goal/{g_id}")
    expect(page.locator(_open_host(g_id))).to_be_visible(timeout=10000)

    # The document links the goal: the open goal lists it under "Mentioned in 1 document" (the opened-card cleanup).
    page.locator(f'{_open_host(g_id)} + .goal-card__children--open [data-role="goal-mentions"]').click()
    page.locator(f'[data-role="goal-mentions-list"] button[data-doc="{doc_id}"]').click()
    _nav_current(page, "docs")
    expect(page.locator('[data-role="doc-detail"]')).to_be_visible(timeout=10000)
    assert _path_and_fragment(page) == (f"/h/{OFF_BOARD_ISO}", f"doc/{doc_id}")

    page.go_back()
    _nav_current(page, "verticals")
    expect(page.locator(_open_host(g_id))).to_be_visible(timeout=10000)
    assert _path_and_fragment(page) == (f"/h/{OFF_BOARD_ISO}", f"goal/{g_id}")

    page.go_forward()
    _nav_current(page, "docs")
    expect(page.locator('[data-role="doc-detail"]')).to_be_visible(timeout=10000)
    assert _path_and_fragment(page) == (f"/h/{OFF_BOARD_ISO}", f"doc/{doc_id}")


# --- UH-10 / UH-11: overlapping walks, failed loads ----------------------------------------------


def test_uh10_fast_double_back_keeps_forward_history(ui_f2: UiSession) -> None:
    """The second Back starts a new walk while the first still awaits its board. The first walk's
    end must not hand the watcher the second one's half-applied state: that push would drop every
    Forward entry."""
    page = ui_f2.page
    page.wait_for_selector("[data-goal-id]")
    week = page.locator('.pattern-vertical-board__column[data-vertical="week"]')
    key_today = week.get_attribute("data-period-key")
    for _ in range(2):
        before = week.get_attribute("data-period-key")
        activate_column(page, "week")
        week.locator('[data-cap="period-next"]').click()
        expect(week).not_to_have_attribute("data-period-key", before or "")
    key_far = week.get_attribute("data-period-key")
    length = page.evaluate("history.length")

    # Board fetches slowed so the walks overlap the way they do on a real network.
    page.evaluate(
        """() => {
          const fetchNow = window.fetch.bind(window)
          window.fetch = async (input, init) => {
            const url = typeof input === 'string' ? input : input.url
            if (url.includes('/api/board')) await new Promise((r) => setTimeout(r, 600))
            return fetchNow(input, init)
          }
          history.back()
          setTimeout(() => history.back(), 100)
        }"""
    )
    expect(week).to_have_attribute("data-period-key", key_today or "", timeout=10000)
    expect(page).to_have_url(re.compile(r"/$"))
    assert page.evaluate("history.length") == length, "a walk pushed an entry and dropped the Forward history"

    page.go_forward()
    page.go_forward()
    expect(week).to_have_attribute("data-period-key", key_far or "", timeout=10000)


def test_uh11_failed_board_load_keeps_the_address(ui_f2: UiSession) -> None:
    """A board that did not load is not a state to correct the address to: the address keeps what
    was asked for, so a retry can get it."""
    session = ui_f2
    session.expects_network_failures = True  # the impossible date is a real 422 from GET /api/board
    page = session.page

    page.goto("about:blank")
    page.goto(f"{session.base_url}/h/2026-02-31")
    expect(page.locator(".toast-stack .toast")).to_be_visible(timeout=10000)
    page.wait_for_timeout(300)
    assert urlsplit(page.url).path == "/h/2026-02-31"
