"""IR-03's mapping table, and nowhere else. `core/errors.py`'s eight types go through the
`_STATUS`/`_CODE` table below to become an HTTP status and a `{"error": ..., "detail": ...}`
body; nothing here inspects a message string or reimplements a rule `core/` already enforces
(the hard constraint on this whole work package — a transport maps, it does not decide).

Two things this module does *not* map from `core/errors.py`, both deliberate:

  * A plain `RuntimeError` — `core/idem.py` raises exactly two, both documented there as its
    own invariant failures (a reservation row vanishing between insert and lookup; `complete()`
    called without a prior `reserve()` on the same connection), not a caller mistake for a
    transport to name. These, and anything else unanticipated, fall through to the catch-all
    handler and become a bare 500 — logged in full server-side, never echoed to the caller
    (`docs/IMPLEMENTATION.md` §4.1's adversarial line for this WP: "find any input producing a
    500 or a traceback in a body" — the traceback goes to the log, not the response).
  * `psycopg.OperationalError` / `psycopg_pool.PoolTimeout` — raised by the driver itself when
    Postgres is gone, not by any `core/` call. `core/errors.DatabaseUnavailable` exists for a
    `core/` module that wraps this and re-raises it as its own taxonomy member, but nothing
    shipped does that yet (checked: `board.py`, `search.py`, `idem.py` call `conn.execute`
    directly, no `try/except` around it). Until one does, catching the driver's own exception
    here is what actually makes S-45 true — the pool losing its database is exactly the
    "unavailable" case this file's whole job is to name correctly, whichever layer raises it.
"""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from psycopg import OperationalError
from psycopg_pool import PoolTimeout

from verticals.core.errors import (
    CycleRefused,
    DatabaseUnavailable,
    HasChildren,
    VerticalError,
    IdempotencyConflict,
    LockNotAvailable,
    NotFound,
    RevisionMismatch,
    ValidationError,
)

logger = logging.getLogger("verticals.api")

# The one place a `core/errors.py` type becomes an HTTP status and an `"error"` code string.
# `ValidationError` is deliberately absent: its 422 uses pydantic's own `detail: [{loc, msg,
# type}]` list shape (S-35, S-128) rather than this table's `{"error": ..., "detail": {...}}`
# dict shape, so it is handled separately, in `validation_error_response` below, not through
# `_STATUS`/`_CODE`. The two shapes never mix — a 422 body is always a list, a 4xx/5xx from
# this table is always a dict.
_STATUS: dict[type[VerticalError], int] = {
    NotFound: 404,
    CycleRefused: 409,
    HasChildren: 409,
    IdempotencyConflict: 409,
    RevisionMismatch: 409,  # optimistic-lock refusal (WP-33): re-read, then retry — same family.
    LockNotAvailable: 503,  # transient — same retry-is-the-fix family as DatabaseUnavailable.
    DatabaseUnavailable: 503,
}

_CODE: dict[type[VerticalError], str] = {
    NotFound: "not_found",
    CycleRefused: "cycle",
    HasChildren: "has_children",
    IdempotencyConflict: "idempotency_conflict",
    RevisionMismatch: "revision_mismatch",
    LockNotAvailable: "lock_not_available",
    DatabaseUnavailable: "database_unavailable",
}


def validation_error_response(
    field: object, message: str, *, error_detail: dict[str, object] | None = None
) -> JSONResponse:
    """The one place a hand-built 422 is assembled, so every 422 this transport ever sends —
    whether pydantic raised it or `core/`'s own `ValidationError` did — carries the same
    `detail: [{"loc": [...], "msg": ..., "type": "value_error"}]` shape (S-35, S-128)."""
    loc = ["body", field] if field else ["body"]
    item: dict[str, object] = {"loc": loc, "msg": message, "type": "value_error"}
    # Keep the ordinary pydantic-compatible loc/msg/type shape, while preserving core's
    # machine-readable refusal fields. The schedule UI needs ids/verticals to explain the
    # parent-placement law without matching an English sentence.
    if error_detail:
        item.update(error_detail)
    return JSONResponse(
        status_code=422,
        content={"detail": [item]},
    )


def _vertical_error_handler(request: Request, exc: VerticalError) -> JSONResponse:
    if isinstance(exc, ValidationError):
        field = exc.detail.get("field") if isinstance(exc.detail, dict) else None
        return validation_error_response(field, exc.message, error_detail=exc.detail)
    if isinstance(exc, NotFound):
        # S-41: an unknown id and another owner's id must produce byte-identical 404 bodies —
        # no existence oracle. `core.errors.NotFound`'s own docstring says the two cases are
        # deliberately indistinguishable, but its raise sites (`goals.py`, `moves.py`) still
        # embed the queried `id`/`owner` in `.detail` for server-side legibility (a log line,
        # never seen here) — echoing that into the response body would make two 404s for two
        # different ids trivially distinguishable by content, defeating the property the
        # scenario checks for. core has no way to know a caller could ever diff two of its
        # error bodies byte-for-byte; that is an HTTP-specific concern this table is the one
        # place to enforce, not a rule to push back onto every raise site.
        return JSONResponse(status_code=404, content={"error": "not_found"})
    status = _STATUS.get(type(exc))
    code = _CODE.get(type(exc))
    if status is None or code is None:
        # A `core/errors.py` member with no row above — the closed set grew and this table did
        # not. Not a caller's fault; refuse to guess a status for it.
        logger.error("unmapped VerticalError subtype %s: %s", type(exc).__name__, exc.message)
        return JSONResponse(status_code=500, content={"error": "internal_error"})
    # One structured line per refused invariant, `level=warning` — S-39 requires it explicitly
    # ("the server log line is one structured line, `level=warning`, not an exception") and this
    # branch logged nothing at all until now (queue row 43). Warning, not info, and not silence:
    # every member of the table above is "an invariant refused this", and the interesting one is
    # `CycleRefused` — it means a caller, most likely an agent, tried to make the tree
    # inconsistent. On a box expected to run unattended for ten years that is exactly the event
    # you want a record of, and the set is small enough that logging all of it is proportionate
    # rather than chatty (a 404 never reaches here — `NotFound` returned above).
    #
    # `exc.message`, never the exception object: `NotFound`'s detail deliberately carries the
    # queried id and owner for server-side legibility, and this line is that server side. It is
    # also the reason nothing here goes near the response body — the log may say more than the
    # wire does, never the reverse.
    logger.warning(
        "refused %s: status=%d code=%s path=%s detail=%s",
        type(exc).__name__,
        status,
        code,
        request.url.path,
        exc.detail,
    )
    return JSONResponse(status_code=status, content={"error": code, "detail": exc.detail})


def _database_unavailable_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.warning("database unavailable: %s", exc)
    return JSONResponse(status_code=503, content={"error": "database_unavailable"})


def _unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    # The floor under every other handler: `core/idem.py`'s two `RuntimeError`s land here, and
    # so does anything nobody anticipated. Full traceback to the log, a flat body to the wire —
    # `exc_info=True` is what makes this an actual debuggable line and not just "something
    # broke", without that detail ever crossing the process boundary.
    logger.error("unhandled exception on %s %s", request.method, request.url.path, exc_info=exc)
    return JSONResponse(status_code=500, content={"error": "internal_error"})


def register(app: FastAPI) -> None:
    """Wire every handler above onto `app`. Called once, from `api/app.py`, at import time."""
    app.add_exception_handler(VerticalError, _vertical_error_handler)
    app.add_exception_handler(OperationalError, _database_unavailable_handler)
    app.add_exception_handler(PoolTimeout, _database_unavailable_handler)
    app.add_exception_handler(Exception, _unhandled_exception_handler)
