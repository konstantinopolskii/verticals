// The circle's moving mode and pick-up (docs/design-handoff S5.P3, S5.P4): while spans are open the field names the view
// ("Weeks") above it; a goal let go over the field waits there beside it, out of its group, until you drag it to its place.
// On an empty field Backspace picks the last thing and a second takes it off; Tab or a tap picks one too.
import { reactive, watchEffect } from 'vue'
import { circle } from './circle'
import { closeSpans, spanColumns, spans, VIEW_NAMES } from './spans'

export const moving = reactive({
  /** The goal waiting above the field. */
  goalId: null as string | null,
  /** What is picked up on the field (S5.P4.004). */
  picked: null as 'goal' | 'view' | null,
})

watchEffect(() => {
  const on = spans.vertical !== null || moving.goalId !== null
  circle.moving = on
  if (on) circle.job = 'moving'
  else if (circle.job === 'moving') circle.job = 'board'
})

/** The goal let go over the field waits there (S5.P3.037). */
export function park(id: string): void {
  moving.goalId = id
  moving.picked = null
}

/** The goal leaves the field: back where it was, or into the hand again (S5.P4.008, S5.P3.018). */
export function unpark(): void {
  moving.goalId = null
  if (moving.picked === 'goal') moving.picked = null
}

/** The view and the move end together; the board is as it was (S5.P1.029, S5.P3.042, S5.P4.008). */
export function endMove(): void {
  moving.goalId = null
  moving.picked = null
  closeSpans()
}

/** What the agent hears with words sent while moving (S5.P3.041): the view, the spans in it, the goal waiting. */
export function moveContext(title: (id: string) => string | null): Record<string, unknown> {
  return {
    view: spans.vertical ? VIEW_NAMES[spans.vertical] : null,
    spans: spanColumns.value.map((span) => `${span.how}: ${span.date}${span.end ? ` – ${span.end}` : ''} (${span.column?.periodKey ?? ""})`),
    goal: moving.goalId ? { id: moving.goalId, title: title(moving.goalId) } : null,
  }
}

/** The stack from the left: the view's name, then the goal. */
function stack(): Array<'view' | 'goal'> {
  return [...(spans.vertical ? ['view' as const] : []), ...(moving.goalId ? ['goal' as const] : [])]
}

/** Backspace on an empty field: pick the last thing; again, take it off and pick the next (S5.P4.002). */
export function backspace(): boolean {
  const items = stack()
  if (!items.length) return false
  if (!moving.picked) {
    moving.picked = items[items.length - 1]!
    return true
  }
  if (moving.picked === 'goal') {
    unpark()
    moving.picked = spans.vertical ? 'view' : null
  } else {
    endMove()
  }
  return true
}

/** Tab picks one, moving left through the stack (S5.P4.003). */
export function tab(): boolean {
  const items = stack()
  if (!items.length) return false
  const at = moving.picked ? items.indexOf(moving.picked) : items.length
  moving.picked = items[(at - 1 + items.length) % items.length]!
  return true
}

/** A tap picks it; a tap on the one picked lets go (S5.P4.017). */
export function tap(item: 'goal' | 'view'): void {
  moving.picked = moving.picked === item ? null : item
}

/** Esc lets go of the pick; with nothing picked it ends the move (S5.P4.013, S5.P1.029). */
export function escape(): boolean {
  if (moving.picked) {
    moving.picked = null
    return true
  }
  if (!circle.moving) return false
  endMove()
  return true
}
