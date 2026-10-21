"""System appearance follows the OS at startup and during editing, with real UI and data."""
from datetime import date
from pathlib import Path

import psycopg
import pytest
from playwright.sync_api import expect

from tests.ui.conftest import UiSession, activate_column, _backend, _static_server, _make_ui_session
from tests.ui.views import open_page, switch_view, tick
from tests.ui.test_agent_conversation import ui_agent  # noqa: F401
from verticals.core import comments, docs, goals


SHOTS = Path(__file__).resolve().parents[2] / "artifacts" / "system-theme"


@pytest.fixture(scope="module", params=["chromium", "webkit"])
def browser(playwright_driver, request):
    browser = getattr(playwright_driver, request.param).launch(headless=True)
    yield browser
    browser.close()


@pytest.fixture
def system_scheme(request):
    return getattr(request, "param", "light")


@pytest.fixture
def ui_f2(browser, f2_dsn, tmp_path, request, web_dist, ui_reduced_motion, system_scheme):
    with _backend(f2_dsn, "t1", tmp_path) as backend:
        with _static_server(backend.base_url, tmp_path) as base_url:
            yield from _make_ui_session(browser=browser, backend=backend, static_base_url=base_url,
                                        request=request, reduced_motion=ui_reduced_motion, color_scheme=system_scheme)


def _rgb(page, selector, prop="backgroundColor"):
    return page.locator(selector).first.evaluate(
        "(el, prop) => getComputedStyle(el)[prop]", prop,
    )


def _channels(value):
    if value.startswith("color(srgb "):
        rgb, _, alpha = value[11:-1].partition(" / ")
        return [float(c) * 255 for c in rgb.split()] + ([float(alpha)] if alpha else [])
    return [float(part) for part in value.removeprefix("rgb(").removeprefix("rgba(").rstrip(")").split(",")]


def _dark_surface(page, selector):
    value = _channels(_rgb(page, selector))
    assert max(value[:3]) < 80, (selector, value)
    assert len(value) == 3 or value[3] == 1, (selector, "transparent background")


def _contrast(page, selector, surface):
    foreground = _channels(_rgb(page, selector, "color"))
    background = _channels(_rgb(page, surface))
    return _contrast_colors(foreground, background)


def _contrast_colors(foreground, background):
    alpha = foreground[3] if len(foreground) == 4 else 1
    foreground = [fg * alpha + bg * (1 - alpha) for fg, bg in zip(foreground[:3], background[:3])]

    def luminance(rgb):
        linear = [(c / 255 / 12.92 if c / 255 <= .04045 else ((c / 255 + .055) / 1.055) ** 2.4) for c in rgb]
        return sum(c * weight for c, weight in zip(linear, (.2126, .7152, .0722)))

    a, b = sorted((luminance(foreground), luminance(background)))
    return (b + .05) / (a + .05)


def _shot(page, name):
    SHOTS.mkdir(parents=True, exist_ok=True)
    engine = page.context.browser.browser_type.name
    page.screenshot(path=str(SHOTS / f"{engine}-{page.viewport_size['width']}-{name}.png"), animations="disabled")


@pytest.mark.parametrize("system_scheme", ["light", "dark"], indirect=True)
@pytest.mark.parametrize("width", [1458, 390])
def test_initial_board_uses_system_appearance(ui_f2: UiSession, system_scheme, width):
    page = ui_f2.page
    page.set_viewport_size({"width": width, "height": 779})
    expect(page.locator(".pattern-vertical-board")).to_be_visible()
    _shot(page, f"board-{system_scheme}")
    if system_scheme == "dark":
        _dark_surface(page, "body")
        _dark_surface(page, ".app-shell")
        _dark_surface(page, ".goal-card")
        assert max(_channels(_rgb(page, ".goal-card__title", "color"))[:3]) <= 220
    else:
        assert _rgb(page, ".app-shell") == "rgb(255, 255, 255)"
    assert _contrast(page, ".goal-card__title", ".goal-card") >= 4.5


def test_live_appearance_changes_keep_task_draft_and_menu_readable(ui_f2: UiSession):
    page = ui_f2.page
    page.emulate_media(color_scheme="light")
    activate_column(page, "day")
    card = page.locator('[data-vertical="day"] .goal-card').first
    title = card.locator(".goal-card__title-text").first
    title.click()
    tick(page)
    title.click()
    draft = card.locator(".goal-card__title-input")
    expect(draft).to_be_visible()
    draft.fill("SYN draft survives system appearance")
    for scheme in ("dark", "light", "dark"):
        page.emulate_media(color_scheme=scheme)
        expect(draft).to_be_focused()
        expect(draft).to_have_value("SYN draft survives system appearance")
        if scheme == "dark":
            _dark_surface(page, ".app-shell")
            expect(draft).to_have_css("color", _rgb(page, ".app-shell", "color"))
            assert _contrast(page, ".goal-card__title-input", ".app-shell") >= 4.5
    draft.press("Enter")
    card.hover()
    card.locator(".goal-actions__trigger").click()
    menu = page.locator(".goal-actions__menu")
    expect(menu).to_be_visible()
    _dark_surface(page, ".goal-actions__menu")
    assert _contrast(page, ".goal-actions__item", ".goal-actions__menu") >= 4.5
    _shot(page, "task-menu-dark")


def test_documents_and_inbox_follow_live_changes(ui_f2: UiSession):
    with psycopg.connect(ui_f2.backend.dsn, autocommit=True) as conn:
        doc_id = docs.create(conn, owner="t1", path="syn-theme/document.md", title="SYN Night notes",
                             body="A readable document in both appearances.\n\n- Keep the same draft").doc.id
        comments.create_thread(conn, owner="t1", doc_id=doc_id, body="SYN Check this wording",
                               author="human", anchor={"quote": "readable", "prefix": "", "suffix": ""})
    page = ui_f2.page
    page.emulate_media(color_scheme="dark")
    switch_view(page, "inbox")
    _dark_surface(page, ".inbox-desk")
    assert _contrast(page, ".desk-head__title", ".inbox-desk") >= 4.5
    _shot(page, "inbox-dark")
    switch_view(page, "docs")
    _dark_surface(page, ".docs-desk")
    _dark_surface(page, ".doc-page")
    _shot(page, "documents-dark")
    open_page(page, doc_id)
    expect(page.locator(".doc-detail__title")).to_have_text("SYN Night notes")
    _dark_surface(page, ".vt-window[data-window='doc']")
    assert _contrast(page, ".doc-detail__title", ".vt-window[data-window='doc']") >= 4.5
    assert max(_channels(_rgb(page, ".doc-detail__body p", "color"))[:3]) <= 220
    assert _contrast(page, ".doc-detail__body p", ".vt-window[data-window='doc']") >= 4.5
    _shot(page, "document-dark")
    page.locator(".doc-detail__body mark.comment-highlight").click()
    tick(page)
    field = page.locator('[data-role="comment-field"]')
    field.fill("SYN keep this comment draft")
    _dark_surface(page, ".doc-card")
    assert _contrast(page, ".doc-card__input", ".doc-card") >= 4.5
    page.locator(".doc-card__send").hover()
    assert _contrast(page, ".doc-card__send", ".doc-card__send") >= 4.5
    _shot(page, "document-comment-dark")
    page.emulate_media(color_scheme="light")
    expect(field).to_have_value("SYN keep this comment draft")
    expect(field).to_be_focused()
    assert _rgb(page, ".vt-window[data-window='doc']") == "rgb(255, 255, 255)"
    expect(page.locator(".doc-detail__title")).to_have_text("SYN Night notes")
    _shot(page, "document-light")


def test_every_value_color_keeps_hovered_task_text_readable(ui_f2: UiSession):
    expect(ui_f2.page.locator(".pattern-vertical-board")).to_be_visible()
    colors = ("#278dea", "#92ce14", "#ecce32", "#955be0", "#df496d", "#f2713a")
    ids = []
    with psycopg.connect(ui_f2.backend.dsn, autocommit=True) as conn:
        for index, color in enumerate(colors):
            root = goals.create(conn, owner="t1", title=f"SYN value {index}", vertical="life",
                                anchor_date=date(2026, 8, 8), color=color).goal
            child = goals.create(conn, owner="t1", title=f"SYN colored task {index}", parent_id=root.id,
                                 vertical="day", anchor_date=date(2026, 8, 8)).goal
            ids.append(child.id)
    page = ui_f2.page
    page.emulate_media(color_scheme="dark")
    page.locator(f'.goal-card[data-goal-id="{ids[-1]}"]').first.wait_for()
    activate_column(page, "day")
    _dark_surface(page, ".app-shell")
    ground = _channels(_rgb(page, ".app-shell"))
    for goal_id in ids:
        card = page.locator(f'[data-vertical="day"] .goal-card[data-goal-id="{goal_id}"]')
        card.locator(".goal-card__title-text").first.hover()
        surface, opacity = card.locator(".goal-card__row").first.evaluate(
            "el => { const s = getComputedStyle(el, '::before'); return [s.backgroundColor, Number(s.opacity)] }",
        )
        wash = _channels(surface)
        alpha = (wash[3] if len(wash) == 4 else 1) * opacity
        background = [color * alpha + base * (1 - alpha) for color, base in zip(wash[:3], ground)]
        foreground = _channels(card.locator(".goal-card__title").first.evaluate("el => getComputedStyle(el).color"))
        assert _contrast_colors(foreground, background) >= 4.5, (goal_id, surface)
    _shot(page, "value-colors-dark")


def test_document_links_stay_readable_on_black_answers_and_messages(ui_agent: UiSession):
    from tests.ui.test_agent_conversation import _send
    from tests.ui.views import FIELD

    with psycopg.connect(ui_agent.backend.dsn, autocommit=True) as conn:
        doc_id = docs.create(conn, owner='t1', path='syn-theme/answer.md', title='SYN Linked notes',
                             body='Synthetic document linked by the agent.').doc.id
    page = ui_agent.page
    page.wait_for_selector('.goal-card__row')
    _send(page, f'[slow] [say] Your notes are ready. [SYN Linked notes](#doc/{doc_id})')
    page.locator('[data-role="out-of-focus"]').click(position={'x':60,'y':60})
    chip = page.locator(f'.circle-field__answer-chips [data-doc-id="{doc_id}"]')
    expect(chip).to_be_visible(timeout=10000)
    for scheme in ('light','dark'):
        page.emulate_media(color_scheme=scheme)
        for part in ('.doc-chip__name','.doc-chip__when'):
            assert _contrast(page, f'.circle-field__answer-chips {part}', '.circle-field__surface') >= 4.5
        if scheme == 'dark':
            assert max(_channels(_rgb(page, '.circle-field__answer-words','color'))[:3]) <= 220
        _shot(page,f'document-answer-{scheme}')
    page.locator('.circle-field__answer-words').click()
    message = '[data-balloon][data-who="agent"]'
    expect(page.locator(f'{message} [data-doc-id="{doc_id}"]')).to_be_visible()
    for scheme in ('light','dark'):
        page.emulate_media(color_scheme=scheme)
        for part in ('.doc-chip__name','.doc-chip__when'):
            assert _contrast(page, f'{message} {part}', message) >= 4.5
        if scheme == 'dark':
            assert max(_channels(_rgb(page, message,'color'))[:3]) <= 220
        _shot(page,f'document-message-{scheme}')
    page.keyboard.press('Control+k')
    page.locator(FIELD).fill('SYN softer draft')
    assert max(_channels(_rgb(page, FIELD,'color'))[:3]) <= 220
