"""P-25 typing behavior rebased onto P-28's contenteditable WYSIWYG.

D35's visible-raw-textarea ruling was overturned by the owner on 2026-08-10. The rendered
document is now the editing surface; raw Markdown remains the body storage and PATCH format.
"""

from __future__ import annotations

from playwright.sync_api import Locator, Page, Request

from tests.ui.conftest import UiSession


MODAL = "#goal-detail .modal__dialog"
REST = f'{MODAL} .goal-detail__body[data-cap="edit-body"][contenteditable="false"]'
EDITOR = f'{MODAL} .goal-detail__body[data-cap="edit-body"][contenteditable="true"]'


def _open_editor(page: Page) -> Locator:
    page.locator("[data-goal-id] .goal-card__title").first.click()
    page.locator(REST).wait_for(state="visible", timeout=5000)
    page.locator(REST).focus()
    page.locator(REST).press("Enter")
    page.locator(EDITOR).wait_for(state="visible", timeout=5000)
    return page.locator(EDITOR)


def _mod(page: Page) -> str:
    return "Meta" if page.evaluate("() => /Mac|iPhone|iPad/.test(navigator.platform)") else "Control"


def _replace(editor: Locator, text: str) -> None:
    # Test setup equivalent of textarea.fill(): replace the whole document, not only the text
    # inside whatever semantic block the previous WYSIWYG value happened to leave selected.
    editor.evaluate(
        """(root, text) => {
          root.replaceChildren(document.createTextNode(text));
          root.dispatchEvent(new InputEvent('input', {
            bubbles: true, inputType: 'insertText', data: text,
          }));
          root.focus();
        }""",
        text,
    )


def _finish(editor: Locator) -> None:
    editor.evaluate("el => el.blur()")
    editor.page.locator(REST).wait_for(state="visible", timeout=5000)


def _reenter(page: Page) -> Locator:
    rest = page.locator(REST)
    rest.focus()
    rest.press("Enter")
    page.locator(EDITOR).wait_for(state="visible", timeout=5000)
    return page.locator(EDITOR)


def _render_and_reenter(page: Page, editor: Locator) -> Locator:
    _finish(editor)
    return _reenter(page)


def _place_caret_at_end(editor: Locator, selector: str | None = None) -> None:
    editor.evaluate(
        """(root, selector) => {
          const target = selector ? root.querySelector(selector) : root;
          const range = document.createRange();
          range.selectNodeContents(target);
          range.collapse(false);
          const selection = getSelection();
          selection.removeAllRanges();
          selection.addRange(range);
          root.focus();
        }""",
        selector,
    )


def _select_all(editor: Locator) -> None:
    editor.evaluate(
        """root => {
          const range = document.createRange();
          range.selectNodeContents(root);
          const selection = getSelection();
          selection.removeAllRanges();
          selection.addRange(range);
          root.focus();
        }"""
    )


def _body_patches(page: Page) -> list[dict[str, str]]:
    patches: list[dict[str, str]] = []

    def capture(request: Request) -> None:
        if request.method == "PATCH" and "/api/goals/" in request.url:
            patches.append(request.post_data_json)

    page.on("request", capture)
    return patches


def _reopen_detail(page: Page) -> None:
    if page.locator(REST).is_visible():
        return
    page.locator("[data-goal-id] .goal-card__title").first.click()
    page.locator(REST).wait_for(state="visible", timeout=5000)


def test_p_25_keeps_raw_markdown_in_a_textarea(ui_f2: UiSession) -> None:
    page = ui_f2.page
    editor = _open_editor(page)
    _replace(editor, "Before **bold** and *emphasis* with `code`.")
    editor = _render_and_reenter(page, editor)

    assert page.locator(f"{MODAL} textarea[data-cap='edit-body']").count() == 0
    assert editor.count() == 1
    assert editor.locator("strong").inner_text() == "bold"
    assert editor.locator("em").inner_text() == "emphasis"
    assert editor.locator("code").inner_text() == "code"
    assert "**bold**" not in editor.inner_text()
    assert editor.get_attribute("spellcheck") == "false"
    assert editor.get_attribute("translate") == "no"

    patches = _body_patches(page)
    _place_caret_at_end(editor)
    editor.type("!")
    _finish(editor)
    assert patches[-1] == {"body": "Before **bold** and *emphasis* with `code`.!"}


def test_p_25_enter_continues_and_exits_markdown_lists(ui_f2: UiSession) -> None:
    page = ui_f2.page
    editor = _open_editor(page)

    for source, list_tag, expected in (
        ("- first", "ul", "- first\n- "),
        ("* first", "ul", "- first\n- "),
        ("1. first", "ol", "1. first\n2. "),
    ):
        _replace(editor, source)
        editor = _render_and_reenter(page, editor)
        assert editor.locator(f"{list_tag} > li").count() == 1, source
        patches = _body_patches(page)
        _place_caret_at_end(editor, f"{list_tag} > li:last-child")
        editor.press("Enter")
        assert editor.locator(f"{list_tag} > li").count() == 2
        _finish(editor)
        assert patches[-1] == {"body": expected}
        editor = _reenter(page)

    _replace(editor, "[x] first")
    editor = _render_and_reenter(page, editor)
    patches = _body_patches(page)
    _place_caret_at_end(editor, "p")
    editor.press("Enter")
    assert editor.inner_text() == "[x] first\n[ ]"
    assert editor.text_content() == "[x] first[ ] "
    _finish(editor)
    assert patches[-1] == {"body": "[x] first\n[ ] "}

    editor = _reenter(page)
    _replace(editor, "- first\n- ")
    editor = _render_and_reenter(page, editor)
    patches = _body_patches(page)
    _place_caret_at_end(editor, "ul > li:last-child")
    editor.press("Enter")
    assert editor.locator("ul > li").count() == 1
    _finish(editor)
    assert patches[-1] == {"body": "- first\n"}


def test_p_25_heading_and_format_markers_remain_literal(ui_f2: UiSession) -> None:
    page = ui_f2.page
    editor = _open_editor(page)
    _replace(editor, "# head\n\n**bold** *italic* `code` > quote [label](relative)")
    editor = _render_and_reenter(page, editor)

    assert "# head" in editor.inner_text()
    assert "> quote" in editor.inner_text()
    assert editor.locator("strong").inner_text() == "bold"
    assert editor.locator("em").inner_text() == "italic"
    assert editor.locator("code").inner_text() == "code"
    assert "[label](relative)" in editor.inner_text()
    assert editor.locator("a").count() == 0
    assert "**bold**" not in editor.inner_text()


def test_p_25_enter_shift_enter_tab_and_history_window(ui_f2: UiSession) -> None:
    page = ui_f2.page
    editor = _open_editor(page)

    _replace(editor, "one")
    _place_caret_at_end(editor)
    editor.press("Enter")
    editor.type("two")
    editor.press("Shift+Enter")
    editor.type("three")
    assert [line for line in editor.inner_text().splitlines() if line] == ["one", "two", "three"]

    patches = _body_patches(page)
    editor.press("Tab")
    assert editor.text_content().endswith("three\t")
    assert editor.evaluate("el => el === document.activeElement")
    _finish(editor)
    assert patches[-1] == {"body": "one\ntwo\nthree\t"}
    editor = _reenter(page)

    _replace(editor, "- nested")
    editor = _render_and_reenter(page, editor)
    patches = _body_patches(page)
    _place_caret_at_end(editor, "ul > li")
    editor.press("Tab")
    assert editor.locator("ul > li").get_attribute("data-md-indent") == "2"
    _finish(editor)
    assert patches[-1] == {"body": "  - nested"}
    editor = _reenter(page)
    assert editor.locator("ul > li").get_attribute("data-md-indent") == "2"
    _place_caret_at_end(editor, "ul > li")
    editor.press("Shift+Tab")
    assert editor.locator("ul > li").get_attribute("data-md-indent") is None
    _finish(editor)
    assert patches[-1] == {"body": "- nested"}
    editor = _reenter(page)

    _replace(editor, "")
    editor = _render_and_reenter(page, editor)
    page.wait_for_timeout(1100)
    editor.type("abc")
    editor.press(f"{_mod(page)}+Z")
    assert editor.inner_text() == ""

    editor.type("a")
    page.wait_for_timeout(1100)
    editor.type("b")
    editor.press(f"{_mod(page)}+Z")
    assert editor.inner_text() == "a"


def test_p_25_paste_uses_plain_text_and_replaces_selection(ui_f2: UiSession) -> None:
    page = ui_f2.page
    editor = _open_editor(page)
    _replace(editor, "replace me")
    _select_all(editor)
    patches = _body_patches(page)
    editor.evaluate(
        """el => {
          const data=new DataTransfer();
          data.setData('text/plain','Rich Link');
          data.setData('text/html','<strong class="foreign">Rich</strong> <a href="javascript:bad()">Link</a>');
          el.dispatchEvent(new ClipboardEvent('paste',{clipboardData:data,bubbles:true,cancelable:true}));
        }"""
    )
    assert editor.inner_text() == "Rich Link"
    assert editor.locator("strong, a, .foreign").count() == 0
    _finish(editor)
    assert patches[-1] == {"body": "Rich Link"}


def test_p_25_textarea_and_rendered_blocks_match_adopted_type(ui_f2: UiSession) -> None:
    page = ui_f2.page
    page.set_viewport_size({"width": 1440, "height": 900})
    editor = _open_editor(page)
    style = editor.evaluate(
        "el => { const s=getComputedStyle(el); return {fontFamily:s.fontFamily,fontSize:s.fontSize,lineHeight:s.lineHeight,caretColor:s.caretColor,outlineStyle:s.outlineStyle,transitionDuration:s.transitionDuration,animationName:s.animationName}; }"
    )
    # `lineHeight` is 24px here, not the 49px P-25's surface table measured on the reference:
    # accepted divergence, owner ruling 2026-08-11 (D98). Everything else in this dict is still
    # the reference's own value. The read state below asserts the SAME number on purpose — the
    # two states are one DOM node with `contenteditable` flipped, and D71's 0.0px entering/
    # leaving drift only holds while they share the rule.
    assert style == {
        "fontFamily": "Inter, sans-serif",
        "fontSize": "16px",
        "lineHeight": "24px",
        "caretColor": "rgb(227, 99, 27)",
        "outlineStyle": "none",
        "transitionDuration": "0s",
        "animationName": "none",
    }
    _replace(editor, "")
    assert editor.inner_text() == ""
    assert editor.evaluate("el => getComputedStyle(el, '::before').content") in {"none", "normal"}

    _replace(editor, "Paragraph\n\n- List")
    _finish(editor)
    paragraph = page.locator(REST).locator(":scope > p")
    item = page.locator(REST).locator(":scope > ul > li")
    assert paragraph.evaluate("el => [getComputedStyle(el).fontSize,getComputedStyle(el).lineHeight]") == ["16px", "24px"]
    assert item.evaluate("el => [getComputedStyle(el).fontSize,getComputedStyle(el).lineHeight]") == ["16px", "24px"]


def test_p_25_typing_never_loses_a_character_or_focus(ui_f2: UiSession) -> None:
    page = ui_f2.page
    editor = _open_editor(page)
    _replace(editor, "")
    lengths = []
    for character in "abcdef":
        editor.type(character)
        lengths.append(len(editor.inner_text()))

    assert lengths == [1, 2, 3, 4, 5, 6]
    assert editor.inner_text() == "abcdef"
    assert editor.evaluate("el => el === document.activeElement")


def test_p_25_keystrokes_coalesce_to_raw_patch_without_refetch(ui_f2: UiSession) -> None:
    page = ui_f2.page
    editor = _open_editor(page)
    page.evaluate(
        r"""() => {
          const realSetTimeout=window.setTimeout.bind(window);
          window.__p25Timers=0;
          window.setTimeout=(fn,delay,...args) => {
            if (delay !== 1000) return realSetTimeout(fn,delay,...args);
            window.__p25Timers += 1;
            return realSetTimeout(fn,window.__p25Timers === 1 ? 50 : 5000,...args);
          };
          const realFetch=window.fetch.bind(window);
          window.__p25Requests=[]; window.__p25Resolves=[];
          window.fetch=(input,init={}) => {
            const url=typeof input === 'string' ? input : input.url;
            if (init.method === 'PATCH' && /\/api\/goals\//.test(url)) {
              const body=JSON.parse(init.body);
              window.__p25Requests.push({method:'PATCH',route:'/api/goals/{id}',body});
              return new Promise(resolve => { window.__p25Resolves.push(() => resolve(new Response(
                JSON.stringify({updated_at:'held'}),
                {status:200,headers:{'Content-Type':'application/json'}}
              ))); });
            }
            if (/\/api\/board/.test(url)) window.__p25Requests.push({method:init.method || 'GET',route:'/api/board'});
            return realFetch(input,init);
          };
        }"""
    )
    _replace(editor, "sync")
    page.wait_for_function("() => window.__p25Requests.length === 1", timeout=1000)

    assert editor.inner_text() == "sync"
    requests = page.evaluate("() => window.__p25Requests")
    assert requests == [{"method": "PATCH", "route": "/api/goals/{id}", "body": {"body": "sync"}}]

    _replace(editor, "newer")
    page.evaluate("() => window.__p25Resolves[0]()")
    page.wait_for_timeout(50)
    assert editor.inner_text() == "newer"
    _finish(editor)
    assert page.locator(REST).inner_text() == "newer"
    page.wait_for_function("() => window.__p25Requests.length === 2", timeout=1000)
    requests = page.evaluate("() => window.__p25Requests")
    assert requests == [
        {"method": "PATCH", "route": "/api/goals/{id}", "body": {"body": "sync"}},
        {"method": "PATCH", "route": "/api/goals/{id}", "body": {"body": "newer"}},
    ]
    page.evaluate("() => window.__p25Resolves[1]()")
    page.wait_for_timeout(50)
    assert page.locator(REST).inner_text() == "newer"
    assert not any(item["route"] == "/api/board" for item in page.evaluate("() => window.__p25Requests"))


def test_p_25_close_flushes_body_inside_debounce_window(ui_f2: UiSession) -> None:
    page = ui_f2.page
    editor = _open_editor(page)
    text = "Close flush keeps this paragraph."
    _replace(editor, text)

    page.locator(f"{MODAL} .modal__close").click()
    page.locator(MODAL).wait_for(state="hidden", timeout=5000)
    _reopen_detail(page)
    assert page.locator(REST).inner_text() == text


def test_p_25_pagehide_flush_survives_reload(ui_f2: UiSession) -> None:
    page = ui_f2.page
    editor = _open_editor(page)
    text = "Pagehide keeps this paragraph."
    _replace(editor, text)

    # Not `wait_until="networkidle"`: D237's `/api/events` stream never finishes, so that
    # predicate can never fire. A rendered card is the readiness signal the reload needs here.
    page.reload()
    page.locator("[data-goal-id]").first.wait_for(state="visible", timeout=10000)
    _reopen_detail(page)
    assert page.locator(REST).inner_text() == text
