from __future__ import annotations

import psycopg

from tests.ui.conftest import UiSession, activate_column


def test_r11_project_tag_chip_is_distinct(ui_f2: UiSession) -> None:
    session = ui_f2
    with psycopg.connect(session.backend.dsn, autocommit=True) as conn:
        conn.execute("UPDATE goals SET tags = ARRAY['SYNTAG1','plain'] WHERE id = 'SYNORD01'")
        conn.execute("INSERT INTO tag_meta(tag, project) VALUES ('SYNTAG1', true)")
    session.page.reload()

    card = session.page.locator('[data-goal-id="SYNORD01"]')
    # D115: tags are absent from board cards but remain editable in detail.
    assert card.locator('[data-role="tag-chips"], [data-role="tag-chip"], [data-role="project-tag-chip"]').count() == 0
    activate_column(session.page, "week")
    card.locator('.goal-card__title').click()
    # An open goal's tags are in its "..." menu, "Tags..." (the opened-card cleanup, KK 27-28 Sep 2026).
    session.gestures.click('[data-goal-id="SYNORD01"].goal-card--detail-open [data-role="goal-actions-trigger"]')
    session.gestures.click('[data-role="goal-actions-menu"] [data-action="tags"] button')
    panel = session.page.locator('#dropdownPortal [data-role="tag-chips"]')
    panel.wait_for(state="visible")
    # Tabler round: the chip's remove affordance is an IconX svg now, not a text "×" —
    # match the tag text and require the icon inside the same chip.
    for tag in ("SYNTAG1", "plain"):
        chip = panel.locator('[data-cap="set-tags"]', has_text=tag)
        assert chip.count() == 1
        assert chip.locator("svg").count() == 1


def test_r12_size_fields_week_day_only_and_actual_readonly(ui_f2: UiSession) -> None:
    session = ui_f2
    with psycopg.connect(session.backend.dsn, autocommit=True) as conn:
        conn.execute(
            "UPDATE goals SET size_expected = '[\"45-120m\",\"45-120m\"]', "
            "size_actual = '[\"10-15m\"]' WHERE id = 'SYNORD01'"
        )

    session.page.reload()
    activate_column(session.page, "week")
    # D232 banding sorts this parentless week root LAST, which drops its title centre into the
    # neighbouring column's hover-promotion wedge — click the title's left edge, which stays in
    # week territory, instead of the geometric centre.
    session.page.locator('[data-goal-id="SYNORD01"] .goal-card__title').click(
        position={"x": 12, "y": 10}
    )
    session.page.locator('[data-role="size-fields"]').wait_for(state="visible")
    # D212-era footer: the section shows a compact summary button; the Plan input and the Actual
    # line mount inside its popover, so the popover is opened the way a user opens it.
    session.page.locator('[data-role="size-summary"]').click()
    session.page.locator('[data-role="size-expected"]').wait_for(state="visible")
    assert session.page.locator('[data-role="size-expected"]').input_value() == "2x45-120"
    actual = session.page.locator('[data-role="size-actual"]')
    # Actual is read-only by construction now: a <p>, not an input at all.
    assert actual.evaluate("el => el.tagName") == "P"
    assert "1 × 15-min shot" in (actual.text_content() or "")
    session.page.keyboard.press("Escape")  # closes the shot-size popover
    session.page.locator('[data-role="size-expected"]').wait_for(state="hidden")
    session.page.keyboard.press("Escape")  # closes the inline detail
    session.page.wait_for_selector('#goal-detail[data-role="inline-detail"]', state="detached")

    activate_column(session.page, "month")
    session.page.locator('[data-goal-id="SYNSCH01"] .goal-card__title').click()
    assert session.page.locator('[data-role="size-fields"]').count() == 0
