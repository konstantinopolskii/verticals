"""S-77 — UI half of the capability manifest (L5).

docs/E2E.md §6 S-77. Fixture F5 (`tests/fixtures/capabilities.json`) against the running app.
Steps: for every row of F5, assert its `ui_selector` resolves to at least one element somewhere in
the app (board, card, detail surface, bulk bar, or Inbox) and that activating that row's affordance
issues the row's `(http_method, http_path)`. Required by AC-104/AC-195. Serves L5.

E2E.md §11 finding 13 and this scenario's own text: every UI-backed row resolves — except
`bulk_update`, which carries `ui_selector: null` since the owner's 2026-08-09 click-opens ruling
removed the selection gesture (see `_selector_of`'s doc comment) and whose selector's *absence*
is asserted instead. `filter_value` took the same shape when the bottom bar became one field
(3bc40f9): a value is an area token in "Find, filter or ask", and the field narrows the loaded
board in the browser, so no control in the page issues the filtered board GET any more; the
route stays on HTTP and MCP. Sets, never counts. `capture_maybe`
resolves by column plus cap (`ui_column` + `ui_selector`, `_selector_of` below) rather than by a
`data-cap` value of its own — rows 108/116(b), the ruling that a capability is a gesture and the
manifest may name a control by where it sits.

**Ruling 1** (owner, 2026-08-09) moves where `capture_maybe` resolves. The Maybe column is no
longer part of the board (`ARCHITECTURE.md`:445's eighth-column reading is superseded) — its own
`[data-vertical=maybe] [data-cap=create-goal]` control now lives on the Inbox nav view
(`InboxView.vue`), mutually exclusive on screen with the board and the detail surface
(`App.vue`'s `v-if`/`v-else`). No other F5 row shares a screen with it any more, so this file
checks `capture_maybe` in its own pass, after navigating to Inbox, rather than folding it into the
single board-plus-detail-surface sweep every other row still resolves against.
"""

from __future__ import annotations

import json
import re
import time
from collections.abc import Callable
from datetime import date
from pathlib import Path
from urllib.parse import parse_qsl, urlsplit

import httpx
import psycopg

from verticals.core import goals as core_goals
from tests.harness.report import gate
from tests.ui.conftest import UiSession, activate_column
from tests.ui.views import switch_view

REPO_ROOT = Path(__file__).resolve().parents[2]
MANIFEST = REPO_ROOT / "tests" / "fixtures" / "capabilities.json"
MUTATING_METHODS = {"DELETE", "PATCH", "POST", "PUT"}
GRIP = {"x": 50, "y": 6}


def _selector_of(row: dict) -> str | None:
    """`"[data-cap=create-goal]"` — already a valid CSS selector as stored, used verbatim so a
    manifest edit is what this test follows, not a transformation this test invented.

    One row carries `ui_column` as well, and it composes: `capture_maybe` is the `create-goal`
    gesture *in the Maybe column*, resolved as `[data-vertical=maybe] [data-cap=create-goal]`
    (`docs/PENDING_DOC_FIXES.md` rows 108, 116(b)). A capability is a gesture, not a DOM
    attribute: the Maybe column's inline-add already exists and already carries `create-goal`,
    which S-106/AC-110 pin literally on all eight columns, and an element holds one `data-cap`.
    Resolving by column plus cap is what lets the manifest name that control without a second
    attribute value on it and without a decorative wrapper element to answer a selector.

    `reorder`'s `ui_selector` was `null` for one pass and is a real selector again. The history is
    worth keeping because it is the only row that has been in all three states. The menu-driven
    "Move up"/"Move down" controls that carried `[data-cap=reorder]` were removed by the owner's
    2026-08-09 ruling ("remove ur shitty move up down"), and the cross-column drag that replaced
    them did not carry within-column reorder with it — so for one pass the capability genuinely had
    no UI entry point and `null` was the honest value (`docs/PENDING_DOC_FIXES.md` row 127). The
    owner's second round of drag rulings the same day put the gesture back as a drag (AC-220/S-145),
    and it resolves against `.goal-card__row` — the same resting element the drag is armed from,
    which is also the element you aim a reorder *at*. Row 129 asked whether it should instead name
    the drop indicator: no. That element exists only mid-gesture, and a manifest checked against a
    resting board cannot resolve it.

    The `null` branch below is live again: `bulk_update` took the shape `reorder` vacated. The
    owner's second 2026-08-09 ruling ("why tasks are still can be selected if I click them and
    shitty stuff on the top appears? I don't need it") removed the selection gesture and the bulk
    bar entirely — a plain click now opens the detail surface, the incumbent's behaviour. Bulk
    complete is not a lost capability: it stays exactly as S-44/S-133 exercise it, `PATCH
    /api/goals` with `ids[]` over HTTP and MCP. It just has no UI entry point any more, and `null`
    is the honest value — the same honesty `reorder`'s one `null` pass established."""
    selector = row["ui_selector"]
    if selector is None:
        return None
    column = row.get("ui_column")
    return f"[data-vertical={column}] {selector}" if column else selector


def _request_matches(row: dict, request: dict) -> bool:
    """Match an observed URL to F5 while treating `{id}` as one opaque path segment.

    A manifest query is significant (`cascade=true` distinguishes subtree delete). When F5
    declares no query, the client's explicit default `cascade=false` is the same leaf route as an
    omitted default and is accepted; every other undeclared query is rejected.
    """
    if request["method"] != row["http_method"]:
        return False
    expected_path, separator, expected_query = row["http_path"].partition("?")
    actual = urlsplit(request["url"])
    pattern = "^" + re.escape(expected_path).replace(r"\{id\}", r"[^/]+") + "$"
    if re.fullmatch(pattern, actual.path) is None:
        return False
    if separator:
        # Subset semantics with `{id}` as a wildcard: `filter_value` declares
        # `/api/board?value={id}` while the live URL also carries the always-present `date`
        # parameter and a real id. Every declared pair must be present (a literal value must
        # match exactly — `cascade=true` still rejects an observed `cascade=false`); undeclared
        # extras like `date` are the route's own required plumbing, not a different capability.
        actual_params = dict(parse_qsl(actual.query))
        return all(
            key in actual_params and (expected in ("{id}", actual_params[key]))
            for key, expected in parse_qsl(expected_query)
        )
    return actual.query in {"", "cascade=false"}


def _route_shape(request: dict) -> tuple[str, str]:
    """Anonymised route shape for failures: never leak fixture ids into assertion text."""
    parsed = urlsplit(request["url"])
    path = re.sub(r"^(/api/goals/)[^/]+", r"\1{id}", parsed.path)
    return request["method"], path + (f"?{parsed.query}" if parsed.query else "")


def _activate_row(
    session: UiSession,
    row: dict,
    gesture: Callable[[], None],
    observed: set[tuple[str, str, str]],
) -> None:
    before = len(session.request_log)
    gesture()
    deadline = time.monotonic() + 5.0
    matches: list[dict] = []
    while time.monotonic() < deadline:
        matches = [
            request
            for request in session.request_log[before:]
            if _request_matches(row, request)
        ]
        if matches:
            break
        session.page.wait_for_timeout(25)
    assert matches, (
        f"{row['cap']}: activating its UI surface did not issue declared "
        f"{row['http_method']} {row['http_path']}"
    )
    assert matches[0]["status"] is not None and matches[0]["status"] < 400, (
        f"{row['cap']}: declared route did not succeed"
    )
    observed.add((row["cap"], row["http_method"], row["http_path"]))


def _seed_live_ghost(session: UiSession, title: str):
    """R10 revised (KK ruling 2026-08-16): ghosts exist only on the wall-clock current period,
    so the pinned 2026-08-08 board carries none; a year's plan from last year stays in Year's
    group whatever day the suite runs on (docs/design-handoff S4.P1.007)."""
    with psycopg.connect(session.backend.dsn, autocommit=True) as conn:
        return core_goals.create(
            conn, owner="t1", title=title, vertical="year",
            anchor_date=date(date.today().year - 1, 6, 15),
        ).goal


def _open_card_menu(page, vertical: str, goal_id: str) -> None:
    activate_column(page, vertical)
    page.click(f'[data-goal-id="{goal_id}"] [data-role=goal-actions-trigger]')
    page.wait_for_selector('[data-role="goal-context-menu"]', timeout=5000)


def _open_reparent_menu(page, vertical: str, goal_id: str) -> None:
    _open_card_menu(page, vertical, goal_id)
    page.click('#dropdownPortal [data-move="under"]')
    page.wait_for_selector('[data-role="move-step"][data-step="under"]', timeout=5000)


def _open_tags(page, goal_id: str) -> None:
    """An open goal's tags are in its "..." menu, "Tags..." (the opened-card cleanup, KK 27-28 Sep 2026): the inline
    card has no icon row, so the Tags button this scenario used to click is gone."""
    page.click(f'[data-goal-id="{goal_id}"].goal-card--detail-open [data-role="goal-actions-trigger"]')
    page.click('[data-role="goal-actions-menu"] [data-action="tags"] button')
    page.wait_for_selector('#dropdownPortal [data-role="tag-chips"]', timeout=5000)


def _close_tags(page) -> None:
    """Escape closes one level per press: the Tags submenu, then the "..." menu. The open card stays open."""
    page.keyboard.press("Escape")
    page.wait_for_selector('[data-role="tag-chips"]', state="hidden", timeout=5000)
    page.keyboard.press("Escape")
    page.wait_for_selector('[data-role="goal-context-menu"]', state="hidden", timeout=5000)


def _prepare_inline_add(page, selector: str, title: str) -> str:
    page.click(selector)
    editor = f'{selector} [data-role="column-add-editor"]'
    page.wait_for_selector(editor, timeout=5000)
    page.fill(editor, title)
    return editor


def _reorder_to_edge(page, source: str, target: str, edge_fraction: float) -> None:
    source_box = page.locator(source).bounding_box()
    target_box = page.locator(target).bounding_box()
    assert source_box is not None, "reorder source has no live geometry"
    assert target_box is not None, "reorder target has no live geometry"
    sx, sy = source_box["x"] + GRIP["x"], source_box["y"] + GRIP["y"]
    tx = target_box["x"] + min(GRIP["x"], target_box["width"] * 0.45)
    ty = target_box["y"] + target_box["height"] * edge_fraction
    page.mouse.move(sx, sy)
    page.mouse.down()
    page.mouse.move(sx + 8, sy)
    page.wait_for_timeout(50)
    assert page.locator('[data-role="drag-overlay"]').count() == 1, (
        "reorder pointer move did not arm the drag overlay"
    )
    page.mouse.move((sx + tx) / 2, (sy + ty) / 2, steps=5)
    page.mouse.move(tx, ty, steps=5)
    page.wait_for_timeout(50)
    assert page.locator('[data-role="drop-indicator"]').count() == 1, (
        "reorder pointer move did not expose a drop indicator"
    )
    page.mouse.up()


def test_s77_capability_manifest_ui(ui_f2: UiSession) -> None:
    session = ui_f2
    page = session.page
    page.wait_for_selector('[data-goal-id="SYNDAY01"]', timeout=10000)

    rows = json.loads(MANIFEST.read_text())
    # WP-A (commit 46fa17b, docs/COMMENTS_SPEC.md) pushed F5 from 26 to 29 rows — three new
    # HTTP/MCP-only rows (`create_comment`/`reply_comment`/`resolve_comment`, `ui_selector: null`
    # at the time, matching `bulk_update`/`set_color`'s own established shape) — but that commit's
    # own "make test-static test-core test-http test-mcp" run never touched this suite (`docs/
    # COMMENTS_SPEC.md`: "No web/ changes"), so this assertion went stale until WP-B's own
    # `make test-ui` run surfaced it. Fixed here, not silently: none of the sweeps below needed a
    # change (`board_rows`/`expected` both already filter on `row["ui_selector"] is not None`, the
    # same shape `bulk_update`/`set_color` already exercised, so three more null rows pass through
    # unchanged) — this is the one number that named the old total.
    assert len(rows) == 29, (
        f"F5 must hold 29 rows (20 + D250's four doc capabilities + D254's link/unlink + WP-A's "
        f"three comment capabilities), found {len(rows)}"
    )
    # "Remove from vertical" left the goal's menu with its systematic order (docs/design-handoff S5.P5.007): park is
    # HTTP/MCP only now.
    park_rows = [row for row in rows if row["cap"] == "park"]
    assert park_rows == [{
        "cap": "park",
        "ui_selector": None,
        "http_method": "POST",
        "http_path": "/api/goals/{id}/park",
        "mcp_tool": "park",
        "mcp_args": {"id": "<id>"},
    }]

    scheduled = httpx.put(
        f"{session.backend.base_url}/api/goals/SYNSUB01/schedule",
        json={"vertical": "day", "anchor_date": "2026-08-08"},
        headers={"Authorization": f"Bearer {session.backend.token}"},
        timeout=10,
    )
    assert scheduled.status_code == 200, scheduled.text
    page.reload()

    # Open the detail surface too: the scenario allows a row's selector to resolve on the board,
    # a card, the detail surface or the bulk bar, so all of those must be on screen before the
    # resolution pass runs. The detail surface is the only one that needs a gesture to exist.
    # D142: nested board hierarchy is already expanded and has no collapse control.
    assert page.locator('[data-role="subgoal-toggle"]').count() == 0
    activate_column(page, "day")
    activate_column(page, "day")  # D244: the nested reorder grip unfolds with its column
    page.click('[data-goal-id="SYNSUB01"] > [data-cap=reorder]')
    # D186: the detail surface opens INLINE on the board card now; the breadcrumb belongs to
    # the drawer/modal fallback only (D189), so the inline container is the open-marker.
    page.wait_for_selector('#goal-detail[data-role="inline-detail"]', timeout=5000)

    # `capture_maybe` resolves on Inbox, not the board (ruling 1, see this file's own module
    # docstring) — checked in its own pass, on its own screen, since no other row shares it.
    #
    # `reorder` is back in the ordinary sweep, reversing the exclusion row 127 added: the gesture
    # exists again as a drag and its selector is a resting element (`_selector_of`'s doc comment
    # has the full history). Nothing special is needed for it here, which is the point.
    #
    # `bulk_update` is the `null`-selector row now (`_selector_of`'s doc comment): the owner's
    # 2026-08-09 click-opens ruling removed the selection gesture and the bulk bar, so there is no
    # element for this row to resolve against and nothing to click. Its absence from the DOM is
    # asserted below — a `[data-cap=bulk]` element reappearing would mean the ruling regressed.
    gesture_caps = {"set_tags", "list_tags"}
    board_rows = [
        row
        for row in rows
        if row["cap"] not in {"capture_maybe", *gesture_caps}
        and row["ui_selector"] is not None
    ]
    unresolved = [row for row in board_rows if page.locator(_selector_of(row)).count() == 0]

    tags_rows = [row for row in rows if row["cap"] in {"set_tags", "list_tags"}]
    _open_tags(page, "SYNSUB01")
    unresolved.extend(
        row for row in tags_rows if page.locator(_selector_of(row)).count() == 0
    )
    _close_tags(page)

    # `set_color` joined `bulk_update` in the `null`-selector shape: D203 removed the colour
    # picker from goal detail (card colour still renders from stored data; the capability stays
    # PATCH-able over HTTP/MCP). An element answering the old selector would mean the removal
    # regressed, so its absence is asserted the same way bulk's is below.
    assert page.locator("[data-cap=set-color]").count() == 0, (
        "`[data-cap=set-color]` must not exist anywhere — D203 removed the colour picker from "
        "the detail surface (set_color stays HTTP/MCP-only, `ui_selector: null`)"
    )

    # `filter_value` is the third `null` row: the D238 nav links that carried `[data-cap=value-filter]` went with the
    # bottom bar (3bc40f9). A value is an area token in the field now, and the field filters in the browser.
    assert page.locator("[data-cap=value-filter]").count() == 0, (
        "`[data-cap=value-filter]` must not exist anywhere — the value links left with the bottom bar (3bc40f9); "
        "a value is an area token in the field, which filters in the browser (filter_value stays HTTP/MCP-only, "
        "`ui_selector: null`)"
    )

    assert page.locator("[data-cap=bulk]").count() == 0, (
        "`[data-cap=bulk]` must not exist anywhere — the owner's 2026-08-09 ruling removed the "
        "selection gesture and the bulk bar (bulk stays HTTP/MCP-only, `ui_selector: null`); an "
        "element answering this selector means the ruling has regressed"
    )

    capture_maybe_row = next(row for row in rows if row["cap"] == "capture_maybe")
    # The inline detail opened above (`SYNSUB01`) still owns the card row until a real close.
    # Escape is the same close path S-66/S-104 exercise, not a new gesture invented here. SYNSUB01 is drawn under
    # SYNDAY01: the first Escape goes up to SYNDAY01 (flow 4, as in S-68), the second closes.
    page.keyboard.press("Escape")
    page.wait_for_selector('.goal-card--detail-open[data-goal-id="SYNDAY01"]', timeout=5000)
    page.keyboard.press("Escape")
    page.wait_for_selector('#goal-detail[data-role="inline-detail"]', state="detached", timeout=5000)

    move_group = '[data-role="goal-context-menu"] [data-menu-section="move"]'
    activate_column(page, "day")
    page.click('[data-goal-id="SYNDAY01"] [data-role=goal-actions-trigger]')
    page.wait_for_selector(move_group, timeout=5000)
    assert page.locator("[data-cap=park]").count() == 0
    page.keyboard.press("Escape")
    page.wait_for_selector(move_group, state="hidden", timeout=5000)

    # `due_ack` left the card's menu with the roll (docs/design-handoff S4.P1.020): its row is
    # HTTP/MCP only now (`ui_selector: null`), and a carried plan's menu must not offer it.
    live_ghost = _seed_live_ghost(session, "SYN s77 carried plan")
    page.goto(f"{session.base_url}/h/{date.today().isoformat()}")
    page.wait_for_selector(f'[data-goal-id="{live_ghost.id}"]', timeout=5000)
    activate_column(page, "year")
    page.click(f'[data-goal-id="{live_ghost.id}"] [data-role=goal-actions-trigger]')
    page.wait_for_selector(move_group, timeout=5000)
    assert page.locator("[data-cap=due-ack]").count() == 0
    page.keyboard.press("Escape")
    page.goto(session.base_url)
    page.wait_for_selector('[data-goal-id="SYNDAY01"]', timeout=5000)

    switch_view(page, "inbox")
    page.wait_for_selector('[data-cap="inbox"]')
    if page.locator(_selector_of(capture_maybe_row)).count() == 0:
        unresolved.append(capture_maybe_row)

    if unresolved:
        missing_selectors = sorted({_selector_of(r) for r in unresolved})
        distinct_selectors = {_selector_of(r) for r in rows if r["ui_selector"] is not None}
        caps = ", ".join(r["cap"] for r in unresolved)
        gate(
            f"{len(unresolved)} of the 20 F5 rows have no element to resolve against: "
            f"{len(missing_selectors)} of the {len(distinct_selectors)} distinct resolved "
            "non-null `ui_selector`s are absent from "
            f"the built app — {', '.join(missing_selectors)} (rows: {caps}). `reorder` is back "
            "in this sweep (row 129): the 2026-08-09 drag rulings rebuilt within-column reorder, "
            "so it resolves against the card row it is armed from, not against the mid-gesture "
            "drop indicator. `web/src/**` now ships `[data-cap=]` values nav, inbox, search, "
            "search-input, search-results, sample-banner, remove-sample, create-goal, schedule, "
            "complete, edit-title, edit-body and set-tags — "
            "the detail surface's editing "
            "controls landed with `GoalDetailEditor.vue` (set-color left with D203). "
            "`capture_maybe` is no longer among the "
            "missing either: rows 108/116(b) ruled it the `create-goal` gesture scoped to the "
            "Maybe column, so it resolves as `[data-vertical=maybe] [data-cap=create-goal]` "
            "against the control that already exists, with no second `data-cap` value and no "
            "wrapper element added to answer a selector. `bulk_update` carries `ui_selector: "
            "null` — the owner's 2026-08-09 click-opens ruling removed the selection gesture and "
            "the bulk bar, so it is HTTP/MCP-only and its selector's absence is asserted, not "
            "resolved. Whatever remains above is a real missing "
            "entry point, and until it lands neither half of this scenario (selector resolution, "
            "and the route each affordance issues) can be observed for the whole manifest"
        )

    # The sweep above left the app on Inbox, and the URL now carries the view (`#inbox`), so a
    # reload would restore Inbox rather than the board every block below is written against.
    switch_view(page, "verticals")
    page.wait_for_selector('[data-goal-id="SYNDAY01"]', timeout=10000)

    by_cap = {row["cap"]: row for row in rows}
    observed: set[tuple[str, str, str]] = set()
    activation_start = len(session.request_log)

    # `list_tags` is a display capability, not a write affordance. Loading the UI activates its
    # GET; the selector-resolution pass above separately proves the returned tags have a live
    # display surface once the real Tags trigger is opened.
    _activate_row(session, by_cap["list_tags"], page.reload, observed)
    page.wait_for_selector('[data-goal-id="SYNDAY01"]', timeout=10000)

    # `filter_value` has no activation here: its value is an area token in the field, which narrows the loaded board in
    # the browser (3bc40f9, tests/ui/test_value_bar.py), so the row carries `ui_selector: null` and its filtered board
    # GET is HTTP/MCP-only, like `bulk_update` and `set_color`.

    # Capture in Inbox and ordinary create on the board share one control implementation but
    # carry distinct manifest rows. Enter is the committing gesture in both surfaces.
    switch_view(page, "inbox")
    page.wait_for_selector('[data-cap="inbox"]')
    maybe_add = _selector_of(by_cap["capture_maybe"])
    maybe_editor = _prepare_inline_add(page, maybe_add, "Manifest inbox capture")
    _activate_row(
        session,
        by_cap["capture_maybe"],
        lambda: page.press(maybe_editor, "Enter"),
        observed,
    )

    switch_view(page, "verticals")
    page.wait_for_selector('[data-goal-id="SYNDAY01"]', timeout=10000)
    activate_column(page, "day")
    day_add = '[data-vertical="day"] [data-cap=create-goal]'
    day_editor = _prepare_inline_add(page, day_add, "Manifest day create")
    _activate_row(
        session,
        by_cap["create_goal"],
        lambda: page.press(day_editor, "Enter"),
        observed,
    )

    # Same checkbox capability, two independent fixture states and therefore two F5 rows. Keeping
    # them independent avoids coupling uncomplete to optimistic completed-card reordering.
    complete = '[data-goal-id="SYNCOL07"] > [data-cap=reorder] [data-cap=complete]'
    uncomplete = '[data-goal-id="SYNDON01"] > [data-cap=reorder] [data-cap=complete]'
    page.wait_for_selector(f'{complete}[aria-checked="false"]', timeout=5000)
    page.wait_for_selector(f'{uncomplete}[aria-checked="true"]', timeout=5000)
    _activate_row(session, by_cap["complete"], lambda: page.click(complete), observed)
    _activate_row(session, by_cap["uncomplete"], lambda: page.click(uncomplete), observed)

    # Within-column reorder runs before reparent/detach reshape the weekly sibling set. Carryover
    # ghosts share this rendered column but not its stored sibling group, so use two adjacent
    # current-period rows: moving the first before the fourth emits `after_id` for the third.
    activate_column(page, "week")
    reorder_source = '[data-goal-id="SYNORD01"] > [data-cap="reorder"]'
    reorder_target = '[data-goal-id="SYNORD04"] > [data-cap="reorder"]'
    _activate_row(
        session,
        by_cap["reorder"],
        lambda: _reorder_to_edge(page, reorder_source, reorder_target, 0.15),
        observed,
    )

    # Detail editor: real card-row click, then title/body/tags/colour controls. Body persists on
    # blur; pressing the open card's "..." supplies that blur on the way to its Tags submenu.
    activate_column(page, "day")
    page.click('[data-goal-id="SYNCOL06"] > [data-cap=reorder]')
    # D187: the opened card's own compact row is the editor's identity rail — `edit-title` sits
    # on the HOST CARD's title, above the `#goal-detail` container that expands beneath it.
    page.wait_for_selector('[data-goal-id="SYNCOL06"] [data-cap="edit-title"]', timeout=5000)

    title = '[data-goal-id="SYNCOL06"] [data-cap="edit-title"]'
    page.click(title)
    page.fill(f"{title}:is(textarea)", "Manifest title edit")
    _activate_row(
        session,
        by_cap["edit_title"],
        lambda: page.press(f"{title}:is(textarea)", "Enter"),
        observed,
    )

    body = '#goal-detail [data-cap="edit-body"]'
    page.click(body)
    page.fill(body, "Manifest body edit")
    _activate_row(
        session,
        by_cap["edit_body"],
        lambda: page.click('[data-goal-id="SYNCOL06"].goal-card--detail-open [data-role="goal-actions-trigger"]'),
        observed,
    )
    page.click('[data-role="goal-actions-menu"] [data-action="tags"] button')
    page.wait_for_selector('#dropdownPortal [data-role="tag-chips"]', timeout=5000)

    tag_input = '#dropdownPortal [data-role="tag-chips"] [data-cap="set-tags"]'
    page.fill(tag_input, "manifest-tag")
    _activate_row(
        session,
        by_cap["set_tags"],
        lambda: page.press(tag_input, "Enter"),
        observed,
    )
    _close_tags(page)

    # `set_color` has no activation here: D203 removed the colour picker, the row carries
    # `ui_selector: null`, and null rows are HTTP/MCP-only by the manifest's own shape.

    # Pick Tomorrow from the detail schedule surface: the open goal's date, the first fact under its title (GoalFacts.vue,
    # the opened-card cleanup, KK 27-28 Sep 2026). Clearing schedule lives in the card menu's
    # `Move to Inbox` action; it is the same PUT route in the manifest's null state.
    page.click('[data-goal-id="SYNCOL06"].goal-card--detail-open .goal-facts [data-cap="schedule"]')
    page.wait_for_selector('[data-role="schedule-footer"]', timeout=5000)
    _activate_row(
        session,
        by_cap["schedule"],
        lambda: page.click(
            '#dropdownPortal [data-role="schedule-footer"] [data-period-key="2026-08-09"]'
        ),
        observed,
    )
    page.keyboard.press("Escape")
    page.wait_for_selector(
        '#goal-detail[data-role="inline-detail"]', state="detached", timeout=5000,
    )

    _open_card_menu(page, "day", "SYNCOL05")
    _activate_row(
        session,
        by_cap["unschedule"],
        lambda: page.click('#dropdownPortal [data-action="inbox"]'),
        observed,
    )

    # Reparent and detach are two rows of the menu's Under step (docs/design-handoff S5.P5.012).
    _open_reparent_menu(page, "week", "SYNORD03")
    _activate_row(
        session,
        by_cap["reparent"],
        lambda: page.click('[data-role="move-step"] [data-parent-id="SYNSCH01"]'),
        observed,
    )
    _open_reparent_menu(page, "week", "SYNORD03")
    _activate_row(
        session,
        by_cap["detach"],
        lambda: page.click('[data-role="move-step"] [data-parent-id=""]'),
        observed,
    )

    # Leaf delete succeeds directly. Subtree delete intentionally receives one 409 first; that
    # is how the UI reveals its explicit `Delete all` action instead of guessing cascade intent.
    _open_card_menu(page, "day", "SYNCOL03")
    _activate_row(
        session,
        by_cap["delete_leaf"],
        lambda: page.click('#dropdownPortal [data-action="delete"]'),
        observed,
    )

    session.expects_network_failures = True
    _open_card_menu(page, "day", "SYNDAY01")
    page.click('#dropdownPortal [data-action="delete"]')
    page.get_by_role("button", name="Delete all", exact=True).wait_for(timeout=5000)
    _activate_row(
        session,
        by_cap["delete_subtree"],
        lambda: page.get_by_role("button", name="Delete all", exact=True).click(),
        observed,
    )

    expected = {
        (row["cap"], row["http_method"], row["http_path"])
        for row in rows
        if row["ui_selector"] is not None
    }
    assert observed == expected, (
        f"activation coverage mismatch: missing caps={sorted(cap for cap, _, _ in expected - observed)}, "
        f"extra caps={sorted(cap for cap, _, _ in observed - expected)}"
    )

    writes = [
        request
        for request in session.request_log[activation_start:]
        if request["method"] in MUTATING_METHODS
    ]
    # The app's own daily carry-over (docs/design-handoff S4.P1.017) runs on every page load; it
    # is housekeeping, not a capability, the same carve-out as `tests/mcp/test_cross_transport.py`.
    off_manifest = [
        _route_shape(request)
        for request in writes
        if not any(_request_matches(row, request) for row in rows)
        and urlsplit(request["url"]).path != "/api/replan"
    ]
    assert off_manifest == [], f"unmanifested mutating route shape(s): {off_manifest}"

    # The single error is deliberate discovery of subtree state. Assert it narrowly here because
    # the fixture teardown's opt-out is coarse and otherwise suppresses all network/console checks.
    assert len(session.bad_responses) == 1, "subtree delete must produce exactly one intentional 409"
    assert session.bad_responses[0].startswith("409 DELETE "), (
        "subtree delete's intentional response must be a DELETE 409"
    )
    assert session.failed_requests == [], "activation pass produced a failed network request"
    assert len(session.console_errors) == 1, (
        "subtree delete must produce exactly one intentional browser console error"
    )
    assert "409 (Conflict)" in session.console_errors[0], (
        "subtree delete's intentional console error must describe its DELETE 409"
    )
