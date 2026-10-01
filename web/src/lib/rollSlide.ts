// A period turning while the app is open (docs/design-handoff S4.P1.013, .014): the plans left over slide from where they
// stood into their column's group in one movement, 400 ms; with reduced motion they fade in.
import { nextTick } from 'vue'
import { reducedMotion, timing } from './motion'

const ROW = '.goal-card[data-goal-id] > .goal-card__row'

/** Where every plan outside a group stands now. */
export function captureRows(): Map<string, DOMRect> {
  const rows = new Map<string, DOMRect>()
  if (typeof document === 'undefined') return rows
  for (const row of document.querySelectorAll<HTMLElement>(ROW)) {
    if (row.closest('[data-role="carried-group"]')) continue
    rows.set(row.parentElement!.dataset.goalId!, row.getBoundingClientRect())
  }
  return rows
}

/** After the board has drawn the new day: the plans that joined a group come from where they stood. */
export async function slideIntoGroups(before: Map<string, DOMRect>): Promise<void> {
  if (!before.size) return
  await nextTick()
  for (const row of document.querySelectorAll<HTMLElement>(`[data-role="carried-group"] ${ROW}`)) {
    const was = before.get(row.parentElement!.dataset.goalId!)
    if (!was) continue
    const now = row.getBoundingClientRect()
    const dx = was.left - now.left
    const dy = was.top - now.top
    if (Math.abs(dx) < 1 && Math.abs(dy) < 1) continue
    row.animate(
      reducedMotion() ? [{ opacity: 0 }, { opacity: 1 }] : [{ transform: `translate(${dx}px, ${dy}px)` }, { transform: 'none' }],
      timing('pop', 'large'),
    )
  }
}
