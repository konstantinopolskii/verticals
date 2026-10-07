// Carrying a card in the Inbox onto the field (Inbox and Documents redesign, round 5, frames c2–c3; KK 7 Oct 2026: "If
// we are in Inbox I believe it should Jump on the same line to field and stay on the left side and big"). Press a card
// or a row and move it past 10 px: it follows the hand. Held over the field, the field becomes the pill that takes it
// (S5.P3.002); let go there and it waits beside the field, on its line at its left, at the Inbox's tile size (final page,
// frame carry), as a goal waits in Move (`lib/moving.ts`): what you ask next carries it. Let go anywhere else, or Esc, and
// it goes back to its place.
import { reactive } from 'vue'
import type { InboxGoal } from './api'
import { park } from './moving'

const THRESHOLD = 10
const TILE_HEIGHT = 92

export const carry = reactive({
  item: null as InboxGoal | null,
  /** Where the card is drawn while it moves: its top-left corner in the window. */
  x: 0,
  y: 0,
  width: 0,
  /** Held over the field. */
  over: false,
  /** The card that waits beside the field, after a let-go over it. */
  beside: null as InboxGoal | null,
})

let start: { x: number; y: number; dx: number; dy: number; item: InboxGoal; width: number } | null = null
/** A press that became a carry is not a click. */
let carried = false
export const wasCarried = (): boolean => { const was = carried; carried = false; return was }

function overField(x: number, y: number): boolean {
  const shape = document.querySelector<HTMLElement>('.circle-field__shape')?.getBoundingClientRect()
  return !!shape && x >= shape.left - 24 && x <= shape.right + 24 && y >= shape.top - 24 && y <= shape.bottom + 24
}

function onMove(event: PointerEvent): void {
  if (!start) return
  if (!carry.item) {
    if (Math.hypot(event.clientX - start.x, event.clientY - start.y) < THRESHOLD) return
    carry.item = start.item
    carry.width = start.width
    carried = true
  }
  carry.x = event.clientX - start.dx
  carry.y = event.clientY - start.dy
  carry.over = overField(event.clientX, event.clientY)
  event.preventDefault()
}

function finish(keep: boolean): void {
  window.removeEventListener('pointermove', onMove)
  window.removeEventListener('pointerup', onUp)
  window.removeEventListener('pointercancel', onCancel)
  window.removeEventListener('keydown', onKey, true)
  if (keep && carry.item && carry.over) {
    carry.beside = carry.item
    park(carry.item.id)
  }
  carry.item = null
  carry.over = false
  start = null
}
function onUp(): void { finish(true) }
function onCancel(): void { finish(false) }
function onKey(event: KeyboardEvent): void {
  if (event.key === 'Escape' && carry.item) { event.preventDefault(); event.stopPropagation(); finish(false) }
}

export function pressCard(event: PointerEvent, item: InboxGoal): void {
  if (event.button !== 0 || (event.target as HTMLElement).closest('.goal-affordance')) return
  const card = event.currentTarget as HTMLElement
  const box = card.getBoundingClientRect()
  // In the hand and beside the field a task is the Inbox's tile, a quarter of the desk, held where it was taken.
  const desk = card.closest('.inbox-desk')
  const width = desk ? (desk.clientWidth - 92 - 48) / 4 : box.width
  const dx = Math.min(event.clientX - box.left, width - 24)
  const dy = Math.min(event.clientY - box.top, TILE_HEIGHT - 24)
  start = { x: event.clientX, y: event.clientY, dx, dy, item, width }
  window.addEventListener('pointermove', onMove, { passive: false })
  window.addEventListener('pointerup', onUp)
  window.addEventListener('pointercancel', onCancel)
  window.addEventListener('keydown', onKey, true)
}
