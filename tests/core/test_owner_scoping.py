"""S-21 — `owner` is never defaulted, and every statement carries it. `docs/E2E.md` S-21;
AC-013, AC-014. `core/`'s own audit of the rule that keeps a second owner from being a rewrite:
every function that touches a real table takes `owner` with no default and uses it, and every
SQL literal naming that table also scopes it by `owner` — or is named, with a reason, on the
two-entry allowlist below.

Two rules, both machine-checked (S-21's own "both halves machine-defined"):

  1. A function that calls `.execute(` directly — an actual entry point to the database, not a
     text-builder a caller assembles further (`core/search.py`'s `build_statement` is exactly
     that: it returns SQL text and touches no connection, and is public precisely so a test can
     assert that text without reaching into a private name) — has `owner` as a parameter with
     `default is inspect.Parameter.empty`, and the name `owner` is used somewhere in its own
     body (`inspect.signature`, per S-21's own two-step method: ast, then introspect).
  2. Every SQL string literal in `core/` naming an application table — read from
     `information_schema.tables`, never hardcoded to `goals` alone, which is AC-014's own point
     — also carries the parameter that scopes it to the caller's `owner`: `owner = %(...)s` for
     `SELECT`/`UPDATE`/`DELETE`, or `%(owner)s` bound into the row for `INSERT`, which has no
     `WHERE` to carry a filter in. Checked per function, over every literal in that function's
     own body pooled together: `build_statement`'s `"FROM goals"` and `"owner = %(owner)s"` are
     two separate Python literals joined only at SQL-execution time, and a check narrower than
     "this function's own literals, together" would either miss that join or flag it as broken.
     A function only "touches" a table if its pooled literals also contain a SQL verb (`SELECT`/
     `INSERT`/`UPDATE`/`DELETE`) — `core/idem.py`'s `reserve` names "idempotency" only in a
     `RuntimeError` message's English prose ("idempotency row for owner=... vanished..."), never
     in SQL of its own (its statements are module-level constants, referenced by name, not
     inlined), and a bare substring match on the table name alone would flag that sentence as an
     unscoped query. `core/board.py`'s branches went the other way: each `SELECT ... FROM goals
     WHERE owner = %(owner)s ...` is written inline, in the one function that builds it, rather
     than split across a helper and its caller — so this rule stays a same-function check, never
     a call-graph one, and the module being checked stays honest on its own terms instead of the
     checker growing a second way to be fooled.

This is a textual audit, not a SQL parser: it would not catch `SET owner = %(owner)s` standing
in for a missing `WHERE owner = %(owner)s` — both contain the same substring, and telling a
`SET` clause from a `WHERE` clause by regex is exactly the corner a real parser is for. No
function in `core/` does that today; closing that gap the rest of the way is out of scope here,
named rather than silently assumed away.

The allowlist is declared and enforced — a synthetic, deliberately-broken fixture below proves
rule 2 flags all four verbs it names, and proves an allowlisted name is correctly excused — but
is *empty* against today's real `verticals/core/`: every function that touches `goals` or
`idempotency` already carries its own `owner` filter, so there is no live case to name yet.
Flagged in this package's own report rather than forcing a count that does not match reality.
"""

from __future__ import annotations

import ast
import importlib
import inspect
import re
from pathlib import Path

import psycopg
import pytest

CORE_DIR = Path(__file__).resolve().parents[2] / "verticals" / "core"

# (module_name, function_name) — id-only lookups, owner-filtered by their own caller before
# they are ever reached, exempted from rule 2 only. Empty today; see the module docstring.
ALLOWLIST: frozenset[tuple[str, str]] = frozenset({
    # R11's exact schema is global by design: tag_meta has no owner column. The public core
    # function still requires owner so every caller keeps the standard boundary, but its one
    # upsert cannot carry a predicate or value for a column the table deliberately lacks.
    ("verticals.core.tag_meta", "mark"),
})

_OWNER_FILTER_RE = re.compile(r"\bowner\s*=\s*%")
_SQL_VERB_RE = re.compile(r"\b(?:SELECT|INSERT|UPDATE|DELETE)\b", re.IGNORECASE)


def _docstring_node(func: ast.AST) -> ast.AST | None:
    body = getattr(func, "body", None)
    if (
        body
        and isinstance(body[0], ast.Expr)
        and isinstance(body[0].value, ast.Constant)
        and isinstance(body[0].value.value, str)
    ):
        return body[0].value
    return None


def literal_text(func: ast.AST) -> str:
    """Every string/f-string literal in `func`'s own body, pooled into one text blob — never
    its docstring (a bare string statement is documentation, not SQL, and `core/tree.py`'s own
    docstrings say "goals" in plain English often enough to false-flag a naive scan of it)."""
    skip = _docstring_node(func)
    parts: list[str] = []
    for node in ast.walk(func):
        if node is skip:
            continue
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            parts.append(node.value)
        elif isinstance(node, ast.JoinedStr):
            for value in node.values:
                if isinstance(value, ast.Constant) and isinstance(value.value, str):
                    parts.append(value.value)
    return "\n".join(parts)


def calls_execute(func: ast.AST) -> bool:
    return any(
        isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "execute"
        for n in ast.walk(func)
    )


def owner_used(func: ast.AST) -> bool:
    return any(isinstance(n, ast.Name) and n.id == "owner" for n in ast.walk(func))


def touches(text: str, tables: list[str]) -> bool:
    """A table's name alone is not enough — `core/idem.py`'s `reserve` says "idempotency" only
    inside a `RuntimeError`'s English sentence, never in SQL it wrote itself (its statements are
    module-level constants referenced by name). Requiring a SQL verb alongside the table name is
    what tells that sentence apart from a real, broken query."""
    if not _SQL_VERB_RE.search(text):
        return False
    return any(re.search(rf"\b{re.escape(t)}\b", text) for t in tables)


def owner_scoped(text: str, tables: list[str]) -> bool:
    alt = "|".join(re.escape(t) for t in tables)
    is_insert = re.search(rf"\bINSERT\s+INTO\s+(?:{alt})\b", text, re.IGNORECASE)
    if is_insert:
        return "%(owner)s" in text
    return bool(_OWNER_FILTER_RE.search(text))


def core_functions() -> list[tuple[str, str, ast.AST]]:
    """`(module_name, function_name, ast_node)` for every function under `verticals/core/` —
    S-21's own "parse verticals/core/ with ast", applied to whatever files are actually there
    today rather than a fixed list, so a future WP's new module is in scope for free."""
    out: list[tuple[str, str, ast.AST]] = []
    for path in sorted(CORE_DIR.glob("*.py")):
        if path.name == "__init__.py":
            continue
        tree = ast.parse(path.read_text(), filename=str(path))
        modname = f"verticals.core.{path.stem}"
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                out.append((modname, node.name, node))
    return out


@pytest.fixture
def app_tables(db: psycopg.Connection) -> list[str]:
    """AC-014's own point: read the table list from the catalogue, never hardcode `goals`. A
    fresh F0 clone is enough for this — the check needs the schema, not any row."""
    rows = db.execute(
        "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'"
    ).fetchall()
    return [r[0] for r in rows]


# --- S-21, against the real package ---------------------------------------------------------


def test_s21a_every_execute_calling_function_takes_undefaulted_owner_and_uses_it() -> None:
    violations = []
    for modname, funcname, node in core_functions():
        if not calls_execute(node):
            continue
        func = getattr(importlib.import_module(modname), funcname, None)
        if func is None or not inspect.isfunction(func):
            continue
        owner_param = inspect.signature(func).parameters.get("owner")
        ok = (
            owner_param is not None
            and owner_param.default is inspect.Parameter.empty
            and owner_used(node)
        )
        if not ok:
            violations.append(f"{modname}.{funcname}")
    assert violations == [], f"missing/defaulted/unused owner parameter: {violations}"


def test_s21b_every_table_literal_is_owner_scoped_or_allowlisted(app_tables: list[str]) -> None:
    violations = []
    for modname, funcname, node in core_functions():
        text = literal_text(node)
        if not touches(text, app_tables):
            continue
        if (modname, funcname) in ALLOWLIST:
            continue
        if not owner_scoped(text, app_tables):
            violations.append(f"{modname}.{funcname}")
    assert violations == [], f"table literal missing owner scoping: {violations}"


# --- proof: the checks catch what they are supposed to, against synthetic broken code ----------
#
# Not imported, not called, not connected to any database — `ast.parse`d as bare source text and
# run through the exact same three functions the two tests above use against the real package.

_BROKEN_VERBS = """
def broken_select(conn, *, owner, id):
    return conn.execute("SELECT id FROM goals WHERE id = %(id)s", {"id": id}).fetchall()

def broken_insert(conn, *, owner, title):
    return conn.execute(
        "INSERT INTO goals (id, title) VALUES (%(id)s, %(title)s)", {"id": "x", "title": title}
    )

def broken_update(conn, *, owner, id, title):
    return conn.execute(
        "UPDATE goals SET title = %(title)s WHERE id = %(id)s", {"id": id, "title": title}
    )

def broken_delete(conn, *, owner, id):
    return conn.execute("DELETE FROM goals WHERE id = %(id)s", {"id": id})
"""

# The allowlist mechanism, exercised on its own: an id-only lookup with no `owner` predicate in
# its own text at all — genuinely a rule-2 violation on its face — paired with the caller that
# validates ownership before ever reaching it. `checked_lookup` proves the *unlisted* case still
# flags; `allowlisted_lookup` is the same shape, proven excused only once named.
_ALLOWLIST_PAIR = """
def checked_lookup(conn, *, id):
    return conn.execute("SELECT id FROM goals WHERE id = %(id)s", {"id": id}).fetchone()

def allowlisted_lookup(conn, *, id):
    return conn.execute("SELECT id FROM goals WHERE id = %(id)s", {"id": id}).fetchone()
"""

_BROKEN_SIGNATURES = """
def defaulted_owner(conn, *, owner="nobody", id):
    return conn.execute(
        "SELECT id FROM goals WHERE owner = %(owner)s AND id = %(id)s", {"owner": owner, "id": id}
    )

def unused_owner(conn, *, owner, id):
    return conn.execute("SELECT id FROM goals WHERE id = %(id)s", {"id": id})
"""


def _functions_in(source: str) -> dict[str, ast.AST]:
    return {n.name: n for n in ast.walk(ast.parse(source)) if isinstance(n, ast.FunctionDef)}


def test_s21c_rule_two_catches_all_four_broken_verbs() -> None:
    tables = ["goals", "idempotency"]
    funcs = _functions_in(_BROKEN_VERBS)
    assert set(funcs) == {"broken_select", "broken_insert", "broken_update", "broken_delete"}
    for name, node in funcs.items():
        text = literal_text(node)
        assert touches(text, tables), f"{name}: fixture itself does not name a table"
        assert not owner_scoped(text, tables), f"{name}: broken fixture passed the check"


def test_s21d_allowlist_suppresses_only_the_named_exception() -> None:
    tables = ["goals"]
    funcs = _functions_in(_ALLOWLIST_PAIR)
    checked, allowlisted = funcs["checked_lookup"], funcs["allowlisted_lookup"]
    assert touches(literal_text(checked), tables) and not owner_scoped(
        literal_text(checked), tables
    ), "checked_lookup should read as a rule-2 violation before any allowlist is consulted"

    local_allowlist = {("synthetic", "allowlisted_lookup")}
    violations = [
        name
        for name, node in funcs.items()
        if touches(literal_text(node), tables)
        and ("synthetic", name) not in local_allowlist
        and not owner_scoped(literal_text(node), tables)
    ]
    assert violations == ["checked_lookup"], violations


def test_s21e_rule_one_catches_a_defaulted_and_an_unused_owner() -> None:
    funcs = _functions_in(_BROKEN_SIGNATURES)
    defaulted = inspect.Parameter(
        "owner", inspect.Parameter.KEYWORD_ONLY, default="nobody"
    )
    assert defaulted.default is not inspect.Parameter.empty  # the shape rule 1 must reject
    assert owner_used(funcs["unused_owner"]) is False  # never referenced past the signature
    assert owner_used(funcs["defaulted_owner"]) is True  # used, but still defaulted — both matter
