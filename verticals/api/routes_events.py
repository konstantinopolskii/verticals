"""`GET /api/events` — the change feed as Server-Sent Events (D237, KK 2026-08-15).

One event type, no data: every `goals`/`due_acknowledgements` write raises
`pg_notify('goals_changed', owner)` (migration 012) and this endpoint forwards a bare
`data: changed` frame to the board, which refetches through the ordinary authenticated routes.
The stream is a doorbell, deliberately content-free — see the migration's own header.

Mechanics, chosen for boredom:

* One DEDICATED async connection per stream, opened outside the request pool. LISTEN pins a
  connection for the lifetime of the subscription; parking that in the pool would starve the
  three-connection default for as long as a tab stays open. A single-owner deployment holds a
  handful of tabs at most, so one backend process per tab is the honest cost, paid visibly.
* Bearer auth exactly like every other route (`verify_bearer_token`), which is also why the
  client reads this with `fetch()` + a stream reader, never `EventSource` — EventSource cannot
  send an Authorization header, and this house never puts credentials in a URL.
* A `: ping` comment frame every 15s of silence keeps intermediaries from reaping the idle
  connection; SSE comments are invisible to the client parser by spec.
* Owner filtering happens HERE (payload == configured owner), not in the trigger: the trigger
  serves every listener, this deployment serves exactly one owner (routes_board.py's own rule).
* No `X-Query-Count`, no counting cursor: this is not a board read, and the counter's whole
  contract (one statement per request) is meaningless on an endpoint whose lifetime is "until
  the tab closes".
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import psycopg
from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse

from verticals.api.deps import verify_bearer_token

router = APIRouter(dependencies=[Depends(verify_bearer_token)])

PING_INTERVAL = 15.0


async def _stream(dsn: str, owner: str) -> AsyncIterator[bytes]:
    conn = await psycopg.AsyncConnection.connect(dsn, autocommit=True)
    try:
        await conn.execute("LISTEN goals_changed")
        # `retry:` tells any spec-following reader the reconnect delay; our own client keeps its
        # backoff regardless. The first frame also flushes headers so the client sees the stream
        # open immediately instead of on the first write minutes later.
        yield b"retry: 2000\n\n"
        while True:
            changed = False
            async for notice in conn.notifies(timeout=PING_INTERVAL, stop_after=1):
                if notice.payload == owner:
                    changed = True
            # A burst of writes lands as one wakeup here (NOTIFY dedup within a transaction) or
            # a few frames in quick succession across transactions — the client debounces.
            yield b"data: changed\n\n" if changed else b": ping\n\n"
    finally:
        await conn.close()


@router.get("/api/events")
async def events(request: Request) -> StreamingResponse:
    cfg = request.app.state.config
    return StreamingResponse(
        _stream(cfg.database_url, cfg.owner),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-store",
            # nginx honours this per-response switch (docker/nginx.conf.template keeps its
            # buffering defaults everywhere else) — a buffered SSE stream delivers nothing.
            "X-Accel-Buffering": "no",
        },
    )
