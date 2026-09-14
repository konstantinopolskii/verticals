"""P-01 parity contract: search surface, wire, matching, rows, and tag filter.

Fixture F2. Each test maps to one ASSERT cluster in docs/parity/P-01.md. Synthetic fixture
identifiers are used throughout; no live-account content enters this file.
"""

from __future__ import annotations

from urllib.parse import parse_qs, urlsplit

import pytest

from tests.ui.conftest import UiSession


SEARCH_TRIGGER = '[data-cap="search-trigger"]'
SEARCH_BACKDROP = '[data-cap="search-backdrop"]'
SEARCH_MODAL = '[data-cap="search-modal"]'
SEARCH_INPUT = '[data-cap="search-input"] input'
RESULTS = '[data-cap="search-results"]'
ROWS = f'{RESULTS} [data-goal-id]'
EMPTY = f'{RESULTS} [data-role="search-empty"]'

LOUPE_PATH = (
    "M0.413086 8.00195C0.413086 11.8691 3.55957 15.0156 7.42676 15.0156C8.95605 "
    "15.0156 10.3535 14.5234 11.5049 13.6973L15.8291 18.0303C16.0312 18.2324 "
    "16.2949 18.3291 16.5762 18.3291C17.1738 18.3291 17.5869 17.8809 17.5869 "
    "17.292C17.5869 17.0107 17.4814 16.7559 17.2969 16.5713L12.999 12.2471C13.9043 "
    "11.0693 14.4404 9.60156 14.4404 8.00195C14.4404 4.13477 11.2939 0.988281 "
    "7.42676 0.988281C3.55957 0.988281 0.413086 4.13477 0.413086 8.00195ZM1.91602 "
    "8.00195C1.91602 4.96094 4.38574 2.49121 7.42676 2.49121C10.4678 2.49121 "
    "12.9375 4.96094 12.9375 8.00195C12.9375 11.043 10.4678 13.5127 7.42676 "
    "13.5127C4.38574 13.5127 1.91602 11.043 1.91602 8.00195Z"
)

CYCL_IDS = ["SYNSCH01", "SYNSCH02", "SYNSCH03", "SYNSCH04"]
RECENT_IDS = [
    "SYNEDG07",
    "SYNEDG06",
    "SYNEDG05",
    "SYNEDG04",
    "SYNEDG03",
    "SYNEDG02",
    "SYNEDG01",
    "SYNDON02",
    "SYNDON01",
    "SYNOLD02",
]
TAG_IDS = {"SYNRET01", "SYNRET02"}


def _search_requests(log: list[dict]) -> list[dict]:
    return [request for request in log if "/api/search" in request["url"]]


def _query(request: dict) -> dict[str, list[str]]:
    return parse_qs(urlsplit(request["url"]).query)


def _result_ids(session: UiSession) -> list[str]:
    return session.page.locator(ROWS).evaluate_all(
        "els => els.map(el => el.getAttribute('data-goal-id'))"
    )


def _wait_for_results(session: UiSession) -> None:
    session.page.wait_for_selector(ROWS, timeout=5000)


def _wait_for_result_change(session: UiSession, previous_ids: list[str]) -> None:
    session.page.wait_for_function(
        """({selector, previousIds}) => {
          const currentIds = [...document.querySelectorAll(selector)]
            .map(el => el.getAttribute('data-goal-id'))
          return currentIds.length > 0
            && JSON.stringify(currentIds) !== JSON.stringify(previousIds)
        }""",
        arg={"selector": ROWS, "previousIds": previous_ids},
        timeout=5000,
    )


def _open_search(session: UiSession) -> None:
    session.page.locator(SEARCH_TRIGGER).click()
    session.page.locator(SEARCH_MODAL).wait_for(state="visible", timeout=5000)
    session.page.locator(SEARCH_INPUT).wait_for(state="visible", timeout=5000)


def test_p01_surface_deep_link_and_escape(ui_f2: UiSession) -> None:
    """ASSERT cluster A1+A7: modal lifecycle, route persistence, Escape/focus restore."""
    session = ui_f2
    page = session.page
    url_before = page.url
    trigger = page.locator(SEARCH_TRIGGER)
    _open_search(session)
    search_input = page.locator(SEARCH_INPUT)
    assert page.locator(SEARCH_BACKDROP).is_visible()
    assert search_input.evaluate("el => el === document.activeElement")

    search_input.fill("cycl")
    _wait_for_results(session)
    assert urlsplit(page.url).path == "/search/cycl"

    search_input.press("Escape")
    page.wait_for_selector(SEARCH_MODAL, state="detached", timeout=5000)
    assert page.locator(SEARCH_BACKDROP).count() == 0
    assert page.url == url_before
    assert trigger.evaluate("el => el === document.activeElement")

    page.goto(f"{session.base_url}/search/cycl")
    page.wait_for_selector(SEARCH_MODAL)
    page.wait_for_selector(SEARCH_INPUT)
    _wait_for_results(session)
    page.reload()
    page.wait_for_selector(SEARCH_INPUT)
    _wait_for_results(session)
    assert page.locator(SEARCH_INPUT).input_value() == "cycl"


def test_p01_empty_search_shows_recent_default(ui_f2: UiSession) -> None:
    """ASSERT cluster A2: unfiltered recent-default request and order."""
    session = ui_f2
    n0 = len(session.request_log)
    _open_search(session)

    for _ in range(15):
        if _search_requests(session.request_log[n0:]):
            break
        session.page.wait_for_timeout(100)

    requests = _search_requests(session.request_log[n0:])
    assert len(requests) == 1, f"expected one recent-default search request, got {requests}"
    assert requests[0]["method"] == "GET"
    params = _query(requests[0])
    assert params == {"limit": ["10"]}, f"recent-default query drifted: {params}"

    _wait_for_results(session)
    assert _result_ids(session) == RECENT_IDS


def test_p01_search_uses_trailing_debounce(ui_f2: UiSession) -> None:
    """ASSERT cluster A3: one final request from one typing burst."""
    session = ui_f2
    _open_search(session)
    search_input = session.page.locator(SEARCH_INPUT)
    session.page.wait_for_timeout(500)  # isolate the empty recent-default request from this cluster
    n0 = len(session.request_log)

    search_input.fill("cyc")
    session.page.wait_for_timeout(100)
    search_input.fill("cycl")
    session.page.wait_for_timeout(250)

    early = [r for r in _search_requests(session.request_log[n0:]) if "q" in _query(r)]
    assert early == [], f"text search fired before trailing debounce elapsed: {early}"

    for _ in range(10):
        text_requests = [r for r in _search_requests(session.request_log[n0:]) if "q" in _query(r)]
        if text_requests:
            break
        session.page.wait_for_timeout(100)

    assert len(text_requests) == 1, f"expected one debounced request, got {text_requests}"
    assert _query(text_requests[0]) == {"q": ["cycl"]}


def test_p01_search_matches_title_body_completed_and_stable_order(ui_f2: UiSession) -> None:
    """ASSERT cluster A4: our retained substring semantics and stable non-recency order."""
    session = ui_f2
    _open_search(session)
    search_input = session.page.locator(SEARCH_INPUT)

    search_input.fill("cycl")
    _wait_for_results(session)
    assert _result_ids(session) == CYCL_IDS
    body_only = session.page.locator(f'{ROWS}[data-goal-id="SYNSCH04"] .goal-card__title')
    assert "cycl" not in body_only.inner_text().lower(), "fixture no longer proves a body-only match"

    previous_ids = _result_ids(session)
    search_input.fill("shipped")
    _wait_for_result_change(session, previous_ids)
    assert set(_result_ids(session)) == {"SYNDON01", "SYNDON02", "SYNRET01"}
    for goal_id in ("SYNDON01", "SYNDON02"):
        row = session.page.locator(f'{ROWS}[data-goal-id="{goal_id}"]')
        assert row.locator('input[type="checkbox"]').is_checked()
        alpha = row.locator(".goal-card__title").evaluate(
            "el => Number(getComputedStyle(el).color.match(/[\\d.]+/g).at(-1) || 1)"
        )
        assert alpha < 1, f"completed result {goal_id} title is not muted"


def test_p01_result_row_anatomy_and_plain_title(ui_f2: UiSession) -> None:
    """ASSERT cluster A5: result controls, period/open slots, and no highlighting."""
    session = ui_f2
    _open_search(session)
    search_input = session.page.locator(SEARCH_INPUT)
    search_input.fill("cycl")
    _wait_for_results(session)

    for goal_id in CYCL_IDS:
        row = session.page.locator(f'{ROWS}[data-goal-id="{goal_id}"]')
        assert row.locator('[data-cap="complete"]').count() == 1
        title = row.locator(".goal-card__title")
        assert title.count() == 1
        assert title.evaluate("el => el.childElementCount") == 0, "title contains highlight markup"
        assert row.locator('[data-role="search-period"]').count() == 1
        assert row.locator('[data-role="search-open"]').count() == 1

    previous_ids = _result_ids(session)
    search_input.fill("maybe candidate")
    _wait_for_result_change(session, previous_ids)
    undated = session.page.locator(f'{ROWS}[data-goal-id="SYNMAY01"]')
    assert undated.locator('[data-role="search-period"]').inner_text() == ""


def test_p01_empty_state_copy(ui_f2: UiSession) -> None:
    """ASSERT cluster A6: measured empty-state structure and copy."""
    session = ui_f2
    _open_search(session)
    session.page.locator(SEARCH_INPUT).fill("zzzz-no-f2-match")
    empty = session.page.locator(EMPTY)
    empty.wait_for(state="visible", timeout=5000)
    assert empty.count() == 1
    assert empty.inner_text() == "No results matched your search"
    assert session.page.locator(ROWS).count() == 0
    style = empty.evaluate(
        """el => { const s=getComputedStyle(el); return {
          textAlign:s.textAlign, marginTop:s.marginTop, marginBottom:s.marginBottom,
          fontSize:s.fontSize, lineHeight:s.lineHeight
        }}"""
    )
    assert style == {
        "textAlign": "center",
        "marginTop": "30px",
        "marginBottom": "30px",
        "fontSize": "16px",
        "lineHeight": "18.4px",
    }


def test_p01_hash_tag_uses_filter_wire(ui_f2: UiSession) -> None:
    """ASSERT cluster A8: our single-tag adaptation through filterByTag."""
    session = ui_f2
    _open_search(session)
    search_input = session.page.locator(SEARCH_INPUT)
    n0 = len(session.request_log)
    search_input.fill("#retro")
    chip = session.page.locator(f'{SEARCH_MODAL} [data-tag="retro"]')
    chip.wait_for(state="visible", timeout=5000)
    assert _search_requests(session.request_log[n0:]) == []

    chip.click()
    _wait_for_results(session)
    requests = _search_requests(session.request_log[n0:])
    assert len(requests) == 1
    assert requests[0]["method"] == "GET"
    assert _query(requests[0]) == {"tag": ["retro"]}
    assert set(_result_ids(session)) == TAG_IDS


def test_p01_open_focuses_input_and_enter_is_no_op(ui_f2: UiSession) -> None:
    """ASSERT cluster A9: focus-on-open and Enter opens/submits nothing."""
    session = ui_f2
    page = session.page
    _open_search(session)
    search_input = page.locator(SEARCH_INPUT)
    page.wait_for_timeout(500)
    assert search_input.evaluate("el => el === document.activeElement")

    url_before = page.url
    requests_before = list(session.request_log)
    dialogs_before = session.dialog_records()
    search_input.press("Enter")
    page.wait_for_timeout(500)

    assert session.request_log == requests_before, "Enter submitted a request"
    assert session.dialog_records() == dialogs_before, "Enter opened a dialog"
    assert page.url == url_before, "Enter navigated"
    assert search_input.evaluate("el => el === document.activeElement")


def test_p01_entry_icon_geometry_position_and_microstates(ui_f2: UiSession) -> None:
    """ASSERT A10: D10 placement plus measured loupe geometry and pointer states."""
    page = ui_f2.page
    nav = page.locator('[data-cap="nav"]')
    trigger = page.locator(SEARCH_TRIGGER)
    icon = trigger.locator('[data-role="search-icon"]')
    nav_box = nav.bounding_box()
    trigger_box = trigger.bounding_box()
    assert nav_box and trigger_box
    assert trigger_box["width"] == pytest.approx(24, abs=1)
    assert trigger_box["height"] == pytest.approx(25, abs=1)
    assert trigger_box["y"] >= nav_box["y"] + nav_box["height"] / 2
    assert 0 <= nav_box["y"] + nav_box["height"] - trigger_box["y"] - trigger_box["height"] <= 32
    assert 0 <= trigger_box["x"] - nav_box["x"] <= 40
    assert trigger.evaluate("el => getComputedStyle(el).cursor") == "pointer"

    assert icon.get_attribute("viewBox") == "0 0 18 19"
    icon_box = icon.bounding_box()
    assert icon_box and icon_box["width"] == pytest.approx(24, abs=1)
    assert icon_box["height"] == pytest.approx(25, abs=1)
    assert icon.locator("path").count() == 1
    assert icon.locator("path").get_attribute("d") == LOUPE_PATH
    resting = icon.evaluate(
        """el => { const s=getComputedStyle(el); return {
          opacity:s.opacity, duration:s.transitionDuration,
          easing:s.transitionTimingFunction, property:s.transitionProperty
        }}"""
    )
    assert resting == {
        "opacity": "0.3",
        "duration": "0.25s",
        "easing": "cubic-bezier(0.165, 0.84, 0.44, 1)",
        "property": "opacity",
    }
    trigger.hover()
    page.wait_for_timeout(300)
    assert icon.evaluate("el => getComputedStyle(el).opacity") == "1"


def test_p01_modal_backdrop_geometry(ui_f2: UiSession) -> None:
    """ASSERT A11: measured backdrop, horizontal centering, shape, and width formula."""
    session = ui_f2
    page = session.page
    _open_search(session)
    backdrop = page.locator(SEARCH_BACKDROP)
    modal = page.locator(SEARCH_MODAL)
    geometry = page.evaluate(
        """({backdropSelector, modalSelector}) => {
          const backdrop=document.querySelector(backdropSelector), modal=document.querySelector(modalSelector)
          const b=backdrop.getBoundingClientRect(), m=modal.getBoundingClientRect()
          const bs=getComputedStyle(backdrop), ms=getComputedStyle(modal)
          return {
            viewport:{width:innerWidth,height:innerHeight},
            backdrop:{rect:{x:b.x,y:b.y,width:b.width,height:b.height},position:bs.position,
              background:bs.backgroundColor,blur:bs.backdropFilter},
            modal:{rect:{x:m.x,y:m.y,width:m.width,height:m.height},radius:ms.borderRadius,
              background:ms.backgroundColor,border:ms.borderTopWidth,shadow:ms.boxShadow}
          }
        }""",
        {"backdropSelector": SEARCH_BACKDROP, "modalSelector": SEARCH_MODAL},
    )
    assert geometry["backdrop"] == {
        "rect": {"x": 0, "y": 0, **geometry["viewport"]},
        "position": "fixed",
        "background": "rgba(0, 0, 0, 0.6)",
        "blur": "none",
    }
    modal_box = geometry["modal"]["rect"]
    assert modal_box["y"] == pytest.approx(50, abs=1)
    assert modal_box["width"] == pytest.approx(824, abs=1)
    assert modal_box["x"] + modal_box["width"] / 2 == pytest.approx(
        geometry["viewport"]["width"] / 2, abs=1
    )
    assert geometry["modal"]["radius"] == "12px"
    assert geometry["modal"]["background"] == "rgb(255, 255, 255)"
    assert geometry["modal"]["border"] == "0px"
    assert geometry["modal"]["shadow"] == "none"

    page.set_viewport_size({"width": 768, "height": 900})
    narrow = modal.bounding_box()
    assert narrow and narrow["x"] == pytest.approx(0, abs=1)
    assert narrow["width"] == pytest.approx(768, abs=1)
    assert narrow["y"] == pytest.approx(50, abs=1)


def test_p01_modal_inner_geometry_and_row_hover(ui_f2: UiSession) -> None:
    """ASSERT A12: input, scroll area, row anatomy, typography, and hover feel."""
    session = ui_f2
    page = session.page
    _open_search(session)
    _wait_for_results(session)
    search_input = page.locator(SEARCH_INPUT)
    input_style = search_input.evaluate(
        """el => { const s=getComputedStyle(el), r=el.getBoundingClientRect(); return {
          height:r.height, placeholder:el.placeholder, fontFamily:s.fontFamily, fontSize:s.fontSize,
          fontWeight:s.fontWeight, lineHeight:s.lineHeight, padding:s.padding,
          border:s.border, borderRadius:s.borderRadius
        }}"""
    )
    assert input_style["height"] == pytest.approx(65.891, abs=1)
    assert input_style["placeholder"] == "Search"
    assert input_style["fontFamily"].startswith("Inter")
    assert input_style["fontSize"] == "26px"
    assert input_style["fontWeight"] == "400"
    assert input_style["lineHeight"] == "29.9px"
    assert input_style["padding"] == "16px 16px 16px 44px"
    assert input_style["border"] == "2px solid rgb(255, 255, 255)"
    assert input_style["borderRadius"] == "8px"
    input_icon = page.locator('[data-role="search-input-icon"]')
    input_icon_box = input_icon.bounding_box()
    assert input_icon_box and input_icon_box["width"] == pytest.approx(20, abs=1)
    assert input_icon_box["height"] == pytest.approx(20, abs=1)
    assert input_icon.evaluate(
        "el => ({opacity:getComputedStyle(el).opacity,cursor:getComputedStyle(el).cursor})"
    ) == {"opacity": "0.6", "cursor": "default"}

    results_style = page.locator(RESULTS).evaluate(
        """el => { const s=getComputedStyle(el); return {
          maxHeight:s.maxHeight, overflow:s.overflow, paddingBottom:s.paddingBottom
        }}"""
    )
    assert results_style == {"maxHeight": "450px", "overflow": "scroll", "paddingBottom": "15px"}

    row = page.locator(ROWS).first
    row_style = row.evaluate(
        """el => { const s=getComputedStyle(el), r=el.getBoundingClientRect(); return {
          height:r.height,padding:s.padding,borderBottomWidth:s.borderBottomWidth,
          cursor:s.cursor,background:s.backgroundColor
        }}"""
    )
    assert min(abs(row_style["height"] - height) for height in (37, 57)) <= 1
    assert row_style["padding"] == "8px 18px"
    assert row_style["borderBottomWidth"] == "1px"
    title_style = row.locator(".goal-card__title").evaluate(
        "el => ({fontSize:getComputedStyle(el).fontSize,lineHeight:getComputedStyle(el).lineHeight})"
    )
    assert title_style == {"fontSize": "15px", "lineHeight": "20px"}
    period_style = row.locator('[data-role="search-period"]').evaluate(
        """el => { const s=getComputedStyle(el); return {
          fontSize:s.fontSize,lineHeight:s.lineHeight,opacity:s.opacity
        }}"""
    )
    assert period_style == {"fontSize": "14px", "lineHeight": "20px", "opacity": "0.5"}
    open_box = row.locator('[data-role="search-open"]').bounding_box()
    assert open_box and open_box["width"] == pytest.approx(16, abs=1)
    assert open_box["height"] == pytest.approx(16, abs=1)

    row.hover()
    page.wait_for_timeout(320)
    hover = row.evaluate(
        """el => { const s=getComputedStyle(el); return {
          cursor:s.cursor,background:s.backgroundColor,duration:s.transitionDuration,
          easing:s.transitionTimingFunction
        }}"""
    )
    assert hover == {
        "cursor": "pointer",
        "background": "rgb(236, 237, 239)",
        "duration": "0.3s",
        "easing": "cubic-bezier(0.165, 0.84, 0.44, 1)",
    }


def test_p01_modal_topology_motion_and_close_paths(ui_f2: UiSession) -> None:
    """ASSERT A13: one subtree, measured motion boundary, scroll lock, and exits."""
    session = ui_f2
    page = session.page
    content = page.locator(".app-content")
    content_before = content.bounding_box()
    page.evaluate(
        """({backdrop, modal}) => {
          window.__p01PortalAdds = 0
          window.__p01SawSpinner = false
          window.__p01Observer = new MutationObserver(records => records.forEach(record => {
            for (const node of record.addedNodes) if (node instanceof Element) {
              const hasBackdrop=node.matches(backdrop) || node.querySelector(backdrop)
              const hasModal=node.matches(modal) || node.querySelector(modal)
              if (hasBackdrop && hasModal) window.__p01PortalAdds += 1
              if (node.matches('[data-role="search-spinner"]') ||
                  node.querySelector('[data-role="search-spinner"]')) window.__p01SawSpinner = true
            }
          }))
          window.__p01Observer.observe(document.body, {childList:true,subtree:true})
        }""",
        {"backdrop": SEARCH_BACKDROP, "modal": SEARCH_MODAL},
    )
    page.locator(SEARCH_TRIGGER).click()
    page.locator(SEARCH_MODAL).wait_for(state="visible", timeout=5000)
    assert page.evaluate("window.__p01PortalAdds") == 1
    assert content.bounding_box() == content_before
    assert page.evaluate(
        """() => {
          const root=document.scrollingElement, body=getComputedStyle(document.body)
          return root.scrollHeight <= root.clientHeight || body.overflow === 'hidden'
        }"""
    )

    animations = page.evaluate(
        """({iconSelector, backdropSelector, modalSelector}) => document.getAnimations().map(a => ({
          icon:a.effect?.target?.matches?.(iconSelector) || false,
          surface:a.effect?.target?.matches?.(`${backdropSelector},${modalSelector}`) || false,
          duration:a.effect?.getTiming?.().duration,
          easing:a.effect?.target instanceof Element
            ? getComputedStyle(a.effect.target).transitionTimingFunction : null,
          keyframes:a.effect?.getKeyframes?.() || []
        }))""",
        {
            "iconSelector": f'{SEARCH_TRIGGER} [data-role="search-icon"]',
            "backdropSelector": SEARCH_BACKDROP,
            "modalSelector": SEARCH_MODAL,
        },
    )
    assert any(
        item["icon"]
        and item["duration"] == 250
        and item["easing"] == "cubic-bezier(0.165, 0.84, 0.44, 1)"
        for item in animations
    ), "entrance-phase trigger opacity animation missing"
    assert not any(item["surface"] for item in animations), "surface invented entrance motion"
    assert page.locator(
        f'{SEARCH_MODAL} button[aria-label*="close" i], {SEARCH_MODAL} button[title*="close" i]'
    ).count() == 0
    _wait_for_results(session)
    assert page.evaluate("window.__p01SawSpinner"), "recent state never mounted measured spinner"

    page.locator(SEARCH_INPUT).press("Escape")
    page.locator(SEARCH_MODAL).wait_for(state="detached", timeout=5000)
    assert page.locator(SEARCH_BACKDROP).count() == 0
    assert page.locator(SEARCH_TRIGGER).evaluate("el => el === document.activeElement")

    _open_search(session)
    page.mouse.click(4, 4)
    page.locator(SEARCH_MODAL).wait_for(state="detached", timeout=5000)
    assert page.locator(SEARCH_BACKDROP).count() == 0


def test_p01_modal_feel_invariants_and_result_keyboard(ui_f2: UiSession) -> None:
    """ASSERT A14: no jump, no lost input, no result selection/navigation."""
    session = ui_f2
    page = session.page
    _open_search(session)
    search_input = page.locator(SEARCH_INPUT)
    assert search_input.evaluate("el => el === document.activeElement")
    modal_before = page.locator(SEARCH_MODAL).bounding_box()

    search_input.fill("cycl")
    _wait_for_results(session)
    modal_after = page.locator(SEARCH_MODAL).bounding_box()
    assert search_input.input_value() == "cycl"
    assert modal_before and modal_after
    assert modal_after["y"] == pytest.approx(modal_before["y"], abs=1)
    assert modal_after["x"] + modal_after["width"] / 2 == pytest.approx(
        modal_before["x"] + modal_before["width"] / 2, abs=1
    )

    selected = f'{ROWS}[aria-selected="true"], {ROWS}._selected, {ROWS}[data-selected="true"]'
    assert page.locator(selected).count() == 0
    url_before = page.url
    for key in ("ArrowDown", "ArrowUp", "Enter"):
        search_input.press(key)
        page.wait_for_timeout(50)
        assert search_input.evaluate("el => el === document.activeElement")
        assert page.locator(selected).count() == 0
        assert page.url == url_before
