"""Detail-family read: direct children plus a Life value's parked descendant ideas.

This is the second and final statement in ``core.goals.goal``. Combining both populations keeps
the established detail-read budget at two statements while R9 expands ideas beyond direct kids.
"""

from __future__ import annotations

from datetime import date as _date
from dataclasses import dataclass

import psycopg

from verticals.core import vertical
from verticals.models import Ancestor, Goal

COLUMNS = (
    "id, owner, parent_id, path, depth, vertical, anchor_date, period_key, "
    "title, body, color, tags, done_at, position, origin, created_at, updated_at, "
    "repeat_rule, repeat_series_id, repeat_index, repeat_start_date, "
    "parked_from_vertical, foil, carryover_ignored_until, size_expected, size_actual, private"
)


@dataclass(frozen=True)
class GoalDetail:
    goal: Goal
    ancestors: tuple[Ancestor, ...]
    children: tuple[Goal, ...]
    ideas: tuple[Goal, ...]


def _to_goal(row: tuple) -> Goal:
    values = list(row)
    values[11] = tuple(values[11])
    values[24] = tuple(values[24]) if values[24] is not None else None
    values[25] = tuple(values[25]) if values[25] is not None else None
    return Goal(*values)


def detail_family(
    conn: psycopg.Connection, *, owner: str, target: Goal
) -> tuple[tuple[Goal, ...], tuple[Goal, ...]]:
    """Return ``(direct committed children, parked descendant ideas)``.

    Ideas exist only for a root goal on an unbounded scale. Direct parked children satisfy both
    source predicates once because the statement uses one OR, not a UNION.
    """
    is_value = (
        target.parent_id is None
        and target.vertical is not None
        and vertical.descriptor(target.vertical).bounds_fn(target.anchor_date or _date.today()) is None
    )
    rows = conn.execute(
        f"""
        SELECT {COLUMNS},
               (%(include_ideas)s AND vertical IS NULL
                 AND path OPERATOR(pg_catalog.~>=~) %(path)s
                 AND path OPERATOR(pg_catalog.~<~) %(path_end)s
                 AND id <> %(id)s) AS is_idea
          FROM goals
         WHERE owner = %(owner)s
           AND (parent_id = %(id)s OR
                (%(include_ideas)s AND vertical IS NULL
                  AND path OPERATOR(pg_catalog.~>=~) %(path)s
                  AND path OPERATOR(pg_catalog.~<~) %(path_end)s
                  AND id <> %(id)s))
         ORDER BY position, id
        """,
        {
            "owner": owner,
            "id": target.id,
            "include_ideas": is_value,
            "path": target.path,
            "path_end": target.path[:-1] + "0",
        },
    ).fetchall()
    children = tuple(
        child
        for row in rows
        if not row[-1]
        for child in (_to_goal(row[:-1]),)
        if not is_value or child.vertical == target.vertical
    )
    ideas = tuple(
        sorted(
            (_to_goal(row[:-1]) for row in rows if row[-1]),
            key=lambda idea: (-vertical.rank(idea.parked_from_vertical), idea.title),
        )
    )
    return children, ideas
