"""WP-C (KK, 2026-08-25, docs/parity/DECISIONS.md D256) — the Inbox opens on today's day-log
document, through Chromium, live HTTP, and real Postgres.

KK, verbatim: "In the INBOX SECTION from now on ABOVE the task list THERE SHOULD BE LIKE A
DOCUMENT OPENED BY DEFAULT, EXACTLY THE ONE THAT WE SAVE TO THE DOC SECTION AUTOMATICALLY. AND YOU
SIMPLY CAN OPEN INBOX AND WRITE THERE." `InboxDayDoc.vue` renders the day-log doc
(`inbox/YYYY-MM-DD.md`, `docs/COMMENTS_SPEC.md`'s own convention) above `InboxView.vue`'s existing
Maybe column — the SAME document `DocsView.vue`/`DocDetail.vue` show for that path, via the same
`lib/api.ts` doc endpoints.

Covers: the surface is open and editable the moment it loads (no click needed); typed text commits
into `inbox/YYYY-MM-DD.md` and is readable both through the API and through the Docs view (one
doc, two views, no copy); a pre-existing today-doc's content loads straight in; an empty day never
creates a doc row at all; the Maybe column underneath is untouched (still drags/adds/opens).

`ui_f2` (F2, owner t1) throughout, same convention `test_docs_view.py`/`test_comments_panel.py`
both use. The pinned clock (`tests/ui/conftest.py::PINNED_CLOCK_ISO`) is 2026-08-08T09:00:00+03:00,
so every scenario here reads "today" as 2026-08-08 — path `inbox/2026-08-08.md`, title
"8 August 2026" (`web/src/lib/dayDoc.ts::dayDocTitle`)."""

from __future__ import annotations

import httpx
import psycopg
from playwright.sync_api import expect

from verticals.core import docs as core_docs
from tests.harness.report import artifact
from tests.ui.conftest import ARTIFACTS_ROOT, REPO_ROOT, UiSession

TODAY_ISO = "2026-08-08"
TODAY_PATH = f"inbox/{TODAY_ISO}.md"
TODAY_TITLE = "8 August 2026"

DAY_DOC_BODY = '[data-role="inbox-day-doc-body"]'
DAY_DOC_TITLE = '[data-role="inbox-day-doc-title"]'
MAYBE_ADD = '[data-vertical="maybe"] [data-cap="create-goal"]'
MAYBE_EDITOR = f'{MAYBE_ADD} [data-role="column-add-editor"]'


def _open_inbox(session: UiSession) -> None:
    session.page.click('[data-nav-item="inbox"]')
    session.page.wait_for_selector('[data-cap="inbox"]', timeout=5000)


def _api_list_docs(session: UiSession) -> list[dict]:
    resp = httpx.get(
        f"{session.backend.base_url}/api/docs",
        headers={"Authorization": f"Bearer {session.backend.token}"}, timeout=10,
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["docs"]


def _api_get_doc(session: UiSession, doc_id: str) -> dict:
    resp = httpx.get(
        f"{session.backend.base_url}/api/docs/{doc_id}",
        headers={"Authorization": f"Bearer {session.backend.token}"}, timeout=10,
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def _find_today_doc(session: UiSession) -> dict | None:
    return next((d for d in _api_list_docs(session) if d["path"] == TODAY_PATH), None)


# --- surface is open and editable the moment it loads, no extra click ---------------------------


def test_inbox_shows_editable_day_doc_surface_by_default(ui_f2: UiSession) -> None:
    session = ui_f2
    page = session.page
    page.reload()
    _open_inbox(session)

    body = page.locator(DAY_DOC_BODY)
    body.wait_for(state="visible", timeout=10000)
    # No click anywhere on the surface before this check — KK's own "no extra click" bar.
    expect(body).to_have_attribute("contenteditable", "true", timeout=5000)
    expect(page.locator(DAY_DOC_TITLE)).to_have_text(TODAY_TITLE, timeout=5000)

    # Still an empty day at this point — nothing typed yet, nothing should exist server-side.
    assert _find_today_doc(session) is None, "opening Inbox alone must not create today's doc"


# --- typing + commit persists into inbox/YYYY-MM-DD.md, same doc the Docs view shows -------------


def test_typing_commits_into_shared_day_doc_and_maybe_list_still_works(ui_f2: UiSession, request) -> None:
    session = ui_f2
    page = session.page
    page.reload()
    _open_inbox(session)

    body = page.locator(DAY_DOC_BODY)
    body.wait_for(state="visible", timeout=10000)
    expect(body).to_have_attribute("contenteditable", "true", timeout=5000)

    note_text = "WP-C probe note — grocery run, call Sasha at 6"
    body.click()
    body.fill(note_text)
    # Commit without waiting on the debounce timer — blur flushes immediately, same as
    # DocDetail.vue's own body editor (`InboxDayDoc.vue::finishEdit`).
    page.locator(DAY_DOC_TITLE).click()

    saved = None
    for _ in range(20):
        saved = _find_today_doc(session)
        if saved is not None:
            break
        page.wait_for_timeout(250)
    assert saved is not None, "typed + committed text never created inbox/2026-08-08.md"
    assert saved["title"] == TODAY_TITLE

    full = _api_get_doc(session, saved["id"])
    assert note_text in full["body"], f"committed body missing the typed note: {full['body']!r}"

    # Same doc, no copy: the Docs view opens the identical row for the identical path.
    page.click('[data-nav-item="docs"]')
    page.wait_for_selector('[data-cap="docs"]', timeout=5000)
    page.click(f'[data-doc-id="{saved["id"]}"]')
    expect(page.locator('[data-role="doc-path"]')).to_have_text(TODAY_PATH, timeout=10000)
    expect(page.locator('[data-role="doc-body"]')).to_contain_text(note_text, timeout=10000)

    # --- Maybe list is untouched: still renders, still accepts an added card ---------------------
    page.click('[data-nav-item="inbox"]')
    page.wait_for_selector('[data-cap="inbox"]', timeout=5000)
    maybe_add = page.locator(MAYBE_ADD)
    expect(maybe_add).to_be_visible(timeout=5000)
    maybe_add.click()
    editor = page.locator(MAYBE_EDITOR)
    editor.wait_for(state="visible", timeout=5000)
    new_title = "WP-C maybe-still-works probe"
    editor.fill(new_title)
    editor.press("Enter")
    new_card = page.locator('[data-vertical="maybe"] .card-stack > [data-goal-id]', has_text=new_title)
    new_card.wait_for(state="visible", timeout=5000)

    # --- screenshot: day-doc surface (with text) above the Maybe list (task's own gate item 3) ----
    page.wait_for_timeout(200)  # let the just-added card settle before the capture
    shot_dir = ARTIFACTS_ROOT / "wp-c-inbox"
    shot_dir.mkdir(parents=True, exist_ok=True)
    shot_path = shot_dir / "inbox-day-doc.png"
    page.screenshot(path=str(shot_path))
    artifact(request, str(shot_path.relative_to(REPO_ROOT)))


# --- a pre-existing today-doc's content loads straight into the surface --------------------------


def test_preexisting_today_doc_content_loads_in_inbox(ui_f2: UiSession) -> None:
    session = ui_f2
    page = session.page
    existing_text = "Already on the books before Inbox ever opened"
    with psycopg.connect(session.backend.dsn, autocommit=True) as conn:
        core_docs.create(conn, owner="t1", path=TODAY_PATH, title=TODAY_TITLE, body=existing_text)

    page.reload()
    _open_inbox(session)

    body = page.locator(DAY_DOC_BODY)
    body.wait_for(state="visible", timeout=10000)
    expect(body).to_contain_text(existing_text, timeout=10000)
    expect(body).to_have_attribute("contenteditable", "true", timeout=5000)


# --- empty day: never creates a doc row ------------------------------------------------------------


def test_empty_day_creates_no_doc(ui_f2: UiSession) -> None:
    session = ui_f2
    page = session.page
    page.reload()
    _open_inbox(session)

    body = page.locator(DAY_DOC_BODY)
    body.wait_for(state="visible", timeout=10000)
    expect(body).to_have_attribute("contenteditable", "true", timeout=5000)

    # Click in, type nothing, click away — the whole "opened by default" affordance with zero
    # committed content.
    body.click()
    page.locator(DAY_DOC_TITLE).click()
    page.wait_for_timeout(1500)  # past BODY_SAVE_DEBOUNCE_MS, in case anything was queued

    assert _find_today_doc(session) is None, "an empty day must never create an empty doc row"

    # Leaving the view and coming back must not have created one either (no create-on-mount).
    page.click('[data-nav-item="docs"]')
    page.wait_for_selector('[data-cap="docs"]', timeout=5000)
    _open_inbox(session)
    page.wait_for_timeout(300)
    assert _find_today_doc(session) is None


# --- long note: the PAGE scrolls (KK bug report 2026-08-25) ----------------------------------------


def test_long_day_doc_scrolls_the_page_and_maybe_list_stays_reachable(ui_f2: UiSession) -> None:
    """WP-C's first cut clipped the view (`overflow: hidden`) and left scrolling to the kit
    column's own scrollport — a real-length note (the first prod note is 3,900 characters) filled
    the viewport and nothing scrolled anywhere. The fix makes `.inbox-view` the one scrollport:
    day doc and Maybe list at natural height, page scrolls, list reachable below a long note."""
    session = ui_f2
    page = session.page
    long_text = "\n\n".join(f"Paragraph {i}: a thought long enough to need real room." for i in range(40))
    with psycopg.connect(session.backend.dsn, autocommit=True) as conn:
        core_docs.create(conn, owner="t1", path=TODAY_PATH, title=TODAY_TITLE, body=long_text)

    page.reload()
    _open_inbox(session)
    page.locator(DAY_DOC_BODY).wait_for(state="visible", timeout=10000)

    view = page.locator('[data-cap="inbox"]')
    overflow = view.evaluate("el => el.scrollHeight - el.clientHeight")
    assert overflow > 0, f"long note must overflow the inbox scrollport, got {overflow}px"

    # The Maybe column sits below the note; scrolling the page must bring it into view.
    add_row = page.locator(MAYBE_ADD)
    add_row.scroll_into_view_if_needed(timeout=5000)
    expect(add_row).to_be_in_viewport(timeout=5000)
    scrolled = view.evaluate("el => el.scrollTop")
    assert scrolled > 0, "reaching the Maybe list must scroll the page scrollport itself"

    # And the column no longer keeps a scrollport of its own — natural height only.
    column_clips = page.locator('[data-vertical="maybe"]').evaluate(
        "el => el.scrollHeight > el.clientHeight + 1"
    )
    assert not column_clips, "the Maybe column must not clip/scroll internally on this page"
