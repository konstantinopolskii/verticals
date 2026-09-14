"""S-68 — L2: the ancestor chain is visible without navigating away.

docs/E2E.md §6 S-68. Fixture F2. Required by AC-107. Serves J1, L2.

Reshaped by the 2026-08-13 inline-detail round: the board goal's detail surface opens INLINE on
its own card (D186), and the breadcrumb now belongs only to the drawer/modal fallback for goals
absent from the board projection (D189). The chain a reader sees without navigating away is
D195's: the opened goal takes the exact hover wash on its card and PERSISTENTLY highlights every
rendered ancestor/descendant card across verticals (`goal-card--open-related`), while unrelated
siblings stay neutral. That highlight — on the ancestors' own cards, in their own columns — is
the ancestor chain made visible, and it is what this scenario asserts now.

Steps: schedule `SYNSUB01` onto the day board, open it inline. Assert: every fixture ancestor
that renders a board card carries the D195 highlight class; a neutral sibling does not;
`page.url()` changed by hash/param only; Escape returns to the board with the same scroll
position (±4 px) and drops the highlight.
"""

from __future__ import annotations

from urllib.parse import urlsplit

import httpx

from tests.ui.conftest import UiSession, activate_column

# `tests/fixtures/f2_synth.sql` lines 34-45: SYNSUB01's stored `path` is
# `/SYNLIF01/SYNDEC01/SYNYRR01/SYNQ1R01/SYNQ2R01/SYNDAY01/SYNSUB01/`, so these six ids ARE the
# ancestor chain, root-to-parent. Read from the SQL, not invented — a fixture edit that reroots
# the row fails this test rather than silently passing a stale list.
ANCESTOR_IDS = ["SYNLIF01", "SYNDEC01", "SYNYRR01", "SYNQ1R01", "SYNQ2R01", "SYNDAY01"]

# A day-column card outside SYNSUB01's ancestry and subtree (`f2_synth.sql`): D195's "unrelated
# sibling tasks remain neutral" needs a witness, or the assertion above could pass because the
# class landed on every card on the board.
UNRELATED_ID = "SYNCOL01"

SUB_TITLE = '[data-goal-id="SYNSUB01"] .goal-card__title'
INLINE_DETAIL = '#goal-detail[data-role="inline-detail"]'
RELATED_CLASS = "goal-card--open-related"


def _url_parts(url: str) -> tuple[str, str, str, str]:
    """(scheme, netloc, path, query) — everything S-68 requires to be *unchanged*. The fragment
    is deliberately excluded: it is the one component the scenario permits to move."""
    p = urlsplit(url)
    return (p.scheme, p.netloc, p.path, p.query)


def _has_related_class(page, goal_id: str) -> bool:
    classes = page.locator(f'[data-goal-id="{goal_id}"]').first.get_attribute("class") or ""
    return RELATED_CLASS in classes.split()


def test_s68_ancestor_chain_visible(ui_f2: UiSession) -> None:
    session = ui_f2
    page = session.page

    # R7 hides parked children from board subgoal lists. Recommit this legacy fixture child to
    # its parent's day vertical; ancestry stays byte-identical and remains this scenario's subject.
    scheduled = httpx.put(
        f"{session.backend.base_url}/api/goals/SYNSUB01/schedule",
        json={"vertical": "day", "anchor_date": "2026-08-08"},
        headers={"Authorization": f"Bearer {session.backend.token}"},
        timeout=10,
    )
    assert scheduled.status_code == 200, scheduled.text
    page.reload()
    url_before = page.url
    # D142: the nested row is already present; no collapse control remains.
    assert page.locator('[data-role="subgoal-toggle"]').count() == 0
    # D244: SYNSUB01 is SYNDAY01's same-column subtask — folded into the compact day column's
    # stack until the column expands. Expanding is the user's own header gesture, and the URL
    # does not move for it, so `url_before` above stays the scenario's baseline.
    activate_column(page, "day")
    page.wait_for_selector(SUB_TITLE, timeout=10000)

    # Scroll the page to a non-zero offset first: "returns to the board with the same scroll
    # position" is unfalsifiable at 0, which is where a freshly loaded board sits. The board's own
    # vertical extent at 1458x779 is what makes any offset available at all, so the target is
    # clamped by the document rather than asserted to be a specific number.
    page.evaluate("window.scrollTo(0, Math.min(200, document.body.scrollHeight))")
    page.wait_for_timeout(50)
    scroll_before = page.evaluate("window.scrollY")

    # No highlight before the open — the class is the OPEN state's cue, not a hover leftover.
    for ancestor_id in ANCESTOR_IDS:
        if page.locator(f'[data-goal-id="{ancestor_id}"]').count():
            assert not _has_related_class(page, ancestor_id), (
                f"ancestor card carries {RELATED_CLASS} before anything is open"
            )

    # --- open the detail surface (inline, D186) ---------------------------------------------------
    session.gestures.click(SUB_TITLE)
    page.wait_for_selector(INLINE_DETAIL, timeout=5000)

    # --- the chain: every RENDERED ancestor card is highlighted (D195) ----------------------------
    rendered = [a for a in ANCESTOR_IDS if page.locator(f'[data-goal-id="{a}"]').count()]
    assert rendered, (
        "no ancestor renders a board card at all — the fixture no longer exercises the scenario"
    )
    assert "SYNDAY01" in rendered, "the direct parent must render on the day board"
    for ancestor_id in rendered:
        assert _has_related_class(page, ancestor_id), (
            f"rendered ancestor {ancestor_id} is not highlighted while its descendant is open "
            f"(D195: the chain must be visible without navigating away)"
        )

    # --- and an unrelated sibling stays neutral (D195's other half) -------------------------------
    assert page.locator(f'[data-goal-id="{UNRELATED_ID}"]').count() == 1
    assert not _has_related_class(page, UNRELATED_ID), (
        f"unrelated card {UNRELATED_ID} caught the open-chain highlight — the cue no longer "
        f"distinguishes the chain from the rest of the board"
    )

    # --- the URL moved by fragment only ------------------------------------------------------------
    url_open = page.url
    assert _url_parts(url_open) == _url_parts(url_before), (
        f"opening the detail surface changed more than the hash/query: {url_before} -> {url_open}"
    )
    assert urlsplit(url_open).fragment == "goal/SYNSUB01", (
        f"expected the fragment to name the open goal, got {urlsplit(url_open).fragment!r}"
    )

    # --- Escape returns to the board at the same scroll position (+-4 px) ---------------------------
    page.keyboard.press("Escape")
    page.wait_for_selector(INLINE_DETAIL, state="detached", timeout=5000)

    # The board is what is on screen again, not an emptied page: spot-check the card that was
    # clicked is still rendered where it was, and the chain highlight is gone with the open state.
    assert page.locator(SUB_TITLE).count() == 1, "the board did not come back after Escape"
    for ancestor_id in rendered:
        assert not _has_related_class(page, ancestor_id), (
            f"ancestor {ancestor_id} still highlighted after close — the cue leaked past its state"
        )

    scroll_after = page.evaluate("window.scrollY")
    assert abs(scroll_after - scroll_before) <= 4, (
        f"scroll position moved across open/close: {scroll_before} -> {scroll_after}"
    )

    url_after = page.url
    assert _url_parts(url_after) == _url_parts(url_before), (
        f"closing the detail surface changed more than the hash/query: {url_before} -> {url_after}"
    )
