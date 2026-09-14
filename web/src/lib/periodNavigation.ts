import { isoDate, localDate } from './schedule'
import type { VerticalScale } from './periods'

export type AdjustableVertical = Exclude<VerticalScale, 'life'>
export type PeriodDirection = -1 | 1

function mondayOf(date: Date): Date {
  const monday = new Date(date.getFullYear(), date.getMonth(), date.getDate())
  const weekday = monday.getDay() || 7
  monday.setDate(monday.getDate() + 1 - weekday)
  return monday
}

/** Start date of the adjacent period selected by one navigator click. */
export function adjacentPeriodAnchor(
  anchor: string,
  vertical: AdjustableVertical,
  direction: PeriodDirection,
): string {
  const date = localDate(anchor)
  let result: Date

  switch (vertical) {
    case 'day':
      result = new Date(date.getFullYear(), date.getMonth(), date.getDate() + direction)
      break
    case 'week': {
      const monday = mondayOf(date)
      result = new Date(monday.getFullYear(), monday.getMonth(), monday.getDate() + 7 * direction)
      break
    }
    case 'month':
      result = new Date(date.getFullYear(), date.getMonth() + direction, 1)
      break
    case 'quarter': {
      const quarterMonth = Math.floor(date.getMonth() / 3) * 3
      result = new Date(date.getFullYear(), quarterMonth + 3 * direction, 1)
      break
    }
    case 'year':
      result = new Date(date.getFullYear() + direction, 0, 1)
      break
    case 'decade': {
      const triennium = 2026 + 3 * Math.floor((date.getFullYear() - 2026) / 3)
      result = new Date(triennium + 3 * direction, 0, 1)
      break
    }
  }

  return isoDate(result)
}
