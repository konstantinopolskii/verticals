"""Template-database machinery shared by every suite that touches Postgres, plus the harness's
report hooks (GATE detection, `VERTICALS_FORCE_FAIL`, artifact capture). `docs/IMPLEMENTATION.md`
WP-06 card; `docs/E2E.md` §2 "How a suite gets a clean database".

Template databases, not transactional rollback — `http`, `mcp` and `ui` drive a server that owns
its own connection pool and cannot join a test's transaction, so one isolation mechanism has to
serve every suite:

    per run:   CREATE DATABASE verticals_tmpl_f0;  <migrate>
    per test:  CREATE DATABASE verticals_t_<worker>_<n>_<rand> TEMPLATE verticals_tmpl_f0
    teardown:  DROP DATABASE verticals_t_<worker>_<n>_<rand> WITH (FORCE)

Two traps, named in the WP-06 card, both fixed here:

  1. `CREATE DATABASE ... TEMPLATE` fails while any session is connected to the template. Under
     parallel pytest-xdist workers this bites immediately. Fixed by ordering, not locking: every
     template is built in `pytest_configure`, which — under xdist — runs to completion in the
     controller process before any worker is spawned (`config.workerinput` exists only inside a
     worker), and under a plain, non-distributed `pytest` invocation there is no controller/
     worker split at all, so the same guard is trivially satisfied there too.
  2. `pg_stat_statements` is cluster-wide and is deliberately never created in a `verticals_t_*`
     clone (IR-06; `docker/test-initdb/01-pg-stat-statements.sql`). This module never touches
     that extension at all — `tests/harness/stmt.py` owns it, scoped by `dbid`, connected to the
     `postgres` maintenance database.

A third trap, found the hard way twice and fixed here (`docs/PENDING_DOC_FIXES.md` row 69): a
template that already exists is not a template that is still correct. The cluster outlives the
session that built it, so a migration added afterwards reaches nothing — every clone carries the
old schema and every suite goes green while proving nothing about the new file. Each template now
records the migration set it was built from, and `ensure_template` compares that against the
migrations directory on every call, rebuilding on any difference. See "template provenance" below.

The `verticals_t` name guard: every `CREATE DATABASE` / `DROP DATABASE` this module issues is
checked against `TEST_DB_PREFIX` first. `docs/E2E.md` §2: "[the harness] refuses to run against
a database whose name does not start with verticals_t."
"""

from __future__ import annotations

import hashlib
import os
import secrets
import sys
import zlib
from collections.abc import Iterator
from contextlib import contextmanager
from itertools import count
from pathlib import Path

import psycopg
import pytest
from playwright.sync_api import Browser, Playwright, sync_playwright
from psycopg import sql as psql_sql

from verticals.db import runner as migration_runner
from tests.harness import tree_invariant
from tests.harness.report import (
    FailDetail,
    Gated,
    artifacts_for,
    format_fail_block,
    scenario_id_of,
    suite_of,
)

TEST_DB_PREFIX = "verticals_t"

_FORCE_FAIL_ENV = "VERTICALS_FORCE_FAIL"


class UnsafeDatabaseName(RuntimeError):
    """A `CREATE DATABASE`/`DROP DATABASE` this module was about to issue targets a name outside
    the harness's own namespace. Refuses rather than risk a developer's or production database —
    the one guard every other function in this module routes through."""


def _guard(name: str) -> str:
    if not name.startswith(TEST_DB_PREFIX):
        raise UnsafeDatabaseName(
            f"refusing to touch database {name!r}: harness only operates on names starting "
            f"with {TEST_DB_PREFIX!r} (docs/E2E.md §2)"
        )
    return name


# --- connection parameters ---------------------------------------------------------------------
# Same PGHOST/PGPORT/PGUSER/PGPASSWORD convention tests/core/test_migrations.py already uses
# (docs/IMPLEMENTATION.md §6.2) — deliberately not verticals.config.load(), which additionally
# requires VERTICALS_TOKEN and is the application's boot contract, not the harness's.


def _env_dsn(dbname: str) -> str:
    host = os.environ.get("PGHOST", "127.0.0.1")
    port = os.environ.get("PGPORT", "55432")
    user = os.environ.get("PGUSER", "verticals")
    password = os.environ.get("PGPASSWORD", "verticals")
    return f"postgresql://{user}:{password}@{host}:{port}/{dbname}"


def maintenance_dsn() -> str:
    """The `postgres` maintenance database — the only database `CREATE`/`DROP DATABASE` and (per
    `tests/harness/stmt.py`) `pg_stat_statements` can be reached through."""
    return _env_dsn("postgres")


# --- templates -----------------------------------------------------------------------------


def _template_name(fixture: str) -> str:
    return f"verticals_tmpl_{fixture}"


# --- template provenance: what migration set this template was built from ----------------------
#
# Row 69 of docs/PENDING_DOC_FIXES.md, fired twice. "Build once per machine" is right for speed
# and wrong at exactly one moment: when the migration set changes under a cluster that outlives
# the session that built the template. A pre-migration template clones a pre-migration schema
# into every test database, and the suite reports green against a schema the code no longer
# targets — silent in both directions, since the tests that would have caught it are the ones
# that could not run against the right schema. Fixed here by making the template carry the
# migration set it was built from and having every `ensure_template` call compare that against
# the migrations directory on disk, rebuilding on any difference.
#
# The provenance string lives in the template's own `COMMENT ON DATABASE`, not in a table inside
# it. That placement is load-bearing twice over. A comment is stored in `pg_shdescription`, a
# shared catalogue keyed by database OID, so it is *not* copied into a clone — AC-004's "the
# extension set the application ever sees" style of promise extends to tables too, and a harness
# bookkeeping table inside F0 would show up in every clone, every schema digest (S-88) and every
# `information_schema` assertion any scenario cares to make. And reading it costs one row from a
# catalogue on the maintenance connection this function already opens.
#
# The digest is over file *content*, not just the head version number. A head-only check misses
# the case that bit WP-P5 in a different disguise: an existing numbered file edited in place
# (a constraint tightened in `004_path_format.sql` rather than a new `006_`). Content is what
# the schema is built from, so content is what is compared.

_PROVENANCE_PREFIX = "verticals-template"

# Advisory-lock namespace for template rebuilds. Two-int form; the first int is a constant
# private to this module and the second is derived from the template name, so two different
# templates never contend. These locks are taken on the `postgres` maintenance database, and
# advisory locks are scoped per database — they cannot collide with the application's own
# advisory locks (`verticals/core/tree.py`), which are only ever taken inside a clone.
_LOCK_CLASS = 0x484F  # "HO"

# A rebuild that cannot get the lock inside this window is a real problem (a wedged sibling
# process, a lock held by something that will never release it) and must say so rather than hang
# a suite forever. `pg_advisory_lock` is an ordinary function call, so `statement_timeout`
# applies to it.
_LOCK_TIMEOUT_MS = 120_000


class TemplateRebuildFailed(RuntimeError):
    """The template was stale and could not be rebuilt. Deliberately fatal: the alternative is
    cloning a schema that is known to be wrong, which is the exact failure this machinery
    exists to prevent."""


def migrations_provenance(migrations_dir: Path | None = None) -> str:
    """The one-line fingerprint of the migration set on disk: head version plus a digest over
    every migration file's name and bytes. Rebuilt from disk on every call — this is a handful
    of small files and the read is what makes the check honest."""
    directory = migrations_dir or migration_runner.DEFAULT_MIGRATIONS_DIR
    migrations = migration_runner.discover_migrations(directory)
    head = migrations[-1].version if migrations else 0
    digest = hashlib.sha256()
    for m in migrations:
        digest.update(m.filename.encode("utf-8"))
        digest.update(b"\0")
        digest.update(m.path.read_bytes())
        digest.update(b"\0")
    return f"{_PROVENANCE_PREFIX} head={head} digest={digest.hexdigest()[:16]}"


def _lock_key(name: str) -> int:
    # crc32 is deterministic across processes and Python runs (hash() is not, PYTHONHASHSEED).
    # Shifted into signed int32 range, which is what pg_advisory_lock's two-int form takes.
    return zlib.crc32(name.encode("utf-8")) - 2**31


def read_template_provenance(name: str) -> str | None:
    """The provenance string recorded on `name`, or `None` for a template that has none — which
    is what every template built before this check existed looks like, and is treated as stale."""
    with psycopg.connect(maintenance_dsn(), autocommit=True) as admin:
        return _read_provenance(admin, _guard(name))


def _read_provenance(admin: psycopg.Connection, name: str) -> str | None:
    row = admin.execute(
        "SELECT shobj_description(oid, 'pg_database') FROM pg_database WHERE datname = %s",
        (name,),
    ).fetchone()
    return row[0] if row else None


def _disconnect_everyone(admin: psycopg.Connection, name: str) -> int:
    """Terminate every backend connected to `name`, returning how many were hit.

    `DROP DATABASE ... WITH (FORCE)` does this itself on Postgres 13+, so this is not the only
    defence — but it is the one that produces a number, and the number is the point. The manual
    fix this replaces required a human to confirm "0 active connections" before dropping; the
    automatic path has to state what it found instead of quietly assuming zero. A backend that
    reconnects between this call and the DROP is still handled, by FORCE.
    """
    rows = admin.execute(
        "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
        "WHERE datname = %s AND pid <> pg_backend_pid()",
        (name,),
    ).fetchall()
    return len(rows)


def _build_template(admin: psycopg.Connection, name: str, provenance: str) -> None:
    admin.execute(f'CREATE DATABASE "{name}"')
    migration_runner.run_up(_env_dsn(name))
    admin.execute(
        psql_sql.SQL("COMMENT ON DATABASE {} IS {}").format(
            psql_sql.Identifier(name), psql_sql.Literal(provenance)
        )
    )


def _ensure_template_locked(name: str, want: str, found: str | None) -> None:
    """Build the template, or drop and rebuild it when its provenance does not match the
    migrations on disk. Everything that writes a template goes through here, under the lock.

    Concurrency. This box runs many suites at once, so two processes can reach this function for
    the same template in the same instant, and a third can be in the middle of cloning from it.
    Three things make that safe, and none of them is "hope":

      * an exclusive advisory lock, keyed on the template name, serialises rebuilds — the loser
        waits, then finds the provenance already correct and does nothing (the re-read below is
        why a serialised second rebuild is not merely redundant but skipped);
      * `fresh_clone` takes the *shared* form of the same lock around its `CREATE DATABASE ...
        TEMPLATE`, so a rebuild cannot pull the template out from under a clone in flight, and a
        clone cannot start against a template that is mid-rebuild;
      * connected backends are terminated and the DROP is `WITH (FORCE)`, so a live connection —
        an idle psql, a leftover pool from a crashed run — delays the rebuild by nothing and
        cannot turn it into a silent no-op.

    A failure anywhere here raises. A stale template that could not be rebuilt must stop the run:
    the whole defect being fixed is a run that continues against the wrong schema.
    """
    with psycopg.connect(maintenance_dsn(), autocommit=True) as admin:
        admin.execute(f"SET statement_timeout = {_LOCK_TIMEOUT_MS}")
        try:
            admin.execute("SELECT pg_advisory_lock(%s, %s)", (_LOCK_CLASS, _lock_key(name)))
        except psycopg.errors.QueryCanceled as exc:
            raise TemplateRebuildFailed(
                f"template {name} is stale (found {found!r}, want {want!r}) and the rebuild lock "
                f"was still held after {_LOCK_TIMEOUT_MS}ms — another process is wedged holding "
                f"it. Refusing to clone a schema known to be out of date."
            ) from exc
        admin.execute("SET statement_timeout = 0")
        try:
            if _read_provenance(admin, name) == want:
                return  # a racing sibling built or rebuilt it while this process queued
            exists = admin.execute(
                "SELECT 1 FROM pg_database WHERE datname = %s", (name,)
            ).fetchone()
            if exists:
                killed = _disconnect_everyone(admin, name)
                print(
                    f"tests/conftest.py: template {name} is stale "
                    f"(found {found or '(no provenance recorded)'}, want {want}); "
                    f"rebuilding after terminating {killed} connection(s) to it.",
                    file=sys.stderr,
                )
            try:
                admin.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
                _build_template(admin, name, want)
            except (psycopg.Error, migration_runner.MigrationError) as exc:
                raise TemplateRebuildFailed(
                    f"template {name} is stale (found {found!r}, want {want!r}) and the rebuild "
                    f"failed: {exc}. Refusing to clone a schema known to be out of date."
                ) from exc
        finally:
            admin.execute("SELECT pg_advisory_unlock(%s, %s)", (_LOCK_CLASS, _lock_key(name)))


def ensure_template(fixture: str = "f0") -> str:
    """Build `verticals_tmpl_<fixture>` if it does not already exist, and rebuild it if the
    migration set on disk has moved since it was built. F0 — migrations at head, zero rows
    (`docs/E2E.md` §2) — is the only fixture this work package carries the SQL for; a later work
    package extends this by adding its own `verticals_tmpl_<name>` build here or by cloning F0 and
    loading its own fixture file on top. Idempotent: safe to call from every worker and every
    suite, the actual build happens at most once per template per migration set per machine.

    `pytest_configure`'s ordering fixes the in-process (xdist controller-vs-worker) version of
    trap 1. It says nothing about two *separate* `pytest`/`make test` invocations racing each
    other's first-ever build of the same template — a real possibility whenever more than one
    agent has a shell open on this repo. `CREATE DATABASE` losing that race raises
    `DuplicateDatabase`; caught and treated the same as "already existed", since that is exactly
    what it means.

    Trap 3, row 69: an *existing* template is not evidence of a *current* one. The provenance
    comparison below is deliberately not cached anywhere — it is one catalogue read on a
    connection this function already opens plus a digest over five small files, and a cache
    keyed on "we already checked this process" is exactly the assumption that produced the
    defect. On drift the template is rebuilt, not warned about: a warning in a scrolled-past log
    is what the manual procedure already was, and it failed twice.
    """
    name = _guard(_template_name(fixture))
    want = migrations_provenance()
    with psycopg.connect(maintenance_dsn(), autocommit=True) as admin:
        found = _read_provenance(admin, name)
    if found != want:
        # Covers both "does not exist" (no row, so no comment, so `None`) and "exists but was
        # built from a different migration set". Both need the same lock and the same builder,
        # which is why they are not two branches: a first build racing a rebuild for the same
        # name is precisely the case a separate unlocked create path would get wrong.
        _ensure_template_locked(name, want, found)
    return name


def pytest_configure(config: pytest.Config) -> None:
    """Trap 1 fix — see module docstring. Swallows a connection failure rather than crashing
    collection: `tests/static` needs no database at all, so this must not be the reason a
    static-only invocation dies. A suite that does need a clone fails at its own fixture, with
    psycopg's own connection error, which is a clearer signal than one raised three layers up
    here."""
    if hasattr(config, "workerinput"):
        return
    try:
        ensure_template("f0")
    except psycopg.OperationalError as exc:
        print(
            f"tests/conftest.py: no Postgres reachable at configure time ({exc}); "
            f"database-backed suites will fail at their own fixture, not here.",
            file=sys.stderr,
        )


# --- per-test clones -------------------------------------------------------------------------

_clone_counter = count()  # one counter per process; under xdist that means one per worker


def _worker_id() -> str:
    return os.environ.get("PYTEST_XDIST_WORKER", "nogw")


def _new_clone_name() -> str:
    # The random suffix protects against a name collision with a leftover clone from a prior
    # run that crashed before teardown ran (same worker id, same counter value) — cheap
    # insurance, not the isolation mechanism itself.
    return _guard(f"{TEST_DB_PREFIX}_{_worker_id()}_{next(_clone_counter)}_{secrets.token_hex(3)}")


def _drop_database(name: str) -> None:
    _guard(name)
    with psycopg.connect(maintenance_dsn(), autocommit=True) as admin:
        admin.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')


@contextmanager
def fresh_clone(fixture: str = "f0") -> Iterator[str]:
    """A context-manager form of the `db_name` fixture below, for a caller that needs more than
    one clone alive at once — the fixture form gives exactly one. `db_name` is defined in terms
    of this, not the other way round, so the two can never drift apart. Dropped `WITH (FORCE)`
    on exit regardless of what the caller left connected (`docs/E2E.md` §2, S-46).

    **AC-203's tree invariant runs here**, in the one breath before the `DROP DATABASE` — which
    is literally where `docs/E2E.md` S-126 puts it ("in the teardown of every `core`, `http` and
    `mcp` scenario, beside the `DROP DATABASE ... WITH (FORCE)` those suites already do"). This
    is a better site than the `pytest_runtest_teardown` hook the docs' wording suggests, and the
    difference is not stylistic: a hook implementation runs either side of pytest's own fixture
    finalisation, never *between* finalisation and the drop. Every fixture that touches a clone
    depends on `db_name` — the server subprocesses of `http` and `mcp` included — so by the time
    this `finally` body runs, those subprocesses are dead, their pools are closed, and the store
    is in its final settled state. A hook would be racing them. It also needs no per-suite
    wiring: one call site covers every suite that takes a clone, which is all of them.

    The drop happens whether or not the invariant held: a corrupt clone is still a clone, and
    AC-090 ("the harness refuses to leave one behind") is not suspended because AC-203 failed.
    The violation is re-raised afterwards, out of the fixture finaliser, which is what fails the
    scenario in its `teardown` phase — `tests/harness/runner.py` already merges all three phases
    per scenario, so a scenario whose body passed and whose teardown found corruption is
    reported FAIL, which is exactly what AC-203 asks for."""
    template = ensure_template(fixture)
    name = _new_clone_name()
    with psycopg.connect(maintenance_dsn(), autocommit=True) as admin:
        # Shared side of the rebuild lock (see `_ensure_template_locked`): any number of clones
        # may be taken at once, but none of them overlaps a sibling process's rebuild of the same
        # template. Without it a rebuild's `DROP ... WITH (FORCE)` could land between the
        # `ensure_template` above and the `CREATE DATABASE` below, and this clone would fail with
        # a bare "database does not exist" that reads like a harness bug.
        admin.execute("SELECT pg_advisory_lock_shared(%s, %s)", (_LOCK_CLASS, _lock_key(template)))
        try:
            admin.execute(f'CREATE DATABASE "{name}" TEMPLATE "{template}"')
        finally:
            admin.execute(
                "SELECT pg_advisory_unlock_shared(%s, %s)", (_LOCK_CLASS, _lock_key(template))
            )
    try:
        yield name
    finally:
        violation: BaseException | None = None
        try:
            tree_invariant.check_dsn(_env_dsn(name), context=f"clone {name}")
        except tree_invariant.TreeInvariantViolated as exc:
            violation = exc
        _drop_database(name)
        if violation is not None:
            raise violation


@pytest.fixture
def db_name() -> Iterator[str]:
    """A fresh clone of the F0 template, unique to this test."""
    with fresh_clone("f0") as name:
        yield name


@pytest.fixture
def db_dsn(db_name: str) -> str:
    """`db_name` as a full libpq URL — for a test that hands a DSN to a subprocess (the `http`
    and `mcp` suites point a server subprocess at this) instead of opening its own connection."""
    return _env_dsn(db_name)


@pytest.fixture
def db(db_dsn: str) -> Iterator[psycopg.Connection]:
    """An open connection to a fresh clone. Closed before `db_name`'s teardown drops the
    database — pytest tears fixtures down in the reverse of their setup order, so `db` (which
    depends on `db_dsn`, which depends on `db_name`) closes its connection before `db_name`'s
    own finalizer runs, for free."""
    conn = psycopg.connect(db_dsn, autocommit=True)
    try:
        yield conn
    finally:
        conn.close()


# --- Playwright: one driver, process-wide -------------------------------------------------------
#
# `tests/ui/conftest.py` and `tests/uidiff/conftest.py` each used to define their own
# session-scoped `playwright_driver`/`browser` pair, byte-for-byte identical (raw `playwright`,
# `sync_playwright()`, `chromium.launch(headless=True)` — neither suite uses the `pytest-playwright`
# plugin, see `tests/ui/conftest.py`'s own header comment on why). That was harmless as long as the
# two suites only ever ran as separate `pytest` invocations (which is what `tests.harness.runner`
# does, one subprocess per suite) — but a single combined run (`PYTEST="tests/ui tests/uidiff"
# scripts/e2e-run.sh`, the shape WP-E's own definition of done requires) collects both suites into
# one process, and "session" scope means both fixtures come alive in that one process without ever
# tearing down in between. `sync_playwright()`'s sync wrapper cannot be entered a second time in a
# process that still has an earlier instance open — Playwright's own guard for that is the
# "It looks like you are using Playwright Sync API inside the asyncio loop" error, which is what a
# combined run produced from every suite-G scenario that touches `browser`. One fixture pair,
# hoisted here so both suites resolve the same session-scoped instance regardless of which order
# or combination they run in, fixes the collision at the root rather than working around it twice.
@pytest.fixture(scope="session")
def playwright_driver() -> Iterator[Playwright]:
    with sync_playwright() as p:
        yield p


@pytest.fixture(scope="session")
def browser(playwright_driver: Playwright) -> Iterator[Browser]:
    b = playwright_driver.chromium.launch(headless=True)
    try:
        yield b
    finally:
        b.close()


# --- whole-cluster bookkeeping, for the leak audit and the full-run sweep ----------------------


def list_test_databases() -> list[str]:
    """Every database on the cluster whose name starts with `verticals_t` — clones and templates
    alike. Filtered in Python, not via SQL `LIKE` (`_` is a wildcard there, and `verticals_t`
    contains one) — deliberate: a wildcard match risks catching a name nobody meant to include.
    """
    with psycopg.connect(maintenance_dsn(), autocommit=True) as admin:
        rows = admin.execute("SELECT datname FROM pg_database").fetchall()
    return [row[0] for row in rows if row[0].startswith(TEST_DB_PREFIX)]


def _is_clone(name: str) -> bool:
    # A clone is "verticals_t_<worker>_<n>_<rand>" — the underscore right after the prefix is
    # the tell. A template is "verticals_tmpl_<fixture>", which also starts with TEST_DB_PREFIX
    # ("verticals_t" is a prefix of "verticals_tmpl" too) but never gets that underscore there.
    return name.startswith(f"{TEST_DB_PREFIX}_")


def drop_leaked_clones() -> int:
    """Drop every *clone* left on the cluster — never a template. `tests/harness/runner.py`
    calls this once, at the end of a full (`--suite`-less) run, to catch a clone whose owning
    test crashed before its own `db_name` teardown ran; `docs/E2E.md` §2's "the harness refuses
    to leave one behind" (AC-090), made true rather than assumed. Templates are infrastructure,
    not test pollution — swept by nothing here, on a full run or a single-suite one alike;
    rebuilding one from scratch costs a full migration for no benefit to anyone still iterating
    locally."""
    names = [n for n in list_test_databases() if _is_clone(n)]
    for name in names:
        _drop_database(name)
    return len(names)


# --- report hooks: GATE, VERTICALS_FORCE_FAIL, artifact capture --------------------------------


@pytest.hookimpl(wrapper=True)
def pytest_runtest_makereport(item: pytest.Item, call: pytest.CallInfo):
    report = yield
    if call.when == "call":
        sid = scenario_id_of(item.name)
        forced = os.environ.get(_FORCE_FAIL_ENV)
        if forced and sid == forced and report.outcome == "passed":
            # VERTICALS_FORCE_FAIL is read in exactly this one place (docs/E2E.md §12, S-124).
            line = item.location[1] + 1 if item.location[1] is not None else 0
            detail = FailDetail(
                scenario_id=sid,
                suite=suite_of(item.nodeid),
                name=item.name,
                file=f"{item.location[0]}:{line}",
                assert_expr=f"os.environ[{_FORCE_FAIL_ENV!r}] == {sid!r}",
                expected="pass",
                actual="forced fail",
                detail=(
                    f"{_FORCE_FAIL_ENV}={forced} requested this scenario fail; the scenario's "
                    f"own assertions were never evaluated."
                ),
            )
            report.outcome = "failed"
            report.longrepr = format_fail_block(detail)
        elif call.excinfo is not None and call.excinfo.errisinstance(Gated):
            report.outcome = "gate"
            report.gate_reason = call.excinfo.value.reason
        report.artifacts = artifacts_for(item)
    elif call.when == "setup" and call.excinfo is not None and call.excinfo.errisinstance(Gated):
        # A missing precondition is often known before the test body can run — and the place that
        # knows it is a fixture, which reports in the `setup` phase, not `call`. Without this
        # branch a `gate()` raised from a fixture surfaces as a plain ERROR: the runner would count
        # it under `fail`, which is precisely the confusion GATE exists to prevent (both refuse to
        # certify; only one claims the code is broken). `runner.py`'s own per-scenario merge
        # already reads all three phases and already honours `outcome == "gate"` from any of them
        # (`for when in ("setup", "call", "teardown")`), so nothing downstream needed changing —
        # this hook was the only place that assumed a gate could only come from a test body.
        # Deliberately not extended to `teardown`: a gate discovered after the test already ran
        # would overwrite a real verdict the run had legitimately earned.
        report.outcome = "gate"
        report.gate_reason = call.excinfo.value.reason
    return report


def pytest_report_teststatus(
    report: pytest.TestReport, config: pytest.Config
) -> tuple[str, str, str] | None:
    """Gives pytest's terminal reporter a bucket for the `gate` outcome. Returning `None` for
    everything else defers to pytest's own default (pass/fail/skip) — this only adds a case,
    never overrides one."""
    if getattr(report, "outcome", None) == "gate":
        return "gate", "G", "GATED"
    return None
