"""The app's views, reached the way a person reaches them since the bottom bar became one field ("filter board from
one field", 3bc40f9): Inbox and Docs are commands in "Find, filter or ask". The empty field, focused, offers them;
taking one shows that view, and removing its token goes back to the board. The `[data-nav-item]` links are gone.

A view entered another way (a document opened from a goal, an address with `#inbox` or `#doc/...`) puts no token in
the field, so a scenario that left the board that way comes back with the browser's back, as a person would."""

from __future__ import annotations

import re

from playwright.sync_api import Page, expect

FIELD = 'input[aria-label="Find, filter or ask"]'
VIEW_TOKEN = re.compile(r"^(Inbox|Docs)\b")
MARK = {"inbox": '[data-cap="inbox"]', "docs": '[data-cap="docs"]', "verticals": ".pattern-vertical-board"}


def switch_view(page: Page, view: str) -> None:
    """`inbox` or `docs` from the command field's suggestions; `verticals` by removing the view's token."""
    if view == "verticals":
        page.locator(".command-field__token", has_text=VIEW_TOKEN).first.click()
    else:
        page.locator(FIELD).click()
        page.locator(f'.command-field__suggestions [data-token="{view}"]').click()
    expect(page.locator(MARK[view]).first).to_be_visible(timeout=10000)


def expect_view(page: Page, view: str) -> None:
    """The view on screen: its own surface, and no other view's."""
    expect(page.locator(MARK[view]).first).to_be_visible(timeout=10000)
    for other, mark in MARK.items():
        if other != view:
            expect(page.locator(mark)).to_have_count(0)
