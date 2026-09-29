"""S-78 — No emoji in any user-facing string.

`docs/E2E.md` §6, S-78 (line 1801). Required by AC-122 and its negative twin AC-184. House law:
this repo's `CLAUDE.md` — "Never use emoji in any user-facing bot texts or UI strings."

    Steps: collect `document.body.innerText` across board, detail surface, popover, empty state,
    and every error state reachable in S-75; also read every string literal in the built JS
    bundle's extracted i18n table.

Two scans, deliberately kept as two rather than merged:

  * **Rendered text.** `document.body.innerText` at each named surface, in the real built app.
    This is the half that catches a character a source scan would miss — one composed at runtime,
    or shipped inside the vendored kit and rendered by a kit component this app mounts.
  * **The built bundle.** `web/dist/**` (JS, CSS, HTML), scanned twice: once as the bytes on disk,
    and once with JavaScript escape sequences (`\\uXXXX`, `\\u{XXXXX}`, surrogate pairs) decoded
    first — a minifier is free to emit either form, and a scan of only the literal bytes is
    trivially defeated by the escaped one.

Two documented deviations from the scenario text, both widening the gate rather than narrowing it,
both reported rather than decided silently:

  1. *"the built JS bundle's extracted i18n table"* — this app has no i18n table and no i18n
     library (`docs/DEPENDENCIES.md`'s cap; every string is a literal in a `.vue` template). The
     bundle is therefore scanned **whole**, which is a strict superset of any string table that
     could have been extracted from it: an emoji anywhere in the shipped bytes fails, whether or
     not it sits in a string literal.
  2. *"every error state reachable in S-75"* — S-75's error state is produced by killing uvicorn
     mid-session. `tests/ui/conftest.py::Server` as committed holds no handle to that process
     (only `base_url`/`token`/`dsn`/`log_path`), and `docs/E2E.md` §1 fixes the instrumentation
     list at exactly three entries, none of which is network fault injection — so that surface is
     not reachable from this scenario without S-75's own `kill_backend`/`restart_backend` hook,
     which is a separate work package. Its copy is covered here by the bundle scan above, which
     reads every error string the app can ever render, reached or not. When S-75's hook lands,
     this test gains one more surface and nothing else changes. Flagged upstream, not skipped.

The character set is the **union** of the two documents' lists, because they disagree and the
union can only ever fail more than either alone:

  * `docs/E2E.md` S-78's enumerated ranges — `U+1F000–1FAFF`, `U+2600–27BF`, `U+2B00–2BFF`,
    `U+FE0F`, `U+200D`, and the eight named singletons — implemented in Python below.
  * `ACCEPTANCE.md` AC-122's property test — `/\\p{Extended_Pictographic}|[\\u{1F1E6}-\\u{1F1FF}]|
    \\uFE0F|\\u20E3/u` — run in the browser's own regex engine, which supports Unicode property
    escapes natively (no new dependency, per AC-122's own note). Python's `re` has no `\\p{…}`,
    so this half runs where a real engine for it already exists.

E2E.md's closing line — "`ACCEPTANCE.md` AC-122 and AC-184 must cite the same list" — is a doc
task, not a code one; the disagreement between the two lists is reported, and this file implements
both sides so neither document can be satisfied while the other is violated.
"""

from __future__ import annotations

import re
from pathlib import Path

from playwright.sync_api import Page, expect

from tests.ui.conftest import REPO_ROOT, UiSession, activate_column
from tests.ui.views import FIELD

DIST = REPO_ROOT / "web" / "dist"

# docs/E2E.md S-78, verbatim.
EMOJI_RANGES: tuple[tuple[int, int], ...] = (
    (0x1F000, 0x1FAFF),  # one contiguous range; absorbs the regional-indicator flags U+1F1E6-1F1FF
    (0x2600, 0x27BF),
    (0x2B00, 0x2BFF),  # Miscellaneous Symbols and Arrows — decorative stars live here
    (0xFE0F, 0xFE0F),  # variation selector 16
    (0x200D, 0x200D),  # zero-width joiner
)
EMOJI_SINGLETONS = frozenset(
    {0x203C, 0x2049, 0x2122, 0x2139, 0x3030, 0x303D, 0x3297, 0x3299}
)

# ACCEPTANCE.md AC-122's property test, run in the browser's own engine (see the module docstring).
AC122_REGEX_JS = r"/\p{Extended_Pictographic}|[\u{1F1E6}-\u{1F1FF}]|\uFE0F|\u20E3/u"

CARD_TITLE = '[data-goal-id="SYNSCH04"] > .goal-card__row .goal-card__title'
# KK ruling, 2026-08-09: the schedule trigger moved off the board card into the detail editor
# (`GoalDetailEditor.vue`), so opening its popover now requires the detail surface open first —
# `SCHEDULE_CARD_TITLE` below. The trigger remains under `#goal-detail`, but `PopoverEngine`
# portals the opened menu to the body-level `#dropdownPortal`; its schedule-grid content makes
# that portalled surface unambiguous.
# Ruling 1 (owner, 2026-08-09) also took the Maybe column off the board, so a Maybe card
# (`SYNMAY01`, this selector's original target) is not reachable here at all — the board is the
# active nav view throughout this file, and an unverticaled card renders only in the Inbox view
# (`InboxView.vue`), mutually exclusive on screen with the board (`App.vue`'s `v-if`/`v-else`).
# `SYNSCH05` is an already-verticaled, already-on-the-board card (`month`, parentless, distinct
# from `CARD_TITLE`'s own `SYNSCH04`) — this scenario only needs *a* card whose detail surface it
# can open to reach the popover, not specifically an unverticaled one, so no nav detour is needed.
SCHEDULE_CARD_TITLE = '[data-goal-id="SYNSCH05"] .goal-card__title'
# Since the opened-card cleanup (KK 27-28 Sep 2026) the open goal's date is the first fact under its title, and it
# opens the same schedule popover (GoalFacts.vue).
SCHEDULE_TRIGGER = '.goal-card--detail-open .goal-facts [data-cap="schedule"]'
SCHEDULE_POPOVER = (
    '#dropdownPortal [data-popover-surface][data-state="open"]:has(.schedule-popover__row)'
)
DETAIL_BODY = ".goal-detail__body"
# The search modal left with the bottom bar's redo (3bc40f9): words go into the one field, and when nothing matches, the
# field itself says so on the line above it.
SEARCH_EMPTY = '[data-role="search-empty"]'

# A query that clears the 3-character client-side floor (§10-D6) and matches nothing in F2, so the
# results panel renders its empty state rather than a list.
EMPTY_STATE_QUERY = "zzqx"


def _offenders(text: str, where: str) -> list[str]:
    """Every character of `text` inside the E2E.md range list, reported with its code point, the
    surface it came from, and ~30 characters of surrounding context so a failure names the string
    rather than only the character."""
    hits = []
    for i, ch in enumerate(text):
        o = ord(ch)
        if o in EMOJI_SINGLETONS or any(lo <= o <= hi for lo, hi in EMOJI_RANGES):
            context = text[max(0, i - 30) : i + 30].replace("\n", "\\n")
            hits.append(f"{where}: U+{o:04X} in …{context}…")
    return hits


# `\uXXXX`, `\u{XXXXX}` and `\xXX` — the three forms a JS minifier can emit for a character it
# does not want to write literally. Decoded before the scan so an escaped emoji is caught too.
_ESCAPE_RE = re.compile(r"\\u\{([0-9a-fA-F]{1,6})\}|\\u([0-9a-fA-F]{4})|\\x([0-9a-fA-F]{2})")


def _decode_js_escapes(text: str) -> str:
    def sub(m: re.Match[str]) -> str:
        hexdigits = m.group(1) or m.group(2) or m.group(3)
        cp = int(hexdigits, 16)
        return chr(cp)

    decoded = _ESCAPE_RE.sub(sub, text)
    # A surrogate pair written as two `\uXXXX` escapes decodes to two lone surrogates above; join
    # them back into the astral character they encode, so the U+1F000-1FAFF range sees it.
    return decoded.encode("utf-16", "surrogatepass").decode("utf-16", "replace")


def _ac122_hits(page: Page, text: str) -> list[str]:
    """AC-122's property regex, evaluated by the browser. Returns the matched characters."""
    return page.evaluate(
        "(s) => Array.from(s.matchAll(new RegExp(" + AC122_REGEX_JS + ".source, 'gu'))).map(m => m[0])",
        text,
    )


def _surface_text(page: Page) -> str:
    return page.evaluate("document.body.innerText")


def test_s78_no_emoji_in_any_user_facing_string(ui_f2: UiSession) -> None:
    session = ui_f2
    page = session.page
    surfaces: dict[str, str] = {}

    # --- surface 1: the board -----------------------------------------------------------------
    expect(page.locator(CARD_TITLE)).to_be_visible()
    surfaces["board"] = _surface_text(page)

    # --- surface 2: the detail surface --------------------------------------------------------
    activate_column(page, "month")
    page.click(CARD_TITLE)
    expect(page.locator(DETAIL_BODY)).to_be_visible()
    surfaces["detail"] = _surface_text(page)
    page.keyboard.press("Escape")
    expect(page.locator(DETAIL_BODY)).to_be_hidden()

    # --- surface 3: the popover, reached through the detail surface (KK ruling 2026-08-09) -----
    activate_column(page, "month")
    page.click(SCHEDULE_CARD_TITLE)
    expect(page.locator(SCHEDULE_TRIGGER)).to_be_visible()
    page.click(SCHEDULE_TRIGGER)
    popover = page.locator(SCHEDULE_POPOVER)
    expect(popover).to_be_visible()
    assert popover.inner_text().strip(), "schedule popover rendered no text — its emoji scan would be vacuous"
    surfaces["popover"] = _surface_text(page)
    page.keyboard.press("Escape")
    expect(page.locator(SCHEDULE_POPOVER)).to_be_hidden()
    page.keyboard.press("Escape")
    expect(page.locator(DETAIL_BODY)).to_be_hidden()

    # --- surface 4: the empty state -----------------------------------------------------------
    page.locator(FIELD).click()
    page.fill(FIELD, EMPTY_STATE_QUERY)
    panel = page.locator(SEARCH_EMPTY)
    expect(panel).to_be_visible(timeout=10000)
    expect(panel).to_contain_text("Nothing matches")
    surfaces["empty-state"] = _surface_text(page)

    # --- scan 1: rendered text, both character sets -------------------------------------------
    offenders: list[str] = []
    for name, text in surfaces.items():
        assert text.strip(), f"surface {name!r} rendered no text at all — the scan would pass vacuously"
        offenders += _offenders(text, name)
        property_hits = _ac122_hits(page, text)
        offenders += [f"{name}: AC-122 property match {c!r}" for c in property_hits]

    # --- scan 2: the built bundle -------------------------------------------------------------
    bundle_files = sorted(
        p
        for p in DIST.rglob("*")
        if p.is_file() and p.suffix in {".js", ".css", ".html", ".json", ".map"}
    )
    assert bundle_files, f"no built bundle under {DIST} — the build fixture did not run"
    for path in bundle_files:
        raw = path.read_text(encoding="utf-8", errors="replace")
        rel = str(path.relative_to(REPO_ROOT))
        offenders += _offenders(raw, rel)
        offenders += _offenders(_decode_js_escapes(raw), f"{rel} (escapes decoded)")
        offenders += [f"{rel}: AC-122 property match {c!r}" for c in _ac122_hits(page, raw)]

    assert not offenders, (
        "no user-facing string may contain an emoji (CLAUDE.md house law; AC-122/AC-184):\n"
        + "\n".join(offenders[:40])
        + (f"\n… and {len(offenders) - 40} more" if len(offenders) > 40 else "")
    )


def test_s78a_the_emoji_scan_catches_a_planted_emoji(ui_f2: UiSession) -> None:
    """The gate's own discriminator, in the same spirit as `tests/static/test_no_mocks.py`'s
    planted-import tests and `tests/static/test_pixel_gate_discriminates.py`: a scan that cannot
    be shown to fail on a real emoji is not evidence of anything. Three characters, one per
    mechanism the union covers — an astral pictograph, a regional-indicator flag (which fell
    between the two ranges S-78's list used to name), and a Miscellaneous-Symbols star.

    Nothing is planted in the application: the strings below are built in this test and passed
    through the same two functions the scan above uses. `web/src/**` is never touched.
    """
    page = ui_f2.page
    planted = {
        "astral pictograph": "Ship it \U0001f680 today",
        "regional indicator flag": "Locale \U0001f1e6\U0001f1e8 selected",
        "miscellaneous symbol star": "Favourite \u2b50 goal",
        "variation selector": "Warning \u2757\ufe0f now",
    }
    for name, text in planted.items():
        assert _offenders(text, name), f"the E2E.md range scan missed a planted {name}: {text!r}"
        assert _ac122_hits(page, text), f"AC-122's property test missed a planted {name}: {text!r}"

    # And the converse: ordinary product copy, including the app's own non-ASCII characters
    # (the ellipsis in "Loading…", the en dash), must not trip either half.
    clean = "Loading… Remove sample data — no matches. Q3 groundwork, 2026-W32."
    assert _offenders(clean, "clean") == [], "the range scan flagged ordinary copy"
    assert _ac122_hits(page, clean) == [], "AC-122's property test flagged ordinary copy"
