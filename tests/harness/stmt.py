"""The statement-text counter of IR-06 (`docs/IMPLEMENTATION.md` §0.3).

`pg_stat_statements` is cluster-wide, not per-database, and is created exactly once — in the
container's `postgres` maintenance database, never in a `verticals_t_%` clone
(`docker/test-initdb/01-pg-stat-statements.sql`). That single fact drives every function here:

  * there is no "reset" or "read" that does not name a target database. A bare, zero-argument
    `pg_stat_statements_reset()` would zero every sibling worker's counters; IR-06 bans it
    outright and `tests/static/test_seam.py` (WP-18) greps for the literal text. Nothing in this
    module ever calls it with zero arguments — `reset()` below always passes the three-argument
    form, scoped by the target database's `oid`.
  * every function connects to the **maintenance** database (normally `postgres`), because that
    is the only database the extension's SQL objects exist in. The database under test (a
    `verticals_t_*` clone) never has the extension itself — connecting there and calling
    `pg_stat_statements_reset` would fail with "function does not exist", which is the intended
    failure mode for anyone who tries to skip the maintenance connection.

This is **not** the `X-Query-Count` mechanism — that counter is product code, and specifically
`verticals/api/deps.py`'s `CountingCursor`, installed on the connection `get_conn` checks out.
Being `api/` code is the whole reason this module exists: a `core/` call has no request, so there
is nothing to install the cursor on and no header to publish it in.

So there are two mechanisms, split by whether the assertion has a transport under it — `E2E.md`
§1 and `IMPLEMENTATION.md` IR-06 each used to state one of them as the whole rule, and neither
was true alone:

  * over HTTP, `X-Query-Count` per request and `/healthz`'s cumulative `queries`;
  * in `core`, this module, scoped by `dbid`. Not a fallback — the only mechanism available
    there, and what S-09's "zero `UPDATE`" and S-10's "exactly one" run through
    (`tests/core/test_tree.py`).

`pg_stat_statements` is additionally the only source of the literal statement *text*, which
S-25 and S-27 need in order to `EXPLAIN` what Postgres actually ran rather than a query the test
wrote itself; plus this work package's own two-worker cross-talk probe.
"""

from __future__ import annotations

import psycopg

# Three-argument form only. `userid=0` and `queryid=0` mean "any" — `dbid` is the one argument
# that matters here. Never remove an argument to "simplify" this call; a two- or zero-argument
# reset is the exact defect IR-06 exists to prevent.
_RESET_SQL = "SELECT pg_stat_statements_reset(0, (SELECT oid FROM pg_database WHERE datname = %s), 0)"

_READ_SQL = """
    SELECT query, calls
      FROM pg_stat_statements
     WHERE dbid = (SELECT oid FROM pg_database WHERE datname = %s)
"""

_EXTENSION_CHECK_SQL = "SELECT count(*) FROM pg_extension WHERE extname = 'pg_stat_statements'"


def available(maintenance_dsn: str) -> bool:
    """IR-06's stated precondition: the extension needs `shared_preload_libraries` and a server
    restart, so it cannot be assumed. A scenario that finds this `False` reports GATE, never
    PASS — "a statement-text assertion that silently degrades to 'no error' is worse than none"
    (`docs/E2E.md` §2)."""
    with psycopg.connect(maintenance_dsn, autocommit=True) as conn:
        (count,) = conn.execute(_EXTENSION_CHECK_SQL).fetchone()
        return count > 0


def reset(maintenance_dsn: str, target_dbname: str) -> None:
    """Zero the counters for `target_dbname` only. Every other database's counters, including
    a sibling worker's, are untouched — that is the entire point of the three-argument form."""
    with psycopg.connect(maintenance_dsn, autocommit=True) as conn:
        conn.execute(_RESET_SQL, (target_dbname,))


def read(maintenance_dsn: str, target_dbname: str) -> list[tuple[str, int]]:
    """`[(query_text, calls), ...]` for `target_dbname` only, since the last `reset()`."""
    with psycopg.connect(maintenance_dsn, autocommit=True) as conn:
        cur = conn.execute(_READ_SQL, (target_dbname,))
        return [(row[0], row[1]) for row in cur.fetchall()]


def count(maintenance_dsn: str, target_dbname: str) -> int:
    """Total statements executed against `target_dbname` since the last `reset()` — the sum of
    `calls` across every distinct statement text. What a scenario asserting "exactly N
    statements" (S-25, S-27) reads."""
    return sum(calls for _, calls in read(maintenance_dsn, target_dbname))


def current_dbname(conn: psycopg.Connection) -> str:
    """The name of the database `conn` (a connection to a `verticals_t_*` clone, not to the
    maintenance database) is connected to. Convenience for a caller that only holds the
    connection under test and needs the `target_dbname` argument the functions above require —
    this is IR-06's own `current_database()`, evaluated on the connection it actually means."""
    (name,) = conn.execute("SELECT current_database()").fetchone()
    return name
