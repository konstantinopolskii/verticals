"""One switch for reduced motion (`docs/design/column-bounce.md`): the desktop app's Reduce Motion item (View menu) tells the
page its answer on <html> (`data-reduce-motion="on"` or `"off"`), and everything that obeys the system's
`prefers-reduced-motion` obeys it too.

Scripts ask one function, `reducedMotion()` in `web/src/lib/motion.ts`. Styles go through the build: `web/vite.config.ts`
copies every `@media (prefers-reduced-motion: reduce)` block under the switch's `on`, and lets the original block apply
only while the app has given no answer. A rule written tomorrow gets both without anyone remembering; a form the copy
can't translate fails the build. This file counts, so a block that never reached the build (a stylesheet outside it, a
plugin that stopped running) shows as a difference of numbers."""

from __future__ import annotations

import json
import os
import re
import subprocess
from collections.abc import Iterator
from pathlib import Path

import pytest

from tests.harness.report import gate
from tests.static.conftest import REPO_ROOT, WEB_DIR, WEB_SRC_DIR
from verticals import host

BLOCK = re.compile(r"@media\s*\(\s*prefers-reduced-motion\s*:\s*reduce\s*\)\s*\{", re.IGNORECASE)
ON = "[data-reduce-motion=on]"  # the copy's mark, once per selector
UNANSWERED = ":not([data-reduce-motion])"  # the original's mark, once per selector


def _blocks(css: str) -> list[str]:
    """The inside of every reduced-motion block (comments gone first, so a sentence about the rule isn't one)."""
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.DOTALL)
    bodies = []
    for found in BLOCK.finditer(css):
        depth, end = 1, found.end()
        while depth and end < len(css):
            depth += {"{": 1, "}": -1}.get(css[end], 0)
            end += 1
        bodies.append(css[found.end():end - 1])
    return bodies


def _selectors(body: str) -> int:
    """How many selectors the rules inside a block name: a list counts each of its members."""
    count = 0
    for prelude in re.findall(r"([^{}]+)\{[^{}]*\}", body):
        depth = 0
        count += 1
        for char in prelude:
            depth += {"(": 1, "[": 1, ")": -1, "]": -1}.get(char, 0)
            count += char == "," and depth == 0
    return count


def _sources() -> Iterator[Path]:
    yield from sorted(path for path in WEB_SRC_DIR.rglob("*") if path.suffix in {".css", ".tsx"})


@pytest.fixture(scope="module")
def built_css(tmp_path_factory: pytest.TempPathFactory) -> str:
    """The page's own build, not minified so that every rule stays where the plugin put it, in a folder of its own (the
    `web/dist` the UI suite serves is left alone)."""
    if not (WEB_DIR / "node_modules" / "vite").is_dir():
        gate("web/node_modules is not installed (run `npm --prefix web ci`)")
    out = tmp_path_factory.mktemp("reduce-motion-build")
    run = subprocess.run(
        [host.NPM, "--prefix", "web", "run", "build", "--", "--outDir", str(out), "--emptyOutDir", "--minify", "false"],
        cwd=REPO_ROOT, capture_output=True, text=True, timeout=300,
    )
    assert run.returncode == 0, f"the build failed:\n{run.stdout[-1500:]}\n{run.stderr[-1500:]}"
    return "\n".join(path.read_text(encoding="utf-8") for path in sorted(out.rglob("*.css")))


def test_every_reduced_motion_block_is_copied_under_the_switch(built_css: str) -> None:
    blocks = selectors = 0
    for path in _sources():
        for body in _blocks(path.read_text(encoding="utf-8")):
            blocks += 1
            selectors += _selectors(body)
    assert blocks >= 25, f"found only {blocks} reduced-motion blocks in the sources: has the scan lost its way?"

    built_blocks = _blocks(built_css)
    assert len(built_blocks) == blocks, (
        f"{blocks} reduced-motion blocks in web/src and the kit, {len(built_blocks)} in the built CSS: "
        "a stylesheet the build doesn't take in, or a block the plugin removed"
    )
    assert built_css.count(ON) == selectors, (
        f"{selectors} selectors in the blocks, {built_css.count(ON)} copied under the switch's `on`"
    )
    assert built_css.count(UNANSWERED) == selectors, (
        f"{selectors} selectors in the blocks, {built_css.count(UNANSWERED)} that wait for the app to give no answer"
    )


def test_scripts_ask_one_function_whether_motion_is_reduced() -> None:
    """A script that asks the system by itself (`matchMedia('(prefers-reduced-motion…')`) never hears the app's switch."""
    asking = re.compile(r"matchMedia\(\s*[`'\"][^`'\"]*prefers-reduced-motion")
    offenders = [
        path.relative_to(WEB_SRC_DIR).as_posix()
        for path in sorted(WEB_SRC_DIR.rglob("*"))
        if path.suffix in {".ts", ".tsx"} and path.name != "motion.ts" and asking.search(path.read_text(encoding="utf-8"))
    ]
    assert offenders == [], f"use reducedMotion() from lib/motion.ts instead of matchMedia in {offenders}"


# The plugin itself, on CSS written for the purpose: Vite loads the real config, the config hands over the real plugin.
_PLUGIN = """
import { loadConfigFromFile } from 'vite'
import postcss from 'postcss'
const { config } = await loadConfigFromFile({ command: 'build', mode: 'production' }, 'vite.config.ts', process.cwd())
const plugin = config.css.postcss.plugins[0]
const out = []
for (const css of JSON.parse(process.env.CASES)) {
  try { out.push({ css: (await postcss([plugin]).process(css, { from: undefined })).css }) }
  catch (error) { out.push({ error: error.reason ?? error.message }) }
}
console.log(JSON.stringify(out))
"""


def _through_the_plugin(*cases: str) -> list[dict]:
    if not (WEB_DIR / "node_modules" / "postcss").is_dir():
        gate("web/node_modules is not installed (run `npm --prefix web ci`)")
    run = subprocess.run(
        ["node", "--input-type=module", "-e", _PLUGIN], cwd=WEB_DIR, capture_output=True, text=True, timeout=120,
        env={**os.environ, "CASES": json.dumps(cases)},
    )
    assert run.returncode == 0, run.stderr[-1500:]
    return json.loads(run.stdout.strip().splitlines()[-1])


def _flat(css: str) -> str:
    """The same CSS without the spacing the stylesheet's own formatting left around its braces and semicolons."""
    return re.sub(r"\s*([{};])\s*", r"\1", re.sub(r"\s+", " ", css)).strip()


def test_a_copy_weighs_what_its_original_weighs_and_sits_right_after_it() -> None:
    """`:where` adds no weight, so the switch can't win a fight the system setting would lose, or the other way round;
    a rule that begins with `:root` or `html` puts the attribute on that element instead of under it; a block that also
    asks for something else (a hover) keeps asking for it in the copy."""
    plain, conditions = _through_the_plugin(
        "@media (prefers-reduced-motion: reduce) { :root { --a: 0; } .x, .y:hover { transition: none; } html .z { color: red; } }",
        "@media (hover: hover) and (prefers-reduced-motion: reduce) { .a:hover { transform: none; } }",
    )
    assert _flat(plain["css"]) == _flat(
        "@media (prefers-reduced-motion: reduce) {"
        " :root:where(:not([data-reduce-motion])) { --a: 0; }"
        " :where(:root:not([data-reduce-motion])) .x, :where(:root:not([data-reduce-motion])) .y:hover { transition: none; }"
        " html:where(:not([data-reduce-motion])) .z { color: red; } }"
        " :root:where([data-reduce-motion=on]) { --a: 0; }"
        " :where(:root[data-reduce-motion=on]) .x, :where(:root[data-reduce-motion=on]) .y:hover { transition: none; }"
        " html:where([data-reduce-motion=on]) .z { color: red; }"
    )
    assert _flat(conditions["css"]) == _flat(
        "@media (hover: hover) and (prefers-reduced-motion: reduce) {"
        " :where(:root:not([data-reduce-motion])) .a:hover { transform: none; } }"
        " @media (hover: hover) { :where(:root[data-reduce-motion=on]) .a:hover { transform: none; } }"
    )


@pytest.mark.parametrize("css", [
    "@media (prefers-reduced-motion: no-preference) { .a { x: y; } }",
    "@media not (prefers-reduced-motion: reduce) { .a { x: y; } }",
    "@media (prefers-reduced-motion: reduce), print { .a { x: y; } }",
    "@media (prefers-reduced-motion: reduce) { @keyframes a { from { x: y; } } }",
    ".a { @media (prefers-reduced-motion: reduce) { x: y; } }",
])
def test_a_form_the_copy_cannot_follow_fails_the_build(css: str) -> None:
    """Better a stop at the stylesheet's line than a rule that quietly misses the switch."""
    (result,) = _through_the_plugin(css)
    assert "css" not in result and "Reduce Motion switch" in result["error"], result
