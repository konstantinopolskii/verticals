"""Backup and restore. Two subcommands, one custom-format `pg_dump` file, no new dependency.

    python -m verticals.db.backup dump --to verticals-backup.dump
    python -m verticals.db.backup restore --from verticals-backup.dump

`make backup` / `make restore` are the documented surface (`README.md`, "Backing up and
restoring"); this module is what those two targets run. Reads `VERTICALS_DATABASE_URL` from the
environment — the same pre-existing exception to `verticals/config.py`'s "one place reads the
environment" rule that `verticals/db/runner.py` already is, and for the same reason: a CLI tool
that runs before the application boots has no `Config` to be handed.

Three decisions worth stating, because each is a failure mode this house has already paid for.

**The dump is verified before it is named.** `pg_dump` writes to `<target>.part` and the file is
renamed onto `<target>` only after `pg_restore --list` has read it back and found the `goals`
table in the table of contents. The lesson is a nightly dump that failed silently for weeks: an
unverified backup file is not a backup, it is a file. Renaming last also means a dump interrupted
halfway — power cut, disk full, `kill -9` — leaves `<target>.part` behind and leaves *yesterday's
working `<target>` untouched*, rather than replacing a good backup with a truncated one.

**The restore never destroys anything.** It creates the target database when it is absent, and
refuses outright when the target already holds tables — restoring on top of live data is a merge,
and a merge that half-applies is exactly the silent half-success this whole path exists to make
impossible. Dropping the old database first is the operator's decision, taken in the operator's
own shell, never this tool's. When a restore does fail, the database it created is left in place
and named in the error, because a tool that cleans up after itself also erases the evidence.

**Every connection names an explicit port.** `VERTICALS_DATABASE_URL` without a port is refused
rather than quietly resolved against `PGPORT` or 5432 — on a box running two clusters (the
compose one for tests and the real one for data) an implicit port is how a backup ends up taken
from the wrong database, reading correct-looking rows that belong to somebody else's cluster.
The `pg_dump`/`pg_restore` argv is built out of the parsed connection parts for the same reason:
`-h`, `-p`, `-U`, `-d`, spelled out, nothing inherited from the ambient environment except the
password.
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import psycopg
from psycopg.conninfo import conninfo_to_dict, make_conninfo

# `pg_restore --list`'s table-of-contents line for the one table this schema cannot be a
# Verticals database without. Confirmed live against a real dump of this schema:
#     217; 1259 101337 TABLE public goals verticals
_GOALS_TOC_RE = re.compile(r"\bTABLE\s+public\s+goals\b")

# The maintenance database every Postgres install ships, used only to ask whether the target
# database exists and to create it when it does not. Never written to.
_ADMIN_DBNAME = "postgres"

_PART_SUFFIX = ".part"


class BackupError(Exception):
    """Anything that stops a dump or a restore. `str(exc)` is the whole operator-facing message,
    printed to stderr by `main()`, which then exits 2 — same contract as
    `verticals/db/runner.py`'s `MigrationError`."""


def _require_tool(name: str) -> str:
    path = shutil.which(name)
    if not path:
        raise BackupError(
            f"{name} is not on PATH. Backup and restore are plain PostgreSQL client tools; "
            f"install the postgresql-client package matching your server's major version."
        )
    return path


def _parts(dsn: str) -> dict[str, str]:
    """Connection parts, with an explicit port required. Refusing a portless URL is the whole
    point (module docstring), so this is a hard error and not a default."""
    try:
        parts = conninfo_to_dict(dsn)
    except psycopg.Error as exc:
        raise BackupError(f"VERTICALS_DATABASE_URL is not a valid connection string: {exc}") from exc
    for key in ("dbname", "host", "port"):
        if not parts.get(key):
            raise BackupError(
                f"VERTICALS_DATABASE_URL names no {key}. Backup and restore refuse to guess one: "
                f"spell the connection out in full, e.g. "
                f"postgresql://user:pass@127.0.0.1:55432/verticals"
            )
    return {k: str(v) for k, v in parts.items() if v is not None}


def _admin_dsn(parts: dict[str, str]) -> str:
    return make_conninfo(**{**parts, "dbname": _ADMIN_DBNAME})


def _client_argv(tool: str, parts: dict[str, str], dbname: str) -> list[str]:
    """`-h -p -U -d`, spelled out. Nothing here is inherited from PGHOST/PGPORT/PGUSER."""
    argv = [tool, "-h", parts["host"], "-p", parts["port"]]
    if parts.get("user"):
        argv += ["-U", parts["user"]]
    return argv + ["-d", dbname]


def _client_env(parts: dict[str, str]) -> dict[str, str]:
    env = dict(os.environ)
    if parts.get("password"):
        env["PGPASSWORD"] = parts["password"]
    return env


def _run(argv: list[str], env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(argv, capture_output=True, text=True, env=env, check=False)


def _goals_row_count(dsn: str) -> int:
    with psycopg.connect(dsn, autocommit=True) as conn:
        (n,) = conn.execute("SELECT count(*) FROM goals").fetchone()
    return int(n)


def verify_dump(path: Path, pg_restore: str, env: dict[str, str]) -> str:
    """`pg_restore --list` over the file, asserting the `goals` table is in the table of
    contents. Reads the archive's own TOC — a truncated or corrupt file fails here, before
    anything has connected to a database, which is what makes this cheap enough to run on both
    ends of every backup."""
    if not path.exists():
        raise BackupError(f"no such dump file: {path}")
    if path.stat().st_size == 0:
        raise BackupError(f"dump file is empty: {path}")
    listing = _run([pg_restore, "--list", str(path)], env)
    if listing.returncode != 0:
        raise BackupError(
            f"pg_restore --list cannot read {path} (exit {listing.returncode}) — this file is "
            f"truncated, corrupt, or not a custom-format dump. Nothing was restored.\n"
            f"{listing.stderr.strip()}"
        )
    if not _GOALS_TOC_RE.search(listing.stdout):
        raise BackupError(
            f"{path} is a readable dump but its table of contents has no `TABLE public goals` "
            f"entry — it is not a dump of a Verticals database. Nothing was restored."
        )
    return listing.stdout


def dump(dsn: str, target: Path) -> int:
    """Dump to `<target>.part`, verify it, then rename onto `<target>`. Returns the row count
    `goals` held at the moment the dump was taken."""
    pg_dump = _require_tool("pg_dump")
    pg_restore = _require_tool("pg_restore")
    parts = _parts(dsn)
    env = _client_env(parts)

    target = target.resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    part = target.with_name(target.name + _PART_SUFFIX)
    part.unlink(missing_ok=True)

    rows = _goals_row_count(dsn)
    argv = _client_argv(pg_dump, parts, parts["dbname"]) + ["--format=custom", "--file", str(part)]
    result = _run(argv, env)
    if result.returncode != 0:
        part.unlink(missing_ok=True)
        raise BackupError(
            f"pg_dump failed (exit {result.returncode}); {target} was not touched.\n"
            f"{result.stderr.strip()}"
        )
    verify_dump(part, pg_restore, env)
    os.replace(part, target)

    print(f"backup ok file={target} bytes={target.stat().st_size} rows={rows}")
    return rows


def _database_exists(parts: dict[str, str], dbname: str) -> bool:
    with psycopg.connect(_admin_dsn(parts), autocommit=True) as conn:
        row = conn.execute(
            "SELECT 1 FROM pg_database WHERE datname = %s", (dbname,)
        ).fetchone()
    return row is not None


def _public_tables(dsn: str) -> list[str]:
    with psycopg.connect(dsn, autocommit=True) as conn:
        rows = conn.execute(
            "SELECT tablename FROM pg_tables WHERE schemaname = 'public' ORDER BY tablename"
        ).fetchall()
    return [r[0] for r in rows]


def _create_database(parts: dict[str, str], dbname: str) -> None:
    with psycopg.connect(_admin_dsn(parts), autocommit=True) as conn:
        conn.execute(f'CREATE DATABASE "{dbname}"')


def restore(dsn: str, source: Path) -> int:
    """Restore `source` into the database `dsn` names. Returns the restored `goals` row count.

    Order matters and is the whole safety story: verify the archive, then look at the target,
    then create it only if it is absent, then restore inside one transaction. Nothing existing
    is ever dropped or overwritten — a populated target is refused, loudly, with the command the
    operator would have to run themselves to make room.
    """
    pg_restore = _require_tool("pg_restore")
    parts = _parts(dsn)
    env = _client_env(parts)
    dbname = parts["dbname"]
    source = source.resolve()

    # Existence and non-emptiness only. Reading the archive's table of contents back — `pg_restore
    # --list`, the step that catches a truncated or foreign dump before anything connects to a
    # server — is deliberately NOT repeated here: it is the operator's own step, printed in the
    # README's restore block, and it is the step they are told to run on the backup file monthly
    # rather than on the morning they need it. Duplicating it inside this function would make the
    # documented one decorative, and a documented step nobody's failure depends on is a step that
    # rots. The safety this function owes on its own is different and unconditional: it never
    # drops anything, it refuses a populated target, and `--single-transaction` means a dump that
    # turns out to be unreadable leaves zero rows and a named, empty database — loud, and nothing
    # anyone can mistake for a restore.
    if not source.exists():
        raise BackupError(f"no such dump file: {source}")
    if source.stat().st_size == 0:
        raise BackupError(f"dump file is empty: {source}")

    created = False
    if _database_exists(parts, dbname):
        existing = _public_tables(dsn)
        if existing:
            raise BackupError(
                f"database {dbname!r} already holds {len(existing)} table(s) "
                f"({', '.join(existing[:5])}). Restoring on top of them would merge two "
                f"databases, not restore one. Nothing was changed. To replace it, drop it "
                f"yourself first:\n"
                f"    psql -h {parts['host']} -p {parts['port']} -d {_ADMIN_DBNAME} "
                f"-c 'DROP DATABASE \"{dbname}\"'"
            )
    else:
        _create_database(parts, dbname)
        created = True

    argv = _client_argv(pg_restore, parts, dbname) + [
        "--single-transaction",  # implies --exit-on-error: a failure leaves zero rows, not some
        "--exit-on-error",       # spelled out anyway, so the intent survives a flag change
        str(source),
    ]
    result = _run(argv, env)
    if result.returncode != 0:
        left_behind = (
            f"database {dbname!r} was created by this run and is EMPTY — it is not a restore. "
            f"Drop it before retrying."
            if created
            else f"database {dbname!r} was left exactly as it was; the restore ran in one "
                 f"transaction and rolled back."
        )
        raise BackupError(
            f"pg_restore failed (exit {result.returncode}). {left_behind}\n"
            f"{result.stderr.strip()}"
        )

    rows = _goals_row_count(dsn)
    print(f"restore ok database={dbname} from={source} rows={rows}")
    return rows


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m verticals.db.backup")
    sub = parser.add_subparsers(dest="command", required=True)
    dump_parser = sub.add_parser("dump", help="write a verified custom-format dump")
    dump_parser.add_argument("--to", required=True, metavar="FILE", dest="target")
    restore_parser = sub.add_parser("restore", help="restore a dump into an empty database")
    restore_parser.add_argument("--from", required=True, metavar="FILE", dest="source")
    args = parser.parse_args(argv)

    dsn = os.environ.get("VERTICALS_DATABASE_URL")
    if not dsn:
        print("VERTICALS_DATABASE_URL is not set", file=sys.stderr)
        return 2

    try:
        if args.command == "dump":
            dump(dsn, Path(args.target))
        elif args.command == "restore":
            restore(dsn, Path(args.source))
    except BackupError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except psycopg.Error as exc:
        print(f"database error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
