"""V2 R1: every vertical column carries its semantic verb once."""

from __future__ import annotations

from tests.ui.conftest import UiSession


LADDER = (
    ("life", "become"),
    ("decade", "visualise"),
    ("year", "bet"),
    ("quarter", "achieve"),
    ("month", "plan"),
    ("week", "execute"),
    ("day", "focus"),
)


def test_v2_column_add_prompts_render_once_in_ladder_order(ui_f2: UiSession) -> None:
    page = ui_f2.page
    page.wait_for_selector('[data-vertical="day"] [data-cap="create-goal"]', timeout=10_000)

    found = []
    for vertical, expected in LADDER:
        prompts = page.locator(f'[data-vertical="{vertical}"] [data-cap="create-goal"]')
        assert prompts.count() == 1, f"{vertical} must render exactly one add prompt"
        found.append(prompts.inner_text().strip())

    # D112-D113: verbs moved from headers to action-only prompts, with no Add prefix.
    assert found == [f"{verb.capitalize()}…" for _vertical, verb in LADDER]
    assert page.locator('[data-role="column-verb"]').count() == 0


def test_v2_three_year_header_uses_generic_headline_and_period_label(ui_f2: UiSession) -> None:
    page = ui_f2.page
    header = page.locator('[data-vertical="decade"] .column-header')
    assert header.locator('.t-title').inner_text().strip() == "3 years"
    assert header.locator('.t-caption').inner_text().strip() == "2026–2028"
    assert header.locator('[data-role="column-verb"]').count() == 0
