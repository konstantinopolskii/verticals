"""S-90 (part 1 of 2) — the 750-line rule. `docs/IMPLEMENTATION.md` WP-18 card, file table row 1.
`docs/E2E.md` S-90 says: "run the check from `ARCHITECTURE.md` §2 verbatim." This file does not,
on purpose, and the reason is load-bearing enough to write down rather than silently work around.

`ARCHITECTURE.md` §2's own quoted command is:

    find verticals -name '*.py' -exec awk 'END{if(NR>750) print FILENAME": "NR" lines"}' {} + \\
      | { ! grep .; }

`find ... -exec ... {} +` batches every matched path into ONE invocation of `awk`. Inside that
one process, `NR` counts records read across the *entire run*, never resetting between files,
and `END`/`FILENAME` fire exactly once, holding whatever the last file happened to be. Run
verbatim against this tree while writing this suite, it printed `verticals/api/__init__.py: 1883
lines` — a real, empty, 0-line file, accused of 1883 lines because 1883 was the sum of every
`*.py` file's line count combined and `api/__init__.py` happened to be last in `find`'s order.
A verbatim run of §2's own command is therefore not a check this suite can trust; it is a
toss-up against `find`'s traversal order, and copying it here would make S-90 fail on a fully
compliant tree the day the wrong file sorts last.

The `Makefile`'s own `lint` target already carries the fix — `FNR` (per-file record count) and
`nextfile` instead of `NR`/`END` — confirmed by running it directly: correct output, nothing
printed, exit 0. `ARCHITECTURE.md` §2's own quoted snippet was simply never updated to match
after `lint` was fixed. Recorded in `docs/PENDING_DOC_FIXES.md`.

So: this file re-implements the *correct* per-file version natively, in Python, which is what
"the 750-line rule" must have meant all along — the number in AC-083/AC-181 is 750 lines per
module, not 750 divided across however many files `find` happens to enumerate first.

`docs/IMPLEMENTATION.md`'s own WP-18 file table extends this file's scope past
`ARCHITECTURE.md` §2's Python-only text to "Python + `.vue`/`.ts`" — `web/src/` now holds both
(WP-12 landed it). AC-083/AC-181/S-90's own wording never mentions the frontend, so the
`.vue`/`.ts` half below is this suite's own addition on top of the four-document contract, laid
on as a second, clearly-separated assertion rather than folded into the Python one.

A third assertion adds `tests/` itself, per the ruling recorded at `docs/PENDING_DOC_FIXES.md`
row 76: `make lint` has always scanned `find verticals tests`, this suite scanned only
`VERTICALS_DIR`/`WEB_SRC_DIR`, and the stricter of the two enforcers is not one `make test`
invokes — so `tests/perf/test_perf.py` sat at 799 lines, failing, for a whole session, while
`static` kept reporting green. See that test's own docstring for the rationale; recorded here
only so this module's own scope list stays complete.
"""

from __future__ import annotations

from pathlib import Path

from tests.harness.report import gate
from tests.static.conftest import VERTICALS_DIR, TESTS_DIR, WEB_SRC_DIR

LIMIT = 750


def _line_count(path: Path) -> int:
    with path.open(encoding="utf-8") as f:
        return sum(1 for _ in f)


def oversized(root: Path, patterns: tuple[str, ...]) -> list[tuple[Path, int]]:
    """Every file under `root` matching any of `patterns` (`"*.py"`, `"*.vue"`, ...) whose own
    line count exceeds `LIMIT` — the correct, per-file replacement for `ARCHITECTURE.md` §2's
    batched `awk` command. Discovered by `rglob`, never a hand-kept file list, so a module a
    sibling work package adds after this suite is written is in scope the next time it runs."""
    hits = []
    for pattern in patterns:
        for path in sorted(root.rglob(pattern)):
            n = _line_count(path)
            if n > LIMIT:
                hits.append((path, n))
    return hits


def test_s90a_no_python_module_over_750_lines():
    """AC-083, AC-181. Every `*.py` under `verticals/`, no exclusions (not even `__init__.py`) —
    the same set `find verticals -name '*.py'` names, just counted one file at a time."""
    hits = oversized(VERTICALS_DIR, ("*.py",))
    assert not hits, (
        f"{len(hits)} module(s) over {LIMIT} lines: "
        + ", ".join(f"{p.relative_to(VERTICALS_DIR.parent)}:{n}" for p, n in hits)
    )


def test_s90a_no_frontend_module_over_750_lines():
    """`docs/IMPLEMENTATION.md` WP-18's own scope extension: the identical budget applied to
    `web/src/`'s `.vue` and `.ts` files. Gates rather than vacuously passing if `web/src/` is
    ever absent — WP-12 owns creating it; this suite should not silently claim victory over a
    directory that was never generated."""
    if not WEB_SRC_DIR.is_dir():
        gate("web/src/ does not exist yet (WP-12 not landed)")
    hits = oversized(WEB_SRC_DIR, ("*.vue", "*.ts"))
    assert not hits, (
        f"{len(hits)} frontend module(s) over {LIMIT} lines: "
        + ", ".join(f"{p.relative_to(WEB_SRC_DIR.parent)}:{n}" for p, n in hits)
    )


def test_s90a_no_test_module_over_750_lines():
    """`docs/PENDING_DOC_FIXES.md` row 76's ruling: the wider scope — `verticals` + `tests` +
    `web/src` — is the real rule, and whichever check runs inside `make test` has to be the one
    that says so, because `make lint` already did and nobody runs `lint` in the loop. `tests/**`
    was inside the 750-line cap for one enforcer and outside it for the other, and that was not
    a theoretical gap: `tests/perf/test_perf.py` sat at 799 lines, `make lint` failing on it,
    for the whole of one session, while this suite kept reporting a green `static` PASS the
    entire time — a rule enforced only by a target nobody runs in the loop is not enforced. The
    rationale for widening rather than narrowing: a 799-line test file is exactly as hard for a
    person to hold in their head as a 799-line shipped module would be, `ARCHITECTURE.md` §2's
    own cap was never argued to be about deploy risk rather than plain readability, and the tree
    already satisfies this reading on its own — `test_perf.py` was split three ways instead of
    grandfathered (`tests/perf/test_perf_core_queries.py`, `tests/perf/test_perf_transport_import.py`,
    `tests/perf/judge.py`; commit 86053c6) — so this assertion costs the tree nothing real today,
    same as S-109's stricter `monkeypatch` reading cost nothing when it was adopted."""
    hits = oversized(TESTS_DIR, ("*.py",))
    assert not hits, (
        f"{len(hits)} test module(s) over {LIMIT} lines: "
        + ", ".join(f"{p.relative_to(TESTS_DIR.parent)}:{n}" for p, n in hits)
    )


def test_module_size_rule_catches_a_planted_751_line_file(scratch_dir):
    """The rule has to be provably able to fail, per this WP's own done-when clause. Plant a
    751-line file under `scratch_dir` (`tempfile.mkdtemp`, outside the repo entirely — never
    under `verticals/`, so no other suite or scanner ever sees it), run the exact scanner
    `test_s90a_no_python_module_over_750_lines` uses, and assert it is caught by name and by
    the exact line count. `scratch_dir`'s own fixture teardown deletes the file unconditionally.
    """
    victim = scratch_dir / "oversized.py"
    victim.write_text("x = 1\n" * (LIMIT + 1), encoding="utf-8")
    hits = oversized(scratch_dir, ("*.py",))
    assert hits == [(victim, LIMIT + 1)], f"expected exactly one {LIMIT + 1}-line hit, got {hits}"

    # And the negative: one line under the limit must not trip it — the boundary is ">", not ">=".
    victim.write_text("x = 1\n" * LIMIT, encoding="utf-8")
    assert oversized(scratch_dir, ("*.py",)) == [], f"{LIMIT} lines exactly must not be flagged"
