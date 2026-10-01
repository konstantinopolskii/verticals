"""S-01, S-02 — the migration runner's own build-time proof. Real Postgres, no mocks.

Self-contained on purpose: creates and drops its own scratch database per test via the
`postgres` admin database, using PGHOST/PGPORT/PGUSER/PGPASSWORD
(docs/IMPLEMENTATION.md §6.2 — the same variables `make db-up`'s printed instructions set).
It does not reach into `tests/conftest.py`'s template-database machinery, because that
machinery is WP-06's (docs/IMPLEMENTATION.md WP-01 card: "No scenario can print a PASS line
before WP-06 lands the runner") and does not exist yet. Once it does, wiring this file onto
the shared harness is a fixture rename, not a rewrite — the assertions below are the scenario
text itself, not the plumbing around it.

Run directly (today, standalone):
    docker compose -f docker-compose.test.yml up -d --wait
    PGHOST=127.0.0.1 PGPORT=55432 PGUSER=verticals PGPASSWORD=verticals \
        pytest tests/core/test_migrations.py -v
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterator

import psycopg
import pytest

from verticals.db import runner

MIGRATIONS_DIR = runner.DEFAULT_MIGRATIONS_DIR

# md5 over the sorted catalogue: columns, types, nullability, defaults, constraints, indexes.
# E2E.md §3 (S-02): "md5 over the sorted output of a catalogue query covering columns, types,
# nullability, defaults, constraints and indexes."
#
# The constraints branch excludes Postgres's auto-generated `<schema_oid>_<table_oid>_
# <colnum>_not_null` synthetic CHECK rows (one per NOT NULL column, added automatically by
# Postgres 12+ and visible in information_schema.table_constraints alongside real, named
# constraints). Their names embed the table's OID, which is assigned fresh by Postgres on
# every CREATE TABLE and is never the same across two independently-created databases even
# for byte-identical DDL — so leaving them in makes any *cross-database* digest comparison
# (S-88 compares two) fail on OID noise, not on an actual schema difference. Harmless to drop:
# each column's own `is_nullable` (in the columns branch above) already carries the same fact.
_DIGEST_SQL = """
    SELECT md5(string_agg(line, '|' ORDER BY line)) FROM (
        SELECT format('col:%s.%s:%s:%s:%s', table_name, column_name, data_type,
                       is_nullable, coalesce(column_default, '')) AS line
          FROM information_schema.columns WHERE table_schema = 'public'
        UNION ALL
        SELECT format('con:%s:%s:%s', table_name, constraint_name, constraint_type)
          FROM information_schema.table_constraints
         WHERE table_schema = 'public'
           AND constraint_name !~ '^[0-9]+_[0-9]+_[0-9]+_not_null$'
        UNION ALL
        SELECT format('idx:%s', indexdef)
          FROM pg_indexes WHERE schemaname = 'public'
    ) AS catalogue
"""


def _admin_dsn(dbname: str = "postgres") -> str:
    host = os.environ.get("PGHOST", "127.0.0.1")
    port = os.environ.get("PGPORT", "55432")
    user = os.environ.get("PGUSER", "verticals")
    password = os.environ.get("PGPASSWORD", "verticals")
    return f"postgresql://{user}:{password}@{host}:{port}/{dbname}"


@pytest.fixture
def fresh_db() -> Iterator[str]:
    """F0: a brand-new, unmigrated database — 'migrations at head, zero rows' minus the
    'at head' part, since reaching head is the action under test here, not a precondition.
    Dropped `WITH (FORCE)` on teardown regardless of what the test left connected."""
    name = f"verticals_t_wp01_{uuid.uuid4().hex[:16]}"
    with psycopg.connect(_admin_dsn(), autocommit=True) as admin:
        admin.execute(f'CREATE DATABASE "{name}"')
    try:
        yield _admin_dsn(name)
    finally:
        with psycopg.connect(_admin_dsn(), autocommit=True) as admin:
            admin.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')


def _schema_digest(dsn: str) -> str:
    with psycopg.connect(dsn, autocommit=True) as conn, conn.cursor() as cur:
        cur.execute(_DIGEST_SQL)
        (digest,) = cur.fetchone()
        return digest


def _enum_label_counts(dsn: str) -> dict[str, int]:
    with psycopg.connect(dsn, autocommit=True) as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT t.typname, count(e.enumlabel)
              FROM pg_type t JOIN pg_enum e ON e.enumtypid = t.oid
             WHERE t.typname IN ('vertical_scale', 'goal_origin')
             GROUP BY t.typname
            """
        )
        return dict(cur.fetchall())


def test_s01_migrations_apply_from_zero_to_head(fresh_db: str) -> None:
    """S-01 — a bare database reaches head with a recorded version.

    Fixture: F0 on an empty database. Steps: CREATE DATABASE, `runner up`.
    Assert: exit 0 (no MigrationError raised); max(schema_version.version) equals the
    highest-numbered migration file; exactly 12 tables (D250/WP-1 added `docs`, `doc_revisions`,
    `goal_doc_links`; WP-A/015_comments.sql added `comment_threads`, `comment_messages`;
    016_replan.sql added `carryover_runs`); the enums carry 7 and 4 labels (016 added the app as
    an author).
    """
    highest = max(m.version for m in runner.discover_migrations(MIGRATIONS_DIR))

    applied = runner.run_up(fresh_db)

    assert applied == len(runner.discover_migrations(MIGRATIONS_DIR))
    with psycopg.connect(fresh_db, autocommit=True) as conn, conn.cursor() as cur:
        cur.execute("SELECT max(version) FROM schema_version")
        (max_version,) = cur.fetchone()
        assert max_version == highest

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
            SELECT column_name, data_type, is_nullable, column_default
              FROM information_schema.columns
             WHERE table_schema = 'public' AND table_name = 'goals'
               AND column_name IN (
                 'vertical', 'parked_from_vertical', 'foil', 'carryover_ignored_until'
               )
            """
        )
        columns = {name: (kind, nullable, default) for name, kind, nullable, default in cur.fetchall()}
        assert columns["vertical"][1] == "YES"
        assert columns["parked_from_vertical"][:2] == ("text", "YES")
        assert columns["foil"][:2] == ("boolean", "NO")
        assert columns["foil"][2] == "false"
        assert columns["carryover_ignored_until"][:2] == ("date", "YES")

        cur.execute(
            "SELECT constraint_name FROM information_schema.table_constraints "
            "WHERE table_schema = 'public' AND table_name = 'goals'"
        )
        constraints = {row[0] for row in cur.fetchall()}
        assert {"parked_from_vertical_is_scale", "vertical_parked_together"} <= constraints

    counts = _enum_label_counts(fresh_db)
    assert counts.get("vertical_scale") == 7
    assert counts.get("goal_origin") == 4


def test_s02_migrations_are_idempotent_and_forward_only(fresh_db: str) -> None:
    """S-02 — re-running the runner changes nothing.

    Steps: run S-01's path, capture a schema digest, run the runner again, recapture.
    Assert: digests byte-identical; schema_version row count unchanged; exit 0; `applied=0`.
    """
    first_applied = runner.run_up(fresh_db)
    assert first_applied > 0
    digest_before = _schema_digest(fresh_db)
    with psycopg.connect(fresh_db, autocommit=True) as conn, conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM schema_version")
        (version_rows_before,) = cur.fetchone()

    second_applied = runner.run_up(fresh_db)

    assert second_applied == 0
    digest_after = _schema_digest(fresh_db)
    assert digest_after == digest_before
    with psycopg.connect(fresh_db, autocommit=True) as conn, conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM schema_version")
        (version_rows_after,) = cur.fetchone()
    assert version_rows_after == version_rows_before


def test_008_upgrades_existing_unverticaled_rows_without_data_loss(fresh_db: str) -> None:
    runner.run_up(fresh_db, to_version=7)
    with psycopg.connect(fresh_db, autocommit=True) as conn:
        conn.execute(
            "INSERT INTO goals (id, owner, path, title) "
            "VALUES ('SYNLEG01', 'SYN-migration', '/SYNLEG01/', 'SYN legacy unset row')"
        )

    # to_version pinned: 009/010 landed in the same release wave, so an open-ended run_up
    # applies three migrations here — this test is about 008's backfill alone.
    assert runner.run_up(fresh_db, to_version=8) == 1

    with psycopg.connect(fresh_db, autocommit=True) as conn:
        row = conn.execute(
            "SELECT vertical, parked_from_vertical, foil, carryover_ignored_until "
            "FROM goals WHERE id = 'SYNLEG01'"
        ).fetchone()
    assert row == (None, "life", False, None)
