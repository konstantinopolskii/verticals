"""`GET /api/board` — the whole board, one call (S-33, IR-07) — and `POST /api/replan`, the
roll's one write (docs/design-handoff S4.P1): `core/board.py` is a single frozen function with
no write half, so the carry-over task has its own writer, `core/replan.py`, fronted here beside
the board it reads like.

`owner` is never taken from the request — read from `request.app.state.config.owner` on every
call, matching `verticals/config.py`'s own docstring ("this module only carries it for whichever
transport wants it") and `pyproject.toml`'s "single owner, one Postgres box": this deployment
serves exactly one owner, and the only reason F2 carries a second (`t2`) is to prove isolation
holds, not because a real boot ever chooses between owners per request.
"""

from __future__ import annotations

from datetime import date as _date

from fastapi import APIRouter, Depends, Request, Response

from verticals.api.deps import get_conn, verify_bearer_token
from verticals.api.schemas import board_to_json
from verticals.core import board as core_board
from verticals.core import inbox as core_inbox
from verticals.core import replan as core_replan
from verticals.core import spans as core_spans

router = APIRouter(dependencies=[Depends(verify_bearer_token)])


@router.get("/api/board")
def get_board(
    request: Request, response: Response, date: _date, value: str | None = None
) -> dict:
    """`date` is required, no invented default: `core/board.py`'s own `board()` takes no
    default either, and guessing "today" here would be this transport deciding a product
    behaviour `core/` does not state (the hard constraint this whole work package is built
    under). A caller that means "today" sends today's date, same as every scenario that
    exercises this route already does (S-20, S-33: `?date=2026-08-08`).

    `value` (D233) is the value filter: a parentless life-vertical goal's id, narrowing every
    dated column except `life` (and `maybe`) to that value's subtree. Optional, passed through
    verbatim — the semantics, exemptions and the unknown-id NotFound all live in
    `core/board.py`, not here."""
    owner = request.app.state.config.owner
    with get_conn(request) as conn:
        result = core_board.board(conn, owner=owner, date=date, value=value)
        response.headers["X-Query-Count"] = str(conn.query_count)
    return board_to_json(result)


@router.get("/api/spans")
def get_spans(
    request: Request, response: Response, vertical: str, date: _date, count: int = 7, value: str | None = None,
) -> dict:
    """One vertical's periods in a row, from the one holding `date`, in the board's own payload
    (docs/design-handoff S5.P1.030): the board a moved goal opens over a column's dots."""
    owner = request.app.state.config.owner
    with get_conn(request) as conn:
        result = core_spans.spans(conn, owner=owner, scale=vertical, start=date, count=count, value=value)
        response.headers["X-Query-Count"] = str(conn.query_count)
    return board_to_json(result)


@router.post("/api/replan")
def post_replan(request: Request, date: _date) -> dict:
    """The day's carry-over into the "Replan carried-over plans" task (S4.P1.017): the app asks
    on start and when its day turns, and the server does it once a day however often it is
    asked. `date` is the owner's today, as the board's own `date`; a day more than one away from
    the server's own is not run, so a wrong clock can neither mark days that have not come nor
    gather plans against a day long gone."""
    if abs((date - _date.today()).days) > 1:
        return {"task_id": None}
    owner = request.app.state.config.owner
    with get_conn(request) as conn:
        task_id = core_replan.run(conn, owner=owner, today=date)
    return {"task_id": task_id}


@router.get("/api/inbox")
def get_inbox(request: Request, response: Response) -> dict:
    """The Inbox: every open goal with no date, the ones under a goal included (`core/inbox.py`), newest first, with
    the goal each sits under and its value's colour, so the Inbox draws Today's cards and the shelves from one call."""
    owner = request.app.state.config.owner
    with get_conn(request) as conn:
        rows = core_inbox.items(conn, owner=owner)
        response.headers["X-Query-Count"] = str(conn.query_count)
    return {
        "goals": [
            {
                "id": row.id,
                "title": row.title,
                "parent": {"id": row.parent_id, "title": row.parent_title} if row.parent_id else None,
                "value_color": row.value_color,
                "parked_from_vertical": row.parked_from_vertical,
                "created_at": row.created_at,
                "body_chars": row.body_chars,
                "origin": row.origin,
                "private": row.private,
            }
            for row in rows
        ]
    }
