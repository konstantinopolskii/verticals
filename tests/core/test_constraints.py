"""S-05 — the database is the last line, not the first. Real Postgres, no mocks.

Also covers the two other facts WP-03's own card names as done-when, alongside S-05: IR-11's
bounds (`depth <= 32`, `cardinality(tags) <= 32`) refuse at the CHECK-constraint layer, and the
catalogue reports four tables (goal_evidence since 007/WP-33) and enums of 7 and 3 labels. The last of those already has a
proof in test_migrations.py's S-01 (`test_s01_migrations_apply_from_zero_to_head`); it is
repeated here in miniature so this file stands on its own, the same reasoning test_migrations.py
and test_schema_parity.py both give for not sharing fixtures before WP-06's harness exists.

Also covers 004_path_format.sql's `path_well_formed`, added after S-05/IR-11 landed: same idiom,
same file, one more CHECK. `tests/core/test_board.py` covers the *reason* this constraint exists
(it makes `core/board.py`'s successor-bound predicate sound); this file covers only the
constraint's own mechanics — which shapes it refuses, which it admits — same split as every
other constraint above.

Self-contained on purpose, same idiom as tests/core/test_migrations.py: creates and drops its
own scratch databases via the `postgres` admin database, using PGHOST/PGPORT/PGUSER/PGPASSWORD.

Run directly (today, standalone):
    docker compose -f docker-compose.test.yml up -d --wait
    PGHOST=127.0.0.1 PGPORT=55432 PGUSER=verticals PGPASSWORD=verticals \
        pytest tests/core/test_constraints.py -v
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterator
from pathlib import Path

import psycopg
import pytest

from verticals.db import runner

F2_SQL = Path(__file__).parent.parent / "fixtures" / "f2_synth.sql"


def _admin_dsn(dbname: str = "postgres") -> str:
    host = os.environ.get("PGHOST", "127.0.0.1")
    port = os.environ.get("PGPORT", "55432")
    user = os.environ.get("PGUSER", "verticals")
    password = os.environ.get("PGPASSWORD", "verticals")
    return f"postgresql://{user}:{password}@{host}:{port}/{dbname}"


@pytest.fixture
def fresh_db() -> Iterator[str]:
    """F0, migrated to head: a bare `goals`/`idempotency`/`schema_version`, zero rows."""
    name = f"verticals_t_wp03_{uuid.uuid4().hex[:16]}"
    with psycopg.connect(_admin_dsn(), autocommit=True) as admin:
        admin.execute(f'CREATE DATABASE "{name}"')
    try:
        dsn = _admin_dsn(name)
        applied = runner.run_up(dsn)
        assert applied > 0
        yield dsn
    finally:
        with psycopg.connect(_admin_dsn(), autocommit=True) as admin:
            admin.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')


@pytest.fixture
def f2_db(fresh_db: str) -> str:
    """F2 loaded on top of a fresh migration: 49 literal rows, ids fixed (E2E.md §2)."""
    sql = F2_SQL.read_text()
    with psycopg.connect(fresh_db, autocommit=True) as conn:
        conn.execute(sql)
    return fresh_db


def _row_count(dsn: str) -> int:
    with psycopg.connect(dsn, autocommit=True) as conn, conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM goals")
        (n,) = cur.fetchone()
        return n


def _expect_check_violation(conn: psycopg.Connection, sql: str, constraint: str) -> None:
    """Run `sql` inside its own savepoint (via conn.transaction()); assert it raises
    CheckViolation naming `constraint`, and that the savepoint rollback leaves `conn` usable
    for the next statement — this is what lets four attempts share one connection and one
    final `SELECT count(*)`, matching S-05's "attempt four raw inserts ... SELECT count(*)
    unchanged" as one sequence rather than four isolated databases."""
    with pytest.raises(psycopg.errors.CheckViolation) as excinfo:
        with conn.transaction():
            conn.execute(sql)
    assert excinfo.value.diag.constraint_name == constraint, (
        f"expected {constraint!r}, got {excinfo.value.diag.constraint_name!r}"
    )


def test_s05_check_constraints_refuse_contradictory_rows(f2_db: str) -> None:
    """S-05 — four raw inserts, each bypassing core/, each violating exactly one CHECK.

    Fixture: F2 (49 rows) already loaded by the `f2_db` fixture. Steps: (a) vertical='week',
    period_key=NULL; (b) vertical=NULL, period_key='2026-W32'; (c) vertical='week',
    anchor_date=NULL; (d) color='#ff0000'. Each row supplies every other column cleanly so
    only the named constraint is the one that fires — e.g. (c) still sets period_key, so it
    cannot also trip vertical_period_together and leave which constraint fired ambiguous.
    Assert: four CheckViolations naming vertical_period_together (twice), vertical_needs_anchor,
    color_is_canon; `SELECT count(*)` unchanged at 49.
    """
    with psycopg.connect(f2_db, autocommit=True) as conn:
        assert _row_count(f2_db) == 49

        _expect_check_violation(
            conn,
            "INSERT INTO goals (id, owner, path, vertical, anchor_date, period_key, title) "
            "VALUES ('BADROWA1', 't1', '/BADROWA1/', 'week', '2026-08-08', NULL, 'bad row a')",
            "vertical_period_together",
        )
        _expect_check_violation(
            conn,
            "INSERT INTO goals (id, owner, path, vertical, anchor_date, period_key, "
            "parked_from_vertical, title) VALUES "
            "('BADROWB1', 't1', '/BADROWB1/', NULL, NULL, '2026-W32', 'life', 'bad row b')",
            "vertical_period_together",
        )
        _expect_check_violation(
            conn,
            "INSERT INTO goals (id, owner, path, vertical, anchor_date, period_key, title) "
            "VALUES ('BADROWC1', 't1', '/BADROWC1/', 'week', NULL, '2026-W32', 'bad row c')",
            "vertical_needs_anchor",
        )
        _expect_check_violation(
            conn,
            "INSERT INTO goals (id, owner, path, color, parked_from_vertical, title) "
            "VALUES ('BADROWD1', 't1', '/BADROWD1/', '#ff0000', 'life', 'bad row d')",
            "color_is_canon",
        )

        assert _row_count(f2_db) == 49, "a refused insert must not leave a row behind"


def test_ir11_depth_bound_refuses_33_accepts_32(fresh_db: str) -> None:
    """IR-11 — `depth <= 32` is a CHECK, not just an application-level ValidationError.

    The pre-write ValidationError in core/tree.py and core/goals.py is WP-13's surface; this
    is the constraint underneath it, proven directly so a bypass of core/ still cannot exceed
    the bound the whole tree design assumes (docs/IMPLEMENTATION.md §0.3 IR-11).
    """
    with psycopg.connect(fresh_db, autocommit=True) as conn:
        conn.execute(
            "INSERT INTO goals (id, owner, path, depth, parked_from_vertical, title) "
            "VALUES ('DEPTHOK1', 't1', '/DEPTHOK1/', 32, 'life', 'at the bound')"
        )
        _expect_check_violation(
            conn,
            "INSERT INTO goals (id, owner, path, depth, parked_from_vertical, title) "
            "VALUES ('DEPTHBAD', 't1', '/DEPTHBAD/', 33, 'life', 'one past the bound')",
            "depth_bounded",
        )


def test_ir11_tags_bound_refuses_33_accepts_32(fresh_db: str) -> None:
    """IR-11 — `cardinality(tags) <= 32` is a CHECK, same reasoning as the depth bound."""
    tags_32 = "ARRAY[" + ",".join(f"'t{i}'" for i in range(32)) + "]"
    tags_33 = "ARRAY[" + ",".join(f"'t{i}'" for i in range(33)) + "]"
    with psycopg.connect(fresh_db, autocommit=True) as conn:
        conn.execute(
            f"INSERT INTO goals (id, owner, path, tags, parked_from_vertical, title) "
            f"VALUES ('TAGSOK01', 't1', '/TAGSOK01/', {tags_32}, 'life', 'at the bound')"
        )
        _expect_check_violation(
            conn,
            f"INSERT INTO goals (id, owner, path, tags, parked_from_vertical, title) "
            f"VALUES ('TAGSBAD1', 't1', '/TAGSBAD1/', {tags_33}, 'life', 'one past the bound')",
            "tags_bounded",
        )


def test_path_well_formed_fires_on_bad_shapes_and_stays_silent_on_good_ones(fresh_db: str) -> None:
    """004_path_format.sql's `path_well_formed` — `CHECK (path LIKE '/%/' AND path NOT LIKE
    '%//%')`. Not an E2E.md scenario id: this constraint postdates S-05/IR-11, added to make
    `core/tree.py`'s own writing convention ("every path ends in exactly one '/'") a database
    fact rather than a convention — see `core/board.py`'s `prog` LATERAL comment and
    `test_board.py`'s `test_path_well_formed_constraint_exists_and_blocks_the_shape_the_bound_
    assumes_away` for why that matters.

    Four bad shapes, each raw-inserted, each expected to refuse naming `path_well_formed`: no
    leading slash, no trailing slash, the empty string, an embedded '//'. Then two good shapes —
    `core/tree.py`'s own two path forms, root `/{id}/` and nested `/{parent}{id}/` — each
    expected to insert with no exception and the path stored byte-for-byte as given.
    """
    with psycopg.connect(fresh_db, autocommit=True) as conn:
        _expect_check_violation(
            conn,
            "INSERT INTO goals (id, owner, path, parked_from_vertical, title) "
            "VALUES ('BADPATH1', 't1', 'BADPATH1/', 'life', 'no leading slash')",
            "path_well_formed",
        )
        _expect_check_violation(
            conn,
            "INSERT INTO goals (id, owner, path, parked_from_vertical, title) "
            "VALUES ('BADPATH2', 't1', '/BADPATH2', 'life', 'no trailing slash')",
            "path_well_formed",
        )
        _expect_check_violation(
            conn,
            "INSERT INTO goals (id, owner, path, parked_from_vertical, title) "
            "VALUES ('BADPATH3', 't1', '', 'life', 'empty string')",
            "path_well_formed",
        )
        _expect_check_violation(
            conn,
            "INSERT INTO goals (id, owner, path, parked_from_vertical, title) "
            "VALUES ('BADPATH4', 't1', '/BAD//PATH4/', 'life', 'embedded double slash')",
            "path_well_formed",
        )
        assert _row_count(fresh_db) == 0, "no bad-shape insert may leave a row behind"

        conn.execute(
            "INSERT INTO goals (id, owner, parent_id, path, parked_from_vertical, title) "
            "VALUES ('GOODROOT1', 't1', NULL, '/GOODROOT1/', 'life', 'root goal')"
        )
        conn.execute(
            "INSERT INTO goals (id, owner, parent_id, path, parked_from_vertical, title) "
            "VALUES ('GOODKID01', 't1', 'GOODROOT1', '/GOODROOT1/GOODKID01/', 'life', 'nested goal')"
        )
        rows = dict(conn.execute("SELECT id, path FROM goals ORDER BY id").fetchall())
        assert rows == {
            "GOODROOT1": "/GOODROOT1/",
            "GOODKID01": "/GOODROOT1/GOODKID01/",
        }, "good shapes must insert unmodified, no exception raised"


def test_catalogue_five_tables_and_enum_labels(fresh_db: str) -> None:
    """WP-03's own done-when, updated by WP-33, D250/WP-1, WP-A (`015_comments.sql`) and the
    roll (`016_replan.sql`): "the catalogue reports twelve tables and enums of 7 and 4 labels."
    Mirrors test_migrations.py's S-01 assertion so this file's own claim to be done does not
    depend on another suite file staying green.
    """
    with psycopg.connect(fresh_db, autocommit=True) as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT count(*) FROM information_schema.tables WHERE table_schema = 'public'"
        )
        (table_count,) = cur.fetchone()
        assert table_count == 12, (
            "expected goals, schema_version, idempotency, goal_evidence, tag_meta, "
            "due_acknowledgements, docs, doc_revisions, goal_doc_links, comment_threads, "
            "comment_messages, carryover_runs"
        )

        cur.execute(
            """
            SELECT t.typname, count(e.enumlabel)
              FROM pg_type t JOIN pg_enum e ON e.enumtypid = t.oid
             WHERE t.typname IN ('vertical_scale', 'goal_origin')
             GROUP BY t.typname
            """
        )
        counts = dict(cur.fetchall())
        assert counts.get("vertical_scale") == 7
        assert counts.get("goal_origin") == 4


def test_f2_fixture_loads_49_rows_self_consistent(f2_db: str) -> None:
    """WP-03's own done-when: "psql -f tests/fixtures/f2_synth.sql loads 49 rows whose path
    and depth are self-consistent." 46 rows for owner 't1', 3 for owner 't2' (E2E.md §2).

    Self-consistent means: `path` is exactly the slash-joined id chain from root to this row,
    `depth` is `len(chain) - 1`, and — where `parent_id` is set — the parent's own `path` is
    this row's `path` with its own id-segment removed from the tail.
    """
    with psycopg.connect(f2_db, autocommit=True) as conn, conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM goals")
        (total,) = cur.fetchone()
        assert total == 49

        cur.execute("SELECT owner, count(*) FROM goals GROUP BY owner ORDER BY owner")
        assert dict(cur.fetchall()) == {"t1": 46, "t2": 3}

        cur.execute("SELECT id, parent_id, path, depth FROM goals")
        rows = {id_: (parent_id, path, depth) for id_, parent_id, path, depth in cur.fetchall()}
        assert len(rows) == 49

        for goal_id, (parent_id, path, depth) in rows.items():
            segments = [s for s in path.split("/") if s]
            assert segments[-1] == goal_id, f"{goal_id}: path does not end in its own id"
            assert len(segments) == depth + 1, f"{goal_id}: depth does not match path length"
            if parent_id is None:
                assert depth == 0, f"{goal_id}: root row must be depth 0"
                assert path == f"/{goal_id}/"
            else:
                _, parent_path, parent_depth = rows[parent_id]
                assert path == f"{parent_path}{goal_id}/", f"{goal_id}: path does not extend parent's"
                assert depth == parent_depth + 1, f"{goal_id}: depth does not extend parent's"
