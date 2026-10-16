"""Sources (docs/design/sources.md) through Chromium, live HTTP and real Postgres: the Inbox's third row under Documents,
the same chips with each source's state ("checked 07:00", in red "not answering since 06:00", grey while it waits),
red ones first; a source's window with its state, the exact check, Approve for a command and Fix for a red source.

The sources timer is off in this suite's backend (`conftest._spawn_backend`): the answers shown are written here, through
`core`, at times this file chooses. The page's clock is moved to the database's day first, as in `test_inbox_view.py`.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import httpx
import psycopg
from playwright.sync_api import Page, expect

from tests.ui.conftest import UiSession
from tests.ui.test_agent_conversation import BALLOON, ui_agent  # noqa: F401  (the fixture)
from tests.ui.views import switch_view, tick
from verticals.core import docs as core_docs
from verticals.core import source_checks as sc
from verticals.core import source_docs
from verticals.core import sources as core
from verticals.core.sources import Result

OWNER = "t1"
ROW = '[data-role="inbox-sources"]'
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
RED = "rgb(201, 58, 91)"

BODY_SAVE_SETTLE_MS = 1500  # BODY_SAVE_DEBOUNCE_MS (1000) in DocDetail.vue, plus round-trip slack
HTTP = {"kind": "http", "url": "https://example.test/health"}
CMD = {"kind": "cmd", "argv": ["/bin/echo", "disk 71% used"], "parse": r"(\d+)%", "max": 90}
GOOD = Result(ok=True, detail="HTTP 200", ms=12)
BAD = Result(ok=False, detail="HTTP 503", ms=9)


def _source(conn: psycopg.Connection, name: str, raw: dict, *, approved: bool = True) -> core.Source:
    """A source document. Every check the agent writes has the owner's approval unless `approved` is False: the scenarios
    about a state show it as it is once approved, and the ones about waiting show it before."""
    body = sc.build_body(gives="What the report reads.", how="Ask it.", since="the last report", check=sc.Check.from_dict(raw),
                         fixes=["Restart the worker."])
    doc = core_docs.create(conn, owner=OWNER, path=f"sources/{name}.md", title=name.title(), body=body).doc
    source = core.find(conn, owner=OWNER, ref=doc.id)
    if approved and source.check.gated:
        core.approve(conn, owner=OWNER, doc_id=source.id, check_hash=source.check.hash, now=datetime.now(timezone.utc))
        source = core.find(conn, owner=OWNER, ref=doc.id)
    return source


def _record(conn: psycopg.Connection, source: core.Source, result: Result, when: datetime) -> None:
    core.record(conn, owner=OWNER, doc_id=source.id, check_hash=source.check.hash, result=result, now=when)


def _said(when: datetime) -> str:
    """A moment as the page says it (lib/sources.ts clockOf): the time today in this machine's zone, else the day too."""
    local = when.astimezone()
    time = local.strftime("%H:%M")
    return time if local.date() == datetime.now().astimezone().date() else f"{local.day} {MONTHS[local.month - 1]}, {time}"


def _open_inbox(session: UiSession) -> None:
    session.page.clock.set_fixed_time(datetime.now(timezone.utc))
    session.page.reload()
    switch_view(session.page, "inbox")


def _chip(page: Page, doc_id: str):
    return page.locator(f'{ROW} [data-role="doc-chip"][data-doc-id="{doc_id}"]')


def _open_window(page: Page, doc_id: str):
    tick(page)
    _chip(page, doc_id).click()
    strip = page.locator('[data-role="doc-window"] [data-role="source-strip"]')
    expect(strip).to_be_visible(timeout=10000)
    return strip


def test_the_sources_row_stands_under_documents_red_first_each_with_its_state(ui_f2: UiSession) -> None:
    session = ui_f2
    page = session.page
    now = datetime.now(timezone.utc)
    with psycopg.connect(session.backend.dsn, autocommit=True) as conn:
        mail = _source(conn, "mail", HTTP)
        chat = _source(conn, "chat", HTTP)
        disk = _source(conn, "disk", CMD, approved=False)
        notes = core_docs.create(conn, owner=OWNER, path="syn-sources/notes.md", title="SYN Sources notes").doc.id
        _record(conn, mail, GOOD, now - timedelta(minutes=3))
        _record(conn, chat, BAD, now - timedelta(minutes=65))
        _record(conn, chat, BAD, now - timedelta(minutes=60))

    _open_inbox(session)
    row = page.locator(ROW)
    expect(row.locator('[data-role="doc-chip"]')).to_have_count(3, timeout=10000)

    # Under Documents, with its count; what needs a look stands first: red, then the one waiting for you, then the rest.
    expect(page.locator('[data-role="inbox-docs"] + [data-role="inbox-sources"]')).to_have_count(1)
    expect(row.locator(".inbox-desk__head")).to_have_text("Sources3")
    ids = row.locator('[data-role="doc-chip"]').evaluate_all("els => els.map(e => e.dataset.docId)")
    assert ids == [chat.id, disk.id, mail.id], f"red, waiting, ok: {ids}"

    # The line under the name: the words the design gives, in the page's zone.
    red = _chip(page, chat.id).locator('[data-role="source-state"]')
    expect(red).to_have_text(f"not answering since {_said(now - timedelta(minutes=65))}")
    expect(red).to_have_css("color", RED)
    waiting = _chip(page, disk.id).locator('[data-role="source-state"]')
    expect(waiting).to_have_text("waiting for your approval")
    ok = _chip(page, mail.id).locator('[data-role="source-state"]')
    expect(ok).to_have_text(f"checked {_said(now - timedelta(minutes=3))}")
    assert waiting.evaluate("e => getComputedStyle(e).color") == ok.evaluate("e => getComputedStyle(e).color") != RED, (
        "only a source that stopped answering is coloured")

    # A source is a document, shown once: Documents keeps the documents that are not sources.
    docs = page.locator('[data-role="inbox-docs"]')
    expect(docs.locator(f'[data-doc-id="{notes}"]')).to_have_count(1)
    for source in (mail, chat, disk):
        expect(docs.locator(f'[data-doc-id="{source.id}"]')).to_have_count(0)


def test_a_source_the_agent_writes_appears_in_the_open_inbox_and_a_stale_answer_is_grey_never_red(ui_f2: UiSession) -> None:
    session = ui_f2
    page = session.page
    now = datetime.now(timezone.utc)
    _open_inbox(session)
    expect(page.locator(ROW)).to_have_count(0)

    with psycopg.connect(session.backend.dsn, autocommit=True) as conn:
        # What the agent's tool does: the document, then the answer to its first run (here an old one, the Mac was asleep).
        draft = source_docs.prepare(conn, owner=OWNER, title="Calendar", gives="Events.", how="Ask it.", since="the last report", check=HTTP)
        saved = source_docs.save(conn, owner=OWNER, draft=draft, now=now)
        core.approve(conn, owner=OWNER, doc_id=saved.id, check_hash=saved.check.hash, now=now - timedelta(minutes=131))
        _record(conn, saved, BAD, now - timedelta(minutes=130))
        _record(conn, saved, BAD, now - timedelta(minutes=125))

    # Nothing was reloaded by hand: the bell the answer rang brought the row in.
    chip = _chip(page, saved.id)
    expect(chip).to_be_visible(timeout=15000)
    state = chip.locator('[data-role="source-state"]')
    expect(state).to_have_text(f"not checked since {_said(now - timedelta(minutes=125))}")
    expect(state).not_to_have_css("color", RED)


def test_a_command_waits_in_its_window_for_your_approval_of_exactly_that_text(ui_f2: UiSession) -> None:
    session = ui_f2
    page = session.page
    with psycopg.connect(session.backend.dsn, autocommit=True) as conn:
        disk = _source(conn, "disk", CMD, approved=False)

    _open_inbox(session)
    strip = _open_window(page, disk.id)
    expect(strip).to_have_attribute("data-state", "grey")
    expect(strip).to_have_attribute("data-why", "waiting")
    expect(strip.locator('[data-role="source-strip-state"]')).to_have_text("Waiting for your approval")
    # The exact text of what will run, in words the owner reads.
    check = strip.locator('[data-role="source-strip-check"]')
    expect(check).to_contain_text("Runs /bin/echo 'disk 71% used' on this Mac every hour")
    expect(strip.locator('[data-role="source-fix"]')).to_have_count(0)

    tick(page)
    strip.locator('[data-role="source-approve"]').click()
    expect(strip.locator('[data-role="source-approve"]')).to_have_count(0, timeout=10000)
    expect(strip.locator('[data-role="source-strip-state"]')).to_have_text("Not checked yet")
    with psycopg.connect(session.backend.dsn, autocommit=True) as conn:
        approved = conn.execute("SELECT approved_hash FROM source_state WHERE doc_id = %s", (disk.id,)).fetchone()
    assert approved == (disk.check.hash,), "what was approved is the hash of the check that was shown"


def test_an_address_waits_in_its_window_like_a_command_and_shows_what_will_be_asked(ui_f2: UiSession) -> None:
    session = ui_f2
    page = session.page
    check = {**HTTP, "url": "https://example.test/health?full=1", "expect": {"status": "ok"}}
    with psycopg.connect(session.backend.dsn, autocommit=True) as conn:
        web = _source(conn, "web", check, approved=False)

    _open_inbox(session)
    expect(_chip(page, web.id).locator('[data-role="source-state"]')).to_have_text("waiting for your approval", timeout=10000)
    strip = _open_window(page, web.id)
    expect(strip).to_have_attribute("data-why", "waiting")
    expect(strip.locator('[data-role="source-strip-state"]')).to_have_text("Waiting for your approval")
    # The exact address, query and all, and what it wants back, in words.
    expect(strip.locator('[data-role="source-strip-check"]')).to_contain_text(
        'Asks https://example.test/health?full=1 every hour and wants HTTP 200 and status to be "ok"')
    tick(page)
    strip.locator('[data-role="source-approve"]').click()
    expect(strip.locator('[data-role="source-approve"]')).to_have_count(0, timeout=10000)
    with psycopg.connect(session.backend.dsn, autocommit=True) as conn:
        approved = conn.execute("SELECT approved_hash FROM source_state WHERE doc_id = %s", (web.id,)).fetchone()
    assert approved == (web.check.hash,)


def test_a_check_edited_while_you_read_it_is_not_approved_unseen(ui_f2: UiSession) -> None:
    session = ui_f2
    page = session.page
    with psycopg.connect(session.backend.dsn, autocommit=True) as conn:
        disk = _source(conn, "disk", CMD, approved=False)

    _open_inbox(session)
    strip = _open_window(page, disk.id)
    expect(strip.locator('[data-role="source-strip-check"]')).to_contain_text("disk 71% used")

    # The agent changes the command while the window is open; the page still shows the old one.
    other = {**CMD, "argv": ["/bin/echo", "disk 72% used"]}
    with psycopg.connect(session.backend.dsn, autocommit=True) as conn:
        current = core.find(conn, owner=OWNER, ref=disk.id)
        body = sc.set_section(current.body, "check", sc.render_block(sc.Check.from_dict(other)))
        core_docs.save(conn, owner=OWNER, id=disk.id, expected_revision=current.revision, body=body)

    session.expects_network_failures = True  # the refused Approve is a 409: this scenario's subject
    tick(page)
    strip.locator('[data-role="source-approve"]').click()
    expect(strip.locator('[data-role="source-strip-problem"]')).to_have_text("The check changed while you read it. Read it again.", timeout=10000)
    # The new text is what stands there now, still waiting for its own approval.
    expect(strip.locator('[data-role="source-strip-check"]')).to_contain_text("disk 72% used", timeout=10000)
    expect(strip.locator('[data-role="source-approve"]')).to_have_count(1)
    with psycopg.connect(session.backend.dsn, autocommit=True) as conn:
        approved = conn.execute("SELECT approved_hash FROM source_state WHERE doc_id = %s", (disk.id,)).fetchone()
    assert approved is None or approved == (None,), f"nothing was approved: {approved}"


def test_a_red_source_window_says_why_and_offers_no_fix_without_an_agent(ui_f2: UiSession) -> None:
    session = ui_f2
    page = session.page
    now = datetime.now(timezone.utc)
    with psycopg.connect(session.backend.dsn, autocommit=True) as conn:
        chat = _source(conn, "chat", HTTP)
        _record(conn, chat, BAD, now - timedelta(minutes=65))
        _record(conn, chat, BAD, now - timedelta(minutes=60))

    _open_inbox(session)
    strip = _open_window(page, chat.id)
    state = strip.locator('[data-role="source-strip-state"]')
    expect(state).to_have_text(f"Not answering since {_said(now - timedelta(minutes=65))}")
    expect(state).to_have_css("color", RED)
    expect(strip.locator('[data-role="source-strip-detail"]')).to_have_text("HTTP 503")
    expect(strip.locator('[data-role="source-strip-check"]')).to_contain_text("Asks https://example.test/health every hour")
    expect(strip.locator('[data-role="source-fix"]')).to_have_count(0)
    expect(strip.locator('[data-role="source-approve"]')).to_have_count(0)
    # The document is under it, as any document's page.
    expect(page.locator('[data-role="doc-window"] [data-role="doc-title"]')).to_have_text("Chat")


def test_a_first_failure_is_quiet_on_the_tile_and_honest_in_the_window(ui_f2: UiSession) -> None:
    session = ui_f2
    page = session.page
    now = datetime.now(timezone.utc)
    failed = now - timedelta(minutes=2)
    with psycopg.connect(session.backend.dsn, autocommit=True) as conn:
        chat = _source(conn, "chat", HTTP)
        _record(conn, chat, BAD, failed)

    _open_inbox(session)
    # One failure is looked at again in five minutes before anyone is told: the tile is not red and not changed.
    tile = _chip(page, chat.id).locator('[data-role="source-state"]')
    expect(tile).to_have_text(f"checked {_said(failed)}", timeout=10000)
    expect(tile).not_to_have_css("color", RED)
    strip = _open_window(page, chat.id)
    expect(strip.locator('[data-role="source-strip-state"]')).not_to_have_css("color", RED)
    expect(strip.locator('[data-role="source-strip-detail"]')).to_have_text(f"HTTP 503; looking again at {_said(failed + timedelta(minutes=5))}")
    expect(strip.locator('[data-role="source-fix"]')).to_have_count(0)


def test_a_pass_that_read_a_number_shows_it_and_a_plain_pass_says_nothing_more(ui_f2: UiSession) -> None:
    session = ui_f2
    page = session.page
    now = datetime.now(timezone.utc)
    with psycopg.connect(session.backend.dsn, autocommit=True) as conn:
        plain = _source(conn, "plain", HTTP)
        disk = _source(conn, "disk", CMD)
        _record(conn, plain, GOOD, now - timedelta(minutes=2))
        _record(conn, disk, Result(ok=True, detail="71 from '71% of'", value=71.0, ms=8), now - timedelta(minutes=2))

    _open_inbox(session)
    strip = _open_window(page, plain.id)
    expect(strip.locator('[data-role="source-strip-state"]')).to_have_text(f"Checked {_said(now - timedelta(minutes=2))}")
    expect(strip.locator('[data-role="source-strip-detail"]')).to_have_count(0)
    page.keyboard.press("Escape")
    expect(page.locator('[data-role="doc-window"]')).to_have_count(0)
    strip = _open_window(page, disk.id)
    expect(strip.locator('[data-role="source-strip-detail"]')).to_have_text("71 from '71% of'")
    expect(strip.locator('[data-role="source-approve"]')).to_have_count(0)  # an approved command is not asked about again


def test_editing_a_sources_text_in_its_window_leaves_its_check_and_its_approval_as_they_were(ui_f2: UiSession) -> None:
    """The editor writes the whole document back when you change a word of it. The check's block is a fenced block there: set
    quietly, never edited, written back exactly as it was. So the check comes back the same, with the lines the editor used
    to bend (`_word_` became `*word*`), and an approval of it still holds."""
    session = ui_f2
    page = session.page
    check = {"kind": "cmd", "argv": ["/bin/df", "-k", "/"], "parse": r"\s(\d+)%\s", "max": 90, "say": "_{v}_% of the *disk* is `used`"}
    with psycopg.connect(session.backend.dsn, autocommit=True) as conn:
        disk = _source(conn, "disk", check)

    _open_inbox(session)
    _open_window(page, disk.id)
    expect(page.locator('[data-role="doc-window"] [data-role="doc-body"] pre[data-md-fence="check"]')).to_have_count(1)
    text = page.locator('[data-role="doc-window"] [data-role="doc-body"] p').first
    tick(page)
    text.click()
    page.keyboard.press("End")
    page.keyboard.type(" Today.")
    page.wait_for_timeout(BODY_SAVE_SETTLE_MS)

    saved = httpx.get(f"{session.backend.base_url}/api/docs/{disk.id}", headers={"Authorization": f"Bearer {session.backend.token}"}, timeout=10)
    assert saved.status_code == 200, saved.text
    body = saved.json()["body"]
    assert "Today." in body and saved.json()["revision"] > 1, "the edit was saved"
    assert sc.parse_check(body).hash == disk.check.hash, f"the check came back different:\n{body}"
    with psycopg.connect(session.backend.dsn, autocommit=True) as conn:
        assert core.find(conn, owner=OWNER, ref=disk.id).approved is True, "so the approval still holds"


def test_fix_opens_a_conversation_about_the_source_with_the_failure_in_its_first_sentence(ui_agent: UiSession) -> None:  # noqa: F811
    session = ui_agent
    page = session.page
    now = datetime.now(timezone.utc)
    with psycopg.connect(session.backend.dsn, autocommit=True) as conn:
        chat = _source(conn, "chat", HTTP)
        _record(conn, chat, BAD, now - timedelta(minutes=65))
        _record(conn, chat, BAD, now - timedelta(minutes=60))

    _open_inbox(session)
    strip = _open_window(page, chat.id)
    tick(page)
    strip.locator('[data-role="source-fix"]').click()

    said = page.locator(f'{BALLOON}[data-who="you"]')
    expect(said).to_contain_text("Fix the source “Chat”: not answering since", timeout=10000)
    expect(said).to_contain_text("HTTP 503")
    expect(said).to_contain_text("sources/chat.md")
    # The agent was asked once, by the click; nothing sent anything before it.
    expect(said).to_have_count(1)


def test_with_no_sources_the_row_says_so_and_names_the_servers_the_agent_reaches(ui_f2: UiSession) -> None:
    """Nothing to read yet: the row does not vanish, it says so and names the servers the agent reaches, from the app's own
    Connections check, so the owner learns where sources come from. A document under the folder with no check is a plain
    document: it stands in Documents, not here."""
    session = ui_f2
    page = session.page
    now = datetime.now(timezone.utc)
    with psycopg.connect(session.backend.dsn, autocommit=True) as conn:
        connections = core.ensure_connections(conn, owner=OWNER)
        own = core.find(conn, owner=OWNER, ref=connections)
        core.record(conn, owner=OWNER, doc_id=connections, check_hash=own.check.hash,
                    result=Result(ok=True, detail="all 3 answer: chat, mail, calendar", value=3.0, ms=900), now=now - timedelta(minutes=2))
        plain = core_docs.create(conn, owner=OWNER, path="sources/elena/transcript.md", title="A transcript", body="No check here.").doc.id

    _open_inbox(session)
    row = page.locator(ROW)
    expect(row.locator('[data-role="inbox-sources-none"]')).to_have_text(
        "No sources yet. The agent reaches chat, mail and calendar. Tell it what to read each morning, in one sentence.", timeout=10000)
    expect(row.locator(".inbox-desk__head")).to_have_text("Sources")
    expect(row.locator(f'[data-doc-id="{plain}"]')).to_have_count(0)
    expect(page.locator(f'[data-role="inbox-docs"] [data-doc-id="{plain}"]')).to_have_count(1)
