"""S-127 — position allocation under real concurrency, over HTTP. AC-204.

**What this file cannot claim, and why — queue row 32, orchestrator-confirmed.** S-127's own
"Pre:" step pre-exhausts the head gap of `(t1, week, 2026-W32)` so the burst forces
`tree.renumber`'s whole-group-renumber branch to run mid-flight. That branch only ever fires for
a *midpoint* insert (`after_id` and `before_id` both given) landing in a gap of 1 — confirmed by
reading `core/tree.py::renumber` directly: a plain tail append (`after_id=None, before_id=None`)
always takes `rows[-1][1] + POSITION_GAP`, no ceiling, never renumbers, no matter how packed the
rest of the group is. Nothing HTTP-reachable ever sends `after_id`/`before_id`: `CreateGoalRequest`
and `ScheduleRequest` (`api/schemas.py`) have no such fields, and `core.moves.move_between` — the
one verb that *can* request a midpoint — has zero callers anywhere in `api/routes_goals.py`; its
own docstring at `core/tree.py:406` still calls it "future." So the renumber branch is
unreachable from this transport as shipped, regardless of what this file's own setup pre-loads.

This is not a hole in this WP's card. `E2E.md`'s route table promises `reorder` on
`PATCH /api/goals/{id}` (`E2E.md:913` route table, `E2E.md:1416` capability table), and the MCP
surface promises the same capability — schema half in **S-47** (`E2E.md:1270-1272`: `ids`
mutually exclusive with `id`, `maxItems: 500`, `after_id: string|null`), behavioural half in
**S-133** (`E2E.md:1455`, "Bulk and reorder over MCP" — step 2 already pins the arithmetic:
`update {"id":"SYNORD03","after_id":"SYNORD01"}` lands SYNORD03 at position 1536, the midpoint
between 1024 and 2048) — a product capability specified on both transports and built on neither.
(Originally cited here as S-126, which is actually the mid-reparent kill scenario and has nothing
to do with reorder — orchestrator-caught, row 40, corrected.) Bolting it onto one transport at
the end of this package would only have created a parity gap for WP-19 to discover the hard way.
Reported to the orchestrator rather than worked around or wired in unilaterally; independently
verified there (`grep -rn 'after_id\\|before_id' verticals/api/*.py` returns nothing) and filed as
queue row 32, with WP-19 told directly not to assume HTTP parity exists to mirror. Not fixed
here: wiring `move_between` into a route is outside this WP's own card ("eight routes plus
`/healthz`," no mention of reorder), and changing a shared route's contract unreviewed is its own
risk regardless of ownership.

What this file claims instead, all real and all achieved through the actual HTTP surface: 50
barrier-released concurrent `POST /api/goals` calls into one column never collide, never deadlock,
never disturb the siblings that were already there, settle to a stable total order, and the
advisory-lock serialisation AC-204 requires is both named in the code and observed actually being
held during the burst — the last of these via a `pg_locks` sampler keyed on the exact
`(classid, objid)` a `pg_advisory_xact_lock(hashtext(...))` on this group's own key produces,
verified empirically against a live connection before being hard-coded here (Postgres packs a
promoted-int4 bigint key as `classid = high 32 bits, objid = low 32 bits, objsubid = 1` — checked
directly, both the positive- and negative-hashtext cases, not assumed from documentation).

**2026-08-09 correction — queue row 32 closed, the paragraph above is now half stale.**
`verticals/api/routes_goals.py::patch_goal` wires `after_id` into `core.moves.move_between` as of
this date; `core.moves.move_between` no longer "has zero callers anywhere in `api/routes_goals.py`"
and `CreateGoalRequest`/`ScheduleRequest` having no `after_id`/`before_id` fields is no longer the
whole story — `UpdatePatch` (`api/schemas.py`) now carries `after_id`. Left the original paragraph
above unedited rather than rewritten in place (`docs/PENDING_DOC_FIXES.md`'s own convention: a
correction is a dated addendum, not a silent rewrite of what an earlier WP actually observed at
the time) — every citation and grep result quoted there was true when written and independently
re-verified true of that WP's own card scope.

The renumber branch this file's own Assert language gestures at ("the renumber ran") is *still*
not exercised by this file's `test_s127...` below, and, separately, still cannot be — S-127's own
Steps (docs/E2E.md:1223) are 50 plain tail-append `POST /api/goals` calls, and a tail append
(`after_id=None, before_id=None`) takes `tree.renumber`'s early-return branch unconditionally
(`core/tree.py:449-450`), never the exhausted-gap branch, regardless of what HTTP can now do. That
gap in S-127 itself is filed as `docs/PENDING_DOC_FIXES.md` row 59, not corrected here — rewriting
a catalogue scenario's Steps is not this file's call to make unilaterally.

What *is* new in this file: `test_concurrency_reorder_into_exhausted_gap_forces_renumber` below,
added the same day as the `after_id` wiring, proves the branch is reachable at all now that a
route actually calls `move_between` — the first test anywhere in this suite to do so. It is not
named `test_s127b_...` or similar: no catalogue scenario covers this sequence either (same naming
law reasoning as `tests/http/test_update.py`'s new `test_update_reorder_*` tests).
"""

from __future__ import annotations

import threading
import time
from pathlib import Path

import httpx
import psycopg

REPO_ROOT = Path(__file__).resolve().parents[2]
MOVES_SOURCE = REPO_ROOT / "verticals" / "core" / "moves.py"
CONCURRENT_WORKERS = 50
GROUP_LOCK_KEY = "column\x1ft1\x1fweek\x1f2026-W32"  # core.moves._lock_key's own format


def _group_state(dsn: str) -> list[tuple[str, int]]:
    with psycopg.connect(dsn, autocommit=True) as conn:
        return conn.execute(
            "SELECT id, position FROM goals"
            " WHERE owner = 't1' AND vertical = 'week' AND period_key = '2026-W32'"
            " ORDER BY position"
        ).fetchall()


def _deadlock_count(dsn: str, dbname: str) -> int:
    with psycopg.connect(dsn, autocommit=True) as conn:
        (value,) = conn.execute(
            "SELECT deadlocks FROM pg_stat_database WHERE datname = %s", (dbname,)
        ).fetchone()
    return value


def _dbname(dsn: str) -> str:
    with psycopg.connect(dsn, autocommit=True) as conn:
        (name,) = conn.execute("SELECT current_database()").fetchone()
    return name


def _advisory_classid_objid(dsn: str, key: str) -> tuple[int, int]:
    """What Postgres would store in `pg_locks` for `pg_advisory_xact_lock(hashtext(key))` — the
    int4 `hashtext` result implicitly promotes to bigint (sign-extended), then splits into two
    unsigned 32-bit halves. Derived from a live `hashtext()` call, not computed by hand, so a
    Postgres version that hashed differently would still produce a correct expectation here."""
    with psycopg.connect(dsn, autocommit=True) as conn:
        (value,) = conn.execute("SELECT hashtext(%s)", (key,)).fetchone()
    unsigned64 = value % (2**64)
    return (unsigned64 >> 32), (unsigned64 & 0xFFFFFFFF)


# Was a hand-copy of `tests/core/test_tree.py`'s private helper; now the one shared
# implementation in `tests/harness/tree_invariant.py`, which `tests/conftest.py` also runs in
# every clone's teardown (AC-203).
from tests.harness.tree_invariant import violations as _tree_invariant_violations


class _LockWatcher:
    """Polls `pg_locks` at 5ms resolution on its own connection until `stop()`, recording every
    distinct `(classid, objid)` seen among `locktype = 'advisory'` rows — a best-effort sampler,
    not a guarantee (a lock held for less than one poll interval could be missed), but with 50
    threads contending for the *same* key across the whole burst, the key is held by someone for
    nearly the entire window."""

    def __init__(self, dsn: str) -> None:
        self._conn = psycopg.connect(dsn, autocommit=True)
        self._seen: set[tuple[int, int]] = set()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def _run(self) -> None:
        while not self._stop.is_set():
            rows = self._conn.execute(
                "SELECT classid, objid FROM pg_locks WHERE locktype = 'advisory'"
            ).fetchall()
            self._seen.update(rows)
            time.sleep(0.005)

    def start(self) -> "_LockWatcher":
        self._thread.start()
        return self

    def stop(self) -> set[tuple[int, int]]:
        self._stop.set()
        self._thread.join(timeout=5)
        self._conn.close()
        return self._seen


def test_s127_position_allocation_under_real_concurrency(client: httpx.Client, server) -> None:
    dbname = _dbname(server.dsn)

    # --- "named in the code": a static assertion, not an inference from the outcome -------------
    moves_source = MOVES_SOURCE.read_text()
    assert "pg_advisory_xact_lock" in moves_source
    assert "hashtext" in moves_source

    expected_classid, expected_objid = _advisory_classid_objid(server.dsn, GROUP_LOCK_KEY)

    state_before = _group_state(server.dsn)
    assert len(state_before) == 4, "F2's own G2: four rows already in (t1, week, 2026-W32)"
    ids_before_ordered = [gid for gid, _ in state_before]
    deadlocks_before = _deadlock_count(server.dsn, dbname)

    watcher = _LockWatcher(server.dsn).start()

    barrier = threading.Barrier(CONCURRENT_WORKERS)
    results: list[int] = []
    errors: list[BaseException] = []
    results_lock = threading.Lock()

    def worker(i: int) -> None:
        try:
            barrier.wait(timeout=10)
            resp = client.post(
                "/api/goals",
                json={"title": f"C{i}", "vertical": "week", "anchor_date": "2026-08-05"},
            )
            with results_lock:
                results.append(resp.status_code)
        except BaseException as exc:  # noqa: BLE001 — collected and asserted on, never swallowed
            with results_lock:
                errors.append(exc)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(CONCURRENT_WORKERS)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)

    observed_locks = watcher.stop()

    assert errors == [], f"{len(errors)} of {CONCURRENT_WORKERS} workers raised: {errors!r}"
    assert results == [201] * CONCURRENT_WORKERS, f"non-201 among: {sorted(set(results))}"

    assert (expected_classid, expected_objid) in observed_locks, (
        "never observed the group's own advisory lock held during the burst — sampler resolution "
        f"issue or the lock was not taken; saw {len(observed_locks)} distinct advisory key(s)"
    )

    state_after = _group_state(server.dsn)
    assert len(state_after) == 4 + CONCURRENT_WORKERS
    positions_after = [p for _, p in state_after]
    assert len(set(positions_after)) == len(positions_after), "every position must be distinct"
    assert positions_after == sorted(positions_after)

    deadlocks_after = _deadlock_count(server.dsn, dbname)
    assert deadlocks_after == deadlocks_before, "zero deadlocks"

    # The four pre-existing rows, relative to each other, are untouched — true unconditionally
    # for a pure tail-append burst (see module docstring: this replaces "the renumber ran and
    # preserved order," which cannot be exercised through this transport).
    ids_after_ordered = [gid for gid, _ in state_after]
    surviving_in_order = [gid for gid in ids_after_ordered if gid in set(ids_before_ordered)]
    assert surviving_in_order == ids_before_ordered
    positions_before_by_id = dict(state_before)
    positions_after_by_id = dict(state_after)
    for gid in ids_before_ordered:
        assert positions_after_by_id[gid] == positions_before_by_id[gid], (
            f"{gid}'s own position moved even though no renumber ran"
        )

    # Stable ordering across three consecutive reads.
    reads = [_group_state(server.dsn) for _ in range(3)]
    assert reads[0] == reads[1] == reads[2]

    with psycopg.connect(server.dsn, autocommit=True) as conn:
        assert _tree_invariant_violations(conn, "t1") == []


def test_concurrency_reorder_into_exhausted_gap_forces_renumber(client: httpx.Client, server) -> None:
    """AC-204's renumber clause, actually exercised over HTTP — see the 2026-08-09 addendum to
    this file's module docstring for why `test_s127...` above cannot be this proof and never
    could (its Steps are pure tail-appends; the exhausted-gap branch needs a midpoint request,
    `after_id` *and* `before_id` both set — `core/tree.py:459`'s own `before_pos - after_pos > 1`
    check, read directly, not inferred).

    F2's G2 ships every gap in the group at a full `POSITION_GAP` (1024) — nothing here is
    pre-exhausted by the fixture itself (confirmed against tests/fixtures/f2_synth.sql). So this
    test manufactures the exhausted gap by hand, direct SQL, same convention `_group_state` in
    this file already uses for read-back: SYNORD02 moves from 2048 to 1025, leaving a gap of
    exactly 1 against SYNORD01 (1024) — the smallest gap `tree.renumber`'s own check treats as
    *not* exhausted is 2 (`> 1`), so 1 is the minimal genuine trigger, not an arbitrarily small
    number chosen for convenience.

    Then a real reorder over `PATCH /api/goals/{id}` — SYNORD04 (currently last, at 4096) asks to
    move to right after SYNORD01 — forces `_derive_before_id` to compute `before_id=SYNORD02`
    (the true next sibling by position), which is exactly the pair whose gap was just exhausted.
    `core.moves.move_between` -> `allocate_position` -> `tree.renumber` must take the
    whole-group-renumber branch to satisfy that request at all.
    """
    dsn = server.dsn

    with psycopg.connect(dsn, autocommit=True) as conn:
        conn.execute("UPDATE goals SET position = 1025 WHERE owner = 't1' AND id = 'SYNORD02'")

    before = dict(_group_state(dsn))
    assert before == {"SYNORD01": 1024, "SYNORD02": 1025, "SYNORD03": 3072, "SYNORD04": 4096}, (
        f"setup did not land the expected pre-state: {before}"
    )

    resp = client.patch("/api/goals/SYNORD04", json={"after_id": "SYNORD01"})
    assert resp.status_code == 200, resp.text
    moved = resp.json()
    assert moved["id"] == "SYNORD04"
    assert moved["position"] == 1536, (
        f"expected the midpoint of the *renumbered* 1024/2048 pair, got {moved['position']!r}"
    )

    after = dict(_group_state(dsn))
    assert after == {"SYNORD01": 1024, "SYNORD02": 2048, "SYNORD03": 3072, "SYNORD04": 1536}, (
        f"unexpected post-renumber state: {after}"
    )

    # The actual "renumber ran" proof (S-127's own Assert wording, docs/E2E.md:1240, restated
    # here since S-127 itself cannot reach this branch): SYNORD02's position changed from its
    # first-read value even though SYNORD02 was never the PATCH target — only the whole-group
    # renumber branch touches a sibling's position as a side effect of reordering a different row.
    assert after["SYNORD02"] != before["SYNORD02"], "SYNORD02's position never moved — no renumber ran"
    assert after["SYNORD01"] == before["SYNORD01"], "SYNORD01 happened to renumber to its own value"
    assert after["SYNORD03"] == before["SYNORD03"], "SYNORD03 was not between the exhausted pair"

    ordered = sorted(after, key=after.get)
    assert ordered == ["SYNORD01", "SYNORD04", "SYNORD02", "SYNORD03"], (
        f"SYNORD04 must land strictly between SYNORD01 and SYNORD02: {ordered}"
    )

    with psycopg.connect(dsn, autocommit=True) as conn:
        assert _tree_invariant_violations(conn, "t1") == []
