"""S-122 — backup and restore, performed the way `README.md` says, on a database this test built
and can therefore destroy. Required by AC-166.

**What this proves that S-89 does not.** `tests/pipeline/test_backup.py` proves the *mechanism*:
`pg_dump` under twenty contending writers, restored into a second cluster, digest compared. S-122
proves the *instructions* — the blocks a self-hoster reads in `README.md`, replayed verbatim, with
the database dropped between them. That distinction is the whole scenario: the house lesson behind
AC-166 is a nightly dump that failed silently for weeks, and dumps do not fail silently because
`pg_dump` is broken. They fail because the documented procedure was never once run end to end.

**Both blocks are extracted, never typed.** `tests/pipeline/readme_blocks.py` parses `README.md`
at run time and this file selects blocks out of the `Backing up and restoring` section by content.
Nothing below holds its own copy of a command (AC-162): edit the README's backup block into
something that does not work and this scenario fails, which is the only arrangement under which a
green test says anything about the document.

**A private cluster, always.** The blocks end in `DROP DATABASE`-shaped destruction, and this
suite runs under xdist beside scenarios using the shared `docker-compose.test.yml` cluster on port
55432. So this file boots its own throwaway postmaster (`initdb` into a temp dir, unix socket
only, `-h ''`, an OS-assigned port) and points `VERTICALS_DATABASE_URL` at it. Cluster machinery is
duplicated from `test_backup.py`'s S-89 rather than imported — this suite's standing convention
for a scenario that owns its whole stack (`test_schema_parity.py`: "this file owns its whole stack
independently, on purpose"), and S-89's two hard-won fixes to `docs/E2E.md` §2's literal recipe
(`-p 0` is not a port; a socket directory under `tmp_path` blows macOS's 103-byte ceiling) are
carried over verbatim rather than rediscovered.

**One `MAKEFLAGS=-e`, declared rather than hidden.** The blocks say `make backup` and read
`VERTICALS_DATABASE_URL` from the environment. This repository's `Makefile` does `include .env`,
and a GNU make variable set in the makefile beats the environment — so on a developer checkout
holding a real `.env`, replaying `make backup` verbatim would dump *the shared compose cluster*,
which is precisely the "never point a dump at a cluster you did not create" rule. `MAKEFLAGS=-e`
in the child environment restores the ordinary precedence (environment wins). The block text is
still verbatim; what the test controls is the environment, which is exactly what a fresh box
differs by. Asserted, not assumed: the first thing the scenario does is confirm the backup landed
against the private cluster's row count and not the shared cluster's.

**One test function, not four.** The runner runs this suite with `-n auto` and the default `load`
distribution, so two test functions in this file could execute in two processes at once — and the
README's block names a fixed path (`./verticals-backup.dump`) in the repository root, which two
processes cannot share. The scenario is one scenario; it runs as one function, in four named
phases, each printing its own line.

Run standalone:
    .venv/bin/python -m pytest tests/pipeline/test_s122_backup_readme.py -v -s
"""

from __future__ import annotations

import os
import random
import re
import shutil
import socket
import subprocess
import tempfile
import threading
import time
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import psycopg
import pytest

from verticals.core import goals, moves
from verticals.db import runner
from tests.harness.report import gate
from tests.harness.tree_invariant import violations as _tree_invariant_violations
from tests.pipeline.readme_blocks import Fence, read_fences

REPO_ROOT = Path(__file__).resolve().parents[2]
F2_SQL = REPO_ROOT / "tests" / "fixtures" / "f2_synth.sql"

SECTION = "Backing up and restoring"
DBNAME = "verticals_t_s122"
OWNER = "t1"

# The path the README's own blocks name. Not configurable here on purpose: a test that overrode
# it would stop replaying the documented command and start replaying a variant of it.
DUMP_PATH = REPO_ROOT / "verticals-backup.dump"

WRITER_COUNT = 20
_PAD_ROW_COUNT = 120_000  # S-89's measured number: widens pg_dump's window past the writers' gap
_WARMUP_SECONDS = 0.3
_COOLDOWN_SECONDS = 0.2
_JOIN_TIMEOUT = 10.0
_MAX_ITERATIONS_PER_WRITER = 5000
_RETRIABLE = (psycopg.errors.DeadlockDetected, psycopg.errors.SerializationFailure)

_VERSION_RE = re.compile(r"PostgreSQL\)?\s+(\d+)\.")


# --- the private cluster (duplicated from S-89, module docstring) --------------------------------


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _sh(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
    return subprocess.run(argv, capture_output=True, text=True, **kwargs)  # type: ignore[arg-type]


class _PrivateCluster:
    def __init__(self, tmp_root: Path, role: str) -> None:
        self.role = role
        self.pgdata = tmp_root / "pg122"
        self.pg_log = tmp_root / "pg122.log"
        self.sock_dir = Path(tempfile.mkdtemp(prefix="hz122-"))
        self.port = _free_port()
        self._started = False

    def start(self, initdb: str, pg_ctl: str) -> None:
        r = _sh([initdb, "-D", str(self.pgdata), "--auth=trust", "-U", self.role])
        if r.returncode != 0:
            raise RuntimeError(f"initdb failed:\n{r.stdout}\n{r.stderr}")
        r = _sh(
            [
                pg_ctl, "-D", str(self.pgdata),
                "-o", f"-p {self.port} -k {self.sock_dir} -h '' -c deadlock_timeout=50ms",
                "-l", str(self.pg_log), "-w", "start",
            ]
        )
        if r.returncode != 0:
            log = self.pg_log.read_text() if self.pg_log.exists() else "(no log)"
            raise RuntimeError(f"pg_ctl start failed:\n{r.stdout}\n{r.stderr}\nlog:\n{log}")
        self._started = True

    def dsn(self, dbname: str) -> str:
        return f"postgresql://{self.role}@/{dbname}?host={self.sock_dir}&port={self.port}"

    def admin_dsn(self) -> str:
        return self.dsn("postgres")

    def create_database(self, name: str) -> None:
        with psycopg.connect(self.admin_dsn(), autocommit=True) as conn:
            conn.execute(f'CREATE DATABASE "{name}"')

    def drop_database(self, name: str) -> None:
        with psycopg.connect(self.admin_dsn(), autocommit=True) as conn:
            conn.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')

    def database_exists(self, name: str) -> bool:
        with psycopg.connect(self.admin_dsn(), autocommit=True) as conn:
            return conn.execute(
                "SELECT 1 FROM pg_database WHERE datname = %s", (name,)
            ).fetchone() is not None

    def stop(self, pg_ctl: str) -> None:
        if not self._started:
            return
        _sh([pg_ctl, "-D", str(self.pgdata), "-m", "fast", "-t", "30", "-w", "stop"])
        self._started = False

    def pid_survives(self) -> bool:
        return bool(_sh(["pgrep", "-f", str(self.pgdata)]).stdout.strip())

    def cleanup_dirs(self) -> None:
        shutil.rmtree(self.pgdata, ignore_errors=True)
        shutil.rmtree(self.sock_dir, ignore_errors=True)


@dataclass
class _Setup:
    error: str | None
    cluster: _PrivateCluster | None = None


@pytest.fixture(scope="module")
def cluster(tmp_path_factory: pytest.TempPathFactory) -> Iterator[_Setup]:
    """Boots once. The version check is live — it asks the *running server* for its own
    `server_version_num` and compares against the `pg_dump`/`pg_restore` the README's own commands
    will resolve off PATH, because the failure being guarded is a PATH with two Postgres installs
    on it, which reads like a product bug and is not one."""
    tools = {n: shutil.which(n) for n in ("initdb", "pg_ctl", "pg_dump", "pg_restore", "psql", "make")}
    missing = [n for n, p in tools.items() if not p]
    if missing:
        yield _Setup(error=f"S-122 needs {', '.join(missing)} on PATH — it owns a private cluster")
        return

    tmp_root = tmp_path_factory.mktemp("s122")
    node = _PrivateCluster(tmp_root, "s122")
    started = False
    try:
        node.start(tools["initdb"], tools["pg_ctl"])
        started = True
        with psycopg.connect(node.admin_dsn(), autocommit=True) as conn:
            (num,) = conn.execute("SHOW server_version_num").fetchone()
        server_major = str(int(num) // 10000)
        for name in ("pg_dump", "pg_restore"):
            out = _sh([tools[name], "--version"]).stdout
            m = _VERSION_RE.search(out)
            if not m or m.group(1) != server_major:
                yield _Setup(
                    error=(
                        f"{name} reports {out.strip()!r} against a server reporting major "
                        f"{server_major} — refusing to trust a version-mismatched client pair"
                    )
                )
                return
        yield _Setup(error=None, cluster=node)
    finally:
        if started:
            node.stop(tools["pg_ctl"])
        survives = node.pid_survives() if started else False
        node.cleanup_dirs()
        assert not survives, "S-122 cluster process survived teardown"


# --- README block selection ---------------------------------------------------------------------


def _section_fences() -> list[Fence]:
    return [f for f in read_fences() if f.section == SECTION and f.is_executable_language]


def _one(fences: list[Fence], needle: str) -> Fence:
    hits = [f for f in fences if needle in f.body]
    assert len(hits) == 1, (
        f"expected exactly one block under {SECTION!r} containing {needle!r}, found {len(hits)} "
        f"(README.md lines {[f.line_no for f in hits]})"
    )
    return hits[0]


def _block_env(dsn: str) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if k != "BACKUP_FILE"}
    env["VERTICALS_DATABASE_URL"] = dsn
    env["MAKEFLAGS"] = "-e"  # module docstring: the checkout's own .env must not win
    return env


def _run_block(body: str, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    """One block, one bash, `-e -o pipefail` so a failing line anywhere in a multi-line block is
    the block's exit status — otherwise a README block could 'pass' on its last line alone."""
    return subprocess.run(
        ["bash", "-e", "-o", "pipefail", "-c", body],
        capture_output=True, text=True, cwd=str(REPO_ROOT), env=env, check=False,
    )


# --- database helpers ----------------------------------------------------------------------------


def _digest(conn: psycopg.Connection) -> str:
    (value,) = conn.execute(
        "SELECT md5(string_agg(goals::text, '|' ORDER BY id)) FROM goals"
    ).fetchone()
    return value


def _count(conn: psycopg.Connection) -> int:
    (n,) = conn.execute("SELECT count(*) FROM goals").fetchone()
    return int(n)


def _invariant_violations(dsn: str) -> list[str]:
    with psycopg.connect(dsn, autocommit=True) as conn:
        owners = [r[0] for r in conn.execute("SELECT DISTINCT owner FROM goals").fetchall()]
        out: list[str] = []
        for owner in owners:
            out += _tree_invariant_violations(conn, owner)
    return out


def _load_f2(dsn: str) -> None:
    runner.run_up(dsn)
    with psycopg.connect(dsn, autocommit=True) as conn:
        conn.execute(F2_SQL.read_text())
        conn.execute("ANALYZE goals")


# --- the writer burst (S-89's condition, reused for S-122's concurrent clause) --------------------


def _writer_loop(
    dsn: str, parents: tuple[str, str], leaves: list[str], stop: threading.Event, seed: int,
    op_log: list[float], errors: list[BaseException], lock: threading.Lock,
) -> None:
    rng = random.Random(seed)
    n = 0
    with psycopg.connect(dsn, autocommit=True) as conn:
        while not stop.is_set() and n < _MAX_ITERATIONS_PER_WRITER:
            try:
                if rng.random() < 0.5:
                    moves.reparent(
                        conn, owner=OWNER, id=rng.choice(leaves), parent_id=rng.choice(parents)
                    )
                else:
                    goals.create(
                        conn, owner=OWNER, title=f"churn {seed}.{n}", parent_id=rng.choice(parents)
                    )
            except _RETRIABLE:
                continue  # Postgres broke a genuine cycle; retrying is what a real client does
            except Exception as exc:  # noqa: BLE001 — collected and asserted on by the caller
                with lock:
                    errors.append(exc)
                break
            else:
                with lock:
                    op_log.append(time.monotonic())
            n += 1


# --- the scenario ---------------------------------------------------------------------------------


def test_s122_backup_and_restore_the_way_the_readme_says(cluster: _Setup) -> None:
    if cluster.error:
        gate(cluster.error)
    node = cluster.cluster
    assert node is not None

    fences = _section_fences()
    assert fences, f"README section {SECTION!r} carries no executable block"
    backup_block = _one(fences, "make backup")
    restore_block = _one(fences, "make restore")
    drop_block = _one(fences, "DROP DATABASE")

    # AC-166 names the verification step and S-122 requires it to be *in the block*: the restore
    # block must read the archive back before touching a database. Phase 3 below proves the step
    # is load-bearing rather than decorative by deleting it and watching the guarantee break.
    verify_lines = [
        ln for ln in restore_block.body.splitlines() if "pg_restore --list" in ln
    ]
    assert len(verify_lines) == 1, (
        f"the restore block must carry exactly one `pg_restore --list` verification line, "
        f"found {len(verify_lines)}: {restore_block.body!r}"
    )
    assert "count(*)" in restore_block.body, (
        "the restore block must also check row count after restoring — AC-166 is 'restore, "
        "compare', not 'restore'"
    )
    # The drop step is documentation, not something this scenario replays (it names the compose
    # cluster's own host and port). It must at least spell a port out: an implicit-port DROP
    # DATABASE in a README is a loaded gun on any box running two clusters.
    assert re.search(r"-p\s+\d+", drop_block.body), (
        f"the documented DROP DATABASE names no explicit port: {drop_block.body!r}"
    )

    env = _block_env(node.dsn(DBNAME))
    DUMP_PATH.unlink(missing_ok=True)
    try:
        _phase1_round_trip(node, env, backup_block, restore_block)
        _phase2_corrupt_dumps(node, env, restore_block)
        _phase3_verification_is_load_bearing(node, env, restore_block)
        _phase4_concurrent(node, env, backup_block, restore_block)
    finally:
        DUMP_PATH.unlink(missing_ok=True)
        DUMP_PATH.with_suffix(".dump.part").unlink(missing_ok=True)
        node.drop_database(DBNAME)


def _phase1_round_trip(
    node: _PrivateCluster, env: dict[str, str], backup_block: Fence, restore_block: Fence
) -> None:
    """Backup block verbatim, `DROP DATABASE`, restore block verbatim, compare."""
    node.drop_database(DBNAME)
    node.create_database(DBNAME)
    dsn = node.dsn(DBNAME)
    _load_f2(dsn)
    with psycopg.connect(dsn, autocommit=True) as conn:
        source_count, source_digest = _count(conn), _digest(conn)
    assert source_count == 49, f"F2 is 49 rows, got {source_count}"

    backup = _run_block(backup_block.body, env)
    assert backup.returncode == 0, f"README backup block failed:\n{backup.stdout}\n{backup.stderr}"
    assert DUMP_PATH.exists() and DUMP_PATH.stat().st_size > 0, "backup block produced no dump"
    # The dump came from the private cluster and not from the developer's own .env database —
    # the MAKEFLAGS=-e claim in the module docstring, asserted rather than trusted.
    assert f"rows={source_count}" in backup.stdout, (
        f"backup reported a row count that is not this cluster's: {backup.stdout!r}"
    )

    node.drop_database(DBNAME)
    assert not node.database_exists(DBNAME)

    restore = _run_block(restore_block.body, env)
    assert restore.returncode == 0, (
        f"README restore block failed:\n{restore.stdout}\n{restore.stderr}"
    )

    with psycopg.connect(dsn, autocommit=True) as conn:
        restored_count, restored_digest = _count(conn), _digest(conn)
    assert restored_count == source_count, f"{source_count} rows out, {restored_count} back"
    assert restored_digest == source_digest, "restored rows differ from the source rows"
    assert _invariant_violations(dsn) == [], "tree invariant violated in the restored database"
    print(
        f"S-122 phase 1: source rows={source_count} digest={source_digest}; "
        f"restored rows={restored_count} digest={restored_digest}; dump "
        f"{DUMP_PATH.stat().st_size} bytes"
    )


def _write_corrupt(kind: str, good: bytes) -> int:
    """Two shapes of broken dump, both of which a disk or a network produces on its own: a file
    that stops halfway (interrupted write) and a file of the right size full of the wrong bytes."""
    if kind == "truncated":
        payload = good[: max(1, len(good) // 3)]
    else:
        payload = b"\x00garbage" * (len(good) // 8 or 1)
    DUMP_PATH.write_bytes(payload)
    return len(payload)


def _phase2_corrupt_dumps(node: _PrivateCluster, env: dict[str, str], restore_block: Fence) -> None:
    """A corrupt dump must fail loudly and change nothing. The database is absent when the block
    runs, so "changed nothing" is checkable exactly: it must still be absent afterwards."""
    good = DUMP_PATH.read_bytes()
    for kind in ("truncated", "garbage"):
        node.drop_database(DBNAME)
        size = _write_corrupt(kind, good)
        result = _run_block(restore_block.body, env)
        assert result.returncode != 0, (
            f"the {kind} dump restored successfully — a silent half-success is the failure this "
            f"scenario exists to rule out:\n{result.stdout}"
        )
        combined = result.stdout + result.stderr
        assert "pg_restore" in combined, f"failure named nothing readable:\n{combined}"
        assert not node.database_exists(DBNAME), (
            f"the {kind} dump left database {DBNAME!r} behind — the restore was destructive on a "
            f"file it could not read"
        )
        print(
            f"S-122 phase 2 [{kind}, {size} bytes]: exit {result.returncode}, database absent, "
            f"first line: {combined.strip().splitlines()[0][:120]!r}"
        )
    DUMP_PATH.write_bytes(good)


def _phase3_verification_is_load_bearing(
    node: _PrivateCluster, env: dict[str, str], restore_block: Fence
) -> None:
    """S-122's own clause: remove the verification step from a *copy* of the block and the
    scenario must fail. Phase 2's assertion is "the database is still absent"; with the
    `pg_restore --list` line deleted, that assertion is false — `make restore` gets as far as
    creating the database before pg_restore chokes, leaving an empty database that looks like a
    restore and holds nothing. Both halves are asserted here, so the day someone deletes that line
    from the README, phase 2 turns red rather than quietly proving less."""
    good = DUMP_PATH.read_bytes()
    mutated = "\n".join(
        ln for ln in restore_block.body.splitlines() if "pg_restore --list" not in ln
    )
    assert mutated != restore_block.body

    node.drop_database(DBNAME)
    _write_corrupt("truncated", good)
    result = _run_block(mutated, env)
    assert result.returncode != 0
    left_behind = node.database_exists(DBNAME)
    node.drop_database(DBNAME)
    DUMP_PATH.write_bytes(good)

    assert left_behind, (
        "with the verification line removed the corrupt restore still left nothing behind — the "
        "step this scenario calls load-bearing is decorative, and the assertion in phase 2 proves "
        "nothing about it"
    )
    print(
        "S-122 phase 3: with `pg_restore --list` deleted from the block, the same truncated dump "
        f"left database {DBNAME!r} created and empty (exit {result.returncode}) — the verification "
        "step is what makes the failure non-destructive"
    )


def _phase4_concurrent(
    node: _PrivateCluster, env: dict[str, str], backup_block: Fence, restore_block: Fence
) -> None:
    """The same documented backup, taken while twenty writers reparent and create — S-89's
    condition, applied to the README's command rather than to a hand-written `pg_dump`."""
    node.drop_database(DBNAME)
    node.create_database(DBNAME)
    dsn = node.dsn(DBNAME)
    _load_f2(dsn)
    with psycopg.connect(dsn, autocommit=True) as conn:
        p1 = goals.create(conn, owner=OWNER, title="Churn parent A").goal.id
        p2 = goals.create(conn, owner=OWNER, title="Churn parent B").goal.id
        leaves = [
            goals.create(
                conn, owner=OWNER, title=f"Churn leaf {i}", parent_id=(p1 if i < 3 else p2)
            ).goal.id
            for i in range(6)
        ]
        baseline = _count(conn)
        # Bulk filler so pg_dump's window is wide enough for the writers to land inside it —
        # S-89's measured finding, reused: schema-valid roots under an owner nobody churns.
        conn.execute(
            "INSERT INTO goals (id, owner, parent_id, path, depth, parked_from_vertical, title)"
            " SELECT 'pad-' || gs, 'bulkpad', NULL, '/pad-' || gs || '/', 0, 'life',"
            " 'padding row ' || gs"
            " FROM generate_series(1, %(n)s) AS gs",
            {"n": _PAD_ROW_COUNT},
        )

    stop = threading.Event()
    op_log: list[float] = []
    errors: list[BaseException] = []
    lock = threading.Lock()
    threads = [
        threading.Thread(
            target=_writer_loop, args=(dsn, (p1, p2), leaves, stop, i, op_log, errors, lock)
        )
        for i in range(WRITER_COUNT)
    ]
    for t in threads:
        t.start()
    time.sleep(_WARMUP_SECONDS)

    t0 = time.monotonic()
    backup = _run_block(backup_block.body, env)
    t1 = time.monotonic()

    time.sleep(_COOLDOWN_SECONDS)
    stop.set()
    for t in threads:
        t.join(timeout=_JOIN_TIMEOUT)

    assert not any(t.is_alive() for t in threads), "a writer thread outlived the join timeout"
    assert errors == [], f"{len(errors)} writer error(s); first: {errors[0]!r}"
    assert backup.returncode == 0, f"backup under load failed:\n{backup.stdout}\n{backup.stderr}"
    during = [ts for ts in op_log if t0 <= ts <= t1]
    assert during, (
        f"none of {len(op_log)} writer ops landed inside the {t1 - t0:.3f}s backup window — this "
        f"run proves nothing about a backup taken under load"
    )

    node.drop_database(DBNAME)
    restore = _run_block(restore_block.body, env)
    assert restore.returncode == 0, f"restore after a loaded backup failed:\n{restore.stderr}"
    with psycopg.connect(dsn, autocommit=True) as conn:
        restored = _count(conn)
    assert restored >= baseline + _PAD_ROW_COUNT, (
        f"restored {restored} rows, fewer than the {baseline + _PAD_ROW_COUNT} that existed before "
        f"the burst started — the dump's snapshot predates its own setup data"
    )
    assert _invariant_violations(dsn) == [], "tree invariant violated after a concurrent backup"
    print(
        f"S-122 phase 4: {len(op_log)} writer ops, {len(during)} inside the {t1 - t0:.3f}s backup "
        f"window; restored {restored} rows (baseline {baseline + _PAD_ROW_COUNT}), tree invariant "
        f"clean"
    )
