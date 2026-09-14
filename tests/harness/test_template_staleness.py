"""The template-staleness guard, exercised against a real cluster — `docs/PENDING_DOC_FIXES.md`
row 69, the defect that fired twice (a migration lands, the long-lived template is pre-migration,
every clone inherits the old schema, and every suite reports green while proving nothing about the
new file).

Why the tests live here rather than in `tests/core`. This is harness machinery, not product
behaviour: the thing under test is `tests/conftest.py`'s own template bookkeeping, in the same
sense that `test_runner_contract.py` tests the runner and `test_stmt_scoping_...` tests the
statement counter. Suite `harness` is the one suite that runs as plain pytest (`make
test-harness`), which is also what these tests need — a scenario id from `docs/E2E.md` would have
to be minted and reconciled across three documents to say something about the harness rather than
about the product.

**Non-vacuity — the discipline AC-203's tree invariant set when it injected a bad `path` and
watched the scenario fail.** A guard nobody has seen fail is not a guard. `test_stale_template_is_
detected_and_rebuilt` does not merely assert that a fresh template ends up at head; it *builds the
stale template first* — a real database migrated to head-1, exactly the shape the cluster was in
when this defect fired — asserts that it is genuinely stale (missing the last migration's own
effect, not just carrying an older label), then calls `ensure_template` and asserts the rebuild
happened. Delete the provenance comparison from `ensure_template` and the "already exists" branch
returns the stale template untouched: the post-condition assertions fail, and so does this file.
That is the same failure the suites themselves cannot show, because a stale template makes them
pass.

Everything below operates on its own template names (`verticals_tmpl_row69*`), never on
`verticals_tmpl_f0` — a test that dropped the template every other worker on this box is cloning
from would be a worse defect than the one it is fixing. No mocks anywhere (`docs/BRIEF.md` rule 2,
`tests/static/test_no_mocks.py`): a real cluster, real `CREATE DATABASE`, real migrations, real
concurrent threads.
"""

from __future__ import annotations

import threading

import psycopg
import pytest

from verticals.db import runner as migration_runner
from tests import conftest


def _cluster_reachable() -> bool:
    try:
        with psycopg.connect(conftest.maintenance_dsn(), autocommit=True):
            return True
    except psycopg.OperationalError:
        return False


def _drop(name: str) -> None:
    conftest._guard(name)
    with psycopg.connect(conftest.maintenance_dsn(), autocommit=True) as admin:
        admin.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')


def _build_stale(fixture: str, to_version: int) -> str:
    """A template built exactly the way the old code built one: create, migrate, record nothing.
    This is not a simulation of the stale state — it *is* the stale state, byte for byte, since
    the pre-row-69 `ensure_template` did these two statements and no more."""
    name = conftest._guard(conftest._template_name(fixture))
    _drop(name)
    with psycopg.connect(conftest.maintenance_dsn(), autocommit=True) as admin:
        admin.execute(f'CREATE DATABASE "{name}"')
    migration_runner.run_up(conftest._env_dsn(name), to_version=to_version)
    return name


def _version_of(name: str) -> int:
    with psycopg.connect(conftest._env_dsn(name), autocommit=True) as conn:
        return migration_runner.current_version(conn)


def _head_version() -> int:
    return migration_runner.discover_migrations(migration_runner.DEFAULT_MIGRATIONS_DIR)[-1].version


def test_stale_template_is_detected_and_rebuilt():
    """The row-69 defect, and its fix, in one run: build the template one migration behind head,
    prove it is behind, then let `ensure_template` see it."""
    if not _cluster_reachable():
        pytest.fail("no Postgres reachable at PGHOST/PGPORT; this test needs a real cluster")
    head = _head_version()
    assert head >= 2, "this test needs at least two migrations to be able to build a stale one"
    fixture = "row69_stale"
    name = _build_stale(fixture, to_version=head - 1)
    try:
        # Before: genuinely stale, and carrying no provenance — the shape every template built
        # before this guard existed has.
        assert _version_of(name) == head - 1
        assert conftest.read_template_provenance(name) is None

        returned = conftest.ensure_template(fixture)

        # After: rebuilt at head, and now carrying the fingerprint of the migration set on disk.
        # Both assertions fail if the staleness comparison is removed from `ensure_template`.
        assert returned == name
        assert _version_of(name) == head, (
            f"template {name} still at schema_version={_version_of(name)} after ensure_template; "
            f"the staleness check did not fire (row 69)"
        )
        assert conftest.read_template_provenance(name) == conftest.migrations_provenance()
    finally:
        _drop(name)


def test_stale_template_with_live_connections_is_still_rebuilt():
    """The manual procedure this replaces required a human to confirm zero active connections
    before dropping. The automatic path gets no such courtesy: an idle session sits on the stale
    template for the whole rebuild, and the rebuild must neither crash nor quietly skip."""
    if not _cluster_reachable():
        pytest.fail("no Postgres reachable at PGHOST/PGPORT; this test needs a real cluster")
    head = _head_version()
    fixture = "row69_busy"
    name = _build_stale(fixture, to_version=head - 1)
    squatter = psycopg.connect(conftest._env_dsn(name), autocommit=True)
    try:
        squatter.execute("SELECT 1")  # a real, established, idle-in-session backend
        with psycopg.connect(conftest.maintenance_dsn(), autocommit=True) as admin:
            (live,) = admin.execute(
                "SELECT count(*) FROM pg_stat_activity WHERE datname = %s", (name,)
            ).fetchone()
        assert live >= 1, "the squatting connection did not register in pg_stat_activity"

        conftest.ensure_template(fixture)

        assert _version_of(name) == head
        assert conftest.read_template_provenance(name) == conftest.migrations_provenance()
    finally:
        try:
            squatter.close()
        except psycopg.Error:
            pass  # the rebuild terminated it, which is the point
        _drop(name)


def test_concurrent_rebuilds_do_not_corrupt_or_deadlock():
    """Four threads, one stale template, one instant. psycopg releases the GIL on every round
    trip to Postgres, so these are genuinely concurrent `DROP`/`CREATE`/migrate attempts — the
    same race two `make test-core` invocations on this box produce. The advisory lock has to make
    exactly one of them do the work and the rest find it already done; a lost race must not raise,
    must not leave a half-migrated template, and must not hang."""
    if not _cluster_reachable():
        pytest.fail("no Postgres reachable at PGHOST/PGPORT; this test needs a real cluster")
    head = _head_version()
    fixture = "row69_race"
    name = _build_stale(fixture, to_version=head - 1)
    errors: list[BaseException] = []
    start = threading.Barrier(4)

    def racer() -> None:
        try:
            start.wait(timeout=30)
            conftest.ensure_template(fixture)
        except BaseException as exc:  # noqa: BLE001 — every failure is reported, none swallowed
            errors.append(exc)

    threads = [threading.Thread(target=racer) for _ in range(4)]
    try:
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=180)
        assert not any(t.is_alive() for t in threads), (
            "a rebuild thread was still running after 180s — the advisory lock deadlocked"
        )
        assert not errors, f"concurrent ensure_template raised: {errors!r}"
        assert _version_of(name) == head
        assert conftest.read_template_provenance(name) == conftest.migrations_provenance()
    finally:
        for t in threads:
            t.join(timeout=30)
        _drop(name)


def test_provenance_tracks_migration_content_not_just_the_head_number(tmp_path):
    """Head-version-only comparison would miss an existing numbered file edited in place, which is
    the same defect wearing a different hat. Two directories with identical filenames and
    different bytes must fingerprint differently."""
    a = tmp_path / "a"
    b = tmp_path / "b"
    a.mkdir()
    b.mkdir()
    (a / "001_init.sql").write_text("SELECT 1;\n")
    (b / "001_init.sql").write_text("SELECT 2;\n")
    assert conftest.migrations_provenance(a) != conftest.migrations_provenance(b)
    assert conftest.migrations_provenance(a) == conftest.migrations_provenance(a)
