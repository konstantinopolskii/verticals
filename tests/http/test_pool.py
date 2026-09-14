"""S-46 — connections are returned to the pool under a mixed, sustained load, docs/E2E.md §4.

`server`'s own fixture (tests/http/conftest.py) already boots with `VERTICALS_POOL_MIN=2,
VERTICALS_POOL_MAX=10` — the same numbers this scenario names — so no bespoke server config is
needed here.

**Split into three tests, per the orchestrator's ruling on this file's first draft, then
recalibrated once queue row 34 landed (`verticals/db/pool.py`, commit a904576).** That first draft
asserted, in one test, both that the pool never grows past `pool_max` under load *and* that it
settles back to `pool_min` within a 2s quiesce afterward — and the second half failed honestly
against real code. Root-caused (source read of the installed psycopg_pool 3.3.1, plus standalone
timing repros) to `open_pool` never passing `max_idle` to `ConnectionPool(...)`, so it ran at the
library's own default, 600s — and the deeper finding, confirmed independently by the
orchestrator: no `max_idle` value fixes this by itself. `_shrink_pool` closes **at most one** idle
connection per `max_idle`-second cycle, gated on the *previous* full cycle having seen zero
contention, so retiring 8 excess connections (`pool_max=10` down to `pool_min=2`) takes 8+ cycles
no matter how `max_idle` is tuned — no value above roughly 0.25s can satisfy a 2s window at all,
and anything near that ceiling means closing a connection roughly every 150-300ms, fighting the
entire point of pooling under perfectly ordinary bursty traffic. The properties live on different
timescales and do not belong in one assertion:

  1. **The ceiling holds, and every connection comes back** —
     `test_s46_connections_are_returned_to_the_pool` below: `pool_max` never breached (sampled
     every 100ms through the burst), the post-burst sample series is non-increasing, and a probe
     request issued the instant the burst ends still gets an immediate checkout — proof something
     was actually free, not just proof the ceiling number never moved. Real, fast, passes today
     against the actual HTTP surface and the production pool.
  2. **`open_pool` states its idle policy explicitly, and enforces it** —
     `test_pool_open_pool_states_its_idle_policy_explicitly` below: the pool `open_pool` builds
     reports `max_idle == DEFAULT_MAX_IDLE_SECONDS` (300.0 — a single-user, home-hosted tool's own
     number, not the library's 600 and not a value chosen to make a test pass, per that constant's
     own docstring), and a non-positive `max_idle` is refused before a pool is ever built.
  3. **Idle connections are eventually reclaimed, as a policy** —
     `test_pool_idle_connections_are_reclaimed_when_max_idle_is_tuned` below, against a pool
     *this test constructs itself* with a small, test-chosen `max_idle`, proving the mechanism
     genuinely works at a timescale a caller controls, within the orchestrator's own formula for
     how long draining `max_size` down to `min_size` may take: `(max_size - min_size + 2) x
     max_idle`. Neither of the last two claims an `S-46` id (the naming law: claim an id only
     through the scenario's own entry point, and neither makes an HTTP request).
"""

from __future__ import annotations

import queue
import threading
import time

import httpx
import psycopg
import pytest
from psycopg_pool import ConnectionPool

from verticals.db.pool import DEFAULT_MAX_IDLE_SECONDS, open_pool
from tests.http.conftest import SERVER_APP_NAME

TOTAL_REQUESTS = 500
CONCURRENT_CLIENTS = 20
POOL_MAX = 10
SAMPLER_APP_NAME = "s46_sampler"
RECLAIM_APP_NAME = "pool_reclaim_probe"


def _row_count(dsn: str) -> int:
    with psycopg.connect(dsn, autocommit=True) as conn:
        (count,) = conn.execute("SELECT count(*) FROM goals").fetchone()
    return count


class _ConnectionSampler:
    """Own short-lived connections, one per sample. Each sample is stamped with `time.monotonic()`
    at read time, not just the bare count, so a caller can split the series into "during" and
    "after" a burst it ran concurrently with this sampler.

    **Counts the pool positively, by `application_name`.** E2E.md S-46's Steps name the query
    literally — `SELECT count(*) FROM pg_stat_activity WHERE datname = current_database()` — and
    that query answers a different question than the Assert asks. "Backends on this database" is
    not "connections the pool opened": Postgres attaches its own backends to a database (an
    autovacuum worker carries `datname` and an empty `application_name`, and this cluster runs
    with `autovacuum on`, `autovacuum_max_workers=3`), and any of them lands in a count that the
    ceiling assertion then compares against `pool_max`.

    That is not theoretical. Observed under parallel load, with the pool sitting exactly at its
    ceiling: `AssertionError: observed 11 connections, over pool_max=10`, from the series
    `[2, 10, 10, 10, 10, 10, ...]`. The pool was behaving perfectly; the eleventh backend was
    never its. Note the direction — an uncounted backend can only push the count *up*, so the old
    predicate could manufacture a FAIL but could never hide a real breach.

    This is a correction to the literal Step, not an extension of it, and the Step was already
    being corrected: the shipped version of this class subtracted its own monitoring connection
    (`application_name != 's46_sampler'`) because the Step's own SQL would otherwise count the
    sampler and make `<= pool_max` an off-by-one question. Same fix, carried to its end — identify
    the subject rather than enumerate the intruders one incident at a time. Filed for the document
    in `docs/PENDING_DOC_FIXES.md`; the Assert ("connection count <= pool_max at all times") is
    unchanged and is what this measures.
    """

    def __init__(self, dsn: str) -> None:
        joiner = "&" if "?" in dsn else "?"
        self._dsn = f"{dsn}{joiner}application_name={SAMPLER_APP_NAME}"
        self._samples: list[tuple[float, int]] = []
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                with psycopg.connect(self._dsn, autocommit=True, connect_timeout=2) as conn:
                    (count,) = conn.execute(
                        "SELECT count(*) FROM pg_stat_activity"
                        " WHERE datname = current_database() AND application_name = %s",
                        (SERVER_APP_NAME,),
                    ).fetchone()
                self._samples.append((time.monotonic(), count))
            except psycopg.OperationalError:
                pass  # a sample lost to a momentary contention spike is not this test's subject
            time.sleep(0.1)

    def start(self) -> "_ConnectionSampler":
        self._thread.start()
        return self

    def stop(self) -> list[tuple[float, int]]:
        self._stop.set()
        self._thread.join(timeout=5)
        return self._samples


def _build_work_queue(client: httpx.Client) -> "queue.Queue[tuple[str, callable]]":
    """250 board / 100 create / 50 patch / 50 delete-409 / 25 404 / 25 422 = 500, each a
    zero-argument callable returning a `httpx.Response`. Every non-create request targets fixture
    rows that never change shape under this mix (`SYNDAY01` keeps its 3 children throughout —
    nothing here ever deletes them; `SYNCOL01` is only ever patched, never removed)."""
    q: "queue.Queue[tuple[str, callable]]" = queue.Queue()
    counter = {"n": 0}

    def make_board():
        return lambda: client.get("/api/board", params={"date": "2026-08-08"})

    def make_create():
        counter["n"] += 1
        i = counter["n"]
        return lambda: client.post("/api/goals", json={"title": f"load-{i}"})

    def make_patch():
        # D231: colour patches are refused off value roots; a title patch is the same cheap
        # idempotent 200 this burst needs.
        return lambda: client.patch("/api/goals/SYNCOL01", json={"title": "SYN pool patch"})

    def make_delete_409():
        return lambda: client.delete("/api/goals/SYNDAY01")

    def make_404():
        return lambda: client.get("/api/goals/ZZZZZZZZ")

    def make_422():
        return lambda: client.post("/api/goals", json={})

    items: list[tuple[str, callable]] = []
    items += [("board", make_board()) for _ in range(250)]
    items += [("create", make_create()) for _ in range(100)]
    items += [("patch", make_patch()) for _ in range(50)]
    items += [("delete_409", make_delete_409()) for _ in range(50)]
    items += [("404", make_404()) for _ in range(25)]
    items += [("422", make_422()) for _ in range(25)]
    assert len(items) == TOTAL_REQUESTS

    # Round-robin interleave, not run in six contiguous blocks — 20 workers pulling from one
    # queue already interleaves across *workers*, but keeping the block order would still let one
    # worker run 250 board calls in a row before ever touching another kind. `items[i::20]`
    # concatenated for `i` in range(20) round-robins the six kinds across the whole queue.
    interleaved: list[tuple[str, callable]] = []
    for i in range(CONCURRENT_CLIENTS):
        interleaved.extend(items[i::CONCURRENT_CLIENTS])
    for item in interleaved:
        q.put(item)
    return q


def test_s46_connections_are_returned_to_the_pool(client: httpx.Client, server) -> None:
    before = _row_count(server.dsn)

    work = _build_work_queue(client)
    results: list[tuple[str, int, float]] = []  # (kind, status, elapsed_seconds)
    results_lock = threading.Lock()
    errors: list[BaseException] = []

    def worker() -> None:
        while True:
            try:
                kind, make_request = work.get_nowait()
            except queue.Empty:
                return
            try:
                t0 = time.perf_counter()
                resp = make_request()
                elapsed = time.perf_counter() - t0
                with results_lock:
                    results.append((kind, resp.status_code, elapsed))
            except BaseException as exc:  # noqa: BLE001 — collected, asserted on, never swallowed
                with results_lock:
                    errors.append(exc)
            finally:
                work.task_done()

    sampler = _ConnectionSampler(server.dsn).start()

    threads = [threading.Thread(target=worker) for _ in range(CONCURRENT_CLIENTS)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=120)
    t_burst_end = time.monotonic()

    # A probe issued the instant the burst ends: if it gets a fast 200, a connection was free
    # for it immediately — the live counterpart to "every connection comes back," not merely an
    # inference from the ceiling number never having moved.
    t0 = time.perf_counter()
    probe = client.get("/api/board", params={"date": "2026-08-08"})
    probe_elapsed = time.perf_counter() - t0
    assert probe.status_code == 200
    assert probe_elapsed < 1.0, (
        f"the first request after the burst took {probe_elapsed:.2f}s — the pool did not grant "
        "an immediate checkout, which means something was still held"
    )

    time.sleep(1.0)  # gather a handful of post-burst samples before stopping the sampler
    samples = sampler.stop()

    assert errors == [], f"{len(errors)} of {TOTAL_REQUESTS} requests raised: {errors!r}"
    assert len(results) == TOTAL_REQUESTS

    assert samples, "the sampler never got a single reading in"
    counts = [count for _, count in samples]
    assert max(counts) <= POOL_MAX, f"observed {max(counts)} connections, over pool_max={POOL_MAX}"

    post_burst = [count for ts, count in samples if ts >= t_burst_end]
    assert len(post_burst) >= 3, f"only {len(post_burst)} post-burst samples — window too short"
    non_increasing = all(post_burst[i] >= post_burst[i + 1] for i in range(len(post_burst) - 1))
    assert non_increasing, f"connection count rose after the burst ended: {post_burst}"

    statuses_5xx = [(kind, status) for kind, status, _ in results if status >= 500]
    assert statuses_5xx == [], f"{len(statuses_5xx)} requests returned 5xx: {statuses_5xx[:10]}"

    slow = [(kind, elapsed) for kind, _, elapsed in results if elapsed > 5.0]
    assert slow == [], f"{len(slow)} requests exceeded the 5s wall-clock deadline: {slow[:10]}"

    by_kind_status: dict[str, set[int]] = {}
    for kind, status, _ in results:
        by_kind_status.setdefault(kind, set()).add(status)
    assert by_kind_status["board"] == {200}
    assert by_kind_status["create"] == {201}
    assert by_kind_status["patch"] == {200}
    assert by_kind_status["delete_409"] == {409}
    assert by_kind_status["404"] == {404}
    assert by_kind_status["422"] == {422}

    after = _row_count(server.dsn)
    assert after - before == 100


def test_pool_open_pool_states_its_idle_policy_explicitly(db_dsn: str) -> None:
    """Not `test_s46_*` — no HTTP request, so no scenario id claimed (see module docstring).

    `verticals/db/pool.py` is WP-01's file; queue row 34 landed there (commit a904576) once this
    package reported the settle-time defect. Checked here rather than taken on faith: the pool
    `open_pool` actually builds reports the documented default, and the `> 0` guard the module's
    own docstring promises is real, not aspirational."""
    pool = open_pool(db_dsn)
    try:
        assert pool.max_idle == DEFAULT_MAX_IDLE_SECONDS == 300.0
    finally:
        pool.close()

    for bad_value in (0, -1.0):
        with pytest.raises(ValueError, match="max_idle"):
            open_pool(db_dsn, max_idle=bad_value)


def test_pool_idle_connections_are_reclaimed_when_max_idle_is_tuned(db_dsn: str) -> None:
    """Not `test_s46_*` — see the module docstring's "split into three tests." E2E.md's S-46
    Method is specifically an HTTP burst through this suite's own `server`/`client` fixtures
    (`test_s46_connections_are_returned_to_the_pool` above); this test never makes an HTTP
    request and does not claim that scenario id.

    Answers the question the orchestrator's ruling raised: does psycopg_pool's `max_idle` knob
    actually reclaim idle connections at a timescale a caller controls, at all — proven here
    against a pool this test builds itself (`open_pool` itself, not a bare `ConnectionPool`, now
    that row 34 gives it a `max_idle` parameter to tune) with a small, test-chosen `max_idle`, not
    the production pool's own `DEFAULT_MAX_IDLE_SECONDS = 300.0` (asserted separately, above).

    The deadline is not a guess: `(max_size - min_size + 2) x max_idle` is the orchestrator's own
    formula for `_shrink_pool`'s worst case — at most one connection reclaimed per `max_idle`
    cycle, plus slack for the cycle the burst itself consumes. Measured empirically against the
    installed psycopg_pool (3.3.1) before being trusted here: at `max_idle=0.3` this bound is 3.0s
    and the pool actually settled at ~2.7s; `max_idle=0.5` (used below, for more comfortable
    absolute margin against jitter from whatever else is running on this box at the same time —
    this suite is not the only thing on the machine) gives a 5.0s bound.

    `db_dsn` (tests/conftest.py) is a fresh, uniquely-named per-test clone database — no other
    test or concurrently-running agent's connections are ever attached to it, so the only thing
    the sampling query has to exclude is its own connection, tagged with `RECLAIM_APP_NAME` for
    exactly that (a query counting activity always sees its own connection unless it filters
    itself out — the same reason the burst test's own sampler excludes itself)."""
    min_size, max_size, max_idle = 2, 10, 0.5
    settle_bound_seconds = (max_size - min_size + 2) * max_idle  # 5.0s

    pool = open_pool(db_dsn, min_size=min_size, max_size=max_size, max_idle=max_idle)
    sample_dsn = db_dsn + ("&" if "?" in db_dsn else "?") + f"application_name={RECLAIM_APP_NAME}"
    try:
        conns = [pool.getconn() for _ in range(max_size)]
        for c in conns:
            pool.putconn(c)

        def _active_count() -> int:
            with psycopg.connect(sample_dsn, autocommit=True) as conn:
                (n,) = conn.execute(
                    "SELECT count(*) FROM pg_stat_activity"
                    " WHERE datname = current_database() AND application_name != %s",
                    (RECLAIM_APP_NAME,),
                ).fetchone()
            return n

        deadline = time.monotonic() + settle_bound_seconds
        settled = False
        last_seen = None
        while time.monotonic() < deadline:
            last_seen = _active_count()
            if last_seen <= min_size:
                settled = True
                break
            time.sleep(0.05)
        assert settled, (
            f"pool did not settle to min_size={min_size} within {settle_bound_seconds:.1f}s "
            f"of max_idle={max_idle}; last saw {last_seen}"
        )
    finally:
        pool.close()


def test_pool_sampler_counts_the_server_pool_and_not_its_neighbours(server) -> None:
    """The sampler's immunity to backends that are not the pool's, asserted rather than assumed.

    This is the guard for the correction described in `_ConnectionSampler`'s docstring. Under the
    predicate it replaced — every backend on the database except the sampler's own — a neighbour
    holding a connection to the same database was indistinguishable from a pool connection, and
    the ceiling assertion in S-46 turned that into `observed 11 connections, over pool_max=10`
    while the pool was behaving correctly.

    Opens real connections to the same database, with an `application_name` that is not the
    server's, and asserts the count the sampler reports does not move. No traffic is issued to the
    server during the window, so its pool has no reason to grow on its own: any increase would be
    the sampler counting somebody else's connection, which is exactly the defect.

    Claims no scenario id. S-46's own Steps do not ask for this; it protects S-46's instrument.
    """
    neighbours = 4
    sampler = _ConnectionSampler(server.dsn).start()
    try:
        time.sleep(0.5)  # a handful of samples with nothing else attached
        split = time.monotonic()
        conns = [
            psycopg.connect(server.dsn, autocommit=True, application_name=f"not_the_server_{i}")
            for i in range(neighbours)
        ]
        try:
            # Prove the neighbours are genuinely attached to the same database and visible in
            # pg_stat_activity — otherwise this test could pass by having arranged nothing at all.
            (visible,) = conns[0].execute(
                "SELECT count(*) FROM pg_stat_activity"
                " WHERE datname = current_database() AND application_name LIKE 'not_the_server_%'"
            ).fetchone()
            assert visible == neighbours, (
                f"expected {neighbours} neighbour backends visible on this database, saw {visible}"
                " — the test arranged nothing and would prove nothing"
            )
            time.sleep(0.7)  # several more samples, now with the neighbours attached
        finally:
            for c in conns:
                c.close()
    finally:
        samples = sampler.stop()

    before = [n for t, n in samples if t < split]
    during = [n for t, n in samples if t >= split]
    assert before and during, f"sampler produced too few samples to judge: {samples}"
    assert max(during) <= max(before), (
        f"the sampler counted connections that are not the server's: {max(before)} before "
        f"{neighbours} neighbours attached, {max(during)} while they were attached. Series: {samples}"
    )
    assert max(samples, key=lambda s: s[1])[1] <= POOL_MAX, samples
