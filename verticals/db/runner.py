"""Migration runner. Forward-only, one transaction per invocation, tracked in `schema_version`.

    python -m verticals.db.runner up            # apply everything outstanding
    python -m verticals.db.runner up --to 2      # apply through 002_*.sql only
    python -m verticals.db.runner status         # print current version and pending files

Reads `VERTICALS_DATABASE_URL` from the environment — the .env contract is frozen in
docs/IMPLEMENTATION.md §6.3; this module invents no other variable. Migration files live in
`verticals/db/migrations/NNN_name.sql`, applied in ascending numeric order. There is no `down`:
a mistake is a new numbered file (docs/IMPLEMENTATION.md §6.4). Nobody has ever been glad they
ran a down-migration on a database holding their own goals.

One transaction for the whole invocation, not one per file — AC-005's own name is "fails
loudly instead of half-migrating," and half-migrating is exactly what one-transaction-per-file
produces the moment two files are pending at once: file N commits, file N+1 fails, and the
database is left with file N's tables and none of file N+1's. Verified against a role that can
create tables but not extensions (schema-level CREATE granted, database-level CREATE withheld,
which is genuinely how `CREATE EXTENSION` is gated on Postgres 16 — see IMPLEMENTATION.md
§0.3 IR-05's neighbouring note on aborted transactions for the same style of trap): under the
old per-file design `001_init.sql` committed and `002_trgm.sql` failed, leaving two live tables
behind. A single connection, a single `conn.transaction()` spanning bootstrap and every pending
file, fixes it — a failure anywhere in the invocation rolls back everything the invocation did,
and a later invocation (after the privilege is fixed) starts from `current_version()` exactly as
before, since nothing from the failed attempt was ever committed. This does not reintroduce
`down`: it is ordinary atomicity of one `up` call, not a mechanism for undoing history that was
already committed by an earlier, successful call.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path

import psycopg

DEFAULT_MIGRATIONS_DIR = Path(__file__).parent / "migrations"

_FILENAME_RE = re.compile(r"^(\d{3,})_[A-Za-z0-9_]+\.sql$")

# Independent of any numbered migration file, so the runner never has to apply a migration
# in order to find out what it has already applied. Idempotent: safe on every invocation.
_BOOTSTRAP_SQL = """
CREATE TABLE IF NOT EXISTS schema_version (
    version    INTEGER PRIMARY KEY,
    name       TEXT NOT NULL,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""


class MigrationError(Exception):
    """Discovery or apply failed. `str(exc)` is the full operator-facing message."""


@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    path: Path

    @property
    def filename(self) -> str:
        return self.path.name


def discover_migrations(migrations_dir: Path) -> list[Migration]:
    """Every `NNN_name.sql` in migrations_dir, sorted by numeric version.

    A malformed filename or two files claiming the same version number fail discovery
    itself, loudly — the alternative is applying the wrong file, or applying one of two
    same-numbered files at random depending on directory listing order.
    """
    if not migrations_dir.is_dir():
        return []
    found: dict[int, Migration] = {}
    for path in sorted(migrations_dir.glob("*.sql")):
        m = _FILENAME_RE.match(path.name)
        if not m:
            raise MigrationError(
                f"malformed migration filename: {path.name!r} "
                f"(expected NNN_name.sql, e.g. 001_init.sql)"
            )
        version = int(m.group(1))
        if version in found:
            raise MigrationError(
                f"duplicate migration version {version}: "
                f"{found[version].filename!r} and {path.name!r} both claim it"
            )
        found[version] = Migration(version=version, name=path.stem, path=path)
    return [found[v] for v in sorted(found)]


def _connect(dsn: str) -> psycopg.Connection:
    # autocommit=True is load-bearing, not a style choice: `status`'s bare read
    # (current_version, _table_exists) must not silently open an implicit transaction that
    # nothing then closes. Under autocommit=True a bare read starts and ends in the same
    # instant, and conn.transaction() always opens a genuine top-level transaction on demand
    # — which is what run_up's single whole-invocation transaction requires.
    try:
        return psycopg.connect(dsn, autocommit=True)
    except psycopg.OperationalError as exc:
        raise MigrationError(f"cannot connect to database: {exc}") from exc


def _table_exists(conn: psycopg.Connection, name: str) -> bool:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT 1 FROM information_schema.tables "
            "WHERE table_schema = 'public' AND table_name = %s",
            (name,),
        )
        return cur.fetchone() is not None


def _bootstrap(conn: psycopg.Connection) -> None:
    """Idempotent, and — since the caller always runs this inside its own transaction — as
    atomic as everything else in that transaction: a role that cannot even create
    `schema_version` fails here and rolls back to nothing, same as a role that fails on a
    later file."""
    try:
        with conn.cursor() as cur:
            cur.execute(_BOOTSTRAP_SQL)
    except psycopg.Error as exc:
        raise MigrationError(
            f"FAILED bootstrapping schema_version: {str(exc).strip()}\n"
            "remediation: connect as a role with CREATE on the target schema and retry."
        ) from exc


def read_version(conn: psycopg.Connection) -> int:
    """The bare version read: exactly one statement, and no opinion about a database that has
    no `schema_version` table — it raises `psycopg.errors.UndefinedTable` and lets the caller
    decide what that means.

    Split out of `current_version` for the `/healthz` probe, for two reasons that point the
    same way. A liveness probe is the most frequently executed statement in the system, so
    doubling it to pre-check `information_schema` is a cost paid forever; and S-32 counts
    statements across two probes, so the probe's own contribution being 1 rather than 2 is
    load-bearing on an assertion, not just tidiness.

    The second reason is the more important one. `current_version` answers 0 for a database
    with no `schema_version`, which is right for the CLI — `status` on a fresh database should
    print 0, not crash. It is wrong for a health probe: a database that has never been migrated
    is not healthy at version 0, it is undeployed, and a probe that returns ok for it is exactly
    the probe that lets a broken deploy pass. Raising is the honest signal.

    `api/` calls this rather than writing the SQL itself — ARCHITECTURE.md §2's seam rule, which
    `tests/static/test_seam.py` enforces.
    """
    with conn.cursor() as cur:
        cur.execute("SELECT COALESCE(max(version), 0) FROM schema_version")
        (version,) = cur.fetchone()
        return version


def current_version(conn: psycopg.Connection) -> int:
    """Guarded form, two statements: 0 for a database with no `schema_version` rather than an
    error. This is what the migration CLI wants — see `read_version` above for why the health
    probe deliberately wants the opposite."""
    if not _table_exists(conn, "schema_version"):
        return 0
    return read_version(conn)


def _downgrade_refusal(current: int, requested: int) -> str:
    """`up --to N` with N below the recorded version is a downgrade request, and this runner has
    no down-migrations to serve it with (docs/IMPLEMENTATION.md §6.4, ARCHITECTURE.md §3:
    forward-only). Silently applying nothing and exiting 0 — what the version-comparison filter
    did on its own — is the dangerous answer: the operator asked to go back, was told "applied=0",
    and walks away believing the schema moved. It did not. Refusing loudly and naming the one
    procedure that actually goes backwards (restore from a backup taken at that version) is the
    honest one. `docs/E2E.md` S-116 asserts this rather than assuming it."""
    return (
        f"refusing to migrate down: schema_version is {current}, --to {requested} is below it.\n"
        "This runner is forward-only — there are no down-migrations, so nothing here can undo an "
        "applied file.\n"
        f"remediation: restore from a backup taken at version {requested} "
        "(README 'Backing up and restoring'), then migrate forward again."
    )


def _remediation(migration: Migration, exc: psycopg.Error) -> str:
    """One block naming the file, Postgres's own message and hint, and the exact statement
    text a sufficiently-privileged role must run to unblock it — which, for a migration file
    that does one thing, is simply that file's own SQL, verbatim."""
    diag = getattr(exc, "diag", None)
    primary = (diag.message_primary if diag and diag.message_primary else None) or str(exc).strip().splitlines()[0]
    hint = diag.message_hint if diag else None
    lines = [f"FAILED applying {migration.filename}: {primary}"]
    if hint:
        lines.append(f"hint: {hint}")
    lines.append("remediation: connect as a role with sufficient privilege and run:")
    lines.append(migration.path.read_text().strip())
    lines.append(
        "nothing was committed by this invocation (whole-invocation transaction); "
        "re-run once the remediation above has been applied."
    )
    return "\n".join(lines)


def run_up(dsn: str, migrations_dir: Path = DEFAULT_MIGRATIONS_DIR, to_version: int | None = None) -> int:
    """Apply every pending migration (or through `to_version`). Returns the count applied.

    One connection, one transaction for the entire invocation: bootstrap and every pending
    file share it. A clean exit commits everything at once; any failure rolls back everything
    this invocation did — including files that individually "succeeded" earlier in the same
    call — so a partial run never leaves a half-migrated database (AC-005). Each file's
    `schema_version` row still commits together with that file's own DDL, since neither
    commits at all until the whole invocation does. Raises MigrationError with the full
    remediation text on failure; nothing this invocation touched survives that.
    """
    migrations = discover_migrations(migrations_dir)
    conn = _connect(dsn)
    try:
        applied = 0
        with conn.transaction():
            _bootstrap(conn)
            current = current_version(conn)
            if to_version is not None and to_version < current:
                raise MigrationError(_downgrade_refusal(current, to_version))
            pending = [
                m for m in migrations
                if m.version > current and (to_version is None or m.version <= to_version)
            ]
            for m in pending:
                print(f"applying {m.filename}...", end=" ", file=sys.stdout, flush=True)
                try:
                    conn.execute(m.path.read_text())
                    conn.execute(
                        "INSERT INTO schema_version (version, name) VALUES (%s, %s)",
                        (m.version, m.name),
                    )
                except psycopg.Error as exc:
                    print("FAILED", file=sys.stdout)
                    raise MigrationError(_remediation(m, exc)) from exc
                print("OK", file=sys.stdout)
                applied += 1
        return applied
    finally:
        conn.close()


def print_status(dsn: str, migrations_dir: Path = DEFAULT_MIGRATIONS_DIR) -> None:
    """Read-only: never creates schema_version, so `status` cannot be the thing that mutates
    a database an operator only meant to inspect."""
    migrations = discover_migrations(migrations_dir)
    conn = _connect(dsn)
    try:
        version = current_version(conn) if _table_exists(conn, "schema_version") else 0
        pending = [m.filename for m in migrations if m.version > version]
    finally:
        conn.close()
    print(f"version={version}")
    print(f"pending={','.join(pending) if pending else '(none)'}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m verticals.db.runner")
    sub = parser.add_subparsers(dest="command", required=True)
    up_parser = sub.add_parser("up", help="apply every outstanding migration")
    up_parser.add_argument("--to", type=int, default=None, metavar="N", dest="to_version")
    sub.add_parser("status", help="print current version and pending files")
    args = parser.parse_args(argv)

    dsn = os.environ.get("VERTICALS_DATABASE_URL")
    if not dsn:
        print("VERTICALS_DATABASE_URL is not set", file=sys.stderr)
        return 2

    try:
        if args.command == "up":
            applied = run_up(dsn, to_version=args.to_version)
            print(f"applied={applied}")
        elif args.command == "status":
            print_status(dsn)
    except MigrationError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
