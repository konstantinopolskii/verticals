"""S-109 — the no-mock audit. `docs/E2E.md` §7b; AC-085, AC-182. "All tests are E2E, no mocks"
(this repo's `CLAUDE.md`, "architectural decision") only stays true if something keeps checking.

Two documents name two different token lists for the same rule — `E2E.md` S-109's own text bans
`unittest.mock, mock.patch, monkeypatch, MagicMock, pytest-mock, responses, respx, freezegun,
time-machine, sinon, jest.mock, vi.mock, msw, nock` unconditionally; `ACCEPTANCE.md` AC-085 bans
a *different*, overlapping set (adds `httpretty`, `fakeredis`, `testfixtures`; narrows
`monkeypatch` to "calls against `verticals.*`" rather than the word outright). Implemented here as
the union of both lists, with `monkeypatch` read the stricter (E2E) way — a blanket ban is a
strict superset of "only against verticals.*", so implementing the stronger rule can never pass
something the weaker one would have failed, only the reverse. Recorded in
`docs/PENDING_DOC_FIXES.md` as a real disagreement rather than picked silently. Verified against
today's tree first: zero existing `monkeypatch` usage anywhere under `tests/`, so the stricter
reading costs nothing real right now.

Python-side tokens are read as real `import`/`from ... import` statements and real identifier
usage (`MagicMock`, `monkeypatch` as a fixture parameter) — AST, never text, for the same reason
every other check in this suite is: this file's own module docstring, one paragraph up, contains
the literal substring `"unittest.mock"` as English prose, and a bare `grep` over `tests/` would
flag itself. JS-side tokens (`sinon`, `jest.mock`, `vi.mock`, `msw`, `nock`) have no Python source
to appear in — `tests/` holds nothing but `.py` — so they are checked only where `docs/E2E.md`
also asks for them: as package names in `package-lock.json`, at any depth, alongside the
Python-side names in whichever lockfile actually exists (see `test_dependencies.py`'s own note:
`uv.lock` is referenced by the docs but this project ships no Python lockfile at all — pip+venv,
pinned by `==` in `pyproject.toml` — so the Python half degrades to a `.venv` dist-info scan).
"""

from __future__ import annotations

import ast
from pathlib import Path

from tests.static.conftest import (
    REPO_ROOT,
    TESTS_DIR,
    identifiers,
    npm_package_names,
    parse_py,
    python_files,
    venv_dist_info_names,
)

PY_BANNED_IMPORTS = {
    "unittest.mock", "mock", "pytest_mock", "responses", "respx", "freezegun",
    "time_machine", "httpretty", "fakeredis", "testfixtures",
}
PY_BANNED_NAMES = {"MagicMock", "monkeypatch"}
LOCK_BANNED_PACKAGES = {
    "mock", "pytest-mock", "responses", "respx", "freezegun", "time-machine", "sinon",
    "jest", "jest-mock", "vitest", "msw", "nock", "httpretty", "fakeredis", "testfixtures",
}


def _import_roots(tree: ast.Module) -> set[str]:
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            roots.add(node.module)
    return roots


def mock_hits_in(root) -> list[str]:
    """Every banned import and every use of a banned bare name (`MagicMock`, `monkeypatch`)
    under `root`. A dotted import is checked whole (`"unittest.mock"`) and by its first segment
    (`"responses.registries"` -> `"responses"`), so a submodule import of a banned top-level
    package cannot dodge the rule by importing one level deeper."""
    hits = []
    for path in python_files(root):
        tree = parse_py(path)
        for mod in _import_roots(tree):
            head = mod.split(".", 1)[0]
            if mod in PY_BANNED_IMPORTS or head in PY_BANNED_IMPORTS:
                hits.append(f"{path} imports {mod!r}")
        for name, line in identifiers(tree):
            if name in PY_BANNED_NAMES:
                hits.append(f"{path}:{line} uses {name!r}")
    return hits


def lockfile_hits() -> list[str]:
    hits = []
    npm_lock = REPO_ROOT / "web" / "package-lock.json"
    if npm_lock.is_file():
        found = npm_package_names(npm_lock) & LOCK_BANNED_PACKAGES
        hits += [f"package-lock.json carries banned package {n!r}" for n in sorted(found)]
    found = venv_dist_info_names() & LOCK_BANNED_PACKAGES
    hits += [f".venv carries banned package {n!r} (uv.lock absent, see PENDING_DOC_FIXES.md)" for n in sorted(found)]
    return hits


def test_s109_no_mock_imports_or_calls_under_tests():
    hits = mock_hits_in(TESTS_DIR)
    assert not hits, "no test may replace a real component with a fake (AC-085):\n" + "\n".join(hits)


def test_s109_no_mock_package_in_either_lockfile():
    hits = lockfile_hits()
    assert not hits, "a transitive mock library must not arrive unnoticed:\n" + "\n".join(hits)


def test_s109_instrumentation_file_matches_the_tree():
    """AC-085's three named exceptions (`MutationObserver`, `HTMLMediaElement.prototype.play` via
    `page.addInitScript`, `page.clock.install`) live only in the `ui` suite, which M0 does not
    build (`tests/ui/` does not exist). If `tests/INSTRUMENTATION.md` is also absent, the
    invariant "the tree matches the declared list" holds trivially — both sides are empty — so
    this passes rather than gates; gating would wrongly suggest the file is owed now, when
    nothing under `tests/` today does any interception at all, declared or not."""
    instrumentation_md = TESTS_DIR / "INSTRUMENTATION.md"
    interception_tokens = ("MutationObserver", "addInitScript", "page.clock.install")
    # Excludes this file itself: the tokens above are real Python string constants (not inside
    # a docstring), so a whole-tree scan that did not exclude its own search-target definition
    # would flag itself on every run — the identical trap this suite spent five other files
    # avoiding, just self-inflicted instead of found in someone else's code.
    found_in_tree = [
        f"{p}: {tok}"
        for p in python_files(TESTS_DIR, exclude=frozenset({Path(__file__).resolve()}))
        for tok in interception_tokens
        if tok in p.read_text(encoding="utf-8")
    ]
    if not instrumentation_md.is_file():
        assert not found_in_tree, f"undeclared interception found, tests/INSTRUMENTATION.md is missing: {found_in_tree}"
        return
    declared = instrumentation_md.read_text(encoding="utf-8")
    for tok in interception_tokens:
        assert tok in declared, f"tests/INSTRUMENTATION.md must name {tok!r} (AC-085's 3-entry table)"


def test_no_mocks_rule_catches_a_planted_unittest_mock_import(scratch_dir):
    victim = scratch_dir / "leaky_test.py"
    victim.write_text("from unittest.mock import MagicMock\n\ndef test_thing():\n    m = MagicMock()\n")
    hits = mock_hits_in(scratch_dir)
    assert any("unittest.mock" in h for h in hits) and any("MagicMock" in h for h in hits), hits


def test_no_mocks_rule_ignores_a_docstring_mentioning_unittest_mock(scratch_dir):
    """Proof of the exact trap this file's own module docstring sits in: a file that only
    *talks about* `unittest.mock` in prose must not be flagged."""
    (scratch_dir / "clean_test.py").write_text('"""This suite never imports unittest.mock."""\n')
    assert mock_hits_in(scratch_dir) == []


def test_no_mocks_rule_catches_a_planted_monkeypatch_fixture(scratch_dir):
    victim = scratch_dir / "leaky_test.py"
    victim.write_text("def test_thing(monkeypatch):\n    monkeypatch.setattr('os.getcwd', lambda: '/x')\n")
    hits = mock_hits_in(scratch_dir)
    assert any("monkeypatch" in h for h in hits), hits
