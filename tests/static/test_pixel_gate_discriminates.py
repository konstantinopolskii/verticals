"""The suite-G pixel gate, proved to fail on the things it exists to catch — and to stay silent
on the things it must not.

`assert_matches_reference` is two conditions, and both were added because the catalogue's single
condition could be passed by a render that proves nothing. A guard that has only ever been watched
passing is indistinguishable from a guard that cannot fail, so this file plants the violations.

**Why this is in `static` and not in `uidiff`.** Every case here is decided by the two comparison
scripts and the committed reference fixtures — no database, no browser, no F3. Suite G gates on a
machine that lacks `seed/`, which is every machine but one; a rule that only executes where the
personal corpus lives is a rule almost nobody runs. `tests/harness/report.py::suite_of` derives the
suite from the path segment after `tests/`, so this file attributes to `static`, which needs
neither. The `uidiff` scenario stays where it belongs and this file proves the instrument under it.

No test here claims a scenario id. §9's rows are the measurements; this is the instrument beneath
them, which the catalogue does not give an id of its own.

The six cases are the ones `docs/PENDING_DOC_FIXES.md` row 72 was written from, re-derived here
rather than quoted, so a future change to either script has to keep them true rather than keep a
table in a document true.
"""

from __future__ import annotations

import json
import struct
import subprocess
import zlib
from pathlib import Path

import pytest

from tests.uidiff.conftest import (
    BLANKNESS_MJS,
    COMPARE_MJS,
    MATCH_FLOOR,
    REFERENCE_DIR,
    UIREF_DIR,
    assert_matches_reference,
)

# The two surfaces this file leans on, chosen for opposite reasons: `board` is what S-100 measures
# and is dense enough that a wrong render should be visible; `inbox` is the sparsest committed
# surface and is the one that defeats a naive absolute floor.
BOARD = REFERENCE_DIR / "board-1458x779.png"
INBOX = REFERENCE_DIR / "inbox-1458x779.png"
GOAL = REFERENCE_DIR / "goal-1458x779.png"
SEARCH = REFERENCE_DIR / "search-1458x779.png"

# The reference capture's device-pixel size: 1458x779 CSS at deviceScaleFactor 2
# (`tools/uiref/render.mjs`). A planted image must match it exactly or `pixelmatch` refuses the
# comparison outright, which is itself asserted below.
REF_WIDTH, REF_HEIGHT = 2916, 1558

# The background the reference planner's own board sits on. This is the colour that makes the catalogue's
# single condition unfalsifiable, so it is the colour the planted blank page uses.
PLANNER_BG = (0xF7, 0xF7, 0xF5)


def _write_flat_png(path: Path, rgb: tuple[int, int, int], width: int, height: int) -> Path:
    """A solid-colour PNG, written with the standard library only.

    Deliberately not generated with `pngjs` through the scripts under test: a fixture built by the
    same library the assertion runs on can hide a defect in that library's round trip, and the
    point of this file is that the planted violation is independent of the thing it tests. `zlib`
    and `struct` are enough — a PNG is a signature, IHDR, one IDAT of zlib-compressed scanlines
    each prefixed with a zero filter byte, and IEND.
    """

    def chunk(kind: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + kind
            + data
            + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
        )

    row = b"\x00" + bytes(rgb) * width
    png = (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(row * height, 6))
        + chunk(b"IEND", b"")
    )
    path.write_bytes(png)
    return path


def _run(script: Path, *args: str) -> dict:
    proc = subprocess.run(
        ["node", str(script), *args], cwd=UIREF_DIR, capture_output=True, text=True, timeout=120
    )
    if proc.returncode != 0:
        raise AssertionError(f"{script.name} exited {proc.returncode}: {proc.stderr.strip()}")
    return json.loads(proc.stdout)


def measure(actual: Path, reference: Path, tmp_path: Path) -> dict:
    """The same two measurements `tests/uidiff/conftest.py::compare_to_reference` performs, merged
    the same way, so what is asserted here is what a scenario would see."""
    result = _run(COMPARE_MJS, str(actual), str(reference), str(tmp_path / "diff.png"))
    blank = _run(BLANKNESS_MJS, str(actual), str(tmp_path / "blank.png"))
    result["blankness"] = blank["blankness"]
    result["visible_pixels"] = blank["visible_pixels"]
    result["dominant_colour"] = blank["dominant_colour"]
    result["dominant_share"] = blank["dominant_share"]
    return result


# --- the planted violations: renders that must NOT certify ---------------------------------------


def test_a_blank_page_in_the_reference_background_colour_does_not_certify(tmp_path: Path) -> None:
    """The case that motivated the second condition. An app that drew nothing but the right
    background colour scores **above** the catalogue's bar against the real board reference, so
    the bar alone would certify it. Both facts are asserted: that the ratio passes, and that the
    scenario refuses anyway. Asserting only the refusal would let a future change fix this by
    making the ratio fail for some unrelated reason, and the specific defect would go unwatched."""
    blank = _write_flat_png(tmp_path / "blank.png", PLANNER_BG, REF_WIDTH, REF_HEIGHT)
    result = measure(blank, BOARD, tmp_path)

    assert result["match_ratio"] >= MATCH_FLOOR, (
        f"the premise of row 72 no longer holds: a flat {PLANNER_BG} page now scores "
        f"{result['match_ratio']:.4f} against the board reference, below the {MATCH_FLOOR:.2f} "
        f"bar. If the reference was re-captured this is expected — re-derive row 72's numbers "
        f"rather than deleting this test, because the *shape* of the defect survives a re-capture."
    )
    assert result["blankness"] == pytest.approx(1.0), (
        f"a flat fill must be maximally blank; got {result['blankness']:.4f}"
    )
    with pytest.raises(AssertionError, match="resembles a blank page"):
        assert_matches_reference(result, "board")


def test_the_wrong_screen_entirely_does_not_certify(tmp_path: Path) -> None:
    """The second false green the ratio alone admits: the real inbox surface, rendered where the
    board was wanted, clears 0.90 against the board reference. Two different screens, both mostly
    background, agreeing on the background."""
    result = measure(INBOX, BOARD, tmp_path)

    assert result["match_ratio"] >= MATCH_FLOOR, (
        f"inbox-vs-board now scores {result['match_ratio']:.4f}, below the bar — the fixtures "
        f"changed and this file's premise needs re-deriving, not deleting"
    )
    with pytest.raises(AssertionError, match="resembles a blank page"):
        assert_matches_reference(result, "board")


def test_a_grossly_different_screen_is_caught_by_the_ratio_not_the_blankness_test(
    tmp_path: Path,
) -> None:
    """The case that shows the second condition does **not** subsume the first, which is the whole
    reason both ship. The goal surface rendered where search was wanted has plenty of ink — it
    resembles the reference far more than it resembles nothing — so the relative test passes it.
    The ratio is what refuses it. Remove either condition and one of these three tests goes red."""
    result = measure(GOAL, SEARCH, tmp_path)

    assert result["match_ratio"] > result["blankness"], (
        "premise changed: this case exists because the relative test alone passes it"
    )
    with pytest.raises(AssertionError, match=f"below the {MATCH_FLOOR:.2f} bar"):
        assert_matches_reference(result, "search")


# --- the false-positive guards: renders that MUST certify ----------------------------------------


def test_a_perfect_render_certifies(tmp_path: Path) -> None:
    """The obvious direction, and not redundant: a guard that refuses everything blocks the suite
    forever and would be discovered as noise rather than as a bug."""
    result = measure(BOARD, BOARD, tmp_path)
    assert result["match_ratio"] == 1.0
    assert_matches_reference(result, "board")


def test_the_sparsest_surface_still_certifies_against_itself(tmp_path: Path) -> None:
    """The case that killed the first version of this guard, kept as the record of why.

    An earlier draft used 0.90 as an **absolute** floor on blankness — "if the render is more than
    90% flat, refuse it". The committed fixtures disprove it: the real inbox reference is 0.9971
    flat under this metric and would have been refused as a blank page, and the real board
    reference sits at 0.8998, two ten-thousandths from the same fate. A sparse screen is not an
    empty screen, and only a *relative* comparison can tell them apart."""
    result = measure(INBOX, INBOX, tmp_path)
    assert result["blankness"] > 0.99, (
        f"this test's whole point is that the inbox surface is nearly flat; it now measures "
        f"{result['blankness']:.4f}, so the false-positive it guards against no longer exists here"
    )
    assert_matches_reference(result, "inbox")


# --- the instrument itself -----------------------------------------------------------------------


def test_a_dimension_mismatch_is_refused_rather_than_scaled(tmp_path: Path) -> None:
    """Two images of different sizes have no meaningful match ratio, and silently coercing one
    would produce a number that looks like evidence. This is also the failure a harness hits when
    it renders at the documented 1458x779 without the reference's `deviceScaleFactor: 2`
    (`docs/PENDING_DOC_FIXES.md` row 73), so the error text has to name both sizes."""
    half = _write_flat_png(tmp_path / "half.png", PLANNER_BG, REF_WIDTH // 2, REF_HEIGHT // 2)
    proc = subprocess.run(
        ["node", str(COMPARE_MJS), str(half), str(BOARD), str(tmp_path / "d.png")],
        cwd=UIREF_DIR,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert proc.returncode != 0, "a size mismatch must not produce a ratio"
    assert "size mismatch" in proc.stderr
    assert f"{REF_WIDTH // 2}x{REF_HEIGHT // 2}" in proc.stderr
    assert f"{REF_WIDTH}x{REF_HEIGHT}" in proc.stderr


def test_the_reference_fixtures_are_all_at_the_captured_device_size(tmp_path: Path) -> None:
    """Every committed surface must share one geometry, or a scenario comparing against one of
    them measures something different from a scenario comparing against another. Read out of the
    PNG headers rather than trusted from the filenames — the filenames say 1458x779 and the bytes
    say 2916x1558, which is exactly the confusion row 73 exists to end."""
    for surface in (BOARD, INBOX, GOAL, SEARCH):
        width, height = struct.unpack(">II", surface.read_bytes()[16:24])
        assert (width, height) == (REF_WIDTH, REF_HEIGHT), (
            f"{surface.name} is {width}x{height}, not {REF_WIDTH}x{REF_HEIGHT}; the fixtures no "
            f"longer share a geometry and every suite-G ratio is measuring a different thing"
        )
