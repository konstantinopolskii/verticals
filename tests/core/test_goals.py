"""A direct probe of `verticals/core/goals.py` — WP-13 — against real Postgres 16 and the real F2
fixture. No mocks, no stubs, no fakes (`docs/BRIEF.md` rule 2).

Covers, through the real verbs (not `tree.py`/`idem.py` directly): S-03 (the `period_key` edge
table, through `create`), S-04 (`period_key` rejected as input; `create` then `schedule`), S-06,
S-07 (root/child insert), S-29, S-30 (idempotent `create`, both halves). `core/moves.py`'s own
scenarios (S-08…S-13) are `tests/core/test_moves.py`; `delete`'s (S-14…S-16) are
`tests/core/test_delete.py`; progress (S-17…S-19) is `tests/core/test_progress.py`; owner scoping
across every verb (S-20) is `tests/core/test_owner_404.py`. The rest of this file is adversarial
coverage of `goals.py`'s own bounds and read surface — real, needed, but not itself a catalogue
scenario, so none of it is named `test_sNN_*` (`docs/IMPLEMENTATION.md` WP-13 card, naming rule).

Run directly:
    PGHOST=127.0.0.1 PGPORT=55432 PGUSER=verticals PGPASSWORD=verticals \\
        .venv/bin/python -m pytest tests/core/test_goals.py -v -s
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date
from pathlib import Path

import psycopg
import pytest
from psycopg.types.json import Jsonb

from verticals.core import goals
from verticals.core import vertical as vertical_mod
from verticals.core import moves
from verticals.core.errors import IdempotencyConflict, NotFound, ValidationError
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


def _goal_count(conn: psycopg.Connection) -> int:
    return conn.execute("SELECT count(*) FROM goals").fetchone()[0]


def _idem_count(conn: psycopg.Connection, owner: str) -> int:
    return conn.execute("SELECT count(*) FROM idempotency WHERE owner = %s", (owner,)).fetchone()[0]


def _require_stmt_counter(dsn: str) -> None:
    if not stmt.available(dsn):
        gate("pg_stat_statements unavailable — statement-count assertion cannot run")


# --- S-03 — period_key over the full edge table, through create() -----------------------------

# anchor, day, week, month, quarter, year, decade — docs/E2E.md S-03's own table, verbatim.
_S03_EDGE_TABLE = [
    ("2024-02-29", "2024-02-29", "2024-W09", "2024-02", "2024-Q1", "2024", "2023–2025"),
    ("2021-01-01", "2021-01-01", "2020-W53", "2021-01", "2021-Q1", "2021", "2020–2022"),
    ("2021-01-03", "2021-01-03", "2020-W53", "2021-01", "2021-Q1", "2021", "2020–2022"),
    ("2021-01-04", "2021-01-04", "2021-W01", "2021-01", "2021-Q1", "2021", "2020–2022"),
    ("2026-12-31", "2026-12-31", "2026-W53", "2026-12", "2026-Q4", "2026", "2026–2028"),
    ("2027-01-01", "2027-01-01", "2026-W53", "2027-01", "2027-Q1", "2027", "2026–2028"),
    ("2019-12-31", "2019-12-31", "2020-W01", "2019-12", "2019-Q4", "2019", "2017–2019"),
    ("2020-01-01", "2020-01-01", "2020-W01", "2020-01", "2020-Q1", "2020", "2020–2022"),
    ("2029-12-31", "2029-12-31", "2030-W01", "2029-12", "2029-Q4", "2029", "2029–2031"),
    ("2030-01-01", "2030-01-01", "2030-W01", "2030-01", "2030-Q1", "2030", "2029–2031"),
    ("2016-01-01", "2016-01-01", "2015-W53", "2016-01", "2016-Q1", "2016", "2014–2016"),
    ("2026-08-08", "2026-08-08", "2026-W32", "2026-08", "2026-Q3", "2026", "2026–2028"),
]
_S03_SCALES = ("day", "week", "month", "quarter", "year", "decade")


def test_s03_period_key_over_the_full_edge_table(f2: psycopg.Connection) -> None:
    """72 exact string equalities, each via a real `create()` call — not `core.vertical.period_key`
    called directly, which would prove the arithmetic but not that `create` wires it in."""
    checked = 0
    for anchor, *expected_by_scale in _S03_EDGE_TABLE:
        for scale, expected in zip(_S03_SCALES, expected_by_scale):
            created = goals.create(
                f2, owner=OWNER, title=f"edge {anchor} {scale}",
                vertical=scale, anchor_date=date.fromisoformat(anchor),
            )
            assert created.goal.period_key == expected, (anchor, scale, created.goal.period_key)
            checked += 1
    assert checked == 72

    life = goals.create(f2, owner=OWNER, title="life probe", vertical="life", anchor_date=date(2026, 8, 8))
    assert life.goal.period_key == "life"
    assert life.goal.anchor_date == date(2026, 8, 8), "anchor_date is stored as supplied (§10-D10)"

    before = _goal_count(f2)
    with pytest.raises(ValueError, match="fortnight"):
        vertical_mod.period_key("fortnight", date(2026, 8, 8))
    assert _goal_count(f2) == before, "the direct, unreachable-from-create() call wrote no row"


# --- S-04 — period_key is derived, never accepted ----------------------------------------------


def test_s04a_period_key_rejected_as_input(f2: psycopg.Connection) -> None:
    before = _goal_count(f2)
    with pytest.raises(ValidationError) as exc:
        goals.create(
            f2, owner=OWNER, title="rejected", vertical="week",
            anchor_date=date(2026, 8, 8), period_key="1999-W01",
        )
    assert exc.value.detail["field"] == "period_key"
    assert _goal_count(f2) == before, "pinned rejected, not ignored — §10-D2"


def test_s04b_create_then_schedule_recomputes_period_key(f2: psycopg.Connection) -> None:
    created = goals.create(f2, owner=OWNER, title="s04b", vertical="week", anchor_date=date(2026, 8, 8))
    assert created.goal.period_key == "2026-W32"

    rescheduled = moves.schedule(
        f2, owner=OWNER, id=created.goal.id, vertical="month", anchor_date=date(2026, 8, 8)
    ).goal
    assert rescheduled.period_key == "2026-08"
    assert rescheduled.anchor_date == date(2026, 8, 8), "anchor_date unchanged at 2026-08-08"


# --- S-06, S-07 — root and child insert ----------------------------------------------------------


def test_s06_root_insert_sets_path_and_depth(f2: psycopg.Connection) -> None:
    created = goals.create(f2, owner=OWNER, title="root", vertical="day", anchor_date=date(2026, 8, 8))
    g = created.goal
    assert g.path == f"/{g.id}/"
    assert g.depth == 0
    assert g.parent_id is None


def test_s07_child_insert_extends_parent_path(f2: psycopg.Connection) -> None:
    created = goals.create(f2, owner=OWNER, parent_id="SYNQ2R01", title="child")
    g = created.goal
    assert g.path == f"/SYNLIF01/SYNDEC01/SYNYRR01/SYNQ1R01/SYNQ2R01/{g.id}/"
    assert g.depth == 5
    assert len(g.path) == 6 * 9 + 1 == 55


# --- create(): field bounds (IR-11) — adversarial, not scenario-claiming ------------------------


def test_create_blank_title_is_refused(f2: psycopg.Connection) -> None:
    with pytest.raises(ValidationError) as exc:
        goals.create(f2, owner=OWNER, title="   ")
    assert exc.value.detail["field"] == "title"


def test_create_title_above_maximum_is_refused(f2: psycopg.Connection) -> None:
    with pytest.raises(ValidationError) as exc:
        goals.create(f2, owner=OWNER, title="x" * 251)
    assert exc.value.detail["field"] == "title"


def test_create_title_at_maximum_is_accepted(f2: psycopg.Connection) -> None:
    created = goals.create(f2, owner=OWNER, title="x" * 250)
    assert len(created.goal.title) == 250


def test_create_title_control_char_is_refused(f2: psycopg.Connection) -> None:
    with pytest.raises(ValidationError) as exc:
        goals.create(f2, owner=OWNER, title="line one\nline two")
    assert exc.value.detail["field"] == "title"


def test_create_body_over_64kb_is_refused(f2: psycopg.Connection) -> None:
    with pytest.raises(ValidationError) as exc:
        goals.create(f2, owner=OWNER, title="body test", body="x" * (64 * 1024 + 1))
    assert exc.value.detail["field"] == "body"


def test_create_body_at_64kb_is_accepted(f2: psycopg.Connection) -> None:
    created = goals.create(f2, owner=OWNER, title="body ok", body="x" * (64 * 1024))
    assert len(created.goal.body.encode("utf-8")) == 64 * 1024


def test_create_17_tags_is_refused(f2: psycopg.Connection) -> None:
    with pytest.raises(ValidationError) as exc:
        goals.create(f2, owner=OWNER, title="tags", tags=[f"t{i}" for i in range(17)])
    assert exc.value.detail["field"] == "tags"


def test_create_16_tags_is_accepted(f2: psycopg.Connection) -> None:
    created = goals.create(f2, owner=OWNER, title="tags ok", tags=[f"t{i}" for i in range(16)])
    assert len(created.goal.tags) == 16


def test_create_tag_49_chars_is_refused(f2: psycopg.Connection) -> None:
    with pytest.raises(ValidationError) as exc:
        goals.create(f2, owner=OWNER, title="tag len", tags=["x" * 49])
    assert exc.value.detail["field"] == "tags"


def test_create_tag_with_whitespace_is_refused(f2: psycopg.Connection) -> None:
    with pytest.raises(ValidationError):
        goals.create(f2, owner=OWNER, title="tag ws", tags=["has space"])


def test_create_unknown_color_is_refused(f2: psycopg.Connection) -> None:
    with pytest.raises(ValidationError) as exc:
        goals.create(f2, owner=OWNER, title="color", color="#ff0000")
    assert exc.value.detail["field"] == "color"


def test_create_canon_color_is_accepted(f2: psycopg.Connection) -> None:
    created = goals.create(f2, owner=OWNER, title="color ok", color="#ecce32")
    assert created.goal.color == "#ecce32"


def test_create_anchor_date_without_vertical_is_refused(f2: psycopg.Connection) -> None:
    with pytest.raises(ValidationError) as exc:
        goals.create(f2, owner=OWNER, title="orphan anchor", anchor_date=date(2026, 8, 8))
    assert exc.value.detail["field"] == "vertical,anchor_date"


def test_create_unknown_vertical_is_refused(f2: psycopg.Connection) -> None:
    with pytest.raises(ValidationError) as exc:
        goals.create(f2, owner=OWNER, title="bad scale", vertical="fortnight", anchor_date=date(2026, 8, 8))
    assert exc.value.detail["field"] == "vertical"


def test_create_unknown_origin_is_refused(f2: psycopg.Connection) -> None:
    with pytest.raises(ValidationError) as exc:
        goals.create(f2, owner=OWNER, title="bad origin", origin="robot")
    assert exc.value.detail["field"] == "origin"


def _chain(depth: int) -> dict:
    """A single-branch `children` spec `depth` levels deep (level 1 is the outermost dict)."""
    spec = {"title": "L1"}
    node = spec
    for i in range(2, depth + 1):
        node["children"] = [{"title": f"L{i}"}]
        node = node["children"][0]
    return spec


def test_create_children_9_deep_is_refused(f2: psycopg.Connection) -> None:
    with pytest.raises(ValidationError) as exc:
        goals.create(f2, owner=OWNER, title="root", children=[_chain(9)])
    assert exc.value.detail["field"] == "children"


def test_create_children_8_deep_is_accepted(f2: psycopg.Connection) -> None:
    created = goals.create(f2, owner=OWNER, title="root", children=[_chain(8)])
    assert len(created.children) == 8


def test_create_201_nodes_is_refused(f2: psycopg.Connection) -> None:
    with pytest.raises(ValidationError) as exc:
        goals.create(f2, owner=OWNER, title="root", children=[{"title": f"c{i}"} for i in range(200)])
    assert exc.value.detail["field"] == "children"


def test_create_200_nodes_is_accepted(f2: psycopg.Connection) -> None:
    created = goals.create(f2, owner=OWNER, title="root", children=[{"title": f"c{i}"} for i in range(199)])
    assert 1 + len(created.children) == 200


def test_create_children_over_either_bound_writes_zero_rows(f2: psycopg.Connection) -> None:
    """AC-200's second clause: a refused `create` leaves no partial subtree behind. The four bound
    tests above assert only the exception and its `field`.

    **What this catches, established by planting the defect rather than assumed.** The first plant
    was the obvious one — move the node-count check inside `conn.transaction()`, after the root
    insert, so the bound is discovered mid-write. All seven tests still passed, this one included:
    `create` validates outside the transaction, but even when it does not, the `with
    conn.transaction()` block rolls the root back on the way out, so the row count is unchanged
    either way. Validation order is therefore *not* what makes AC-200's clause true, and a test
    written to check validation order would be a check that cannot fail.

    The second plant is the defect that can really happen: a write that escapes the transaction —
    `conn.execute` on the connection before the block opens, then a refusal inside it. That one
    fails here, `50 == 49`, because the block is a savepoint over an already-open transaction and
    cannot undo work done before it. So this test guards the transaction boundary, not the
    validation order, and that is the property worth guarding: every future `create` variant must
    keep all of its writes inside that one block.

    Digest as well as count, since a count alone passes if one row is written and another deleted."""
    before_count = _goal_count(f2)
    (before_digest,) = f2.execute("SELECT md5(string_agg(goals::text, '|' ORDER BY id)) FROM goals").fetchone()

    for children in ([_chain(9)], [{"title": f"c{i}"} for i in range(200)]):
        with pytest.raises(ValidationError):
            goals.create(f2, owner=OWNER, title="root", children=children)
        assert _goal_count(f2) == before_count, "a refused create wrote rows"

    (after_digest,) = f2.execute("SELECT md5(string_agg(goals::text, '|' ORDER BY id)) FROM goals").fetchone()
    assert after_digest == before_digest


def test_create_children_bound_refusals_name_which_bound_was_hit(f2: psycopg.Connection) -> None:
    """AC-200 calls the two refusals `children_too_deep` and `children_too_many`. No such code
    exists on `ValidationError` — the criterion names an interface the errors do not have. What
    they do carry is `field` plus `maximum`, and that pair *is* distinguishing, since the two
    bounds are different numbers: 8 and 200. Pinned here so the distinction is a tested property
    rather than an accident of the message text, and so that adding a `code` later (the other way
    to satisfy AC-200) does not silently remove the only thing that tells the two apart.

    Deliberately not asserting the prose message: a message is not an interface, and a test that
    pins one turns every rewording into a failure while catching nothing a caller can act on."""
    with pytest.raises(ValidationError) as too_deep:
        goals.create(f2, owner=OWNER, title="root", children=[_chain(9)])
    with pytest.raises(ValidationError) as too_many:
        goals.create(f2, owner=OWNER, title="root", children=[{"title": f"c{i}"} for i in range(200)])

    assert too_deep.value.detail["maximum"] == goals.MAX_CHILDREN_DEPTH == 8
    assert too_many.value.detail["maximum"] == goals.MAX_NODES_PER_CREATE == 200
    assert too_deep.value.detail["maximum"] != too_many.value.detail["maximum"]


def test_create_unexpected_child_spec_key_is_refused(f2: psycopg.Connection) -> None:
    with pytest.raises(ValidationError) as exc:
        goals.create(f2, owner=OWNER, title="root", children=[{"title": "x", "bogus": 1}])
    assert exc.value.detail["field"] == "children"


def test_create_child_needs_a_title(f2: psycopg.Connection) -> None:
    with pytest.raises(ValidationError) as exc:
        goals.create(f2, owner=OWNER, title="root", children=[{"body": "no title"}])
    assert exc.value.detail["field"] == "title"


def test_create_nested_plan_is_one_call_flattened(f2: psycopg.Connection) -> None:
    """S-52's own shape (proved fully at the MCP layer, not claimed here): one `create` call
    with grandchildren returns every descendant flattened, not only direct children."""
    created = goals.create(
        f2, owner=OWNER, title="plan root",
        children=[{"title": "phase 1", "children": [{"title": "step 1.1"}, {"title": "step 1.2"}]}],
    )
    assert len(created.children) == 3
    titles = {c.title for c in created.children}
    assert titles == {"phase 1", "step 1.1", "step 1.2"}
    parents = {c.title: c.parent_id for c in created.children}
    phase1_id = next(c.id for c in created.children if c.title == "phase 1")
    assert parents["step 1.1"] == phase1_id
    assert parents["step 1.2"] == phase1_id


# --- goal(), children_of(): reads, independent of any board date --------------------------------


def test_goal_returns_breadcrumb_and_children(f2: psycopg.Connection) -> None:
    detail = goals.goal(f2, owner=OWNER, id="SYNQ1R01")
    assert detail.goal.id == "SYNQ1R01"
    assert [a.id for a in detail.ancestors] == ["SYNLIF01", "SYNDEC01", "SYNYRR01"]
    assert [c.id for c in detail.children] == ["SYNQ2R01"]


def test_goal_notfound_for_missing_id(f2: psycopg.Connection) -> None:
    with pytest.raises(NotFound):
        goals.goal(f2, owner=OWNER, id="NOSUCHID1")


def test_goal_off_board_row_still_resolves(f2: psycopg.Connection) -> None:
    """F2 G5: SYNRET01/02 sit off the 2026-08-08 board on purpose but must still resolve here —
    `goal()` is independent of any board date (unlike `core/board.py`'s per-id dicts)."""
    detail = goals.goal(f2, owner=OWNER, id="SYNRET01")
    assert detail.goal.id == "SYNRET01"
    assert detail.goal.period_key == "2026-W31"


def test_children_of_direct_children_only_in_position_order(f2: psycopg.Connection) -> None:
    kids = goals.children_of(f2, owner=OWNER, id="SYNDAY01")
    assert [k.id for k in kids] == ["SYNSUB01", "SYNSUB02", "SYNSUB03"]


def test_children_of_notfound_for_missing_id(f2: psycopg.Connection) -> None:
    with pytest.raises(NotFound):
        goals.children_of(f2, owner=OWNER, id="NOSUCHID1")


# --- update(): content only, PATCH-partial, bulk all-or-nothing ---------------------------------


def test_update_partial_only_named_fields_change(f2: psycopg.Connection) -> None:
    created = goals.create(f2, owner=OWNER, title="orig title", body="orig body", color="#ecce32", tags=["a"])
    updated = goals.update(f2, owner=OWNER, id=created.goal.id, title="new title")
    assert updated.goal.title == "new title"
    assert updated.goal.body == "orig body"
    assert updated.goal.color == "#ecce32"
    assert updated.goal.tags == ("a",)


def test_update_color_can_be_cleared_to_none(f2: psycopg.Connection) -> None:
    # D231: colour is writable on value roots only, so the clear-to-None path is exercised on a
    # parentless life goal — the one place a stored colour is ever read from.
    created = goals.create(
        f2, owner=OWNER, title="color clear", vertical="life",
        anchor_date=date(2026, 8, 8), color="#ecce32",
    )
    updated = goals.update(f2, owner=OWNER, id=created.goal.id, color=None)
    assert updated.goal.color is None


def test_update_needs_at_least_one_field(f2: psycopg.Connection) -> None:
    created = goals.create(f2, owner=OWNER, title="empty update")
    with pytest.raises(ValidationError):
        goals.update(f2, owner=OWNER, id=created.goal.id)


def test_update_needs_exactly_one_of_id_or_ids(f2: psycopg.Connection) -> None:
    with pytest.raises(ValidationError):
        goals.update(f2, owner=OWNER, title="x")
    with pytest.raises(ValidationError):
        goals.update(f2, owner=OWNER, id="SYNORD01", ids=["SYNORD02"], title="x")


def test_update_bulk_all_or_nothing(f2: psycopg.Connection) -> None:
    (before,) = f2.execute("SELECT title FROM goals WHERE id = 'SYNORD01'").fetchone()
    with pytest.raises(NotFound):
        goals.update(f2, owner=OWNER, ids=["SYNORD01", "NOSUCHID1"], title="bulk fail")
    (after,) = f2.execute("SELECT title FROM goals WHERE id = 'SYNORD01'").fetchone()
    assert after == before, "a failed bulk update must not partially apply"


def test_update_bulk_success_returns_tuple_in_order(f2: psycopg.Connection) -> None:
    result = goals.update(f2, owner=OWNER, ids=["SYNORD02", "SYNORD01"], title="bulk ok")
    assert isinstance(result, tuple)
    assert [u.goal.id for u in result] == ["SYNORD02", "SYNORD01"]
    assert all(u.goal.title == "bulk ok" for u in result)


def test_update_notfound_for_missing_id(f2: psycopg.Connection) -> None:
    with pytest.raises(NotFound):
        goals.update(f2, owner=OWNER, id="NOSUCHID1", title="x")


def test_update_unknown_tag_shape_is_refused(f2: psycopg.Connection) -> None:
    with pytest.raises(ValidationError):
        goals.update(f2, owner=OWNER, id="SYNORD01", tags=["bad tag with spaces"])


def test_update_done_true_single_id_reports_open_descendants(f2: psycopg.Connection) -> None:
    """A leaf with no children of its own: `open_descendants == 0`, not `None` — `None` means
    "didn't touch completion", `0` means "closed, nothing left open" (`Updated`'s own docstring)."""
    updated = goals.update(f2, owner=OWNER, id="SYNSUB01", done=True)
    assert updated.goal.done_at is not None
    assert updated.open_descendants == 0


def test_update_done_true_bulk_reports_open_descendants_per_row(f2: psycopg.Connection) -> None:
    """The batched `open_descendants` readback (one `GROUP BY` statement for the whole bulk call,
    not one `COUNT` per id — S-44) must still attribute a *different* count to each row, not the
    same value or a cross-contaminated one. `SYNDAY01` (three open children) and `SYNCOL01` (a
    leaf, unrelated root) are deliberately from different, non-overlapping subtrees, so neither
    row's count can leak into the other's."""
    updated = goals.update(f2, owner=OWNER, ids=["SYNDAY01", "SYNCOL01"], done=True)
    by_id = {u.goal.id: u for u in updated}
    assert by_id["SYNDAY01"].open_descendants == 3
    assert by_id["SYNCOL01"].open_descendants == 0
    assert all(u.goal.done_at is not None for u in updated)


# --- S-29 — idempotent create: same client_token twice -----------------------------------------


def test_s29a_idempotent_create_same_token_twice_writes_once(f2: psycopg.Connection) -> None:
    dsn = maintenance_dsn()
    _require_stmt_counter(dsn)
    dbname = stmt.current_dbname(f2)

    first = goals.create(
        f2, owner=OWNER, title="Ship it", vertical="day", anchor_date=date(2026, 8, 8),
        client_token="ct-0001",
    )
    assert first.replayed is False, "a fresh write is never reported as a replay"
    assert _goal_count(f2) == 50

    stmt.reset(dsn, dbname)
    second = goals.create(
        f2, owner=OWNER, title="Ship it", vertical="day", anchor_date=date(2026, 8, 8),
        client_token="ct-0001",
    )
    log = stmt.read(dsn, dbname)

    assert second.goal.id == first.goal.id
    assert second.replayed is True, "the second call with the same token must self-report as a replay"
    assert _goal_count(f2) == 50, "SELECT count(*) is 50, not 51"
    goal_inserts = [text for text, calls in log if "insert into goals" in text.lower() and calls > 0]
    assert goal_inserts == [], f"replay executed an INSERT on goals: {goal_inserts}"


def test_s29b_changed_payload_same_token_conflicts(f2: psycopg.Connection) -> None:
    goals.create(
        f2, owner=OWNER, title="Ship it", vertical="day", anchor_date=date(2026, 8, 8),
        client_token="ct-0002",
    )
    before = _goal_count(f2)
    with pytest.raises(IdempotencyConflict):
        goals.create(
            f2, owner=OWNER, title="Ship it later", vertical="day", anchor_date=date(2026, 8, 8),
            client_token="ct-0002",
        )
    assert _goal_count(f2) == before, "writes nothing"


def test_s29c_same_token_and_payload_different_owner_creates_independently(f2: psycopg.Connection) -> None:
    """AC-198. The uniqueness key is `(owner, client_token)`, not `client_token` alone."""
    t1 = goals.create(
        f2, owner="t1", title="Ship it", vertical="day", anchor_date=date(2026, 8, 8),
        client_token="ct-shared",
    )
    t2 = goals.create(
        f2, owner="t2", title="Ship it", vertical="day", anchor_date=date(2026, 8, 8),
        client_token="ct-shared",
    )
    assert t1.goal.id != t2.goal.id
    assert t2.goal.owner == "t2"
    assert t1.replayed is False and t2.replayed is False, "two independent owners, two fresh writes"
    leaked = {t2.goal.id, *[c.id for c in t2.children]}
    assert t1.goal.id not in leaked, "t2 must not be able to read t1's id from its own response"


# --- S-30 — idempotency expires after 24 hours ---------------------------------------------------


def test_s30a_idempotency_expires_after_24_hours(f2: psycopg.Connection) -> None:
    first = goals.create(
        f2, owner=OWNER, title="Ship it", vertical="day", anchor_date=date(2026, 8, 8),
        client_token="ct-0003",
    )
    f2.execute(
        "UPDATE idempotency SET created_at = now() - interval '25 hours'"
        " WHERE owner = %s AND client_token = %s",
        (OWNER, "ct-0003"),
    )
    before = _goal_count(f2)

    second = goals.create(
        f2, owner=OWNER, title="Ship it", vertical="day", anchor_date=date(2026, 8, 8),
        client_token="ct-0003",
    )

    assert second.goal.id != first.goal.id, "a new id is returned"
    assert _goal_count(f2) == before + 1
    assert _idem_count(f2, OWNER) == 1, "the expired row is removed by the same call, not left behind"


def test_s30b_5000_stale_rows_swept_by_ten_creates(f2: psycopg.Connection) -> None:
    stale_owner = "t-bulk"
    n = 5000
    values_sql = ",".join(["(%s, %s, %s, %s, now() - interval '25 hours')"] * n)
    params: list[object] = []
    for i in range(n):
        params += [stale_owner, f"ct-stale-{i}", "0" * 64, Jsonb({"id": f"old-{i}"})]
    f2.execute(
        "INSERT INTO idempotency (owner, client_token, request_digest, response_json, created_at) "
        f"VALUES {values_sql}",
        params,
    )
    assert _idem_count(f2, stale_owner) == n

    for i in range(10):
        goals.create(f2, owner=stale_owner, title=f"live {i}", client_token=f"ct-live-{i}")

    assert _idem_count(f2, stale_owner) == 10, "back to the live-token count, not 5 010"
