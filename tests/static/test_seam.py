"""S-90 (part 2 of 2) — the transport/logic seam. `docs/E2E.md` S-90: "`core/` contains zero
occurrences of `fastapi`, `starlette`, `mcp` or `pydantic` imports, and `api/` + `mcp/` contain
zero occurrences of `SELECT `, `INSERT `, `UPDATE ` or `DELETE ` outside of comments." AC-084.

Two different node classes for two different halves, on purpose:

  * The import half reads `ast.Import`/`ast.ImportFrom` nodes — an import statement is
    unambiguous, so a bare substring scan would already be safe here. AST is used anyway for
    symmetry with the rest of this suite and because it is the only way to get "at module scope,
    ignoring what a string happens to say" for free.
  * The SQL-verb half reads string/f-string literal *content*, deliberately skipping every
    module's, class's and function's own docstring (`conftest.non_docstring_string_constants`).
    `docs/E2E.md`'s own words are "outside of comments" — comments are never in the AST at all,
    so that half is free — but a bare reading of "outside of comments" would still let a
    docstring explaining the seam itself trip this check on its own prose (a route module
    documenting "this handler never runs an UPDATE directly, core/ does" is not a violation, it
    is a true sentence about the rule). `tests/core/test_owner_scoping.py`'s own lesson — English
    prose containing a banned word is not the same event as code containing it — applies here
    identically to how it applies to S-108's retro/inbox checks two files over. Treating a
    docstring as documentation rather than code is the one-line fix, applied consistently with
    every other check in this suite rather than invented fresh for this file.
"""

from __future__ import annotations

import ast

from tests.static.conftest import API_DIR, CORE_DIR, MCP_DIR, non_docstring_string_constants, parse_py, python_files

BANNED_CORE_IMPORTS = ("fastapi", "starlette", "mcp", "pydantic")
BANNED_SQL_VERBS = ("SELECT ", "INSERT ", "UPDATE ", "DELETE ")


def _import_roots(tree: ast.Module) -> list[tuple[str, int]]:
    """Every dotted module path a real `import`/`from ... import ...` statement in `tree`
    names, paired with its line — `import fastapi.routing as r` and
    `from starlette.responses import JSONResponse` both surface their root package name."""
    out: list[tuple[str, int]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                out.append((alias.name, node.lineno))
        elif isinstance(node, ast.ImportFrom) and node.module:
            out.append((node.module, node.lineno))
    return out


def transport_imports_in(root) -> list[str]:
    """`(file, line, module)` strings for every import under `root` whose root package is one of
    `BANNED_CORE_IMPORTS` — a dotted import counts by its first segment (`fastapi.routing` is
    still `fastapi`)."""
    hits: list[str] = []
    for path in python_files(root):
        for module, line in _import_roots(parse_py(path)):
            head = module.split(".", 1)[0]
            if head in BANNED_CORE_IMPORTS:
                hits.append(f"{path}:{line} imports {module!r}")
    return hits


def sql_verbs_in(root) -> list[str]:
    """`(file, line, verb)` strings for every non-docstring string/f-string literal under `root`
    containing one of `BANNED_SQL_VERBS`. Comments are already absent (never in the AST);
    docstrings are excluded on purpose — see the module docstring above."""
    hits: list[str] = []
    for path in python_files(root):
        for text, line in non_docstring_string_constants(parse_py(path)):
            for verb in BANNED_SQL_VERBS:
                if verb in text:
                    hits.append(f"{path}:{line} contains {verb!r}")
    return hits


def test_s90b_core_has_no_transport_imports():
    hits = transport_imports_in(CORE_DIR)
    assert not hits, "core/ must never import a transport library:\n" + "\n".join(hits)


def test_s90b_api_and_mcp_have_no_raw_sql_verbs():
    hits = sql_verbs_in(API_DIR) + sql_verbs_in(MCP_DIR)
    assert not hits, "api/ and mcp/ must never hold a raw SQL verb:\n" + "\n".join(hits)


def test_seam_rule_catches_a_planted_transport_import(scratch_dir):
    """Proof, not assertion: a `core/`-shaped file that imports FastAPI must be caught."""
    victim = scratch_dir / "leaky_core.py"
    victim.write_text("import fastapi\n\ndef handler():\n    return fastapi.Response()\n")
    hits = transport_imports_in(scratch_dir)
    assert len(hits) == 1 and "fastapi" in hits[0], f"expected one fastapi hit, got {hits}"


def test_seam_rule_ignores_a_docstring_mentioning_a_transport_name(scratch_dir):
    """The negative half of the same proof: a module that only *talks about* FastAPI in its own
    docstring — never imports it — must not be flagged. Mirrors the real, already-shipped
    `core/board.py`/`core/search.py` docstrings, which discuss transports and SQL verbs in prose
    without ever importing or executing either."""
    clean = scratch_dir / "clean_core.py"
    clean.write_text('"""This module never imports fastapi, starlette, mcp or pydantic."""\n')
    assert transport_imports_in(scratch_dir) == []


def test_seam_rule_catches_a_planted_raw_select(scratch_dir):
    """Proof for the SQL-verb half: a real, executed string literal containing `SELECT ` in an
    `api/`-shaped file must be caught."""
    victim = scratch_dir / "leaky_route.py"
    victim.write_text('def handler(conn):\n    return conn.execute("SELECT * FROM goals")\n')
    hits = sql_verbs_in(scratch_dir)
    assert len(hits) == 1 and "SELECT " in hits[0], f"expected one SELECT hit, got {hits}"


def test_seam_rule_ignores_a_docstring_mentioning_select(scratch_dir):
    """The negative half: a module whose own docstring explains that it never runs `SELECT `
    must not be flagged for saying so."""
    clean = scratch_dir / "clean_route.py"
    clean.write_text('"""This handler never runs a SELECT directly; core/board.py does."""\n')
    assert sql_verbs_in(scratch_dir) == []
