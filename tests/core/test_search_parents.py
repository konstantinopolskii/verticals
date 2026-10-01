"""The board's finding (docs/design-handoff S1.P3): every word of three letters or more, in titles and notes, each match
with its parents root first and its value's colour, in one statement."""

from __future__ import annotations

from datetime import date

import psycopg
import pytest

from verticals.core import goals, search
from verticals.core.errors import ValidationError

OWNER = "SYN-finding-owner"


def _make(conn: psycopg.Connection, title: str, vertical: str, parent: str | None = None, body: str = "",
          color: str | None = None) -> str:
    return goals.create(conn, owner=OWNER, title=title, body=body, vertical=vertical, anchor_date=date(2026, 10, 1),
                        parent_id=parent, color=color).goal.id


def test_a_word_only_in_notes_is_found_with_its_parents_root_first(db: psycopg.Connection) -> None:
    value = _make(db, "SYN value", "life", color="#92ce14")
    year = _make(db, "SYN launch the series", "year", value)
    step = _make(db, "SYN run the pilots", "quarter", year, body="Reach out to local teams.")
    result = search.search_with_parents(db, owner=OWNER, q="local")
    assert [goal.id for goal in result.goals] == [step]
    assert [parent.id for parent in result.parents[step]] == [value, year]
    assert [parent.vertical for parent in result.parents[step]] == ["life", "year"]
    assert result.goals[0].color == "#92ce14"


def test_every_word_of_three_letters_must_match(db: psycopg.Connection) -> None:
    outline = _make(db, "SYN draft the pilot outline", "week")
    _make(db, "SYN pilot slides", "week")
    result = search.search_with_parents(db, owner=OWNER, q="pilot outline of")
    assert [goal.id for goal in result.goals] == [outline]


def test_words_under_three_letters_are_the_boards(db: psycopg.Connection) -> None:
    with pytest.raises(ValidationError):
        search.search_with_parents(db, owner=OWNER, q="ab cd")


def test_more_than_the_limit_is_cut_and_says_so(db: psycopg.Connection) -> None:
    for i in range(3):
        _make(db, f"SYN many {i}", "day")
    result = search.search_with_parents(db, owner=OWNER, q="many", limit=2)
    assert len(result.goals) == 2
    assert result.truncated
