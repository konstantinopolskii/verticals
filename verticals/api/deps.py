"""Three things every route needs, and the one place each is decided: bearer auth (checked
before any connection is touched — S-32), the query-counting mechanism (`X-Query-Count` per
request, the cumulative `queries` figure `/healthz` reports), and the one-transaction-per-
request connection a route calls a `core/` function with (IR-02, for free — see below).
"""

from __future__ import annotations

import hmac
import threading
from collections.abc import Iterator
from contextlib import contextmanager

import psycopg
from fastapi import Header, HTTPException, Request
from psycopg_pool import ConnectionPool

# --- query counting ---------------------------------------------------------------------------
#
# One counter per connection (the per-request `X-Query-Count` header — safe with no lock, since
# the pool hands each connection to exactly one request at a time) and one counter for the whole
# process (`/healthz`'s cumulative `queries` — genuinely shared across every connection and every
# thread Starlette's threadpool runs a handler on, so this one is lock-protected). Both increment
# from the same place: every `core/` module calls `conn.execute(...)`, which psycopg3 implements
# as sugar for `conn.cursor().execute(...)` — so a `cursor_factory` that hands back the subclass
# below is the one interception point that sees every statement either counter needs to see,
# without `core/` knowing this transport is counting anything at all (IR-06: `X-Query-Count` is
# application-owned product code, not the `pg_stat_statements` mechanism `tests/harness/stmt.py`
# scopes to S-25/S-27 alone).

_global_lock = threading.Lock()
_global_count = 0


def _bump_global() -> None:
    global _global_count
    with _global_lock:
        _global_count += 1


def read_global_count() -> int:
    """`/healthz`'s `"queries"` field — the process-cumulative count, read after whatever
    statement `/healthz` itself just ran, per S-31/S-32 (the second probe's own statement is
    part of what it reports)."""
    with _global_lock:
        return _global_count


class CountingCursor(psycopg.Cursor):
    """`psycopg.Cursor` declares `__slots__ = ()`; subclassing it *without* redeclaring
    `__slots__` gives this class a normal `__dict__`, and `psycopg.Connection` itself carries no
    `__slots__` at all — both confirmed against the installed psycopg 3.3.4 before relying on
    either. `connection.query_count` is set fresh by `get_conn` below on every checkout, so it
    always exists by the time `execute` runs on that connection."""

    def execute(self, *args, **kwargs):
        _bump_global()
        self.connection.query_count += 1
        return super().execute(*args, **kwargs)

    def executemany(self, *args, **kwargs):
        _bump_global()
        self.connection.query_count += 1
        return super().executemany(*args, **kwargs)


# --- bearer auth ---------------------------------------------------------------------------


def verify_bearer_token(
    request: Request, authorization: str | None = Header(default=None)
) -> None:
    """Router-level dependency (`APIRouter(dependencies=[Depends(verify_bearer_token)])`) —
    FastAPI resolves dependencies passed to a router before any path-operation-level dependency
    on the route it matched, which is what makes "checked before the database" true by
    construction rather than by hoping two independent dependencies happen to run in declaration
    order: this function never touches `request.app.state.pool`, so there is nothing here to
    race against in the first place.

    `hmac.compare_digest`, never `==` (S-113) — comparison time must not depend on how much of
    the token happened to match. The rejected value is never placed in the response body or a
    log line, on either failure path below (S-113's "never echoed back").
    """
    expected = request.app.state.config.token
    if authorization is None or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=401,
            detail="missing bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    presented = authorization.removeprefix("Bearer ")
    if not hmac.compare_digest(presented, expected):
        raise HTTPException(
            status_code=401,
            detail="invalid bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )


# --- the per-request connection -------------------------------------------------------------


@contextmanager
def get_conn(request: Request) -> Iterator[psycopg.Connection]:
    """One connection, checked out for exactly the lifetime of this `with` block. `pool.
    connection()` is itself a transaction context manager (verified against the installed
    psycopg_pool 3.3.1: entering it opens the connection's own transaction scope; exiting it
    commits on a clean return and rolls back on an exception) — so IR-02's "one transaction per
    request, commit on success, roll back on error" is already true here with no extra code. A
    route that lets a `core/` exception propagate out of this block gets its rollback for free,
    before `api/errors.py`'s handler ever sees the exception.

    `cursor_factory` is restored to whatever it was before this call, in a `finally` around the
    `yield` — the connection must leave this function exactly as it arrived. This guards a
    **latent** defect, not one observed on this pool: reproduced standalone (a bare
    `psycopg_pool.ConnectionPool(..., check=ConnectionPool.check_connection)`, no server, about
    ten lines) — a connection returned to the pool still carrying `CountingCursor` keeps carrying
    it while idle, and if the pool is configured with a `check=` or `reset=` callback, that
    callback's own keepalive `execute` then runs through the leftover factory too, inflating both
    this counter and the process-global one with a statement no request issued. `db/pool.py`'s
    `open_pool()` passes neither `check=` nor `reset=` today, so `check_connection` never runs
    against this pool and the leak is not active here — one config line away, not live. Kept
    anyway: cheap, correct, and the alternative is re-discovering this the day someone adds one of
    those callbacks. `X-Query-Count` and `/healthz`'s `queries` are only honest if a bare checkout
    that runs no statement of its own never moves them (`test_deps.py`'s own regression, written
    directly against the standalone reproduction, not against a symptom this codebase ever
    showed)."""
    pool: ConnectionPool = request.app.state.pool
    with pool.connection() as conn:
        previous_factory = conn.cursor_factory
        conn.cursor_factory = CountingCursor
        conn.query_count = 0
        try:
            yield conn
        finally:
            conn.cursor_factory = previous_factory
