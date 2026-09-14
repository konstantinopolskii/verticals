"""S-88, S-111 — install-path parity and the pg_trgm privilege contract. Real Postgres, no mocks.

Self-contained, same reasoning as tests/core/test_migrations.py: WP-06's shared harness
(template databases, the `verticals_t` name guard) does not exist yet, so this file manages
its own scratch state directly via psycopg.

S-111 is the one scenario in this catalogue that needs Postgres clusters this test is allowed
to break — a role deliberately missing a privilege — so per E2E.md §2 ("Scenarios that own the
server") it does not touch the shared `docker-compose.test.yml` cluster at all. It spins up
disposable `postgres:16-alpine` containers directly via the `docker` CLI (subprocess — no
Docker SDK dependency, consistent with the six-dependency allowlist) and stops each in
`finally`. Requires a reachable `docker` on PATH; there is no mock for "a role without a
privilege" because privilege is a server-side property, not something a client fakes.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
import uuid
from collections.abc import Iterator

import psycopg
import pytest

from verticals.db import runner

MIGRATIONS_DIR = runner.DEFAULT_MIGRATIONS_DIR
_IMAGE = "postgres:16-alpine"


# --------------------------------------------------------------------------------------
# S-88 — shares the compose cluster; no privilege boundary involved, nothing to isolate.
# --------------------------------------------------------------------------------------


def _admin_dsn(dbname: str = "postgres") -> str:
    host = os.environ.get("PGHOST", "127.0.0.1")
    port = os.environ.get("PGPORT", "55432")
    user = os.environ.get("PGUSER", "verticals")
    password = os.environ.get("PGPASSWORD", "verticals")
    return f"postgresql://{user}:{password}@{host}:{port}/{dbname}"


@pytest.fixture
def two_fresh_dbs() -> Iterator[tuple[str, str]]:
    """Two independent, unmigrated databases (`A`, `B`) in the shared test cluster."""
    names = [f"verticals_t_wp01_{uuid.uuid4().hex[:16]}" for _ in range(2)]
    with psycopg.connect(_admin_dsn(), autocommit=True) as admin:
        for name in names:
            admin.execute(f'CREATE DATABASE "{name}"')
    try:
        yield tuple(_admin_dsn(n) for n in names)  # type: ignore[return-value]
    finally:
        with psycopg.connect(_admin_dsn(), autocommit=True) as admin:
            for name in names:
                admin.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')


def _schema_digest(dsn: str) -> str:
    # See tests/core/test_migrations.py's _DIGEST_SQL for why the constraints branch
    # excludes Postgres's OID-named auto-generated not-null CHECK rows: this scenario
    # compares two *different* databases (A and B), and those synthetic names embed each
    # table's own OID, which is never equal across two independently-created tables even
    # for byte-identical DDL. Real, named constraints (color_is_canon, the FK, the PK, ...)
    # are unaffected — only the redundant not-null-per-column noise is dropped.
    query = """
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
    with psycopg.connect(dsn, autocommit=True) as conn, conn.cursor() as cur:
        cur.execute(query)
        (digest,) = cur.fetchone()
        return digest


def test_s88_stepwise_and_one_shot_reach_same_schema(two_fresh_dbs: tuple[str, str]) -> None:
    """S-88 — no drift between a fresh install and an upgraded one.

    Database A: `runner up` from zero, one shot. Database B: `runner up --to N` for each N
    in order. Assert: schema digests identical; both report the same `schema_version`.
    """
    dsn_a, dsn_b = two_fresh_dbs

    applied_a = runner.run_up(dsn_a)
    assert applied_a > 0

    versions = sorted(m.version for m in runner.discover_migrations(MIGRATIONS_DIR))
    for v in versions:
        runner.run_up(dsn_b, to_version=v)

    assert _schema_digest(dsn_a) == _schema_digest(dsn_b)

    def _version(dsn: str) -> int:
        with psycopg.connect(dsn, autocommit=True) as conn, conn.cursor() as cur:
            cur.execute("SELECT max(version) FROM schema_version")
            (v,) = cur.fetchone()
            return v

    assert _version(dsn_a) == _version(dsn_b)


# --------------------------------------------------------------------------------------
# S-111 — three privilege shapes on throwaway clusters this test is allowed to break.
# --------------------------------------------------------------------------------------


def _run(*args: str, timeout: float = 30.0) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, capture_output=True, text=True, timeout=timeout)


def _wait_ready(dsn: str, timeout: float = 30.0) -> None:
    deadline = time.monotonic() + timeout
    last: Exception | None = None
    while time.monotonic() < deadline:
        try:
            with psycopg.connect(dsn, connect_timeout=2) as conn:
                conn.execute("SELECT 1")
            return
        except psycopg.OperationalError as exc:
            last = exc
            time.sleep(0.5)
    raise TimeoutError(f"postgres did not become ready within {timeout}s: {last}")


class _ThrowawayCluster:
    """A `postgres:16-alpine` container nobody else can see. `docker run --rm`, an
    auto-assigned host port (`-p 127.0.0.1::5432`, so nothing collides with
    `docker-compose.test.yml`'s fixed 55432), stopped unconditionally on exit."""

    def __init__(self) -> None:
        self._container_id: str | None = None
        self.admin_dsn = ""

    def __enter__(self) -> "_ThrowawayCluster":
        result = _run(
            "docker", "run", "-d", "--rm",
            "-e", "POSTGRES_USER=postgres",
            "-e", "POSTGRES_PASSWORD=probepw",
            "-e", "POSTGRES_DB=postgres",
            "-p", "127.0.0.1::5432",
            _IMAGE,
        )
        if result.returncode != 0:
            pytest.fail(f"docker run failed (is Docker running?): {result.stderr.strip()}")
        self._container_id = result.stdout.strip()

        port_result = _run("docker", "port", self._container_id, "5432/tcp")
        port = port_result.stdout.strip().rsplit(":", 1)[-1]
        self.admin_dsn = f"postgresql://postgres:probepw@127.0.0.1:{port}/postgres"
        _wait_ready(self.admin_dsn)
        return self

    def __exit__(self, *exc_info: object) -> None:
        if self._container_id:
            _run("docker", "stop", "-t", "5", self._container_id, timeout=20.0)

    def exec_sql(self, sql: str) -> None:
        with psycopg.connect(self.admin_dsn, autocommit=True) as conn:
            conn.execute(sql)

    def role_dsn(self, role: str, password: str) -> str:
        host_port = self.admin_dsn.split("@", 1)[1]
        return f"postgresql://{role}:{password}@{host_port}"

    def public_table_count(self) -> int:
        with psycopg.connect(self.admin_dsn, autocommit=True) as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT count(*) FROM information_schema.tables WHERE table_schema = 'public'"
            )
            (count,) = cur.fetchone()
            return count

    def extension_names(self) -> set[str]:
        with psycopg.connect(self.admin_dsn, autocommit=True) as conn, conn.cursor() as cur:
            cur.execute("SELECT extname FROM pg_extension")
            return {row[0] for row in cur.fetchall()}


def test_s111a_stock_superuser_reaches_head() -> None:
    """S-111(a) — stock image, superuser, nothing pre-created: migrate and serve."""
    with _ThrowawayCluster() as cluster:
        applied = runner.run_up(cluster.admin_dsn)
        assert applied > 0
        assert cluster.extension_names() == {"plpgsql", "pg_trgm"}


def test_s111b_pretrusted_extension_nonsuperuser_reaches_head() -> None:
    """S-111(b) — pg_trgm already created by hand, the app role not a superuser: migrate
    and serve. The role gets schema-level CREATE only (never superuser, never database-level
    CREATE) — enough to build tables/types/indexes; `CREATE EXTENSION IF NOT EXISTS pg_trgm`
    is a verified no-op against an already-installed extension and does not re-check the
    database-level privilege it would need to install one from scratch."""
    with _ThrowawayCluster() as cluster:
        cluster.exec_sql("CREATE EXTENSION pg_trgm")
        cluster.exec_sql("CREATE ROLE app_b LOGIN PASSWORD 'app_b_pw'")
        cluster.exec_sql("GRANT CREATE ON SCHEMA public TO app_b")

        applied = runner.run_up(cluster.role_dsn("app_b", "app_b_pw"))

        assert applied > 0
        assert cluster.extension_names() == {"plpgsql", "pg_trgm"}


def test_s111c_missing_privilege_fails_loudly_and_leaves_nothing() -> None:
    """S-111(c) — non-superuser role, pg_trgm absent and uncreatable: migrate.

    The role gets schema-level CREATE (so `001_init.sql` — tables, types, indexes — would
    succeed on its own) but not database-level CREATE, which is specifically what Postgres 16
    requires for `CREATE EXTENSION` (verified against a live server, not assumed — see
    verticals/db/runner.py's module docstring). That isolates the failure to `002_trgm.sql`.

    Assert: exit 2; stderr names `pg_trgm` and the exact remediation statement and the role
    that must run it; zero tables left in `public` — AC-005's whole point is "fails loudly
    instead of half-migrating," and the runner commits the whole invocation atomically or not
    at all, so 001's already-"applied" work does not survive 002's failure. Then: re-run after
    granting the missing privilege reaches head, proving the failure was recoverable by doing
    the one thing the message said.
    """
    with _ThrowawayCluster() as cluster:
        cluster.exec_sql("CREATE ROLE restricted LOGIN PASSWORD 'restricted_pw'")
        cluster.exec_sql("GRANT CREATE ON SCHEMA public TO restricted")
        locked_dsn = cluster.role_dsn("restricted", "restricted_pw")

        result = subprocess.run(
            [sys.executable, "-m", "verticals.db.runner", "up"],
            env={**os.environ, "VERTICALS_DATABASE_URL": locked_dsn},
            capture_output=True,
            text=True,
            timeout=30,
        )

        assert result.returncode == 2
        assert "pg_trgm" in result.stderr
        assert "CREATE EXTENSION" in result.stderr
        # "the role that must run it" (E2E.md S-111): the runner cannot know a real
        # superuser's name on an arbitrary target server, so it names the privilege a role
        # needs instead of guessing an identity — the only generically honest thing to say.
        assert "role" in result.stderr and "privilege" in result.stderr
        assert cluster.public_table_count() == 0

        cluster.exec_sql("GRANT CREATE ON DATABASE postgres TO restricted")
        rerun = subprocess.run(
            [sys.executable, "-m", "verticals.db.runner", "up"],
            env={**os.environ, "VERTICALS_DATABASE_URL": locked_dsn},
            capture_output=True,
            text=True,
            timeout=30,
        )

        assert rerun.returncode == 0
        assert cluster.extension_names() == {"plpgsql", "pg_trgm"}
