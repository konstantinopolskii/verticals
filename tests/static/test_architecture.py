"""S-108 — the architecture audit. `docs/E2E.md` §7b names it "stated as six greps that must
find nothing" in its own intro sentence, then lists **seven** numbered rows in its own table
(the IR-11 bounds row was added by a later correction — `ARCHITECTURE.md` §2's revision-log line
292 names it explicitly as one of the corrections layered on afterward — and the intro sentence
was never updated to match). Recorded in `docs/PENDING_DOC_FIXES.md` rather than silently
resolved: it is a one-word miscount, but "six" and "seven" are both load-bearing if a reader
counts rows against the sentence.

Every row below follows `tests/core/test_owner_scoping.py`'s own precedent and this suite's
`conftest.py`: AST for shape (imports, comparisons, attribute access), never bare text; a
module's own docstring is documentation, not code, and is excluded from every literal-content
scan for the same reason `core/board.py` and `core/search.py` may not be flagged for their own
(real, checked) prose about inboxes, retros and SQL verbs.

Row 7 (IR-11) splits into two test functions rather than one: `core/tree.py` and
`db/migrations/001_init.sql` are already shipped (WP-08, WP-03) and checked for real; `core/goals.py`
(WP-13) and `mcp/tools.py` (WP-19) are not built as of this writing — both directories hold
nothing but an empty `__init__.py`. Rather than fail on a file that is simply not due yet, or
silently skip the row and lose the signal forever, that half gates by name until the files exist,
then runs the same style of check for real, no code change required on this side when it does.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

from tests.harness.report import gate
from tests.static.conftest import (
    CORE_DIR,
    VERTICALS_DIR,
    MCP_DIR,
    SCALE_KEYS,
    has_int_constant,
    identifiers,
    non_docstring_string_constants,
    parse_py,
    python_files,
    raises_named,
)

VERTICAL_PY = CORE_DIR / "vertical.py"
INIT_SQL = VERTICALS_DIR / "db" / "migrations" / "001_init.sql"

# ---------------------------------------------------------------------------------------------
# Row 1 — exactly 7 descriptors, `menu_label('day') == 'Today'`.
# ---------------------------------------------------------------------------------------------


def test_s108a_seven_vertical_descriptors_and_today_label():
    from verticals.core import vertical  # local: this is the one test in the suite that imports

    assert len(vertical.VERTICALS) == 7, f"expected 7 descriptors, found {len(vertical.VERTICALS)}"
    assert vertical.menu_label("day") == "Today", "UI_REFERENCE §6: the day column reads 'Today'"


def test_architecture_row1_catches_a_planted_eighth_descriptor(scratch_dir):
    victim = scratch_dir / "vertical.py"
    victim.write_text("VERTICALS = ('day','week','month','quarter','year','decade','life','sprint')\n")
    tree = parse_py(victim)
    (assign,) = [n for n in ast.walk(tree) if isinstance(n, ast.Assign)]
    (count,) = [len(elt.elts) for elt in [assign.value] if isinstance(elt, ast.Tuple)]
    assert count == 8, "planted 8-descriptor tuple was not read back as 8"


# ---------------------------------------------------------------------------------------------
# Row 2 — zero comparisons against a vertical scale literal outside `core/vertical.py`.
# ---------------------------------------------------------------------------------------------


def _scale_strings(node: ast.AST) -> set[str]:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return {node.value} if node.value in SCALE_KEYS else set()
    if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
        found: set[str] = set()
        for elt in node.elts:
            found |= _scale_strings(elt)
        return found
    return set()


def scale_literal_comparisons(root: Path, *, exclude: frozenset[Path] = frozenset()) -> list[str]:
    hits = []
    for path in python_files(root, exclude=exclude):
        for node in ast.walk(parse_py(path)):
            if not isinstance(node, ast.Compare):
                continue
            if not all(isinstance(op, (ast.Eq, ast.NotEq, ast.In, ast.NotIn)) for op in node.ops):
                continue
            found = _scale_strings(node.left)
            for comparator in node.comparators:
                found |= _scale_strings(comparator)
            if found:
                hits.append(f"{path}:{node.lineno} compares against {sorted(found)}")
    return hits


def test_s108b_no_scale_literal_comparisons_outside_vertical_py():
    hits = scale_literal_comparisons(VERTICALS_DIR, exclude=frozenset({VERTICAL_PY}))
    assert not hits, "scale behaviour must live only in core/vertical.py:\n" + "\n".join(hits)


def test_architecture_row2_catches_a_planted_scale_branch(scratch_dir):
    victim = scratch_dir / "leaky.py"
    victim.write_text("def f(h):\n    if h == 'day':\n        return 1\n    return 0\n")
    hits = scale_literal_comparisons(scratch_dir)
    assert len(hits) == 1 and "day" in hits[0], f"expected one 'day' hit, got {hits}"


# ---------------------------------------------------------------------------------------------
# Rows 3 & 4 — zero retro-specific code, zero inbox-specific code path (one exemption: the real
# `goals_inbox` partial index name, AC-087's own stated carve-out).
# ---------------------------------------------------------------------------------------------


def _word_hits(root: Path, word: str, *, allow_tokens: frozenset[str] = frozenset()) -> list[str]:
    """Every real identifier or non-docstring string/f-string literal fragment under `root`
    containing `word` (case-insensitive), skipping any fragment that IS one of `allow_tokens`
    exactly (not merely containing it) — the narrow, named-token exemption `goals_inbox` needs
    rather than a blanket pass on anything nearby."""
    hits = []
    needle = word.lower()
    for path in python_files(root):
        tree = parse_py(path)
        for name, line in identifiers(tree):
            if needle in name.lower() and name not in allow_tokens:
                hits.append(f"{path}:{line} identifier {name!r}")
        for text, line in non_docstring_string_constants(tree):
            if needle in _masked(text, allow_tokens).lower():
                hits.append(f"{path}:{line} string {text!r}")
    return hits


def _masked(text: str, allow_tokens: frozenset[str]) -> str:
    """`text` with every occurrence of every `allow_tokens` member cut out — so a needle that
    exists only *inside* an allowed token (`"inbox"` inside `"goals_inbox"`) stops matching,
    while a needle sitting anywhere else on the same line still does."""
    for tok in allow_tokens:
        text = re.sub(re.escape(tok), "", text, flags=re.IGNORECASE)
    return text


_SQL_COMMENT_RE = re.compile(r"--.*$", re.MULTILINE)


def _sql_word_hits(root: Path, word: str, *, allow_tokens: frozenset[str] = frozenset()) -> list[str]:
    """Same idea, over `.sql` files: `--` comments stripped first (never part of any grammar,
    same treatment Python comments get for free from `ast.parse`), then a masked, case-insensitive
    substring search line by line."""
    hits = []
    needle = word.lower()
    for path in sorted(root.rglob("*.sql")):
        stripped = _SQL_COMMENT_RE.sub("", path.read_text(encoding="utf-8"))
        for lineno, line in enumerate(stripped.splitlines(), start=1):
            if needle in _masked(line, allow_tokens).lower():
                hits.append(f"{path}:{lineno}: {line.strip()}")
    return hits


def test_s108c_no_retro_specific_code():
    hits = _word_hits(VERTICALS_DIR, "retro") + _sql_word_hits(VERTICALS_DIR, "retro")
    assert not hits, "retro is a tagged goal, not a feature (ARCHITECTURE.md §4b):\n" + "\n".join(hits)


def test_s108d_no_inbox_specific_code_beyond_the_partial_index():
    allow = frozenset({"goals_inbox"})
    hits = _word_hits(VERTICALS_DIR, "inbox", allow_tokens=allow) + _sql_word_hits(
        VERTICALS_DIR, "inbox", allow_tokens=allow
    )
    assert not hits, "Maybe is vertical IS NULL plus one partial index, nothing else:\n" + "\n".join(hits)


def test_architecture_row3_catches_a_planted_retro_identifier(scratch_dir):
    victim = scratch_dir / "leaky.py"
    victim.write_text("def create_retro_summary():\n    return None\n")
    hits = _word_hits(scratch_dir, "retro")
    assert len(hits) == 1, f"expected one retro hit, got {hits}"


def test_architecture_row3_ignores_retro_in_a_docstring(scratch_dir):
    (scratch_dir / "clean.py").write_text('"""Explains what retro means. Never a real branch."""\n')
    assert _word_hits(scratch_dir, "retro") == []


def test_architecture_row4_catches_a_planted_inbox_table(scratch_dir):
    victim = scratch_dir / "leaky.py"
    victim.write_text("INBOX_TABLE = 'goal_inbox_items'\n")
    hits = _word_hits(scratch_dir, "inbox", allow_tokens=frozenset({"goals_inbox"}))
    assert hits, "expected the planted inbox table to be caught"


def test_architecture_row4_allows_the_real_partial_index_name(scratch_dir):
    (scratch_dir / "s.sql").write_text("CREATE INDEX goals_inbox ON goals (owner, position);\n")
    hits = _sql_word_hits(scratch_dir, "inbox", allow_tokens=frozenset({"goals_inbox"}))
    assert hits == [], f"the declared exception itself must not be flagged, got {hits}"


# ---------------------------------------------------------------------------------------------
# Row 5 — zero scheduler at module scope.
# ---------------------------------------------------------------------------------------------

SCHEDULER_IMPORT_ROOTS = {"apscheduler", "celery", "croniter", "sched"}
SCHEDULER_ATTRS = {("threading", "Timer"), ("asyncio", "create_task")}


def _module_scope_nodes(tree: ast.Module):
    """Every node that runs at import time: module-level statements and class bodies (a class's
    own body executes the moment the class is defined), recursively — but never inside a
    function, async function or lambda body, none of which run until something calls them.
    `ast.walk(top)` on its own does not give this: it recurses into *everything* under a
    top-level node, function bodies included, which is exactly the bug this replaced — it
    called a `threading.Timer` built only inside a never-invoked function "module scope"."""

    def _walk(node: ast.AST):
        yield node
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            return
        for child in ast.iter_child_nodes(node):
            yield from _walk(child)

    for top in tree.body:
        yield from _walk(top)


def module_scope_scheduler_hits(root: Path) -> list[str]:
    hits = []
    for path in python_files(root):
        tree = parse_py(path)
        for node in _module_scope_nodes(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.split(".")[0] in SCHEDULER_IMPORT_ROOTS:
                        hits.append(f"{path}:{node.lineno} imports {alias.name!r}")
            elif isinstance(node, ast.ImportFrom) and node.module:
                if node.module.split(".")[0] in SCHEDULER_IMPORT_ROOTS:
                    hits.append(f"{path}:{node.lineno} imports from {node.module!r}")
            elif isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
                if (node.value.id, node.attr) in SCHEDULER_ATTRS:
                    hits.append(f"{path}:{node.lineno} references {node.value.id}.{node.attr}")
    return hits


def test_s108e_no_scheduler_at_module_scope():
    hits = module_scope_scheduler_hits(VERTICALS_DIR)
    assert not hits, "nothing runs when nobody asked (S-30 is the runtime half):\n" + "\n".join(hits)


def test_architecture_row5_catches_a_planted_module_scope_timer(scratch_dir):
    victim = scratch_dir / "leaky.py"
    victim.write_text("import threading\n_t = threading.Timer(60, lambda: None)\n_t.start()\n")
    hits = module_scope_scheduler_hits(scratch_dir)
    assert len(hits) == 1 and "Timer" in hits[0], f"expected one Timer hit, got {hits}"


def test_architecture_row5_ignores_a_timer_built_inside_a_function(scratch_dir):
    victim = scratch_dir / "clean.py"
    victim.write_text(
        "import threading\n\ndef start_if_asked():\n    return threading.Timer(60, lambda: None)\n"
    )
    assert module_scope_scheduler_hits(scratch_dir) == [], "a Timer built only if called is not module scope"


# ---------------------------------------------------------------------------------------------
# Row 6 — nothing parses `body` for structure.
# ---------------------------------------------------------------------------------------------

CHECKBOX_PATTERN_TEXT = r"^\s*[-*]\s*\["


def body_parsing_hits(root: Path) -> list[str]:
    hits = []
    for path in python_files(root):
        tree = parse_py(path)
        touches_body = any(isinstance(n, ast.Attribute) and n.attr == "body" for n in ast.walk(tree))
        if not touches_body:
            continue
        if any(CHECKBOX_PATTERN_TEXT in text for text, _ in non_docstring_string_constants(tree)):
            hits.append(f"{path} both reads .body and holds the checkbox-line regex")
    return hits


def test_s108f_nothing_parses_body_for_structure():
    hits = body_parsing_hits(VERTICALS_DIR)
    assert not hits, "body is content, never structure (ARCHITECTURE.md §4, S-73):\n" + "\n".join(hits)


def test_architecture_row6_catches_a_planted_body_parser(scratch_dir):
    victim = scratch_dir / "leaky.py"
    victim.write_text(
        "import re\n\ndef extract(goal):\n"
        "    return re.findall(r'^\\s*[-*]\\s*\\[', goal.body, re.MULTILINE)\n"
    )
    hits = body_parsing_hits(scratch_dir)
    assert len(hits) == 1, f"expected one body-parsing hit, got {hits}"


def test_architecture_row6_ignores_body_read_without_the_checkbox_regex(scratch_dir):
    (scratch_dir / "clean.py").write_text("def render(goal):\n    return markdown(goal.body)\n")
    assert body_parsing_hits(scratch_dir) == []


# ---------------------------------------------------------------------------------------------
# Row 7 — IR-11 bounds. Split: schema + tree.py are shipped; goals.py + mcp/tools.py are not.
# ---------------------------------------------------------------------------------------------

DEPTH_CHECK_RE = re.compile(r"CONSTRAINT\s+depth_bounded\s+CHECK\s*\(\s*depth\s*<=\s*32\s*\)")
TAGS_CHECK_RE = re.compile(r"CONSTRAINT\s+tags_bounded\s+CHECK\s*\(\s*cardinality\(tags\)\s*<=\s*32\s*\)")


def test_s108g_ir11_bounds_in_schema_and_tree():
    sql_text = INIT_SQL.read_text(encoding="utf-8")
    assert DEPTH_CHECK_RE.search(sql_text), "001_init.sql must CHECK depth <= 32"
    assert TAGS_CHECK_RE.search(sql_text), "001_init.sql must CHECK cardinality(tags) <= 32"

    tree_py = parse_py(CORE_DIR / "tree.py")
    assert has_int_constant(tree_py, 32) and raises_named(tree_py, "ValidationError"), (
        "core/tree.py must raise ValidationError and bound depth at 32 (IR-11)"
    )


def test_s108g_ir11_bounds_in_goals_and_mcp():
    goals_py = CORE_DIR / "goals.py"
    tools_py = MCP_DIR / "tools.py"
    missing = [str(p.relative_to(VERTICALS_DIR.parent)) for p in (goals_py, tools_py) if not p.is_file()]
    if missing:
        gate(f"not built yet: {', '.join(missing)}")

    goals_tree = parse_py(goals_py)
    assert has_int_constant(goals_tree, 200) and raises_named(goals_tree, "ValidationError"), (
        "core/goals.py must raise ValidationError and bound node count at 200 (IR-11)"
    )
    assert "200" in tools_py.read_text(encoding="utf-8"), (
        "mcp/tools.py's create tool schema must state the 200-node maximum (IR-11)"
    )


def test_architecture_row7_catches_a_missing_depth_bound(scratch_dir):
    victim = scratch_dir / "001_init.sql"
    victim.write_text("CREATE TABLE goals (depth INTEGER NOT NULL DEFAULT 0);\n")
    assert not DEPTH_CHECK_RE.search(victim.read_text(encoding="utf-8")), "expected no match on an unbounded table"
