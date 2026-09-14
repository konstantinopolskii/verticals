"""S-61 — Stage 0: first run shows a worked example, not seven empty columns.

docs/E2E.md lines 1520-1531. Fixture F1 on a fresh database. Steps: navigate to `/`.
Required by AC-159 (exactly 6 cards -> corrected to "5-plus-1" by S-61's own text, which
`ACCEPTANCE.md` AC-159's row already restates the same way) and AC-192 (no signup/quiz/tour/
dialog).
"""

from __future__ import annotations

import re
import time

from tests.ui.conftest import UiSession, activate_column

_EMOJI_RE = re.compile(
    "[\U0001f300-\U0001faff☀-➿←-⇿⬀-⯿]", re.UNICODE
)


def _top_level_card_count(session: UiSession, vertical: str) -> int:
    """Direct children of that column's `.card-stack` only — a nested subgoal (rendered inside
    another card's `.goal-card__children`) is a descendant of the column too, so a plain
    descendant selector would over-count it. `Column.vue`'s own template is the source for this
    shape: `KCardStack` (`.card-stack`, per `Board.vue`'s own comment on the same mechanism) is
    the direct parent of every top-level `GoalCard`."""
    return session.page.locator(f'[data-vertical="{vertical}"] .card-stack > [data-goal-id]').count()


def test_s61_stage_zero_worked_example(ui_f1: UiSession) -> None:
    session = ui_f1

    # --- paints within 1500 ms (S-61's own budget, not S-97's F4-567 number) -------------------
    t0 = time.monotonic()
    session.page.goto(session.base_url, wait_until="domcontentloaded")
    session.page.wait_for_selector('[data-goal-id="SAMPLE01"]')
    elapsed_ms = (time.monotonic() - t0) * 1000
    assert elapsed_ms < 1500, f"board took {elapsed_ms:.0f}ms to paint SAMPLE01, budget is 1500ms"

    # --- exactly 5 cards, one each in life/year/quarter/week/day -------------------------------
    for vertical in ("life", "year", "quarter", "week", "day"):
        count = _top_level_card_count(session, vertical)
        assert count == 1, f"{vertical} column: expected 1 top-level card, found {count}"

    # --- plus one same-vertical nested subgoal under SAMPLE05 (R7: no duplicate column card) ----
    # D142: board hierarchy is always expanded and exposes no collapse control.
    assert session.page.locator('[data-role="subgoal-toggle"]').count() == 0
    # D244: the compact day column folds SAMPLE06 into SAMPLE05's stack; expanding the column is
    # the reader's own gesture and restores the inline rendering this block pins.
    activate_column(session.page, "day")
    nested_selector = (
        '[data-goal-id="SAMPLE05"] + .goal-card__children [data-goal-id="SAMPLE06"]'
    )
    session.page.wait_for_selector(nested_selector)
    nested = session.page.locator(nested_selector).count()
    assert nested == 1, "SAMPLE06 must render once under SAMPLE05, not as a duplicate column card"

    # --- 6 goal rows in total (5 top-level + SAMPLE06) ------------------------------------------
    total_rows = session.page.locator("[data-goal-id]").count()
    assert total_rows == 6, f"expected 6 total goal rows (cards + nested subgoal), found {total_rows}"

    # --- month and decade columns render their empty state (zero cards, add-row still present) -
    for vertical in ("month", "decade"):
        count = _top_level_card_count(session, vertical)
        assert count == 0, f"{vertical} column: expected empty (0 cards), found {count}"
        add_selector = (
            f'[data-vertical="{vertical}"] '
            '[data-role="column-add"][data-cap="create-goal"]'
        )
        add_row = session.page.locator(add_selector)
        assert add_row.count() == 1, f"{vertical} column: expected its inline-add ghost row to still render"
        activate_column(session.page, vertical)
        add_row.click()
        editor = session.page.locator(
            f'[data-vertical="{vertical}"] '
            '[data-cap="create-goal"] input.column-add-editor'
        )
        editor.wait_for(state="visible")
        assert editor.count() == 1, f"{vertical} column: ghost row did not activate its add editor"
        editor.press("Escape")
        add_row.wait_for(state="visible")

    # --- sample banner present, sentence case, no emoji -----------------------------------------
    banner = session.page.locator('[data-cap="sample-banner"]')
    assert banner.count() == 1, "expected exactly one [data-cap=sample-banner]"
    assert banner.is_visible()
    banner_text = banner.inner_text().strip()
    assert banner_text, "banner has no text"
    assert not _EMOJI_RE.search(banner_text), f"banner text contains emoji: {banner_text!r}"
    assert banner_text[0].isupper(), f"banner text is not sentence case (first char): {banner_text!r}"
    assert banner_text != banner_text.upper(), f"banner text looks like shouty caps: {banner_text!r}"

    # --- no signup form, no quiz, no tour overlay -----------------------------------------------
    # No component in this tree implements a quiz or a tour overlay (the full inventory read this
    # session is Board/Column/ColumnHeader/GoalCard/InlineAdd/SchedulePopover/SearchBar/TagChip) —
    # true by construction, not asserted by a selector that would only prove one did not happen to
    # match today's class names. The password-field and dialog checks below are the two that a
    # regression could actually reintroduce.
    assert session.page.locator('input[type="password"]').count() == 0, "a password field would mean a signup form"
    body_text_lower = session.page.inner_text("body").lower()
    assert "quiz" not in body_text_lower

    # --- no role=dialog anywhere in the MutationObserver record ---------------------------------
    assert session.dialog_records() == [], f"dialog(s) recorded on first run: {session.dialog_records()}"
