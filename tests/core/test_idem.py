"""Direct probes for `verticals/core/idem.py` — IR-04, AC-051, AC-052, AC-053, AC-198, AC-199.

Neither S-29 nor S-30 can run end to end this wave: both are specified as entering through
`create()` (docs/E2E.md), which lives in `core/goals.py` — WP-13's file, not built yet
(docs/IMPLEMENTATION.md WP-11 card: "at the w3.writeside verify"). What this file proves
instead, against real Postgres and nothing else, is every property `create()` will need from
`core/idem.py` once it exists — the same split WP-05's `tests/core/test_vertical_unit.py`
already established as precedent for a package whose scenario enters through a verb it does
not own:

  * `test_idem_replay_*` — a real `goals` INSERT stands in for the write
    `create()` will eventually perform: the same call twice writes once and replays (zero
    `INSERT` on `goals`, captured through `pg_stat_statements` via `tests/harness/stmt.py`,
    never a hand-rolled reset — IR-06); a changed payload raises `IdempotencyConflict`
    instead of silently overwriting; a token is scoped `(owner, client_token)`, so two owners
    sharing one token never collide or leak a response (AC-198).
  * `test_idem_expired_*` — a row backdated with a real `UPDATE ... interval '25 hours'`
    (no frozen clock anywhere, docs/BRIEF.md rule 2) is reclaimed by the very call that finds
    it expired, both for one token and at the 5 000-row, owner-scoped scale AC-199 names.
  * `test_concurrent_*` — the development check the WP-11 card calls out by name: not in the
    catalogue, not a scenario, the only thing that tells a correct `ON CONFLICT DO NOTHING
    RETURNING` implementation apart from a check-then-write one that happens to pass S-29
    anyway (docs/IMPLEMENTATION.md §5, R3). 50 real threads, 50 real connections, one
    Postgres — psycopg releases the GIL on the network round-trip, so this is genuine
    concurrent SQL traffic, the same argument `tests/harness/test_runner_contract.py`'s
    two-worker probe makes.

The real S-29/S-30, run through `create()`, are WP-13's job.

Every sequential test below opens its own connection at `autocommit=False` (psycopg3's
default) rather than using the shared `db` fixture from `tests/conftest.py`, which is
`autocommit=True` — fine for a read-only module like `core/search.py`, but wrong here: this
whole module exists to prove what stays invisible *inside* one open transaction (IR-02), and
an autocommit connection commits every statement immediately, which would hide exactly the
bug (a placeholder response visible to a concurrent reader) this file exists to catch.

Run directly:
    PGHOST=127.0.0.1 PGPORT=55432 PGUSER=verticals PGPASSWORD=verticals \
        .venv/bin/python -m pytest tests/core/test_idem.py -v
"""

from __future__ import annotations

import concurrent.futures
import hashlib
import threading
from collections.abc import Iterator

import psycopg
import pytest
from psycopg.types.json import Jsonb

from verticals.core import idem
from verticals.core.errors import IdempotencyConflict, ValidationError
from tests import conftest
from tests.harness import stmt
from tests.harness.report import gate

OWNER = "t1"

PAYLOAD = {"owner": OWNER, "title": "Ship it", "vertical": "day", "anchor_date": "2026-08-08"}
PAYLOAD_CHANGED = {**PAYLOAD, "title": "Ship it later"}


@pytest.fixture
def conn(db_dsn: str) -> Iterator[psycopg.Connection]:
    """A dedicated, non-autocommit connection per test — see the module docstring for why the
    shared `db` fixture (autocommit=True) is the wrong tool here."""
    connection = psycopg.connect(db_dsn)
    try:
        yield connection
    finally:
        connection.close()


def _insert_goal(conn: psycopg.Connection, *, goal_id: str, owner: str, title: str) -> None:
    """A minimal, valid `goals` row — id/owner/path/title is the entire set of NOT NULL
    columns with no default. Stands in for the write `core/goals.py`'s `create()` (WP-13)
    will perform once it exists; this file does not test `create()`, only that
    `core/idem.py` never lets a second identical call reach a second one of these.

    `path` is `f"/{goal_id}/"`, `core/tree.py`'s own root form, not the bare id: since
    `path_well_formed` (`db/migrations/004_path_format.sql`), a bare id is no longer a valid
    `goals` row at all, and this helper's whole point is that it *is* one."""
    conn.execute(
        "INSERT INTO goals (id, owner, path, parked_from_vertical, title) "
        "VALUES (%s, %s, %s, 'life', %s)",
        (goal_id, owner, f"/{goal_id}/", title),
    )


def _goal_count(conn: psycopg.Connection, owner: str = OWNER) -> int:
    (n,) = conn.execute("SELECT count(*) FROM goals WHERE owner = %s", (owner,)).fetchone()
    return n


def _idem_count(conn: psycopg.Connection, owner: str) -> int:
    (n,) = conn.execute(
        "SELECT count(*) FROM idempotency WHERE owner = %s", (owner,)
    ).fetchone()
    return n


# --- S-29: same client_token twice -----------------------------------------------------------


def test_idem_replay_same_payload_writes_once(conn: psycopg.Connection) -> None:
    """AC-051. The first call reserves and writes; the identical second call replays the
    exact stored response and — verified through `pg_stat_statements`, not inferred from the
    row count alone — performs zero `INSERT` on `goals`."""
    dsn = conftest.maintenance_dsn()
    if not stmt.available(dsn):
        gate("pg_stat_statements not available on this cluster")
    dbname = stmt.current_dbname(conn)

    first = idem.reserve(conn, owner=OWNER, client_token="ct-0001", request_digest=idem.digest(PAYLOAD))
    assert isinstance(first, idem.Reserved)
    _insert_goal(conn, goal_id="G0001", owner=OWNER, title="Ship it")
    response = {"id": "G0001", "title": "Ship it"}
    idem.complete(conn, owner=OWNER, client_token="ct-0001", response=response)
    conn.commit()
    assert _goal_count(conn) == 1

    stmt.reset(dsn, dbname)
    second = idem.reserve(
        conn, owner=OWNER, client_token="ct-0001", request_digest=idem.digest(PAYLOAD)
    )
    conn.commit()

    assert isinstance(second, idem.Replayed)
    assert second.response == response, "the replay must hand back the exact stored response"
    assert _goal_count(conn) == 1, "the second call must not have written a second goal"

    captured = stmt.read(dsn, dbname)
    goal_inserts = [text for text, calls in captured if "insert into goals" in text.lower() and calls > 0]
    assert goal_inserts == [], f"second call executed an INSERT on goals: {goal_inserts}"


def test_idem_changed_payload_conflicts_and_writes_nothing(conn: psycopg.Connection) -> None:
    """AC-052. Same token, different payload: `IdempotencyConflict`, not a silent overwrite —
    `goals` and `idempotency` are both unchanged by the refused call."""
    first = idem.reserve(conn, owner=OWNER, client_token="ct-0002", request_digest=idem.digest(PAYLOAD))
    assert isinstance(first, idem.Reserved)
    _insert_goal(conn, goal_id="G0002", owner=OWNER, title="Ship it")
    idem.complete(conn, owner=OWNER, client_token="ct-0002", response={"id": "G0002"})
    conn.commit()

    before_goals, before_idem = _goal_count(conn), _idem_count(conn, OWNER)
    digest_a = idem.digest(PAYLOAD)
    digest_b = idem.digest(PAYLOAD_CHANGED)
    assert digest_a != digest_b, "the two digests must differ for this test to mean anything"

    with pytest.raises(IdempotencyConflict) as exc:
        idem.reserve(conn, owner=OWNER, client_token="ct-0002", request_digest=digest_b)
    assert exc.value.detail["client_token"] == "ct-0002"
    conn.rollback()

    assert _goal_count(conn) == before_goals, "a conflict must write nothing to goals"
    assert _idem_count(conn, OWNER) == before_idem, "a conflict must not touch idempotency either"


def test_idem_token_is_scoped_by_owner_not_global(conn: psycopg.Connection) -> None:
    """AC-198. `(owner, client_token)` is the primary key, not `client_token` alone: the same
    token and the same payload, replayed under a second owner, reserves its own row rather
    than replaying the first owner's — and the first owner's response never surfaces there."""
    shared_token = "ct-shared"
    d = idem.digest(PAYLOAD)

    r1 = idem.reserve(conn, owner="t1", client_token=shared_token, request_digest=d)
    assert isinstance(r1, idem.Reserved)
    idem.complete(conn, owner="t1", client_token=shared_token, response={"id": "T1-SECRET"})
    conn.commit()

    r2 = idem.reserve(conn, owner="t2", client_token=shared_token, request_digest=d)
    assert isinstance(r2, idem.Reserved), "a second owner must get its own reservation, not t1's replay"
    idem.complete(conn, owner="t2", client_token=shared_token, response={"id": "T2-OWN"})
    conn.commit()

    assert _idem_count(conn, "t1") == 1
    assert _idem_count(conn, "t2") == 1
    (t1_response,) = conn.execute(
        "SELECT response_json FROM idempotency WHERE owner = 't1' AND client_token = %s",
        (shared_token,),
    ).fetchone()
    assert t1_response == {"id": "T1-SECRET"}, "t2's reservation must never overwrite t1's row"


# --- S-30: the window is 24 hours, measured against a real timestamp -------------------------


def test_idem_expired_row_reclaimed_by_next_call(conn: psycopg.Connection) -> None:
    """AC-053. No frozen clock anywhere: `created_at` is backdated with a real `UPDATE ...
    interval '25 hours'`, compared against Postgres's own `now()` inside `reserve()`. The
    next call with the same token gets a fresh reservation, not a replay, and the stale row
    is gone by the time that call returns."""
    token = "ct-0003"
    first = idem.reserve(conn, owner=OWNER, client_token=token, request_digest=idem.digest(PAYLOAD))
    assert isinstance(first, idem.Reserved)
    _insert_goal(conn, goal_id="G0003", owner=OWNER, title="Ship it")
    idem.complete(conn, owner=OWNER, client_token=token, response={"id": "G0003"})
    conn.commit()

    conn.execute(
        "UPDATE idempotency SET created_at = now() - interval '25 hours' "
        "WHERE owner = %s AND client_token = %s",
        (OWNER, token),
    )
    conn.commit()

    before_goals = _goal_count(conn)
    second = idem.reserve(conn, owner=OWNER, client_token=token, request_digest=idem.digest(PAYLOAD))
    assert isinstance(second, idem.Reserved), "an expired row must look like no reservation at all"
    _insert_goal(conn, goal_id="G0003b", owner=OWNER, title="Ship it")
    idem.complete(conn, owner=OWNER, client_token=token, response={"id": "G0003b"})
    conn.commit()

    assert _goal_count(conn) == before_goals + 1, "a new id, a new row — not a replay"
    assert _idem_count(conn, OWNER) == 1, "the expired row was removed by the same call, not left behind"


def test_idem_5000_stale_rows_swept_by_ten_writes(
    conn: psycopg.Connection,
) -> None:
    """AC-199, at the size where a leak is visible. 5 000 rows aged 25 hours, seeded directly
    (no 5 000 real reservations needed to set the scene) for one owner; ten ordinary
    `reserve()` calls, each its own fresh token, and the table returns to the live-token
    count. The sweep is owner-scoped and rides every write — not a background job racing to
    catch up, not a table-wide scan that makes every owner pay for one owner's backlog."""
    stale_owner = "t-bulk"
    n = 5000
    values_sql = ",".join(["(%s, %s, %s, %s, now() - interval '25 hours')"] * n)
    params: list[object] = []
    for i in range(n):
        params += [stale_owner, f"ct-stale-{i}", "0" * 64, Jsonb({"id": f"old-{i}"})]
    conn.execute(
        "INSERT INTO idempotency (owner, client_token, request_digest, response_json, created_at) "
        f"VALUES {values_sql}",
        params,
    )
    conn.commit()
    assert _idem_count(conn, stale_owner) == n

    for i in range(10):
        r = idem.reserve(
            conn, owner=stale_owner, client_token=f"ct-live-{i}", request_digest=idem.digest(PAYLOAD)
        )
        assert isinstance(r, idem.Reserved)
        idem.complete(conn, owner=stale_owner, client_token=f"ct-live-{i}", response={"id": f"live-{i}"})
        conn.commit()

    assert _idem_count(conn, stale_owner) == 10, "back to the live-token count, not 5 010"


# --- digest() and input validation -------------------------------------------------------------


def test_digest_is_deterministic_and_key_order_independent() -> None:
    a = idem.digest({"title": "x", "owner": "o"})
    b = idem.digest({"owner": "o", "title": "x"})
    assert a == b
    assert len(a) == 64
    assert a == hashlib.sha256(b'{"owner":"o","title":"x"}').hexdigest()


def test_digest_changes_with_payload() -> None:
    assert idem.digest({"title": "x"}) != idem.digest({"title": "y"})


def test_digest_refuses_a_non_mapping() -> None:
    with pytest.raises(ValidationError):
        idem.digest(["not", "a", "mapping"])  # type: ignore[arg-type]


def test_reserve_refuses_empty_owner(conn: psycopg.Connection) -> None:
    with pytest.raises(ValidationError) as exc:
        idem.reserve(conn, owner="", client_token="ct", request_digest=idem.digest(PAYLOAD))
    assert exc.value.detail["field"] == "owner"


def test_reserve_refuses_empty_client_token(conn: psycopg.Connection) -> None:
    with pytest.raises(ValidationError) as exc:
        idem.reserve(conn, owner=OWNER, client_token="", request_digest=idem.digest(PAYLOAD))
    assert exc.value.detail["field"] == "client_token"


def test_reserve_refuses_malformed_digest(conn: psycopg.Connection) -> None:
    for bad in ("not-a-digest", "0" * 63, "0" * 65, "G" * 64, ""):
        with pytest.raises(ValidationError) as exc:
            idem.reserve(conn, owner=OWNER, client_token="ct", request_digest=bad)
        assert exc.value.detail["field"] == "request_digest"


# --- development check: not S-29, not in the catalogue (WP-11 card, §5 R3) --------------------


def test_concurrent_50_identical_tokens_yield_one_reservation_and_49_replays(db_dsn: str) -> None:
    """"S-29 alone cannot distinguish a correct implementation from a check-then-write one."
    50 real threads, 50 real `psycopg` connections to the same clone — psycopg releases the
    GIL on the network round-trip to Postgres, so this is genuine concurrent SQL traffic, not
    a Python-level illusion of it (the same argument
    `tests/harness/test_runner_contract.py::test_stmt_scoping_has_no_cross_worker_talk`
    makes). A `threading.Barrier` lines up all 50 `reserve()` calls as close to simultaneous
    as the scheduler allows: a check-then-write implementation would let more than one thread
    read "no row yet" before any of them had written one."""
    token = "ct-concurrent"
    n = 50
    barrier = threading.Barrier(n)
    d = idem.digest(PAYLOAD)

    def _call(_: int) -> str:
        # `with psycopg.connect(...)` commits on clean exit, rolls back on exception — verified
        # against a real connection before relying on it here, so one connection per thread is
        # also one transaction per thread, matching the real transport's own IR-02 boundary.
        with psycopg.connect(db_dsn) as own_conn:
            barrier.wait(timeout=30)
            result = idem.reserve(own_conn, owner=OWNER, client_token=token, request_digest=d)
            if isinstance(result, idem.Reserved):
                _insert_goal(own_conn, goal_id="G-CONCURRENT", owner=OWNER, title="Ship it")
                idem.complete(own_conn, owner=OWNER, client_token=token, response={"id": "G-CONCURRENT"})
                return "reserved"
            assert isinstance(result, idem.Replayed)
            return "replayed"

    with concurrent.futures.ThreadPoolExecutor(max_workers=n) as pool:
        futures = [pool.submit(_call, i) for i in range(n)]
        outcomes = [f.result(timeout=30) for f in futures]

    reserved_n = outcomes.count("reserved")
    replayed_n = outcomes.count("replayed")
    assert reserved_n == 1, f"expected exactly 1 reservation among {n} identical tokens, got {reserved_n}"
    assert replayed_n == n - 1, f"expected exactly {n - 1} replays, got {replayed_n}"

    with psycopg.connect(db_dsn, autocommit=True) as check:
        (goal_rows,) = check.execute(
            "SELECT count(*) FROM goals WHERE owner = %s", (OWNER,)
        ).fetchone()
        (idem_rows,) = check.execute(
            "SELECT count(*) FROM idempotency WHERE owner = %s AND client_token = %s",
            (OWNER, token),
        ).fetchone()
    assert goal_rows == 1, f"{n} concurrent identical tokens must produce exactly one goals row, got {goal_rows}"
    assert idem_rows == 1, f"expected exactly one idempotency row for this token, got {idem_rows}"
