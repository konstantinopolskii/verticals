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
