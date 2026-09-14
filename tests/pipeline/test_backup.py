"""S-89 — a pg_dump/pg_restore round trip against a private cluster pair this test owns outright,
including a dump taken while 20 concurrent, genuinely contending writers are still running.
`docs/E2E.md` §2 ("Scenarios that own the server, and the serialized tail") puts S-89 alongside
S-45 and S-126 as one of the three scenarios that may not touch the shared
`docker-compose.test.yml` cluster (`pg_ctl`/a live `pg_dump` there would race every other parallel
worker's own database) and never uses the CI container (`postgres:16-alpine` has neither the
`initdb`/`pg_ctl`/`pg_dump`/`pg_restore` binaries nor the permission to run them).

**Two clusters, not one.** §2's own summary table calls this scenario "dumps it under 20
concurrent writers, restores into a second instance" — Postgres terminology for a second running
server, not merely a second database next to the one this test already has open. A backup
procedure that only ever restores onto the box it dumped from proves less than the house lesson
(a nightly dump that failed silently for weeks) actually needs: a dump that only replays next to
its own source has never been tested as a *backup* at all. So this file builds a source cluster
(the one the 20 writers hit, and the one `pg_dump` reads) and a destination cluster (the one
`pg_restore` writes into), both throwaway, both `initdb`'d fresh into a temp directory and torn
down at module teardown.

**Cluster machinery duplicated from `tests/http/test_availability.py`'s S-45, not imported** —
this suite's own established precedent for a scenario that owns its whole stack
(`test_schema_parity.py`'s "self-contained" module docstring, and that file's own "this file owns
its whole stack independently, on purpose"). Two fixes S-45 already found by running the literal
`docs/E2E.md` §2 recipe, reapplied verbatim here rather than rediscovered: `-p 0` is not a valid
Postgres port (bind an ephemeral TCP port first, hand `pg_ctl` the concrete number, then `-h ''`
so the only path in is the unix socket); a `unix_socket_directories` path under pytest's own
`tmp_path` blows macOS's 103-byte socket-path ceiling (a short-prefixed `tempfile.mkdtemp()`
instead — `PGDATA` itself carries no such limit). `--auth=trust`, deliberately, for the same
reason S-45 gives: the only path in is a unix socket inside a mode-0700 directory this OS user
alone can reach, and a password would protect nothing a filesystem permission does not already
protect. Both clusters use the *same* bootstrap role name (`s89`) even though they are two
unrelated postmasters — deliberately, so a dump's `ALTER ... OWNER TO s89` / `GRANT ... TO s89`
statements resolve cleanly on the destination without `--no-owner`, which would quietly hide a
real ownership mismatch class of restore failure instead of proving there isn't one.

**The tree invariant (five counts, all zero — named once in `docs/E2E.md` under S-126, and
implemented once already at `tests/core/test_tree.py`'s own `_tree_invariant_violations`, see its
`AC-203` comments around lines 84 and 685) is duplicated below, not imported.**
`tests/http/test_concurrency.py` already faced this exact question — another suite needing the
same invariant — and answered it in its own docstring: "Duplicated from tests/core/test_tree.py
rather than imported across the suite boundary (this suite's established convention — see
tests/http/conftest.py's own f2_dsn)." Checked directly: nothing mechanical stops the import —
there is no `__init__.py` boundary guarding `tests/core`, `pyproject.toml`'s `pythonpath = ["."]`
is exactly what makes `tests.harness.report` and `tests.conftest` importable from every suite
already, and `from tests.core.test_tree import _tree_invariant_violations` resolves cleanly today
(verified live, not assumed). So this is a choice, not a limitation, and the smaller move is to
keep making the same choice the codebase already made twice: one more copy in a family that
already has two is cheaper to reason about than the first cross-suite import in the catalogue,
because every suite that carries its own copy can be read — and broken — in isolation, which is
this suite's own point (`test_schema_parity.py`'s "self-contained" precedent, again). Copied here
from `test_concurrency.py`'s own text (the closer precedent — another suite, not `core` itself),
`vertical IS NOT NULL` scoping and all.

**Digest.** `SELECT md5(string_agg(goals::text, '|' ORDER BY id)) FROM goals` — the same full-row,
order-independent fingerprint every suite in this catalogue re-derives locally rather than
imports (`tests/core/test_tree.py::_digest`, `tests/pipeline/test_import.py::_digest`,
`tests/mcp/conftest.py::full_table_digest`, `tests/http/test_limits.py`, ...); three lines, the
same "not a cross-module reach into another file's private helper" precedent
`test_export.py` states for its own three-line `_dsn_for`.

Run standalone:
    .venv/bin/python -m pytest tests/pipeline/test_backup.py -v -s
"""

from __future__ import annotations

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
from tests.harness.report import artifact, gate

REPO_ROOT = Path(__file__).resolve().parents[2]
F2_SQL = REPO_ROOT / "tests" / "fixtures" / "f2_synth.sql"

WRITER_COUNT = 20
_WARMUP_SECONDS = 0.3
_COOLDOWN_SECONDS = 0.2
_JOIN_TIMEOUT = 10.0
_MAX_ITERATIONS_PER_WRITER = 5000
_LOCK_POLL_SECONDS = 0.005

# F2's own 49-57 rows are gone from pg_dump before the OS has finished scheduling the call --
# measured live against a throwaway scratch database on the shared cluster: 20k rows dumped in
# 119ms, 50k in 148ms, 100k in 248ms, 200k in 427ms (roughly a 90ms fixed floor plus ~1.8us/row on
# this box). Against a dump that fast, "at least one writer op landed inside pg_dump's own window"
# is a coin flip, not a proof -- measured writer throughput here is on the order of one committed
# op per ~25-30ms across all 20 threads combined, so a <100ms window has poor odds of catching any
# of them regardless of whether the writers and the dump genuinely overlapped. Padding the source
# database with bulk, schema-valid filler rows under a third owner ("bulkpad", never touched by
# t1's churn threads) buys pg_dump real bytes to move and a correspondingly real, measurable
# window -- 120k rows costs ~4s of one-time INSERT ... SELECT generate_series setup and lands the
# dump around 350ms, a comfortable order of magnitude wider than the inter-arrival gap. The pad
# rows are themselves well-formed tree roots (parent_id NULL, path/depth consistent, vertical NULL
# so they are exempt from the position-uniqueness check) purely so they don't trip the restored
# database's own tree-invariant scan, which runs over every owner found, pad included.
_PAD_ROW_COUNT = 120_000

# tests/http/test_availability.py's own regex: the closing paren in "pg_ctl (PostgreSQL) 16.13"
# sits between the product name and the version, so a fixed substring check for "PostgreSQL 16."
# never matches on any real install.
_VERSION_RE = re.compile(r"PostgreSQL\)?\s+(\d+)\.")


# --- the private cluster pair --------------------------------------------------------------------


def _free_port() -> int:
    """Same TOCTOU-tolerant technique as tests/http/test_availability.py's own `_free_port`,
    duplicated rather than imported (module docstring)."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _run(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, capture_output=True, text=True, **kwargs)  # type: ignore[arg-type]


def _binary_major(path: str) -> str | None:
    out = subprocess.run([path, "--version"], capture_output=True, text=True).stdout
    m = _VERSION_RE.search(out)
    return m.group(1) if m else None


def _server_major(dsn: str) -> str:
    """`server_version_num` is `MMmmpp` (e.g. `160014` for 16.14) for every Postgres >= 10 —
    verified live against the running shared cluster before trusting the formula."""
    with psycopg.connect(dsn, autocommit=True) as conn:
        (num,) = conn.execute("SHOW server_version_num").fetchone()
    return str(int(num) // 10000)


class _PrivateCluster:
    """One throwaway Postgres cluster: its own `initdb` data directory, its own unix socket (no
    TCP at all — `-h ''`), its own OS-assigned port, reachable by nobody but this OS user. Module
    docstring: the recipe and both of S-45's fixes to `docs/E2E.md` §2's literal text."""

    def __init__(self, tmp_root: Path, label: str, role: str) -> None:
        self.label = label
        self.role = role
        self.pgdata = tmp_root / f"pg89{label}"
        self.pg_log = tmp_root / f"pg89{label}.log"
        self.sock_dir = Path(tempfile.mkdtemp(prefix=f"hz89{label}-"))
        self.port = _free_port()
        self._started = False

    def start(self, initdb: str, pg_ctl: str) -> None:
        r = _run([initdb, "-D", str(self.pgdata), "--auth=trust", "-U", self.role])
        if r.returncode != 0:
            raise RuntimeError(f"initdb ({self.label}) failed:\n{r.stdout}\n{r.stderr}")
        r = _run(
            [
                pg_ctl, "-D", str(self.pgdata),
                # deadlock_timeout=50ms, not the 1s default: this cluster is private and
                # throwaway, so tuning it is not touching product config. Measured live: with the
                # default 1s, a genuine 3-way deadlock cycle among the writer threads (see
                # _RETRIABLE's comment) left every backend piled up motionless for up to a second
                # waiting for Postgres to even *notice* the cycle, which swallowed pg_dump's own
                # 150-200ms window whole and made "an op landed during the dump" a coin flip
                # despite real, continuous contention throughout. 50ms is still generous next to
                # ordinary lock waits (which resolve in microseconds once the holder commits) and
                # turns detection latency from the dominant timescale into a rounding error.
                "-o", f"-p {self.port} -k {self.sock_dir} -h '' -c deadlock_timeout=50ms",
                "-l", str(self.pg_log),
                "-w", "start",
            ]
        )
        if r.returncode != 0:
            log = self.pg_log.read_text() if self.pg_log.exists() else "(no log)"
            raise RuntimeError(
                f"pg_ctl start ({self.label}) failed:\n{r.stdout}\n{r.stderr}\nlog:\n{log}"
            )
        self._started = True

    def dsn(self, dbname: str) -> str:
        return f"postgresql://{self.role}@/{dbname}?host={self.sock_dir}&port={self.port}"

    def admin_dsn(self) -> str:
        return self.dsn("postgres")

    def create_database(self, name: str) -> None:
        with psycopg.connect(self.admin_dsn(), autocommit=True) as conn:
            conn.execute(f'CREATE DATABASE "{name}"')

    def stop(self, pg_ctl: str) -> None:
        if not self._started:
            return
        _run([pg_ctl, "-D", str(self.pgdata), "-m", "fast", "-t", "30", "-w", "stop"])
        self._started = False

    def pid_survives(self) -> bool:
        return bool(_run(["pgrep", "-f", str(self.pgdata)]).stdout.strip())

    def cleanup_dirs(self) -> None:
        shutil.rmtree(self.pgdata, ignore_errors=True)
        shutil.rmtree(self.sock_dir, ignore_errors=True)


@dataclass
class _ClusterSetup:
    """What the `clusters` fixture hands each test. `error` is `None` on a clean, version-checked
    pair, or the precise reason S-89 cannot run — read and `gate()`d from each test's own first
    statement, never from the fixture itself: `tests/pipeline/test_import.py`'s own rule
    ("every dependent test's own first statement is `if census is None: gate(...)`, preserving
    the call-phase rule while still sharing the one [expensive setup] run"), applied here to the
    same shape of problem (an expensive, shared precondition several tests read)."""

    error: str | None
    source: _PrivateCluster | None = None
    dest: _PrivateCluster | None = None
    pg_dump: str = ""
    pg_restore: str = ""


@pytest.fixture(scope="module")
def clusters(tmp_path_factory: pytest.TempPathFactory) -> Iterator[_ClusterSetup]:
    """Built once for the module — two `initdb`/`pg_ctl` boots are not cheap — and shared by both
    S-89 test functions below, the same "expensive setup once, gate per test" split
    `tests/pipeline/test_import.py`'s own `census`/`imported` fixtures already use.

    The version check is live, not merely `--version` string comparison: it starts each cluster
    first (from whichever `initdb`/`pg_ctl` resolve off `PATH`) and then asks the *running server*
    for its own `server_version_num`, because the failure this guards against is exactly a PATH
    with more than one Postgres install on it — `pg_dump` resolving to a different install than
    the one `initdb`/`pg_ctl` just built and started, which is precisely the "reads like a product
    bug" case named in this WP's brief.
    """
    tool_names = ("initdb", "pg_ctl", "pg_dump", "pg_restore")
    tools = {name: shutil.which(name) for name in tool_names}
    missing = [name for name, path in tools.items() if not path]
    if missing:
        yield _ClusterSetup(
            error=(
                f"S-89 needs {', '.join(missing)} on PATH — it owns a private cluster pair and "
                f"cannot use the shared CI container (postgres:16-alpine has neither the "
                f"binaries nor the permission to run them)"
            )
        )
        return

    tmp_root = tmp_path_factory.mktemp("s89")
    source = _PrivateCluster(tmp_root, "src", "s89")
    dest = _PrivateCluster(tmp_root, "dst", "s89")
    source_started = dest_started = False
    try:
        source.start(tools["initdb"], tools["pg_ctl"])
        source_started = True
        dest.start(tools["initdb"], tools["pg_ctl"])
        dest_started = True

        dump_major = _binary_major(tools["pg_dump"])
        restore_major = _binary_major(tools["pg_restore"])
        source_major = _server_major(source.admin_dsn())
        dest_major = _server_major(dest.admin_dsn())
        if dump_major != source_major or restore_major != dest_major:
            yield _ClusterSetup(
                error=(
                    f"version mismatch: pg_dump reports major {dump_major!r} against a source "
                    f"server reporting {source_major!r}; pg_restore reports {restore_major!r} "
                    f"against a destination server reporting {dest_major!r} — refusing to trust "
                    f"either (a version-mismatched pg_dump/pg_restore fails in a way that reads "
                    f"like a product bug, not an environment one)"
                )
            )
            return

        yield _ClusterSetup(
            error=None, source=source, dest=dest,
            pg_dump=tools["pg_dump"], pg_restore=tools["pg_restore"],
        )
    finally:
        if dest_started:
            dest.stop(tools["pg_ctl"])
        if source_started:
            source.stop(tools["pg_ctl"])
        dest_pid_survives = dest.pid_survives() if dest_started else False
        source_pid_survives = source.pid_survives() if source_started else False
        source.cleanup_dirs()
        dest.cleanup_dirs()
        assert not source_pid_survives, "S-89 source cluster process survived teardown"
        assert not dest_pid_survives, "S-89 dest cluster process survived teardown"


# --- shared helpers ---------------------------------------------------------------------------


def _digest(conn: psycopg.Connection) -> str:
    """Full-table fingerprint, every column of every row, order-independent — duplicated
    three-line SQL, module docstring."""
    (value,) = conn.execute(
        "SELECT md5(string_agg(goals::text, '|' ORDER BY id)) FROM goals"
    ).fetchone()
    return value


def _row_count(conn: psycopg.Connection) -> int:
    (n,) = conn.execute("SELECT count(*) FROM goals").fetchone()
    return n


# Was a hand-copy of `tests/core/test_tree.py`'s private helper; now the one shared
# implementation in `tests/harness/tree_invariant.py`, which `tests/conftest.py` also runs in
# every clone's teardown (AC-203).
from tests.harness.tree_invariant import violations as _tree_invariant_violations


def _dump_lists_goals_table(listing_stdout: str) -> bool:
    """`pg_restore --list`'s TOC line shape, confirmed live against a real dump of this schema:
    `217; 1259 101337 TABLE public goals verticals`. Since WP-33 the same check also requires
    `goal_evidence` (verification receipts) and `tag_meta` (project-chip settings). A restore
    missing either table changes the meaning or presentation of otherwise intact goals."""
    return (
        re.search(r"\bTABLE\s+public\s+goals\b", listing_stdout) is not None
        and re.search(r"\bTABLE\s+public\s+goal_evidence\b", listing_stdout) is not None
        and re.search(r"\bTABLE\s+public\s+tag_meta\b", listing_stdout) is not None
    )


# --- S-89a — quiescent dump/restore: exact row count and a byte-for-byte digest match ------------


def test_s89a_dump_restore_matches_source_row_count_and_digest(
    clusters: _ClusterSetup, request: pytest.FixtureRequest
) -> None:
    if clusters.error:
        gate(clusters.error)
    source, dest = clusters.source, clusters.dest
    assert source is not None and dest is not None  # clusters.error is None iff both are set

    dbname = "s89a_quiescent"
    source.create_database(dbname)
    src_dsn = source.dsn(dbname)
    runner.run_up(src_dsn)
    with psycopg.connect(src_dsn, autocommit=True) as conn:
        conn.execute(F2_SQL.read_text())
        conn.execute("ANALYZE goals")
        source_count = _row_count(conn)
        source_digest = _digest(conn)
    assert source_count == 49

    dump_path = REPO_ROOT / artifact(request, "artifacts/pipeline/S-89/quiescent.dump")
    dump_path.parent.mkdir(parents=True, exist_ok=True)
    dump = _run([clusters.pg_dump, "-Fc", "-f", str(dump_path), src_dsn])
    assert dump.returncode == 0, dump.stderr
    assert dump_path.stat().st_size > 0, "pg_dump produced an empty file"

    listing = _run([clusters.pg_restore, "--list", str(dump_path)])
    assert listing.returncode == 0, listing.stderr
    assert _dump_lists_goals_table(listing.stdout), (
        f"pg_restore --list never names the goals table:\n{listing.stdout}"
    )

    restored_name = "s89a_restored"
    dest.create_database(restored_name)
    restored_dsn = dest.dsn(restored_name)
    restore = _run([clusters.pg_restore, "-d", restored_dsn, str(dump_path)])
    assert restore.returncode == 0, restore.stderr

    with psycopg.connect(restored_dsn, autocommit=True) as conn:
        restored_count = _row_count(conn)
        restored_digest = _digest(conn)
    assert restored_count == 49
    if restored_digest != source_digest:
        # A bare hash != hash tells you nothing about *what* differs. Re-query both sides row by
        # row and name it — this is also the reason `_digest`'s query orders by id: a bare
        # `string_agg` without ORDER BY would make two logically-identical tables hash differently
        # depending on physical row order, which is exactly the kind of vacuous failure this
        # branch exists to rule out from ever being the actual cause.
        with psycopg.connect(src_dsn, autocommit=True) as sc, psycopg.connect(restored_dsn, autocommit=True) as rc:
            src_rows = dict(sc.execute("SELECT id, goals::text FROM goals ORDER BY id").fetchall())
            dst_rows = dict(rc.execute("SELECT id, goals::text FROM goals ORDER BY id").fetchall())
        only_src = sorted(set(src_rows) - set(dst_rows))
        only_dst = sorted(set(dst_rows) - set(src_rows))
        changed = sorted(i for i in src_rows.keys() & dst_rows.keys() if src_rows[i] != dst_rows[i])
        pytest.fail(
            f"digest mismatch ({source_digest} != {restored_digest}): "
            f"missing from restore: {only_src}; extra in restore: {only_dst}; "
            f"changed rows: {changed[:5]}"
            + (f" (first changed row) source={src_rows[changed[0]]!r} restored={dst_rows[changed[0]]!r}"
               if changed else "")
        )
    assert restored_digest == source_digest


# --- S-89b — a dump taken while 20 concurrent, contending writers are running --------------------
#
# What they contend on, and why: two parent nodes (p1, p2) and six leaves split between them, all
# under owner t1. Every writer repeatedly either reparents a randomly chosen leaf onto a randomly
# chosen parent (`verticals.core.moves.reparent`, the same public verb S-126's own steps name) or
# creates a fresh child under a randomly chosen parent (`verticals.core.goals.create`) — the real
# verbs, not hand-rolled SQL, so the locking they take is whatever the product actually takes: a
# `SELECT ... FOR UPDATE` on both the moved row and its new parent inside `tree.move` (AC-204's
# neighbour, not AC-204 itself), and `pg_advisory_xact_lock(hashtext(...))` keyed on the (owner,
# parent) sibling group inside `moves.allocate_position` for every create. With 20 threads and
# only 8 rows to fight over (2 parents + 6 leaves), the same row is under contention from several
# threads at once almost immediately — this is deliberately *not* 20 inserts into 20 unrelated
# rows, which would never block on anything and would prove nothing about snapshot consistency
# under real contention. `_watch_lock_waiters` and the during-dump-window check below both assert
# this actually happened rather than trusting the design on paper.


# A first version of this loop treated *any* exception as fatal and asserted `errors == []`. Run
# against the real cluster, 20 threads reparenting/creating across 2 parents + 6 leaves produced
# real `DeadlockDetected` — Postgres's own detector breaking a genuine three-way wait-for cycle
# (`tree.move`'s `_fetch_locked` takes its two row locks in one statement, but each thread targets
# a different pair, so three independent two-row locks can still close a cycle across three
# transactions even though no *two* threads ever contend on more than one row directly). That is
# not a bug in this test or in the product — it is Postgres doing exactly its job under load real
# enough to need it, and it is independent, stronger evidence of genuine contention than the
# `pg_stat_activity` watcher alone. The correct response, here and in any real client, is to catch
# it and retry: `checked psycopg.errors.DeadlockDetected.__mro__` live and confirmed it and
# `SerializationFailure` are siblings under `OperationalError` in this psycopg version, not both
# nested under `TransactionRollback` as the bare SQLSTATE class grouping (40xxx) would suggest —
# so both are named explicitly below rather than caught via one assumed common parent. Retries are
# logged, not silent, and every *other* exception type still ends the thread and fails the test.
_RETRIABLE = (psycopg.errors.DeadlockDetected, psycopg.errors.SerializationFailure)


def _writer_loop(
    dsn: str,
    owner: str,
    parents: tuple[str, str],
    leaves: list[str],
    stop_event: threading.Event,
    seed: int,
    op_log: list[tuple[float, str]],
    errors: list[BaseException],
    retries: list[tuple[float, str]],
    lock: threading.Lock,
) -> None:
    rng = random.Random(seed)
    n = 0
    with psycopg.connect(dsn, autocommit=True) as conn:
        while not stop_event.is_set() and n < _MAX_ITERATIONS_PER_WRITER:
            try:
                if rng.random() < 0.5:
                    leaf = rng.choice(leaves)
                    target = rng.choice(parents)
                    moves.reparent(conn, owner=owner, id=leaf, parent_id=target)
                    op = "reparent"
                else:
                    parent = rng.choice(parents)
                    goals.create(conn, owner=owner, title=f"churn {seed}.{n}", parent_id=parent)
                    op = "create"
            except _RETRIABLE as exc:
                with lock:
                    retries.append((time.monotonic(), type(exc).__name__))
                continue  # same targets are still fair game; psycopg's Transaction ctx already
                          # rolled back the aborted attempt, so the connection is ready to reuse
            except Exception as exc:  # noqa: BLE001 — collected and asserted on below, never swallowed
                with lock:
                    errors.append(exc)
                break
            else:
                with lock:
                    op_log.append((time.monotonic(), op))
            n += 1


def _watch_lock_waiters(dsn: str, stop_event: threading.Event, samples: list[int]) -> None:
    """Polls `pg_stat_activity` for backends actually blocked on a lock — row lock or advisory,
    either shows `wait_event_type = 'Lock'` — the direct evidence that the 20 writers were not
    merely concurrent but contending. Same sampling idiom as `tests/http/test_concurrency.py`'s
    own `_LockWatcher`, narrower (one counter, not a `pg_locks` key set) because this only needs
    to prove contention happened, not identify which key."""
    with psycopg.connect(dsn, autocommit=True) as conn:
        while not stop_event.is_set():
            (n,) = conn.execute(
                "SELECT count(*) FROM pg_stat_activity"
                " WHERE datname = current_database() AND wait_event_type = 'Lock'"
            ).fetchone()
            samples.append(n)
            time.sleep(_LOCK_POLL_SECONDS)


def test_s89b_dump_under_concurrent_writers_restores_consistent_tree(
    clusters: _ClusterSetup, request: pytest.FixtureRequest
) -> None:
    if clusters.error:
        gate(clusters.error)
    source, dest = clusters.source, clusters.dest
    assert source is not None and dest is not None

    dbname = "s89b_churn"
    source.create_database(dbname)
    src_dsn = source.dsn(dbname)
    runner.run_up(src_dsn)
    owner = "t1"
    with psycopg.connect(src_dsn, autocommit=True) as conn:
        conn.execute(F2_SQL.read_text())
        conn.execute("ANALYZE goals")
        p1 = goals.create(conn, owner=owner, title="Churn parent A").goal.id
        p2 = goals.create(conn, owner=owner, title="Churn parent B").goal.id
        leaves = [
            goals.create(
                conn, owner=owner, title=f"Churn leaf {i}", parent_id=(p1 if i < 3 else p2)
            ).goal.id
            for i in range(6)
        ]
        baseline_count = _row_count(conn)
    assert baseline_count == 49 + 2 + 6  # F2's 49, plus the two parents, plus six leaves

    # Bulk filler so pg_dump's own window is wide enough to prove overlap, not just claim it —
    # see _PAD_ROW_COUNT's comment. Raw SQL, not goals.create(): 120k round trips through the
    # product's own validation path is setup cost this scenario has no reason to pay, and a
    # single INSERT ... SELECT is exactly the same bytes-on-disk pg_dump will read either way.
    with psycopg.connect(src_dsn, autocommit=True) as conn:
        conn.execute(
            "INSERT INTO goals (id, owner, parent_id, path, depth, parked_from_vertical, title)"
            " SELECT 'pad-' || gs, 'bulkpad', NULL, '/pad-' || gs || '/', 0, 'life',"
            "        'padding row ' || gs"
            " FROM generate_series(1, %(n)s) AS gs",
            {"n": _PAD_ROW_COUNT},
        )

    stop_event = threading.Event()
    op_log: list[tuple[float, str]] = []
    errors: list[BaseException] = []
    retries: list[tuple[float, str]] = []
    log_lock = threading.Lock()
    threads = [
        threading.Thread(
            target=_writer_loop,
            args=(src_dsn, owner, (p1, p2), leaves, stop_event, i, op_log, errors, retries, log_lock),
        )
        for i in range(WRITER_COUNT)
    ]

    lock_stop = threading.Event()
    lock_samples: list[int] = []
    watcher = threading.Thread(target=_watch_lock_waiters, args=(src_dsn, lock_stop, lock_samples))

    for t in threads:
        t.start()
    watcher.start()
    time.sleep(_WARMUP_SECONDS)  # let the 20 threads get well into their loops before the dump starts

    dump_path = REPO_ROOT / artifact(request, "artifacts/pipeline/S-89/concurrent.dump")
    dump_path.parent.mkdir(parents=True, exist_ok=True)
    t_dump_start = time.monotonic()
    dump = _run([clusters.pg_dump, "-Fc", "-f", str(dump_path), src_dsn])
    t_dump_end = time.monotonic()

    time.sleep(_COOLDOWN_SECONDS)
    stop_event.set()
    for t in threads:
        t.join(timeout=_JOIN_TIMEOUT)
    lock_stop.set()
    watcher.join(timeout=5.0)

    assert not any(t.is_alive() for t in threads), "a writer thread did not stop within the join timeout"
    assert errors == [], f"{len(errors)} writer error(s) out of {len(op_log)} ops; first: {errors[0]!r}"
    assert dump.returncode == 0, dump.stderr
    assert dump_path.stat().st_size > 0

    assert len(op_log) > 0, "no writer completed a single operation — the burst never ran at all"
    during_dump = [ts for ts, _ in op_log if t_dump_start <= ts <= t_dump_end]
    assert len(during_dump) > 0, (
        f"none of {len(op_log)} completed writer operations landed inside pg_dump's own "
        f"{t_dump_end - t_dump_start:.4f}s window — the load never overlapped the dump, so this "
        f"run proves nothing about snapshot consistency"
    )
    assert max(lock_samples, default=0) > 0, (
        "never observed a backend waiting on a lock during the writer burst — the 20 threads "
        "never actually contended with each other"
    )

    listing = _run([clusters.pg_restore, "--list", str(dump_path)])
    assert listing.returncode == 0, listing.stderr
    assert _dump_lists_goals_table(listing.stdout)

    restored_name = "s89b_restored"
    dest.create_database(restored_name)
    restored_dsn = dest.dsn(restored_name)
    restore = _run([clusters.pg_restore, "-d", restored_dsn, str(dump_path)])
    assert restore.returncode == 0, restore.stderr

    with psycopg.connect(restored_dsn, autocommit=True) as conn:
        restored_count = _row_count(conn)
        owners = [r[0] for r in conn.execute("SELECT DISTINCT owner FROM goals").fetchall()]
        violations: list[str] = []
        for o in owners:
            violations += _tree_invariant_violations(conn, o)
    assert restored_count >= baseline_count, (
        "restored fewer rows than existed before the burst even started — the dump's snapshot "
        "predates its own setup data, which is not a legal snapshot"
    )
    assert violations == [], f"tree invariant violations in the restored database: {violations}"

    print(
        f"S-89b: {len(op_log)} writer ops committed, {len(retries)} deadlock/serialization "
        f"retries survived, {len(during_dump)} ops landed inside the "
        f"{t_dump_end - t_dump_start:.4f}s dump window, max concurrent lock-waiters observed "
        f"{max(lock_samples, default=0)}, restored row count {restored_count}"
    )
