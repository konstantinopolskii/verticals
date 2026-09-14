from __future__ import annotations

from datetime import date

import psycopg
import pytest

from verticals.core import goals, sizes
from verticals.core.errors import ValidationError


def _scheduled(db: psycopg.Connection, vertical: str):
    return goals.create(
        db, owner="size-owner", title=f"Synthetic {vertical}",
        vertical=vertical, anchor_date=date(2026, 8, 12),
    ).goal


def test_compact_parse_format_round_trip_and_closed_tokens() -> None:
    shots = ["45-120m", "45-120m", "10-15m"]
    compact = sizes.format_compact(shots)
    assert compact == "2x45-120 1x10-15"
    assert sizes.parse_compact(compact) == shots
    assert sizes.parse_compact("2x45-120m + 1x10-15m") == shots
    with pytest.raises(ValidationError):
        sizes.parse_compact("1x30-60")
    with pytest.raises(ValidationError):
        sizes.validate(["unknown"], field="size_expected")


def test_expected_and_actual_sizes_week_day_only_null_not_empty(db: psycopg.Connection) -> None:
    week = _scheduled(db, "week")
    day = _scheduled(db, "day")
    month = _scheduled(db, "month")

    updated = goals.update(db, owner="size-owner", id=week.id, size_expected="2x45-120 1x10-15")
    assert updated.goal.size_expected == ("45-120m", "45-120m", "10-15m")
    assert sizes.report(db, owner="size-owner", goal_id=day.id, size_actual=["<5m"]).size_actual == ("<5m",)

    assert goals.update(db, owner="size-owner", id=week.id, size_expected=None).goal.size_expected is None
    with pytest.raises(ValidationError):
        goals.update(db, owner="size-owner", id=week.id, size_expected=[])
    with pytest.raises(ValidationError):
        goals.update(db, owner="size-owner", id=month.id, size_expected=["10-15m"])
    with pytest.raises(ValidationError):
        sizes.report(db, owner="size-owner", goal_id=month.id, size_actual=["10-15m"])


def test_size_writes_do_not_bump_content_revision(db: psycopg.Connection) -> None:
    week = _scheduled(db, "week")
    before = db.execute("SELECT content_revision FROM goals WHERE id = %s", (week.id,)).fetchone()[0]
    goals.update(db, owner="size-owner", id=week.id, size_expected=["10-15m"])
    sizes.report(db, owner="size-owner", goal_id=week.id, size_actual=["10-15m"])
    after = db.execute("SELECT content_revision FROM goals WHERE id = %s", (week.id,)).fetchone()[0]
    assert after == before
