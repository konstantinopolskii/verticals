/* The drag's slot in a list of goals (components/DropSlot.tsx): a column's top-level list, or a goal's own subgoals
   (Column.tsx, GoalCard.tsx). */
import { nextTick } from '../reactivity'
import { store } from '../store'
import { curve, reducedMotion } from './motion'

export type SlotItem = { kind: 'slot'; key: '__dnd-placeholder__' | '__dnd-destination__'; settling: boolean }

/** The slot spliced into `items` before the goal it stands before, or at the end (`insertBeforeId: null`, or a goal
 *  that is not in the list). */
export function withSlot<T extends { kind: 'goal'; goal: { id: string } }>(items: T[]): (T | SlotItem)[] {
  const out: (T | SlotItem)[] = [...items]
  const beforeId = store.state.drag.slot?.insertBeforeId ?? null
  const found = beforeId === null ? items.length : items.findIndex((item) => item.goal.id === beforeId)
  out.splice(found < 0 ? items.length : found, 0, {
    kind: 'slot',
    key: store.state.drag.settling ? '__dnd-destination__' : '__dnd-placeholder__',
    settling: store.state.drag.settling !== null,
  })
  return out
}

/** The goals under `root` slide from where they stood to where the slot's move leaves them, after the next drawing.
 *  With reduced motion the gap simply opens and the goals below stand where they land (docs/design/column-bounce.md). */
export async function slideGoals(root: () => HTMLElement | null, selector: string): Promise<void> {
  if (reducedMotion()) return
  const before = new Map(
    [...(root()?.querySelectorAll<HTMLElement>(selector) ?? [])]
      // A hidden card (a goal's subtasks flying with it) has no place to slide from.
      .filter((element) => element.getClientRects().length > 0)
      .map((element) => [element.dataset.goalId, element.getBoundingClientRect().top]),
  )
  await nextTick()
  for (const element of root()?.querySelectorAll<HTMLElement>(selector) ?? []) {
    const oldTop = before.get(element.dataset.goalId)
    if (oldTop === undefined) continue
    const delta = oldTop - element.getBoundingClientRect().top
    if (Math.abs(delta) < 0.5) continue
    element.animate(
      [{ transform: `translateY(${delta}px)` }, { transform: 'translateY(0)' }],
      { duration: 200, easing: curve('medium') },
    )
  }
}
