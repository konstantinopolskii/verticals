"""The app's views, reached the way a person reaches them since the field became the circle (docs/design-handoff S1.P2,
S2.P2): pointed at, the circle shows its tags; the docs tag opens Docs, the Inbox tag the Inbox, and a view's own tag
pressed again goes back to the board.

A view entered another way (a document opened from a goal, an address with `#inbox` or `#doc/...`) comes back the same
way, or with the browser's back, as a person would."""

from __future__ import annotations

from playwright.sync_api import Page, expect

FIELD = '[data-cap="search-input"] textarea'
CIRCLE = ".circle-field__shape"
MARK = {"inbox": '[data-cap="inbox"]', "docs": '[data-cap="docs"]', "verticals": ".pattern-vertical-board"}


def show_tags(page: Page) -> None:
    """Point at the circle: the field opens and its tags come in."""
    page.locator(CIRCLE).hover()
    expect(page.locator(".circle-tags.is-shown")).to_have_count(1)


def switch_view(page: Page, view: str) -> None:
    """`inbox` or `docs` from its tag; `verticals` by pressing the tag of the view on screen again."""
    show_tags(page)
    if view == "verticals":
        page.locator('.circle-tag[aria-pressed="true"]').click()
    else:
        page.locator(f'.circle-tag[data-tag="{view}"]').click()
    expect(page.locator(MARK[view]).first).to_be_visible(timeout=10000)


def expect_view(page: Page, view: str) -> None:
    """The view on screen: its own surface, and no other view's."""
    expect(page.locator(MARK[view]).first).to_be_visible(timeout=10000)
    for other, mark in MARK.items():
        if other != view:
            expect(page.locator(mark)).to_have_count(0)


def tick(page: Page) -> None:
    """A second passes on the pinned clock (`conftest.PINNED_CLOCK_ISO`). Vue drops an event stamped no later than the
    moment its handler was attached, and the pinned clock never moves: a click inside something just mounted, under a
    listener that stamps the click first (a window's own click capture, WindowStack.vue), would be dropped. A person's
    click always comes later than what they click on."""
    page.clock.set_fixed_time(page.evaluate("Date.now()") / 1000 + 1)


def open_page(page: Page, doc_id: str) -> None:
    """A document from the Documents desk, as a person opens it (Inbox and Documents redesign, rounds 2 and 7): the
    stack holding it laid out over the desk, then its page, which opens as a window (S3.P4). Documents must be on
    screen."""
    stacks = page.locator("[data-stack]")
    expect(stacks.first).to_be_visible(timeout=10000)
    laid_out = page.locator('[data-role="docs-open"]')
    sheet = laid_out.locator(f'[data-doc-id="{doc_id}"]')

    def open_sheet() -> None:
        sheet.click()
        expect(page.locator('[data-role="doc-window"] [data-role="doc-detail"]')).to_be_visible(timeout=10000)
        tick(page)

    def put_back() -> None:
        # As a person does: a click on the laid-out stack's heading (DocsDesk.vue's `@click.self`).
        laid_out.locator(".docs-open__head").click(position={"x": 1, "y": 1})
        expect(laid_out).to_have_count(0)

    # A stack stays laid out after one of its pages was opened and closed.
    if laid_out.count():
        if sheet.count():
            open_sheet()
            return
        put_back()
    for key in stacks.evaluate_all("els => els.map(el => el.dataset.stack)"):
        page.locator(f'[data-stack="{key}"]').click()
        expect(laid_out).to_be_visible()
        if sheet.count():
            open_sheet()
            return
        put_back()
    raise AssertionError(f"document {doc_id} lies in no stack on the desk")
