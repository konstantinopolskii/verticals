"""The seven vertical-scale descriptors — the entire "what is a day/week/.../life column"
vocabulary, in one place, per ARCHITECTURE.md §3 and docs/UI_REFERENCE.md §6.

**`period_key` is written once and never touched again** (ARCHITECTURE.md §3). The function
below is that pinned implementation — do not reshape an existing branch's output format;
changing it changes what every already-written row means. Add an eighth scale by adding a
branch here *and* a descriptor entry below, never one without the other.

**Scale behaviour lives only here** (docs/IMPLEMENTATION.md WP-05 notes; AC-012). No other
module under `verticals/` may compare a value against one of the seven scale strings — every
caller that needs scale-specific behaviour goes through `descriptor()`, `period_key()`, or
`menu_label()` instead, so an eighth scale is a change to this file alone. The sole exception
the acceptance criterion itself declares is the enum literal in `db/migrations/001_init.sql`
(WP-03's file, generated from this same seven-entry list, not touched here).

The reference planner's own client gives each vertical an object with capability methods, including a
recurrence-options getter (`docs/UI_REFERENCE.md` §6). **Recurrence is out of scope for v1**
(`docs/ACCEPTANCE.md` AC-187 fails the build on the word itself), so the descriptor below
carries only the one capability flag this product actually has: whether a column can be
timeblocked. If recurrence ever ships, it is one more field added here — nowhere else.
"""

from __future__ import annotations

import calendar
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, timedelta
from functools import partial

Bounds = tuple[date, date] | None
TRIENNIUM_EPOCH = 2026


def _triennium_start_year(year: int) -> int:
    return TRIENNIUM_EPOCH + 3 * ((year - TRIENNIUM_EPOCH) // 3)


def period_key(scale: str, d: date) -> str:
    """The entire vertical engine. `life` has no period arithmetic (§10-D10): every anchor
    maps to the single constant bucket `"life"`. An unrecognised scale raises `ValueError`
    naming it rather than guessing — the enum at the Postgres and Pydantic boundaries means
    `create()` can never actually deliver one here, but the guard stays because this function
    is reachable directly, and a silent fallback would hide the caller's bug instead of
    surfacing it (house rule: rigid input validation over guessing)."""
    if scale == "day":
        return d.isoformat()
    if scale == "week":
        year, week, _ = d.isocalendar()
        return f"{year}-W{week:02d}"
    if scale == "month":
        return f"{d:%Y-%m}"
    if scale == "quarter":
        return f"{d.year}-Q{(d.month - 1) // 3 + 1}"
    if scale == "year":
        return str(d.year)
    if scale == "decade":
        start_year = _triennium_start_year(d.year)
        return f"{start_year}–{start_year + 2}"
    if scale == "life":
        return "life"
    raise ValueError(scale)


def _bounds_day(d: date) -> Bounds:
    return (d, d)


def _bounds_week(d: date) -> Bounds:
    start = d - timedelta(days=d.isoweekday() - 1)
    return (start, start + timedelta(days=6))


def _bounds_month(d: date) -> Bounds:
    last_day = calendar.monthrange(d.year, d.month)[1]
    return (d.replace(day=1), d.replace(day=last_day))


def _bounds_quarter(d: date) -> Bounds:
    first_month = (d.month - 1) // 3 * 3 + 1
    last_month = first_month + 2
    last_day = calendar.monthrange(d.year, last_month)[1]
    return (date(d.year, first_month, 1), date(d.year, last_month, last_day))


def _bounds_year(d: date) -> Bounds:
    return (date(d.year, 1, 1), date(d.year, 12, 31))


def _bounds_decade(d: date) -> Bounds:
    start_year = _triennium_start_year(d.year)
    return (date(start_year, 1, 1), date(start_year + 2, 12, 31))


def _bounds_life(_d: date) -> Bounds:
    # No period arithmetic (§10-D10) — a caller that needs to know whether a scale even has
    # a date range checks `descriptor(scale).bounds_fn(d) is None`, never the scale itself.
    return None


@dataclass(frozen=True)
class VerticalDescriptor:
    """One frozen row of the table `docs/UI_REFERENCE.md` §6 asks for, in Python instead of
    seven scattered `if` branches."""

    key: str
    label: str
    menu_label: str
    period_key_fn: Callable[[date], str]
    bounds_fn: Callable[[date], Bounds]
    is_timeblockable: bool


# Declaration order doubles as AC-145's "vertical descriptor rank" — day first, life last,
# matching the enum's own declaration order in db/migrations/001_init.sql.
VERTICALS: tuple[VerticalDescriptor, ...] = (
    VerticalDescriptor("day", "Day", "Today", partial(period_key, "day"), _bounds_day, True),
    VerticalDescriptor("week", "Week", "Week", partial(period_key, "week"), _bounds_week, False),
    VerticalDescriptor(
        "month", "Month", "Month", partial(period_key, "month"), _bounds_month, False
    ),
    VerticalDescriptor(
        "quarter", "Quarter", "Quarter", partial(period_key, "quarter"), _bounds_quarter, False
    ),
    VerticalDescriptor("year", "Year", "Year", partial(period_key, "year"), _bounds_year, False),
    VerticalDescriptor(
        "decade", "3 years", "3 years", partial(period_key, "decade"), _bounds_decade, False
    ),
    VerticalDescriptor("life", "Life", "Life", partial(period_key, "life"), _bounds_life, False),
)

# Lets a caller validate "is this a real scale" by membership test instead of enumerating —
# or reimplementing — the seven values itself.
SCALE_KEYS: frozenset[str] = frozenset(h.key for h in VERTICALS)

_BY_KEY: dict[str, VerticalDescriptor] = {h.key: h for h in VERTICALS}
_RANK_BY_KEY: dict[str, int] = {h.key: rank for rank, h in enumerate(VERTICALS)}


def descriptor(scale: str) -> VerticalDescriptor:
    """The one lookup every other module should use instead of an `if`/`elif` ladder over
    scale strings. Raises `ValueError` naming the scale, matching `period_key`'s contract."""
    try:
        return _BY_KEY[scale]
    except KeyError:
        raise ValueError(scale) from None


def menu_label(scale: str) -> str:
    """`docs/UI_REFERENCE.md` §6: the day column's menu item says "Today", not "Day" — every
    other scale's menu label equals its plain label. `menu_label('day') == 'Today'` is
    AC-012's own example assertion."""
    return descriptor(scale).menu_label


def map_label(scale: str, d: date) -> str:
    """D252 (KK, 2026-08-20): the bracketed label `outline(mode='map')` prints beside a scheduled
    node. Every scale but two uses its own `menu_label` (`decade` -> "3 years", `year` -> "Year",
    `quarter` -> "Quarter", `week` -> "Week", `life` -> "Life") — KK's own sample byte-matches
    `menu_label` for exactly those four. The two exceptions are KK's own words: "days show the
    date", and a month goal shows its month NAME rather than the bare word "Month" (which would
    be useless without knowing which one). Kept here with every other scale-specific branch
    (AC-012 / S-108b: no scale-literal comparison outside this module) — a caller (`core/
    markdown.py::goal_map`) hands in the scale and the goal's own `anchor_date` and gets back
    an opaque string, never branching on the scale itself."""
    if scale == "day":
        return d.isoformat()
    if scale == "month":
        return f"{d:%B}"
    return menu_label(scale)


def rank(scale: str) -> int:
    """Commitment rank, day=0 through life=6. A child may stay at its parent's rank or move
    downward toward day, never upward toward life. Raises `ValueError` for an unknown scale,
    matching `descriptor()` and `period_key()`."""
    try:
        return _RANK_BY_KEY[scale]
    except KeyError:
        raise ValueError(scale) from None


def is_value_scale(scale: str | None) -> bool:
    """D231/D239's root-gate predicate: values are parentless goals on the life scale — the
    scale whose rows feed the value menu and the derived-colour law. Kept here with every other
    scale-specific branch (AC-012 / S-108b: no scale-literal comparisons outside this module)."""
    return scale == "life"


def loads_legacy_period_keys(scale: str) -> bool:
    """Whether board membership must use anchor bounds instead of stored period_key.

    The 3-year redesign kept old decade-keyed rows byte-untouched, so only this legacy storage
    key needs the compatibility read. Kept here with all scale-specific behaviour (AC-012).
    """
    return scale == "decade"
