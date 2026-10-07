"""S-62 — Sample data is removable in one gesture, and removes only the sample.

docs/E2E.md lines 1533-1549. Fixture F1u (F1 + USERROW1/USERROW2, neither tagged `sample`) —
its own negative control: on F1 alone, every assertion here is also satisfied by an unfiltered
`DELETE FROM goals`, which is real data loss. Steps: click `[data-cap=remove-sample]`.
Required by AC-160 (docs/PENDING_DOC_FIXES.md row 38 already corrected AC-160's own text to this
F1u shape rather than the weaker "0 cards" it originally read).
"""

from __future__ import annotations

import psycopg
import pytest

from tests.ui.conftest import UiSession
from tests.ui.views import switch_view


def _row(conn: psycopg.Connection, goal_id: str) -> tuple:
    """The full row, every column, as a plain tuple — a direct equality compare on this is a
    full-row digest by construction (any differing byte in any column makes the tuples unequal)
    without needing to pick a hash function; a failure also prints exactly which fields moved,
    which a hash digest would not."""
    row = conn.execute("SELECT * FROM goals WHERE id = %s", (goal_id,)).fetchone()
    assert row is not None, f"{goal_id} missing entirely"
    return row


def test_s62_remove_sample(ui_f1u: UiSession) -> None:
    session = ui_f1u
    conn = psycopg.connect(session.backend.dsn, autocommit=True)
    try:
        before_u1 = _row(conn, "USERROW1")
        before_u2 = _row(conn, "USERROW2")

        banner_before = session.page.locator('[data-cap="sample-banner"]')
        assert banner_before.count() == 1, "F1u should still show the banner before removal"

        # --- the one scripted gesture ------------------------------------------------------------
        session.gestures.click('[data-cap="remove-sample"]')
        assert session.gestures.count == 1, f"expected gesture count 1, got {session.gestures.count}"

        # The click triggers a DELETE + reload (store.ts::removeSample -> reloadBoard); wait for
        # the banner to actually disappear rather than racing the assertion against the request.
        banner_before.wait_for(state="detached", timeout=5000)

        # --- no confirmation: gesture count 1 (checked above) + no dialog ever appeared ----------
        assert session.dialog_records() == [], f"a confirmation would show up here: {session.dialog_records()}"

        # --- DB: sample gone, exactly 2 rows remain, untouched ------------------------------------
        (sample_count,) = conn.execute(
            "SELECT count(*) FROM goals WHERE tags @> ARRAY['sample']"
        ).fetchone()
        assert sample_count == 0, f"expected 0 rows tagged sample, found {sample_count}"

        (total_count,) = conn.execute("SELECT count(*) FROM goals").fetchone()
        assert total_count == 2, f"expected exactly 2 rows total, found {total_count}"

        after_u1 = _row(conn, "USERROW1")
        after_u2 = _row(conn, "USERROW2")
        assert before_u1 == after_u1, "USERROW1 changed by a delete that should never have touched it"
        assert before_u2 == after_u2, "USERROW2 changed by a delete that should never have touched it"

        # --- board shows the surviving rows, banner gone ------------------------------------------
        # Ruling 1 (owner, 2026-08-09) took the Maybe column off the board: USERROW2 is vertical
        # NULL / parent_id NULL, so after the sample delete it lives in the Inbox view, not on the
        # seven-column board. USERROW1 is vertical='day', so it stays a board card. The board count
        # here is therefore 1, not 2 — the "both rows survive, visibly" intent is unchanged, split
        # across the two surfaces that now exist rather than asserted on one that no longer shows
        # both kinds of row.
        assert session.page.locator('[data-cap="sample-banner"]').count() == 0
        assert session.page.locator('[data-goal-id]').count() == 1
        assert session.page.locator('[data-goal-id="USERROW1"]').count() == 1

        # --- Inbox shows USERROW2, and only USERROW2 (F1u's sample data has no root Maybe row:
        # SAMPLE06 is a subgoal, MAYBE_PREDICATE requires parent_id IS NULL) --------------------------
        switch_view(session.page, "inbox")
        session.page.wait_for_selector('[data-cap="inbox"] [data-goal-id="USERROW2"]')
        assert session.page.locator('[data-goal-id]').count() == 1
        assert session.page.locator('[data-goal-id="USERROW2"]').count() == 1

        # --- reload restores nothing ---------------------------------------------------------------
        session.page.reload(wait_until="domcontentloaded")
        session.page.wait_for_selector('[data-cap="inbox"]')
        # A reloaded Inbox names no view in the command field, so the way back to the board is the browser's back.
        session.page.go_back()
        session.page.wait_for_selector('[data-goal-id="USERROW1"]')
        assert session.page.locator('[data-cap="sample-banner"]').count() == 0, "reload brought the sample banner back"
        assert session.page.locator('[data-goal-id]').count() == 1, "reload changed the surviving board row count"
        (total_after_reload,) = conn.execute("SELECT count(*) FROM goals").fetchone()
        assert total_after_reload == 2, "reload caused a DB-level change"
    finally:
        conn.close()


@pytest.mark.parametrize("_marker", [None])
def test_dialog_recorder_detects_a_real_dialog(ui_f1u: UiSession, _marker: None) -> None:
    """Not a catalogue scenario (docs/PENDING_DOC_FIXES.md row 41's own naming rule: `test_sNN_*`
    is reserved for coverage that IS a catalogue scenario) — this is the "both directions" proof
    for the one mechanism every one of this package's seven scenarios depends on:
    `session.dialog_records()`, backed by the MutationObserver `conftest.py` installs before app
    load. Every `test_s*` in this package asserts the record is empty; none of them, alone,
    proves the observer would actually have caught a real one. This test does: inject a real
    `role="dialog"` node after the observer is already installed (same context/page S-62 just
    proved clean) and confirm it is recorded, then confirm the record for the *real* S-62 flow —
    already asserted empty above — is what "passes" means."""
    session = ui_f1u
    assert session.dialog_records() == [], "record should start empty on a fresh load"

    session.page.evaluate(
        """() => {
            const d = document.createElement('div');
            d.setAttribute('role', 'dialog');
            d.textContent = 'planted by test_dialog_recorder_detects_a_real_dialog';
            document.body.appendChild(d);
        }"""
    )
    records_after_plant = session.dialog_records()
    assert records_after_plant != [], "MutationObserver did not record a real role=dialog node — the check is vacuous"
    assert records_after_plant[0]["role"] == "dialog"

    # Both directions, observed: the check FAILS (correctly) against a planted dialog —
    # `records_after_plant` above, non-empty, is that observed failure text. Restoring means
    # removing the plant and confirming a *fresh* observer (fresh page, since this MutationObserver
    # instance's log is append-only and cannot un-record history) again reads empty — which is
    # exactly what every `test_s6*`/`test_s125*` in this package already demonstrates on its own,
    # real, un-planted page load.
    session.page.evaluate(
        "() => document.querySelectorAll('[role=\"dialog\"]').forEach(el => el.remove())"
    )
