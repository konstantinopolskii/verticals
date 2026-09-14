"""S-125 — Search and the tag filter on the surface KK looks at.

docs/E2E.md lines 1772-1788. Fixture F2. Steps: 1. open search with the loupe, then type `c`,
`cy`, then `cycl` into the modal. 2. click a `#retro` tag chip. 3. press Escape. Required by
AC-120. Serves J6, L7, J4.

Also the browser half of S-114 (CORS-closed, same-origin only) per this scenario's own closing
paragraph.
"""

from __future__ import annotations

from urllib.parse import urlsplit

from tests.ui.conftest import UiSession

SEARCH_TRIGGER = '[data-cap="search-trigger"]'
SEARCH_BACKDROP = '[data-cap="search-backdrop"]'
SEARCH_MODAL = '[data-cap="search-modal"]'
SEARCH_INPUT = '[data-cap="search-input"] input'
SEARCH_RESULTS = '[data-cap="search-results"]'
SEARCH_ROWS = f'{SEARCH_RESULTS} [data-goal-id]'
SYNSCH_IDS = {"SYNSCH01", "SYNSCH02", "SYNSCH03", "SYNSCH04"}
SYNRET_IDS = {"SYNRET01", "SYNRET02"}


def _search_requests(log: list[dict]) -> list[dict]:
    return [r for r in log if "/api/search" in r["url"]]


def test_s125_search_and_tag(ui_f2: UiSession) -> None:
    session = ui_f2
    url_before = session.page.url
    own_origin = urlsplit(session.base_url)._replace(path="", query="", fragment="").geturl()

    # P-01 opens search as a full surface and loads a bounded recent-default list. Isolate that
    # request before S-125 measures the 1/2/4-character text-search sequence.
    search_trigger = session.page.locator(SEARCH_TRIGGER)
    search_trigger.click()
    session.page.locator(SEARCH_MODAL).wait_for(state="visible", timeout=5000)
    search_input = session.page.locator(SEARCH_INPUT)
    search_input.wait_for(state="visible", timeout=5000)
    for _ in range(15):
        if _search_requests(session.request_log):
            break
        session.page.wait_for_timeout(100)
    initial_requests = _search_requests(session.request_log)
    assert len(initial_requests) == 1
    assert initial_requests[0]["url"].endswith("/api/search?limit=10")

    # --- 1a: "c" — no request at 1 character ------------------------------------------------------
    n0 = len(session.request_log)
    search_input.fill("c")
    session.page.wait_for_timeout(150)  # let any (wrongly issued) request land before counting
    assert _search_requests(session.request_log[n0:]) == [], "a request was issued at 1 character"
    assert session.page.locator(SEARCH_ROWS).count() == 0, "results rendered at 1 char"

    # --- 1b: "cy" — still no request at 2 characters ------------------------------------------------
    n1 = len(session.request_log)
    search_input.fill("cy")
    session.page.wait_for_timeout(150)
    assert _search_requests(session.request_log[n1:]) == [], "a request was issued at 2 characters"
    assert session.page.locator(SEARCH_ROWS).count() == 0, "results rendered at 2 chars"

    # --- 1c: "cycl" — exactly 4 results, exactly the S-26 ids, via GET /api/search?q=cycl -----------
    n2 = len(session.request_log)
    search_input.fill("cycl")
    session.page.wait_for_selector(SEARCH_ROWS, timeout=5000)
    new_requests = _search_requests(session.request_log[n2:])
    assert len(new_requests) == 1, f"expected exactly 1 search request at 3+ chars, got {len(new_requests)}"
    assert new_requests[0]["method"] == "GET"
    assert new_requests[0]["url"].endswith("/api/search?q=cycl"), f"unexpected url: {new_requests[0]['url']}"
    assert new_requests[0]["status"] == 200

    result_ids = set(
        session.page.locator(SEARCH_ROWS).evaluate_all(
            "els => els.map(el => el.getAttribute('data-goal-id'))"
        )
    )
    assert result_ids == SYNSCH_IDS, f"expected exactly {SYNSCH_IDS}, got {result_ids}"

    assert session.dialog_records() == [], (
        f"a browser dialog opened during search: {session.dialog_records()}"
    )
    assert urlsplit(session.page.url).path == "/search/cycl"

    # --- 2: click a #retro tag chip — exactly SYNRET01/SYNRET02, not on the current board ------------
    search_input.fill("#retro")
    chip = session.page.locator(f'{SEARCH_MODAL} [data-tag="retro"]')
    chip.wait_for(state="visible")
    # "The hash is CSS" (E2E.md S-125's own words, UI_REFERENCE §3): the `#` is a `::before`
    # generated-content glyph, not a DOM text node — confirmed live that Chromium's own
    # `element.innerText`/`textContent` do NOT include `::before` content (both returned bare
    # "retro" here even though the glyph paints on screen), so asserting against `inner_text()`
    # would be asserting a false thing about a DOM API this feature was never built to satisfy.
    # The correct, still-DOM-only proof of "renders as #retro": the element's own text node is
    # exactly "retro" (bare, no hash baked into markup — the stored/testable value) AND its
    # `::before` computed `content` is the `#` glyph immediately before it.
    chip_info = chip.evaluate(
        "el => ({ text: el.textContent.trim(), before: getComputedStyle(el, '::before').content })"
    )
    assert chip_info["text"] == "retro", f"chip's own text node should be bare 'retro', got {chip_info['text']!r}"
    assert chip_info["before"] == '"#"', (
        f"chip's ::before generated content should render the '#' glyph, got {chip_info['before']!r}"
    )
    assert chip.get_attribute("data-tag") == "retro", "stored tag must be bare 'retro', not '#retro'"

    n3 = len(session.request_log)
    chip.click()
    session.page.wait_for_selector(SEARCH_ROWS, timeout=5000)
    tag_requests = _search_requests(session.request_log[n3:])
    assert len(tag_requests) == 1, f"expected exactly 1 request for the tag click, got {len(tag_requests)}"
    assert "tag=retro" in tag_requests[0]["url"], f"unexpected url: {tag_requests[0]['url']}"

    retro_result_ids = set(
        session.page.locator(SEARCH_ROWS).evaluate_all(
            "els => els.map(el => el.getAttribute('data-goal-id'))"
        )
    )
    assert retro_result_ids == SYNRET_IDS, f"expected exactly {SYNRET_IDS}, got {retro_result_ids}"

    # Neither result is native to the current board — and under R10 revised (KK ruling
    # 2026-08-16) the pinned board date is a time-traveled request, so the overdue rows no
    # longer project as ghosts either: search finds them, the board shows them nowhere at all.
    board_retro = session.page.locator(
        '[data-vertical] [data-goal-id]'
    ).evaluate_all(
        "els => els.map(el => el.dataset.goalId).filter(id => ['SYNRET01','SYNRET02'].includes(id))"
    )
    assert board_retro == []

    assert session.dialog_records() == [], (
        f"a browser dialog opened after the tag click: {session.dialog_records()}"
    )
    assert urlsplit(session.page.url).path == "/search/%23retro"

    # --- 3: press Escape — restores the unfiltered board -----------------------------------------
    search_input.click()  # focus must be inside the field for the bubbled keydown.esc to fire
    search_input.press("Escape")
    session.page.wait_for_selector(SEARCH_MODAL, state="detached", timeout=5000)
    assert session.page.locator(SEARCH_BACKDROP).count() == 0, "search backdrop still open after Escape"
    assert search_trigger.evaluate("el => el === document.activeElement"), (
        "Escape did not restore focus to the search trigger"
    )
    # The board itself was never touched by search/filter (client-side state only) — confirm its
    # census is still F2's full unfiltered shape by spot-checking a few real board columns.
    # 10 natives — R10 revised (KK ruling 2026-08-16): the pinned board date is time-traveled,
    # so F2's two former day ghosts no longer render.
    assert session.page.locator('[data-vertical="day"] .card-stack > [data-goal-id]').count() == 10, (
        "day column card count changed after Escape — the board was not left unfiltered"
    )

    assert session.dialog_records() == [], (
        f"a browser dialog opened on Escape: {session.dialog_records()}"
    )
    assert session.page.url == url_before, "Escape changed page.url()"

    # --- S-114's browser half: same-origin only, zero foreign Origin headers, zero CORS mentions ---
    for r in session.request_log:
        origin_header = r["headers"].get("origin")
        if origin_header is not None:
            assert origin_header.rstrip("/") == own_origin.rstrip("/"), (
                f"request to {r['url']} carried a foreign Origin header: {origin_header!r}"
            )
    cors_mentions = [line for line in session.console_errors if "cors" in line.lower()]
    assert cors_mentions == [], f"console error(s) mention CORS: {cors_mentions}"
