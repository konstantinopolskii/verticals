"""AC-206 / S-131, claimed in full — `core/goals.py::create` (WP-13) refuses three hostile
titles before any write and stores two others raw; `core/markdown.py::outline` (this package)
then proves the render side: escaping, the parsed node set, the chip count, and rule 6's
descendant-body indent. Real Postgres, the real `create` verb, no mocks.

**Upgrade note.** This file previously could not print `PASS S-131`: `docs/E2E.md` S-131's steps
are "create four children of `SYNQ2R01` with hostile titles, then `outline(id='SYNQ2R01')`"
through the real `create` verb, and `core/goals.py` (WP-13) had not landed when this file was
first written, so every test here seeded its two *accepted* rows with a direct `INSERT` instead
and stayed named `test_outline_grammar_*` — proving escaping, not refusal, per
`tests/harness/report.py`'s own naming rule. `core/goals.py::create` has since landed with
`_validate_title`/`_is_control` doing exactly S-131's refusal work, so every test below now
routes through `goals.create` for all four hostile titles and claims `test_s131*_*`.

**A number discrepancy found in the process, reported rather than silently picked.**
`docs/E2E.md` S-131's table lists three distinct hostile title values across its first two rows
(`first\\nsecond`, `plan\\ttab`, `plan\\rcr`), but its own Assert paragraph immediately below
says "the two control-character titles are refused". `docs/ACCEPTANCE.md`'s AC-206 row — the
criterion this scenario proves — says "the three control-character titles are refused",
matching the table. `test_s131a_*` below asserts three refusals; E2E.md's "two" looks like the
stale number, flagged for the record rather than fixed here (not this package's file to edit).

`test_s131e_*`'s node also carries a non-empty body. F2 itself has none on any non-root row
(checked directly: `SELECT id FROM goals WHERE body <> '' AND parent_id IS NOT NULL` returns
zero rows), so nothing in the shipped fixture otherwise exercises grammar rule 6's descendant
branch — the indented, no-blank-line body — at all. This closes that gap rather than leaving
AC-128's core half (this package's other hook, per the WP-14 card) proven only for root bodies.
"""

from __future__ import annotations

import re
from pathlib import Path

import psycopg
import pytest

from verticals.core import goals, markdown
from verticals.core.errors import NotFound, ValidationError

F2_SQL = Path(__file__).resolve().parents[1] / "fixtures" / "f2_synth.sql"

_ID_RE = re.compile(r"(?<!\\)\[([0-9A-Za-z]{8})\]")
_CHIP_RE = re.compile(r"(?<!\\)·[a-z]+ [^·\n]+(?<!\\)·")

# S-131's table, rows 1-2: three hostile values, not two (see module docstring).
_HOSTILE_CONTROL_TITLES = ("first\nsecond", "plan\ttab", "plan\rcr")


def _parse_ids(text: str) -> list[str]:
    """The one small parser S-131 itself calls for — id positions only, and only the unescaped
    ones: a title's own literal `[`/`]` is always backslash-escaped by the renderer, so a real
    id is exactly a `[........]` with no backslash immediately before it."""
    return _ID_RE.findall(text)


def _count_chips(text: str) -> int:
    return len(_CHIP_RE.findall(text))


@pytest.fixture
def f2(db: psycopg.Connection) -> psycopg.Connection:
    db.execute(F2_SQL.read_text())
    db.execute("ANALYZE goals")
    return db


@pytest.fixture
def f2_with_hostile_children(f2: psycopg.Connection) -> tuple[psycopg.Connection, str, str]:
    """The two *accepted* rows of S-131's table (rows 3 and 4), created through the real verb —
    not seeded by direct `INSERT`. Ids are whatever `create` mints (IR-05, random 8-char base62);
    captured here so the tests below assert against the real id rather than a hardcoded one."""
    bracket = goals.create(f2, owner="t1", parent_id="SYNQ2R01", title="Fix [8CHARID] now")
    chip = goals.create(
        f2,
        owner="t1",
        parent_id="SYNQ2R01",
        title="Ship ·quarter 2026-Q3· soon",
        body="Line one.\n\n\nLine two after two blanks.",
    )
    return f2, bracket.goal.id, chip.goal.id


def test_s131a_control_character_titles_are_refused_before_any_write(
    f2: psycopg.Connection,
) -> None:
    (before,) = f2.execute("SELECT count(*) FROM goals").fetchone()

    for title in _HOSTILE_CONTROL_TITLES:
        with pytest.raises(ValidationError) as excinfo:
            goals.create(f2, owner="t1", parent_id="SYNQ2R01", title=title)
        assert excinfo.value.detail.get("field") == "title"

    (after,) = f2.execute("SELECT count(*) FROM goals").fetchone()
    assert after == before, "a refused create must not write any row"


def test_s131b_accepted_titles_round_trip_raw_and_byte_identical(
    f2_with_hostile_children: tuple[psycopg.Connection, str, str],
) -> None:
    conn, bracket_id, chip_id = f2_with_hostile_children
    stored_bracket = goals.goal(conn, owner="t1", id=bracket_id).goal
    stored_chip = goals.goal(conn, owner="t1", id=chip_id).goal
    assert stored_bracket.title == "Fix [8CHARID] now"
    assert stored_chip.title == "Ship ·quarter 2026-Q3· soon"


def test_s131c_outline_escapes_the_forged_bracket_and_chip(
    f2_with_hostile_children: tuple[psycopg.Connection, str, str],
) -> None:
    conn, bracket_id, chip_id = f2_with_hostile_children
    text = markdown.outline(conn, owner="t1", id="SYNQ2R01")

    assert f"- [ ] Fix \\[8CHARID\\] now [{bracket_id}]" in text
    assert f"- [ ] Ship \\·quarter 2026-Q3\\· soon [{chip_id}]" in text
    # unescaped, would only exist if the renderer failed to escape the title
    assert "[8CHARID]" not in text


def test_s131d_parsed_node_set_and_chip_count(
    f2_with_hostile_children: tuple[psycopg.Connection, str, str],
) -> None:
    conn, bracket_id, chip_id = f2_with_hostile_children
    text = markdown.outline(conn, owner="t1", id="SYNQ2R01")
    ids = _parse_ids(text)

    expected = {"SYNQ2R01", "SYNDAY01", "SYNSUB01", "SYNSUB02", "SYNSUB03", bracket_id, chip_id}
    assert set(ids) == expected, f"parsed {sorted(ids)}, expected {sorted(expected)}"
    assert len(ids) == len(expected), f"an id parsed more than once: {ids}"
    assert "8CHARID" not in ids

    # SYNQ2R01 (quarter) and SYNDAY01 (day) are the only two nodes in this subtree with a real
    # vertical; both new nodes are vertical NULL, including the one whose title forges a chip.
    assert _count_chips(text) == 2


def test_s131e_descendant_body_indented_no_blank_line(
    f2_with_hostile_children: tuple[psycopg.Connection, str, str],
) -> None:
    conn, bracket_id, chip_id = f2_with_hostile_children
    text = markdown.outline(conn, owner="t1", id="SYNQ2R01")
    # rule 6: a descendant's body sits at indent + 6 (this node is a direct child of the queried
    # root, indent 0, so content column 6), blank lines collapsed to one, no blank line before it.
    expected = (
        f"- [ ] Ship \\·quarter 2026-Q3\\· soon [{chip_id}]\n"
        "      Line one.\n"
        "\n"
        "      Line two after two blanks.\n"
    )
    assert expected in text


def test_markdown_outline_missing_id_raises_not_found(f2: psycopg.Connection) -> None:
    """Not part of S-131 (its steps are the hostile-title case only) — `core/markdown.py`'s own
    error path, exercised here rather than left unproven."""
    with pytest.raises(NotFound):
        markdown.outline(f2, owner="t1", id="NOSUCHID1")
