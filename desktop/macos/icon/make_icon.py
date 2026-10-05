"""The Verticals app icon: the mascot (the board's black circle with its upright line, `circleField.css`: an 84 px
circle, a 3 x 24 px line with round ends, here 1.5 times as wide and 1.1 times as tall) on a macOS icon tile.
`AppIcon`: a white tile and a white line. `AppIcon-dev`: the yellow of a yellow goal's checkbox (#ffe45c,
`lib/devPalette.ts`) for the tile and the line, so a dev build never looks like the app people use.

The tile follows Apple's macOS icon grid: a 1024 px canvas, an 824 px tile centred on it with continuous corners
(radius 185.4, smoothed like Apple's), and the grid's shadow under it. In the 16 and 32 px images the line would come
out too thin to read, so it keeps at least 1.375 px of width and 3.85 px of height there.

Usage: .venv/bin/python desktop/macos/icon/make_icon.py   -> AppIcon.svg/.icns and AppIcon-dev.svg/.icns next to it,
which bundle.py puts in the app (`--dev` takes the dev one). Renders through Playwright's Chrome (the repository's test
browser) and builds the .icns with macOS's own iconutil."""
import math, pathlib, shutil, subprocess, tempfile

CANVAS, TILE, RADIUS, SMOOTHING = 1024, 824, 185.4, 0.6
CIRCLE = 0.84 * TILE          # the mascot fills the tile like Telegram's circle (KK, 5 Oct 2026)
# The line, as a share of the circle: the board's line (circleField.css: 3 x 24 px on an 84 px circle) at 1.5 times its
# width and 1.1 times its height, with round ends. At icon size the board's own width read too thin and twice it too
# bold (KK, 5 Oct 2026: "Find the middle line between. And make height 10% bigger of the I").
LINE_W, LINE_H = 4.5 / 84, 26.4 / 84
LOOKS = {
    'AppIcon': {'tile': '#ffffff', 'circle': '#000000', 'line': '#ffffff'},
    'AppIcon-dev': {'tile': '#ffe45c', 'circle': '#000000', 'line': '#ffe45c'},
}


def squircle(x, y, w, h, r, s):
    """A rounded rectangle with continuous corners (figma-squircle's construction, the shape Apple's icons use)."""
    p = min((1 + s) * r, w / 2, h / 2)
    arc = 90 * (1 - s)
    arc_len = math.sin(math.radians(arc / 2)) * r * math.sqrt(2)
    alpha = (90 - arc) / 2
    p34 = r * math.tan(math.radians(alpha / 2))
    beta = 45 * s
    c = p34 * math.cos(math.radians(beta))
    d = c * math.tan(math.radians(beta))
    b = (p - arc_len - c - d) / 3
    a = 2 * b
    f = lambda v: f'{v:.3f}'
    return ' '.join([
        f'M {f(x + w - p)} {f(y)}',
        f'c {f(a)} 0 {f(a + b)} 0 {f(a + b + c)} {f(d)}',
        f'a {f(r)} {f(r)} 0 0 1 {f(arc_len)} {f(arc_len)}',
        f'c {f(d)} {f(c)} {f(d)} {f(b + c)} {f(d)} {f(a + b + c)}',
        f'L {f(x + w)} {f(y + h - p)}',
        f'c 0 {f(a)} 0 {f(a + b)} {f(-d)} {f(a + b + c)}',
        f'a {f(r)} {f(r)} 0 0 1 {f(-arc_len)} {f(arc_len)}',
        f'c {f(-c)} {f(d)} {f(-(b + c))} {f(d)} {f(-(a + b + c))} {f(d)}',
        f'L {f(x + p)} {f(y + h)}',
        f'c {f(-a)} 0 {f(-(a + b))} 0 {f(-(a + b + c))} {f(-d)}',
        f'a {f(r)} {f(r)} 0 0 1 {f(-arc_len)} {f(-arc_len)}',
        f'c {f(-d)} {f(-c)} {f(-d)} {f(-(b + c))} {f(-d)} {f(-(a + b + c))}',
        f'L {f(x)} {f(y + p)}',
        f'c 0 {f(-a)} 0 {f(-(a + b))} {f(d)} {f(-(a + b + c))}',
        f'a {f(r)} {f(r)} 0 0 1 {f(arc_len)} {f(-arc_len)}',
        f'c {f(c)} {f(-d)} {f(b + c)} {f(-d)} {f(a + b + c)} {f(-d)}',
        'Z',
    ])


def svg(look, px=CANVAS):
    """The icon on the 1024 grid, drawn for a render `px` wide (only the line's minimum width depends on it)."""
    colours = LOOKS[look]
    off = (CANVAS - TILE) / 2
    tile = squircle(off, off, TILE, TILE, RADIUS, SMOOTHING)
    cx = cy = CANVAS / 2
    unit = CANVAS / px                       # one rendered pixel, in grid units
    lw = max(CIRCLE * LINE_W, 1.375 * unit)
    lh = max(CIRCLE * LINE_H, 3.85 * unit)
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {CANVAS} {CANVAS}" width="{px}" height="{px}">
  <defs>
    <filter id="shadow" x="-10%" y="-10%" width="120%" height="125%">
      <feDropShadow dx="0" dy="10" stdDeviation="5" flood-color="#000" flood-opacity="0.3"/>
    </filter>
  </defs>
  <path d="{tile}" fill="{colours['tile']}" filter="url(#shadow)"/>
  <circle cx="{cx}" cy="{cy}" r="{CIRCLE / 2:.3f}" fill="{colours['circle']}"/>
  <rect x="{cx - lw / 2:.3f}" y="{cy - lh / 2:.3f}" width="{lw:.3f}" height="{lh:.3f}" rx="{lw / 2:.3f}"
    fill="{colours['line']}"/>
</svg>
"""


# iconutil's names: (file, rendered pixels)
SIZES = [('icon_16x16', 16), ('icon_16x16@2x', 32), ('icon_32x32', 32), ('icon_32x32@2x', 64), ('icon_128x128', 128),
         ('icon_128x128@2x', 256), ('icon_256x256', 256), ('icon_256x256@2x', 512), ('icon_512x512', 512),
         ('icon_512x512@2x', 1024)]


def main(out):
    from playwright.sync_api import sync_playwright
    tmp = pathlib.Path(tempfile.mkdtemp())
    with sync_playwright() as pw:
        browser = pw.chromium.launch(channel='chrome')
        page = browser.new_page(device_scale_factor=1)
        for look in LOOKS:
            (out / f'{look}.svg').write_text(svg(look))
            iconset = tmp / f'{look}.iconset'
            iconset.mkdir()
            for name, px in SIZES:
                page.set_viewport_size({'width': px, 'height': px})
                page.set_content(f'<html><body style="margin:0;background:transparent">{svg(look, px)}</body></html>')
                page.locator('svg').screenshot(path=str(iconset / f'{name}.png'), omit_background=True)
            subprocess.run(['iconutil', '-c', 'icns', str(iconset), '-o', str(out / f'{look}.icns')], check=True)
        browser.close()
    shutil.rmtree(tmp, ignore_errors=True)
    print('\n'.join(str(p) for p in sorted(out.glob('*.icns'))))


if __name__ == '__main__':
    main(pathlib.Path(__file__).resolve().parent)
