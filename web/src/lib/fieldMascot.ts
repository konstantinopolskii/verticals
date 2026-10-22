/* The mascot's line in the field (components/MascotLine.tsx): where it stands in each state, and how it gets there. */
import { watch, type ComputedRef, type Ref } from '../reactivity'
import { curve } from './motion'
import { useMascot } from './mascot'
import type { CircleState } from './circle'

type Point = { x: number; y: number }

export type LineMode = 'mascot' | 'hidden' | 'upright' | 'caret' | 'hand' | 'home'

export interface LineIn {
  state: CircleState
  carryOver: boolean
  hovered: boolean
  wide: boolean
  inboxWriting: boolean
  focused: boolean
  selecting: boolean
  hand: Point | null
  onTags: boolean
}

/** Where the line stands: the mascot's at rest, upright under the pointer, your hand over the field, your caret once the
 *  field has it. */
export function lineModeOf(f: LineIn): LineMode {
  if (f.carryOver) return 'mascot'
  if (f.state === 'answer') return 'hidden'
  // Under the pointer the circle only widens: its line neither leans towards a goal nor follows the hand
  // (docs/design/field-hover.md).
  if (f.hovered) return 'upright'
  if (!f.wide) return 'mascot'
  // Resting open in the Inbox, the field is an invitation to write, not the agent: no line until you write (lib/inbox.ts).
  if (f.inboxWriting && f.state === 'open' && !f.focused && !f.hand) return 'hidden'
  if (f.focused) return f.selecting ? 'hidden' : 'caret'
  if (f.hand && !f.onTags) return 'hand'
  return f.state === 'typing' ? 'caret' : 'home'
}

interface Parts {
  line: Ref<HTMLElement | null>
  surface: Ref<HTMLElement | null>
  body: Ref<HTMLElement | null>
  shape: Ref<HTMLElement | null>
}

/** The field's mascot, inside useSetup: it looks around while `mayLook`, and its line goes where `mode` says, again
 *  whenever the hand, the caret or the field's size moves. */
export function fieldMascot(parts: Parts, mayLook: () => boolean, follow: {
  mode: ComputedRef<LineMode>
  hand: ComputedRef<Point | null>
  caret: ComputedRef<Point>
  size: ComputedRef<number>[]
}): void {
  const { mover } = useMascot({
    line: parts.line, surface: parts.surface, body: parts.body,
    center: () => {
      const box = parts.shape.value?.getBoundingClientRect()
      return box ? { x: box.left + box.width / 2, y: box.top + box.height / 2 } : null
    },
  }, mayLook)

  let lastMode: LineMode = 'mascot'
  watch([follow.mode, follow.hand, follow.caret, ...follow.size], () => {
    const m = mover()
    if (!m) return
    const mode = follow.mode.value
    const hand = follow.hand.value
    if (mode === 'hand' && hand) m.set({ x: hand.x, y: hand.y, r: 0, sy: 1 })
    // At once, a lean in flight included: the change comes with the pointer.
    else if (mode === 'upright') { if (lastMode !== 'upright') m.set({ x: 0, y: 0, r: 0, sy: 1 }) }
    else if (mode === 'caret') {
      const slide = lastMode !== 'caret' && lastMode !== 'hidden'
      if (slide) void m.to({ ...follow.caret.value, r: 0, sy: 1 }, 140, curve('large'))
      else m.set({ ...follow.caret.value, r: 0, sy: 1 })
    } else if (mode === 'home' && lastMode !== 'home') void m.to({ x: 0, y: 0, r: 0, sy: 1 }, 160, curve('large'))
    else if (mode === 'mascot' && lastMode !== 'mascot') void m.to({ x: 0, y: 0, r: 0, sy: 1 }, 160, curve('large'))
    lastMode = mode
  }, { flush: 'post' })
}
