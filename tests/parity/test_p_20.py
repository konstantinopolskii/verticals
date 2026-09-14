"""P-20: period navigation topology, behavior, motion, and read-only wire contract."""

from __future__ import annotations

from typing import Any
from urllib.parse import parse_qs, urlsplit

from playwright.sync_api import Page

from tests.ui.conftest import UiSession
from tools.parity.probe_p20_period_nav import decode_reference as decode_p20_reference


def _rect(page: Page, selector: str) -> dict[str, float]:
    box = page.locator(selector).first.bounding_box()
    assert box is not None, f"{selector!r} has no rectangle"
    return box


P20_ADJUSTABLE = ("day", "week", "month", "quarter", "year", "decade")
P20_EXPECTED_TODAY = {
    "day": "2026-08-08",
    "week": "2026-W32",
    "month": "2026-08",
    "quarter": "2026-Q3",
    "year": "2026",
    "decade": "2026–2028",
    "life": "life",
}


def _p20_column(vertical: str) -> str:
    return f'[data-vertical="{vertical}"]'


def _p20_control(vertical: str, cap: str) -> str:
    return f'{_p20_column(vertical)} [data-cap="{cap}"]'


def _p20_periods(page: Page) -> dict[str, str]:
    return page.locator("[data-vertical]").evaluate_all(
        "els => Object.fromEntries(els.map(el => [el.dataset.vertical, el.dataset.periodKey]))"
    )


def _p20_wait_period(page: Page, vertical: str, period: str) -> None:
    page.locator(f'{_p20_column(vertical)}[data-period-key="{period}"]').wait_for(
        state="attached", timeout=5_000
    )


def _p20_finished_requests(session: UiSession, start: int, count: int = 1) -> list[dict[str, Any]]:
    deadline_ms = 5_000
    waited = 0
    while len(session.request_log[start:]) < count and waited < deadline_ms:
        session.page.wait_for_timeout(20)
        waited += 20
    return session.request_log[start:]


def _p20_board_requests(requests: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [request for request in requests if urlsplit(request["url"]).path == "/api/board"]


def _p20_date(request: dict[str, Any]) -> str | None:
    return parse_qs(urlsplit(request["url"]).query).get("date", [None])[0]


def _p20_writes(requests: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        request for request in requests
        if request["method"] in {"POST", "PUT", "PATCH", "DELETE"}
    ]


def test_p_20_reference_period_navigation_spec_from_pinned_bundles() -> None:
    """ASSERT A1: pinned assets encode topology, state, anatomy, keyboard, range, and motion."""
    reference = decode_p20_reference()
    assert reference["topology"] == {
        "control_owner": "one navigation subtree per eligible vertical column",
        "visibility": "desktop subtree displays only while its column is hovered",
        "shift_scope": "one invoking period step becomes an anchor; all columns reindex",
        "swap_cast": "outgoing and incoming Swiper slides coexist during transition",
        "dom_cleanup_delay_ms": 350,
    }
    assert reference["anatomy"]["order"] == ["Previous period", "Today", "Next period"]
    assert reference["anatomy"]["arrow_svg"] == {
        "width_css_px": 32, "height_css_px": 32,
        "viewBox": "-0.5 0 32 32", "stroke_width_css_px": 1.8,
    }
    assert reference["anatomy"]["today_disabled_when_all_at_current_anchor"] is True
    assert reference["anatomy"]["previous_next_disabled_or_range_limit"] is False
    assert reference["behaviour"] == {
        "previous_index_delta": -1,
        "next_index_delta": 1,
        "all_columns_period_containing_selected_anchor": True,
        "today_reindexes_all_columns": True,
        "dated_route": "/verticals/YYYY-MM-DD/",
        "today_route": "/verticals/today/",
    }
    assert reference["keyboard"] == {
        "today_global_key": "T",
        "previous_next_global_keys": None,
        "semantic_button_activation": ["Enter", "Space"],
    }
    assert reference["motion"] == {
        "property": "transform", "duration_ms": 350, "easing": "ease",
        "pointer_follow_duration_ms": 0,
    }
    assert reference["state"]["server_write"] is False


def test_p_20_column_local_anatomy_and_states(ui_f2: UiSession) -> None:
    """ASSERT A2: six local controls expose exact anatomy, material, hover, and disabled state."""
    page = ui_f2.page
    page.locator(_p20_column("day")).wait_for(state="visible", timeout=10_000)
    assert page.locator('[data-cap="period-nav"]').count() == 6
    assert page.locator(f'{_p20_column("life")} [data-cap="period-nav"]').count() == 0

    for vertical in P20_ADJUSTABLE:
        nav = page.locator(_p20_control(vertical, "period-nav"))
        assert nav.count() == 1
        order = nav.locator("[data-cap]").evaluate_all(
            "els => els.map(el => el.getAttribute('data-cap')).filter(x => x !== 'period-nav')"
        )
        assert order == ["period-prev", "period-today", "period-next"]

    day_nav = page.locator(_p20_control("day", "period-nav"))
    assert day_nav.evaluate("el => getComputedStyle(el).display") == "none"
    page.locator(_p20_column("day")).hover()
    assert day_nav.evaluate("el => getComputedStyle(el).display") == "flex"

    prev = page.locator(_p20_control("day", "period-prev"))
    today = page.locator(_p20_control("day", "period-today"))
    nxt = page.locator(_p20_control("day", "period-next"))
    assert prev.get_attribute("aria-label") == "Previous period"
    assert nxt.get_attribute("aria-label") == "Next period"
    assert today.inner_text() == "Today"
    assert today.is_disabled()
    assert not prev.is_disabled() and not nxt.is_disabled()

    svg = prev.locator("svg")
    box = svg.bounding_box()
    assert box is not None
    assert abs(box["width"] - 32) <= 1 and abs(box["height"] - 32) <= 1
    assert svg.get_attribute("viewBox") == "-0.5 0 32 32"
    assert svg.locator("path").get_attribute("stroke-width") == "1.8"
    style = day_nav.evaluate(
        """el => { const s=getComputedStyle(el); return {display:s.display,border:s.border,
          radius:s.borderRadius,background:s.backgroundColor}; }"""
    )
    assert style["border"] == "1px solid rgb(241, 241, 241)"
    assert style["radius"] == "7px"
    assert style["background"] == "rgb(241, 241, 241)"
    assert prev.evaluate("el => getComputedStyle(el).cursor") == "pointer"
    assert prev.evaluate("el => getComputedStyle(el).userSelect") == "none"


def test_p_20_day_previous_reanchors_every_column_once(ui_f2: UiSession) -> None:
    """ASSERT A3: Day Previous produces one coherent whole-board read and fixed outer cast."""
    page = ui_f2.page
    page.locator(_p20_column("day")).hover()
    strip_before = _rect(page, '[data-role="column-strip"]')
    columns_before = {h: _rect(page, _p20_column(h)) for h in (*P20_ADJUSTABLE, "life")}
    n0 = len(ui_f2.request_log)
    page.locator(_p20_control("day", "period-prev")).click()
    _p20_wait_period(page, "day", "2026-08-07")
    requests = _p20_finished_requests(ui_f2, n0)
    boards = _p20_board_requests(requests)
    assert len(boards) == 1 and _p20_date(boards[0]) == "2026-08-07"
    assert _p20_writes(requests) == []
    assert page.evaluate("location.pathname") == "/h/2026-08-07"
    assert _p20_periods(page) == {
        **P20_EXPECTED_TODAY,
        "day": "2026-08-07",
    }
    strip_after = _rect(page, '[data-role="column-strip"]')
    columns_after = {h: _rect(page, _p20_column(h)) for h in (*P20_ADJUSTABLE, "life")}
    for key in ("x", "y", "width", "height"):
        assert abs(strip_after[key] - strip_before[key]) <= 1
        for vertical in columns_before:
            assert abs(columns_after[vertical][key] - columns_before[vertical][key]) <= 1


def test_p_20_week_next_uses_next_week_anchor(ui_f2: UiSession) -> None:
    """ASSERT A4: Week Next reanchors to next ISO-week start, not an unrelated unit."""
    page = ui_f2.page
    page.locator(_p20_column("week")).hover()
    n0 = len(ui_f2.request_log)
    page.locator(_p20_control("week", "period-next")).click()
    _p20_wait_period(page, "week", "2026-W33")
    requests = _p20_finished_requests(ui_f2, n0)
    boards = _p20_board_requests(requests)
    assert len(boards) == 1 and _p20_date(boards[0]) == "2026-08-10"
    assert page.evaluate("location.pathname") == "/h/2026-08-10"
    assert _p20_periods(page) == {
        **P20_EXPECTED_TODAY,
        "day": "2026-08-10",
        "week": "2026-W33",
    }


def test_p_20_today_button_and_t_reset_every_vertical(ui_f2: UiSession) -> None:
    """ASSERT A5: Today button and global T both reset the complete vertical cast through one GET."""
    page = ui_f2.page

    def step_away() -> None:
        page.locator(_p20_column("day")).hover()
        page.locator(_p20_control("day", "period-prev")).click()
        _p20_wait_period(page, "day", "2026-08-07")

    step_away()
    n0 = len(ui_f2.request_log)
    page.locator(_p20_control("day", "period-today")).click()
    _p20_wait_period(page, "day", "2026-08-08")
    button_requests = _p20_finished_requests(ui_f2, n0)
    assert [_p20_date(r) for r in _p20_board_requests(button_requests)] == ["2026-08-08"]
    assert page.evaluate("location.pathname") == "/"
    assert _p20_periods(page) == P20_EXPECTED_TODAY
    assert page.locator(_p20_control("day", "period-today")).is_disabled()

    step_away()
    n1 = len(ui_f2.request_log)
    page.locator("body").press("t")
    _p20_wait_period(page, "day", "2026-08-08")
    key_requests = _p20_finished_requests(ui_f2, n1)
    assert [_p20_date(r) for r in _p20_board_requests(key_requests)] == ["2026-08-08"]
    assert page.evaluate("location.pathname") == "/"
    assert _p20_periods(page) == P20_EXPECTED_TODAY


def test_p_20_swap_keeps_two_casts_and_moves_only_contents(ui_f2: UiSession) -> None:
    """ASSERT A6: old/new period slides coexist, transform for 350ms ease, then clean up."""
    page = ui_f2.page
    page.locator(_p20_column("day")).hover()
    before = {h: _rect(page, _p20_column(h)) for h in (*P20_ADJUSTABLE, "life")}
    page.locator(_p20_control("day", "period-prev")).click()
    page.locator('[data-role="period-slide"][data-state="incoming"]').first.wait_for(
        state="attached", timeout=5_000
    )
    assert page.locator('[data-role="period-slide"][data-state="outgoing"]').count() == 6
    assert page.locator('[data-role="period-slide"][data-state="incoming"]').count() == 6
    assert page.locator(f'{_p20_column("life")} [data-role="period-slide"]').count() == 1
    assert page.locator('[data-role="column-strip"] [role="status"]').count() == 0
    animations = page.evaluate(
        """() => document.getAnimations().filter(a =>
          a.effect?.target?.matches?.('[data-role="period-track"]')).map(a => {
            const duration=a.effect.getTiming().duration;
            a.pause();
            a.currentTime=duration / 2;
            const midpointProgress=a.effect.getComputedTiming().progress;
            const frames=a.effect.getKeyframes().map(f => ({
              transform:f.transform ?? null, opacity:f.opacity ?? null
            }));
            a.play();
            return {duration,midpointProgress,frames};
          })"""
    )
    assert len(animations) == 6
    for animation in animations:
        assert animation["duration"] == 350
        assert abs(animation["midpointProgress"] - 0.8024) <= 0.01
        assert all(frame["transform"] is not None for frame in animation["frames"])
        assert all(frame["opacity"] is None for frame in animation["frames"])
    during = {h: _rect(page, _p20_column(h)) for h in (*P20_ADJUSTABLE, "life")}
    for vertical in before:
        for key in ("x", "y", "width", "height"):
            assert abs(during[vertical][key] - before[vertical][key]) <= 1
    page.wait_for_timeout(380)
    assert page.locator('[data-role="period-slide"][data-state="outgoing"]').count() == 0
    assert page.locator('[data-role="period-slide"][data-state="incoming"]').count() == 0
    assert page.locator('[data-role="period-slide"][data-state="current"]').count() == 6


def test_p_20_native_keyboard_range_and_read_only_wire(ui_f2: UiSession) -> None:
    """ASSERT A7: native activation works, arrows stay enabled, and navigation remains read-only."""
    page = ui_f2.page
    page.locator(_p20_column("day")).hover()
    prev = page.locator(_p20_control("day", "period-prev"))
    nxt = page.locator(_p20_control("day", "period-next"))
    assert not prev.is_disabled() and not nxt.is_disabled()

    n0 = len(ui_f2.request_log)
    prev.focus()
    prev.press("Enter")
    _p20_wait_period(page, "day", "2026-08-07")
    first = _p20_finished_requests(ui_f2, n0)
    assert len(_p20_board_requests(first)) == 1 and _p20_writes(first) == []

    n1 = len(ui_f2.request_log)
    page.locator(_p20_control("day", "period-next")).press("Space")
    _p20_wait_period(page, "day", "2026-08-08")
    second = _p20_finished_requests(ui_f2, n1)
    assert len(_p20_board_requests(second)) == 1 and _p20_writes(second) == []

    before = _p20_periods(page)
    n2 = len(ui_f2.request_log)
    page.locator("body").focus()
    page.keyboard.press("ArrowLeft")
    page.keyboard.press("ArrowRight")
    page.wait_for_timeout(50)
    assert _p20_periods(page) == before
    assert _p20_board_requests(ui_f2.request_log[n2:]) == []
