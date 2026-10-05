"""Shot-size parsing, validation, formatting, and agent-only actual-size writes."""

from __future__ import annotations

import re
from collections import Counter
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

from verticals.core import vertical
from verticals.core.errors import NotFound, ValidationError
from verticals.models import Goal

SHOT_TOKENS: tuple[str, ...] = ("<5m", "10-15m", "45-120m", "240-480m")
_TOKEN_SET = frozenset(SHOT_TOKENS)
_COMPACT_TO_TOKEN = {"<5m": "<5m", "10-15": "10-15m", "45-120": "45-120m", "240-480": "240-480m"}
_TOKEN_TO_COMPACT = {value: key for key, value in _COMPACT_TO_TOKEN.items()}
_PART_RE = re.compile(r"(?P<count>[1-9][0-9]*)x(?P<token><5m|10-15m?|45-120m?|240-480m?)")
_SIZED_VERTICALS = frozenset(h.key for h in vertical.VERTICALS[:2])

COLUMNS = (
    "id, owner, parent_id, path, depth, vertical, anchor_date, period_key, "
    "title, body, color, tags, done_at, position, origin, created_at, updated_at, "
    "repeat_rule, repeat_series_id, repeat_index, repeat_start_date, "
    "parked_from_vertical, foil, carryover_ignored_until, size_expected, size_actual, private"
)


def _validate_owner(owner: object) -> str:
    if not isinstance(owner, str) or not owner:
        raise ValidationError("owner is required and must be a non-empty string", field="owner")
    return owner


def _require_id(value: object) -> str:
    if not isinstance(value, str) or not value:
        raise ValidationError("goal_id is required and must be a non-empty string", field="goal_id")
    return value


def validate(value: object, *, field: str) -> tuple[str, ...] | None:
    """Return canonical tokens. None means unsized; empty arrays are never a second null."""
    if value is None:
        return None
    if isinstance(value, str):
        return tuple(parse_compact(value, field=field))
    if not isinstance(value, (list, tuple)):
        raise ValidationError(f"{field} must be a shot array, compact string, or null", field=field)
    if not value:
        raise ValidationError(f"{field} must not be empty; use null for unsized", field=field)
    tokens: list[str] = []
    for token in value:
        if not isinstance(token, str) or token not in _TOKEN_SET:
            raise ValidationError(
                f"{field} entries must be one of {list(SHOT_TOKENS)}, got {token!r}", field=field
            )
        tokens.append(token)
    return tuple(tokens)


def parse_compact(text: object, *, field: str = "size") -> list[str]:
    """Parse ``2x45-120 1x10-15`` (optional ``+`` separators) into canonical tokens."""
    if not isinstance(text, str):
        raise ValidationError(f"{field} must be a compact string", field=field)
    normalized = text.replace("+", " ").strip()
    if not normalized:
        raise ValidationError(f"{field} must not be empty; use null for unsized", field=field)
    out: list[str] = []
    for part in normalized.split():
        match = _PART_RE.fullmatch(part)
        if match is None:
            raise ValidationError(
                f"{field} must use compact shots like '2x45-120 1x10-15'", field=field
            )
        raw_token = match.group("token")
        compact = raw_token[:-1] if raw_token.endswith("m") and raw_token != "<5m" else raw_token
        token = _COMPACT_TO_TOKEN.get(compact)
        if token is None:
            raise ValidationError(f"{field} contains unknown shot token {raw_token!r}", field=field)
        out.extend([token] * int(match.group("count")))
    return out


def format_compact(value: object, *, field: str = "size") -> str:
    """Group canonical tokens by first appearance into stable compact notation."""
    tokens = validate(value, field=field)
    if tokens is None:
        return ""
    counts = Counter(tokens)
    ordered = list(dict.fromkeys(tokens))
    return " ".join(f"{counts[token]}x{_TOKEN_TO_COMPACT[token]}" for token in ordered)


def ensure_vertical(vertical_key: str | None, *, field: str) -> None:
    if vertical_key not in _SIZED_VERTICALS:
        raise ValidationError(f"{field} is allowed only on week or day goals", field=field)


def update_assignment(value: object) -> tuple[tuple[str, ...] | None, dict[str, object], list[str]]:
    """Build the canonical JSONB assignment consumed by ``goals.update``."""
    normalized = validate(value, field="size_expected")
    stored = Jsonb(list(normalized)) if normalized is not None else None
    return normalized, {"size_expected": stored}, ["size_expected = %(size_expected)s"]


def validate_targets(
    conn: psycopg.Connection, *, owner: str, ids: tuple[str, ...]
) -> None:
    """Lock every expected-size target and refuse missing or above-week goals atomically."""
    rows = conn.execute(
        "SELECT id, vertical FROM goals WHERE owner = %(owner)s AND id = ANY(%(ids)s) FOR UPDATE",
        {"owner": owner, "ids": list(ids)},
    ).fetchall()
    by_id_vertical = dict(rows)
    missing = [goal_id for goal_id in ids if goal_id not in by_id_vertical]
    if missing:
        raise NotFound(f"no goal {missing[0]!r} for owner {owner!r}", id=missing[0], owner=owner)
    for vertical_key in by_id_vertical.values():
        ensure_vertical(vertical_key, field="size_expected")


def _to_goal(row: tuple[Any, ...]) -> Goal:
    values = list(row)
    values[11] = tuple(values[11])
    values[24] = tuple(values[24]) if values[24] is not None else None
    values[25] = tuple(values[25]) if values[25] is not None else None
    return Goal(*values)


def report(
    conn: psycopg.Connection, *, owner: str, goal_id: str, size_actual: object
) -> Goal:
    """Agent-only actual-size write. Owner check and vertical guard happen before update."""
    owner = _validate_owner(owner)
    goal_id = _require_id(goal_id)
    shots = validate(size_actual, field="size_actual")
    with conn.transaction():
        row = conn.execute(
            "SELECT vertical FROM goals WHERE owner = %(owner)s AND id = %(id)s FOR UPDATE",
            {"owner": owner, "id": goal_id},
        ).fetchone()
        if row is None:
            raise NotFound(f"no goal {goal_id!r} for owner {owner!r}", id=goal_id, owner=owner)
        ensure_vertical(row[0], field="size_actual")
        updated = conn.execute(
            f"""
            UPDATE goals
               SET size_actual = %(shots)s, updated_at = clock_timestamp()
             WHERE owner = %(owner)s AND id = %(id)s
             RETURNING {COLUMNS}
            """,
            {"owner": owner, "id": goal_id, "shots": Jsonb(list(shots)) if shots is not None else None},
        ).fetchone()
    return _to_goal(updated)
