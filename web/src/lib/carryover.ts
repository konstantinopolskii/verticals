import { store, todayIso } from '../store'
import { VERTICAL_SCALES, type VerticalScale } from './periods'
import { buildScheduleGrid, localDate } from './schedule'

export type CarryoverAction = 'done' | 'move' | 'missed' | 'later'

export const CARRYOVER_ACTIONS = [
  { action: 'done', label: 'Done' },
  { action: 'move', label: 'Move to today' },
  { action: 'missed', label: 'Missed' },
  { action: 'later', label: 'Later' },
] as const satisfies readonly { action: CarryoverAction; label: string }[]

export async function resolveCarryover(
  goal: { id: string; vertical?: string | null; ghostUntil?: string | null },
  action: CarryoverAction,
): Promise<void> {
  if (action === 'done' || action === 'missed') {
    await store.dueAckGhost(goal.id, action === 'done' ? 'done_on_time' : 'overdue')
    return
  }
  if (action === 'later') {
    if (goal.ghostUntil) await store.ignoreGhost(goal.id, goal.ghostUntil)
    return
  }

  if (!goal.vertical || !VERTICAL_SCALES.includes(goal.vertical as VerticalScale)) return
  const vertical = goal.vertical as VerticalScale
  const today = todayIso()
  const current = buildScheduleGrid(localDate(today))
  const grid = current.props
  const period = vertical === 'day' ? today
    : vertical === 'week' ? grid.thisWeek
    : vertical === 'quarter'
      ? grid.quarters.filter((key) => current.anchorDate('quarter', key) <= today).slice(-1)[0]!
      : grid[vertical]

  // Scheduling uses the real current period, even while the board or calendar is browsing
  // another date. The broad store action reloads the board, clearing stale ghost decoration.
  store.resetScheduleView()
  await store.scheduleGoalTo(goal.id, vertical, period)
}
