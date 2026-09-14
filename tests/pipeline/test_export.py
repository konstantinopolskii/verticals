"""S-87 — `tools/export_markdown.py` against real Postgres and a real subprocess. No mocks: the
CLI tool is invoked exactly as AC-143 states it (`python tools/export_markdown.py --owner t1`,
`sys.executable` standing in for `python`), reading a real F2 clone through a real
`VERTICALS_DATABASE_URL`.

`docs/E2E.md` S-87's own text: "Byte equality across a reload is the assertion that matters:
determinism has to come from a total order in the SQL, not from the physical row order a reload
happens to reproduce." Reversing F2's *insertion* order is not a bare reversal of all 49 tuples,
though — `tests/fixtures/f2_synth.sql`'s own header says why: "Foreign keys are not deferred, so
G1's chain is listed parent-before-child ... every other row is a root ... and order does not
matter for it." A naive full reversal would put G1's children ahead of their own parents inside
one `INSERT` and the load would fail outright, proving nothing. `_reversed_insert_sql` below
reverses what is actually free to reverse (the 40 independent root rows) and relocates the G1
block, internally untouched, from the front of the file to the back — a different physical row
order on both counts, and one that still loads.

Three separate concerns, three test functions, one scenario id (`tests/harness/report.py`'s own
`test_s87[a-z]?_...` convention for "several functions, one catalogue scenario"):
  * S-87a — determinism and completeness across three runs, one of them a reversed reload.
  * S-87b — zero Python-level sockets other than the one Postgres connection (AC-143's
    `strace`/`dtrace`-free check).
  * S-87c — the escaping round-trip: a forged id inside a title must not survive a parse of the
    rendered file (the same grammar `tests/core/test_outline_grammar.py` attacks directly).
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path

import psycopg
import pytest

from tests.conftest import fresh_clone

REPO_ROOT = Path(__file__).resolve().parents[2]
F2_SQL = REPO_ROOT / "tests" / "fixtures" / "f2_synth.sql"
EXPORT_TOOL = REPO_ROOT / "tools" / "export_markdown.py"

_TIMEOUT = 30.0

# The G1 ladder (docs/E2E.md §2's census: "G1 ladder | 9") — the one chain with a real
# parent-before-child dependency inside f2_synth.sql's single INSERT.
_G1_CHAIN_IDS = frozenset(
    {
        "SYNLIF01", "SYNDEC01", "SYNYRR01", "SYNQ1R01", "SYNQ2R01", "SYNDAY01",
        "SYNSUB01", "SYNSUB02", "SYNSUB03",
    }
)

# An id is 8 base62 characters everywhere this codebase mints one (ARCHITECTURE.md §5); F2's own
# ids additionally all start "SYN", which the two non-escaping assertions below rely on to stay
# simple. Escape-aware parsing (S-87c) cannot use this — a forged id could claim any 8 characters
# — so it uses the general form instead.
_F2_ID_RE = re.compile(r"\[(SYN[A-Za-z0-9]{5})\]")


def _dsn_for(dbname: str) -> str:
    # Duplicated from tests/conftest.py's own (underscore-private) _env_dsn rather than
    # imported — tests/pipeline/test_schema_parity.py's _admin_dsn already sets this precedent
    # for the suite: three lines, not a cross-module reach into another file's private helper.
    host = os.environ.get("PGHOST", "127.0.0.1")
    port = os.environ.get("PGPORT", "55432")
    user = os.environ.get("PGUSER", "verticals")
    password = os.environ.get("PGPASSWORD", "verticals")
    return f"postgresql://{user}:{password}@{host}:{port}/{dbname}"


def _reversed_insert_sql(text: str) -> str:
    """See module docstring. Splits F2's one `INSERT`'s 49 value-tuples into the G1 block (kept
    in its own original, dependency-valid order) and the 40 independent rows (reversed), then
    puts the reversed 40 first and the untouched G1 block last — the opposite physical position
    from the original file, without ever placing a child tuple before its own parent's."""
    lines = text.splitlines()
    header_end = next(i for i, ln in enumerate(lines) if ln.strip() == "VALUES") + 1
    header = lines[:header_end]

    row_re = re.compile(r"^  \((.*)\)[,;]\s*$")
    g1_rows: list[str] = []
    other_rows: list[str] = []
    for ln in lines[header_end:]:
        m = row_re.match(ln)
        if not m:
            continue  # a comment or blank line inside the VALUES block
        row_id = ln.split("'", 2)[1]  # the first quoted literal on any data line is always `id`
        (g1_rows if row_id in _G1_CHAIN_IDS else other_rows).append(f"  ({m.group(1)})")

    assert len(g1_rows) == 9 and len(other_rows) == 40, (
        f"f2_synth.sql's shape changed (g1={len(g1_rows)}, other={len(other_rows)}) — this "
        f"helper's assumption about the file no longer holds and must be revisited"
    )

    ordered = list(reversed(other_rows)) + g1_rows
    return "\n".join(header) + "\n" + ",\n".join(ordered) + ";\n"


def _run_export(dsn: str, owner: str = "t1") -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    env["VERTICALS_DATABASE_URL"] = dsn
    env.pop("VERTICALS_TOKEN", None)  # AC-143: no token, even if the ambient shell happens to set one
    return subprocess.run(
        [sys.executable, str(EXPORT_TOOL), "--owner", owner],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=_TIMEOUT,
        stdin=subprocess.DEVNULL,  # AC-143: no login prompt — a tool that tried to read one
        # would hit EOF here rather than hang, so a passing run is proof none was attempted.
    )


@pytest.fixture
def f2_dsn(db_dsn: str, db: psycopg.Connection) -> str:
    """F2 loaded onto a fresh clone, DSN form — a subprocess needs the string, not the harness's
    own open connection. Same idiom as tests/core/test_board.py's `f2` fixture."""
    db.execute(F2_SQL.read_text())
    db.execute("ANALYZE goals")
    return db_dsn


def test_s87a_export_deterministic_and_complete(f2_dsn: str) -> None:
    a = _run_export(f2_dsn)
    b = _run_export(f2_dsn)
    assert a.returncode == 0, a.stderr
    assert b.returncode == 0, b.stderr

    with fresh_clone("f0") as reversed_name:
        reversed_dsn = _dsn_for(reversed_name)
        with psycopg.connect(reversed_dsn, autocommit=True) as conn:
            conn.execute(_reversed_insert_sql(F2_SQL.read_text()))
            conn.execute("ANALYZE goals")
        c = _run_export(reversed_dsn)

    assert c.returncode == 0, c.stderr
    assert a.stdout == b.stdout, "two runs against the same clone must be byte-identical"
    assert a.stdout == c.stdout, (
        "a reversed physical reload changed the export's bytes — the order came from row "
        "order, not from a total ORDER BY"
    )

    ids = _F2_ID_RE.findall(a.stdout)
    counts = Counter(ids)
    assert len(counts) == 46, f"expected 46 distinct t1 ids, found {len(counts)}: {sorted(counts)}"
    assert set(counts.values()) == {1}, f"some id did not appear exactly once: {counts}"
    assert "SYNOTH01" not in a.stdout and "SYNOTH02" not in a.stdout and "SYNOTH03" not in a.stdout, (
        "owner t2's ids must never appear in owner t1's export"
    )

    heading_lines = [ln for ln in a.stdout.splitlines() if ln.startswith("#")]
    assert heading_lines, "expected at least one root heading"
    for ln in heading_lines:
        level = len(ln) - len(ln.lstrip("#"))
        assert level == 1, f"grammar rule 1 permits only a level-1 heading, found {ln!r}"


def test_s87b_export_opens_zero_sockets_other_than_postgres(f2_dsn: str) -> None:
    """AC-143's `strace`/`dtrace`-free check, run in-process instead: this repo's dependency
    stack opens the Postgres connection through psycopg[binary]'s compiled libpq, which never
    calls back into Python's own `socket` module (verified live against this cluster: a
    monkeypatched `socket.socket.__init__` sees zero constructions for a real, successful
    `psycopg.connect(...).execute(...)`). So a correct, Postgres-only implementation measures as
    *zero* Python-level socket constructions, and the same probe would catch a stray `requests`/
    `httpx`/`urllib` call, which all go through this exact constructor. The probe runs the tool
    exactly as `main()` would from the command line (`runpy.run_path(..., run_name="__main__")`
    with `sys.argv` set), not a hand-written substitute for it."""
    probe = (
        "import runpy, socket, sys\n"
        "calls = []\n"
        "_orig_init = socket.socket.__init__\n"
        "def _tracking_init(self, *a, **kw):\n"
        "    calls.append(1)\n"
        "    _orig_init(self, *a, **kw)\n"
        "socket.socket.__init__ = _tracking_init\n"
        "sys.argv = ['export_markdown.py', '--owner', 't1']\n"
        "code = 0\n"
        "try:\n"
        f"    runpy.run_path({str(EXPORT_TOOL)!r}, run_name='__main__')\n"
        "except SystemExit as exc:\n"
        "    code = exc.code or 0\n"
        "sys.stderr.write('SOCKET_PROBE_COUNT=' + str(len(calls)) + chr(10))\n"
        "raise SystemExit(code)\n"
    )
    env = dict(os.environ)
    env["VERTICALS_DATABASE_URL"] = f2_dsn
    env.pop("VERTICALS_TOKEN", None)
    result = subprocess.run(
        [sys.executable, "-c", probe],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=_TIMEOUT,
        stdin=subprocess.DEVNULL,
    )
    assert result.returncode == 0, result.stderr
    m = re.search(r"SOCKET_PROBE_COUNT=(\d+)", result.stderr)
    assert m is not None, f"probe never printed its marker; stderr was: {result.stderr!r}"
    assert int(m.group(1)) == 0, (
        f"export opened {m.group(1)} Python-level socket(s) beyond the Postgres connection: "
        f"{result.stderr}"
    )
    assert result.stdout, "the probe's instrumentation must not have suppressed the real export"


def _parse_ids_unescaped(text: str) -> list[str]:
    """The "one small parser" `docs/E2E.md` S-87/S-131 both describe — reads an `outline`
    document's own grammar (module docstring, `verticals/core/markdown.py`), not a general
    markdown parser. An id is a `[...]` not immediately preceded by a backslash; a title's own
    literal `[`/`]` always is, because the renderer escapes exactly those two characters and
    nothing else can put an unescaped `[` next to 8 id-shaped characters and a `]`."""
    return re.findall(r"(?<!\\)\[([0-9A-Za-z]{8})\]", text)


def _has_unescaped_chip(text_line: str) -> bool:
    return re.search(r"(?<!\\)·[a-z]+ [^·]+(?<!\\)·", text_line) is not None


def test_s87c_export_escapes_a_forged_id_so_reparse_is_a_fixed_point(
    f2_dsn: str, db: psycopg.Connection
) -> None:
    hostile_title = "Ship it [SYNDAY01] ·day 2026-08-08·"
    db.execute(
        "INSERT INTO goals"
        " (id, owner, parent_id, path, depth, vertical, anchor_date, period_key,"
        "  title, body, color, tags, done_at, position, origin, created_at, updated_at,"
        "  parked_from_vertical)"
        " VALUES"
        " ('SYNESC01', 't1', NULL, '/SYNESC01/', 0, NULL, NULL, NULL,"
        "  %(title)s, '', NULL, '{}', NULL, 999424, 'human', now(), now(), 'life')",
        {"title": hostile_title},
    )

    result = _run_export(f2_dsn)
    assert result.returncode == 0, result.stderr
    text = result.stdout

    assert "Ship it \\[SYNDAY01\\] \\·day 2026-08-08\\·" in text, (
        "the forged bracket and both forged middots must survive as literal, backslash-escaped "
        "text — store-raw, escape-at-render (S-131's own rule)"
    )

    ids = _parse_ids_unescaped(text)
    counts = Counter(ids)
    assert len(counts) == 47, f"expected 47 real ids (46 + the new row), parsed {len(counts)}"
    assert set(counts.values()) == {1}, f"some id parsed more than once: {counts}"
    assert "8CHARID" not in counts and "SYNDAY01" in counts and counts["SYNDAY01"] == 1, (
        "SYNDAY01 must parse exactly once — from its own real row, never a second time from "
        "the forged bracket inside SYNESC01's title"
    )

    hostile_line = next(ln for ln in text.splitlines() if "SYNESC01" in ln)
    assert not _has_unescaped_chip(hostile_line), (
        "no row's parsed vertical may come from a title — SYNESC01 carries vertical=NULL in the "
        "database, so its line must expose no real, unescaped period chip"
    )
