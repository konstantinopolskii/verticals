"""Twin snapshots: one state of the app read the same way from any build, so two builds of it can be compared.

`capture()` writes `artifacts/twin/<package>/<state>.html` (the page's DOM, normalized) and `<state>.png` (the
viewport). `python -m tests.harness.twin web web-react` compares two such folders: a unified diff per state that
differs and the count of pixels that differ, with a picture of where (`<state>.diff.png` in the second folder).

The DOM is normalized only where two renderers may differ with nothing different on screen: attribute and class
order, style declaration order, comments, whitespace-only text, generated ids, the framework's own marks
(`data-v-*`) and the `value`/`checked` attributes, which are read as the live properties instead."""

from __future__ import annotations

import difflib
import sys
from pathlib import Path

from playwright.sync_api import Page

from tests.harness.png import decode_png, encode_png
from tests.harness.web import REPO_ROOT, WEB_PREFIX

TWIN_ROOT = REPO_ROOT / "artifacts" / "twin"

NORMALIZED_DOM = r"""() => {
  const GENERATED = /^(v-\d+|:r[0-9a-z]+:|«r[0-9a-z]+»|_r_[0-9a-z]+_)$/
  const REFERS = /^(for|aria-(controls|labelledby|describedby|owns|activedescendant))$/
  const SKIP = new Set(['SCRIPT', 'STYLE', 'TEMPLATE', 'NOSCRIPT'])
  const lines = []
  const attrs = (el) => {
    const out = []
    const field = el instanceof HTMLInputElement || el instanceof HTMLTextAreaElement || el instanceof HTMLSelectElement
    for (const { name, value } of el.attributes) {
      if (name.startsWith('data-v-') || (field && (name === 'value' || name === 'checked'))) continue
      let v = value
      if (name === 'class') v = [...new Set(value.split(/\s+/).filter(Boolean))].sort().join(' ')
      else if (name === 'style') v = value.split(';').map((d) => d.trim().replace(/\s*:\s*/, ': ')).filter(Boolean).sort().join('; ')
      else if (name === 'id' ? GENERATED.test(v) : REFERS.test(name) && v.split(/\s+/).every((t) => GENERATED.test(t))) v = '#generated'
      if ((name === 'class' || name === 'style') && !v) continue
      out.push(`${name}="${v.replace(/"/g, '&quot;')}"`)
    }
    if (field) out.push(`:value="${el.value.replace(/"/g, '&quot;')}"`)
    if (el instanceof HTMLInputElement && (el.type === 'checkbox' || el.type === 'radio')) out.push(`:checked="${el.checked}"`)
    return out.sort()
  }
  const walk = (node, depth) => {
    const pad = '  '.repeat(depth)
    for (const child of node.childNodes) {
      if (child.nodeType === Node.TEXT_NODE) {
        const text = child.data.replace(/\s+/g, ' ').trim()
        if (text) lines.push(pad + text)
      } else if (child.nodeType === Node.ELEMENT_NODE && !SKIP.has(child.tagName)) {
        const a = attrs(child)
        lines.push(`${pad}<${child.tagName.toLowerCase()}${a.length ? ' ' + a.join(' ') : ''}>`)
        walk(child, depth + 1)
      }
    }
  }
  walk(document.body, 0)
  return lines.join('\n') + '\n'
}"""


def twin_dir(package: str = WEB_PREFIX) -> Path:
    return TWIN_ROOT / package


def capture(page: Page, state: str) -> Path:
    """The state as it stands now; motion is expected to be settled (the suite runs with reduced motion)."""
    out = twin_dir()
    out.mkdir(parents=True, exist_ok=True)
    (out / f"{state}.html").write_text(page.evaluate(NORMALIZED_DOM), encoding="utf-8")
    page.screenshot(path=str(out / f"{state}.png"), animations="disabled", caret="hide")
    return out / f"{state}.html"


def pixel_diff(a: Path, b: Path, picture: Path) -> int:
    """Pixels that differ between two captures; where they do is drawn red over a faded copy of `b`."""
    wa, ha, ca, pa = decode_png(a.read_bytes())
    wb, hb, cb, pb = decode_png(b.read_bytes())
    if (wa, ha) != (wb, hb):
        return -1
    if ca == cb and pa == pb:
        return 0
    out = bytearray(wa * ha * 4)
    differ = 0
    for i in range(wa * ha):
        x, y = pa[i * ca:i * ca + 3], pb[i * cb:i * cb + 3]
        if x != y:
            differ += 1
            out[i * 4:i * 4 + 4] = b"\xff\x00\x00\xff"
        else:
            grey = 255 - (255 - sum(y) // 3) // 4
            out[i * 4:i * 4 + 4] = bytes((grey, grey, grey, 255))
    if differ:
        picture.write_bytes(encode_png(wa, ha, bytes(out)))
    return differ


def compare(first: str, second: str, context: int = 3, limit: int = 80) -> int:
    """Print what differs between two packages' captures; the count of states that differ."""
    a, b = twin_dir(first), twin_dir(second)
    states = sorted({p.stem for p in a.glob("*.html")} | {p.stem for p in b.glob("*.html")})
    differing = 0
    for state in states:
        ha, hb = a / f"{state}.html", b / f"{state}.html"
        if not ha.exists() or not hb.exists():
            print(f"{state}: only in {first if ha.exists() else second}")
            differing += 1
            continue
        dom = list(difflib.unified_diff(ha.read_text().splitlines(), hb.read_text().splitlines(),
                                        f"{first}/{state}", f"{second}/{state}", n=context, lineterm=""))
        pixels = pixel_diff(a / f"{state}.png", b / f"{state}.png", b / f"{state}.diff.png")
        if not dom and pixels == 0:
            print(f"{state}: same")
            continue
        differing += 1
        size = "different sizes" if pixels < 0 else f"{pixels} px differ"
        print(f"{state}: {len(dom)} diff lines, {size}")
        print("\n".join(dom[:limit]) + ("\n…" if len(dom) > limit else ""))
    css = css_diff(first, second)
    if css:
        differing += 1
        print(css)
    print(f"{differing} of {len(states)} states differ" + ("" if css else "; the CSS bundles are the same"))
    return differing


def css_diff(first: str, second: str) -> str:
    """The built stylesheets, which must be byte for byte the same: the components' CSS in the same order."""
    a, b = (b"".join(p.read_bytes() for p in sorted((REPO_ROOT / name / "dist" / "assets").glob("*.css"))) for name in (first, second))
    if not a or not b:
        return f"css: no build of {first if not a else second}"
    if a == b:
        return ""
    shorter = min(len(a), len(b))
    at = next((i for i in range(shorter) if a[i] != b[i]), shorter)
    return f"css: differs from byte {at} ({len(a)} vs {len(b)} bytes): {a[at:at + 120]!r} vs {b[at:at + 120]!r}"


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit("usage: python -m tests.harness.twin <package> <package>")
    sys.exit(1 if compare(sys.argv[1], sys.argv[2]) else 0)
