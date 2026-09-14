"""Regression coverage for `api/deps.py`'s `get_conn` — not a docs/E2E.md scenario, so nothing
here claims a `test_sNN_*` name. Every `X-Query-Count` and `/healthz` `queries` assertion in this
suite depends on the counting mechanism itself being honest; this is the test that watches it
directly, without needing a live HTTP server to notice a regression.

Found while chasing what looked like an S-32 failure: a connection returned to the pool still
carrying `CountingCursor` as its `cursor_factory` keeps carrying it while idle, so anything the
pool's own background maintenance later runs on that connection — a `check=` callback, a
`reset=` callback, any future `psycopg_pool` internal housekeeping that calls `execute` — would
run through the leftover factory and inflate both counters for a statement no request issued.
`get_conn` restores the connection's original `cursor_factory` in a `finally` around its `yield`
for exactly this reason (traced with `psycopg_pool.ConnectionPool(..., check=
ConnectionPool.check_connection)` reproducing the leak in about ten lines with no server at all
— confirmed *and* confirmed unnecessary for `open_pool`'s own current, callback-free
configuration: this suite's actual S-32 failure turned out to be this file's test methodology,
not this defect. The defect is real regardless, and this is the guard for it.)
"""

from __future__ import annotations

import types

import pytest
from psycopg_pool import ConnectionPool

from verticals.api import deps


def _fake_request(pool: ConnectionPool):
    """`get_conn` reads exactly one path off its argument: `request.app.state.pool`. A
    `SimpleNamespace` chain is the whole surface it needs — no FastAPI `Request` is validated
    here, since `get_conn` is called as a plain context manager from route bodies, never
    resolved through FastAPI's own dependency injector."""
    return types.SimpleNamespace(app=types.SimpleNamespace(state=types.SimpleNamespace(pool=pool)))


def test_deps_bare_checkout_does_not_move_the_global_counter(db_dsn: str) -> None:
    pool = ConnectionPool(db_dsn, min_size=1, max_size=1, open=True)
    try:
        with deps.get_conn(_fake_request(pool)) as conn:
            conn.execute("SELECT 1")
        after_real_statement = deps.read_global_count()

        for _ in range(5):
            with deps.get_conn(_fake_request(pool)) as conn:
                pass  # a bare checkout — no statement of this call's own
        assert deps.read_global_count() == after_real_statement

        # Not just "uncounted this time" — the connection must leave `get_conn` carrying its
        # original factory, not merely a factory nobody happened to invoke yet.
        with pool.connection() as raw_conn:
            assert raw_conn.cursor_factory is not deps.CountingCursor
    finally:
        pool.close()


def test_deps_cursor_factory_restored_even_when_the_route_raises(db_dsn: str) -> None:
    """The `finally` around `get_conn`'s `yield` has to run on the error path too — any `core/`
    exception, any bug, must not leave `cursor_factory` stuck on `CountingCursor` for whichever
    unrelated request checks this same physical connection out next."""
    pool = ConnectionPool(db_dsn, min_size=1, max_size=1, open=True)
    try:
        with pytest.raises(ValueError):
            with deps.get_conn(_fake_request(pool)) as conn:
                raise ValueError("simulated route failure")

        with pool.connection() as raw_conn:
            assert raw_conn.cursor_factory is not deps.CountingCursor
    finally:
        pool.close()
