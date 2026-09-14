"""Direct probe for `verticals/core/vertical.py`'s pure functions — `period_key` and
`menu_label`. No mocks: neither function touches a database, a clock, or the filesystem, so
there is nothing here a mock would stand in for (docs/BRIEF.md rule 2's own carve-out).

This is not S-03 or S-04. Both scenarios are specified as entering through `create()` and
`schedule()` (docs/E2E.md), which live in `core/goals.py` — WP-13's file, not built in this
wave. The real S-03/S-04 scenarios, run end to end, are WP-13's job, at which point they
belong in `tests/core/test_vertical.py` per the WP-05 file table (docs/IMPLEMENTATION.md). This
file exists so WP-05 has a build-time proof of its own before that file can exist: every exact
value S-03's table asserts, `menu_label`'s asymmetric case, and both `ValueError` guards,
checked directly against the pure functions and nothing else.

Run directly:
    .venv/bin/python -m pytest tests/core/test_vertical_unit.py -v
"""

from __future__ import annotations

from datetime import date

import pytest

from verticals.core.vertical import VERTICALS, menu_label, period_key

# docs/E2E.md S-03 — the full edge table, verbatim: 12 anchors x 6 scales = 72 values. Column
# order matches the source table exactly: day, week, month, quarter, year, decade.
_S03_TABLE: list[tuple[str, str, str, str, str, str, str]] = [
    # anchor         day            week         month     quarter    year    decade
    ("2024-02-29", "2024-02-29", "2024-W09", "2024-02", "2024-Q1", "2024", "2023–2025"),
    ("2021-01-01", "2021-01-01", "2020-W53", "2021-01", "2021-Q1", "2021", "2020–2022"),
    ("2021-01-03", "2021-01-03", "2020-W53", "2021-01", "2021-Q1", "2021", "2020–2022"),
    ("2021-01-04", "2021-01-04", "2021-W01", "2021-01", "2021-Q1", "2021", "2020–2022"),
    ("2026-12-31", "2026-12-31", "2026-W53", "2026-12", "2026-Q4", "2026", "2026–2028"),
    ("2027-01-01", "2027-01-01", "2026-W53", "2027-01", "2027-Q1", "2027", "2026–2028"),
    ("2019-12-31", "2019-12-31", "2020-W01", "2019-12", "2019-Q4", "2019", "2017–2019"),
    ("2020-01-01", "2020-01-01", "2020-W01", "2020-01", "2020-Q1", "2020", "2020–2022"),
    ("2029-12-31", "2029-12-31", "2030-W01", "2029-12", "2029-Q4", "2029", "2029–2031"),
    ("2030-01-01", "2030-01-01", "2030-W01", "2030-01", "2030-Q1", "2030", "2029–2031"),
    ("2016-01-01", "2016-01-01", "2015-W53", "2016-01", "2016-Q1", "2016", "2014–2016"),
    ("2026-08-08", "2026-08-08", "2026-W32", "2026-08", "2026-Q3", "2026", "2026–2028"),
]
_SCALES_IN_TABLE_ORDER = ("day", "week", "month", "quarter", "year", "decade")


def _iso(s: str) -> date:
    return date.fromisoformat(s)


def _s03_cases() -> list[tuple[str, str, str, str]]:
    """Flatten the 12x6 table into 72 (case_id, anchor, scale, expected) tuples."""
    cases: list[tuple[str, str, str, str]] = []
    for row in _S03_TABLE:
        anchor = row[0]
        for scale, expected in zip(_SCALES_IN_TABLE_ORDER, row[1:], strict=True):
            cases.append((f"{anchor}__{scale}", anchor, scale, expected))
    return cases


_CASES = _s03_cases()

assert len(_CASES) == 72, f"S-03 table must yield 72 cases, got {len(_CASES)}"


@pytest.mark.parametrize(
    "anchor,scale,expected",
    [c[1:] for c in _CASES],
    ids=[c[0] for c in _CASES],
)
def test_s03_period_key_matches_edge_table(anchor: str, scale: str, expected: str) -> None:
    assert period_key(scale, _iso(anchor)) == expected


def test_s03_life_has_no_period_arithmetic_on_any_anchor() -> None:
    """§10-D10: `life` is a single constant bucket regardless of `anchor_date`. Checked against
    every S-03 anchor, plus a few dates nowhere near that table, so "any anchor" isn't an
    artefact of reusing S-03's own rows."""
    for anchor, *_rest in _S03_TABLE:
        assert period_key("life", _iso(anchor)) == "life"
    for extra in ("1970-01-01", "2000-02-29", "2099-12-31"):
        assert period_key("life", _iso(extra)) == "life"


def test_s03_unknown_scale_raises_value_error_naming_it() -> None:
    """docs/E2E.md S-03 step 3, verbatim: `core.vertical.period_key("fortnight", date(2026, 8,
    8))` called directly — the table can't reach this case because the enum stops it at the
    Postgres and Pydantic boundaries first."""
    with pytest.raises(ValueError) as exc_info:
        period_key("fortnight", date(2026, 8, 8))
    assert str(exc_info.value) == "fortnight"


def test_menu_label_day_says_today_not_day() -> None:
    """docs/UI_REFERENCE.md §6 / AC-012's own example: the day column's menu item is "Today"."""
    assert menu_label("day") == "Today"


def test_menu_label_is_the_plain_label_everywhere_except_day() -> None:
    """The asymmetry is `day`-only — every other scale's menu label equals its plain label, so
    a copywriting diff would only ever catch this one case (UI_REFERENCE.md §6's own warning)."""
    for h in VERTICALS:
        if h.key == "day":
            assert h.menu_label == "Today" and h.label == "Day"
        else:
            assert h.menu_label == h.label


def test_menu_label_unknown_scale_raises_value_error_naming_it() -> None:
    with pytest.raises(ValueError) as exc_info:
        menu_label("fortnight")
    assert str(exc_info.value) == "fortnight"


def test_exactly_seven_descriptors_one_per_scale() -> None:
    """AC-012: exactly 7 frozen descriptors, one per scale, none repeated."""
    assert len(VERTICALS) == 7
    assert {h.key for h in VERTICALS} == {
        "day", "week", "month", "quarter", "year", "decade", "life",
    }
