"""A direct probe of owner scoping on every entry point S-20 names — all seven rows. Real
Postgres 16, real F2, no mocks (`docs/BRIEF.md` rule 2).

Row 2, `outline(owner='t1', id='SYNOTH01')`, is `core/markdown.py`'s verb (WP-14), not WP-13's.
It was written last, after WP-14 landed: while that module did not exist this file covered six
rows and said so, because a scenario id must not be claimed by a test that skips one of its own
named steps. WP-14 has since shipped, so the seventh row is driven here rather than left as a
permanent asterisk on a green `PASS S-20` — the alternative was a scenario reporting complete
while the one read path an agent is most likely to point at another owner's id went unproven.
Cross-module by necessity: S-20's whole assertion is that *every* entry point scopes, which no
single module's test file can show on its own.

The two id-less halves S-20 also asserts (`board(owner='t2', ...)` column counts;
`search(owner='t2', q='cycl')` == 0 rows) belong to `core/board.py` (WP-09) and `core/search.py`
— noted here, not tested, since they take no id and so cannot carry a foreign one.

Run directly:
    PGHOST=127.0.0.1 PGPORT=55432 PGUSER=verticals PGPASSWORD=verticals \\
        .venv/bin/python -m pytest tests/core/test_owner_404.py -v -s
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date
from pathlib import Path

import psycopg
import pytest

from verticals.core import goals, markdown, moves
from verticals.core.errors import NotFound
from tests.conftest import maintenance_dsn
from tests.harness import stmt

OWNER = "t1"  # the caller — SYNOTH01 itself belongs to t2
FOREIGN_ID = "SYNOTH01"

F2_SQL = Path(__file__).resolve().parents[1] / "fixtures" / "f2_synth.sql"


@pytest.fixture
def f2(db: psycopg.Connection) -> Iterator[psycopg.Connection]:
    db.execute(F2_SQL.read_text())
    db.execute("ANALYZE goals")
    yield db


def _goal_count(conn: psycopg.Connection) -> int:
    return conn.execute("SELECT count(*) FROM goals").fetchone()[0]


def _foreign_row_digest(conn: psycopg.Connection) -> str:
    (value,) = conn.execute("SELECT md5(goals::text) FROM goals WHERE id = %s", (FOREIGN_ID,)).fetchone()
    return value


# --- S-20 — owner scoping on every entry point, read and write (all seven rows) -------------------


def test_s20_outline_against_a_foreign_id_is_notfound(f2: psycopg.Connection) -> None:
    """S-20 row 2 — `core/markdown.py`'s verb. The distinction that matters here is `NotFound`
    rather than `Forbidden`: `outline` renders a whole subtree, so a `Forbidden` would confirm
    the id exists somewhere and name the boundary it sits behind. `NotFound` is indistinguishable
    from "no such id anywhere", which is what S-20's own text demands of every one of the seven.
    """
    with pytest.raises(NotFound) as exc:
        markdown.outline(f2, owner=OWNER, id=FOREIGN_ID)
    assert exc.value.detail["id"] == FOREIGN_ID


def test_s20_goal_against_a_foreign_id_is_notfound(f2: psycopg.Connection) -> None:
    with pytest.raises(NotFound) as exc:
        goals.goal(f2, owner=OWNER, id=FOREIGN_ID)
    assert exc.value.detail["id"] == FOREIGN_ID


def test_s20_children_of_against_a_foreign_id_is_notfound(f2: psycopg.Connection) -> None:
    with pytest.raises(NotFound) as exc:
        goals.children_of(f2, owner=OWNER, id=FOREIGN_ID)
    assert exc.value.detail["id"] == FOREIGN_ID


def test_s20_update_against_a_foreign_id_is_notfound(f2: psycopg.Connection) -> None:
    """The one that matters most (S-20's own text): a foreign id reaching an `UPDATE`, not just
    a read, is the failure that would actually leak or corrupt another owner's row."""
    with pytest.raises(NotFound) as exc:
        goals.update(f2, owner=OWNER, id=FOREIGN_ID, title="x")
    assert exc.value.detail["id"] == FOREIGN_ID


def test_s20_schedule_against_a_foreign_id_is_notfound(f2: psycopg.Connection) -> None:
    with pytest.raises(NotFound) as exc:
        moves.schedule(f2, owner=OWNER, id=FOREIGN_ID, vertical="day", anchor_date=date(2026, 8, 8))
    assert exc.value.detail["id"] == FOREIGN_ID


def test_s20_reparent_against_a_foreign_id_is_notfound(f2: psycopg.Connection) -> None:
    with pytest.raises(NotFound) as exc:
        moves.reparent(f2, owner=OWNER, id=FOREIGN_ID, parent_id=None)
    assert exc.value.detail["id"] == FOREIGN_ID


def test_s20_delete_against_a_foreign_id_is_notfound(f2: psycopg.Connection) -> None:
    with pytest.raises(NotFound) as exc:
        goals.delete(f2, owner=OWNER, id=FOREIGN_ID, cascade=False)
    assert exc.value.detail["id"] == FOREIGN_ID


def test_s20_all_seven_calls_together_leave_49_rows_and_synoth01_untouched(f2: psycopg.Connection) -> None:
    """All seven calls above, run back-to-back on one connection — S-20's own aggregate assertion,
    verbatim: `SELECT count(*)` still 49 after all seven, and `SYNOTH01`'s row digest unchanged.
    Never `Forbidden`: every one of the seven is `NotFound`, indistinguishable from "no such id
    anywhere" — an existence oracle across owners is itself a leak (S-20's own framing).

    Run together rather than only one per test because the failure this guards against is
    cumulative: a verb that scopes correctly in isolation but leaves a row locked, a transaction
    open or a partial write behind would still show 49 on its own and not in sequence."""
    digest_before = _foreign_row_digest(f2)

    attempts = [
        lambda: goals.goal(f2, owner=OWNER, id=FOREIGN_ID),
        lambda: markdown.outline(f2, owner=OWNER, id=FOREIGN_ID),
        lambda: goals.children_of(f2, owner=OWNER, id=FOREIGN_ID),
        lambda: goals.update(f2, owner=OWNER, id=FOREIGN_ID, title="x"),
        lambda: moves.schedule(f2, owner=OWNER, id=FOREIGN_ID, vertical="day", anchor_date=date(2026, 8, 8)),
        lambda: moves.reparent(f2, owner=OWNER, id=FOREIGN_ID, parent_id=None),
        lambda: goals.delete(f2, owner=OWNER, id=FOREIGN_ID, cascade=False),
    ]
    for call in attempts:
        with pytest.raises(NotFound):
            call()

    assert _goal_count(f2) == 49
    assert _foreign_row_digest(f2) == digest_before


def test_s20_update_against_a_foreign_id_touches_no_row_not_even_via_bulk(f2: psycopg.Connection) -> None:
    """Row 4's write-path risk, once more through the bulk `ids=` form, mixing one real `t1` id
    with the foreign one — all-or-nothing must still hold, and the real id's row must survive
    untouched too, not just the foreign one."""
    own_before = f2.execute("SELECT title FROM goals WHERE id = 'SYNORD01'").fetchone()[0]
    with pytest.raises(NotFound) as exc:
        goals.update(f2, owner=OWNER, ids=["SYNORD01", FOREIGN_ID], title="x")
    assert exc.value.detail["id"] == FOREIGN_ID
    own_after = f2.execute("SELECT title FROM goals WHERE id = 'SYNORD01'").fetchone()[0]
    assert own_after == own_before, "the bulk call's own-owner id must not be partially written"
