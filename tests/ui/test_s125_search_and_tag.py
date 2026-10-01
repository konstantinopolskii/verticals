"""S-125 — Search and filter on the surface KK looks at.

The field is the mascot's circle (docs/design-handoff S1.P1–S1.P3): typed words narrow the board in its own columns, and
from a word of three letters the server finds titles and notes in every period, so a goal whose word is only in its
notes shows too. Shorter words search only the board on screen and ask nothing. Fixture F2. Steps: 1. focus the field
with the shortcut and type `cycl`. 2. press Escape. Serves J6, L7, J4.

Also the browser half of S-114 (CORS-closed, same-origin only) per this scenario's own closing paragraph.
"""

from __future__ import annotations

import time
from urllib.parse import urlsplit

from playwright.sync_api import expect

from tests.ui.conftest import UiSession
from tests.ui.views import FIELD

ON_BOARD = ".pattern-vertical-board .goal-card[data-goal-id]"
DAY_CARDS = '[data-vertical="day"] .card-stack > [data-goal-id]'
SYNSCH_IDS = {"SYNSCH01", "SYNSCH02", "SYNSCH03", "SYNSCH04"}  # SYNSCH04's word ("motorcycle") is in its notes


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

    # --- two letters search the board on screen and ask the server nothing ---------------------------
    page.keyboard.press("Control+k")
    field = page.locator(FIELD)
    expect(field).to_be_focused()
    n0 = len(session.request_log)
    field.fill("cy")
    page.wait_for_timeout(600)
    assert _search_requests(session.request_log[n0:]) == [], "one or two letters must send no request"

    # --- 1: "cycl" finds the S-26 titles and the goal with the word in its notes ----------------------
    field.fill("cycl")
    found: set[str] = set()
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        found = _ids(page, ON_BOARD) & SYNSCH_IDS
        if found == SYNSCH_IDS:
            break
        page.wait_for_timeout(100)
    assert found == SYNSCH_IDS, f"expected every S-26 match on the board, notes included, got {found}"
    requests = _search_requests(session.request_log[n0:])
    assert any("q=cycl" in r["url"] and "with=parents" in r["url"] for r in requests)
    assert all(r["method"] == "GET" and r["status"] == 200 for r in requests)
    assert session.dialog_records() == [], f"a browser dialog opened during search: {session.dialog_records()}"

    # --- 2: Escape clears the words: the board is whole again and the address never moved ----------
    field.press("Escape")
    expect(field).to_have_value("")
    expect(page.locator(DAY_CARDS)).to_have_count(day_cards)
    assert session.dialog_records() == [], f"a browser dialog opened on Escape: {session.dialog_records()}"
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
