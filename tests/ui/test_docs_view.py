"""D250 WP-3 — the Docs view, through Chromium, live HTTP, and real Postgres.

Covers: creating a doc in a subfolder through the UI (the tree groups on '/', no folder table);
editing the body bumps a real revision; a concurrent external write (httpx, simulating a second
tab or an agent) is never silently overwritten — the UI's own stale save surfaces as a toast, not
a clobber; history browsing and restore (a restore is a NEW revision, never a rewind); the
goal<->doc link chips in both directions, including D248's "no dialog" law on the doc-to-goal
side; and the `#doc/<id>` boot fragment (mirrors `#goal/<id>`, `test_open_card_drag.py`'s OD-4).

`ui_f2` (F2, owner t1) is used throughout — the docs/doc_revisions/goal_doc_links tables are
empty on every fresh clone (migrations run to head, no fixture seeds them), so every test seeds
its own rows via `verticals.core.docs`/`verticals.core.goals` directly (same convention
`test_v2_subgoals.py`'s own `_create` helper uses) or, where the scenario specifically calls for
a concurrent HTTP client, via `httpx` against the live backend."""

from __future__ import annotations

from datetime import date

import httpx
import psycopg
from playwright.sync_api import expect

from verticals.core import docs as core_docs, goals as core_goals
from tests.ui.conftest import UiSession, activate_column

ANCHOR = date(2026, 8, 8)
TOAST_TEXT = ".toast-stack .toast .toast__text"
DIALOG_SELECTORS = ['[role="dialog"]', '.modal__scrim']
BODY_SAVE_SETTLE_MS = 1500  # BODY_SAVE_DEBOUNCE_MS (1000) in DocDetail.vue, plus round-trip slack


def _create_doc(conn: psycopg.Connection, path: str, title: str | None = None, body: str = "") -> str:
    return core_docs.create(conn, owner="t1", path=path, title=title, body=body).doc.id


def _create_goal(conn: psycopg.Connection, title: str, body: str = "", vertical: str | None = None) -> str:
    kwargs = {"anchor_date": ANCHOR} if vertical else {}
    return core_goals.create(conn, owner="t1", title=title, vertical=vertical, body=body, **kwargs).goal.id


def _api_get_doc(session: UiSession, doc_id: str) -> dict:
    resp = httpx.get(
        f"{session.backend.base_url}/api/docs/{doc_id}",
        headers={"Authorization": f"Bearer {session.backend.token}"},
        timeout=10,
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def _api_patch_doc(session: UiSession, doc_id: str, expected_revision: int, **fields: object) -> httpx.Response:
    return httpx.patch(
        f"{session.backend.base_url}/api/docs/{doc_id}",
        json={"expected_revision": expected_revision, **fields},
        headers={"Authorization": f"Bearer {session.backend.token}"},
        timeout=10,
    )


def _assert_no_dialog(page) -> None:
    for selector in DIALOG_SELECTORS:
        assert page.locator(selector).count() == 0, f"{selector!r} must never appear (D248)"


def _open_docs(session: UiSession) -> None:
    session.page.click('[data-nav-item="docs"]')
    session.page.wait_for_selector('[data-cap="docs"]', timeout=5000)


# --- create in a subfolder, collapsible tree ----------------------------------------------------


def test_create_doc_in_subfolder_appears_under_collapsible_folder(ui_f2: UiSession) -> None:
    session = ui_f2
    page = session.page
    page.reload()
    _open_docs(session)

    page.click('[data-role="docs-new-trigger"]')
    new_input = page.locator('[data-role="docs-new-input"]')
    new_input.wait_for(state="visible", timeout=5000)
    new_input.fill("syn-notes/plan")
    new_input.press("Enter")

    # The doc opened in the right pane the moment it was created.
    expect(page.locator('[data-role="doc-path"]')).to_have_text("syn-notes/plan.md", timeout=10000)

    folder = page.locator('[data-role="docs-folder"][data-folder-path="syn-notes"]')
    expect(folder).to_be_visible()
    assert folder.get_attribute("aria-expanded") == "true", "a new folder starts expanded"
    doc_row = page.locator('[data-role="docs-tree-doc"]', has_text="plan")
    expect(doc_row).to_be_visible()

    folder.click()
    expect(folder).to_have_attribute("aria-expanded", "false", timeout=5000)
    expect(doc_row).to_be_hidden()

    folder.click()
    expect(folder).to_have_attribute("aria-expanded", "true", timeout=5000)
    expect(doc_row).to_be_visible()


# --- body edit bumps a real revision --------------------------------------------------------------


def test_edit_body_and_save_bumps_revision(ui_f2: UiSession) -> None:
    session = ui_f2
    page = session.page
    with psycopg.connect(session.backend.dsn, autocommit=True) as conn:
        doc_id = _create_doc(conn, "syn-revtest/doc.md", title="Rev Test")

    page.reload()
    _open_docs(session)
    page.click(f'[data-doc-id="{doc_id}"]')
    expect(page.locator('[data-role="doc-title"]')).to_have_text("Rev Test", timeout=10000)

    body = page.locator('[data-role="doc-body"]')
    body.click()
    body.fill("SYN edited body text")
    page.wait_for_timeout(BODY_SAVE_SETTLE_MS)

    fresh = _api_get_doc(session, doc_id)
    assert fresh["revision"] == 2, f"expected revision 2 after one body save, got {fresh['revision']}"
    assert fresh["body"] == "SYN edited body text"


def test_leading_heading_repeating_title_is_hidden_and_kept_on_save(ui_f2: UiSession) -> None:
    session = ui_f2
    page = session.page
    with psycopg.connect(session.backend.dsn, autocommit=True) as conn:
        doc_id = _create_doc(conn, "syn-dup-title/doc.md", title="Dup Title", body="# Dup Title\n\nSYN body")

    page.reload()
    _open_docs(session)
    page.click(f'[data-doc-id="{doc_id}"]')
    expect(page.locator('[data-role="doc-title"]')).to_have_text("Dup Title", timeout=10000)

    body = page.locator('[data-role="doc-body"]')
    expect(body.locator("p")).to_have_text("SYN body")
    expect(body.locator("h1")).to_be_hidden()

    body.locator("p").click()
    page.keyboard.press("End")
    page.keyboard.type(" edited")
    page.keyboard.press("Home")
    page.keyboard.press("Backspace")
    page.wait_for_timeout(BODY_SAVE_SETTLE_MS)
    assert _api_get_doc(session, doc_id)["body"] == "# Dup Title\n\nSYN body edited"

    page.click('[data-role="doc-title"]')
    page.fill('[data-role="doc-title-input"]', "Renamed")
    page.press('[data-role="doc-title-input"]', "Enter")
    expect(body.locator("h1")).to_be_visible(timeout=5000)


# --- concurrent write: conflict surfaces, no silent overwrite ------------------------------------


def test_conflicting_save_surfaces_toast_and_never_overwrites(ui_f2: UiSession) -> None:
    session = ui_f2
    page = session.page
    with psycopg.connect(session.backend.dsn, autocommit=True) as conn:
        doc_id = _create_doc(conn, "syn-conflict/doc.md", title="Conflict Test")

    page.reload()
    _open_docs(session)
    page.click(f'[data-doc-id="{doc_id}"]')
    expect(page.locator('[data-role="doc-title"]')).to_have_text("Conflict Test", timeout=10000)

    # A second client (httpx, simulating another tab or an agent) saves first — the UI's own
    # in-memory revision (1, captured when it opened the doc) is now stale.
    external = _api_patch_doc(session, doc_id, expected_revision=1, body="SYN external edit")
    assert external.status_code == 200, external.text
    assert external.json()["revision"] == 2

    # The stale save's own 409 is this scenario's deliberate subject, not a defect — same opt-out
    # `test_s77_capability_manifest_ui.py`'s own subtree-delete 409 uses for the identical reason.
    session.expects_network_failures = True
    body = page.locator('[data-role="doc-body"]')
    body.click()
    body.fill("SYN local edit that must not land")
    page.wait_for_timeout(BODY_SAVE_SETTLE_MS)

    toast = page.locator(TOAST_TEXT)
    expect(toast).to_contain_text("changed elsewhere", timeout=5000)

    fresh = _api_get_doc(session, doc_id)
    assert fresh["revision"] == 2, "the stale local save must not have bumped the revision again"
    assert fresh["body"] == "SYN external edit", "the external write must survive, never silently overwritten"


# --- history: restore is a NEW revision, never a rewind -------------------------------------------


def test_history_restore_old_revision_creates_new_revision_with_old_text(ui_f2: UiSession) -> None:
    session = ui_f2
    page = session.page
    with psycopg.connect(session.backend.dsn, autocommit=True) as conn:
        doc_id = _create_doc(conn, "syn-history/doc.md", title="History Test", body="SYN v1 text")
        core_docs.save(conn, owner="t1", id=doc_id, expected_revision=1, body="SYN v2 text")

    page.reload()
    _open_docs(session)
    page.click(f'[data-doc-id="{doc_id}"]')
    expect(page.locator('[data-role="doc-title"]')).to_have_text("History Test", timeout=10000)

    page.click('[data-role="doc-history-trigger"]')
    page.wait_for_selector('[data-role="docs-history"]', timeout=5000)
    rows = page.locator('[data-role="docs-history-row"]')
    expect(rows).to_have_count(2, timeout=5000)

    page.click('[data-role="docs-history-row"][data-revision="1"]')
    body_view = page.locator('[data-role="docs-history-body"]')
    expect(body_view).to_contain_text("SYN v1 text", timeout=5000)

    page.click('[data-role="docs-history-restore"]')
    # Restore closes history and returns to the live, now-restored doc.
    page.wait_for_selector('[data-role="docs-history"]', state="detached", timeout=5000)
    expect(page.locator('[data-role="doc-body"]')).to_contain_text("SYN v1 text", timeout=5000)

    fresh = _api_get_doc(session, doc_id)
    assert fresh["revision"] == 3, f"restore must append a NEW revision, got {fresh['revision']}"
    assert fresh["body"] == "SYN v1 text"

    history_resp = httpx.get(
        f"{session.backend.base_url}/api/docs/{doc_id}/history",
        headers={"Authorization": f"Bearer {session.backend.token}"},
        timeout=10,
    )
    assert [r["revision"] for r in history_resp.json()["revisions"]] == [1, 2, 3], (
        "restore must never rewrite or remove an existing revision row"
    )


# --- goal -> doc chip: GoalDetail navigates into the Docs view ------------------------------------


def test_goal_doc_chip_navigates_to_docs_view(ui_f2: UiSession) -> None:
    session = ui_f2
    page = session.page
    with psycopg.connect(session.backend.dsn, autocommit=True) as conn:
        doc_id = _create_doc(conn, "syn-linked/target.md", title="SYN Target Doc")
        goal_id = _create_goal(conn, "SYN goal with a doc link", vertical="day")
        # `core.docs.rewrite_goal_links` is called from inside `core.goals.update()` only (its own
        # module docstring: "only when a body was actually written") — `create()` never indexes an
        # initial body's own links. A real body edit always goes through `update()` too (the
        # debounced PATCH `DocDetail.vue`/`GoalDetail.vue` both send), so this mirrors that path
        # rather than the one `create()` alone cannot produce.
        core_goals.update(conn, owner="t1", id=goal_id, body="[the doc](doc:syn-linked/target.md)")

    page.reload()
    card_row = page.locator(f'[data-goal-id="{goal_id}"] > .goal-card__row .goal-card__title')
    expect(card_row).to_be_visible(timeout=10000)
    card_row.click()
    expect(page.locator(f'[data-goal-id="{goal_id}"].goal-card--detail-open')).to_be_visible()

    chip = page.locator(f'[data-role="goal-doc-chip"][data-doc-id="{doc_id}"]')
    expect(chip).to_be_visible(timeout=10000)
    expect(chip).to_have_text("SYN Target Doc")
    chip.click()

    expect(page.locator('[data-cap="docs"]')).to_be_visible(timeout=10000)
    expect(page.locator('[data-role="doc-path"]')).to_have_text("syn-linked/target.md", timeout=10000)
    assert page.locator('[data-nav-item="docs"]').get_attribute("aria-current") == "page"


# --- doc -> goal chip: DocDetail navigates to the board, opens the card in place, no dialog -------


def test_doc_goal_chip_navigates_to_board_and_opens_card_in_place(ui_f2: UiSession) -> None:
    session = ui_f2
    page = session.page
    with psycopg.connect(session.backend.dsn, autocommit=True) as conn:
        goal_id = _create_goal(conn, "SYN target goal for a doc link", vertical="day")
        doc_id = _create_doc(
            conn, "syn-linked/source.md", title="SYN Source Doc", body=f"[the goal](goal:{goal_id})",
        )

    page.reload()
    _open_docs(session)
    page.click(f'[data-doc-id="{doc_id}"]')
    expect(page.locator('[data-role="doc-title"]')).to_have_text("SYN Source Doc", timeout=10000)

    chip = page.locator(f'[data-role="doc-linked-goal-chip"][data-goal-id="{goal_id}"]')
    expect(chip).to_be_visible(timeout=10000)
    chip.click()

    host = page.locator(f'[data-goal-id="{goal_id}"].goal-card--detail-open')
    expect(host).to_be_visible(timeout=10000)
    expect(host.locator(".goal-detail-inline")).to_be_visible()
    _assert_no_dialog(page)
    assert page.locator('[data-nav-item="verticals"]').get_attribute("aria-current") == "page"


# --- #doc/<id> boot fragment ----------------------------------------------------------------------


# --- D251 (KK, 2026-08-20): docs "ghost" down from an ancestor ----------------------------------


def test_inherited_doc_chip_is_ghosted_and_navigates(ui_f2: UiSession) -> None:
    """SYNDAY01/SYNSUB01 are the fixed F2 parent/child pair `test_s68_ancestor_chain_visible.py`
    already uses for the same reason: SYNSUB01's stored `path` names SYNDAY01 as its direct
    parent (`tests/fixtures/f2_synth.sql`). SYNDAY01 links a doc directly (own); SYNSUB01 must
    "see" it too, ghosted — plus SYNSUB01 links its OWN doc, which must render un-ghosted, so the
    same card proves both halves of D251's dedupe (own wins, inherited still shows) at once."""
    session = ui_f2
    page = session.page
    with psycopg.connect(session.backend.dsn, autocommit=True) as conn:
        inherited_doc_id = _create_doc(conn, "syn-inherit/parent-linked.md", title="SYN Parent Doc")
        own_doc_id = _create_doc(conn, "syn-inherit/child-linked.md", title="SYN Child Own Doc")
        core_goals.update(conn, owner="t1", id="SYNDAY01", body="[p](doc:syn-inherit/parent-linked.md)")
        core_goals.update(conn, owner="t1", id="SYNSUB01", body="[c](doc:syn-inherit/child-linked.md)")

    # R7 hides parked children from board subgoal lists (`test_s68_ancestor_chain_visible.py`'s
    # own comment) — recommit SYNSUB01 to its parent's day vertical so it actually renders nested.
    scheduled = httpx.put(
        f"{session.backend.base_url}/api/goals/SYNSUB01/schedule",
        json={"vertical": "day", "anchor_date": "2026-08-08"},
        headers={"Authorization": f"Bearer {session.backend.token}"},
        timeout=10,
    )
    assert scheduled.status_code == 200, scheduled.text

    page.reload()
    # D244: SYNSUB01 is SYNDAY01's same-column subtask — folded into the compact day column's
    # stack until the column expands (`test_s68_ancestor_chain_visible.py`'s own precedent).
    activate_column(page, "day")
    card_row = page.locator('[data-goal-id="SYNSUB01"] > .goal-card__row .goal-card__title')
    expect(card_row).to_be_visible(timeout=10000)
    card_row.click()
    expect(page.locator('[data-goal-id="SYNSUB01"].goal-card--detail-open')).to_be_visible()

    own_chip = page.locator(f'[data-role="goal-doc-chip"][data-doc-id="{own_doc_id}"]')
    inherited_chip = page.locator(f'[data-role="goal-doc-chip"][data-doc-id="{inherited_doc_id}"]')
    expect(own_chip).to_be_visible(timeout=10000)
    expect(inherited_chip).to_be_visible(timeout=10000)

    # the child's own chip is never ghosted...
    assert own_chip.get_attribute("data-inherited") is None
    # ...the inherited one always is, and it is visibly muted, not just tagged
    assert inherited_chip.get_attribute("data-inherited") == "true"
    own_color = own_chip.evaluate("el => getComputedStyle(el).color")
    inherited_color = inherited_chip.evaluate("el => getComputedStyle(el).color")
    assert inherited_color != own_color, "a ghosted chip must read as visually muted, not identical"

    inherited_chip.click()
    expect(page.locator('[data-cap="docs"]')).to_be_visible(timeout=10000)
    expect(page.locator('[data-role="doc-path"]')).to_have_text(
        "syn-inherit/parent-linked.md", timeout=10000
    )


def test_doc_hash_fragment_opens_the_doc_on_boot(ui_f2: UiSession) -> None:
    session = ui_f2
    with psycopg.connect(session.backend.dsn, autocommit=True) as conn:
        doc_id = _create_doc(conn, "syn-boot/target.md", title="SYN Boot Target")

    # `page.goto` to a URL differing only in fragment does not reload an already-booted SPA
    # (`test_open_card_drag.py::test_od4`'s own note) — the `about:blank` hop forces a genuine
    # cross-document navigation so `main.ts`'s one-shot fragment read actually runs.
    session.page.goto("about:blank")
    session.page.goto(f"{session.base_url}/#doc/{doc_id}")

    expect(session.page.locator('[data-cap="docs"]')).to_be_visible(timeout=10000)
    expect(session.page.locator('[data-role="doc-title"]')).to_have_text("SYN Boot Target", timeout=10000)
    assert session.page.locator('[data-nav-item="docs"]').get_attribute("aria-current") == "page"
    assert session.page.url.endswith(f"#doc/{doc_id}")
    _assert_no_dialog(session.page)


# --- in-app links inside a rendered body: `[label](goal:<id>)` / `[label](doc:<path>)` ----------
#
# The links `core/docs.py::extract_links` indexes used to render as literal text (the S-72
# allowlist had http/https/mailto only). A click takes the corresponding chip's own path.


def test_doc_body_goal_link_renders_as_anchor_and_navigates_to_board(ui_f2: UiSession) -> None:
    session = ui_f2
    page = session.page
    with psycopg.connect(session.backend.dsn, autocommit=True) as conn:
        goal_id = _create_goal(conn, "SYN body-link target goal", vertical="day")
        doc_id = _create_doc(
            conn, "syn-bodylink/source.md", title="SYN Body Link Source",
            body=f"See [the goal](goal:{goal_id}) and [outside](https://example.com/x).",
        )

    page.reload()
    _open_docs(session)
    page.click(f'[data-doc-id="{doc_id}"]')
    expect(page.locator('[data-role="doc-title"]')).to_have_text("SYN Body Link Source", timeout=10000)
    body = page.locator('[data-role="doc-body"]')

    link = body.locator(f'a[data-link-kind="goal"][data-link-target="{goal_id}"]')
    expect(link).to_have_text("the goal")
    assert link.get_attribute("href") == f"goal:{goal_id}"
    assert link.get_attribute("target") is None, "an in-app link never opens a browser tab"
    assert f"(goal:{goal_id})" not in body.inner_text(), "the in-app link stayed literal text"
    # An external link keeps S-72's shape untouched, side by side with the in-app one.
    external = body.locator('a[href="https://example.com/x"]')
    expect(external).to_have_text("outside")
    assert external.get_attribute("target") == "_blank"
    assert external.get_attribute("data-link-kind") is None

    link.click()
    host = page.locator(f'[data-goal-id="{goal_id}"].goal-card--detail-open')
    expect(host).to_be_visible(timeout=10000)
    expect(host.locator(".goal-detail-inline")).to_be_visible()
    _assert_no_dialog(page)
    assert page.url.startswith(session.base_url), "an in-app link must never navigate the browser itself"
    assert page.locator('[data-nav-item="verticals"]').get_attribute("aria-current") == "page"


def test_doc_body_doc_link_opens_the_target_doc(ui_f2: UiSession) -> None:
    session = ui_f2
    page = session.page
    with psycopg.connect(session.backend.dsn, autocommit=True) as conn:
        _create_doc(conn, "syn-bodylink/target.md", title="SYN Body Link Target")
        source_id = _create_doc(
            conn, "syn-bodylink/source.md", title="SYN Body Link Source",
            body="Read [the target](doc:syn-bodylink/target.md) first.",
        )

    page.reload()
    _open_docs(session)
    page.click(f'[data-doc-id="{source_id}"]')
    expect(page.locator('[data-role="doc-title"]')).to_have_text("SYN Body Link Source", timeout=10000)

    link = page.locator(
        '[data-role="doc-body"] a[data-link-kind="doc"][data-link-target="syn-bodylink/target.md"]'
    )
    expect(link).to_have_text("the target")
    link.click()

    expect(page.locator('[data-role="doc-path"]')).to_have_text("syn-bodylink/target.md", timeout=10000)
    expect(page.locator('[data-role="doc-title"]')).to_have_text("SYN Body Link Target")
    assert page.locator(TOAST_TEXT).count() == 0
    assert page.url.startswith(session.base_url)


def test_goal_body_doc_link_opens_docs_view(ui_f2: UiSession) -> None:
    session = ui_f2
    page = session.page
    with psycopg.connect(session.backend.dsn, autocommit=True) as conn:
        _create_doc(conn, "syn-bodylink/notes.md", title="SYN Notes")
        goal_id = _create_goal(conn, "SYN goal with a body doc link", vertical="day")
        core_goals.update(conn, owner="t1", id=goal_id, body="Notes: [here](doc:syn-bodylink/notes.md)")

    page.reload()
    card_row = page.locator(f'[data-goal-id="{goal_id}"] > .goal-card__row .goal-card__title')
    expect(card_row).to_be_visible(timeout=10000)
    card_row.click()
    host = page.locator(f'[data-goal-id="{goal_id}"].goal-card--detail-open')
    expect(host).to_be_visible()

    link = host.locator('.goal-detail__body a[data-link-kind="doc"][data-link-target="syn-bodylink/notes.md"]')
    expect(link).to_have_text("here", timeout=10000)
    link.click()

    expect(page.locator('[data-cap="docs"]')).to_be_visible(timeout=10000)
    expect(page.locator('[data-role="doc-path"]')).to_have_text("syn-bodylink/notes.md", timeout=10000)
    assert page.locator('[data-nav-item="docs"]').get_attribute("aria-current") == "page"


def test_editing_a_doc_body_keeps_its_in_app_links(ui_f2: UiSession) -> None:
    """Render and serialize are one round trip (`bodyMarkdown.ts`): an anchor the serializer did
    not recognise would come back as its bare label, and the debounced save would drop the link —
    and with it the `goal_doc_links` row `core/docs.py` derives from the text."""
    session = ui_f2
    page = session.page
    with psycopg.connect(session.backend.dsn, autocommit=True) as conn:
        goal_id = _create_goal(conn, "SYN round-trip target goal", vertical="day")
        doc_id = _create_doc(
            conn, "syn-bodylink/roundtrip.md", title="SYN Round Trip",
            body=f"Plan: [the goal](goal:{goal_id}) first.",
        )

    page.reload()
    _open_docs(session)
    page.click(f'[data-doc-id="{doc_id}"]')
    expect(page.locator('[data-role="doc-title"]')).to_have_text("SYN Round Trip", timeout=10000)

    body = page.locator('[data-role="doc-body"]')
    # Below the text, not on the link: a read-mode link click follows the link instead of editing.
    body.click(position={"x": 8, "y": 180})
    expect(body).to_have_attribute("contenteditable", "true")
    page.keyboard.press("End")
    page.keyboard.type(" Then rest.")
    page.wait_for_timeout(BODY_SAVE_SETTLE_MS)

    fresh = _api_get_doc(session, doc_id)
    assert fresh["body"] == f"Plan: [the goal](goal:{goal_id}) first. Then rest."
    assert goal_id in {g["goal_id"] for g in fresh["linked_goals"]}
