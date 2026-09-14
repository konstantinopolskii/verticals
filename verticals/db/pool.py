"""Connection pool factory for the app's two transports.

IR-01: `core/` is synchronous psycopg3. One `ConnectionPool` per process, owned by the
transport — FastAPI route handlers stay `def` (Starlette runs them in its threadpool), and
the MCP server wraps `core` calls in `anyio.to_thread.run_sync`. Neither transport gets its
own pool; there is one pool per process, full stop. That is what keeps two async stacks from
each growing their own idea of how many connections are open.

This module takes its settings as arguments and never reads the environment itself: parsing
`VERTICALS_DATABASE_URL` / `VERTICALS_POOL_MIN` / `VERTICALS_POOL_MAX` is `verticals/config.py`'s
job (a later work package). A transport resolves those values and calls `open_pool(...)`.
"""

from __future__ import annotations

from psycopg_pool import ConnectionPool

# AC-079 asserts these exact defaults.
DEFAULT_POOL_MIN = 2
DEFAULT_POOL_MAX = 10

# Fail fast, not silently forever. A database that is down at boot should say so within this
# many seconds, not hang the process with no explanation.
DEFAULT_OPEN_TIMEOUT_SECONDS = 10.0

# How long a connection may sit idle before the pool is allowed to reclaim it. Passed
# explicitly — psycopg_pool's own default is 600.0 and this used to inherit it silently, which
# is how a scenario came to assert a settle time the shipped policy could not physically reach
# (docs/PENDING_DOC_FIXES.md row 34). 300.0 rather than 600.0 because this is a single-user,
# home-hosted tool: holding eight idle backends for ten minutes after one burst is a real cost
# on a box also running Postgres, and five minutes is still far above any thrash threshold.
#
# Know the shrink arithmetic before changing this. `ConnectionPool._shrink_pool` closes **at
# most one** connection per `max_idle` cycle, and only when the idle-count minimum over the
# whole prior cycle was > 0 — a deliberate anti-thrash guard. Draining `max_size` down to
# `min_size` therefore takes `(max_size - min_size)` cycles of uninterrupted quiet, here
# 8 x 300s. Any test asserting a settle time must build its own pool with its own small
# `max_idle` and assert this constant separately; a wall-clock deadline against the shipped
# value is unsatisfiable for every value that is not itself pathological.
DEFAULT_MAX_IDLE_SECONDS = 300.0


def open_pool(
    dsn: str,
    min_size: int = DEFAULT_POOL_MIN,
    max_size: int = DEFAULT_POOL_MAX,
    open_timeout: float = DEFAULT_OPEN_TIMEOUT_SECONDS,
    max_idle: float = DEFAULT_MAX_IDLE_SECONDS,
) -> ConnectionPool:
    """Open and return a ready connection pool. Raises if the database is unreachable.

    Callers own the pool's lifetime — close it (or use it as a context manager) at process
    shutdown. `open_pool` blocks until at least `min_size` connections are established or
    `open_timeout` elapses, so a broken DSN or an unreachable database surfaces immediately
    at boot rather than as connections that quietly never come up.

    **Every pool setting that behaviour depends on is passed here explicitly**, never left to
    the library's default, because twice now an investigation has turned on what an unpassed
    default happened to be: `max_idle` (the shrink timing above) and `check`/`reset`, whose
    absence is the reason a leftover `cursor_factory` on a returned connection is currently a
    latent defect rather than a live one (`api/deps.py`). `check` and `reset` stay unset **on
    purpose** — a per-checkout `SELECT 1` would double the statement count of every request and
    `X-Query-Count` is a shipped, asserted value — and that is a decision recorded, not an
    omission. Anyone adding either must fix `api/deps.py`'s counter in the same commit.
    """
    if not dsn:
        raise ValueError("open_pool: dsn must be a non-empty libpq URL (VERTICALS_DATABASE_URL)")
    if min_size < 1:
        raise ValueError(f"open_pool: min_size must be >= 1, got {min_size}")
    if max_size < min_size:
        raise ValueError(f"open_pool: max_size ({max_size}) must be >= min_size ({min_size})")

    if max_idle <= 0:
        raise ValueError(f"open_pool: max_idle must be > 0, got {max_idle}")

    pool = ConnectionPool(
        conninfo=dsn, min_size=min_size, max_size=max_size, max_idle=max_idle, open=False
    )
    pool.open(wait=True, timeout=open_timeout)
    return pool
