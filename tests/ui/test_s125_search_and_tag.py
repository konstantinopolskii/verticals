"""S-125 — Search and filter on the surface KK looks at.

docs/E2E.md lines 1772-1788 drew search as a modal with a result list. KK's redo replaced it with one floating field,
"Find, filter or ask" (3bc40f9: "Replace the rejected view switch, result list and Agent button with KK's floating
720px field"): typed words narrow the board in its own columns, a parent stays as grey context, and goals the board
doesn't show are listed on the same surface, right above the field. Fixture F2. Steps: 1. focus the field with the
shortcut and type `cycl`. 2. press Escape. Serves J6, L7, J4.

Three of the modal's rules left with it, and the gaps are with KK: the field matches titles only, so SYNSCH04, whose
word is in its notes ("motorcycle"), is no longer found; a word under three letters narrows the board too (the field
filters from the first letter and reads the whole inventory for it); and the `#retro` tag chip step (AC-120) has had no
control since the redo.

Also the browser half of S-114 (CORS-closed, same-origin only) per this scenario's own closing paragraph.
"""

from __future__ import annotations

import re
import time
from urllib.parse import urlsplit

from playwright.sync_api import expect

from tests.ui.conftest import UiSession
from tests.ui.views import FIELD

OFF_BOARD = '[data-role="offboard-matches"] [data-goal-id]'
ON_BOARD = ".pattern-vertical-board .goal-card[data-goal-id]:not([data-filter-context])"
DAY_CARDS = '[data-vertical="day"] .card-stack > [data-goal-id]'
SYNSCH_IDS = {"SYNSCH01", "SYNSCH02", "SYNSCH03"}  # S-26's matches by title; SYNSCH04 matches only in its notes


def _search_requests(log: list[dict]) -> list[dict]:
    return [r for r in log if "/api/search" in r["url"]]


def _ids(page, selector: str) -> set[str]:
    return set(page.locator(selector).evaluate_all("els => els.map(el => el.dataset.goalId)"))


def test_s125_search_and_filter(ui_f2: UiSession) -> None:
    session = ui_f2
    page = session.page
    url_before = page.url
    own_origin = urlsplit(session.base_url)._replace(path="", query="", fragment="").geturl()
    page.wait_for_selector(DAY_CARDS, timeout=10000)
    day_cards = page.locator(DAY_CARDS).count()

    # --- 1: the shortcut focuses the field; "cycl" finds the S-26 titles, wherever they are ---------
    page.keyboard.press("Control+k")
    field = page.locator(FIELD)
    expect(field).to_be_focused()
    n0 = len(session.request_log)
    field.fill("cycl")
    # The line above the field ("Maybe this?") names three and counts the rest: "+1".
    found: set[str] = set()
    more = 0
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        found = _ids(page, ON_BOARD) | _ids(page, OFF_BOARD)
        counted = page.locator('[data-role="offboard-matches"] .command-field__muted', has_text=re.compile(r"^\+\d+"))
        more = int((counted.text_content() or "+0").strip().lstrip("+").rstrip("+")) if counted.count() else 0
        if found <= SYNSCH_IDS and len(found) + more == len(SYNSCH_IDS):
            break
        page.wait_for_timeout(100)
    assert found <= SYNSCH_IDS and len(found) + more == len(SYNSCH_IDS), (
        f"expected the {len(SYNSCH_IDS)} S-26 titles on the board or above the field, got {found} and +{more}"
    )
    # The board narrows in the browser at once; the server's answer for goals off the board comes after it.
    deadline = time.monotonic() + 5
    requests = _search_requests(session.request_log[n0:])
    while not any("q=cycl" in r["url"] for r in requests) and time.monotonic() < deadline:
        page.wait_for_timeout(50)
        requests = _search_requests(session.request_log[n0:])
    assert any("q=cycl" in r["url"] for r in requests), "the word goes to the server as the candidate query"
    assert all(r["method"] == "GET" and r["status"] == 200 for r in requests)
    assert session.dialog_records() == [], (
        f"a browser dialog opened during search: {session.dialog_records()}"
    )

    # --- 2: Escape clears the words: the board is whole again and the address never moved ----------
    field.press("Escape")
    expect(field).to_have_value("")
    expect(page.locator(DAY_CARDS)).to_have_count(day_cards)
    assert session.dialog_records() == [], (
        f"a browser dialog opened on Escape: {session.dialog_records()}"
    )
    assert page.url == url_before, "search changed page.url()"

    # --- S-114's browser half: same-origin only, zero foreign Origin headers, zero CORS mentions ---
    for r in session.request_log:
        origin_header = r["headers"].get("origin")
        if origin_header is not None:
            assert origin_header.rstrip("/") == own_origin.rstrip("/"), (
                f"request to {r['url']} carried a foreign Origin header: {origin_header!r}"
            )
    cors_mentions = [line for line in session.console_errors if "cors" in line.lower()]
    assert cors_mentions == [], f"console error(s) mention CORS: {cors_mentions}"
