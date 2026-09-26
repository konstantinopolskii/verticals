/** The schedule popover's BROWSED period — which decade/year/month the calendar is showing.
 *
 *  Lifted out of `store.ts` whole (ARCHITECTURE.md §2's 750-line module rule, S-90a): this is a
 *  self-contained piece of view state with no dependency on the board, so it was the cleanest cut
 *  available and not an arbitrary one. Behaviour is unchanged, imports moved.
 */

import { computed, ref, type ComputedRef } from 'vue'
import { buildScheduleGrid, type ScheduleGrid } from './schedule'

/** Which decade/year/month the popover is currently SHOWING. `0` = follow today.
 *
 *  Without it the grid was `buildScheduleGrid(new Date())` — a value with no reactive dependency,
 *  so all four ‹/› steppers emitted `navigate` into a void and the calendar could never leave the
 *  current month. Stored as a timestamp rather than a `Date` so the computed below re-runs on
 *  assignment (a mutated Date object is the same reference and would not invalidate anything). */
const scheduleViewAt = ref(0)

/** One grid, shared by every card's `SchedulePopover` instance. `today` stays the real clock (the
 *  `isToday` dot and the Today/Tomorrow/This week footer are about the calendar, not about what
 *  the user is browsing); `view` is what the steppers page. The `ui` suite pins the clock for the
 *  run's whole duration (E2E.md §1), which this preserves — a pinned clock still gives a pinned
 *  today, and `scheduleViewAt` starts at 0 = today. */
export const scheduleGrid: ComputedRef<ScheduleGrid> = computed(() => {
  const today = new Date()
  return buildScheduleGrid(today, scheduleViewAt.value ? new Date(scheduleViewAt.value) : today)
})

/** Page the schedule popover's decade/year/month row. The grid is rebuilt from the shifted date;
 *  nothing is scheduled and nothing is written — this only changes what the popover displays. */
export function navigateSchedule(
  scale: 'decade' | 'year' | 'month',
  direction: 'prev' | 'next',
): void {
  const step = direction === 'next' ? 1 : -1
  const from = scheduleViewAt.value ? new Date(scheduleViewAt.value) : new Date()
  const next = new Date(from)
  if (scale === 'month') next.setMonth(from.getMonth() + step)
  else if (scale === 'year') next.setFullYear(from.getFullYear() + step)
  else next.setFullYear(from.getFullYear() + step * 3)
  scheduleViewAt.value = next.getTime()
}

/** Back to the real month. Called when a popover opens so every open starts from today rather
 *  than wherever the previous one was left. */
export function resetScheduleView(): void {
  scheduleViewAt.value = 0
}
