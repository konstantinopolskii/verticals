import { nextTick, reactive } from 'vue'
import { reducedMotion, timing } from './motion'

// A goal checked off keeps its place while its check draws (`checkboxMotion.ts`, 200 ms), then glides to the end of its
// list, and the rows it passes glide up. Unchecked, it glides back at once.

const HOLD = 200

/** Done goals still sorted as open: `boardProjection.ts` keeps them in place. */
export const settlingDone = reactive(new Set<string>())
const holds = new Map<string, number>()

function listsHolding(id: string): HTMLElement[] {
  const cards = document.querySelectorAll<HTMLElement>(`[data-goal-id="${CSS.escape(id)}"]`)
  return [...new Set([...cards].flatMap(card => card.parentElement ?? []))]
}

/** Runs a change that reorders the lists holding this goal; their rows glide from where they stood. */
async function glideRows(id: string, change: () => void): Promise<void> {
  if (reducedMotion() || typeof document === 'undefined') {
    change()
    return
  }
  const lists = listsHolding(id)
  const rows = lists.flatMap(list => [...list.children] as HTMLElement[])
  // The goal itself crosses the rows it passes, so it travels over them: its card and its subgoal list.
  const travelling = new Set(lists.flatMap((list) => {
    const card = list.querySelector<HTMLElement>(`:scope > [data-goal-id="${CSS.escape(id)}"]`)
    const kids = card?.nextElementSibling
    return card ? [card, ...(kids?.matches('.goal-card__children') ? [kids] : [])] : []
  }))
  // A row still gliding is read where it is, so a second change turns it from there.
  const before = new Map(rows.filter(row => row.getClientRects().length).map(row => [row, row.getBoundingClientRect().top]))
  change()
  await nextTick()
  for (const [row, top] of before) {
    if (!row.isConnected) continue
    for (const old of row.getAnimations()) if (old.id === 'row-glide') old.cancel()
    const delta = top - row.getBoundingClientRect().top
    if (Math.abs(delta) < 0.5) continue
    const glide = row.animate([{ translate: `0 ${delta}px` }, { translate: '0 0' }], { ...timing('shape', 'play'), id: 'row-glide' })
    if (!travelling.has(row)) continue
    row.dataset.gliding = ''
    const land = () => { if (!row.getAnimations().some(other => other.id === 'row-glide' && other !== glide)) delete row.dataset.gliding }
    glide.addEventListener('finish', land)
    glide.addEventListener('cancel', land)
  }
}

/** Sets a goal done or open; a done goal moves only once its check is drawn. */
export function placeAfterCheck(id: string, done: boolean, change: () => void): void {
  window.clearTimeout(holds.get(id))
  holds.delete(id)
  if (!done || reducedMotion()) {
    void glideRows(id, () => {
      settlingDone.delete(id)
      change()
    })
    return
  }
  settlingDone.add(id)
  change()
  holds.set(id, window.setTimeout(() => {
    holds.delete(id)
    void glideRows(id, () => settlingDone.delete(id))
  }, HOLD))
}
