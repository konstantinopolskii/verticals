"""Esc peels one layer a press, down to the board (App.tsx `escapeStep`): a window over a desk, then on Documents a
document's history, the document itself, a laid-out stack, and last the desk, Inbox or Documents, back to the board.
Before, Esc on a desk with nothing smaller open did nothing: only the desk's × and the view's tag went back."""

from __future__ import annotations

import psycopg
from playwright.sync_api import Page, expect

from verticals.core import docs as core_docs
from tests.ui.conftest import UiSession
from tests.ui.views import expect_view, open_page, switch_view

LAID_OUT = '[data-role="docs-open"]'
WINDOW = '[data-role="doc-window"]'
DESK = '[data-role="docs-desk"]'
BACK = '[data-role="docs-back"]'


def _seed(session: UiSession) -> str:
    with psycopg.connect(session.backend.dsn, autocommit=True) as conn:
        doc_id = core_docs.create(conn, owner="t1", path="syn-esc/notes.md", title="SYN Esc", body="SYN a few words.").doc.id
        core_docs.save(conn, owner="t1", id=doc_id, expected_revision=1, body="SYN a few words. Edited.")
    return doc_id


def _esc(page: Page) -> None:
    page.keyboard.press("Escape")


def test_esc_on_the_inbox_goes_back_to_the_board(ui_f2: UiSession) -> None:
    page = ui_f2.page
    page.reload()
    switch_view(page, "inbox")
    _esc(page)
    expect_view(page, "verticals")


def test_esc_on_documents_folds_the_stack_and_then_leaves_the_desk(ui_f2: UiSession) -> None:
    session = ui_f2
    page = session.page
    _seed(session)
    page.reload()
    switch_view(page, "docs")

    stacks = page.locator("[data-stack]")
    expect(stacks.first).to_be_visible(timeout=10000)
    stacks.first.click()
    expect(page.locator(LAID_OUT)).to_be_visible()

    _esc(page)  # the stack goes back; the desk stays
    expect(page.locator(LAID_OUT)).to_have_count(0)
    expect_view(page, "docs")

    _esc(page)  # nothing smaller is open: the desk closes
    expect_view(page, "verticals")


def test_esc_closes_a_document_window_before_the_desk(ui_f2: UiSession) -> None:
    session = ui_f2
    page = session.page
    doc_id = _seed(session)
    page.reload()
    switch_view(page, "docs")
    open_page(page, doc_id)

    _esc(page)  # the window goes; the stack it came from stays laid out
    expect(page.locator(WINDOW)).to_have_count(0)
    expect(page.locator(LAID_OUT)).to_be_visible()
    expect_view(page, "docs")

    _esc(page)
    expect(page.locator(LAID_OUT)).to_have_count(0)
    _esc(page)
    expect_view(page, "verticals")


def test_esc_on_a_document_opened_by_its_address_goes_back_to_the_desk_then_the_board(ui_f2: UiSession) -> None:
    session = ui_f2
    page = session.page
    doc_id = _seed(session)
    page.goto("about:blank")
    page.goto(f"{session.base_url}/#doc/{doc_id}")
    expect(page.locator('[data-cap="docs"] [data-role="doc-detail"]')).to_be_visible(timeout=10000)

    page.locator('[data-cap="docs"] [data-role="doc-history-trigger"]').click()
    expect(page.locator('[data-role="docs-history"]')).to_be_visible(timeout=10000)

    _esc(page)  # history closes; the document stays
    expect(page.locator('[data-role="docs-history"]')).to_have_count(0)
    expect(page.locator('[data-cap="docs"] [data-role="doc-detail"]')).to_be_visible()

    _esc(page)  # the document closes; the desk is back
    expect(page.locator(DESK)).to_be_visible(timeout=10000)
    expect(page.locator(BACK)).to_have_count(0)

    _esc(page)
    expect_view(page, "verticals")


def test_esc_while_naming_a_new_document_only_cancels_the_name(ui_f2: UiSession) -> None:
    page = ui_f2.page
    page.reload()
    switch_view(page, "docs")
    page.click('[data-role="docs-new-trigger"]')
    new_input = page.locator('[data-role="docs-new-input"]')
    new_input.wait_for(state="visible", timeout=5000)
    new_input.type("syn-esc/draft")

    _esc(page)  # the text being typed takes Esc: the name is dropped, the desk stays
    expect(new_input).to_have_count(0)
    expect_view(page, "docs")
