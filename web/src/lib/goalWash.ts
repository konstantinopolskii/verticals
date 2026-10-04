// One highlight shape per goal (KK, 27 Sep 2026): "when we hover a parent we highlight parent and sub-agoals as usually
// we had before, no united highligted. Margins betwen parent and subgoals should become like 1px for small columns and
// 2 px for the expanded... Same for the hovering the parent and tracing it down to ancestors. Simple fucking logic".
//
// The colour is a layer behind each goal's row (`goalCard.css`, `.goal-card__row::before`), sized by four offsets
// from the row: --wash-t/-b/-l/-r. Every goal, parent or subgoal, has one shape of its own, whatever colours it (hover,
// the family chain, an opened goal's relatives, its menu) and whatever the column. It spans the top-level goal's lane
// (KK: a subgoal's highlight is as wide as its parent's), starting --goal-shape-inset in from its left edge, which
// leaves room between columns; a list stepped in on the way down to a deeper open goal steps its shapes in with it.
// The shapes of one card tile it from its top to the end of its subgoal list, exactly --subgoal-gap apart: 1 px in a
// narrow column, 2 px in the wide one, the same gap the layout leaves between a goal and its first subgoal. Subgoal
// boxes overlap or leave other space between them, so two neighbours part around the middle of that space, and the
// last shape takes the list's bottom padding: the card as a whole has the same room around its words as a goal
// without subgoals, and the next card is as far as after any goal (KK, 27 Sep 2026: the vertical gaps were
// "questionable and inconsistent"). Titles and checkboxes never move: the layer pushes nothing.
//
// An open goal is one piece (the cleaned-up card, KK 27 Sep 2026): its colour runs down its steps and its notes to the
// end of its list. Its "Add…" row and its notes have no shape of their own; they only bound their neighbours', so a
// step's shape stops at them and the goal after the piece starts below it. The piece's colour is two shapes that meet:
// the goal's row's, down to where its steps start, and its list's, from there to the end (--piece-t/-b/-l/-r on the
// list, goalCard.css). One shape from the row reaching down under the list let WebKit, the engine of Verticals' own
// window, stack the row and the list wrongly whenever either changed layers (filmed in the system WebKit, 4 Oct 2026).
//
// A shape depends on layout only, so it is measured when the group's size or its subgoals change, never when the colour
// moves: colour shows or hides a shape already in place. Positions come from layout boxes (offset*), which a lift's
// transform does not touch.

import { onBeforeUnmount, onMounted, watch, type Ref, type WatchSource } from 'vue'

/** A mounted group: it measures its shapes, then writes them. */
type Group = { measure: () => Measured | null; write: (measured: Measured) => void }
type Measured = { boxes: Box[]; end: number; gap: number; lane: { left: number; right: number } }

/* Groups are placed together: every one is measured, then every one is written, so the board is laid out once for all
   of them. Placed one by one, each read after the last one's writes laid the board out again: 18 ms of the first
   opening, most of it forced layout (profiled 29 Sep 2026). A shape that didn't move isn't written again, so it
   doesn't restyle its card either. */
const groups = new Set<Group>()
const due = new Set<Group>()
let queued = false
function flush(): void {
  queued = false
  const measured = [...due].map((group) => [group, group.measure()] as const)
  due.clear()
  for (const [group, m] of measured) if (m) group.write(m)
}
function schedule(group: Group): void {
  due.add(group)
  if (!queued) {
    queued = true
    queueMicrotask(flush)
  }
}
/** Every group now, so a family move (lib/familyMotion.ts) can place the shapes for the layout it is about to read,
 *  before the resize observer would on the next frame. */
export function placeAllWashes(): void {
  for (const group of groups) due.add(group)
  flush()
}
/** One observer for every card and list: the browser reports all the sizes that changed at once. */
const owners = new WeakMap<Element, Group>()
const sizes = typeof ResizeObserver === 'undefined' ? null : new ResizeObserver((entries) => {
  for (const entry of entries) {
    const group = owners.get(entry.target)
    if (group) due.add(group)
  }
  flush()
})
const written = new WeakMap<HTMLElement, string>()

/** `end`: where an open goal's piece ends (its list's bottom); -Infinity for any other goal. `bound`: a row that has no
 *  shape and only bounds its neighbours' ("Add…", the notes). `shift`: how far its list steps in from the first one. */
type Box = {
  el: HTMLElement; top: number; bottom: number; end: number; left: number; right: number; row: Rect
  bound: boolean; shift: number; piece: (Rect & { el: HTMLElement }) | null
}
type Rect = { top: number; bottom: number; left: number; right: number }

const BOUNDS = '.goal-card__add-step, #goal-detail'

/** An element's layout offset inside `ref`, summed along its offsetParent chain. */
function offsetIn(el: HTMLElement, ref: Element | null): { top: number; left: number } {
  let top = 0
  let left = 0
  for (let e: HTMLElement | null = el; e && e !== ref; e = e.offsetParent as HTMLElement | null) {
    top += e.offsetTop
    left += e.offsetLeft
  }
  return { top, left }
}

export function useGroupWash(options: {
  card: () => HTMLElement | null
  list: Ref<HTMLElement | null>
  /** Measure again when one of these changes: the rendered subgoals. Size changes are watched on their own. */
  layoutSources: WatchSource[]
}) {
  function measure(): Measured | null {
    const card = options.card()
    const list = options.list.value
    if (!card) return null
    const ref = card.offsetParent
    const items = [card, ...(list ? list.querySelectorAll<HTMLElement>(`.goal-card[data-goal-id], ${BOUNDS}`) : [])]
    const end = list && list.offsetParent !== null ? offsetIn(list, ref).top + list.offsetHeight : 0
    const firstList = list && list.offsetParent !== null ? offsetIn(list, ref).left : 0
    const boxes = items.filter((el) => el.offsetParent !== null).map((el) => {
      const at = offsetIn(el, ref)
      const bound = el.matches(BOUNDS)
      const row = bound ? null : el.querySelector<HTMLElement>(':scope > .goal-card__row')
      const rowTop = at.top + (row?.offsetTop ?? 0)
      const rowLeft = at.left + (row?.offsetLeft ?? 0)
      const own = el.classList.contains('goal-card--detail-open') ? el.nextElementSibling : null
      const piece = own instanceof HTMLElement && own.classList.contains('goal-card__children') ? own : null
      const pieceAt = piece ? offsetIn(piece, ref) : null
      const home = el.parentElement?.closest<HTMLElement>('.goal-card__children') ?? null
      return {
        el,
        top: at.top,
        bottom: at.top + el.offsetHeight,
        end: piece && pieceAt ? pieceAt.top + piece.offsetHeight : -Infinity,
        piece: piece && pieceAt ? {
          el: piece, top: pieceAt.top, bottom: pieceAt.top + piece.offsetHeight, left: pieceAt.left, right: pieceAt.left + piece.offsetWidth,
        } : null,
        left: at.left,
        right: at.left + el.offsetWidth,
        row: { top: rowTop, bottom: rowTop + (row?.offsetHeight ?? 0), left: rowLeft, right: rowLeft + (row?.offsetWidth ?? 0) },
        bound,
        shift: home && list ? Math.max(0, offsetIn(home, ref).left - firstList) : 0,
      }
    })
    if (!boxes.length) return null
    const style = getComputedStyle(boxes[0].el)
    const gap = parseFloat(style.getPropertyValue('--subgoal-gap')) || 1
    const lane = { left: boxes[0].left + (parseFloat(style.getPropertyValue('--goal-shape-inset')) || 0), right: boxes[0].right }
    return { boxes, end, gap, lane }
  }

  function write({ boxes: all, end, gap, lane }: Measured): void {
    all.forEach((box, i) => {
      if (box.bound) return
      const prev = all[i - 1]
      const next = all[i + 1]
      const top = prev ? (prev.bottom + box.top + gap) / 2 : box.top
      const bottom = next ? (box.bottom + next.top - gap) / 2 : Math.max(box.bottom, end)
      const shape = [box.row.top - top, bottom - box.row.bottom, box.row.left - lane.left - box.shift, lane.right - box.row.right]
        .map((px) => `${px.toFixed(2)}px`)
      // an open goal's colour runs on down its steps and notes to the end of its piece, drawn by its list from where the
      // row's shape stops
      const piece = box.piece
        ? [box.piece.top - bottom, Math.max(box.end, bottom) - box.piece.bottom, box.piece.left - lane.left - box.shift, lane.right - box.piece.right]
          .map((px) => `${px.toFixed(2)}px`)
        : null
      const key = piece ? `${shape.join()}|${piece.join()}` : shape.join()
      if (written.get(box.el) === key) return
      written.set(box.el, key)
      const style = box.el.style
      style.setProperty('--wash-t', shape[0])
      style.setProperty('--wash-b', shape[1])
      style.setProperty('--wash-l', shape[2])
      style.setProperty('--wash-r', shape[3])
      if (piece && box.piece) {
        const list = box.piece.el.style
        list.setProperty('--piece-t', piece[0])
        list.setProperty('--piece-b', piece[1])
        list.setProperty('--piece-l', piece[2])
        list.setProperty('--piece-r', piece[3])
      }
    })
  }

  const group: Group = { measure, write }
  function watchSize(el: HTMLElement | null, old?: HTMLElement | null): void {
    if (old) { sizes?.unobserve(old); owners.delete(old) }
    if (el) { owners.set(el, group); sizes?.observe(el) }
  }
  // Observing starts with a first report, which measures.
  onMounted(() => {
    groups.add(group)
    watchSize(options.card())
    watchSize(options.list.value)
  })
  watch(options.list, (list, old) => watchSize(list, old), { flush: 'post' }) // the list comes and goes with the subgoals
  watch(options.layoutSources, () => schedule(group), { flush: 'post' })
  onBeforeUnmount(() => {
    groups.delete(group)
    due.delete(group)
    watchSize(null, options.card())
    watchSize(null, options.list.value)
  })
}
