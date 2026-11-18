// "Idk" on a carried plan (docs/design/carried-pills.md; the owner, 21 Oct 2026: "If idk — move to inbox with note that we
// need to realign"): one line at the end of the plan's notes, "Needs realigning. Moved from the week of 5 Oct on 21 Oct.",
// then the Inbox, as one step of the board's history. The history's shots hold no notes (the notes have their own undo), so
// the step the move makes also takes the line back, and puts it again on redo, when nobody has written the notes since.
import { getGoal, patchGoal } from './api'
import type { Step } from './boardHistory'
import type { Applied, Outcome } from './boardRestore'
import { MONTH_NAMES } from './periods'
import { isoWeekStart, localDate, periodKeyFor } from './schedule'

/** "5 Oct", as the board writes a day; with its year when that is not this year's. */
function day(d: Date, today: Date): string {
  const year = d.getFullYear() === today.getFullYear() ? '' : ` ${d.getFullYear()}`
  return `${d.getDate()} ${MONTH_NAMES[d.getMonth()]!.slice(0, 3)}${year}`
}

/** The period the plan was planned for, as the line says it: "20 Oct", "the week of 5 Oct", "September", "Q3", "2025". */
export function plannedFor(vertical: string | null | undefined, anchor: string | null | undefined, today: Date): string {
  if (!anchor) return 'its plan'
  const d = localDate(anchor)
  const year = d.getFullYear() === today.getFullYear() ? '' : ` ${d.getFullYear()}`
  switch (vertical) {
    case 'week': return `the week of ${day(isoWeekStart(d), today)}`
    case 'month': return `${MONTH_NAMES[d.getMonth()]}${year}`
    case 'quarter': return `Q${Math.floor(d.getMonth() / 3) + 1}${year}`
    case 'year': return `${d.getFullYear()}`
    case 'decade': return periodKeyFor('decade', d)
    default: return day(d, today)
  }
}

/** The line Idk adds to the notes. */
export function realignLine(vertical: string | null | undefined, anchor: string | null | undefined, today: Date): string {
  return `Needs realigning. Moved from ${plannedFor(vertical, anchor, today)} on ${day(today, today)}.`
}

/** The notes with the line after them, a paragraph of its own. */
export function withLine(body: string, line: string): string {
  return body.trim() ? `${body.trimEnd()}\n\n${line}` : line
}

const outcomeOf = (result: Outcome | Applied): Outcome => (typeof result === 'string' ? result : result.outcome)

/** Sets the notes from `from` to `to`, unless someone has written them since. */
async function setIf(id: string, from: string, to: string): Promise<void> {
  try {
    if ((await getGoal(id)).body === from) await patchGoal(id, { body: to })
  } catch {
    // The goal is gone or the server can't be reached: the move was the step, and its outcome says so.
  }
}

/** `step`, the move, that takes the line back with it and puts it again on redo. */
export function withNote(step: Step, before: string, after: string): Step {
  return {
    ...step,
    async undo(): Promise<Outcome | Applied> {
      const result = await step.undo()
      if (outcomeOf(result) === 'done') await setIf(step.id, after, before)
      return result
    },
    async redo(): Promise<Outcome | Applied> {
      const result = await step.redo()
      if (outcomeOf(result) === 'done') await setIf(step.id, before, after)
      return result
    },
  }
}
