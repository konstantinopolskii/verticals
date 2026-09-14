"""S-72 — Markdown body renders, and does not execute.

`docs/E2E.md` §6, S-72 (line 1724). Required by AC-116; the stored-raw half is AC-185.

    Steps: 1. Over HTTP, set `SYNSCH04.body` to
    `**bold** [link](https://example.com) <img src=x onerror="window.__pwned=1">
    <script>window.__pwned=2</script>` followed by four more links:
    `[a](javascript:window.__pwned=3)`, `[b](data:text/html,<script>window.__pwned=4</script>)`,
    `[c](vbscript:msgbox)`, `[d](HtTpS://example.com/ok)`.
    2. Open the detail surface. 3. Click **every** rendered `<a>`.

"Does not execute" is asserted on observed effect, never on the absence of a substring: the four
payloads each set a *distinct* `window.__pwned` value, so a passing run proves none of the four
paths fired, and a failing one names which. `window.__pwned` is read out of the page after every
single click, not once at the end — one read at the end cannot tell "nothing ran" from "something
ran and something else overwrote it".

Three separate execution surfaces are covered:
  * the `<img onerror=…>` — would fire on *render*, before any click, if the body reached the DOM
    as markup at all. Zero `<img>` elements under the body is the structural half; `__pwned`
    still undefined after the surface opens is the observable half.
  * the raw `<script>` — same, and additionally checked as zero `<script>` elements under the
    body (scoped to the body: `index.html` legitimately carries the module script that boots the
    app, so a document-wide `<script>` count would be asserting the wrong thing).
  * `javascript:` / `data:` / `vbscript:` hrefs — these need the click, which is why step 3 exists.
    The allowlist rule (E2E.md S-72: an allowlist of `http`, `https`, `mailto`, not a blocklist)
    is asserted both ways: `HtTpS` survives (case-insensitive match) and each refused scheme
    renders as literal text carrying **no** `href` at all — "a dead `href="#"` still steals the
    click".

Popups: every surviving link carries `target="_blank"`, so each click opens a real browser tab
that then tries to reach `example.com`. Those tabs are closed as they appear (`context.on("page")`
below). Their requests belong to *their* page, not to the session's, so the suite's own
zero-failed-request teardown assertion is unaffected — nothing here deliberately fails a request
on the page under test.
"""

from __future__ import annotations

import psycopg
from playwright.sync_api import Page, expect

from tests.ui.conftest import UiSession, activate_column

TARGET = "SYNSCH04"

# Verbatim from the scenario text, joined into the single paragraph the scenario describes
# ("followed by four more links"). Byte-identical round-tripping through Postgres is asserted
# against this exact string.
BODY = (
    '**bold** [link](https://example.com) <img src=x onerror="window.__pwned=1"> '
    "<script>window.__pwned=2</script> "
    "[a](javascript:window.__pwned=3) "
    "[b](data:text/html,<script>window.__pwned=4</script>) "
    "[c](vbscript:msgbox) "
    "[d](HtTpS://example.com/ok)"
)

# The two hrefs the allowlist must let through, and nothing else. `HtTpS` keeps its original
# casing in the rendered href — the scheme check lowercases a copy for the comparison, it does
# not rewrite the URL.
EXPECTED_HREFS = ["https://example.com", "HtTpS://example.com/ok"]

# The three refused links, each of which must appear as its own literal `[label](scheme:…)` text
# span inside the body — nothing swallowed, nothing turned into an anchor.
REFUSED_LITERALS = [
    "[a](javascript:window.__pwned=3)",
    "[b](data:text/html,<script>window.__pwned=4</script>)",
    "[c](vbscript:msgbox)",
]

ALLOWED_SCHEMES = ("http:", "https:", "mailto:")

CARD_TITLE = f'[data-goal-id="{TARGET}"] > .goal-card__row .goal-card__title'
DETAIL_BODY = ".goal-detail__body"


def _pwned(page: Page) -> object:
    """`window.__pwned` as seen right now. `undefined` marshals to `None` through Playwright, so
    the returned value is compared against `None` — a payload that fired would return 1, 2, 3 or
    4 and name itself in the failure message."""
    return page.evaluate("window.__pwned === undefined ? null : window.__pwned")


def test_s72_markdown_renders_and_does_not_execute(ui_f2: UiSession) -> None:
    session = ui_f2
    page = session.page

    # Every `target="_blank"` click opens a real tab; close each one as it appears so a scenario
    # with six clicks does not leave six live tabs behind for the context teardown to reap.
    popups: list[Page] = []
    session.context.on("page", lambda p: popups.append(p))

    conn = psycopg.connect(session.backend.dsn, autocommit=True)
    try:
        # --- step 1: set the body over HTTP ---------------------------------------------------
        res = page.request.patch(
            f"{session.base_url}/api/goals/{TARGET}",
            headers={
                "Authorization": f"Bearer {session.backend.token}",
                "Content-Type": "application/json",
            },
            data={"body": BODY},
        )
        assert res.status == 200, f"PATCH body failed: {res.status} {res.text()}"

        # --- assert: stored raw, byte-identical (§4 "sanitize on render, not on write") -------
        (stored,) = conn.execute("SELECT body FROM goals WHERE id = %s", (TARGET,)).fetchone()
        assert stored == BODY, (
            "the stored body is not byte-identical to what was sent — something sanitised on "
            f"write:\n  sent  {BODY!r}\n  read  {stored!r}"
        )

        # --- step 2: open the detail surface --------------------------------------------------
        page.reload()
        activate_column(page, "month")
        page.click(CARD_TITLE)
        body_el = page.locator(DETAIL_BODY)
        expect(body_el).to_be_visible()

        # An `onerror`/`<script>` payload that reached the DOM as markup would already have run by
        # now, before a single click.
        assert _pwned(page) is None, (
            f"a payload executed on render alone: window.__pwned == {_pwned(page)!r}"
        )

        # --- assert: renders ------------------------------------------------------------------
        assert body_el.locator("strong").count() == 1, "the `**bold**` run did not render a <strong>"
        assert body_el.locator("strong").inner_text() == "bold"

        # --- assert: no markup smuggled in ----------------------------------------------------
        assert body_el.locator("script").count() == 0, "a <script> element rendered inside the body"
        assert body_el.locator("img").count() == 0, "an <img> element rendered inside the body"
        # The raw-HTML payloads survive as *text*, which is what "renders and does not execute"
        # means for them — silently dropping them would also pass the two counts above.
        body_text = body_el.inner_text()
        for literal in ('<img src=x onerror="window.__pwned=1">', "<script>window.__pwned=2</script>"):
            assert literal in body_text, f"the raw-HTML payload vanished instead of rendering as text: {literal!r}"

        # --- assert: the scheme allowlist -----------------------------------------------------
        anchors = body_el.locator("a")
        count = anchors.count()
        hrefs = [anchors.nth(i).get_attribute("href") for i in range(count)]
        assert hrefs == EXPECTED_HREFS, (
            f"exactly the http/https links may become anchors; got {hrefs!r}, expected {EXPECTED_HREFS!r}"
        )
        for i in range(count):
            a = anchors.nth(i)
            href = a.get_attribute("href") or ""
            assert href.lower().startswith(ALLOWED_SCHEMES), (
                f"rendered anchor carries a non-allowlisted scheme: {href!r}"
            )
            assert a.get_attribute("rel") == "noopener noreferrer", (
                f"anchor {href!r} is missing rel=\"noopener noreferrer\" — window.opener is a real "
                f"handle to the board"
            )
            assert a.get_attribute("target") == "_blank", f"anchor {href!r} is missing target=\"_blank\""
        for literal in REFUSED_LITERALS:
            assert literal in body_text, (
                f"a refused-scheme link must render as literal text, nothing lost: {literal!r}"
            )

        # --- step 3: click every rendered <a> -------------------------------------------------
        # Including the surviving ones: an anchor is only inert if clicking it does nothing to
        # this page. `no_wait_after` keeps the click from blocking on the popup's own navigation
        # to a host this machine may not be able to reach.
        for i in range(count):
            href = hrefs[i]
            anchors.nth(i).click(no_wait_after=True)
            page.wait_for_timeout(50)
            assert _pwned(page) is None, (
                f"clicking the rendered link {href!r} executed a payload: window.__pwned == "
                f"{_pwned(page)!r}"
            )
            assert page.url.startswith(session.base_url), (
                f"clicking {href!r} navigated the page under test away to {page.url!r}"
            )

        # The refused links are text, not anchors — there is nothing to click, and that is the
        # assertion: `anchors` above already enumerated every clickable thing in the body.
        assert body_el.locator("a").count() == len(EXPECTED_HREFS), (
            "the anchor set changed while clicking through it"
        )
        assert _pwned(page) is None, f"window.__pwned is set at the end of the run: {_pwned(page)!r}"
    finally:
        for p in popups:
            if not p.is_closed():
                p.close()
        conn.close()
