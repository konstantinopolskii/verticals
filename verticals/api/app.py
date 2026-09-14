"""FastAPI app assembly — the one place `verticals/api/*` becomes a running process.

`python -m verticals.api.app` is how S-113 (WP-21's own test, run against this file's boot
behaviour — WP-15 builds it, does not claim the scenario) boots the bare server with the
container entrypoint bypassed: `config.load()` and this module's own loopback-bind check both
run at **module level**, before a single ASGI object is handed to uvicorn — a bad token or a
non-loopback `VERTICALS_BIND` means the process prints one line naming the variable and exits
non-zero, and no socket is ever opened, whether this module is imported by `uvicorn
verticals.api.app:app` (the http-suite harness's own invocation) or run directly.

`GET /healthz` is the one route not behind `verify_bearer_token` (§4: "not an API route and
carries no auth") — wired directly on `app`, never through `routes_board.router` /
`routes_goals.router`.

No `CORSMiddleware` anywhere in this file, on purpose (S-114). Starlette with no CORS middleware
added never emits an `Access-Control-Allow-*` header on any response — success, 4xx or 5xx alike
— and an unregistered `OPTIONS` method 405s on its own. The closed posture is what happens when
this file does *not* add code, not something it has to build.
"""

from __future__ import annotations

import logging
import sys
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from urllib.parse import quote

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from psycopg import OperationalError
from psycopg.errors import UndefinedTable
from psycopg_pool import PoolTimeout

from verticals import config
from verticals.api import errors
from verticals.api.deps import get_conn, read_global_count
from verticals.api.routes_board import router as board_router
from verticals.api.routes_comments import router as comments_router
from verticals.api.routes_docs import router as docs_router
from verticals.api.routes_events import router as events_router
from verticals.api.routes_goals import router as goals_router
from verticals.api.routes_tags import router as tags_router
from verticals.db.pool import open_pool
from verticals.db.runner import read_version

logger = logging.getLogger("verticals.api")

# §4's "request body" row — the outer bound, checked before any field-level cap and before the
# body is ever deserialised (AC-201). 200 nodes at the per-field caps already exceeds this, so
# it binds first on a runaway nested `create` — the 413 never lets pydantic see the bytes.
MAX_BODY_BYTES = 1024 * 1024

# `core.goals.delete`'s own docstring (S-16): "a lock this call cannot acquire before the
# caller's own lock_timeout — set on conn by the caller, never by this function." The same
# session setting bounds `pg_advisory_xact_lock` in `moves.allocate_position` (an advisory lock
# wait obeys `lock_timeout` the same way a row lock does), so one value guards both. Set once,
# at connect time, via libpq's `options` URI parameter — never a per-request `SET`, which would
# itself be a tracked statement and corrupt every `X-Query-Count` assertion in the http suite.
_LOCK_TIMEOUT_MS = 5_000
_STATEMENT_TIMEOUT_MS = 30_000


def _with_session_options(dsn: str) -> str:
    options = quote(
        f"-c lock_timeout={_LOCK_TIMEOUT_MS}ms -c statement_timeout={_STATEMENT_TIMEOUT_MS}ms"
    )
    joiner = "&" if "?" in dsn else "?"
    return f"{dsn}{joiner}options={options}"


def _parse_loopback_bind(bind: str) -> tuple[str, int]:
    """Security constraint, not boilerplate: every published port binds `127.0.0.1` only.
    `config.bind` is `.env` content, not a caller's input — but a deployment that fat-fingers
    `VERTICALS_BIND=0.0.0.0:8080` is exactly the mistake this check exists to catch before
    uvicorn ever opens a socket, not after (S-112's "no socket it was not configured to open,"
    one layer up from what that scenario tests directly)."""
    host, _, port = bind.rpartition(":")
    if host != "127.0.0.1" or not port.isdigit():
        raise config.ConfigError(
            f"VERTICALS_BIND must be '127.0.0.1:<port>', got {bind!r} — this transport refuses "
            "to publish a port on any interface but loopback"
        )
    return host, int(port)


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    cfg: config.Config = app.state.config
    app.state.pool = open_pool(
        _with_session_options(cfg.database_url), min_size=cfg.pool_min, max_size=cfg.pool_max
    )
    try:
        yield
    finally:
        app.state.pool.close()


# --- AC-201: the 1 MB outer bound, refused before a body byte is deserialised -------------------


class _BodyTooLarge(Exception):
    pass


class BodySizeLimitMiddleware:
    """Pure ASGI, not `BaseHTTPMiddleware`: a `Content-Length` over the cap is answered before
    `receive` is ever called — the "413, before parsing; the server never deserialises it" §4
    row requires exactly this, and reading the body first to measure it would already have done
    the deserialisation work the 413 exists to avoid paying for. A caller that lies about
    `Content-Length` (or sends chunked encoding, which carries none) is still caught: `receive`
    is wrapped to total the bytes as they actually arrive, cut at the same cap, so a body can
    never be fully buffered before this middleware notices it is too large."""

    def __init__(self, app: Callable) -> None:
        self.app = app

    async def __call__(self, scope: dict, receive: Callable, send: Callable) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        declared = next(
            (v for k, v in scope.get("headers", ()) if k == b"content-length"), None
        )
        if declared is not None and declared.isdigit() and int(declared) > MAX_BODY_BYTES:
            await _send_413(send)
            return

        seen = 0

        async def limited_receive() -> dict:
            nonlocal seen
            message = await receive()
            if message["type"] == "http.request":
                seen += len(message.get("body", b""))
                if seen > MAX_BODY_BYTES:
                    raise _BodyTooLarge()
            return message

        try:
            await self.app(scope, limited_receive, send)
        except _BodyTooLarge:
            await _send_413(send)


async def _send_413(send: Callable[[dict], Awaitable[None]]) -> None:
    await send(
        {
            "type": "http.response.start",
            "status": 413,
            "headers": [(b"content-type", b"application/json")],
        }
    )
    # No body echo (§4: "the 413 carries no body echo") — a fixed message, never the caller's
    # own bytes reflected back.
    await send({"type": "http.response.body", "body": b'{"error":"body_too_large"}'})


# --- app assembly ---------------------------------------------------------------------------


def create_app(cfg: config.Config) -> FastAPI:
    app = FastAPI(title="verticals", lifespan=_lifespan)
    app.state.config = cfg
    errors.register(app)
    app.add_middleware(BodySizeLimitMiddleware)
    app.include_router(board_router)
    app.include_router(comments_router)
    app.include_router(docs_router)
    app.include_router(events_router)
    app.include_router(goals_router)
    app.include_router(tags_router)

    @app.get("/healthz")
    def healthz(request: Request) -> JSONResponse:
        """S-31, S-32, S-45. No `Depends(verify_bearer_token)` anywhere on this route — that
        dependency lives on `board_router`/`goals_router` alone, so a probe never touches the
        bearer check, and `queries` (`read_global_count()`) reports this call's own statements
        (S-31's own "used by S-32" note). `read_version` (`db/runner.py`) is `db/`'s own
        version read, not a raw statement here — ARCHITECTURE.md §2's seam rule: `api/`/`mcp/`
        hold no SQL verbs of their own. It costs exactly one statement — `read_version` does
        not pre-check `information_schema` the way `current_version` does (that guarded,
        two-statement form is the migration CLI's own need, not this route's) — so the delta
        this route contributes to S-32's count is 1, matching that scenario's own text.

        `read_version` raises `UndefinedTable` instead of answering 0 for a database with no
        `schema_version` — deliberately: version 0 and "never migrated" are not the same fact,
        and this is the one caller that must not conflate them. A probe that answered `status:
        ok, version: 0` for an undeployed database would be the exact failure mode a health
        check exists to catch — a broken deploy going green. 503 with `db: "not_migrated"`
        keeps that distinguishable in the body from a reachable-but-down database
        (`db: "down"`, the `OperationalError`/`PoolTimeout` branch below) — same status code,
        because either way the caller's answer is "not ready," but the reason a human reads off
        the body differs, and nothing here has to guess which one happened."""
        try:
            with get_conn(request) as conn:
                version = read_version(conn)
            return JSONResponse(
                {"status": "ok", "db": "ok", "version": version, "queries": read_global_count()}
            )
        except (OperationalError, PoolTimeout) as exc:
            logger.warning("healthz: database unavailable: %s", exc)
            return JSONResponse(
                status_code=503,
                content={"status": "error", "db": "down", "queries": read_global_count()},
            )
        except UndefinedTable as exc:
            logger.warning("healthz: schema_version missing (database not migrated): %s", exc)
            return JSONResponse(
                status_code=503,
                content={
                    "status": "error",
                    "db": "not_migrated",
                    "queries": read_global_count(),
                },
            )

    return app


def _configure_logging(level: str) -> None:
    """Give `verticals.*` a real handler and a real format, once, at the entrypoint.

    Without this, nothing in this package configures logging at all: `uvicorn.run(log_level=…)`
    sets up uvicorn's own three loggers and no others, so every `logger.warning`/`logger.error`
    in `api/errors.py` was reaching stderr through `logging.lastResort` — a bare message with no
    level, no timestamp and no logger name. Verified by reading a real server's log file, not
    inferred: the line arrived as `refused CycleRefused: status=409 …` and nothing else.

    That is not a "structured line" in any sense a person debugging a box at 2am can use, and
    `E2E.md` S-39 asks for one at `level=warning` explicitly — a level you cannot assert on a
    stream that never prints levels. `lastResort` is also a fallback, not a contract: it silently
    stops applying the moment anything in the process calls `logging.basicConfig()`, which makes
    "we get logs" depend on which libraries happen to be imported. For a server meant to run
    unattended for ten years, an unconfigured logger is a defect on its own.

    Called from `_boot_or_exit`, deliberately not from `create_app`: importing `create_app` in a
    test must not reconfigure the test process's logging out from under pytest. The entrypoint is
    the only caller that owns the process.
    """
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(
        logging.Formatter(
            fmt="%(asctime)s level=%(levelname)s logger=%(name)s %(message)s",
            datefmt="%Y-%m-%dT%H:%M:%S%z",
        )
    )
    root = logging.getLogger("verticals")
    root.handlers[:] = [handler]
    root.setLevel(level.upper())
    root.propagate = False  # the record is emitted here or nowhere; never twice


def _boot_or_exit() -> tuple[config.Config, str, int]:
    """Everything that can refuse boot, in one place, run before `app` exists at all. Both
    `config.load()` (unset/empty/placeholder `VERTICALS_TOKEN`, AC-081) and
    `_parse_loopback_bind` (a non-loopback `VERTICALS_BIND`) raise the same `config.ConfigError`,
    caught here the same way: one line to stderr naming the variable, exit 1, no traceback, no
    socket — S-113's own steps 1-3, run with the entrypoint bypassed."""
    try:
        cfg = config.load()
        host, port = _parse_loopback_bind(cfg.bind)
    except config.ConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        sys.exit(1)
    # After the refusals, never before: a boot refusal prints one plain line naming the variable
    # and exits (S-113 steps 1-3), and routing that through a configured logger would decorate it
    # with a timestamp and a level the scenario does not ask for.
    _configure_logging(cfg.log_level)
    return cfg, host, port


_cfg, _host, _port = _boot_or_exit()
app = create_app(_cfg)

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host=_host, port=_port, log_level=_cfg.log_level)
