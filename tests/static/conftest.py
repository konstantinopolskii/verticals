"""Shared constants and helpers for suite `static` (S-90, S-108, S-109, S-110) —
`docs/IMPLEMENTATION.md` WP-18 card. No database, no server: every rule file in this directory
reads the working tree, both lockfiles, and the built frontend bundle, as files.

**Every scanner below reads the AST, never raw text, for anything that claims "this identifier
/ this comparison" exists.** `tests/core/test_owner_scoping.py` (S-21, WP-09) already paid for
this lesson once: a bare substring match on the table name `idempotency` flagged
`core/idem.py`'s own `RuntimeError` message, because the word appears there as English prose,
never as SQL. This suite's own words hit the identical trap against the *real, already-shipped*
tree, not a hypothetical one — checked empirically while writing this file:

  * `core/board.py` names the real partial index `goals_inbox` twice, in comments.
  * `core/search.py`'s and `core/board.py`'s own docstrings use "inbox" and "retro" in plain
    English (`"...what board and inbox are for..."`, `"...a caller's ' retro ' into a match..."`).
  * `models.py`'s `Column` docstring says "the Maybe inbox".

None of that is a violation of AC-087 ("no maybe/inbox-specific table, route, tool or branch").
A checker that flagged it would be wrong, not strict. AST-based scanning sidesteps the whole
class for free: comments are never part of the AST, and `skip_docstring` below drops the one
remaining case (a module/class/function's own leading string-statement) using the exact node
identification `test_owner_scoping.py` already uses, so the two files can never quietly diverge
on what counts as "documentation" versus "code".
"""

from __future__ import annotations

import ast
import shutil
import tempfile
from collections.abc import Iterator
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
VERTICALS_DIR = REPO_ROOT / "verticals"
CORE_DIR = VERTICALS_DIR / "core"
API_DIR = VERTICALS_DIR / "api"
MCP_DIR = VERTICALS_DIR / "mcp"
WEB_DIR = REPO_ROOT / "web"
WEB_SRC_DIR = WEB_DIR / "src"
TESTS_DIR = REPO_ROOT / "tests"

# The seven scale keys, spelled out rather than imported from `verticals.core.vertical` — this
# whole suite's job is to audit that module too (S-108 row a), so it must not trust the thing
# it is grading for its own input list. Byte-for-byte `ARCHITECTURE.md` §3's enum declaration.
SCALE_KEYS: tuple[str, ...] = ("day", "week", "month", "quarter", "year", "decade", "life")


def skip_docstring(node: ast.AST) -> ast.AST | None:
    """The first statement of `node`'s body, if it is a bare string constant — a module,
    class or function's own docstring. Identical in shape to
    `tests/core/test_owner_scoping.py`'s `_docstring_node`, duplicated rather than imported:
    that module lives under `tests/core/`, which is a different suite with a different
    dependency direction (`static` must never import from a suite that needs Postgres to
    collect), and a nine-line function is cheaper to keep in sync by inspection than to add a
    cross-suite import for."""
    body = getattr(node, "body", None)
    if (
        body
        and isinstance(body[0], ast.Expr)
        and isinstance(body[0].value, ast.Constant)
        and isinstance(body[0].value.value, str)
    ):
        return body[0].value
    return None


def parse_py(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def python_files(root: Path, *, exclude: frozenset[Path] = frozenset()) -> list[Path]:
    """Every `*.py` under `root`, sorted — discovered, never hand-listed, so a sibling WP's new
    module is in scope for free the next time this suite runs (house ruling: prefer rules that
    read the tree at runtime over anything that hardcodes a file list)."""
    return sorted(p for p in root.rglob("*.py") if p not in exclude and p.name != "__init__.py")


def non_docstring_string_constants(tree: ast.AST) -> list[tuple[str, int]]:
    """Every string / f-string literal constant piece in `tree`, *excluding* every module's,
    class's and function's own docstring — paired with its source line number so a failure can
    point at one. Comments are already gone by construction (`ast.parse` never sees them)."""
    skip_nodes: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            doc = skip_docstring(node)
            if doc is not None:
                skip_nodes.add(id(doc))
    out: list[tuple[str, int]] = []
    for node in ast.walk(tree):
        if id(node) in skip_nodes:
            continue
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            out.append((node.value, node.lineno))
        elif isinstance(node, ast.JoinedStr):
            for value in node.values:
                if isinstance(value, ast.Constant) and isinstance(value.value, str):
                    out.append((value.value, node.lineno))
    return out


def identifiers(tree: ast.AST) -> list[tuple[str, int]]:
    """Every real Python identifier `tree` defines or references — function/class names,
    parameter names, and loaded/stored names — paired with a line number. Deliberately not
    string contents: `AC-087`'s own phrasing is "grep `verticals/` for retro- and inbox-specific
    **identifiers**", and an identifier is a name in the language's own sense, not a substring
    of unrelated prose sitting inside a string."""
    out: list[tuple[str, int]] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            out.append((node.name, node.lineno))
        elif isinstance(node, ast.Name):
            out.append((node.id, node.lineno))
        elif isinstance(node, ast.Attribute):
            out.append((node.attr, node.lineno))
        elif isinstance(node, ast.arg):
            out.append((node.arg, node.lineno))
    return out


def npm_package_names(lock_path: Path) -> set[str]:
    """Every distinct package name `package-lock.json`'s own `"packages"` map holds, at any
    nesting depth — used by both `test_no_mocks.py` (banned test-double libraries) and
    `test_dependencies.py` (ORM/analytics/allowlist). Keys look like `"node_modules/foo"` or,
    nested, `"node_modules/foo/node_modules/bar"`; splitting on the *last* `node_modules/`
    isolates the leaf package name and leaves a scoped name (`"@babel/parser"`) intact, since
    the slash inside a scope is not a second `node_modules/` segment."""
    import json

    data = json.loads(lock_path.read_text(encoding="utf-8"))
    return {key.rsplit("node_modules/", 1)[-1] for key in data.get("packages", {}) if key}


def venv_dist_info_names() -> set[str]:
    """Every installed distribution's project name, read from `.venv/lib/python*/site-packages/
    *.dist-info`, normalized (lowercased, underscores to hyphens — PEP 503) so it compares
    directly against a PyPI-style name like `"time-machine"`. Stands in for a Python lockfile:
    `docs/E2E.md` refers to `uv.lock` throughout, but this project installs via plain pip into a
    venv and pins exact versions with `==` in `pyproject.toml` instead — there is no
    `uv.lock` anywhere in the tree (see `docs/PENDING_DOC_FIXES.md`). The installed venv is a
    real, currently-populated proxy for "what actually landed, transitively included"; the
    always-reliable half of both S-109 and S-110 is the direct-dependency scan of
    `pyproject.toml` itself, which needs no proxy at all."""
    site_packages = next((REPO_ROOT / ".venv" / "lib").glob("python*/site-packages"), None)
    if site_packages is None or not site_packages.is_dir():
        return set()
    return {
        p.name.split("-")[0].replace("_", "-").lower() for p in site_packages.glob("*.dist-info")
    }


def raises_named(tree: ast.AST, name: str) -> bool:
    """True if `tree` contains a `raise X(...)` or `raise mod.X(...)` whose callee's own name is
    `name` — `raise ValidationError(...)` and `raise errors.ValidationError(...)` both match,
    a bare re-`raise` or a different exception class does not."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Raise) and isinstance(node.exc, ast.Call):
            func = node.exc.func
            if isinstance(func, ast.Name) and func.id == name:
                return True
            if isinstance(func, ast.Attribute) and func.attr == name:
                return True
    return False


def has_int_constant(tree: ast.AST, value: int) -> bool:
    """True if the literal integer `value` appears anywhere in `tree` as a bare constant — used
    to check a bound is actually written into the code, not just documented about."""
    return any(isinstance(n, ast.Constant) and n.value == value for n in ast.walk(tree))


@pytest.fixture
def scratch_dir() -> Iterator[Path]:
    """A throwaway directory this suite alone controls — `docs/IMPLEMENTATION.md` WP-18's own
    "copy the tree to a scratch path, plant one violation, prove it, delete the copy". Built
    with `tempfile.mkdtemp`, which lands outside the repository entirely (the OS temp
    directory), never under `tests/`, `verticals/` or `web/`: a planted `unittest.mock` import
    or a fake `import fastapi` must never sit somewhere `test_no_mocks.py`'s or this suite's
    own *real*-tree scans, or `tests/harness/runner.py`'s suite discovery, could trip over by
    accident. Each rule's negative-case test builds only the minimal slice of tree shape the
    one check under test needs (one file, sometimes two) rather than a full copy of `verticals/`
    — the checkers below all take a root directory as a parameter, so a minimal fixture
    exercises the identical code path a full copy would, for zero added cost or risk.
    Removed on teardown even if the test fails."""
    path = Path(tempfile.mkdtemp(prefix="verticals-static-scratch-"))
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)
