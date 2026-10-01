"""One vertical's periods in a row, for moving a goal (docs/design-handoff S5.P1.030).

While a goal is held over a column's dots the board turns into that vertical's periods, each drawn as a regular
column. This read hands them over in the board payload's shape: one column per period, with the cards, their
children, progress and ancestors, and the carried plans of the current period in their group, as `board()` builds
them. Each period is `board()`'s own statement, so a span can never disagree with the board.

IR-02: takes an open connection, never commits.
"""

from __future__ import annotations

from datetime import date as _date
from datetime import timedelta as _timedelta

import psycopg

from verticals.core import board as core_board
from verticals.core import vertical as core_vertical
from verticals.core.errors import ValidationError
from verticals.models import Board

MAX_SPANS = 16


def period_starts(scale: str, start: _date, count: int) -> list[_date]:
    """The first day of `count` consecutive periods of `scale`, from the one holding `start`."""
    bounds = core_vertical.descriptor(scale).bounds_fn
    first = bounds(start)
    if first is None:
        raise ValidationError(f"{scale} has one period and no spans", field="vertical")
    out = [first[0]]
    while len(out) < count:
        out.append(bounds(out[-1])[1] + _timedelta(days=1))
    return out


def spans(
    conn: psycopg.Connection, *, owner: str, scale: str, start: _date, count: int,
    value: str | None = None, today: _date | None = None,
) -> Board:
    if scale not in core_vertical.SCALE_KEYS:
        raise ValidationError(f"vertical must be one of {sorted(core_vertical.SCALE_KEYS)}", field="vertical")
    if not isinstance(count, int) or isinstance(count, bool) or not 1 <= count <= MAX_SPANS:
        raise ValidationError(f"count must be 1..{MAX_SPANS}", field="count")
    starts = period_starts(scale, start, count)
    boards = [core_board.board(conn, owner=owner, date=d, value=value, today=today) for d in starts]
    columns = tuple(next(c for c in b.columns if c.vertical == scale) for b in boards)
    shown = {g.id for c in columns for g in c.goals}

    def merged(field: str) -> dict:
        out: dict = {}
        for b in boards:
            out.update(getattr(b, field))
        return out

    ghosts = {gid: until for gid, until in merged("ghosts").items() if gid in shown}
    return Board(
        owner=boards[0].owner, anchor_date=starts[0], columns=columns, progress=merged("progress"),
        ancestors=merged("ancestors"), children=merged("children"), child_counts=merged("child_counts"),
        evidence=merged("evidence"), ghosts=ghosts, short_labels=merged("short_labels"), values=boards[0].values,
    )
