"""The open goal's colour is two shapes that meet: its row's (`::before`) and its list's, which runs on down the steps and
notes (`web/src/lib/goalWash.ts`). One shape running under the list made the system WebKit draw the colour over the notes
for a frame whenever a layer changed (KK, 4 Oct 2026, a recording); two shapes that meet can't overlap.

- While a goal opens, the list travels with its row by the same kind of transform, so the two edges meet on every frame:
  when the list stood still, the row's colour, moved on the compositor, drew ahead of the list's with a white band
  between them (`lib/familyMotion.ts`).
- The move's clocks start once its first frame is on screen (`lib/startTogether.ts`): the first frame that moves is near
  the start of the path, not most of the way along it.
- When the light leaves the open goal's family, the open goal takes the veil's look itself, its row and list together,
  over the veil (z 2), over several frames, and comes back the same way.

Traced frame by frame in the page, motion on."""

from __future__ import annotations

import pytest

from tests.ui.conftest import UiSession
from tests.ui.test_flow4_going_deeper import _seed, _title

OPEN_SAMPLER = r"""(ids) => {
  const s = window.__open = { frames: [], on: false };
  const px = (v) => parseFloat(v) || 0;
  const rowOf = (id) => {
    const card = [...document.querySelectorAll(`.goal-card[data-goal-id="${id}"]`)].find((c) => !c.closest('.family-ghosts'));
    return card ? [card, card.querySelector(':scope > .goal-card__row')] : [null, null];
  };
  function frame() {
    if (!s.on) return;
    const [card, row] = rowOf(ids.open);
    const [, below] = rowOf(ids.below);
    const f = { below: below ? below.getBoundingClientRect().top : null };
    if (row) {
      const r = row.getBoundingClientRect(), k = r.height / row.offsetHeight;
      f.rowEdge = r.bottom - k * px(getComputedStyle(row, '::before').bottom);
      const list = card.nextElementSibling;
      if (list && list.classList.contains('goal-card__children--open')) {
        const l = list.getBoundingClientRect(), m = list.offsetHeight ? l.height / list.offsetHeight : 1;
        f.listEdge = l.top + m * px(getComputedStyle(list, '::before').top);
      }
    }
    s.frames.push(f);
    requestAnimationFrame(frame);
  }
  s.start = () => { s.frames = []; s.on = true; requestAnimationFrame(frame); };
  s.stop = () => { s.on = false; return s.frames; };
}"""

LOOK_SAMPLER = r"""(id) => {
  const s = window.__look = { frames: [], on: false };
  function frame() {
    if (!s.on) return;
    const card = document.querySelector(`.goal-card.goal-card--detail-open[data-goal-id="${id}"]`);
    const row = card.querySelector(':scope > .goal-card__row'), list = card.nextElementSibling;
    const a = getComputedStyle(row), b = getComputedStyle(list);
    const r = row.getBoundingClientRect(), k = r.height / row.offsetHeight;
    const l = list.getBoundingClientRect(), m = l.height / list.offsetHeight;
    s.frames.push({ light: card.dataset.light ?? null, row: parseFloat(a.opacity), list: parseFloat(b.opacity), rowZ: a.zIndex,
      listZ: b.zIndex, rowEdge: r.bottom - k * parseFloat(getComputedStyle(row, '::before').bottom),
      listEdge: l.top + m * parseFloat(getComputedStyle(list, '::before').top) });
    requestAnimationFrame(frame);
  }
  s.start = () => { s.frames = []; s.on = true; requestAnimationFrame(frame); };
  s.stop = () => { s.on = false; return s.frames; };
}"""


@pytest.fixture
def ui_reduced_motion(request: pytest.FixtureRequest) -> str:
    return getattr(request, "param", "no-preference")


def test_the_open_goals_two_colours_meet_on_every_frame_and_the_move_starts_from_the_start(ui_f2: UiSession) -> None:
    fam = _seed(ui_f2)
    page = ui_f2.page
    title = page.locator(_title("quarter", fam.open)).first
    title.hover()
    page.wait_for_timeout(400)
    page.evaluate(OPEN_SAMPLER, {"open": fam.open, "below": fam.sibling})
    page.evaluate("window.__open.start()")
    title.click()
    page.wait_for_timeout(900)
    frames = page.evaluate("window.__open.stop()")

    # the sibling under the opened goal glides down as the goal's list makes room
    tops = [f["below"] for f in frames if f["below"] is not None]
    start, end = tops[0], tops[-1]
    assert end - start > 20, f"the goal under the opened one glides down: {start} -> {end}"
    moving = [t for t in tops if abs(t - start) > 0.5]
    first = (moving[0] - start) / (end - start)
    assert first < 0.45, f"the first frame that moves is near the start of the path, not {first:.0%} along it"
    assert all(b >= a - 0.5 for a, b in zip(moving, moving[1:])), f"it never turns back: {moving[:12]}"
    met = [f for f in frames if "listEdge" in f and "rowEdge" in f]
    assert len(met) > 5, "the list is there while the goal opens"
    gaps = [round(f["listEdge"] - f["rowEdge"], 2) for f in met]
    assert all(abs(g) <= 0.5 for g in gaps), f"the row's colour and the list's meet on every frame: {gaps}"


def test_the_open_goal_takes_the_veils_look_over_the_veil_as_one_piece(ui_f2: UiSession) -> None:
    fam = _seed(ui_f2)
    page = ui_f2.page
    page.locator(_title("quarter", fam.open)).first.click()
    page.wait_for_selector(f'.goal-card.goal-card--detail-open[data-goal-id="{fam.open}"]')
    header = page.locator('.pattern-vertical-board__column[data-vertical="week"] .pattern-vertical-board__header').first
    header.hover()  # on a column's name: no goal under the pointer
    page.wait_for_timeout(900)
    page.evaluate(LOOK_SAMPLER, fam.open)

    def trace(act, wait_ms: int) -> list[dict]:
        page.evaluate("window.__look.start()")
        act()
        page.wait_for_timeout(wait_ms)
        return page.evaluate("window.__look.stop()")

    def check(frames: list[dict], start: float, end: float) -> None:
        for part in ("row", "list"):
            values = [f[part] for f in frames]
            assert values[0] == pytest.approx(start, abs=0.02) and values[-1] == pytest.approx(end, abs=0.02), (part, values[:3], values[-3:])
            between = [v for v in values if min(start, end) + 0.05 < v < max(start, end) - 0.05]
            assert len(between) >= 3, f"the {part} turns over several frames: {values[:16]}"
        assert all(f["rowZ"] == "2" and f["listZ"] == "2" for f in frames), "the open goal stays over the veil throughout"
        assert all(abs(f["row"] - f["list"]) < 0.03 for f in frames), "its row and list fade as one piece"
        assert all(abs(f["listEdge"] - f["rowEdge"]) <= 0.5 for f in frames), "its two colours meet and never overlap"

    off = trace(lambda: page.locator(_title("quarter", fam.unrelated)).first.hover(), 900)
    lit = off[0]["row"]
    assert lit == pytest.approx(1, abs=0.02), off[0]
    dim = off[-1]["row"]
    assert dim < 0.6, f"with the light on another family the open goal takes the veil's look: {dim}"
    check(off, lit, dim)
    back = trace(lambda: header.hover(), 1300)  # the hand leaves: after the light's grace it comes back the same way
    check(back, dim, lit)
