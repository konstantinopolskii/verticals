"""S-79 through S-86 — `tools/import_planner.py` against real Postgres 16, real subprocesses,
no mocks. WP-16.

**F3 and why nothing here is a literal.** `seed/planner-export.json` is Zone 1, gitignored,
absent on a stranger's machine. Every scenario tagged **F3** below calls `report.gate(...)` as
the first statement in its own body (never from a fixture — `tests/conftest.py`'s
`pytest_runtest_makereport` hook only turns a `Gated` exception into the `gate` outcome when
raised during the test's own "call" phase; a fixture that raised it would surface as a setup
ERROR instead) and reads every expected number from `artifacts/census.json`
(`tests/fixtures/census.py`), never from a number typed into this file — `docs/E2E.md` S-79's own
rule, applied to every F3 scenario here, not only S-79. S-86 carries no **F3** tag in `docs/
E2E.md` (its five crafted files are synthetic) and always runs.

**Nothing from the export ever risks a log line.** The only place this file compares real
content (S-82's "keeps its original ... title") does it through a SHA-256 hash, never a raw
`==`: a failed `assert digest_a == digest_b` prints two hex strings, never the two title strings
pytest's assertion rewriter would otherwise put in the failure output — the one place a bare
`assert title == expected` could turn a passing redaction pass into a moot point by leaking
through the test log itself instead of through a file. `S-83`'s row digest applies the same
principle one level up: `title`/`body` feed an `md5(string_agg(...))` computed entirely inside
Postgres (`tests/pipeline/test_schema_parity.py`'s own `_schema_digest` idiom), so the content
never enters this process at all, only the resulting hash does.

**Shared setup, gated per test.** `census` and `imported` are module-scoped fixtures that do the
expensive F3-dependent work (regenerate `artifacts/census.json`; run the importer once with the
default policy into one shared clone — S-81/S-82/S-84 all read "as S-79, then measure") exactly
once for the whole module. Neither fixture calls `gate()` itself; both return `None` when F3 is
absent, and every dependent test's own first statement is `if census is None: gate(...)`,
preserving the call-phase rule while still sharing the one import run four scenarios read from.

**Statement counting for S-83** uses `tests/harness/stmt.py` direct, against `pg_stat_statements`
on the maintenance connection — not the reserved-for-S-25/S-27 reading of `docs/E2E.md` §1, but
the precedent `tests/core/test_tree.py`, `tests/core/test_idem.py` and `tests/core/test_board.py`
already established and `docs/PENDING_DOC_FIXES.md` #12 already blesses: a `core`-or-pipeline-
level statement-count claim with no HTTP request to carry `X-Query-Count` has no other mechanism
available. Gated (not failed) when the extension is unavailable, matching that same precedent.

**S-84's `root_id`.** `docs/E2E.md` §2's `census.json` shape names no `root_id` field, even
though S-84's own prose reads `census.authored.root_id`. See `docs/PENDING_DOC_FIXES.md` — this
file reads `census.authored.deepest_chain[0]` instead: a real, surviving, root-level id, which is
exactly the property the check exists to prove.

**S-84's `GET /api/goals/{id}` half is not run here.** `docs/E2E.md` §1's suite table gives
`pipeline` its own process reality — "real CLI invocations, real files, real `pg_dump`/
`pg_restore`, real containers" — with no HTTP transport in it, matching the exact reasoning
`docs/PENDING_DOC_FIXES.md` #17 already used to keep an HTTP-shaped claim out of suite `core`.
This file proves the DB-level half of "ids preserved verbatim" (the id exists, unchanged, under
`owner='kk'` after import); the HTTP-200 half belongs to whichever suite actually owns a
transport (`http`, WP-15's), same split #17 already made for S-127/S-128.

Run standalone:
    PGHOST=127.0.0.1 PGPORT=55432 PGUSER=verticals PGPASSWORD=verticals \
        .venv/bin/python -m pytest tests/pipeline/test_import.py -v -s
"""

from __future__ import annotations

import hashlib
import json
import os
import random
import subprocess
import sys
from collections import Counter
from collections.abc import Iterator
from datetime import date, datetime, timezone
from pathlib import Path

import psycopg
import pytest

from verticals.core.board import board
from tests.conftest import fresh_clone, maintenance_dsn
from tests.harness import redact, stmt
from tests.harness.report import artifact, artifacts_for, gate

REPO_ROOT = Path(__file__).resolve().parents[2]
EXPORT_PATH = REPO_ROOT / "seed" / "planner-export.json"
IMPORTER = REPO_ROOT / "tools" / "import_planner.py"
CENSUS_PATH = REPO_ROOT / "artifacts" / "census.json"
OWNER = "kk"

_F3_ABSENT = "F3 absent (seed/planner-export.json not present on this machine)"


# --- shared plumbing -----------------------------------------------------------------------


def _env_dsn(dbname: str) -> str:
    host = os.environ.get("PGHOST", "127.0.0.1")
    port = os.environ.get("PGPORT", "55432")
    user = os.environ.get("PGUSER", "verticals")
    password = os.environ.get("PGPASSWORD", "verticals")
    return f"postgresql://{user}:{password}@{host}:{port}/{dbname}"


def _run_importer(
    dsn: str, *, input_path: Path = EXPORT_PATH, owner: str = OWNER, drop: str | None = None
) -> subprocess.CompletedProcess[str]:
    args = [sys.executable, str(IMPORTER), "--input", str(input_path), "--owner", owner]
    if drop is not None:
        args += ["--drop", drop]
    return subprocess.run(
        args, env={**os.environ, "VERTICALS_DATABASE_URL": dsn}, capture_output=True, text=True,
        timeout=90,
    )


def _parse_reconciliation(stdout: str) -> dict[str, int]:
    parsed: dict[str, int] = {}
    for line in stdout.strip().splitlines():
        key, _, value = line.rpartition(" ")
        parsed[key] = int(value)
    return parsed


def _parse_utc(value: str) -> datetime:
    return datetime.fromisoformat(value).astimezone(timezone.utc)


def _hash(s: str) -> str:
    """SHA-256 of `s` — used the one place this file compares real title content (S-82), so a
    failed assertion's output is two hex digests, never the two strings themselves."""
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def _digest(conn: psycopg.Connection, owner: str) -> str:
    """S-83's own field list, hashed entirely inside Postgres — `title`/`body` content never
    crosses into this process, only the resulting md5 does. Same idiom as
    `tests/pipeline/test_schema_parity.py`'s `_schema_digest`: `format(...)` + `string_agg` +
    `md5`, `ORDER BY id` for a deterministic row order.

    The `%s` inside the SQL `format(...)` call are doubled (`%%s`) because this query also binds
    a real parameter (`%(owner)s`) — psycopg scans the query text for placeholders before it ever
    reaches Postgres, and "positional and named placeholders cannot be mixed" the moment it also
    sees an un-doubled `%s`, even one sitting inside a string literal meant for Postgres's own
    `format()`, not psycopg's binder."""
    (digest,) = conn.execute(
        """
        SELECT md5(string_agg(
            format('%%s|%%s|%%s|%%s|%%s|%%s|%%s|%%s|%%s|%%s|%%s',
                   id, coalesce(parent_id, ''), path, depth, coalesce(vertical::text, ''),
                   coalesce(period_key, ''), title, body, coalesce(color, ''),
                   coalesce(done_at::text, ''), origin),
            '|' ORDER BY id
        )) FROM goals WHERE owner = %(owner)s
        """,
        {"owner": owner},
    ).fetchone()
    return digest


def _row_count(dsn: str, owner: str = OWNER) -> int:
    with psycopg.connect(dsn, autocommit=True) as conn:
        (count,) = conn.execute("SELECT count(*) FROM goals WHERE owner = %s", (owner,)).fetchone()
        return count


def _assert_no_partial_state(dsn: str) -> None:
    """S-86: "SELECT count(*) is 0 after every run (the importer commits once, at the end, or
    not at all)." A fresh F0 clone has zero rows of any owner to begin with, so a bare
    `count(*)` over the whole table is already the strongest form of this check."""
    with psycopg.connect(dsn, autocommit=True) as conn:
        (count,) = conn.execute("SELECT count(*) FROM goals").fetchone()
        assert count == 0


# --- shared fixtures -------------------------------------------------------------------------


@pytest.fixture(scope="module")
def census() -> dict | None:
    """`artifacts/census.json` — read only. `tests/pipeline/conftest.py`'s own `pytest_configure`
    is what regenerates the file, exactly once, before any worker starts (see that module's
    docstring for why: N module instances of this fixture, one per xdist worker, all racing a
    non-atomic write to the same shared path, is the torn-read bug that ran here first). This
    fixture never writes, so N parallel readers of an already-complete file never race anything.
    `None` when F3 is absent; every F3 test's own body checks for that and gates itself."""
    if not EXPORT_PATH.exists():
        return None
    return json.loads(CENSUS_PATH.read_text())


@pytest.fixture(scope="module")
def imported(census: dict | None) -> Iterator[tuple[str, str, subprocess.CompletedProcess[str]] | None]:
    """One import, one shared clone, the default policy — S-79's own command. S-81/S-82/S-84 all
    read "as S-79, then measure/inspect" and reuse this rather than re-running the same 308-row
    import three more times; none of the four scenarios writes to the database afterward, so
    sharing is safe. `None` when F3 is absent."""
    if census is None:
        yield None
        return
    with fresh_clone("f0") as db_name:
        dsn = _env_dsn(db_name)
        result = _run_importer(dsn, drop="calendar+onboarding")
        yield db_name, dsn, result


@pytest.fixture(autouse=True)
def _redact_f3_artifacts(request: pytest.FixtureRequest) -> Iterator[None]:
    """`docs/E2E.md` suite-E teardown: "F3 scenarios additionally run the redactor over their
    artifacts before the run ends, and the redactor's own output is asserted to contain zero
    strings from the export's `name` or `description` fields." Runs after every test in this
    module; a no-op whenever nothing called `report.artifact()` (every test but S-79 today) or
    F3 is absent."""
    yield
    if not EXPORT_PATH.exists():
        return
    paths = [REPO_ROOT / p for p in artifacts_for(request.node)]
    if not paths:
        return
    denylist = redact.build_denylist(EXPORT_PATH)
    redact.redact_and_verify(paths, denylist)


# --- S-79 -------------------------------------------------------------------------------------


def test_s79_import_kk_export_with_exact_reconciliation(
    request: pytest.FixtureRequest,
    census: dict | None,
    imported: tuple[str, str, subprocess.CompletedProcess[str]] | None,
) -> None:
    """S-79 — the exact command from `docs/E2E.md`, asserted against `artifacts/census.json`
    field by field, never against a number typed into this file. Writes the redacted-before-the-
    run-ends reconciliation table to `artifacts/pipeline/S-79/reconciliation.txt`."""
    if census is None or imported is None:
        gate(_F3_ABSENT)
    db_name, dsn, result = imported

    assert result.returncode == 0, result.stderr

    art_path = artifact(request, "artifacts/pipeline/S-79/reconciliation.txt")
    full_path = REPO_ROOT / art_path
    full_path.parent.mkdir(parents=True, exist_ok=True)
    full_path.write_text(result.stdout)

    a = census["authored"]
    parsed = _parse_reconciliation(result.stdout)

    dropped_by_class: dict[str, int] = {}
    for b in census["raw"]["batches"]:
        dropped_by_class[b["class"]] = dropped_by_class.get(b["class"], 0) + b["size"]

    assert parsed["read"] == census["raw"]["count"]
    assert parsed["dropped:calendar_timed"] == dropped_by_class.get("calendar_timed", 0)
    assert parsed["dropped:calendar_allday"] == dropped_by_class.get("calendar_allday", 0)
    assert parsed["dropped:onboarding"] == dropped_by_class.get("onboarding", 0)
    assert parsed["reparented_orphans"] == census["orphans"]["calendar+onboarding"]["count"]
    assert parsed["clamped_to_parent"] == a["clamped_to_parent"]
    assert parsed["imported"] == a["count"]
    for vertical_key, expected in a["by_vertical"].items():
        assert parsed[f"by_vertical:{vertical_key}"] == expected

    with psycopg.connect(dsn, autocommit=True) as conn:
        (count,) = conn.execute(
            "SELECT count(*) FROM goals WHERE owner = %s", (OWNER,)
        ).fetchone()
        assert count == a["count"]

        db_created_at = dict(
            conn.execute("SELECT id, created_at FROM goals WHERE owner = %s", (OWNER,)).fetchall()
        )

    raw_rows = {r["id"]: r for r in json.loads(EXPORT_PATH.read_text())}
    for goal_id, created_at in db_created_at.items():
        expected = _parse_utc(raw_rows[goal_id]["created_datetime"])
        assert created_at == expected, f"created_at drift on {goal_id}"


# --- S-80 -------------------------------------------------------------------------------------


def test_s80_all_three_drop_policies_produce_stated_counts(census: dict | None) -> None:
    """S-80 — three fresh databases, one per named policy. Row counts are derived from
    `census.raw.batches` (never the 427/320/308 literals `docs/E2E.md`'s own prose quotes),
    matching S-79's "never against a typed number" rule extended uniformly; orphan counts and id
    sets come straight from `census.orphans`."""
    if census is None:
        gate(_F3_ABSENT)

    dropped_by_class: dict[str, int] = {}
    for b in census["raw"]["batches"]:
        dropped_by_class[b["class"]] = dropped_by_class.get(b["class"], 0) + b["size"]

    policy_drop_classes = {
        "timed": {"calendar_timed"},
        "calendar": {"calendar_timed", "calendar_allday"},
        "calendar+onboarding": {"calendar_timed", "calendar_allday", "onboarding"},
    }

    kept_counts: dict[str, int] = {}
    for policy, drop_classes in policy_drop_classes.items():
        with fresh_clone("f0") as db_name:
            dsn = _env_dsn(db_name)
            result = _run_importer(dsn, drop=policy)
            assert result.returncode == 0, result.stderr

            expected_dropped = sum(dropped_by_class.get(c, 0) for c in drop_classes)
            count = _row_count(dsn)
            assert count + expected_dropped == census["raw"]["count"]
            kept_counts[policy] = count

            orphan_block = census["orphans"][policy]
            assert orphan_block["count"] <= count
            with psycopg.connect(dsn, autocommit=True) as conn:
                for oid in orphan_block["ids"]:
                    row = conn.execute(
                        "SELECT parent_id, depth, path FROM goals WHERE owner = %s AND id = %s",
                        (OWNER, oid),
                    ).fetchone()
                    assert row is not None, f"orphan {oid} missing under policy {policy!r}"
                    parent_id, depth, path = row
                    assert parent_id is None and depth == 0 and path == f"/{oid}/"

    # default (no --drop flag) equals calendar+onboarding, §10-D5
    with fresh_clone("f0") as db_name:
        dsn = _env_dsn(db_name)
        result = _run_importer(dsn, drop=None)
        assert result.returncode == 0, result.stderr
        assert _row_count(dsn) == kept_counts["calendar+onboarding"]

    timed_ids = set(census["orphans"]["timed"]["ids"])
    calendar_ids = set(census["orphans"]["calendar"]["ids"])
    both_ids = set(census["orphans"]["calendar+onboarding"]["ids"])
    assert timed_ids <= calendar_ids <= both_ids


# --- S-81 -------------------------------------------------------------------------------------


def test_s81_no_machine_batch_survives_onto_today(
    census: dict | None,
    imported: tuple[str, str, subprocess.CompletedProcess[str]] | None,
) -> None:
    """S-81 — C2's whole point: a correct import leaves 2026-08-08's day column empty."""
    if census is None or imported is None:
        gate(_F3_ABSENT)
    _db_name, dsn, result = imported
    assert result.returncode == 0, result.stderr

    a = census["authored"]
    non_authored_batches = {
        _parse_utc(b["created_datetime"]) for b in census["raw"]["batches"] if b["class"] != "authored"
    }

    with psycopg.connect(dsn, autocommit=True) as conn:
        rows = conn.execute("SELECT created_at FROM goals WHERE owner = %s", (OWNER,)).fetchall()
        db_created_ats = [r[0] for r in rows]

        # 1: no imported row's created_at equals a dropped batch's created_datetime
        assert not (set(db_created_ats) & non_authored_batches)

        # 2: the day column for 2026-08-08 is empty
        assert a["by_vertical_date"].get("day", {}).get("2026-08-08", 0) == 0
        b = board(conn, owner=OWNER, date=date(2026, 8, 8))
        day_column = next(c for c in b.columns if c.vertical == "day")
        # R10 ghosts legitimately visit the day column; the claim is about NATIVE rows only.
        native = tuple(g for g in day_column.goals if g.id not in b.ghosts)
        assert native == ()

    # 3: the largest surviving created_at group is at most census's own max_batch_size
    batch_sizes = Counter(db_created_ats)
    assert max(batch_sizes.values()) <= a["max_batch_size"]

    # 4: distinct created_at count matches exactly
    assert len(batch_sizes) == a["distinct_created_at"]


# --- S-82 -------------------------------------------------------------------------------------


def test_s82_orphans_rerooted_not_dropped_not_dangling(
    census: dict | None,
    imported: tuple[str, str, subprocess.CompletedProcess[str]] | None,
) -> None:
    """S-82 — the four `calendar+onboarding` orphans, inspected by id from `census.json`. Title
    equality is checked by SHA-256, never by a raw `==` (module docstring: pytest's assertion
    rewriter would otherwise print both strings on a failure)."""
    if census is None or imported is None:
        gate(_F3_ABSENT)
    _db_name, dsn, result = imported
    assert result.returncode == 0, result.stderr

    orphan_block = census["orphans"]["calendar+onboarding"]
    raw_rows = {r["id"]: r for r in json.loads(EXPORT_PATH.read_text())}

    with psycopg.connect(dsn, autocommit=True) as conn:
        for row in orphan_block["rows"]:
            oid = row["goal_id"]
            db_row = conn.execute(
                "SELECT parent_id, depth, path, vertical, anchor_date, title "
                "FROM goals WHERE owner = %s AND id = %s",
                (OWNER, oid),
            ).fetchone()
            assert db_row is not None, f"orphan {oid} not found after import"
            parent_id, depth, path, vertical, anchor_date, title = db_row

            assert parent_id is None
            assert depth == 0
            assert path == f"/{oid}/"

            source = raw_rows[oid]
            assert vertical == source.get("vertical")
            expected_anchor = date.fromisoformat(source["date"]) if source.get("date") else None
            assert anchor_date == expected_anchor
            assert _hash(title) == _hash(source.get("name") or ""), f"title changed for {oid}"

        (dangling,) = conn.execute(
            "SELECT count(*) FROM goals g LEFT JOIN goals p ON g.parent_id = p.id "
            "WHERE g.parent_id IS NOT NULL AND p.id IS NULL"
        ).fetchone()
        assert dangling == 0

    parsed = _parse_reconciliation(result.stdout)
    assert parsed["reparented_orphans"] == orphan_block["count"]


# --- S-83 -------------------------------------------------------------------------------------


def test_s83_import_is_idempotent(census: dict | None) -> None:
    """S-83 — run twice into the same database. Row digest is computed entirely inside Postgres
    (`_digest`) so title/body content never enters this process. Statement counting: see the
    module docstring's precedent note; gated (not failed) when `pg_stat_statements` is
    unavailable, same as `test_tree.py`/`test_board.py`."""
    if census is None:
        gate(_F3_ABSENT)

    with fresh_clone("f0") as db_name:
        dsn = _env_dsn(db_name)

        result1 = _run_importer(dsn, drop="calendar+onboarding")
        assert result1.returncode == 0, result1.stderr

        with psycopg.connect(dsn, autocommit=True) as conn:
            count1 = conn.execute(
                "SELECT count(*) FROM goals WHERE owner = %s", (OWNER,)
            ).fetchone()[0]
            digest1 = _digest(conn, OWNER)
            created_at1 = dict(
                conn.execute(
                    "SELECT id, created_at FROM goals WHERE owner = %s", (OWNER,)
                ).fetchall()
            )

        maint_dsn = maintenance_dsn()
        counter_available = stmt.available(maint_dsn)
        if counter_available:
            stmt.reset(maint_dsn, db_name)

        result2 = _run_importer(dsn, drop="calendar+onboarding")
        assert result2.returncode == 0, result2.stderr

        if counter_available:
            total = stmt.count(maint_dsn, db_name)
            imported_n = census["authored"]["count"]
            # Generous linear bound (~8 statements per no-op row: SAVEPOINT + optional lock
            # SELECT + INSERT ON CONFLICT + RELEASE SAVEPOINT, per attach() call, plus the one
            # existing-ids read) — nowhere near what O(n^2) would cost at this n (an n^2 run
            # would be ~90x over this bound), comfortably inside it for a correct O(n) run.
            assert total <= 8 * imported_n, (
                f"{total} statements to re-run {imported_n} already-imported rows — "
                f"looks post-linear, not O(1) per row"
            )
        else:
            gate("pg_stat_statements unavailable — statement-count half of S-83 cannot run")

        with psycopg.connect(dsn, autocommit=True) as conn:
            count2 = conn.execute(
                "SELECT count(*) FROM goals WHERE owner = %s", (OWNER,)
            ).fetchone()[0]
            digest2 = _digest(conn, OWNER)
            created_at2 = dict(
                conn.execute(
                    "SELECT id, created_at FROM goals WHERE owner = %s", (OWNER,)
                ).fetchall()
            )

        assert count1 == count2
        assert digest1 == digest2
        assert created_at1 == created_at2

        parsed2 = _parse_reconciliation(result2.stdout)
        assert parsed2["inserted"] == 0
        assert parsed2["updated"] == 0
        assert parsed2["unchanged"] == count2


# --- S-84 -------------------------------------------------------------------------------------


def test_s84_structure_survives_import(
    census: dict | None,
    imported: tuple[str, str, subprocess.CompletedProcess[str]] | None,
) -> None:
    """S-84 — depth, fanout, the deepest chain and the forbidden-column list, all read from
    `census.json` or `information_schema`, never a literal. See the module docstring for
    `root_id` (reads `deepest_chain[0]`) and the `GET /api/goals/{id}` half (not run here)."""
    if census is None or imported is None:
        gate(_F3_ABSENT)
    _db_name, dsn, result = imported
    assert result.returncode == 0, result.stderr

    a = census["authored"]

    with psycopg.connect(dsn, autocommit=True) as conn:
        depth_rows = conn.execute(
            "SELECT id, depth FROM goals WHERE owner = %s", (OWNER,)
        ).fetchall()
        depth_by_id = dict(depth_rows)

        assert max(depth_by_id.values()) == a["max_depth"]
        histogram = Counter(depth_by_id.values())
        assert {str(k): v for k, v in histogram.items()} == a["depth_histogram"]

        fanout_rows = conn.execute(
            "SELECT parent_id, count(*) FROM goals WHERE owner = %s AND parent_id IS NOT NULL "
            "GROUP BY parent_id",
            (OWNER,),
        ).fetchall()
        assert max(c for _, c in fanout_rows) == a["max_fanout"]
        assert len(fanout_rows) == a["parent_count"]

        chain = a["deepest_chain"]
        chain_rows = {
            row[0]: row
            for row in conn.execute(
                "SELECT id, parent_id, path, depth FROM goals WHERE owner = %s AND id = ANY(%s)",
                (OWNER, chain),
            ).fetchall()
        }
        assert set(chain_rows) == set(chain), "deepest_chain id missing from goals"
        prev_id: str | None = None
        prev_path: str | None = None
        for rank, cid in enumerate(chain):
            _id, parent_id, path, depth = chain_rows[cid]
            assert depth == rank, f"{cid}: depth {depth} != chain rank {rank}"
            if rank == 0:
                assert parent_id is None
                assert path == f"/{cid}/"
            else:
                assert parent_id == prev_id
                assert path == f"{prev_path}{cid}/"
            prev_id, prev_path = cid, path

        # root_id substitute — see module docstring
        root_id = chain[0]
        found = conn.execute(
            "SELECT 1 FROM goals WHERE owner = %s AND id = %s", (OWNER, root_id)
        ).fetchone()
        assert found is not None

        raw_rows = json.loads(EXPORT_PATH.read_text())
        checked_ids = {r["id"] for r in raw_rows if r.get("checked")}
        done_rows = conn.execute(
            "SELECT id, done_at, created_at FROM goals WHERE owner = %s", (OWNER,)
        ).fetchall()
        for goal_id, done_at, created_at in done_rows:
            if goal_id in checked_ids:
                assert done_at == created_at
            else:
                assert done_at is None

        colored = conn.execute(
            "SELECT count(*) FROM goals WHERE owner = %s AND color IS NOT NULL", (OWNER,)
        ).fetchone()[0]
        assert colored == a["color_count"]

        forbidden = {"space_id", "bucket_id", "assignee_id", "start_time", "end_time", "url"}
        leaked_columns = conn.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = 'public' AND table_name = 'goals' AND column_name = ANY(%s)",
            (list(forbidden),),
        ).fetchall()
        assert leaked_columns == []


# --- S-85 -------------------------------------------------------------------------------------


def test_s85_input_order_does_not_matter(
    census: dict | None,
    imported: tuple[str, str, subprocess.CompletedProcess[str]] | None,
    tmp_path: Path,
) -> None:
    """S-85 — a fixed-seed shuffle of the real 567 rows, written only to pytest's own `tmp_path`
    (outside the repo, auto-cleaned, never `artifacts/`, never committed — not a "shipped
    fixture" or "test artifact" in the Zone-1 sense those terms carry elsewhere in this suite).
    Asserts the same row digest as S-79's shared import, computed entirely inside Postgres."""
    if census is None or imported is None:
        gate(_F3_ABSENT)
    _db_name, dsn, _result = imported

    with psycopg.connect(dsn, autocommit=True) as conn:
        digest_s79 = _digest(conn, OWNER)

    raw_rows = json.loads(EXPORT_PATH.read_text())
    shuffled = raw_rows[:]
    random.Random(20260808).shuffle(shuffled)  # same seed convention as gen_corpus.py's --seed
    shuffled_path = tmp_path / "shuffled_export.json"
    shuffled_path.write_text(json.dumps(shuffled))

    with fresh_clone("f0") as db_name:
        shuffled_dsn = _env_dsn(db_name)
        result = _run_importer(shuffled_dsn, drop="calendar+onboarding", input_path=shuffled_path)
        assert result.returncode == 0, result.stderr
        assert "ForeignKeyViolation" not in result.stderr

        with psycopg.connect(shuffled_dsn, autocommit=True) as conn:
            digest_shuffled = _digest(conn, OWNER)

    assert digest_shuffled == digest_s79


# --- S-86 (no F3 tag — five synthetic, always-run cases) ------------------------------------


def _craft(tmp_path: Path, content: object) -> Path:
    path = tmp_path / "bad.json"
    path.write_text(content if isinstance(content, str) else json.dumps(content))
    return path


def test_import_clamps_legacy_child_above_parent_and_reports_count(tmp_path: Path) -> None:
    """A v1-shaped SYN export is reconciled without weakening interactive placement law."""
    source = _craft(
        tmp_path,
        [
            {
                "id": "SYNCLAMP1",
                "parent_id": None,
                "vertical": "week",
                "date": "2026-08-10",
                "name": "SYN clamp parent",
                "created_datetime": "2026-08-01T09:00:00+00:00",
            },
            {
                "id": "SYNCLAMP2",
                "parent_id": "SYNCLAMP1",
                "vertical": "quarter",
                "date": "2026-08-08",
                "name": "SYN legacy child",
                "created_datetime": "2026-08-01T09:01:00+00:00",
            },
            {
                "id": "SYNCLAMP3",
                "parent_id": "SYNCLAMP1",
                "vertical": "day",
                "date": "2026-08-10",
                "name": "SYN valid child",
                "created_datetime": "2026-08-01T09:02:00+00:00",
            },
        ],
    )
    with fresh_clone("f0") as db_name:
        dsn = _env_dsn(db_name)
        result = _run_importer(dsn, input_path=source, owner="SYN-import-owner")
        assert result.returncode == 0, result.stderr
        parsed = _parse_reconciliation(result.stdout)
        assert parsed["clamped_to_parent"] == 1
        with psycopg.connect(dsn, autocommit=True) as conn:
            rows = dict(
                conn.execute(
                    "SELECT id, (vertical::text, period_key) FROM goals "
                    "WHERE owner = 'SYN-import-owner' ORDER BY id"
                ).fetchall()
            )
        assert rows == {
            "SYNCLAMP1": ("week", "2026-W33"),
            "SYNCLAMP2": ("week", "2026-W33"),
            "SYNCLAMP3": ("day", "2026-08-10"),
        }


def test_s86a_not_json(tmp_path: Path, db_dsn: str) -> None:
    """S-86(a) — the file does not parse as JSON at all."""
    bad = _craft(tmp_path, "{this is not json")
    result = _run_importer(db_dsn, input_path=bad)
    assert result.returncode == 2
    assert str(bad) in result.stderr
    _assert_no_partial_state(db_dsn)


def test_s86b_json_object_not_array(tmp_path: Path, db_dsn: str) -> None:
    """S-86(b) — valid JSON, but an object where an array of rows is required."""
    bad = _craft(tmp_path, {"id": "AAAAAAAA"})
    result = _run_importer(db_dsn, input_path=bad)
    assert result.returncode == 2
    assert str(bad) in result.stderr
    _assert_no_partial_state(db_dsn)


def test_s86c_row_missing_id(tmp_path: Path, db_dsn: str) -> None:
    """S-86(c) — row 1 (0-based) has no `id`."""
    bad = _craft(
        tmp_path,
        [
            {"id": "AAAAAAAA", "created_datetime": "2026-01-01T00:00:00+00:00"},
            {"created_datetime": "2026-01-01T00:00:00+00:00"},
        ],
    )
    result = _run_importer(db_dsn, input_path=bad)
    assert result.returncode == 2
    assert str(bad) in result.stderr
    assert "row 1" in result.stderr
    assert "id" in result.stderr
    _assert_no_partial_state(db_dsn)


def test_s86d_invalid_vertical(tmp_path: Path, db_dsn: str) -> None:
    """S-86(d) — `vertical: 'fortnight'`, not one of the seven scale strings."""
    bad = _craft(
        tmp_path,
        [
            {
                "id": "AAAAAAAA",
                "created_datetime": "2026-01-01T00:00:00+00:00",
                "vertical": "fortnight",
                "date": "2026-01-01",
            }
        ],
    )
    result = _run_importer(db_dsn, input_path=bad)
    assert result.returncode == 2
    assert str(bad) in result.stderr
    assert "row 0" in result.stderr
    assert "vertical" in result.stderr
    _assert_no_partial_state(db_dsn)


def test_s86e_dangling_parent_id(tmp_path: Path, db_dsn: str) -> None:
    """S-86(e) — `parent_id` points at an id absent from the file and not previously imported
    (a fresh F0 clone has no rows of any kind, so `known_ids` is empty here)."""
    bad = _craft(
        tmp_path,
        [
            {
                "id": "AAAAAAAA",
                "created_datetime": "2026-01-01T00:00:00+00:00",
                "parent_id": "NOPE0000",
            }
        ],
    )
    result = _run_importer(db_dsn, input_path=bad)
    assert result.returncode == 2
    assert str(bad) in result.stderr
    assert "row 0" in result.stderr
    assert "parent_id" in result.stderr
    _assert_no_partial_state(db_dsn)
