// What an ask of the agent's will change, in your words (docs/design/agent-fixes.md, fix 6). The gateway sends the write's name
// and inputs with the ask and the card drew only "Allow Claude to use schedule?", so you answered a question about a tool.
// The goal is named by its title, as the board names it, and its date as the board's own cards say it (lib/schedule.ts):
// "Draft the outline · Mon 10 Aug".
import { reactive } from '../reactivity'
import { getGoal } from './api'
import type { Ask } from './agentChat'
import { findGoal } from './boardIndex'
import { plannedPeriodLabel } from './schedule'
import { store } from '../store'

/** The writes that name a goal already there by its `id`, or by several in `ids`. */
const ON_A_GOAL = new Set(['update', 'schedule', 'reparent', 'delete', 'park'])

const read = reactive(new Map<string, string | null>())

/** A goal's title: the board's, else read once (a goal outside the slice on the board), else null while it is read or if it
 *  is gone. The read is marked best-effort, as the sweep's are: a goal that is gone answers 404 and that is no error here. */
function titleOf(id: string): string | null {
  const known = findGoal(store.state.board, id)?.title
  if (known) return known
  if (!read.has(id)) {
    read.set(id, null)
    void getGoal(id, true).then((goal) => read.set(id, goal.title)).catch(() => undefined)
  }
  return read.get(id) ?? null
}

/** The date the write gives the goal, the way the board says it, or null when the write sets none. Both fields empty is
 *  the goal losing its date. */
function dateOf(input: Record<string, unknown>): string | null {
  if (!('vertical' in input) && !('anchor_date' in input)) return null
  const scale = typeof input.vertical === 'string' ? input.vertical : null
  const day = typeof input.anchor_date === 'string' ? input.anchor_date : null
  if (!scale && !day) return 'No date'
  if (scale === 'life') return 'Life'
  if (!scale || !day) return null
  return plannedPeriodLabel({ vertical: scale, anchor_date: day, period_key: null }) || null
}

/** The goal an ask is about and the date it would get; null when the ask names no goal (a shell command, a document) or
 *  the goal is not known yet. */
export function askDetail(ask: Ask): { goal: string; date: string | null } | null {
  const input = ask.input
  if (!ask.tool || !input) return null
  let goal: string | null = null
  if (ask.tool === 'create') {
    goal = typeof input.title === 'string' ? input.title.trim() : null
  } else if (ON_A_GOAL.has(ask.tool)) {
    const ids = Array.isArray(input.ids) ? input.ids.filter((id): id is string => typeof id === 'string') : []
    if (typeof input.id === 'string') goal = titleOf(input.id)
    else if (ids.length === 1) goal = titleOf(ids[0]!)
    else if (ids.length > 1) goal = `${ids.length} goals`
  }
  return goal ? { goal, date: dateOf(input) } : null
}

/** The same, as the one line the field says; an ask the app makes of its own says its note (the sign-in's,
 *  docs/design/agent-sign-in.md). */
export function askLine(ask: Ask): string {
  if (ask.note) return ask.note
  const detail = askDetail(ask)
  return detail ? [detail.goal, detail.date].filter(Boolean).join(' · ') : ''
}
