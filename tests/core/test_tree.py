"""A direct probe of `verticals/core/tree.py` — WP-08 — against real Postgres 16 and the real F2
fixture. No mocks, no stubs, no fakes (`docs/BRIEF.md` rule 2).

**What this file is not.** S-06 through S-16 (`docs/E2E.md`) enter through `create`, `reparent`,
`move_between` and `delete` — the public verbs `core/goals.py` and `core/moves.py` expose at wave
3 (WP-13), which do not exist yet. This file cannot print `PASS S-14`, `PASS S-15` or `PASS S-16`
at all: those three test a `delete` verb, and `tree.py` has no delete — `attach`, `move`, `detach`
and `renumber` are the four primitives this work package owns, and none of them removes a row.
There is no `test_s14`/`test_s15`/`test_s16` here for that reason, not by oversight. The other
eight scenarios (S-06 through S-13, S-11) map onto `attach`/`move`/`detach`/`renumber` closely
enough to probe directly, and are named `test_s06_...` through `test_s13_...` below — but even
those are **not** the catalogue's own S-06..S-13: they drive the same mechanism the catalogue
scenario will drive once WP-13 wires the public verb on top, and they assert the same table of
values and the same statement shapes, but the runner will not attribute a pass here to the
catalogue until that verb exists. WP-05 and WP-10 were both accepted on exactly this basis.

Run standalone (the WP-13 surface that would make these the catalogue's own S-06..S-16 does not
exist yet):
    PGHOST=127.0.0.1 PGPORT=55432 PGUSER=verticals PGPASSWORD=verticals \
        .venv/bin/python -m pytest tests/core/test_tree.py -v -s
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date
from pathlib import Path

import psycopg
import pytest

from verticals.core import tree as T
from verticals.core.errors import CycleRefused, NotFound, ValidationError
from tests.conftest import maintenance_dsn
from tests.harness import stmt
from tests.harness.report import gate

F2_SQL = Path(__file__).resolve().parents[1] / "fixtures" / "f2_synth.sql"


@pytest.fixture
def f2(db: psycopg.Connection) -> Iterator[psycopg.Connection]:
    """F2 on a fresh clone — same idiom as `tests/core/test_search.py`'s own `f2` fixture."""
    db.execute(F2_SQL.read_text())
    db.execute("ANALYZE goals")
    yield db


# --- shared helpers -------------------------------------------------------------------------


def _dbname(conn: psycopg.Connection) -> str:
    return stmt.current_dbname(conn)


def _digest(conn: psycopg.Connection) -> str:
    """A full-table fingerprint — every column of every row, order-independent. S-09's "zero
    rows have a changed path, depth, parent_id or updated_at" is checked here at full strength:
    if *anything at all* changed, the digest changes."""
    (value,) = conn.execute(
        "SELECT md5(string_agg(goals::text, '|' ORDER BY id)) FROM goals"
    ).fetchone()
    return value


def _update_calls(log: list[tuple[str, int]]) -> int:
    """Sum of `calls` across every captured statement whose text is an `UPDATE` — never a
    `SELECT ... FOR UPDATE`'s locking clause, which contains the substring `UPDATE` too."""
    return sum(calls for text, calls in log if text.strip().upper().startswith("UPDATE"))


def _select_for_update_calls(log: list[tuple[str, int]]) -> int:
    return sum(calls for text, calls in log if "FOR UPDATE" in text.upper())


def _require_stmt_counter(dsn: str) -> None:
    """IR-06 / `tests/harness/stmt.py`'s own contract: a statement-count assertion that finds
    the extension unavailable reports GATE, never a silent pass or a hard failure unrelated to
    the thing being tested."""
    if not stmt.available(dsn):
        gate("pg_stat_statements unavailable — statement-count assertion cannot run")


# AC-203's tree invariant lives in `tests/harness/tree_invariant.py` — one implementation for
# the whole repo. It used to be defined here and hand-copied into `tests/http/test_concurrency.py`
# and `tests/pipeline/test_backup.py`; three copies of a criterion is three chances to drift.
# The same module is what `tests/conftest.py`'s `fresh_clone` runs in every clone's teardown,
# so these in-test assertions and the per-scenario gate can no longer disagree about what the
# invariant says.
from tests.harness.tree_invariant import violations as _tree_invariant_violations


# --- S-06, S-07 — attach ----------------------------------------------------------------------


def test_s06_root_insert_sets_path_and_depth(f2: psycopg.Connection) -> None:
    """AC-024. `create(title='root', vertical='day', anchor_date='2026-08-08')` — the `create`
    verb does not exist, so this drives `tree.attach` with the same effective arguments; the
    `period_key` `create` would derive via `core/vertical.py` is computed here by hand, since
    `attach` intentionally accepts it as an opaque already-derived value (module docstring)."""
    g = T.attach(
        f2, owner="t1", id="NEWROOT1", parent_id=None, title="root",
        vertical="day", anchor_date="2026-08-08", period_key="2026-08-08",
    )
    print("S-06 inserted row:", g)
    assert g is not None
    assert g.path == "/" + g.id + "/"
    assert g.depth == 0
    assert g.parent_id is None
    assert _tree_invariant_violations(f2, "t1") == []


def test_s07_child_insert_extends_parent_path(f2: psycopg.Connection) -> None:
    """AC-025. `create(parent_id='SYNQ2R01', title='child')`."""
    g = T.attach(f2, owner="t1", id="NEWCHLD1", parent_id="SYNQ2R01", title="child")
    print("S-07 inserted row:", g)
    assert g is not None
    assert g.path == "/SYNLIF01/SYNDEC01/SYNYRR01/SYNQ1R01/SYNQ2R01/" + g.id + "/"
    assert g.depth == 5
    assert len(g.path) == 6 * 9 + 1 == 55
    assert _tree_invariant_violations(f2, "t1") == []


def test_attach_notfound_when_parent_missing(f2: psycopg.Connection) -> None:
    with pytest.raises(NotFound) as exc:
        T.attach(f2, owner="t1", id="ORPHANED1", parent_id="DOESNOTEXIST", title="x")
    assert exc.value.detail["id"] == "DOESNOTEXIST"


def test_attach_id_collision_returns_none_not_an_exception(f2: psycopg.Connection) -> None:
    """IR-05: "a zero-row return means a collision; the generator retries" — the generator is
    `core/goals.py`'s, not built here; what this primitive owes that generator is a clean signal,
    not a crash and not a silently-overwritten row."""
    before = f2.execute("SELECT title, position FROM goals WHERE id = 'SYNORD01'").fetchone()
    result = T.attach(f2, owner="t1", id="SYNORD01", parent_id=None, title="hijack attempt")
    assert result is None
    after = f2.execute("SELECT title, position FROM goals WHERE id = 'SYNORD01'").fetchone()
    assert before == after, "a collided insert must not touch the existing row"


def test_attach_own_depth_bound(f2: psycopg.Connection) -> None:
    """IR-11 at `attach` itself, not only at `move` — a fresh child of a depth-32 node would be
    depth 33. Builds a 32-deep chain (depths 0..31) then confirms depth 32 (one more) is
    accepted and depth 33 refused, matching `test_ir11_depth_bound_refuses_33_accepts_32`'s own
    DB-level pinning of the same two numbers."""
    parent_id = None
    for i in range(32):
        g = T.attach(f2, owner="t1", id=f"CHAINDP{i:02d}", parent_id=parent_id, title=f"d{i}")
        assert g is not None
        parent_id = g.id
    deepest = f2.execute("SELECT depth FROM goals WHERE id = %s", (parent_id,)).fetchone()[0]
    assert deepest == 31

    ok = T.attach(f2, owner="t1", id="ATDEPTH32", parent_id=parent_id, title="at the bound")
    assert ok is not None and ok.depth == 32

    with pytest.raises(ValidationError) as exc:
        T.attach(f2, owner="t1", id="OVERDEPTH", parent_id="ATDEPTH32", title="one past")
    assert exc.value.detail["field"] == "depth"
    assert exc.value.detail["maximum"] == 32
    assert exc.value.detail["attempted"] == 33


# --- S-08, S-09 — the cycle guard -------------------------------------------------------------


def test_s08_reparent_onto_self_is_refused(f2: psycopg.Connection) -> None:
    """AC-026. `reparent('SYNQ1R01', 'SYNQ1R01')` — via `tree.move`."""
    before = f2.execute(
        "SELECT parent_id, updated_at FROM goals WHERE id = 'SYNQ1R01'"
    ).fetchone()
    with pytest.raises(CycleRefused) as exc:
        T.move(f2, owner="t1", id="SYNQ1R01", new_parent_id="SYNQ1R01")
    print("S-08 refusal detail:", exc.value.detail)
    assert exc.value.detail["reason"] == "self"
    after = f2.execute("SELECT parent_id, updated_at FROM goals WHERE id = 'SYNQ1R01'").fetchone()
    assert before == after
    assert f2.execute("SELECT count(*) FROM goals").fetchone()[0] == 49


def test_s09a_indirect_cycle_refused_inside_the_transaction(f2: psycopg.Connection) -> None:
    """AC-027 — trap 1, the one the WP-08 card calls out by name. `reparent('SYNLIF01',
    'SYNSUB01')`: `SYNLIF01` is the root of the 9-node G1 chain, `SYNSUB01` is six levels inside
    it. Verified from the connection's own statement log (§2 / IR-06): exactly one
    `SELECT ... FOR UPDATE` and zero `UPDATE` statements — not "the values end up right", the
    literal statement shape a check-then-write implementation cannot produce."""
    dsn = maintenance_dsn()
    _require_stmt_counter(dsn)
    dbname = _dbname(f2)

    digest_before = _digest(f2)
    stmt.reset(dsn, dbname)
    with pytest.raises(CycleRefused) as exc:
        T.move(f2, owner="t1", id="SYNLIF01", new_parent_id="SYNSUB01")
    log = stmt.read(dsn, dbname)

    print("S-09 refusal detail:", exc.value.detail)
    print("S-09 captured statement log:")
    for text, calls in log:
        print(f"    calls={calls}  {text.splitlines()[0][:100]!r}")

    assert exc.value.detail["reason"] == "target_is_descendant"
    assert _select_for_update_calls(log) == 1, log
    assert _update_calls(log) == 0, log

    digest_after = _digest(f2)
    assert digest_before == digest_after, "full-table digest changed on a refused cycle"
    assert f2.execute("SELECT count(*) FROM goals").fetchone()[0] == 49


def test_s09b_new_parent_in_a_different_owner_is_notfound_not_a_cycle_check(
    f2: psycopg.Connection,
) -> None:
    """Owner scoping holds even inside the guard: `SYNOTH01` is `t2`'s, invisible to a `t1`
    lookup, so the correct refusal is `NotFound`, not a cycle verdict computed against a row
    `t1` was never allowed to see."""
    with pytest.raises(NotFound) as exc:
        T.move(f2, owner="t1", id="SYNQ1R01", new_parent_id="SYNOTH01")
    assert exc.value.detail["id"] == "SYNOTH01"


# --- S-10 — the one dangerous write ------------------------------------------------------------


def test_s10_reparent_across_verticals_rewrites_whole_subtree_in_one_update(
    f2: psycopg.Connection,
) -> None:
    """AC-028 — trap 2. `reparent('SYNQ1R01', 'SYNDEC01')`. Asserts the exact depth/path table
    row for row, that `vertical`/`period_key` are untouched on all six, that the unrelated
    `SYNYRR01` is unaffected, and that the rewrite is exactly one `UPDATE` (execute-counter delta
    1 — the statement, not merely its logical effect)."""
    dsn = maintenance_dsn()
    _require_stmt_counter(dsn)
    dbname = _dbname(f2)

    before = {
        r[0]: r[1]
        for r in f2.execute(
            "SELECT id, depth FROM goals WHERE id IN "
            "('SYNQ1R01','SYNQ2R01','SYNDAY01','SYNSUB01','SYNSUB02','SYNSUB03')"
        ).fetchall()
    }
    assert before == {
        "SYNQ1R01": 3, "SYNQ2R01": 4, "SYNDAY01": 5, "SYNSUB01": 6, "SYNSUB02": 6, "SYNSUB03": 6,
    }

    stmt.reset(dsn, dbname)
    rewritten = T.move(f2, owner="t1", id="SYNQ1R01", new_parent_id="SYNDEC01")
    log = stmt.read(dsn, dbname)

    print("S-10 rewritten rows:")
    for r in sorted(rewritten, key=lambda r: r.id):
        print(" ", r)
    print("S-10 captured statement log:")
    for text, calls in log:
        print(f"    calls={calls}  {text.splitlines()[0][:100]!r}")

    by_id = {r.id: r for r in rewritten}
    expect = {
        "SYNQ1R01": (2, "/SYNLIF01/SYNDEC01/SYNQ1R01/"),
        "SYNQ2R01": (3, "/SYNLIF01/SYNDEC01/SYNQ1R01/SYNQ2R01/"),
        "SYNDAY01": (4, "/SYNLIF01/SYNDEC01/SYNQ1R01/SYNQ2R01/SYNDAY01/"),
        "SYNSUB01": (5, "/SYNLIF01/SYNDEC01/SYNQ1R01/SYNQ2R01/SYNDAY01/SYNSUB01/"),
        "SYNSUB02": (5, "/SYNLIF01/SYNDEC01/SYNQ1R01/SYNQ2R01/SYNDAY01/SYNSUB02/"),
        "SYNSUB03": (5, "/SYNLIF01/SYNDEC01/SYNQ1R01/SYNQ2R01/SYNDAY01/SYNSUB03/"),
    }
    assert set(by_id) == set(expect)
    for gid, (depth, path) in expect.items():
        assert by_id[gid].depth == depth, gid
        assert by_id[gid].path == path, gid

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
    assert _tree_invariant_violations(f2, "t1") == []


def test_s10b_move_refused_past_depth_32_checks_the_deepest_descendant(
    f2: psycopg.Connection,
) -> None:
    """IR-11 via `move`, and specifically the case a shallower check would miss: the moved node
    itself could land within bounds while a descendant six levels below it does not. Builds a
    31-deep chain, then moves `SYNDAY01` (which still carries its three `SYNSUB0x` children,
    themselves one level deeper) onto the chain's tail — `SYNDAY01` would land at depth 32
    (legal on its own) but `SYNSUB0x` would land at depth 33 (not)."""
    dsn = maintenance_dsn()
    _require_stmt_counter(dsn)
    dbname = _dbname(f2)

    parent_id = None
    for i in range(32):
        g = T.attach(
            f2,
            owner="t1",
            id=f"DCHAIN{i:02d}",
            parent_id=parent_id,
            title=f"d{i}",
            vertical="life",
            anchor_date=date(2026, 1, 1),
            period_key="life",
        )
        parent_id = g.id
    deepest_id = parent_id
    assert f2.execute("SELECT depth FROM goals WHERE id = %s", (deepest_id,)).fetchone()[0] == 31

    digest_before = _digest(f2)
    stmt.reset(dsn, dbname)
    with pytest.raises(ValidationError) as exc:
        T.move(f2, owner="t1", id="SYNDAY01", new_parent_id=deepest_id)
    log = stmt.read(dsn, dbname)

    print("IR-11/move refusal detail:", exc.value.detail)
    assert exc.value.detail["field"] == "depth"
    assert exc.value.detail["maximum"] == 32
    assert exc.value.detail["attempted"] == 33
    assert _update_calls(log) == 0, log
    assert _digest(f2) == digest_before


# --- S-11 — detach ------------------------------------------------------------------------------


def test_s11_reparent_to_null_detaches_to_root(f2: psycopg.Connection) -> None:
    """AC-029. `reparent('SYNDAY01', None)` — via `tree.detach`."""
    rewritten = T.detach(f2, owner="t1", id="SYNDAY01")
    by_id = {r.id: r for r in rewritten}
    print("S-11 rewritten rows:", rewritten)

    assert by_id["SYNDAY01"].path == "/SYNDAY01/" and by_id["SYNDAY01"].depth == 0
    assert by_id["SYNSUB01"].path == "/SYNDAY01/SYNSUB01/" and by_id["SYNSUB01"].depth == 1

    vertical, done_at = f2.execute(
        "SELECT vertical, done_at FROM goals WHERE id = 'SYNDAY01'"
    ).fetchone()
    assert vertical == "day", "detaching must not clear vertical — SYNDAY01 stays a card"

    maybe_count = f2.execute(
        "SELECT count(*) FROM goals"
        " WHERE owner = 't1' AND vertical IS NULL AND parent_id IS NULL AND done_at IS NULL"
    ).fetchone()[0]
    assert maybe_count == 5, "Maybe must still hold exactly its original 5 open rows"
    assert _tree_invariant_violations(f2, "t1") == []


def test_edge_deepest_node_to_root_and_back(f2: psycopg.Connection) -> None:
    """`docs/IMPLEMENTATION.md:1329`: "move the deepest node to the root and back". `SYNSUB01`
    is F2's deepest row (depth 6). Detach it to root, then move it back under its original
    parent, and confirm the round trip restores its exact original path/depth/parent_id — not
    merely "some" consistent state."""
    original = f2.execute(
        "SELECT parent_id, path, depth FROM goals WHERE id = 'SYNSUB01'"
    ).fetchone()
    assert original == ("SYNDAY01", "/SYNLIF01/SYNDEC01/SYNYRR01/SYNQ1R01/SYNQ2R01/SYNDAY01/SYNSUB01/", 6)

    detached = T.detach(f2, owner="t1", id="SYNSUB01")
    assert detached == (T.RewrittenRow(id="SYNSUB01", path="/SYNSUB01/", depth=0),)

    restored = T.move(f2, owner="t1", id="SYNSUB01", new_parent_id="SYNDAY01")
    assert restored == (
        T.RewrittenRow(
            id="SYNSUB01",
            path="/SYNLIF01/SYNDEC01/SYNYRR01/SYNQ1R01/SYNQ2R01/SYNDAY01/SYNSUB01/",
            depth=6,
        ),
    )
    final = f2.execute("SELECT parent_id, path, depth FROM goals WHERE id = 'SYNSUB01'").fetchone()
    assert final == original, "round trip must restore the exact original row, not merely a valid one"
    assert _tree_invariant_violations(f2, "t1") == []


def test_edge_move_to_descendant_of_a_sibling_subtree_is_not_a_false_cycle(
    f2: psycopg.Connection,
) -> None:
    """`docs/IMPLEMENTATION.md:1329`: a move into a *sibling* subtree is not a cycle and must
    not be refused as one — the guard checks whether the new parent descends from the node being
    moved, not whether the two happen to share a common ancestor. `SYNDEC01` and a freshly
    attached `SYNDEC02` both hang directly off `SYNLIF01`; moving `SYNYRR01` (currently under
    `SYNDEC01`) to be a child of `SYNDEC02` must succeed."""
    sibling = T.attach(
        f2,
        owner="t1",
        id="SYNDEC02X",
        parent_id="SYNLIF01",
        title="sibling branch",
        vertical="life",
        anchor_date=date(2026, 1, 1),
        period_key="life",
    )
    assert sibling is not None and sibling.depth == 1

    rewritten = T.move(f2, owner="t1", id="SYNYRR01", new_parent_id="SYNDEC02X")
    by_id = {r.id: r for r in rewritten}
    print("sibling-subtree move, rewritten:", rewritten)

    assert by_id["SYNYRR01"].path == "/SYNLIF01/SYNDEC02X/SYNYRR01/"
    assert by_id["SYNYRR01"].depth == 2
    # SYNQ1R01/SYNQ2R01/SYNDAY01/SYNSUB0{1,2,3} all ride along underneath it.
    assert len(rewritten) == 7
    assert _tree_invariant_violations(f2, "t1") == []


def test_edge_like_prefix_does_not_match_an_unrelated_id_substring(
    f2: psycopg.Connection,
) -> None:
    """`docs/IMPLEMENTATION.md:1329`: "check whether the prefix UPDATE can match a path that
    merely starts with the same id prefix". `AAAAAAAA` and the lookalike root `AAAAAAAB` differ
    in their last character only; moving `AAAAAAAA` under `BBBBBBBB` must touch `AAAAAAAA` and
    nothing whose id merely shares a prefix with it — the match is anchored on the whole `/id/`
    segment, not a bare substring."""
    T.attach(f2, owner="t1", id="AAAAAAAA", parent_id=None, title="a")
    T.attach(f2, owner="t1", id="BBBBBBBB", parent_id=None, title="b")
    T.attach(f2, owner="t1", id="AAAAAAAB", parent_id=None, title="lookalike root")

    rewritten = T.move(f2, owner="t1", id="AAAAAAAA", new_parent_id="BBBBBBBB")
    assert {r.id for r in rewritten} == {"AAAAAAAA"}

    lookalike_path = f2.execute("SELECT path FROM goals WHERE id = 'AAAAAAAB'").fetchone()[0]
    assert lookalike_path == "/AAAAAAAB/", "an unrelated row sharing a 7-character prefix must be untouched"


def test_edge_two_connections_overlapping_subtree_writes_serialise_not_corrupt(
    f2: psycopg.Connection, db_dsn: str
) -> None:
    """`docs/IMPLEMENTATION.md:1330`'s spirit, read for what a single `core/tree.py` primitive
    can actually promise. A second, real connection opens a transaction and takes
    `SELECT ... FOR UPDATE` on `SYNSUB01` — deep inside the same subtree `move` below is about to
    rewrite — and holds it open without committing, standing in for "another connection is
    mid-write on a row this rewrite would touch". The test connection sets a short
    `lock_timeout` and calls `tree.move` to reparent `SYNQ1R01` (`SYNSUB01`'s ancestor); `move`'s
    own guard performs `SELECT ... FOR UPDATE` over `{id, new_parent_id}`, which does not name
    `SYNSUB01` directly — so this specifically exercises `_rewrite_subtree`'s `UPDATE`, whose
    `WHERE path LIKE ...` matches `SYNSUB01` too, and which Postgres will not let proceed while
    another transaction holds a lock on that row. Translating the resulting timeout into the
    closed taxonomy's `LockNotAvailable` is the transport's job (`core/errors.py`: "before the
    transport's own timeout") — `core/tree.py` does not set `lock_timeout` itself, so this test
    catches the driver's own `psycopg.errors.LockNotAvailable` directly, confirming Postgres
    itself refuses to let the two writes interleave rather than asserting anything `tree.py` does
    about it.
    """
    blocker = psycopg.connect(db_dsn, autocommit=False)
    try:
        blocker.execute("SELECT 1 FROM goals WHERE id = 'SYNSUB01' FOR UPDATE")

        f2.execute("SET lock_timeout = '250ms'")
        digest_before = _digest(f2)
        with pytest.raises(psycopg.errors.LockNotAvailable):
            T.move(f2, owner="t1", id="SYNQ1R01", new_parent_id="SYNDEC01")
        # `move`'s own `with conn.transaction()` rolls back on the raised error — `f2` must
        # still be usable for the next statement, and nothing must have been written.
        assert _digest(f2) == digest_before
        assert f2.execute("SELECT count(*) FROM goals").fetchone()[0] == 49
    finally:
        blocker.rollback()
        blocker.close()

    # With the blocking lock released, the identical move now succeeds cleanly.
    f2.execute("SET lock_timeout = DEFAULT")
    rewritten = T.move(f2, owner="t1", id="SYNQ1R01", new_parent_id="SYNDEC01")
    assert {r.id for r in rewritten} == {
        "SYNQ1R01", "SYNQ2R01", "SYNDAY01", "SYNSUB01", "SYNSUB02", "SYNSUB03",
    }
    assert _tree_invariant_violations(f2, "t1") == []


# --- S-12, S-13 — gap ordering and renumber -----------------------------------------------------


def test_s12_gap_ordering_assigns_1024_multiples_and_midpoints(f2: psycopg.Connection) -> None:
    """AC-018. Steps: 1. read positions in week `2026-W32`. 2. `create` at the column tail (via
    `tree.renumber` with neither `after_id` nor `before_id`). 3. `move_between SYNORD01` and
    `SYNORD02` (via `tree.renumber` with both)."""
    initial = f2.execute(
        "SELECT id, position FROM goals"
        " WHERE owner = 't1' AND vertical = 'week' AND period_key = '2026-W32'"
        " ORDER BY position"
    ).fetchall()
    print("S-12 initial column:", initial)
    assert [p for _, p in initial] == [1024, 2048, 3072, 4096]

    tail = T.renumber(f2, owner="t1", vertical="week", period_key="2026-W32", parent_id=None)
    print("S-12 tail position:", tail)
    assert tail == 5120

    mid = T.renumber(
        f2, owner="t1", vertical="week", period_key="2026-W32", parent_id=None,
        after_id="SYNORD01", before_id="SYNORD02",
    )
    print("S-12 midpoint position:", mid)
    assert mid == 1536

    (data_type,) = f2.execute(
        "SELECT data_type FROM information_schema.columns"
        " WHERE table_name = 'goals' AND column_name = 'position'"
    ).fetchone()
    assert data_type == "integer", data_type


def test_s13_gap_exhaustion_triggers_renumber_that_preserves_order(f2: psycopg.Connection) -> None:
    """AC-019 — trap 3. Insert repeatedly between `SYNORD01` and whatever the last inserted row
    was ("always at the head gap"), until the operation renumbers. Position is what `renumber`
    returns; each value is then written onto a real row via `tree.attach` (not a bare `UPDATE`
    the test writes itself) so the *next* `renumber` call reads real, persisted state — the same
    round trip `move_between` would drive in production."""
    dsn = maintenance_dsn()
    _require_stmt_counter(dsn)
    dbname = _dbname(f2)

    before_id = "SYNORD02"
    sequence: list[int] = []
    for i in range(10):
        pos = T.renumber(
            f2, owner="t1", vertical="week", period_key="2026-W32", parent_id=None,
            after_id="SYNORD01", before_id=before_id,
        )
        sequence.append(pos)
        new_id = f"SYNMIDPT{i}"
        g = T.attach(
            f2, owner="t1", id=new_id, parent_id=None, title=f"midpoint {i}",
            vertical="week", anchor_date="2026-08-05", period_key="2026-W32", position=pos,
        )
        assert g is not None
        before_id = new_id

    print("S-13 first ten inserts:", sequence)
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
    eleventh = T.renumber(
        f2, owner="t1", vertical="week", period_key="2026-W32", parent_id=None,
        after_id="SYNORD01", before_id=before_id,
    )
    log = stmt.read(dsn, dbname)
    print("S-13 eleventh (post-renumber) position:", eleventh)
    print("S-13 captured statement log for the renumber:")
    for text, calls in log:
        print(f"    calls={calls}  {text.splitlines()[0][:100]!r}")

    assert eleventh == 1536

    updates = [(text, calls) for text, calls in log if text.strip().upper().startswith("UPDATE")]
    assert len(updates) == 1, updates
    assert "VALUES" in updates[0][0].upper()
    assert updates[0][1] == 1, "the renumber statement must run exactly once, not fourteen times"

    after_renumber = f2.execute(
        "SELECT id, position FROM goals"
        " WHERE owner = 't1' AND vertical = 'week' AND period_key = '2026-W32'"
        " ORDER BY position, id"
    ).fetchall()
    print("S-13 positions after renumber:", after_renumber)
    assert [gid for gid, _ in after_renumber] == order_before_renumber, "relative order must survive"
    assert [pos for _, pos in after_renumber] == [1024 * (i + 1) for i in range(14)]

    g = T.attach(
        f2, owner="t1", id="SYNELEVEN", parent_id=None, title="eleventh",
        vertical="week", anchor_date="2026-08-05", period_key="2026-W32", position=eleventh,
    )
    assert g is not None
    final_positions = [
        p
        for (p,) in f2.execute(
            "SELECT position FROM goals"
            " WHERE owner = 't1' AND vertical = 'week' AND period_key = '2026-W32'"
            " ORDER BY position"
        ).fetchall()
    ]
    print("S-13 final 15 positions:", final_positions)
    assert len(final_positions) == 15
    assert len(set(final_positions)) == 15, "all fifteen positions must be distinct"
    assert final_positions == sorted(final_positions), "all fifteen positions must be strictly ascending"


def test_renumber_after_id_xor_before_id_is_refused(f2: psycopg.Connection) -> None:
    with pytest.raises(ValidationError) as exc:
        T.renumber(
            f2, owner="t1", vertical="week", period_key="2026-W32", parent_id=None,
            after_id="SYNORD01", before_id=None,
        )
    assert exc.value.detail["field"] == "after_id,before_id"


def test_renumber_scope_subgoal_siblings_independent_from_maybe_pile(f2: psycopg.Connection) -> None:
    """The decision this module's docstring documents and defends: a subgoal's sibling group is
    `(owner, parent_id)`, not the bare `(owner, vertical=NULL, period_key=NULL)` F2's own Maybe
    pile also matches — the two groups' positions are independent and may legitimately share
    values (F2 already does: `SYNMAY01`/`SYNSUB01` both sit at 1024)."""
    subgoal_tail = T.renumber(f2, owner="t1", vertical=None, period_key=None, parent_id="SYNDAY01")
    assert subgoal_tail == 4096  # one past SYNSUB03's 3072

    maybe_tail = T.renumber(f2, owner="t1", vertical=None, period_key=None, parent_id=None)
    assert maybe_tail == 7168  # one past SYNMAY06's 6144

    assert subgoal_tail != maybe_tail
    # F2's own SYNMAY01/SYNSUB01 pair (both 1024) proves the two groups already coexist without
    # collision in the shipped fixture — this is not a hypothetical.
    already_shared = f2.execute(
        "SELECT id, parent_id, vertical, position FROM goals"
        " WHERE owner = 't1' AND id IN ('SYNMAY01', 'SYNSUB01')"
        " ORDER BY id"
    ).fetchall()
    assert already_shared == [
        ("SYNMAY01", None, None, 1024),
        ("SYNSUB01", "SYNDAY01", None, 1024),
    ]


def test_renumber_notfound_when_after_or_before_id_missing(f2: psycopg.Connection) -> None:
    with pytest.raises(NotFound) as exc:
        T.renumber(
            f2, owner="t1", vertical="week", period_key="2026-W32", parent_id=None,
            after_id="SYNORD01", before_id="DOESNOTEXIST",
        )
    assert exc.value.detail["id"] == "DOESNOTEXIST"


# --- AC-203 — the tree invariant, swept once more across everything above -----------------------


def test_ac203_tree_invariant_holds_after_a_mixed_sequence_of_mutations(
    f2: psycopg.Connection,
) -> None:
    """Not one of S-06..S-16: AC-203 in its own right, one of the criteria the WP-08 card lists
    as satisfied. Runs a mixed sequence — attach, move, detach, a renumber-triggering burst —
    on one connection and sweeps the invariant after each step, the way the real teardown hook
    (S-126, wired in by a later work package) would after every mutating scenario."""
    assert _tree_invariant_violations(f2, "t1") == []

    T.attach(f2, owner="t1", id="MIXSEQ01", parent_id="SYNQ2R01", title="mix 1")
    assert _tree_invariant_violations(f2, "t1") == []

    T.move(f2, owner="t1", id="SYNQ1R01", new_parent_id="SYNDEC01")
    assert _tree_invariant_violations(f2, "t1") == []

    T.detach(f2, owner="t1", id="SYNDAY01")
    assert _tree_invariant_violations(f2, "t1") == []

    before_id = "SYNORD02"
    for i in range(11):
        pos = T.renumber(
            f2, owner="t1", vertical="week", period_key="2026-W32", parent_id=None,
            after_id="SYNORD01", before_id=before_id,
        )
        new_id = f"MIXORD{i:02d}"
        T.attach(
            f2, owner="t1", id=new_id, parent_id=None, title="mix ord",
            vertical="week", anchor_date="2026-08-05", period_key="2026-W32", position=pos,
        )
        before_id = new_id
    assert _tree_invariant_violations(f2, "t1") == []


# --- renumber: the head insert (`before_id` alone) ----------------------------------------------
#
# `docs/PENDING_DOC_FIXES.md` rows 109 and 116(c). Two branches, both exercised below: the ordinary
# one, where half the head's own position is free by construction, and the exhausted one, where it
# is not and the whole group is renumbered exactly as the midpoint branch already does.


def test_renumber_before_id_alone_inserts_at_the_head(f2: psycopg.Connection) -> None:
    """G2's head sits at 1024, so the slot below it is 512 — strictly below the head, above
    nothing, and free without moving any existing row."""
    before = dict(
        f2.execute(
            "SELECT id, position FROM goals WHERE owner='t1' AND vertical='week'"
            " AND period_key='2026-W32'"
        ).fetchall()
    )
    pos = T.renumber(
        f2, owner="t1", vertical="week", period_key="2026-W32", parent_id=None,
        before_id="SYNORD01",
    )
    assert pos == 512
    assert pos < min(before.values())
    after = dict(
        f2.execute(
            "SELECT id, position FROM goals WHERE owner='t1' AND vertical='week'"
            " AND period_key='2026-W32'"
        ).fetchall()
    )
    assert after == before, "allocating a head position must not move an existing row"


def test_renumber_before_id_alone_renumbers_when_the_head_gap_is_exhausted(
    f2: psycopg.Connection,
) -> None:
    """The head-side form of trap 3. Drive the head down to position 1 — no integer left below it
    — and the group renumbers to strict 1024-multiples, exactly as the midpoint branch does, after
    which the returned position is again strictly below the new head and free."""
    f2.execute(
        "UPDATE goals SET position = 1 WHERE owner='t1' AND id='SYNORD01'"
    )
    pos = T.renumber(
        f2, owner="t1", vertical="week", period_key="2026-W32", parent_id=None,
        before_id="SYNORD01",
    )
    after = dict(
        f2.execute(
            "SELECT id, position FROM goals WHERE owner='t1' AND vertical='week'"
            " AND period_key='2026-W32' ORDER BY position"
        ).fetchall()
    )
    assert after["SYNORD01"] == 1024, f"the group must have been renumbered: {after}"
    assert pos == 512
    assert pos < min(after.values())
    assert sorted(after.values()) == [1024, 2048, 3072, 4096], after
