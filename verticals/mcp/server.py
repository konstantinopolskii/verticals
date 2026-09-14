"""The MCP transport — `python -m verticals.mcp.server [--transport stdio|http]`. Stdio is the
default (docs/E2E.md's own suite intro: "Client is the official `mcp` Python SDK connected to
`python -m verticals.mcp.server` over stdio"); `--transport http` is S-60's streamable-HTTP twin,
proving the same nine tools behave identically over a second wire.

Mirrors `verticals/api/app.py`'s own shape on purpose (house convention: transports duplicate
small boot/lifecycle/session code rather than import each other) — boot-time refusal before any
socket opens, one connection pool per process (`verticals/db/pool.py`'s own IR-01 docstring:
"there is one pool per process, full stop"), the same `lock_timeout`/`statement_timeout` session
options, the same structured-stderr logging setup.

**The stream rule** (docs/E2E.md, this suite's own intro, "corrected"): over stdio the protocol
owns stdout — nothing but framed JSON-RPC may ever appear there — while stderr is where logs go
and is expected to be non-empty. `mcp.server.stdio.stdio_server()` itself defends stdout at the
OS file-descriptor level (verified by reading its source: fd 1 is swapped to point at fd 2's
destination for the life of the session, restored after), so the one discipline this file must
keep on its own side is never calling `print(...)` or writing to `sys.stdout` directly — logging
goes through the `logging` module to `sys.stderr` exclusively, same as `api/app.py`.

**Auth, not the SDK's OAuth stack.** `Server.streamable_http_app` accepts a `token_verifier`, but
verified live against the installed SDK: passing one without also passing `auth=AuthSettings(...)`
wraps the route in `RequireAuthMiddleware` without ever adding the `AuthenticationMiddleware`
that populates what it reads — every request would 401 regardless of the token presented. That
stack is also built for a resource server validating third-party-issued tokens, not one shared
secret from `.env`. `_BearerAuthMiddleware` below is a small, self-contained ASGI layer instead,
mirroring `api/deps.py`'s `verify_bearer_token` byte for byte (`hmac.compare_digest`, never `==`;
the token is never echoed back).
"""

from __future__ import annotations

import argparse
import functools
import hmac
import logging
import sys
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from urllib.parse import quote

import anyio
from psycopg_pool import ConnectionPool

import mcp.server.stdio
from mcp import types
from mcp.server.lowlevel import Server
from mcp.server.lowlevel.server import ServerRequestContext

from verticals import config
from verticals.db.pool import open_pool
from verticals.mcp import tools

logger = logging.getLogger("verticals.mcp")

# Same values, same reasoning as `api/app.py`'s own constants — one advisory-lock/statement
# budget per box, independently duplicated per transport rather than imported (house convention;
# see that file for the full argument). `core.goals.delete`'s own docstring: a lock this call
# cannot acquire before the caller's own `lock_timeout` surfaces as `LockNotAvailable`, never a
# raw driver error.
_LOCK_TIMEOUT_MS = 5_000
_STATEMENT_TIMEOUT_MS = 30_000


def _with_session_options(dsn: str) -> str:
    options = quote(f"-c lock_timeout={_LOCK_TIMEOUT_MS}ms -c statement_timeout={_STATEMENT_TIMEOUT_MS}ms")
    joiner = "&" if "?" in dsn else "?"
    return f"{dsn}{joiner}options={options}"


def _parse_loopback_bind(bind: str) -> tuple[str, int]:
    """`VERTICALS_MCP_BIND`'s own loopback check — `api/app.py`'s `_parse_loopback_bind`,
    independently duplicated for the same reason every other session-option/logging helper in
    this file is: a deployment that fat-fingers `VERTICALS_MCP_BIND=0.0.0.0:8081` must never open
    that socket, on either transport."""
    host, _, port = bind.rpartition(":")
    if host != "127.0.0.1" or not port.isdigit():
        raise config.ConfigError(
            f"VERTICALS_MCP_BIND must be '127.0.0.1:<port>', got {bind!r} — this transport "
            "refuses to publish a port on any interface but loopback"
        )
    return host, int(port)


def _configure_logging(level: str) -> None:
    """Byte-for-byte `api/app.py`'s own `_configure_logging` — see that file for why an
    unconfigured `logging` module is a defect on a server meant to run unattended for years, and
    why this must be called from the entrypoint, never at import time (importing this module in
    a test must not reconfigure the test process's own logging)."""
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(
        logging.Formatter(
            fmt="%(asctime)s level=%(levelname)s logger=%(name)s %(message)s", datefmt="%Y-%m-%dT%H:%M:%S%z"
        )
    )
    root = logging.getLogger("verticals")
    root.handlers[:] = [handler]
    root.setLevel(level.upper())
    root.propagate = False


@asynccontextmanager
async def _lifespan(_server: Server, *, cfg: config.Config) -> AsyncIterator[ConnectionPool]:
    """`Server.run()` (stdio) and `StreamableHTTPSessionManager.run()` (http) both enter this
    exactly once per process, verified by reading each's source — `run()`'s own docstring says
    outright "enters the server lifespan", and the session manager's does
    `self.app.lifespan(self.app)` around its whole task group, not per request. One pool per
    process either way (IR-01), handed to every tool call as `ctx.lifespan_context`."""
    pool = open_pool(_with_session_options(cfg.database_url), min_size=cfg.pool_min, max_size=cfg.pool_max)
    try:
        yield pool
    finally:
        pool.close()


def create_server(cfg: config.Config) -> Server:
    """Build the one `Server` instance both transports share — constructor-kwarg handler
    registration, not decorators (the installed `mcp==2.0.0` shape, confirmed by introspecting
    `Server.__init__` directly rather than assuming a remembered API). `owner` is closed over
    from `cfg`, never taken from a call's own arguments: this process answers as exactly one
    owner, the same rule `api/routes_board.py` states for the HTTP side.
    """
    owner = cfg.owner

    async def _on_list_tools(
        _ctx: ServerRequestContext, _params: types.PaginatedRequestParams | None
    ) -> types.ListToolsResult:
        return types.ListToolsResult(tools=list(tools.TOOLS))

    async def _on_call_tool(
        ctx: ServerRequestContext, params: types.CallToolRequestParams
    ) -> types.CallToolResult:
        pool: ConnectionPool = ctx.lifespan_context

        def _run() -> types.CallToolResult:
            # IR-02: one connection, one transaction per invocation — `core/`'s own mutators
            # each wrap their body in `with conn.transaction()`; a plain read commits nothing
            # to roll back. `pool.connection()` is itself psycopg_pool's transaction-scoped
            # checkout, matching `api/deps.py::get_conn`'s identical reasoning on the HTTP side.
            with pool.connection() as conn:
                return tools.call_tool(conn, owner=owner, name=params.name, arguments=params.arguments)

        # core/ is synchronous psycopg3 (`db/pool.py`'s own docstring); never run it inline on
        # the event loop that is also carrying every other in-flight request.
        return await anyio.to_thread.run_sync(_run)

    return Server(
        "verticals",
        version="1.0.0",
        lifespan=functools.partial(_lifespan, cfg=cfg),
        on_list_tools=_on_list_tools,
        on_call_tool=_on_call_tool,
    )


# --- bearer auth (streamable-http only; stdio has no network surface to guard) ------------------


class _BearerAuthMiddleware:
    """Pure ASGI, not `Starlette`'s `BaseHTTPMiddleware` — matching `api/app.py`'s own
    `BodySizeLimitMiddleware` precedent for the same reason: a raw `scope`/`receive`/`send`
    callable is the smallest thing that can inspect one header and either forward the call or
    answer 401 directly, with no framework layer to reason about in between. The `lifespan`
    scope type is passed straight through untouched — this is what lets Starlette's own
    `session_manager.run()` lifespan (this module's `_lifespan`, opening the one pool) fire
    normally underneath."""

    def __init__(self, app: Callable, token: str) -> None:
        self.app = app
        self.token = token

    async def __call__(self, scope: dict, receive: Callable, send: Callable) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = dict(scope.get("headers") or ())
        presented = headers.get(b"authorization", b"").decode("latin-1")
        valid = presented.startswith("Bearer ") and hmac.compare_digest(
            presented.removeprefix("Bearer "), self.token
        )
        if not valid:
            await send(
                {
                    "type": "http.response.start",
                    "status": 401,
                    "headers": [(b"content-type", b"application/json"), (b"www-authenticate", b"Bearer")],
                }
            )
            # No body echo, same rule as api/app.py's 413 and S-113's "never echoed back": a
            # fixed message, never the caller's own header reflected.
            await send({"type": "http.response.body", "body": b'{"error":"unauthorized"}'})
            return
        await self.app(scope, receive, send)


def create_http_app(cfg: config.Config, *, host: str) -> Callable:
    server = create_server(cfg)
    # host in {"127.0.0.1", "localhost", "::1"} auto-enables DNS-rebinding / Origin-header
    # protection inside streamable_http_app itself (verified by reading its source) — always
    # true here, since _parse_loopback_bind already refused anything else at boot.
    inner = server.streamable_http_app(host=host)
    return _BearerAuthMiddleware(inner, cfg.token)


# --- entrypoint ----------------------------------------------------------------------------------


def _boot_or_exit(transport: str) -> config.Config:
    """Everything that can refuse boot, before a socket or a stdio session ever opens —
    `api/app.py::_boot_or_exit`'s own shape. Stdio needs no bind at all; http additionally
    refuses a non-loopback `VERTICALS_MCP_BIND` here, not after uvicorn is already listening."""
    try:
        cfg = config.load()
        if transport == "http":
            _parse_loopback_bind(cfg.mcp_bind)
    except config.ConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        sys.exit(1)
    _configure_logging(cfg.log_level)
    return cfg


async def _run_stdio(cfg: config.Config) -> None:
    server = create_server(cfg)
    async with mcp.server.stdio.stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


def _run_http(cfg: config.Config) -> None:
    import uvicorn

    host, port = _parse_loopback_bind(cfg.mcp_bind)
    app = create_http_app(cfg, host=host)
    uvicorn.run(app, host=host, port=port, log_level=cfg.log_level)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m verticals.mcp.server")
    parser.add_argument("--transport", choices=("stdio", "http"), default="stdio")
    args = parser.parse_args(argv)

    cfg = _boot_or_exit(args.transport)
    # AC-139 / the mcp-suite stream rule: stderr is *expected* non-empty, at least one
    # structured line for the run. A tool call already logs one (tools.py::call_tool), but a
    # session that never calls a tool — S-118's own `tools/list`-then-nothing shape, or a probe
    # that only initializes — must not read as a server that logs nothing. One line, always, the
    # moment boot succeeds.
    logger.info("verticals mcp server starting: transport=%s owner=%s", args.transport, cfg.owner)
    if args.transport == "stdio":
        anyio.run(_run_stdio, cfg)
    else:
        _run_http(cfg)


if __name__ == "__main__":
    main()
