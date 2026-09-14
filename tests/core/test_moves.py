"""A direct probe of `verticals/core/moves.py` — WP-13 — against real Postgres 16 and the real F2
fixture. No mocks, no stubs, no fakes (`docs/BRIEF.md` rule 2).

S-08 through S-13 are `core/tree.py`'s own mechanism (`attach`/`move`/`detach`/`renumber`),
already probed directly by `tests/core/test_tree.py` (WP-08) under the same names — that file's
own docstring is explicit that those are not yet the catalogue's own scenarios, because the
public verb they are specified to enter through (`reparent`, `move_between`, `create`) did not
exist. It exists now: every test below re-drives the identical assertions through `moves.reparent`
/ `moves.move_between` / `goals.create`, so these are the catalogue's own S-08…S-13. Left as a
documented, deliberate choice (see this WP's final report): `test_tree.py`'s own `test_s06`
through `test_s13` are not renamed or removed here — they keep passing on the old, now-redundant
path, and the scenario-merge in `tests/harness/report.py` unions by id, so both files agreeing is
harmless; the WP-13 card sanctions renaming them to `test_tree_*` as optional, not mandatory.

Run directly:
    PGHOST=127.0.0.1 PGPORT=55432 PGUSER=verticals PGPASSWORD=verticals \\
        .venv/bin/python -m pytest tests/core/test_moves.py -v -s
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date
from pathlib import Path

import psycopg
import pytest

from verticals.core import goals
from verticals.core import moves
from verticals.core.errors import CycleRefused, NotFound, ValidationError
from tests.conftest import maintenance_dsn
from tests.harness import stmt
from tests.harness.report import gate

OWNER = "t1"

F2_SQL = Path(__file__).resolve().parents[1] / "fixtures" / "f2_synth.sql"


@pytest.fixture
def f2(db: psycopg.Connection) -> Iterator[psycopg.Connection]:
    """F2 on a fresh clone — same idiom as `tests/core/test_tree.py`'s own `f2` fixture."""
    db.execute(F2_SQL.read_text())
    db.execute("ANALYZE goals")
    yield db


def _dbname(conn: psycopg.Connection) -> str:
    return stmt.current_dbname(conn)


def _digest(conn: psycopg.Connection) -> str:
    """Full-table fingerprint, order-independent — `tests/core/test_tree.py`'s own `_digest`,
    duplicated locally (house convention: no cross-import between test modules either)."""
    (value,) = conn.execute("SELECT md5(string_agg(goals::text, '|' ORDER BY id)) FROM goals").fetchone()
    return value


def _update_calls(log: list[tuple[str, int]]) -> int:
    return sum(calls for text, calls in log if text.strip().upper().startswith("UPDATE"))


def _select_for_update_calls(log: list[tuple[str, int]]) -> int:
    return sum(calls for text, calls in log if "FOR UPDATE" in text.upper())


def _require_stmt_counter(dsn: str) -> None:
    if not stmt.available(dsn):
        gate("pg_stat_statements unavailable — statement-count assertion cannot run")


# --- S-08 — reparent onto self is refused --------------------------------------------------------


def test_s08_reparent_onto_self_is_refused(f2: psycopg.Connection) -> None:
    before = f2.execute("SELECT parent_id, updated_at FROM goals WHERE id = 'SYNQ1R01'").fetchone()
    with pytest.raises(CycleRefused) as exc:
        moves.reparent(f2, owner=OWNER, id="SYNQ1R01", parent_id="SYNQ1R01")
    assert exc.value.detail["reason"] == "self"
    after = f2.execute("SELECT parent_id, updated_at FROM goals WHERE id = 'SYNQ1R01'").fetchone()
    assert before == after
    assert f2.execute("SELECT count(*) FROM goals").fetchone()[0] == 49


# --- S-09 — an indirect cycle is refused inside the transaction -----------------------------------


def test_s09_indirect_cycle_refused_inside_the_transaction(f2: psycopg.Connection) -> None:
    """`reparent('SYNLIF01', 'SYNSUB01')`: `SYNLIF01` is the root of the 9-node G1 chain,
    `SYNSUB01` six levels inside it. Verified from the statement log: exactly one
    `SELECT ... FOR UPDATE` and zero `UPDATE` — the extra `SELECT` `reparent` would otherwise add
    to re-read the full `Goal` never runs on this path, since `tree.move` raises before
    `moves.reparent`'s own trailing read is reached."""
    dsn = maintenance_dsn()
    _require_stmt_counter(dsn)
    dbname = _dbname(f2)

    digest_before = _digest(f2)
    stmt.reset(dsn, dbname)
    with pytest.raises(CycleRefused) as exc:
        moves.reparent(f2, owner=OWNER, id="SYNLIF01", parent_id="SYNSUB01")
    log = stmt.read(dsn, dbname)

    assert exc.value.detail["reason"] == "target_is_descendant"
    assert _select_for_update_calls(log) == 1, log
    assert _update_calls(log) == 0, log
    assert _digest(f2) == digest_before, "full-table digest changed on a refused cycle"
    assert f2.execute("SELECT count(*) FROM goals").fetchone()[0] == 49


# --- S-10 — the one dangerous write ---------------------------------------------------------------


def test_s10_reparent_across_verticals_rewrites_whole_subtree_in_one_update(f2: psycopg.Connection) -> None:
    """`reparent('SYNQ1R01', 'SYNDEC01')`. Exact depth/path per row, `vertical`/`period_key`
    untouched on all six, `SYNYRR01` unaffected, and the rewrite is exactly one `UPDATE`."""
    dsn = maintenance_dsn()
    _require_stmt_counter(dsn)
    dbname = _dbname(f2)

    stmt.reset(dsn, dbname)
    g = moves.reparent(f2, owner=OWNER, id="SYNQ1R01", parent_id="SYNDEC01")
    log = stmt.read(dsn, dbname)

    assert g.depth == 2
    assert g.path == "/SYNLIF01/SYNDEC01/SYNQ1R01/"
    assert g.vertical == "quarter", "reparent must not touch vertical"

    rows = {
        r[0]: (r[1], r[2])
        for r in f2.execute(
            "SELECT id, depth, path FROM goals WHERE id IN "
            "('SYNQ1R01','SYNQ2R01','SYNDAY01','SYNSUB01','SYNSUB02','SYNSUB03')"
        ).fetchall()
    }
    expect = {
        "SYNQ1R01": (2, "/SYNLIF01/SYNDEC01/SYNQ1R01/"),
        "SYNQ2R01": (3, "/SYNLIF01/SYNDEC01/SYNQ1R01/SYNQ2R01/"),
        "SYNDAY01": (4, "/SYNLIF01/SYNDEC01/SYNQ1R01/SYNQ2R01/SYNDAY01/"),
        "SYNSUB01": (5, "/SYNLIF01/SYNDEC01/SYNQ1R01/SYNQ2R01/SYNDAY01/SYNSUB01/"),
        "SYNSUB02": (5, "/SYNLIF01/SYNDEC01/SYNQ1R01/SYNQ2R01/SYNDAY01/SYNSUB02/"),
        "SYNSUB03": (5, "/SYNLIF01/SYNDEC01/SYNQ1R01/SYNQ2R01/SYNDAY01/SYNSUB03/"),
    }
    assert rows == expect

    updates = [(text, calls) for text, calls in log if text.strip().upper().startswith("UPDATE")]
    assert len(updates) == 1, updates
    assert updates[0][1] == 1, "the rewrite statement must run exactly once"

    verticals = dict(
        f2.execute(
            "SELECT id, vertical FROM goals WHERE id IN "
            "('SYNQ1R01','SYNQ2R01','SYNDAY01','SYNSUB01','SYNSUB02','SYNSUB03')"
        ).fetchall()
    )
    assert verticals["SYNQ1R01"] == "quarter" and verticals["SYNQ2R01"] == "quarter"
    assert verticals["SYNDAY01"] == "day"
    assert verticals["SYNSUB01"] is None and verticals["SYNSUB02"] is None and verticals["SYNSUB03"] is None

    yrr = f2.execute(
        "SELECT depth, (SELECT count(*) FROM goals WHERE parent_id = 'SYNYRR01') FROM goals"
        " WHERE id = 'SYNYRR01'"
    ).fetchone()
    assert yrr == (2, 0), "SYNYRR01 must still be at depth 2 with 0 children"
    assert f2.execute("SELECT count(*) FROM goals").fetchone()[0] == 49


# --- S-11 — reparent to NULL detaches to root ------------------------------------------------------


def test_s11_reparent_to_null_detaches_to_root(f2: psycopg.Connection) -> None:
    g = moves.reparent(f2, owner=OWNER, id="SYNDAY01", parent_id=None)
    assert g.path == "/SYNDAY01/"
    assert g.depth == 0
    assert g.vertical == "day", "SYNDAY01 keeps its vertical — still a card, not in Maybe"

    sub = f2.execute("SELECT path, depth FROM goals WHERE id = 'SYNSUB01'").fetchone()
    assert sub == ("/SYNDAY01/SYNSUB01/", 1)

    maybe = f2.execute(
        "SELECT count(*) FROM goals"
        " WHERE owner = %s AND vertical IS NULL AND parent_id IS NULL AND done_at IS NULL",
        (OWNER,),
    ).fetchone()[0]
    assert maybe == 5, "Maybe still returns 5 rows — SYNDAY01 does not join it"


# --- S-12 — gap ordering assigns 1024 multiples and midpoints --------------------------------------


def test_s12_gap_ordering_assigns_1024_multiples_and_midpoints(f2: psycopg.Connection) -> None:
    """1. read positions in week 2026-W32. 2. `create` at the column tail. 3. `move_between`
    `SYNORD01` and `SYNORD02` — the newly created row moves there."""
    initial = f2.execute(
        "SELECT id, position FROM goals"
        " WHERE owner = 't1' AND vertical = 'week' AND period_key = '2026-W32' ORDER BY position"
    ).fetchall()
    assert [p for _, p in initial] == [1024, 2048, 3072, 4096]

    created = goals.create(f2, owner=OWNER, title="tail", vertical="week", anchor_date=date(2026, 8, 5))
    assert created.goal.position == 5120

    moved = moves.move_between(
        f2, owner=OWNER, id=created.goal.id, after_id="SYNORD01", before_id="SYNORD02"
    )
    assert moved.position == 1536

    (data_type,) = f2.execute(
        "SELECT data_type FROM information_schema.columns"
        " WHERE table_name = 'goals' AND column_name = 'position'"
    ).fetchone()
    assert data_type == "integer"


# --- S-13 — gap exhaustion triggers a renumber that preserves order --------------------------------


def test_s13_gap_exhaustion_triggers_renumber_that_preserves_order(f2: psycopg.Connection) -> None:
    """Insert repeatedly between `SYNORD01` and whatever the last inserted row was, always via a
    real `create(after_id=..., before_id=...)` call — not a bare `renumber`/`attach` pair — until
    the operation renumbers."""
    dsn = maintenance_dsn()
    _require_stmt_counter(dsn)
    dbname = _dbname(f2)

    before_id = "SYNORD02"
    sequence: list[int] = []
    for i in range(10):
        created = goals.create(
            f2, owner=OWNER, title=f"midpoint {i}", vertical="week", anchor_date=date(2026, 8, 5),
            after_id="SYNORD01", before_id=before_id,
        )
        sequence.append(created.goal.position)
        before_id = created.goal.id

    assert sequence == [1536, 1280, 1152, 1088, 1056, 1040, 1032, 1028, 1026, 1025]

    order_before_renumber = [
        r[0]
        for r in f2.execute(
            "SELECT id FROM goals"
            " WHERE owner = 't1' AND vertical = 'week' AND period_key = '2026-W32'"
            " ORDER BY position, id"
        ).fetchall()
    ]
    assert len(order_before_renumber) == 14

    stmt.reset(dsn, dbname)
    eleventh = goals.create(
        f2, owner=OWNER, title="eleventh", vertical="week", anchor_date=date(2026, 8, 5),
        after_id="SYNORD01", before_id=before_id,
    )
    log = stmt.read(dsn, dbname)

    assert eleventh.goal.position == 1536

    updates = [(text, calls) for text, calls in log if text.strip().upper().startswith("UPDATE")]
    assert len(updates) == 1, updates
    assert "VALUES" in updates[0][0].upper()
    assert updates[0][1] == 1, "the renumber statement must run exactly once, not fourteen times"

    after_renumber = f2.execute(
        "SELECT id, position FROM goals"
        " WHERE owner = 't1' AND vertical = 'week' AND period_key = '2026-W32'"
        " ORDER BY position, id"
    ).fetchall()
    # `eleventh` was requested between SYNORD01 (index 0) and the tenth midpoint row (index 1 of
    # `order_before_renumber`) — so the fifteen-row order is the fourteen-row order with
    # `eleventh` spliced in right after index 0, not the fourteen-row order unchanged.
    expected_order = order_before_renumber[:1] + [eleventh.goal.id] + order_before_renumber[1:]
    assert [gid for gid, _ in after_renumber] == expected_order, "relative order must survive"

    # The fourteen pre-existing rows land on strict multiples of 1024; `eleventh` itself is the
    # freshly computed midpoint (1536) between the renumbered SYNORD01 (1024) and the row that
    # used to be `before_id` (2048) — it is not, and need not be, a multiple of 1024 itself.
    renumbered = [1024 * (i + 1) for i in range(14)]
    expected_positions = renumbered[:1] + [1536] + renumbered[1:]
    assert [pos for _, pos in after_renumber] == expected_positions

    final_positions = [
        p
        for (p,) in f2.execute(
            "SELECT position FROM goals"
            " WHERE owner = 't1' AND vertical = 'week' AND period_key = '2026-W32' ORDER BY position"
        ).fetchall()
    ]
    assert len(final_positions) == 15
    assert len(set(final_positions)) == 15, "all fifteen positions must be distinct"
    assert final_positions == sorted(final_positions)


# --- reparent(): NotFound, not a cycle verdict, for a target in another owner ----------------------


def test_reparent_new_parent_in_different_owner_is_notfound(f2: psycopg.Connection) -> None:
    with pytest.raises(NotFound) as exc:
        moves.reparent(f2, owner=OWNER, id="SYNQ1R01", parent_id="SYNOTH01")
    assert exc.value.detail["id"] == "SYNOTH01"


# --- move_between(): NotFound for a missing id ------------------------------------------------------


def test_move_between_notfound_for_missing_id(f2: psycopg.Connection) -> None:
    with pytest.raises(NotFound):
        moves.move_between(f2, owner=OWNER, id="NOSUCHID1", after_id="SYNORD01", before_id="SYNORD02")


# --- schedule(): the clear path (vertical=None, anchor_date=None) ------------------------------------


def test_schedule_clear_on_root_card_lands_in_maybe_scoped_group(f2: psycopg.Connection) -> None:
    scheduled = moves.schedule(f2, owner=OWNER, id="SYNORD01", vertical=None, anchor_date=None)
    g = scheduled.goal
    assert scheduled.descendants_clamped == 0
    assert g.vertical is None and g.period_key is None
    assert g.anchor_date == date(2026, 8, 5), "v2 park deliberately preserves the anchor"
    assert g.parked_from_vertical == "week"
    assert g.parent_id is None


def test_schedule_clear_on_scheduled_child_keeps_its_real_parent_and_sibling_scope(
    f2: psycopg.Connection,
) -> None:
    """SYNQ2R01 (parent_id='SYNQ1R01', vertical='quarter') loses its vertical but must keep its
    real parent — never silently re-scoped to the Maybe pile's own position numbering, which
    would be a different sibling group than its true one."""
    siblings_before = f2.execute(
        "SELECT id, position FROM goals WHERE owner = %s AND parent_id = 'SYNQ1R01'", (OWNER,)
    ).fetchall()
    scheduled = moves.schedule(f2, owner=OWNER, id="SYNQ2R01", vertical=None, anchor_date=None)
    g = scheduled.goal
    assert scheduled.descendants_clamped == 0
    assert g.parent_id == "SYNQ1R01"
    assert g.vertical is None and g.period_key is None
    assert g.anchor_date == date(2026, 9, 30)
    assert g.parked_from_vertical == "quarter"

    siblings_after = f2.execute(
        "SELECT id, position FROM goals WHERE owner = %s AND parent_id = 'SYNQ1R01'", (OWNER,)
    ).fetchall()
    positions = [p for _, p in siblings_after]
    assert len(positions) == len(set(positions)), "no position collision among SYNQ1R01's real children"
    assert len(siblings_after) == len(siblings_before), "reparenting is untouched by a schedule clear"


def test_schedule_clear_and_reset_round_trips(f2: psycopg.Connection) -> None:
    g1 = moves.schedule(f2, owner=OWNER, id="SYNORD01", vertical=None, anchor_date=None).goal
    assert g1.period_key is None
    g2 = moves.schedule(
        f2, owner=OWNER, id="SYNORD01", vertical="week", anchor_date=date(2026, 8, 5)
    ).goal
    assert g2.vertical == "week" and g2.period_key == "2026-W32"


def test_schedule_clear_notfound_for_missing_id(f2: psycopg.Connection) -> None:
    with pytest.raises(NotFound):
        moves.schedule(f2, owner=OWNER, id="NOSUCHID1", vertical=None, anchor_date=None)


def test_schedule_anchor_date_without_vertical_is_refused(f2: psycopg.Connection) -> None:
    with pytest.raises(ValidationError) as exc:
        moves.schedule(f2, owner=OWNER, id="SYNORD01", vertical=None, anchor_date=date(2026, 8, 8))
    assert exc.value.detail["field"] == "vertical,anchor_date"


def test_schedule_parent_down_clamps_every_violating_descendant_in_one_bulk_update(
    f2: psycopg.Connection,
) -> None:
    anchor = date(2026, 8, 12)
    parent = goals.create(
        f2, owner=OWNER, title="cascade parent", vertical="week", anchor_date=anchor
    ).goal
    child = goals.create(
        f2, owner=OWNER, title="cascade child", parent_id=parent.id,
        vertical="week", anchor_date=anchor,
    ).goal
    grandchild = goals.create(
        f2, owner=OWNER, title="cascade grandchild", parent_id=child.id,
        vertical="week", anchor_date=anchor,
    ).goal
    parked = goals.create(
        f2, owner=OWNER, title="cascade parked", parent_id=parent.id
    ).goal
    day_child = goals.create(
        f2, owner=OWNER, title="cascade already day", parent_id=parent.id,
        vertical="day", anchor_date=anchor,
    ).goal
    parked_before = f2.execute(
        "SELECT vertical, anchor_date, period_key, parked_from_vertical, position, updated_at "
        "FROM goals WHERE id = %s",
        (parked.id,),
    ).fetchone()
    day_before = f2.execute(
        "SELECT vertical, anchor_date, period_key, parked_from_vertical, position, updated_at "
        "FROM goals WHERE id = %s",
        (day_child.id,),
    ).fetchone()

    dsn = maintenance_dsn()
    _require_stmt_counter(dsn)
    dbname = _dbname(f2)
    stmt.reset(dsn, dbname)
    scheduled = moves.schedule(
        f2, owner=OWNER, id=parent.id, vertical="day", anchor_date=anchor
    )
    log = stmt.read(dsn, dbname)

    assert scheduled.descendants_clamped == 2
    assert scheduled.goal.vertical == "day"
    assert scheduled.goal.period_key == "2026-08-12"
    clamped = {
        row[0]: row[1:]
        for row in f2.execute(
            "SELECT id, vertical, anchor_date, period_key, parked_from_vertical, position "
            "FROM goals WHERE id = ANY(%s)",
            ([child.id, grandchild.id],),
        ).fetchall()
    }
    assert clamped[child.id][:4] == ("day", anchor, "2026-08-12", None)
    assert clamped[grandchild.id][:4] == ("day", anchor, "2026-08-12", None)
    assert scheduled.goal.position < clamped[child.id][4] < clamped[grandchild.id][4]
    assert f2.execute(
        "SELECT vertical, anchor_date, period_key, parked_from_vertical, position, updated_at "
        "FROM goals WHERE id = %s",
        (parked.id,),
    ).fetchone() == parked_before
    assert f2.execute(
        "SELECT vertical, anchor_date, period_key, parked_from_vertical, position, updated_at "
        "FROM goals WHERE id = %s",
        (day_child.id,),
    ).fetchone() == day_before

    clamp_updates = [
        calls for text, calls in log if "WITH CLAMP_ROWS AS" in text.upper()
    ]
    assert clamp_updates == [1], "the whole subtree clamp must be one UPDATE ... RETURNING"
    advisory_locks = sum(
        calls for text, calls in log if "PG_ADVISORY_XACT_LOCK" in text.upper()
    )
    assert advisory_locks == 2, "primary and cascade allocations must each take the group lock"


def test_schedule_parent_up_moves_same_group_family_and_leaves_the_rest(
    f2: psycopg.Connection,
) -> None:
    """D109: descendants in the moved row's OLD (vertical, period_key) group are the rows the
    board renders nested inside its card — they travel with it in EVERY direction, up included.
    Descendants at other verticals or periods keep their own schedule."""
    anchor = date(2026, 8, 12)
    parent = goals.create(
        f2, owner=OWNER, title="family parent", vertical="week", anchor_date=anchor
    ).goal
    nested = goals.create(
        f2, owner=OWNER, title="family nested", parent_id=parent.id,
        vertical="week", anchor_date=anchor,
    ).goal
    nested_deep = goals.create(
        f2, owner=OWNER, title="family nested deep", parent_id=nested.id,
        vertical="week", anchor_date=anchor,
    ).goal
    day_child = goals.create(
        f2, owner=OWNER, title="family day child", parent_id=parent.id,
        vertical="day", anchor_date=anchor,
    ).goal
    other_week = goals.create(
        f2, owner=OWNER, title="family other week", parent_id=parent.id,
        vertical="week", anchor_date=date(2026, 8, 19),
    ).goal
    parked = goals.create(
        f2, owner=OWNER, title="family parked", parent_id=parent.id
    ).goal

    scheduled = moves.schedule(
        f2, owner=OWNER, id=parent.id, vertical="month", anchor_date=anchor
    )

    assert scheduled.goal.vertical == "month"
    assert scheduled.descendants_clamped == 2
    after = {
        row[0]: row[1:]
        for row in f2.execute(
            "SELECT id, vertical, period_key, parked_from_vertical FROM goals WHERE id = ANY(%s)",
            ([nested.id, nested_deep.id, day_child.id, other_week.id, parked.id],),
        ).fetchall()
    }
    assert after[nested.id] == ("month", "2026-08", None)
    assert after[nested_deep.id] == ("month", "2026-08", None)
    assert after[day_child.id][:2] == ("day", "2026-08-12")
    assert after[other_week.id][:2] == ("week", "2026-W34")
    assert after[parked.id][0] is None


def test_schedule_period_only_move_carries_the_nested_family(
    f2: psycopg.Connection,
) -> None:
    """Same vertical, next period: the nested unit travels; a different-period sibling card
    does not (it was never rendered inside this card)."""
    anchor = date(2026, 8, 12)
    parent = goals.create(
        f2, owner=OWNER, title="shift parent", vertical="week", anchor_date=anchor
    ).goal
    nested = goals.create(
        f2, owner=OWNER, title="shift nested", parent_id=parent.id,
        vertical="week", anchor_date=anchor,
    ).goal

    scheduled = moves.schedule(
        f2, owner=OWNER, id=parent.id, vertical="week", anchor_date=date(2026, 8, 19)
    )

    assert scheduled.descendants_clamped == 1
    assert scheduled.goal.period_key == "2026-W34"
    assert f2.execute(
        "SELECT vertical, period_key FROM goals WHERE id = %s", (nested.id,)
    ).fetchone() == ("week", "2026-W34")


# --- D241 — same-vertical subtasks unglued (supersedes D179's block half) ---------------------------


def test_d241_same_vertical_child_detaches_and_moves_to_another_parent(
    f2: psycopg.Connection,
) -> None:
    """Pre-D241, both calls below raised ValidationError ("same-vertical subgoal ... must stay
    under its parent" — D179, 2026-08-13). KK's 2026-08-15 report: D236's combine gesture made
    same-vertical subtasks the two-second ordinary case, and the refusal made that a one-way
    door — easy in, no way out. `reparent` is a structure verb only, so the schedule must ride
    through both moves untouched."""
    anchor = date(2026, 8, 8)
    parent = goals.create(
        f2, owner=OWNER, title="SYN glue parent", vertical="day", anchor_date=anchor
    ).goal
    child = goals.create(
        f2, owner=OWNER, title="SYN glue child", parent_id=parent.id,
        vertical="day", anchor_date=anchor,
    ).goal
    other = goals.create(
        f2, owner=OWNER, title="SYN glue other parent", vertical="day", anchor_date=anchor
    ).goal

    detached = moves.reparent(f2, owner=OWNER, id=child.id, parent_id=None)
    assert (detached.parent_id, detached.depth) == (None, 0)
    assert detached.path == f"/{child.id}/"
    assert (detached.vertical, detached.anchor_date) == ("day", anchor)

    moved = moves.reparent(f2, owner=OWNER, id=child.id, parent_id=other.id)
    assert moved.parent_id == other.id
    assert moved.path == f"/{other.id}/{child.id}/"
    assert (moved.vertical, moved.anchor_date) == ("day", anchor)
