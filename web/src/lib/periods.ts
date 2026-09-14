// Client-side period LABELS for SchedulePopover — reads, never derives keys
// (docs/IMPLEMENTATION.md WP-17 card). Every `period_key` this file touches was already produced
// by `core/vertical.py`'s one pure function (ARCHITECTURE.md §3) or handed down by a caller who
// owns real date logic. This module only PARSES an existing key's already-correct string shape
// into display text — it never independently decides which decade/quarter/ISO-week a date falls
// in. Concretely: no `%G-W%` strftime, no `(month - 1) / 3` quarter arithmetic, no
// `Date.prototype.getDay`/`isocalendar`-style ISO-week maths anywhere below. If a seventh scale
// ever needs a fancier label, extend the switch with more parsing, not more computing.

/** Commitment order shared by placement affordances: child rank may not exceed parent rank. */
export const VERTICAL_SCALES = [
  'day', 'week', 'month', 'quarter', 'year', 'decade', 'life',
] as const
export type VerticalScale = typeof VERTICAL_SCALES[number]

export function verticalRank(scale: VerticalScale): number {
  return VERTICAL_SCALES.indexOf(scale)
}

/** One grid cell. `null` (in `WeekRow.days`) is a blank pad cell from the adjacent month — see
 *  `docs/UI_MEASURED.md`-adjacent research (`RESEARCH.md` §"The Schedule picker is the vertical
 *  picker"): the reference planner leaves those blank rather than showing the neighbour month's date. */
export interface DayCell {
  periodKey: string
  isToday?: boolean
}

/** One row of the ISO-week column, paired with that week's seven day cells (Monday first). */
export interface WeekRow {
  periodKey: string
  days: (DayCell | null)[]
}

// Exported for schedule.ts::weekRangeLabel, which needs three-letter abbreviations for a board
// column header ("3–9 Aug") and would otherwise duplicate this same twelve-item list. Everything
// else about this file's charter is unchanged: still reads, never derives keys.
export const MONTH_NAMES = [
  'January', 'February', 'March', 'April', 'May', 'June',
  'July', 'August', 'September', 'October', 'November', 'December',
]

/** Everything after the first "-", e.g. '2026-Q3' -> 'Q3', '2026-W32' -> 'W32'. String slicing
 *  of an already-complete key, not arithmetic on a date. */
function afterDash(periodKey: string): string {
  return periodKey.slice(periodKey.indexOf('-') + 1)
}

/** Turns an existing `period_key` into the text `SchedulePopover` renders. */
export function periodLabel(scale: VerticalScale, periodKey: string): string {
  switch (scale) {
    case 'life':
      return 'Life'
    case 'decade':
    case 'year':
      return periodKey
    case 'quarter':
    case 'week':
      return afterDash(periodKey)
    case 'month': {
      const month = Number(afterDash(periodKey))
      return MONTH_NAMES[month - 1] ?? periodKey
    }
    case 'day': {
      const day = Number(periodKey.slice(periodKey.lastIndexOf('-') + 1))
      return String(day)
    }
    default:
      return periodKey
  }
}
