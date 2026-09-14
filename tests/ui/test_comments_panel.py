"""docs/COMMENTS_SPEC.md WP-B, reworked WP-B2 (KK ruling 2026-08-25, docs/parity/DECISIONS.md
D255) — the comments sidebar, through Chromium, live HTTP, and real Postgres. WP-A (backend,
`verticals/core/comments.py` / `api/routes_comments.py`, commit 46fa17b) is already on `main`; this
suite exercises the frontend built against it: opening the panel from the icon, a whole-card round
trip, an anchored quote showing a highlight and clicking through it, a reply round trip, resolve
collapsing a thread, and the doc-side mirror of the whole-card round trip.

WP-B2 turned the panel from a block rendered inline inside the card/doc it comments on into a
single viewport-docked overlay (`App.vue`'s own mount) — every test that opens the panel now also
calls `_assert_docked_overlay` (this module's own helper) to prove it: structurally NOT a
descendant of the goal card / doc pane, and geometrically `position: fixed`, flush right, full
height, `--inspector-w` wide. `test_reply_round_trip` additionally guards the real bug this move
surfaced — a click landing inside the panel, now DOM-outside `[data-goal-id]`, must not read as
"outside the card" and collapse it (`GoalDetail.vue::onInlinePointerDown`'s exclusion list).

`ui_f2` (F2, owner t1) throughout, same convention `test_docs_view.py` uses — the `comment_threads`/
`comment_messages` tables are empty on every fresh clone (migration 015 seeds nothing), so every
test creates its own goal/doc (and, where a scenario needs a pre-existing thread rather than one
created through the UI, seeds it directly via `verticals.core.comments`, the same "seed via core,
assert via UI+HTTP" shape `test_docs_view.py`'s own module docstring states)."""

from __future__ import annotations

from datetime import date

import httpx
import psycopg
from playwright.sync_api import Page, expect

from verticals.core import comments as core_comments, docs as core_docs, goals as core_goals
from tests.ui.conftest import UiSession

ANCHOR = date(2026, 8, 8)  # the pinned clock date (tests/ui/conftest.py PINNED_CLOCK_ISO)


def _create_goal(conn: psycopg.Connection, title: str, body: str = "") -> str:
    return core_goals.create(
        conn, owner="t1", title=title, vertical="day", anchor_date=ANCHOR, body=body,
    ).goal.id


def _create_doc(conn: psycopg.Connection, path: str, title: str | None = None, body: str = "") -> str:
    return core_docs.create(conn, owner="t1", path=path, title=title, body=body).doc.id


def _seed_thread(
    conn: psycopg.Connection, *, goal_id: str | None = None, doc_id: str | None = None,
    body: str = "seed comment", author: str = "human", anchor: dict | None = None,
) -> str:
    return core_comments.create_thread(
        conn, owner="t1", goal_id=goal_id, doc_id=doc_id, body=body, author=author, anchor=anchor,
    ).thread.id


def _api_goal_comments(session: UiSession, goal_id: str) -> dict:
    resp = httpx.get(
        f"{session.backend.base_url}/api/goals/{goal_id}/comments",
        headers={"Authorization": f"Bearer {session.backend.token}"}, timeout=10,
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def _api_doc_comments(session: UiSession, doc_id: str) -> dict:
    resp = httpx.get(
        f"{session.backend.base_url}/api/docs/{doc_id}/comments",
        headers={"Authorization": f"Bearer {session.backend.token}"}, timeout=10,
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def _open_goal(page: Page, goal_id: str) -> None:
    card_row = page.locator(f'[data-goal-id="{goal_id}"] > .goal-card__row .goal-card__title')
    expect(card_row).to_be_visible(timeout=10000)
    card_row.click()
    expect(page.locator(f'[data-goal-id="{goal_id}"].goal-card--detail-open')).to_be_visible()


def _open_docs_and_doc(session: UiSession, doc_id: str) -> None:
    page = session.page
    page.click('[data-nav-item="docs"]')
    page.wait_for_selector('[data-cap="docs"]', timeout=5000)
    page.click(f'[data-doc-id="{doc_id}"]')
    expect(page.locator('[data-role="doc-path"]')).to_be_visible(timeout=10000)


def _assert_docked_overlay(page: Page, panel, host_selector: str) -> None:
    """WP-B2 (KK ruling 2026-08-25, docs/parity/DECISIONS.md D255): the panel must be a real
    viewport-docked sidebar OVERLAY, not a block laid out inside whatever surface opened it — KK's
    own complaint on the card, verbatim: "why did you put it INSIDE of the fucking card instead?"
    Two independent checks, either of which alone could pass by accident: (1) structural — the
    panel is not a DOM descendant of `host_selector` (the goal card / doc detail pane it comments
    on), proving it is the ONE app-level instance (`App.vue`), not a per-surface copy; (2)
    geometric — `position: fixed`, flush against the viewport's right edge, spanning full height,
    width equal to the kit's own `--inspector-w` token WP-B already used for this width class. A
    tiny (1px) tolerance absorbs subpixel rounding, nothing else — this is not a "roughly on the
    right side" check."""
    assert page.locator(f'{host_selector} [data-role="comments-panel"]').count() == 0, (
        "comments panel is nested inside the host surface — must be the one app-level overlay"
    )
    assert panel.evaluate("el => getComputedStyle(el).position") == "fixed"
    viewport = page.viewport_size
    assert viewport is not None
    box = panel.bounding_box()
    assert box is not None
    assert abs((box["x"] + box["width"]) - viewport["width"]) <= 1, (
        f"panel's right edge {box['x'] + box['width']} is not flush with viewport width {viewport['width']}"
    )
    assert abs(box["y"]) <= 1, f"panel does not start at the viewport top: y={box['y']}"
    assert abs(box["height"] - viewport["height"]) <= 1, (
        f"panel height {box['height']} does not span the full viewport height {viewport['height']}"
    )
    inspector_w = page.evaluate(
        "() => parseFloat(getComputedStyle(document.documentElement).getPropertyValue('--inspector-w'))"
    )
    assert abs(box["width"] - inspector_w) <= 1, (
        f"panel width {box['width']} does not match --inspector-w ({inspector_w})"
    )


def _select_phrase(page: Page, container_selector: str, phrase: str) -> None:
    """Selects `phrase` (a real, non-empty `window.getSelection()`) inside `container_selector`,
    then dispatches a real `mouseup` on the container — the same event
    `commentAnchoring.ts::onBodyMouseUp` is bound to (`@mouseup`, `GoalDetail.vue`/`DocDetail.vue`'s
    own template), so the app's real listener runs and reads the real Selection object, exactly as
    it would after a live drag.

    A live pixel-coordinate drag (`page.mouse.down`/`move`/`up` across the phrase's own measured
    bounding box) was the first approach and was dropped after two rounds of measured flakiness on
    this machine: (1) starting/ending the drag exactly on the phrase's own edge pixel occasionally
    snapped the selection boundary to the wrong side of the boundary glyph (`" important quoted
    phra"` — a leading space AND a dropped trailing letter, both edges off by one in opposite
    directions), and (2) nudging 2px outside the phrase's own box (into the deliberate surrounding
    whitespace every caller's body text carries) produced the SAME off-by-one pattern rather than
    fixing it — evidence the flakiness was not simply "too close to the boundary" but something
    about synthetic pointer-drag timing on this box specifically. `setBaseAndExtent` sidesteps the
    whole class of problem: it is the same Selection API the browser's own drag-selection ends up
    calling internally, called directly and deterministically, and — critically — it does not test
    or depend on Chromium's own drag-selection pixel math at all, which was never the thing this
    scenario needs to prove; `commentAnchoring.ts`'s own reaction to a real Selection object is."""
    page.evaluate(
        """({sel, phrase}) => {
             const container = document.querySelector(sel)
             const walker = document.createTreeWalker(container, NodeFilter.SHOW_TEXT)
             let node
             while ((node = walker.nextNode())) {
               const idx = node.textContent.indexOf(phrase)
               if (idx !== -1) {
                 window.getSelection().setBaseAndExtent(node, idx, node, idx + phrase.length)
                 container.dispatchEvent(new MouseEvent('mouseup', { bubbles: true, cancelable: true }))
                 return
               }
             }
             throw new Error(`phrase not found under ${sel}: ${phrase}`)
           }""",
        {"sel": container_selector, "phrase": phrase},
    )


# --- open panel from the icon --------------------------------------------------------------------


def test_open_comments_panel_from_icon(ui_f2: UiSession) -> None:
    session = ui_f2
    page = session.page
    with psycopg.connect(session.backend.dsn, autocommit=True) as conn:
        goal_id = _create_goal(conn, "SYN comments icon goal")

    page.reload()
    _open_goal(page, goal_id)

    icon = page.locator(f'[data-goal-id="{goal_id}"] [data-cap="open-comments"]')
    expect(icon).to_be_visible(timeout=10000)
    assert icon.get_attribute("aria-expanded") == "false"
    expect(page.locator('[data-role="comments-panel"]')).to_have_count(0)

    icon.click()
    panel = page.locator('[data-role="comments-panel"]')
    expect(panel).to_be_visible(timeout=10000)
    expect(panel.locator('[data-role="comments-new"]')).to_be_visible()
    assert icon.get_attribute("aria-expanded") == "true"
    _assert_docked_overlay(page, panel, f'[data-goal-id="{goal_id}"]')

    icon.click()
    expect(panel).to_have_count(0)
    assert icon.get_attribute("aria-expanded") == "false"


# --- whole-card comment round trip ----------------------------------------------------------------


def test_whole_card_comment_round_trip(ui_f2: UiSession) -> None:
    session = ui_f2
    page = session.page
    with psycopg.connect(session.backend.dsn, autocommit=True) as conn:
        goal_id = _create_goal(conn, "SYN whole-card comment goal")

    page.reload()
    _open_goal(page, goal_id)
    page.locator(f'[data-goal-id="{goal_id}"] [data-cap="open-comments"]').click()

    panel = page.locator('[data-role="comments-panel"]')
    expect(panel).to_be_visible(timeout=10000)
    expect(panel.locator('[data-role="comments-empty"]')).to_be_visible()
    _assert_docked_overlay(page, panel, f'[data-goal-id="{goal_id}"]')

    composer = panel.locator('[data-role="comments-new"]')
    composer.locator('.field__input').fill("SYN whole-card note")
    composer.locator('button.button--primary').click()

    row = panel.locator('[data-role="comment-thread-row"]')
    expect(row).to_have_count(1, timeout=10000)
    expect(row.locator('h3.t-title')).to_have_text("Whole card")
    expect(row.locator('.comment-msg')).to_have_text("SYN whole-card note")
    expect(panel.locator('[data-role="comments-empty"]')).to_have_count(0)

    badge = page.locator(f'[data-goal-id="{goal_id}"] [data-role="comments-badge"]')
    expect(badge).to_have_text("1")

    server = _api_goal_comments(session, goal_id)
    assert len(server["threads"]) == 1
    assert server["threads"][0]["anchor"] is None
    assert server["threads"][0]["messages"][0]["body"] == "SYN whole-card note"
    assert server["threads"][0]["messages"][0]["author"] == "human"


# --- anchored comment: highlight appears, click-through focuses the thread ------------------------


def test_anchored_comment_shows_highlight_and_click_through(ui_f2: UiSession) -> None:
    session = ui_f2
    page = session.page
    quote = "important quoted phrase"
    with psycopg.connect(session.backend.dsn, autocommit=True) as conn:
        goal_id = _create_goal(
            conn, "SYN anchored comment goal", body=f"before the {quote} here after",
        )

    page.reload()
    _open_goal(page, goal_id)
    body_selector = f'[data-goal-id="{goal_id}"] [data-cap="edit-body"]'
    expect(page.locator(body_selector)).to_contain_text(quote, timeout=10000)

    _select_phrase(page, body_selector, quote)
    sel_text = page.evaluate("() => window.getSelection().toString()")
    assert sel_text == quote, f"selection produced {sel_text!r}, expected {quote!r}"

    affordance = page.locator('[data-cap="comment-selection"]')
    expect(affordance).to_be_visible(timeout=5000)
    affordance.click()

    panel = page.locator('[data-role="comments-panel"]')
    expect(panel).to_be_visible(timeout=10000)
    _assert_docked_overlay(page, panel, f'[data-goal-id="{goal_id}"]')
    pending = panel.locator('[data-role="comments-pending-anchor"]')
    expect(pending).to_be_visible(timeout=5000)
    expect(pending.locator('.comments-panel__anchor-quote')).to_have_text(f'“{quote}”')

    composer = panel.locator('[data-role="comments-new"]')
    composer.locator('.field__input').fill("SYN anchored note")
    composer.locator('button.button--primary').click()

    row = panel.locator('[data-role="comment-thread-row"]')
    expect(row).to_have_count(1, timeout=10000)
    expect(row.locator('h3.t-title')).to_have_text(quote)

    server = _api_goal_comments(session, goal_id)
    assert server["threads"][0]["anchor"]["quote"] == quote

    highlight = page.locator(f'{body_selector} mark.comment-highlight')
    expect(highlight).to_be_visible(timeout=10000)
    expect(highlight).to_have_text(quote)

    # Close the panel, then click the highlight — it must reopen the panel on this thread.
    page.locator(f'[data-goal-id="{goal_id}"] [data-cap="open-comments"]').click()
    expect(panel).to_have_count(0)

    highlight.click()
    expect(panel).to_be_visible(timeout=10000)
    expect(panel.locator('[data-role="comment-thread-row"]')).to_have_count(1)
    # The highlight click-through is the OTHER path into the panel (icon click is the first) — KK's
    # own sketch names both ("Click opens a sidebar panel... clicking a highlight focuses its
    # thread"), so both must land on the same docked overlay, not just the icon's own path.
    _assert_docked_overlay(page, panel, f'[data-goal-id="{goal_id}"]')


# --- reply round trip --------------------------------------------------------------------------


def test_reply_round_trip(ui_f2: UiSession) -> None:
    session = ui_f2
    page = session.page
    with psycopg.connect(session.backend.dsn, autocommit=True) as conn:
        goal_id = _create_goal(conn, "SYN reply goal")
        thread_id = _seed_thread(conn, goal_id=goal_id, body="first message")

    page.reload()
    _open_goal(page, goal_id)
    page.locator(f'[data-goal-id="{goal_id}"] [data-cap="open-comments"]').click()

    panel = page.locator('[data-role="comments-panel"]')
    _assert_docked_overlay(page, panel, f'[data-goal-id="{goal_id}"]')
    row = panel.locator(f'[data-role="comment-thread-row"][data-thread-id="{thread_id}"]')
    expect(row).to_be_visible(timeout=10000)
    expect(row.locator('.comment-msg')).to_have_count(1)

    # Regression check for the outside-pointerdown fix this rework needed (GoalDetail.vue's
    # onInlinePointerDown): a real click (real `pointerdown`) landing in the panel — which is now
    # OUTSIDE `[data-goal-id]` in the DOM — must not read as "outside" and collapse the card.
    reply_input = row.locator('[data-role="comment-reply-input"]')
    reply_input.click()
    expect(page.locator(f'[data-goal-id="{goal_id}"].goal-card--detail-open')).to_be_visible()
    reply_input.fill("a reply from the panel")
    reply_input.press("Enter")

    expect(row.locator('.comment-msg')).to_have_count(2, timeout=10000)
    expect(row.locator('.comment-msg').nth(1)).to_have_text("a reply from the panel")

    server = _api_goal_comments(session, goal_id)
    messages = server["threads"][0]["messages"]
    assert [m["body"] for m in messages] == ["first message", "a reply from the panel"]
    assert all(m["author"] == "human" for m in messages)


# --- resolve collapses -------------------------------------------------------------------------


def test_resolve_collapses_and_unresolve_reopens(ui_f2: UiSession) -> None:
    session = ui_f2
    page = session.page
    with psycopg.connect(session.backend.dsn, autocommit=True) as conn:
        goal_id = _create_goal(conn, "SYN resolve goal")
        thread_id = _seed_thread(conn, goal_id=goal_id, body="please resolve me")

    page.reload()
    _open_goal(page, goal_id)
    page.locator(f'[data-goal-id="{goal_id}"] [data-cap="open-comments"]').click()

    panel = page.locator('[data-role="comments-panel"]')
    _assert_docked_overlay(page, panel, f'[data-goal-id="{goal_id}"]')
    row = panel.locator(f'[data-role="comment-thread-row"][data-thread-id="{thread_id}"]')
    expect(row).to_be_visible(timeout=10000)

    thread_card = row.locator('[data-role="comment-thread"]')
    assert thread_card.get_attribute("data-resolved") is None
    expect(thread_card.locator('.comment-msg')).to_be_visible()

    toggle = row.locator('[data-role="comment-resolve-toggle"]')
    expect(toggle).to_have_text("Resolve")
    toggle.click()

    expect(thread_card).to_have_attribute("data-resolved", "true", timeout=10000)
    # The kit's own CSS (`.comment-thread[data-resolved="true"] .card__collapsible{display:none}`)
    # is what does the collapsing — asserted here as "no longer visible", not "removed", since the
    # message is still in the DOM, just hidden.
    expect(thread_card.locator('.comment-msg')).to_be_hidden()
    expect(toggle).to_have_text("Unresolve")

    server = _api_goal_comments(session, goal_id)
    assert server["threads"][0]["resolved_at"] is not None

    toggle.click()
    expect(thread_card).not_to_have_attribute("data-resolved", "true", timeout=10000)
    expect(thread_card.locator('.comment-msg')).to_be_visible()
    expect(toggle).to_have_text("Resolve")

    server = _api_goal_comments(session, goal_id)
    assert server["threads"][0]["resolved_at"] is None


# --- doc comment round trip ---------------------------------------------------------------------


def test_doc_comment_round_trip(ui_f2: UiSession) -> None:
    session = ui_f2
    page = session.page
    with psycopg.connect(session.backend.dsn, autocommit=True) as conn:
        doc_id = _create_doc(conn, "syn-comments/doc.md", title="SYN Doc Comments")

    page.reload()
    _open_docs_and_doc(session, doc_id)

    trigger = page.locator('[data-cap="open-comments"]')
    expect(trigger).to_be_visible(timeout=10000)
    trigger.click()

    panel = page.locator('[data-role="comments-panel"]')
    expect(panel).to_be_visible(timeout=10000)
    # WP-B2: the old `comments-panel--sidebar` layout variant (a right-hand column laid out INSIDE
    # `.doc-detail-layout`) is gone — there is only one panel shape now, the docked overlay, and it
    # is not a descendant of the doc pane it comments on.
    _assert_docked_overlay(page, panel, '[data-role="doc-detail"]')

    composer = panel.locator('[data-role="comments-new"]')
    composer.locator('.field__input').fill("SYN doc note")
    composer.locator('button.button--primary').click()

    row = panel.locator('[data-role="comment-thread-row"]')
    expect(row).to_have_count(1, timeout=10000)
    expect(row.locator('h3.t-title')).to_have_text("Whole document")
    expect(row.locator('.comment-msg')).to_have_text("SYN doc note")

    badge = page.locator('[data-role="comments-badge"]')
    expect(badge).to_have_text("1")

    server = _api_doc_comments(session, doc_id)
    assert len(server["threads"]) == 1
    assert server["threads"][0]["doc_id"] == doc_id
    assert server["threads"][0]["anchor"] is None
    assert server["threads"][0]["messages"][0]["body"] == "SYN doc note"
