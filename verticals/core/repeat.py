"""Repeat-rule validation, date arithmetic, and deterministic occurrence materialisation.

The public trigger is deliberately narrow: `core.goals.update(..., done=True)` calls
`materialize_next` inside the same transaction after completing the current row. Reads and the
wall clock never write. A replay computes the same next occurrence index, while the database's
partial unique index on `(owner, repeat_series_id, repeat_index)` makes the operation idempotent
under both retries and concurrent completion calls.
"""

from __future__ import annotations

import calendar
import secrets
import string
from collections.abc import Mapping
from datetime import date, datetime, timedelta

import psycopg
from psycopg.types.json import Jsonb

from verticals.core import vertical as vertical_mod
from verticals.core import moves, tree
from verticals.core.errors import NotFound, ValidationError
from verticals.models import Goal

# `every_decade`, not `decade`: repeat frequencies are their OWN vocabulary and must not collide
# with the `vertical_scale` labels. The collision was not cosmetic — S-108b forbids comparing
# against a scale literal anywhere outside `core/vertical.py`, and `frequency == "decade"` read
# exactly like scale behaviour leaking out of its module. Distinct words, distinct namespaces.
FREQUENCIES = frozenset({"daily", "weekly", "monthly", "quarterly", "yearly", "every_decade"})
_KEYS = frozenset(
    {"frequency", "interval", "weekdays", "month_days", "months", "quarters", "end_date"}
)
_SELECTORS = ("weekdays", "month_days", "months", "quarters")
_ID_ALPHABET = string.ascii_letters + string.digits


def _integer(value: object, field: str, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise ValidationError(
            f"{field} must be an integer from {minimum} to {maximum}",
            field=field,
            minimum=minimum,
            maximum=maximum,
        )
    return value


def _selection(value: object, field: str, minimum: int, maximum: int) -> list[int]:
    if not isinstance(value, (list, tuple)) or not value:
        raise ValidationError(f"{field} must be a non-empty list", field=field)
    result = [_integer(item, field, minimum, maximum) for item in value]
    if len(set(result)) != len(result):
        raise ValidationError(f"{field} must not contain duplicates", field=field)
    return sorted(result)


def validate_rule(value: object) -> dict | None:
    """Return a JSON-safe rule without guessing or silently correcting any invalid field."""
    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise ValidationError("repeat must be an object or null", field="repeat")
    unexpected = set(value) - _KEYS
    if unexpected:
        field = sorted(unexpected)[0]
        raise ValidationError(f"unexpected repeat field {field!r}", field=f"repeat.{field}")

    frequency = value.get("frequency")
    if not isinstance(frequency, str) or frequency not in FREQUENCIES:
        raise ValidationError(
            f"repeat.frequency must be one of {sorted(FREQUENCIES)}",
            field="repeat.frequency",
        )
    interval_max = 5 if frequency == "weekly" else 10 if frequency in {"yearly", "every_decade"} else 1
    interval = _integer(value.get("interval", 1), "repeat.interval", 1, interval_max)

    selections: dict[str, list[int]] = {}
    ranges = {"weekdays": (1, 7), "month_days": (1, 31), "months": (1, 12), "quarters": (1, 4)}
    for field, bounds in ranges.items():
        if field in value:
            selections[field] = _selection(value[field], f"repeat.{field}", *bounds)
    if len(selections) > 1:
        raise ValidationError(
            "repeat accepts at most one calendar selector",
            field="repeat.weekdays,repeat.month_days,repeat.months,repeat.quarters",
        )

    allowed_selector = {
        "daily": None,
        "weekly": "weekdays" if interval == 1 else None,
        "monthly": "month_days" if interval == 1 else None,
        "quarterly": None,
        "yearly": "months|quarters" if interval == 1 else None,
        "every_decade": None,
    }[frequency]
    for field in selections:
        if allowed_selector is None or field not in allowed_selector.split("|"):
            raise ValidationError(
                f"repeat.{field} is not valid with {frequency} interval {interval}",
                field=f"repeat.{field}",
            )

    end = value.get("end_date")
    if end is not None and (isinstance(end, datetime) or not isinstance(end, date)):
        raise ValidationError("repeat.end_date must be a date or null", field="repeat.end_date")

    normalized: dict[str, object] = {"frequency": frequency, "interval": interval}
    normalized.update(selections)
    if "end_date" in value:
        normalized["end_date"] = end.isoformat() if end is not None else None
    return normalized


def update_assignment(value: object) -> tuple[dict | None, dict[str, object], list[str]]:
    """Translate one validated public rule into the four recurrence-column assignments."""
    rule = validate_rule(value)
    if rule is None:
        return None, {}, [
            "repeat_rule = NULL", "repeat_series_id = NULL", "repeat_index = NULL",
            "repeat_start_date = NULL",
        ]
    return rule, {"repeat_rule": Jsonb(rule)}, [
        "repeat_rule = %(repeat_rule)s::jsonb",
        "repeat_series_id = COALESCE(repeat_series_id, id)",
        "repeat_index = COALESCE(repeat_index, 0)",
        "repeat_start_date = COALESCE(repeat_start_date, anchor_date)",
    ]


def validate_target(conn: psycopg.Connection, *, owner: str, id: str) -> None:
    row = conn.execute(
        "SELECT vertical, anchor_date FROM goals"
        " WHERE owner = %(owner)s AND id = %(id)s FOR UPDATE",
        {"owner": owner, "id": id},
    ).fetchone()
    if row is None:
        raise NotFound(f"no goal {id!r} for owner {owner!r}", id=id, owner=owner)
    vertical, anchor_date = row
    if vertical is None or anchor_date is None:
        raise ValidationError("repeat requires a scheduled goal", field="repeat")
    if vertical_mod.descriptor(vertical).bounds_fn(anchor_date) is None:
        raise ValidationError("this vertical cannot repeat", field="repeat")
    child = conn.execute(
        "SELECT 1 FROM goals WHERE owner = %(owner)s AND parent_id = %(id)s LIMIT 1",
        {"owner": owner, "id": id},
    ).fetchone()
    if child is not None:
        raise ValidationError("goals with subgoals cannot repeat", field="repeat")


def _add_months(value: date, count: int) -> date:
    month_index = value.year * 12 + value.month - 1 + count
    year, zero_month = divmod(month_index, 12)
    month = zero_month + 1
    return date(year, month, min(value.day, calendar.monthrange(year, month)[1]))


def _add_years(value: date, count: int) -> date:
    year = value.year + count
    return date(year, value.month, min(value.day, calendar.monthrange(year, value.month)[1]))


def next_anchor(current: date, rule: Mapping[str, object]) -> date:
    frequency = str(rule["frequency"])
    interval = int(rule["interval"])
    if frequency == "daily":
        return current + timedelta(days=interval)
    if frequency == "weekly" and "weekdays" in rule:
        weekdays = set(rule["weekdays"])
        for offset in range(1, 8):
            candidate = current + timedelta(days=offset)
            if candidate.isoweekday() in weekdays:
                return candidate
    if frequency == "weekly":
        return current + timedelta(weeks=interval)
    if frequency == "monthly" and "month_days" in rule:
        days = set(rule["month_days"])
        for month_offset in range(0, 13):
            base = _add_months(current.replace(day=1), month_offset)
            for day_number in sorted(days):
                if day_number <= calendar.monthrange(base.year, base.month)[1]:
                    candidate = base.replace(day=day_number)
                    if candidate > current:
                        return candidate
    if frequency == "monthly":
        return _add_months(current, interval)
    if frequency == "quarterly":
        return _add_months(current, 3 * interval)
    if frequency == "yearly" and "months" in rule:
        months = set(rule["months"])
        for month_offset in range(1, 25):
            candidate = _add_months(current, month_offset)
            if candidate.month in months:
                return candidate
    if frequency == "yearly" and "quarters" in rule:
        quarters = set(rule["quarters"])
        for month_offset in range(1, 25):
            candidate = _add_months(current, month_offset)
            if (candidate.month - 1) // 3 + 1 in quarters and candidate.month % 3 == 1:
                return candidate
    if frequency == "yearly":
        return _add_years(current, interval)
    if frequency == "every_decade":
        return _add_years(current, interval * 10)
    raise AssertionError(frequency)


def _existing(conn: psycopg.Connection, *, owner: str, series_id: str, index: int) -> Goal | None:
    row = conn.execute(
        f"SELECT {tree.COLUMNS} FROM goals"
        " WHERE owner = %(owner)s AND repeat_series_id = %(series)s AND repeat_index = %(index)s",
        {"owner": owner, "series": series_id, "index": index},
    ).fetchone()
    return tree._to_goal(row) if row is not None else None


def materialize_next(
    conn: psycopg.Connection, *, owner: str, completed: Goal
) -> Goal | None:
    """Materialise index N+1 on completion; replay returns the already-created occurrence."""
    if completed.repeat_rule is None:
        return None
    assert completed.anchor_date is not None
    assert completed.vertical is not None
    assert completed.repeat_series_id is not None
    assert completed.repeat_index is not None
    assert completed.repeat_start_date is not None
    next_index = completed.repeat_index + 1
    existing = _existing(
        conn, owner=owner, series_id=completed.repeat_series_id, index=next_index
    )
    if existing is not None:
        return existing
    anchor = next_anchor(completed.anchor_date, completed.repeat_rule)
    raw_end = completed.repeat_rule.get("end_date")
    if raw_end is not None and anchor > date.fromisoformat(str(raw_end)):
        return None
    period_key = vertical_mod.period_key(completed.vertical, anchor)
    position = moves.allocate_position(
        conn,
        owner=owner,
        vertical=completed.vertical,
        period_key=period_key,
        parent_id=completed.parent_id,
    )
    for _ in range(3):
        created = tree.attach(
            conn,
            owner=owner,
            id="".join(secrets.choice(_ID_ALPHABET) for _ in range(8)),
            parent_id=completed.parent_id,
            title=completed.title,
            body=completed.body,
            vertical=completed.vertical,
            anchor_date=anchor,
            period_key=period_key,
            color=completed.color,
            tags=completed.tags,
            origin=completed.origin,
            position=position,
            repeat_rule=completed.repeat_rule,
            repeat_series_id=completed.repeat_series_id,
            repeat_index=next_index,
            repeat_start_date=completed.repeat_start_date,
        )
        if created is not None:
            return created
        existing = _existing(
            conn, owner=owner, series_id=completed.repeat_series_id, index=next_index
        )
        if existing is not None:
            return existing
    raise ValidationError("could not generate a unique occurrence id", field="id")
