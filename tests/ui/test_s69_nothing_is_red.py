"""S-69 — L3: nothing is red.

`docs/E2E.md` §6, S-69 (line 1644). Required by AC-111, AC-113, AC-114, AC-178.

    Steps: four captures — two boards x two themes. `/h/2026-08-08`, where G6's six coloured
    cards and `SYNCOL07` are live, and `/h/2025-01-06`, the stale board. Screenshot the board
    region in each.
    Assert, in order, on all four captures: (1) no rendered string matches
    `/overdue|просроч|late|behind|failed/i`; (2) no element under the board carries a class or
    `data-*` value matching `/overdue|danger|error|warn|alert|late/`; (3) zero pixels satisfying
    `R >= 140 and R - G >= 45 and R - B >= 45`; (4) four zeroes, not one; (5) on the two
    2026-08-08 captures, the neutral-card/value-affordance computed-style table.

**This scenario gates on a missing application behaviour.** There is no route for
`/h/<YYYY-MM-DD>` anywhere in the frontend: `web/src/main.ts` boots with a hardcoded
`store.loadBoard(todayIso())`, nothing in `web/src/**` reads `location.pathname`, and the app
ships no router at all (`docs/DEPENDENCIES.md`'s cap — `web/vite.config.ts`'s own header: "no
router"). The pinned clock makes `/` the 2026-08-08 board, so two of the four captures are
reachable and every assertion above is exercised against them before the gate is reported; the
`/h/2025-01-06` half — and with it AC-114's "navigate to `/h/2025-01-06` with `SYNOLD01`/
`SYNOLD02` open" — has no way to be reached from the UI, and this file will not invent one.
Building the route is application work (`web/src/**`), which this work package does not own.

Everything below is written to run unchanged the day that route lands: the stale-board half is a
loop over the same helper functions, guarded by one reachability probe.

The PNG decoder is hand-rolled (`_decode_png`) — `zlib` is stdlib, and this repo's
dependency cap (AC-086, `docs/DEPENDENCIES.md`) is a real constraint, not a preference. Pillow or
numpy for one filter-unwind loop would be a seventh runtime choice bought for a single assertion.
Raw value hues are asserted only on the affordance; card and title colours are resolved from the
design-system tokens at runtime.
"""

from __future__ import annotations

import re
import zlib
from pathlib import Path

import httpx

import pytest
from playwright.sync_api import Page, expect

from tests.harness.report import artifact, gate
from tests.ui.conftest import ARTIFACTS_ROOT, REPO_ROOT, UiSession

BOARD = ".pattern-vertical-board"

# docs/E2E.md S-69 assertion 1 and 2, verbatim.
FORGIVENESS_TEXT_RE = re.compile(r"overdue|просроч|late|behind|failed", re.IGNORECASE)
PUNISHING_ATTR_RE = re.compile(r"overdue|danger|error|warn|alert|late")

# Assertion 3's predicate and its threshold. The justification table in E2E.md S-69 is regenerated
# below from the same closed form rather than copied as literals, so a formula change fails here
# instead of silently agreeing with a stale table.
RED_R_FLOOR = 140
RED_CHANNEL_GAP = 45

# The six canon hues, in the order S-69's own table lists them, each with the F2 row that carries
# it (G6). `SYNCOL07` is the seventh row and has no colour.
CANON_HUES: tuple[tuple[str, str], ...] = (
    ("SYNCOL01", "#ecce32"),
    ("SYNCOL02", "#df496d"),
    ("SYNCOL03", "#92ce14"),
    ("SYNCOL04", "#278dea"),
    ("SYNCOL05", "#955be0"),
    ("SYNCOL06", "#f2713a"),
)
NEUTRAL_ID = "SYNCOL07"

STALE_BOARD_PATH = "/h/2025-01-06"
STALE_IDS = ("SYNOLD01", "SYNOLD02")

GATE_REASON = (
    "the frontend has no anchor-date route: web/src/main.ts boots with a hardcoded "
    "store.loadBoard(todayIso()), nothing under web/src/** reads location.pathname, and the app "
    "ships no router — so S-69's `/h/2025-01-06` capture (and AC-114's stale board) is "
    "unreachable. The two `/h/2026-08-08` captures ran and passed first"
)


def _hex_rgb(hex_color: str) -> tuple[int, int, int]:
    n = int(hex_color.lstrip("#"), 16)
    return ((n >> 16) & 255, (n >> 8) & 255, n & 255)


# D184 (owner, 2026-08-13): checkbox box colours are the shipped palette table, no longer a
# computed 20% wash of the hue. Keyed by goal source hue; value is the exact computed
# backgroundColor string the browser reports (rgb() at opacity 1, rgba() otherwise).
D184_BOX_CSS: dict[str, str] = {
    "#ecce32": "rgb(255, 228, 92)",        # yellow: #ffe45c
    "#df496d": "rgba(255, 0, 60, 0.5)",    # rose: #ff003c at 50%
    "#92ce14": "rgb(195, 236, 105)",       # lime: #c3ec69
    "#278dea": "rgb(181, 214, 242)",       # blue: #b5d6f2
    "#955be0": "rgb(207, 173, 255)",       # violet: #cfadff
    "#f2713a": "rgb(252, 226, 215)",       # orange: #fce2d7
}


def _is_red(r: int, g: int, b: int) -> bool:
    return r >= RED_R_FLOOR and r - g >= RED_CHANNEL_GAP and r - b >= RED_CHANNEL_GAP


# --- PNG decode (stdlib only) ------------------------------------------------------------------

_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def _decode_png(data: bytes) -> tuple[int, int, int, bytes]:
    """`(width, height, channels, pixels)` — `pixels` is the unfiltered, de-interlaced raster,
    `channels` bytes per pixel, rows concatenated. Supports exactly what Chromium's screenshot
    encoder emits: 8-bit, non-interlaced, colour type 2 (RGB) or 6 (RGBA). Anything else raises
    rather than guessing, so a future encoder change is a loud failure, not a silently wrong
    pixel count."""
    if data[:8] != _PNG_MAGIC:
        raise ValueError("not a PNG")
    pos = 8
    header: bytes | None = None
    idat = bytearray()
    while pos + 8 <= len(data):
        length = int.from_bytes(data[pos : pos + 4], "big")
        ctype = data[pos + 4 : pos + 8]
        chunk = data[pos + 8 : pos + 8 + length]
        pos += 12 + length  # 4 length + 4 type + data + 4 crc
        if ctype == b"IHDR":
            header = chunk
        elif ctype == b"IDAT":
            idat += chunk
        elif ctype == b"IEND":
            break
    if header is None:
        raise ValueError("PNG has no IHDR")
    width = int.from_bytes(header[0:4], "big")
    height = int.from_bytes(header[4:8], "big")
    bit_depth, colour_type, _comp, _filt, interlace = header[8], header[9], header[10], header[11], header[12]
    if bit_depth != 8 or interlace != 0 or colour_type not in (2, 6):
        raise ValueError(
            f"unsupported PNG: depth={bit_depth} colour_type={colour_type} interlace={interlace}"
        )
    channels = 3 if colour_type == 2 else 4
    raw = zlib.decompress(bytes(idat))
    stride = width * channels
    out = bytearray(stride * height)
    prev = bytearray(stride)
    src = 0
    dst = 0
    for _y in range(height):
        ftype = raw[src]
        src += 1
        line = bytearray(raw[src : src + stride])
        src += stride
        if ftype == 1:  # Sub
            for x in range(channels, stride):
                line[x] = (line[x] + line[x - channels]) & 255
        elif ftype == 2:  # Up
            for x in range(stride):
                line[x] = (line[x] + prev[x]) & 255
        elif ftype == 3:  # Average
            for x in range(stride):
                left = line[x - channels] if x >= channels else 0
                line[x] = (line[x] + ((left + prev[x]) >> 1)) & 255
        elif ftype == 4:  # Paeth
            for x in range(stride):
                a = line[x - channels] if x >= channels else 0
                b = prev[x]
                c = prev[x - channels] if x >= channels else 0
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                pred = a if (pa <= pb and pa <= pc) else (b if pb <= pc else c)
                line[x] = (line[x] + pred) & 255
        elif ftype != 0:
            raise ValueError(f"unknown PNG filter type {ftype}")
        out[dst : dst + stride] = line
        dst += stride
        prev = line
    return width, height, channels, bytes(out)


def count_red_pixels(png: bytes, excluded: list[dict[str, float]] | None = None) -> int:
    """Assertion 3's own predicate, over every pixel of the decoded capture."""
    width, height, channels, pixels = _decode_png(png)
    excluded = excluded or []
    total = 0
    for y in range(height):
        for x in range(width):
            if any(
                box["x"] <= x <= box["right"] and box["y"] <= y <= box["bottom"]
                for box in excluded
            ):
                continue
            offset = (y * width + x) * channels
            if _is_red(pixels[offset], pixels[offset + 1], pixels[offset + 2]):
                total += 1
    return total


# --- style readers -----------------------------------------------------------------------------

_RGB_RE = re.compile(r"rgba?\((\d+),\s*(\d+),\s*(\d+)")


def parse_css_rgb(value: str) -> tuple[int, int, int]:
    m = _RGB_RE.match(value.strip())
    if not m:
        raise ValueError(f"not an rgb()/rgba() colour: {value!r}")
    return (int(m.group(1)), int(m.group(2)), int(m.group(3)))


_ATTR_SCAN_JS = """
() => {
  const root = document.querySelector('.pattern-vertical-board');
  if (!root) return null;
  const out = [];
  for (const el of root.querySelectorAll('*')) {
    const values = [];
    if (typeof el.className === 'string' && el.className) values.push(el.className);
    for (const attr of el.attributes) {
      if (attr.name.startsWith('data-')) values.push(attr.name + '=' + attr.value);
    }
    if (values.length) out.push({ tag: el.tagName, values });
  }
  return out;
}
"""

_BORDER_JS = """
(id) => {
  const el = document.querySelector('[data-goal-id="' + id + '"]');
  const cs = getComputedStyle(el);
  return {
    borders: [cs.borderTopColor, cs.borderRightColor, cs.borderBottomColor, cs.borderLeftColor],
    outline: cs.outlineColor,
  };
}
"""

_ALL_TEXT_COLOURS_JS = """
() => {
  const root = document.querySelector('.pattern-vertical-board');
  const seen = new Set();
  for (const el of root.querySelectorAll('*')) seen.add(getComputedStyle(el).color);
  return Array.from(seen);
}
"""


def _title_colour(page: Page, goal_id: str) -> tuple[int, int, int]:
    value = page.evaluate(
        "(id) => getComputedStyle("
        "document.querySelector('[data-goal-id=\"' + id + '\"] > .goal-card__row .goal-card__title')"
        ").color",
        goal_id,
    )
    return parse_css_rgb(value)


# --- one capture's worth of assertions ---------------------------------------------------------


def _assert_capture_is_forgiving(page: Page, label: str, out_dir: Path) -> Path:
    """Assertions 1, 2 and 3 for one capture. Returns the PNG path written."""
    board = page.locator(BOARD)
    expect(board).to_be_visible()

    # 1. Text.
    text = board.inner_text()
    matches = FORGIVENESS_TEXT_RE.findall(text)
    assert not matches, f"{label}: the board renders punishing language {matches!r}"

    # 2. Classes and data-* values.
    elements = page.evaluate(_ATTR_SCAN_JS)
    assert elements is not None, f"{label}: no board element found for the class scan"
    offenders = [
        f"<{e['tag']}> {v}" for e in elements for v in e["values"] if PUNISHING_ATTR_RE.search(v)
    ]
    assert not offenders, f"{label}: punishing class/data-* values on the board: {offenders}"

    # 3. Pixels.
    # Carryover state has one owner-ruled red cue: D125/D127's red inline `Due.` title prefix, and since
    # KK's 26 Sep 2026 approval (f3ade3f) one red now-line per carrying column in its place, with its count (the count
    # stands over the 1 px line, outside its box). Keep
    # S-69's punishment scan over every other board pixel while excluding that cue.
    # (D234's .value-bar__dot briefly held a slot here; D238 removed the dots with the bar —
    # value links are plain nav text now, so no menu pixel carries a value colour any more.
    # The scan stays PAGE-wide, which is also what proves that.)
    excluded = page.locator(
        '[data-role="milestone-ring"], [data-role="leaf-square"], [data-role="now-line"], [data-role="now-count"]'
    ).evaluate_all(
        """(els) => {
          const root = document.querySelector('.pattern-vertical-board').getBoundingClientRect();
          return els.map(el => { const r = el.getBoundingClientRect(); return {
            x: Math.floor(r.left - root.left) - 1, y: Math.floor(r.top - root.top) - 1,
            right: Math.ceil(r.right - root.left) + 1, bottom: Math.ceil(r.bottom - root.top) + 1
          }; });
        }"""
    )
    png = board.screenshot()
    path = out_dir / f"{label}.png"
    path.write_bytes(png)
    red = count_red_pixels(png, excluded)
    assert red == 0, (
        f"{label}: {red} pixel(s) satisfy R>={RED_R_FLOOR} and R-G>={RED_CHANNEL_GAP} and "
        f"R-B>={RED_CHANNEL_GAP} — nothing on a board is red (AC-113/AC-178)"
    )
    return path


def _assert_colour_table(page: Page) -> None:
    """R3: card surfaces stay neutral and raw goal hues move into affordances only."""
    goal_hues = {_hex_rgb(h) for _id, h in CANON_HUES}

    tokens = page.evaluate(
        """() => {
          const probe = document.createElement('div');
          probe.style.backgroundColor = 'var(--color-bg)';
          probe.style.color = 'var(--color-text)';
          document.body.appendChild(probe);
          const result = {background:getComputedStyle(probe).backgroundColor, text:getComputedStyle(probe).color};
          probe.remove();
          return result;
        }"""
    )

    for goal_id, hue in CANON_HUES:
        card = page.locator(f'[data-goal-id="{goal_id}"]')
        expect(card).to_be_visible()

        assert card.evaluate("el => getComputedStyle(el).backgroundColor") == tokens["background"]
        assert _title_colour(page, goal_id) == parse_css_rgb(tokens["text"])
        # D147-D157: hue identity lives on the checkbox box; D184: its colour is the shipped
        # palette table entry, asserted as the exact computed string (alpha included).
        box = card.locator(':scope > .goal-card__row [data-role="checkbox-box"]')
        assert box.evaluate("el => getComputedStyle(el).backgroundColor") == D184_BOX_CSS[hue]

        borders = page.evaluate(_BORDER_JS, goal_id)
        for value in borders["borders"] + [borders["outline"]]:
            rgb = parse_css_rgb(value)
            assert rgb not in goal_hues, (
                f"{goal_id}: border/outline colour {value} is a raw goal hue — borders are canon "
                f"token values, never the hue itself"
            )
            assert not _is_red(*rgb), f"{goal_id}: border/outline colour {value} is red"

    # SYNCOL07 — no colour — uses the same neutral card surface.
    neutral_card = page.locator(f'[data-goal-id="{NEUTRAL_ID}"]')
    expect(neutral_card).to_be_visible()
    assert neutral_card.evaluate("el => getComputedStyle(el).backgroundColor") == tokens["background"]
    assert _title_colour(page, NEUTRAL_ID) == parse_css_rgb(tokens["text"])

    # D157 allows raw goal hue in configured checkbox checkmarks; title text remains neutral.


def _stale_board_is_reachable(session: UiSession) -> bool:
    """Probe `/h/2025-01-06` without touching the page under test: a 404 from the static server
    would land in this suite's own network log and turn the gate into a teardown failure, so the
    status is read through `page.request` (an API context, not a page navigation). A 200 only
    means the SPA fallback answered — the board still has to actually render the stale rows, so
    the caller checks those too, after navigating."""
    res = session.page.request.get(f"{session.base_url}{STALE_BOARD_PATH}")
    return res.status == 200


def test_s69_nothing_is_red(ui_f2: UiSession, request: pytest.FixtureRequest) -> None:
    session = ui_f2
    page = session.page
    out_dir = ARTIFACTS_ROOT / "S-69"
    out_dir.mkdir(parents=True, exist_ok=True)

    # A conventional error red must trip the pixel predicate; value-colour affordances are masked.
    assert _is_red(*_hex_rgb("#d32f2f")), "the red predicate does not flag a conventional error red"

    # D231: colour is derived from the life-vertical root now — the SYNCOL fixtures' STORED hues
    # are dead by design. Rebuild the same six-hue table the scenario has always asserted by
    # minting one value root per canon hue and hanging each SYNCOL day card under it; the cards
    # keep their day column (reparent does not reschedule), and the derived wash is the hue.
    for index, (goal_id, hue) in enumerate(CANON_HUES):
        created = httpx.post(
            f"{session.backend.base_url}/api/goals",
            json={
                "title": f"SYN value hue {index + 1}",
                "vertical": "life",
                "anchor_date": "2026-08-08",
                "color": hue,
            },
            headers={"Authorization": f"Bearer {session.backend.token}"},
            timeout=10,
        )
        assert created.status_code == 201, created.text
        adopted = httpx.put(
            f"{session.backend.base_url}/api/goals/{goal_id}/parent",
            json={"parent_id": created.json()["id"]},
            headers={"Authorization": f"Bearer {session.backend.token}"},
            timeout=10,
        )
        assert adopted.status_code == 200, adopted.text
    page.reload()
    page.wait_for_selector('[data-goal-id="SYNCOL01"]', timeout=10000)

    # --- the two reachable captures: 2026-08-08 (the pinned clock's own board) x two themes ----
    for theme in ("light", "dark"):
        page.emulate_media(color_scheme=theme)
        label = f"2026-08-08-{theme}"
        path = _assert_capture_is_forgiving(page, label, out_dir)
        artifact(request, str(path.relative_to(REPO_ROOT)))
        _assert_colour_table(page)

    # --- the stale board: unreachable today ----------------------------------------------------
    if not _stale_board_is_reachable(session):
        gate(GATE_REASON)
    page.goto(f"{session.base_url}{STALE_BOARD_PATH}")
    expect(page.locator(BOARD)).to_be_visible()
    if any(page.locator(f'[data-goal-id="{gid}"]').count() == 0 for gid in STALE_IDS):
        gate(GATE_REASON)
    for theme in ("light", "dark"):
        page.emulate_media(color_scheme=theme)
        _assert_capture_is_forgiving(page, f"2025-01-06-{theme}", out_dir)
        for gid in STALE_IDS:
            card = page.locator(f'[data-goal-id="{gid}"]')
            expect(card).to_be_visible()
            background, neutral = card.evaluate(
                """el => {
                  const probe = document.createElement('div');
                  probe.style.backgroundColor = 'var(--color-bg)';
                  el.appendChild(probe);
                  const result = [getComputedStyle(el).backgroundColor,
                                  getComputedStyle(probe).backgroundColor];
                  probe.remove();
                  return result;
                }"""
            )
            assert background == neutral, (
                f"{gid} is 19 months stale and must render as an ordinary neutral card: "
                f"background {background} != token {neutral} (AC-114)"
            )
