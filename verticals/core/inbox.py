"""The Inbox: everything with no date (KK, 6 Oct 2026: "inbox = all notes and tasks which were created and have no
scheduled data").

The board's Maybe column holds only parentless undated goals (``board.MAYBE_PREDICATE``); an undated goal under a parent
is an "idea" and stays off the board. The Inbox shows both, because a thought the agent warms up goes under the goal it
belongs to and stays undated. Each row carries what the Inbox draws: the goal it sits under, its value's colour, when it
was written, and the column it left (``parked_from_vertical``, which the schema sets exactly when ``vertical`` is null,
008_park_foil.sql), so the Inbox can put it on that column's shelf.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import psycopg


@dataclass(frozen=True)
class InboxItem:
    id: str
    title: str
    parent_id: str | None
    parent_title: str | None
    value_color: str | None
    parked_from_vertical: str | None
    created_at: datetime
    body_chars: int
    origin: str
    private: bool


def items(conn: psycopg.Connection, *, owner: str) -> tuple[InboxItem, ...]:
    """Every open goal with no date, newest first; one statement. The value colour is the root's, as on the board
    (``board.py``'s ``value_color``): a root on the life scale gives its colour, anything else gives none."""
    rows = conn.execute(
        """
        SELECT g.id, g.title, g.parent_id, p.title,
               CASE WHEN r.vertical = 'life' THEN r.color END,
               g.parked_from_vertical, g.created_at, length(g.body), g.origin, g.private
          FROM goals g
          LEFT JOIN goals p ON p.owner = g.owner AND p.id = g.parent_id
          LEFT JOIN goals r ON r.owner = g.owner AND r.id = split_part(g.path, '/', 2) AND r.id <> g.id
         WHERE g.owner = %(owner)s
           AND g.vertical IS NULL
           AND g.done_at IS NULL
         ORDER BY g.created_at DESC, g.id
        """,
        {"owner": owner},
    ).fetchall()
    return tuple(InboxItem(*row) for row in rows)
