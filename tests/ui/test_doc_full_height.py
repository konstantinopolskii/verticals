"""A document stands full height (docs/design/doc-full-height.md): its window runs the window's full height, half a pixel
from the top and the bottom (one device pixel on a Retina screen), 720 px wide, its 24 px corners kept, the field over its
foot on a white fade. The windows beside it keep their 200 px at the sides, stepped back; a goal or a page stays a card.

The numbers are the owner's window, 1470 x 923. Before the change a document there was a 720 x 738 card, 32 px under the top
and 153 px above the bottom, as tall as its text up to that. `ui_f2` throughout; every document is made through
`verticals.core.docs`, the way `test_docs_view.py` makes them, and opened as a person opens it, from the Documents desk."""

from __future__ import annotations

from datetime import date

import httpx
import psycopg
from playwright.sync_api import Page, expect

from verticals.core import comments as core_comments, docs as core_docs, goals as core_goals

from tests.ui.conftest import UiSession
from tests.harness.png import decode_png
from tests.ui.views import open_page, show_tags, switch_view, tick

OWNER_WINDOW = {"width": 1470, "height": 923}
DOC = '.vt-window[data-window="doc"]'
GOAL = '.vt-window[data-window="goal"]'
ANCHOR = date(2026, 8, 8)
LONG_BODY = "\n\n".join(f"SYN paragraph {n} of a long document, long enough to run to a second line when it is set at the window's width." for n in range(80))

RECT = """(sel) => {
  const el = document.querySelector(sel)
  if (!el) return null
  const b = el.getBoundingClientRect()
  return { x: b.x, y: b.y, w: b.width, h: b.height, right: b.right, bottom: b.bottom }
}"""
WINDOWS = """() => [...document.querySelectorAll('.vt-window')].map((el) => {
  const b = el.getBoundingClientRect()
  return { kind: el.dataset.window, front: el.classList.contains('vt-window--front'), x: b.x, y: b.y, w: b.width, h: b.height,
           right: b.right, bottom: b.bottom }
})"""
FADE_HEIGHT = "el => parseFloat(getComputedStyle(el, '::after').height)"


def _doc(conn: psycopg.Connection, path: str, title: str, body: str = "") -> str:
    return core_docs.create(conn, owner="t1", path=path, title=title, body=body).doc.id


def _rect(page: Page, selector: str) -> dict[str, float]:
    box = page.evaluate(RECT, selector)
    assert box is not None, f"{selector} is not on the page"
    return box


def _near(value: float, expected: float, tolerance: float = 0.01) -> bool:
    return abs(value - expected) <= tolerance


def _pixels(page: Page, x: float, y: float, width: float, height: float) -> list[tuple[int, int, int]]:
    """The colours of a clip of the screen, as the page draws it (decoded without a library: `tests/harness/png.py`)."""
    png = page.screenshot(clip={"x": round(x), "y": round(y), "width": round(width), "height": round(height)})
    w, h, channels, raw = decode_png(png)
    return [(raw[i], raw[i + 1], raw[i + 2]) for i in range(0, w * h * channels, channels)]


def test_a_document_window_stands_full_height(ui_f2: UiSession) -> None:
    """The owner's window: 0.5 px from the top and from the bottom, 720 px wide and in the middle, the corners at 24 px,
    whatever the document's length: a long one and a two-line one are the same window."""
    session = ui_f2
    page = session.page
    page.set_viewport_size(OWNER_WINDOW)
    with psycopg.connect(session.backend.dsn, autocommit=True) as conn:
        long_id = _doc(conn, "syn-full/long.md", "SYN Full Height", LONG_BODY)
        short_id = _doc(conn, "syn-full/short.md", "SYN Short Note", "Two lines.\n\nThat is all.")
    page.reload()
    switch_view(page, "docs")

    def stands_full_height() -> None:
        page.wait_for_timeout(300)
        box = _rect(page, DOC)
        assert _near(box["y"], 0.5), f"the window's top is at {box['y']}, not half a pixel under the window's"
        assert _near(box["bottom"], OWNER_WINDOW["height"] - 0.5), f"its bottom is at {box['bottom']}"
        assert _near(box["w"], 720) and _near(box["x"], (OWNER_WINDOW["width"] - 720) / 2), box
        radii = page.locator(DOC).evaluate(
            "el => ['TopLeft', 'TopRight', 'BottomRight', 'BottomLeft'].map((c) => getComputedStyle(el)[`border${c}Radius`])"
        )
        assert radii == ["24px"] * 4, radii
        # What the text scrolls in fills the window under its head, so the page is the window.
        assert _near(_rect(page, f"{DOC} .vt-window__body")["bottom"], box["bottom"]), "the text's scroller stops short of the foot"

    open_page(page, long_id)
    stands_full_height()
    page.locator(f"{DOC} [aria-label='Close']").click()
    expect(page.locator(DOC)).to_have_count(0)
    open_page(page, short_id)
    stands_full_height()


def test_the_windows_beside_a_document_keep_their_200_px_and_a_goal_stays_a_card(ui_f2: UiSession) -> None:
    """The row of windows: a document in the centre, another document at its left and a goal at its right, each with 200 px
    in view and stepped back to 94%. The goal is still a card that hugs what it holds, 32 px from the top."""
    session = ui_f2
    page = session.page
    page.set_viewport_size(OWNER_WINDOW)
    with psycopg.connect(session.backend.dsn, autocommit=True) as conn:
        goal_id = core_goals.create(conn, owner="t1", title="SYN beside goal", vertical="day", anchor_date=ANCHOR).goal.id
        second = _doc(conn, "syn-full/second.md", "SYN Second", f"See [the goal](goal:{goal_id}).")
        first = _doc(conn, "syn-full/first.md", "SYN First", "Read [the second one](doc:syn-full/second.md).")
    page.reload()
    switch_view(page, "docs")
    open_page(page, first)
    page.locator('[data-role="doc-body"] a[data-link-kind="doc"]').click()
    expect(page.locator(DOC)).to_have_count(2, timeout=10000)
    page.wait_for_timeout(500)
    tick(page)
    page.locator(f'{DOC}.vt-window--front [data-role="doc-body"] a[data-link-kind="goal"]').click()
    expect(page.locator(GOAL)).to_have_count(1, timeout=10000)
    page.keyboard.press("Meta+BracketLeft")
    expect(page.locator(f"{DOC}.vt-window--front")).to_have_count(1)
    expect(page.locator(f"{DOC}.vt-window--front [data-role='doc-title']")).to_have_text("SYN Second")
    page.wait_for_timeout(700)

    windows = {w["kind"] + ("-front" if w["front"] else "-side"): w for w in page.evaluate(WINDOWS)}
    front, left, goal = windows["doc-front"], windows["doc-side"], windows["goal-side"]
    height = OWNER_WINDOW["height"]
    # The one in the centre: full height, and 720 px wide.
    assert _near(front["y"], 0.5) and _near(front["bottom"], height - 0.5) and _near(front["w"], 720), front
    # At the left a document, 200 px of it in view, stepped back to 94% from its top; at the right the goal the same.
    assert abs(left["right"] - 200) <= 1 and abs(left["w"] - 720 * 0.94) <= 1, left
    assert _near(left["y"], 0.5) and abs(left["bottom"] - (0.5 + 0.94 * (height - 1))) <= 1, left
    assert abs(goal["x"] - (OWNER_WINDOW["width"] - 200)) <= 1 and abs(goal["w"] - 720 * 0.94) <= 1, goal
    # The goal is a card: 32 px from the top, hugging its steps, nowhere near the bottom.
    assert abs(goal["y"] - 32) <= 1 and goal["bottom"] < height - 200, goal
    assert "vt-window--full" not in (page.locator(GOAL).get_attribute("class") or "")

    # Brought to the centre, the goal is the card it was: 720 px wide, 32 px from the top.
    page.keyboard.press("Meta+BracketRight")
    expect(page.locator(f"{GOAL}.vt-window--front")).to_have_count(1)
    page.wait_for_timeout(700)
    card = _rect(page, GOAL)
    assert abs(card["y"] - 32) <= 1 and _near(card["w"], 720) and card["bottom"] < height - 200, card


def test_a_comment_opens_over_its_words_in_a_full_height_document(ui_f2: UiSession) -> None:
    """A document's comments stand on their words (docs/design/doc-comments-inline.md), so the window has no column beside it
    to open: the comment opens right under its words, inside the window's box, and the window stays where it stood while it
    is read and answered; the count stands above the field."""
    session = ui_f2
    page = session.page
    page.set_viewport_size(OWNER_WINDOW)
    words = "SYN paragraph 2 of a long document"
    with psycopg.connect(session.backend.dsn, autocommit=True) as conn:
        doc_id = _doc(conn, "syn-full/comments.md", "SYN Comments Beside", LONG_BODY)
        core_comments.create_thread(
            conn, owner="t1", goal_id=None, doc_id=doc_id, body="SYN seeded note", author="human",
            anchor={"quote": words, "prefix": "", "suffix": ""},
        )
    page.reload()
    switch_view(page, "docs")
    page.mouse.move(8, 8)
    open_page(page, doc_id)
    before = _rect(page, DOC)
    expect(page.locator(f'{DOC} [data-role="doc-comments"]')).to_have_count(0)  # no count in the head: it stands over the field
    expect(page.locator('[data-role="doc-comments-count"]')).to_have_text("1 comment", timeout=10000)

    mark = page.locator(f"{DOC} mark.comment-highlight")
    expect(mark).to_have_text(words, timeout=10000)
    tick(page)
    mark.click()
    card = page.locator('[data-role="comment-card"]')
    expect(card).to_be_visible(timeout=10000)
    expect(card.locator('[data-role="comment-message"]')).to_have_text("SYN seeded note")
    expect(page.locator('[data-role="comments-panel"]')).to_have_count(0)  # no column beside the window

    # It stands in the window's box, just under its words, and the window has not moved or shrunk.
    box = _rect(page, '[data-role="comment-card"]')
    marked = _rect(page, f"{DOC} mark.comment-highlight")
    assert before["x"] <= box["x"] and box["right"] <= before["right"] and before["y"] <= box["y"] and box["bottom"] <= before["bottom"], (box, before)
    assert 0 <= box["y"] - (marked["y"] + marked["h"]) <= 12, (box, marked)
    assert _rect(page, DOC) == before

    # An answer written there lands on the same thread, and the window still has not moved.
    tick(page)
    card.locator('[data-role="comment-field"]').fill("SYN second note")
    page.keyboard.press("Enter")
    expect(card.locator('[data-role="comment-message"]')).to_have_count(2, timeout=10000)
    assert _rect(page, DOC) == before


def test_a_document_window_opens_at_its_full_height_and_lands_on_it(ui_f2: UiSession) -> None:
    """The window grows out of the page it was opened from (S3.P2.013) and ends exactly on its full height: it is that
    tall from its first frame, not a short card that grows when the text arrives (it was 148 px under "Opening…" and
    738 once the document was in), and the movement never passes the half pixel at the top or at the bottom."""
    session = ui_f2
    page = session.page
    page.set_viewport_size(OWNER_WINDOW)
    page.emulate_media(reduced_motion="no-preference")
    with psycopg.connect(session.backend.dsn, autocommit=True) as conn:
        doc_id = _doc(conn, "syn-full/opening.md", "SYN Opening", LONG_BODY)
    page.reload()
    switch_view(page, "docs")
    stacks = page.locator("[data-stack]")
    expect(stacks.first).to_be_visible(timeout=10000)
    laid = page.locator('[data-role="docs-open"]')
    for key in stacks.evaluate_all("els => els.map(el => el.dataset.stack)"):
        page.locator(f'[data-stack="{key}"]').click()
        expect(laid).to_be_visible()
        if laid.locator(f'[data-doc-id="{doc_id}"]').count():
            break
        laid.locator(".docs-open__head").click(position={"x": 1, "y": 1})
        expect(laid).to_have_count(0)
    page.wait_for_timeout(400)

    # The window's height from its first frame on, and its movement held at the start so it can be read frame by frame.
    page.evaluate(
        """() => {
          window.__heights = []
          window.__pop = null
          const t0 = performance.now()
          ;(function watch() {
            const win = document.querySelector('.vt-window[data-window="doc"]')
            if (win) window.__heights.push(win.offsetHeight)
            const pop = document.getAnimations().find((a) => a.effect?.target?.matches?.('.vt-window')
              && a.effect.getKeyframes().some((k) => k.transform && k.transform !== 'none'))
            if (pop && !window.__pop) { pop.pause(); window.__pop = pop }
            if (performance.now() - t0 < 2500) requestAnimationFrame(watch)
          })()
        }"""
    )
    laid.locator(f'[data-doc-id="{doc_id}"]').click()
    page.wait_for_function("() => window.__pop !== null", timeout=5000)
    page.wait_for_timeout(500)
    frames = []
    for at in range(0, 401, 50):
        page.evaluate("(at) => { window.__pop.currentTime = at }", at)
        frames.append(_rect(page, DOC))
    page.evaluate("() => window.__pop.finish()")
    page.wait_for_timeout(100)
    final = _rect(page, DOC)
    heights = set(page.evaluate("() => window.__heights"))
    assert heights == {OWNER_WINDOW["height"] - 1}, f"the window changed height while it opened: {sorted(heights)}"
    assert all(f["y"] >= 0.5 - 0.01 and f["bottom"] <= OWNER_WINDOW["height"] - 0.5 + 0.01 for f in frames), frames
    assert _near(final["y"], 0.5) and _near(final["bottom"], OWNER_WINDOW["height"] - 0.5) and _near(final["w"], 720), final
    assert _near(frames[-1]["y"], final["y"]) and _near(frames[-1]["bottom"], final["bottom"]), (frames[-1], final)
    # It grew: the first frame is small, the last is the window.
    assert frames[0]["h"] < 0.4 * final["h"] and frames[0]["w"] < 0.4 * final["w"], frames[0]


def test_the_field_stands_over_a_documents_foot_on_a_white_fade(ui_f2: UiSession) -> None:
    """Its text fades to white before the field, which stands on the fade; pointed at, the field brings its tags and the
    fade rises with them, as the conversation keeps clear of them; the end of the text rests above the fade; a press on the
    fade still reaches the text under it."""
    session = ui_f2
    page = session.page
    page.set_viewport_size(OWNER_WINDOW)
    with psycopg.connect(session.backend.dsn, autocommit=True) as conn:
        doc_id = _doc(conn, "syn-full/fade.md", "SYN Fade", LONG_BODY)
    page.reload()
    switch_view(page, "docs")
    page.mouse.move(8, 8)
    open_page(page, doc_id)
    page.wait_for_timeout(300)
    box = _rect(page, DOC)

    # The field's circle stands over the window's foot, and the foot is white around it: no word reads beside the circle.
    circle = _rect(page, ".circle-field__shape")
    assert circle["bottom"] < box["bottom"] and circle["y"] > box["bottom"] - 140, (circle, box)
    foot = (box["x"] + 40, box["bottom"] - 100, circle["x"] - 16 - (box["x"] + 40), 70)
    assert {c for c in _pixels(page, *foot)} == {(255, 255, 255)}, "text shows beside the field: the foot is not white"
    # Higher up the text is still there.
    higher = _pixels(page, box["x"] + 40, 380, box["w"] - 80, 60)
    assert sum(1 for p in higher if max(p) < 110) > 40, "no text is drawn above the fade"

    # The fade lets the pointer through: a press on it reaches the text under it, as the board's fade does.
    reaches = page.evaluate(
        "([x, y]) => !!document.elementFromPoint(x, y)?.closest('[data-role=\"doc-window\"]')", [box["x"] + 100, box["bottom"] - 60]
    )
    assert reaches, "the white fade takes the press that was for the text under it"

    # Pointed at, the field brings its tags and the fade rises with them (as the conversation does), so they stand on white.
    fade = float(page.locator(DOC).evaluate(FADE_HEIGHT))
    assert 120 <= fade <= 200, fade
    show_tags(page)
    page.wait_for_timeout(200)
    tags = _rect(page, ".circle-tags")
    beside = _pixels(page, box["x"] + 40, tags["y"] - 4, tags["x"] - 16 - (box["x"] + 40), tags["h"] + 8)
    assert {c for c in beside} == {(255, 255, 255)}, "text shows beside the field's tags: the fade did not rise with them"
    assert float(page.locator(DOC).evaluate(FADE_HEIGHT)) == fade + 44
    page.mouse.move(8, 8)
    page.wait_for_timeout(200)

    # The end of the document rests above the fade, so its last line is read, not covered.
    page.locator(f"{DOC} .vt-window__body").evaluate("el => { el.scrollTop = el.scrollHeight }")
    page.wait_for_timeout(200)
    last = page.locator(f"{DOC} .doc-detail__body p").last.bounding_box()
    assert last is not None and last["y"] + last["height"] <= box["bottom"] - fade + 0.5, (last, fade)


def test_a_documents_head_stands_under_the_desktop_apps_title_bar(ui_f2: UiSession) -> None:
    """The desktop app's transparent title bar takes a press at the top of the window for the window itself
    (Verticals.swift, `WebView.mouseDown`), and sets `--titlebar-height` for the page. The document window still reaches
    the top edge, and its head, with the × and the facts, stands under the bar."""
    session = ui_f2
    page = session.page
    page.set_viewport_size(OWNER_WINDOW)
    with psycopg.connect(session.backend.dsn, autocommit=True) as conn:
        doc_id = _doc(conn, "syn-full/bar.md", "SYN Bar", LONG_BODY)
    page.reload()
    switch_view(page, "docs")
    open_page(page, doc_id)
    page.evaluate("() => document.documentElement.style.setProperty('--titlebar-height', '28px')")
    page.wait_for_timeout(200)
    box = _rect(page, DOC)
    assert _near(box["y"], 0.5) and _near(box["bottom"], OWNER_WINDOW["height"] - 0.5), box
    for selector in (f"{DOC} .vt-window__head--doc .vt-window__button", f"{DOC} [data-role='doc-facts']"):
        part = _rect(page, selector)
        assert part["y"] >= 28, f"{selector} reaches into the title bar: top {part['y']}"


def test_a_press_below_the_text_starts_writing_at_its_end(ui_f2: UiSession) -> None:
    """The page is its writing area: what a short text leaves of the sheet belongs to the document's body, down to the room
    the field keeps under it, so a press anywhere on the page puts the caret at the end of the text and what is typed lands
    there. The field's own room, where a press may only have missed the circle, writes nothing."""
    session = ui_f2
    page = session.page
    page.set_viewport_size(OWNER_WINDOW)
    with psycopg.connect(session.backend.dsn, autocommit=True) as conn:
        doc_id = _doc(conn, "syn-full/write.md", "SYN Write", "Two lines.\n\nThat is all.")
    page.reload()
    switch_view(page, "docs")
    page.mouse.move(8, 8)
    open_page(page, doc_id)
    page.wait_for_timeout(300)
    win = _rect(page, DOC)
    body = page.locator(f"{DOC} [data-role='doc-body']")
    fade = float(page.locator(DOC).evaluate(FADE_HEIGHT))

    # The body runs from the text down to where the fade starts at rest, not as tall as its two lines.
    box = _rect(page, f"{DOC} [data-role='doc-body']")
    room = win["bottom"] - fade - box["bottom"]
    assert 0 <= room <= 30, f"the body stops {room} px from the fade's top, with its two lines at {box['h']} px"
    expect(body).to_have_css("cursor", "text")  # the I-beam over the blank page says it takes writing

    # A press in the field's room, 40 px from the circle's side, is not a press on the page: nothing starts.
    circle = _rect(page, ".circle-field__shape")
    page.mouse.click(circle["x"] - 40, circle["y"] + circle["h"] / 2)
    page.wait_for_timeout(200)
    expect(body).to_have_attribute("contenteditable", "false")

    # A press far under the text, in the middle of the blank page, starts writing at the end of the text.
    page.mouse.click(win["x"] + 300, 450)
    expect(body).to_have_attribute("contenteditable", "true")
    page.keyboard.type(" END")
    expect(body.locator("p").last).to_have_text("That is all. END")
    expect(body.locator("p").first).to_have_text("Two lines.")
    page.wait_for_timeout(1500)
    saved = httpx.get(
        f"{session.backend.base_url}/api/docs/{doc_id}", headers={"Authorization": f"Bearer {session.backend.token}"}, timeout=10
    )
    assert saved.status_code == 200 and saved.json()["body"].rstrip().endswith("That is all. END"), saved.text
