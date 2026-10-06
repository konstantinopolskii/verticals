// Pointer-drag geometry: hit-testing, group identity and the reorder patch it resolves to. Pure
// reads over the DOM (`hitTest`) and over one board payload (everything else) — no reactive state,
// no network, same "arithmetic lives here, writes live in store.ts" split `boardIndex.ts`'s own
// header already uses. Owner verdict this file exists to satisfy (`docs/PLANNER_DND.md`,
// KK's 2026-08-09 drag rulings, AC-220/S-145): whole-card-surface pointer drag, no HTML5
// `draggable`, no text-selection smear, a source ghost that stays in place, a live drop indicator,
// and within-column reorder-by-drag over the `after_id`/`position` PATCH fields
// `verticals/api/routes_goals.py::patch_goal` already serves (see `docs/PENDING_DOC_FIXES.md` rows
// 32/127/129 — the HTTP verb has existed since row 32; rows 127/129 are the UI gesture's own
// history, deleted once, rebuilt here).

import { findGoal, siblingIds } from './boardIndex'
import { idsInColumn, resolveReorderSlot, slotBesideCard, sourceSlot } from './dragSlots'
import type { BoardResponse } from './api'
import { destinationRect, SETTLE_GRACE_MS, settleDuration } from './dragSettle'

/** P-02/M1: desktop stays a click through exactly 5 CSS px and arms strictly beyond it. */
export const DRAG_THRESHOLD_PX = 5
export const DESKTOP_HOLD_MS = 200
export const DESKTOP_HOLD_TOLERANCE_PX = 10
export const TOUCH_HOLD_MS = 250
export const TOUCH_HOLD_TOLERANCE_PX = 5

export const AUTOSCROLL_TICK_MS = 10
export const AUTOSCROLL_EDGE_RATIO = 0.2
export const AUTOSCROLL_CROSS_AXIS_PX = 10
export const AUTOSCROLL_MAX_PX = 25

export { SETTLE_EASING, settleDuration } from './dragSettle'

export function exceedsThreshold(dx: number, dy: number): boolean {
  return Math.hypot(dx, dy) > DRAG_THRESHOLD_PX
}

/** `store.ts`'s own `state.drag` field shape (kept here so its per-field rationale sits beside
 *  the geometry it feeds). `pending` is set on `pointerdown`, before the threshold is crossed —
 *  a plain click never crosses it, so `pending` just clears on `pointerup` and the browser's own
 *  `click` fires normally. `id` is the *armed* source, set only once the threshold is crossed:
 *  `GoalCard.vue`'s ghost and `Board.vue`'s overlay both key off this, not `pending`. `x`/`y` is
 *  the live pointer position; `offsetX`/`offsetY` is where inside the card the pointer grabbed
 *  it (so the overlay stays glued under the cursor); `width`/`height` is the source card's own
 *  footprint at press time. `target` is `computeDropTarget`'s live answer, recomputed every armed
 *  `pointermove`. The drop indicator renders `slot`, not `target`. */
export interface DragState {
  pending: { id: string; x: number; y: number; pointerType: 'desktop' | 'touch' } | null
  id: string | null
  x: number
  y: number
  /** Sign of the last vertical move that wasn't zero: the flying card's leading edge picks the slot. */
  dirY: number
  offsetX: number
  offsetY: number
  /** The dragged ROW's box — the flying visual's geometry. */
  width: number
  height: number
  /** From the row's bottom to the bottom of its subtasks drawn under it: the family travels whole. */
  tailHeight: number
  /** Live ROW box under the current drop target. Board.vue measures the rendered row at the
   *  destination width. D245 (KK ruling 2026-08-18): the flying overlay itself no longer follows
   *  these — re-sizing it against the hover target mid-flight read as the card corrupting
   *  itself, so the overlay now holds `width`/`height` (its pickup size) for the whole gesture.
   *  `previewHeight` still drives Column.vue's drop-indicator height (the destination geometry
   *  legitimately belongs there); `previewWidth` is measured the same way but has no renderer
   *  left to consume it — kept rather than threading its removal through `setDragPreviewSize`
   *  for a value nothing currently needs pulled apart from its sibling. */
  previewWidth: number
  previewHeight: number
  /** The vacated CARD's box — the placeholder's geometry, and a different number: the row sits
   *  inset by the card's padding (6px each side, measured), so a placeholder built from `width`/
   *  `height` reserves 12px less than the card it replaced and every card below jumps up the
   *  moment you pick one up (owner, 2026-08-10: "стоит вытащить карточку через drag как
   *  пространство которое она занимала сократится на N пикселей"). Measured before the fix:
   *  card box 78, placeholder 66, siblings -12px on pick-up. The footprint a drag vacates must
   *  equal the footprint it occupied — nothing on the board may move until the pointer does. */
  slotWidth: number
  slotHeight: number
  slotInsetTop: number
  slotInsetRight: number
  slotInsetBottom: number
  slotInsetLeft: number
  sourceVertical: string | null
  sourcePeriodKey: string | null
  combineMode: boolean
  target: DropTarget
  /** Where the placeholder renders. Stays put while `target` is a combine, so the column does
   *  not reflow under a pointer that has not moved. */
  slot: ReorderTarget | null
  /** Destination ROW box. Live preview should already be here at pointer-up; these values keep
   *  release correct when a very fast pointer-up beats Board.vue's next-frame measurement. */
  settling:
    | {
        id: string
        left: number
        top: number
        width: number | null
        height: number | null
        duration: number
        cancelled: boolean
      }
    | null
}

let holdTimer: number | null = null
let settleTimer: number | null = null
let lastPointerHit: PointerHit | null = null
const rowRects = new Map<string, DOMRect>()

function captureRowRects(): void {
  rowRects.clear()
  for (const card of document.querySelectorAll<HTMLElement>('[data-goal-id]')) {
    const row = card.querySelector<HTMLElement>(':scope > .goal-card__row')
    if (card.dataset.goalId && row) rowRects.set(card.dataset.goalId, row.getBoundingClientRect())
  }
}

/** D246/D247: `lib/dragHover.ts`'s dwell/spring timers both reflow the board mid-gesture (a
 *  column resizes, a card's folded children render inline) — the row rects captured at press time
 *  go stale the instant either applies. Exported wrapper so the caller can force a fresh capture
 *  once its own render (and any width transition) has settled, without this module taking on any
 *  more timers than its existing hold/settle pair. */
export function recaptureRowRects(): void {
  captureRowRects()
}

function clearTimer(timer: number | null): void {
  if (timer !== null) window.clearTimeout(timer)
}

function clearPendingTimer(): void {
  clearTimer(holdTimer)
  holdTimer = null
}

function applyTarget(drag: DragState, target: DropTarget): void {
  drag.target = target
  if (target?.kind !== 'combine') drag.slot = target
}

/** The flying card's edge that leads the move, or its middle before it has moved: the slot switches when that edge
 *  passes a row's middle, so a tall card reorders as soon as it covers half a neighbour. */
function leadingEdgeY(drag: DragState): number {
  const top = drag.y - drag.offsetY
  const height = drag.height + drag.tailHeight
  return drag.dirY > 0 ? top + height : drag.dirY < 0 ? top : top + height / 2
}

function hitAt(drag: DragState): PointerHit {
  return hitTest(drag.x, drag.y, drag.id, leadingEdgeY(drag))
}

function retarget(drag: DragState, board: BoardResponse | null, hit: PointerHit): void {
  if (!drag.id) return
  applyTarget(drag, computeDropTarget(board, drag.id, drag.y, hit, drag.combineMode, drag.slot, leadingEdgeY(drag)))
}

function activateDrag(drag: DragState, board: BoardResponse | null): void {
  if (!drag.pending || drag.id) return
  drag.id = drag.pending.id
  lastPointerHit = hitAt(drag)
  retarget(drag, board, lastPointerHit)
  ;(document.activeElement as HTMLElement | null)?.blur()
  window.getSelection()?.removeAllRanges()
  clearPendingTimer()
}

/** `pointerdown` on a card row, before any threshold check — `store.ts::pointerDownCard`'s whole
 *  body. `drag` is the live `state.drag` object (Vue's `reactive()` tracks a plain mutation on it
 *  exactly the same whether the mutating code lives in this module or in `store.ts` itself — nothing
 *  here needs to be a component or live inside the reactive tree's own file to participate). `rect`
 *  is the card's `getBoundingClientRect()`, captured by the caller at press time (not re-read here
 *  — by the time a later move arms the drag the card may have re-rendered). */
export function armPointerDown(
  drag: DragState,
  board: BoardResponse | null,
  id: string,
  clientX: number,
  clientY: number,
  rect: DOMRect,
  pointerType: string,
  altKey = false,
): void {
  clearPendingTimer()
  clearTimer(settleTimer)
  settleTimer = null
  lastPointerHit = null
  drag.settling = null
  drag.target = null
  drag.slot = null
  const input = pointerType === 'touch' ? 'touch' : 'desktop'
  drag.pending = { id, x: clientX, y: clientY, pointerType: input }
  drag.x = clientX
  drag.y = clientY
  drag.dirY = 0
  drag.offsetX = clientX - rect.left
  drag.offsetY = clientY - rect.top
  drag.width = rect.width
  drag.height = rect.height
  drag.previewWidth = rect.width
  drag.previewHeight = rect.height
  // The placeholder reserves the CARD, not the row — see `slotWidth`'s own note on the state type.
  const cardBox = document
    .querySelector(`[data-goal-id="${CSS.escape(id)}"]`)
    ?.getBoundingClientRect()
  drag.slotWidth = cardBox?.width ?? rect.width
  drag.slotHeight = cardBox?.height ?? rect.height
  const card = document.querySelector<HTMLElement>(`[data-goal-id="${CSS.escape(id)}"]`)
  const cardStyle = card ? getComputedStyle(card) : null
  drag.slotInsetTop = parseFloat(cardStyle?.paddingTop ?? '') || 0
  drag.slotInsetRight = parseFloat(cardStyle?.paddingRight ?? '') || 0
  drag.slotInsetBottom = parseFloat(cardStyle?.paddingBottom ?? '') || 0
  drag.slotInsetLeft = parseFloat(cardStyle?.paddingLeft ?? '') || 0
  // A goal with subtasks drawn under it moves with them: its slot reserves the whole family, and the row sits at the
  // top of that slot.
  drag.tailHeight = 0
  const kids = card?.nextElementSibling
  if (card && cardBox && kids instanceof HTMLElement && kids.classList.contains('goal-card__children')) {
    const bottom = kids.getBoundingClientRect().bottom + (parseFloat(getComputedStyle(kids).marginBottom) || 0)
    drag.tailHeight = Math.max(0, bottom - rect.bottom)
    drag.slotHeight = bottom - cardBox.top
    drag.slotInsetBottom += bottom - cardBox.bottom
  }
  const source = findGoal(board, id)
  drag.sourceVertical = source?.vertical ?? 'maybe'
  drag.sourcePeriodKey = source?.vertical ? source.period_key : null
  drag.combineMode = altKey
  captureRowRects()
  const delay = input === 'touch' ? TOUCH_HOLD_MS : DESKTOP_HOLD_MS
  holdTimer = window.setTimeout(() => {
    const pending = drag.pending
    if (!pending) return
    const tolerance = input === 'touch' ? TOUCH_HOLD_TOLERANCE_PX : DESKTOP_HOLD_TOLERANCE_PX
    if (Math.hypot(drag.x - pending.x, drag.y - pending.y) <= tolerance) activateDrag(drag, board)
  }, delay)
}

/** Window-level `pointermove` — `store.ts::pointerMoveDrag`'s whole body. Arms past the 5px
 *  threshold (an unarmed `pending` is left alone so a plain click's `click` event still fires
 *  normally), then keeps `drag.x/y` and `drag.target` live via `hitTest` + `computeDropTarget`.
 *  Returns the same `PointerHit` it just fed `computeDropTarget`, or `null` while unarmed — D246/
 *  D247's dwell/spring timers (`lib/dragHover.ts`) read column/card identity off this return value
 *  rather than re-running `elementFromPoint` a second time per move. */
export function trackPointerMove(
  drag: DragState,
  board: BoardResponse | null,
  clientX: number,
  clientY: number,
  altKey = drag.combineMode,
): PointerHit | null {
  if (clientY !== drag.y) drag.dirY = Math.sign(clientY - drag.y)
  drag.x = clientX
  drag.y = clientY
  drag.combineMode = altKey
  if (!drag.id) {
    if (!drag.pending) return null
    const dx = clientX - drag.pending.x
    const dy = clientY - drag.pending.y
    if (drag.pending.pointerType === 'touch') {
      if (Math.hypot(dx, dy) > TOUCH_HOLD_TOLERANCE_PX) {
        drag.pending = null
        clearPendingTimer()
        lastPointerHit = null
        rowRects.clear()
      }
      return null
    }
    if (!exceedsThreshold(dx, dy)) return null
    activateDrag(drag, board)
  }
  if (!drag.id) return null
  lastPointerHit = hitAt(drag)
  retarget(drag, board, lastPointerHit)
  return lastPointerHit
}

/** Switch sortable/combine mode without requiring pointer movement. Reuse the last pointermove's
 *  hit: rendering its reorder footprint can start a FLIP animation before the modifier arrives,
 *  so re-running `elementFromPoint` here can observe a displaced sibling instead of the card the
 *  pointer actually entered. */
export function setCombineMode(
  drag: DragState,
  board: BoardResponse | null,
  enabled: boolean,
): void {
  drag.combineMode = enabled
  if (drag.id) {
    lastPointerHit ??= hitAt(drag)
    retarget(drag, board, lastPointerHit)
  }
}

function scrollSpeed(pointer: number, start: number, size: number, maxZone = Infinity): number {
  const zone = Math.min(size * AUTOSCROLL_EDGE_RATIO, maxZone)
  if (pointer >= start && pointer < start + zone) {
    return -AUTOSCROLL_MAX_PX * ((start + zone - pointer) / zone)
  }
  const end = start + size
  if (pointer <= end && pointer > end - zone) {
    return AUTOSCROLL_MAX_PX * ((pointer - (end - zone)) / zone)
  }
  return 0
}

/** P-02/M4: scroll every board ancestor whose axis edge contains the live pointer. */
export function autoScrollAtPointer(drag: DragState): boolean {
  if (!drag.id) return false
  let moved = false
  const candidates = document.querySelectorAll<HTMLElement>(
    '.pattern-vertical-board, .pattern-vertical-board__column',
  )
  for (const el of candidates) {
    const rect = el.getBoundingClientRect()
    const canX = el.scrollWidth > el.clientWidth
    const canY = el.scrollHeight > el.clientHeight
    const inHorizontalCrossAxis = drag.y >= rect.top - AUTOSCROLL_CROSS_AXIS_PX
      && drag.y <= rect.bottom + AUTOSCROLL_CROSS_AXIS_PX
    const inVerticalCrossAxis = drag.x >= rect.left - AUTOSCROLL_CROSS_AXIS_PX
      && drag.x <= rect.right + AUTOSCROLL_CROSS_AXIS_PX
    // Our 1200px viewport has one 400px active column plus 225px standard columns. An uncapped
    // 20% horizontal zone is 240px and therefore reaches 15px into the next complete column;
    // the incumbent's 1130px viewport makes the same 20% zone one standard column wide. Keep
    // M10's 20% law, but clamp this cross-column expansion to one rendered column so hovering
    // the recorded adjacent slot does not start unrelated horizontal movement.
    const columnWidths = el.matches('.pattern-vertical-board')
      ? [...el.querySelectorAll<HTMLElement>(':scope > .pattern-vertical-board__column')]
          .map((column) => column.getBoundingClientRect().width)
          .filter((width) => width > 0)
      : []
    const horizontalZoneMax = columnWidths.length ? Math.min(...columnWidths) : Infinity
    const dx = canX && inHorizontalCrossAxis
      ? scrollSpeed(drag.x, rect.left, rect.width, horizontalZoneMax)
      : 0
    const dy = canY && inVerticalCrossAxis ? scrollSpeed(drag.y, rect.top, rect.height) : 0
    if (dx !== 0 || dy !== 0) {
      const oldLeft = el.scrollLeft
      const oldTop = el.scrollTop
      el.scrollBy(dx, dy)
      const movedX = el.scrollLeft - oldLeft
      const movedY = el.scrollTop - oldTop
      moved ||= movedX !== 0 || movedY !== 0
      if (movedX !== 0 || movedY !== 0) {
        for (const card of el.querySelectorAll<HTMLElement>('[data-goal-id]')) {
          const id = card.dataset.goalId
          const rect = id ? rowRects.get(id) : null
          if (id && rect) {
            rowRects.set(id, new DOMRect(rect.x - movedX, rect.y - movedY, rect.width, rect.height))
          }
        }
      }
    }
  }
  return moved
}

/** Clear input state, animate overlay to drop/cancel destination, then keep 50 ms cleanup grace. */
export function releasePointerDrag(
  drag: DragState,
  cancelled = false,
): { id: string; target: DropTarget } | null {
  clearPendingTimer()
  lastPointerHit = null
  const id = drag.id
  const target = cancelled ? null : drag.target
  drag.pending = null
  drag.combineMode = false
  if (!id) {
    drag.target = null
    drag.slot = null
    rowRects.clear()
    return null
  }

  const fromLeft = drag.x - drag.offsetX
  const fromTop = drag.y - drag.offsetY
  const rect = destinationRect(id, target)
  const left = rect?.left ?? fromLeft
  const top = rect?.top ?? fromTop
  // A cancel returns the card to its own row, where its current size is already correct; only a
  // real drop has a destination box worth growing or shrinking into.
  const width = !cancelled && rect ? rect.width : null
  const height = !cancelled && rect ? rect.height : null
  const distance = rect ? Math.hypot(left - fromLeft, top - fromTop) : null
  const duration = settleDuration(distance)
  const settling = { id, left, top, width, height, duration, cancelled }
  // ORDER IS LOAD-BEARING: settling first, then clear the id. `Board.vue`'s flying-card identity
  // is `drag.id ?? drag.settling?.id`, so clearing the id first makes that value blink through
  // `null` for one tick — which unmounts the overlay and re-clones the row from a source that is
  // ALREADY ghosted, baking `visibility: hidden` into the copy. The card then "flies" invisibly
  // and pops back at the end of the settle (owner report 2026-08-10: "ours blinks: the one u
  // dragged disappears and then reappears in the column").
  drag.settling = settling
  drag.target = target
  drag.slot = target?.kind === 'reorder' ? target : null
  drag.id = null
  rowRects.clear()
  clearTimer(settleTimer)
  settleTimer = window.setTimeout(() => {
    drag.settling = null
    drag.target = null
    drag.slot = null
    settleTimer = null
  }, duration + SETTLE_GRACE_MS)
  return { id, target }
}

// --- hit-testing -----------------------------------------------------------------------------
//
// Reads live row boxes, i.e. what the user sees. Two rules keep a live read from feeding back into
// itself: the indicator under the pointer keeps its slot, and a combine never moves the placeholder.

const LIVE_SLIDE = '[data-role="period-slide"]:not([data-state="outgoing"])'

export interface PointerHit {
  /** Rendered row nearest the flying card's leading edge in the hovered column; never the drag source. */
  cardId: string | null
  cardRect: DOMRect | null
  /** Rendered row right under the pointer, never the drag source: the one a drop would go into. */
  underId: string | null
  underRect: DOMRect | null
  /** Card ids rendered after `cardId` in its container, in DOM order. */
  followingIds: string[]
  /** `cardId`'s own subtasks drawn right under it, in DOM order: the slot just past its row is before the first. */
  childIds: string[]
  columnVertical: string | null
  columnPeriodKey: string | null
  overIndicator: boolean
  /** The pointer is nearest the source's own box: a nested hole, or the card before it collapses. */
  overSource: boolean
}

function childCardIds(card: HTMLElement): string[] {
  const list = card.nextElementSibling
  if (!list?.classList.contains('goal-card__children')) return []
  return [...list.children].flatMap((el) => (el as HTMLElement).dataset?.goalId ?? [])
}

function followingCardIds(card: HTMLElement): string[] {
  const ids: string[] = []
  for (let el = card.nextElementSibling; el; el = el.nextElementSibling) {
    const id = (el as HTMLElement).dataset?.goalId
    if (id) ids.push(id)
  }
  return ids
}

export function hitTest(x: number, y: number, sourceId: string | null = null, edgeY = y): PointerHit {
  const el = document.elementFromPoint(x, y) as HTMLElement | null
  const colEl = el?.closest<HTMLElement>('[data-vertical]') ?? null
  const hit: PointerHit = {
    cardId: null,
    cardRect: null,
    underId: null,
    underRect: null,
    followingIds: [],
    childIds: [],
    columnVertical: colEl?.dataset.vertical ?? null,
    columnPeriodKey: colEl?.dataset.periodKey ? colEl.dataset.periodKey : null,
    overIndicator: false,
    overSource: false,
  }
  if (!colEl) return hit

  // Carried goals are a computed pile, never a drop/reorder destination (their group, S4.P2).
  const group = colEl.querySelector<HTMLElement>(`${LIVE_SLIDE} [data-role="carried-group"]`)?.getBoundingClientRect()
  if (group && y >= group.top && y <= group.bottom) {
    hit.columnVertical = null
    hit.columnPeriodKey = null
    return hit
  }

  // Nearest of the indicator and every row, so no gap between them is left unowned.
  const distance = (rect: DOMRect) => (edgeY < rect.top ? rect.top - edgeY : edgeY > rect.bottom ? edgeY - rect.bottom : 0)
  let best: { card: HTMLElement | null; rect: DOMRect; distance: number } | null = null
  const indicator = colEl.querySelector<HTMLElement>(`${LIVE_SLIDE} [data-role="drop-indicator"]`)
  if (indicator) {
    const rect = indicator.getBoundingClientRect()
    best = { card: null, rect, distance: distance(rect) }
  }
  const rows = colEl.querySelectorAll<HTMLElement>(`${LIVE_SLIDE} [data-goal-id] > .goal-card__row`)
  for (const row of rows) {
    if (row.closest('[data-section="carried"], .goal-card__children--drag-source')) continue
    const card = row.parentElement as HTMLElement
    const rect = (card.dataset.goalId === sourceId ? card : row).getBoundingClientRect()
    if (rect.height <= 0) continue
    if (card.dataset.goalId !== sourceId && y >= rect.top && y <= rect.bottom) {
      hit.underId = card.dataset.goalId ?? null
      hit.underRect = rect
    }
    const d = distance(rect)
    if (!best || d < best.distance) best = { card, rect, distance: d }
  }
  if (!best) return hit
  if (!best.card) {
    hit.overIndicator = true
    return hit
  }
  hit.followingIds = followingCardIds(best.card)
  if (best.card.dataset.goalId === sourceId) {
    hit.overSource = true
    return hit
  }
  hit.cardId = best.card.dataset.goalId ?? null
  hit.cardRect = best.rect
  hit.childIds = childCardIds(best.card)
  return hit
}

// --- drop target ---------------------------------------------------------------------------------

export type DropTarget =
  | {
      kind: 'reorder'
      /** The id this drop would insert the dragged goal immediately before, or `null` to append
       *  after every existing member of the RESOLVED group (`parentId` below) — drop below the
       *  last card of that group, or into an empty column/group. Column.vue and GoalCard.vue read
       *  this to place the drop-indicator rectangle; `reorderWrite` below reads it to build the
       *  actual PATCH body. */
      insertBeforeId: string | null
      /** The target group's own column identity — `'maybe'` for the Inbox/root pile, a real
       *  scale name otherwise — so `Column.vue` can tell "is this reorder aimed at me" without
       *  re-deriving group membership itself (`props.vertical`/`props.periodKey` already carry
       *  the same two values `toColumnData` built this column from). */
      vertical: string
      periodKey: string | null
      /** D249 (KK, 2026-08-19): the resolved slot's own group owner — `null` for the column's own
       *  top level, a goal id for a rendered nested group. Decided HERE, at resolution time, by
       *  `lib/dragSlots.ts::resolveReorderSlot` — never re-inferred later from `insertBeforeId`
       *  the way the deleted `slotParentId` used to. That inference's own law ("an append slot is
       *  always top-level") is REPEALED: the N+1 positions of a rendered nested group, append
       *  included, are first-class targets now. `dragActions.ts::pointerUpDrag` reads this field
       *  directly to decide what a drop means (adopt / detach / plain reorder). */
      parentId: string | null
    }
  | {
      kind: 'combine'
      targetId: string
    }
  | null

export type ReorderTarget = Extract<DropTarget, { kind: 'reorder' }>

export function computeDropTarget(
  board: BoardResponse | null,
  sourceId: string,
  pointerY: number,
  hit: PointerHit,
  combineMode = false,
  currentSlot: ReorderTarget | null = null,
  edgeY = pointerY,
): DropTarget {
  if (!findGoal(board, sourceId)) return null

  // Into a goal is read off the row under the pointer, before the slot: the leading edge can already sit over the
  // indicator while the pointer is in a card's middle.
  //
  // D236 (KK, 2026-08-15): combine no longer hides behind the Alt key. The pointer's position on
  // the hit card disambiguates the two meanings a modifier used to: the middle band reads "into
  // this parent", the outer bands keep their reorder-slot meaning. `combineMode` (Alt) still
  // forces combine across the whole card, unchanged.
  //
  // D249 refinement: when the hit card is a SIBLING of the source in the same rendered group
  // (same parent, both nested), the centre band narrows from 50% to 25% of the row's height (the
  // outer reorder bands widen to 37.5% each side) — a few px of drift between two small subtask
  // rows used to read as "nest under this sibling" far too easily now that reordering among them
  // is a real, expected gesture. Every other hit keeps D236's original 50/25/25 split unchanged.
  if (dragCombineTarget(board, sourceId, hit)) {
    const rect = hit.underRect as DOMRect
    const source = findGoal(board, sourceId)
    const hitGoal = findGoal(board, hit.underId as string)
    const isRenderedSibling = !!source && !!hitGoal
      && source.parent_id !== null
      && source.parent_id === hitGoal.parent_id
    const bandFraction = isRenderedSibling ? 0.375 : 0.25
    const inCentreBand = pointerY >= rect.top + rect.height * bandFraction
      && pointerY <= rect.bottom - rect.height * bandFraction
    if (combineMode || inCentreBand) {
      return { kind: 'combine', targetId: hit.underId as string }
    }
  }

  // The indicator under the leading edge keeps its slot.
  if (hit.overIndicator && currentSlot) return currentSlot
  if (hit.overSource && hit.columnVertical) {
    const slot = sourceSlot(board, sourceId, hit.columnVertical, hit.columnPeriodKey, hit.followingIds)
    if (slot) {
      return { kind: 'reorder', ...slot, vertical: hit.columnVertical, periodKey: hit.columnPeriodKey }
    }
  }

  // Leading edge past a row's middle: slot below it, before it: slot above it.
  if (hit.cardId && hit.cardRect && hit.columnVertical) {
    const after = edgeY >= hit.cardRect.top + hit.cardRect.height / 2
    const slot = slotBesideCard(
      board, sourceId, hit.columnVertical, hit.columnPeriodKey, hit.cardId, after, hit.followingIds, hit.childIds,
    )
    if (slot) {
      return { kind: 'reorder', ...slot, vertical: hit.columnVertical, periodKey: hit.columnPeriodKey }
    }
  }

  // Empty column, or a row that is no valid anchor: fall back to press-time geometry.
  if (hit.columnVertical) {
    const slot = resolveReorderSlot(
      board, sourceId, hit.columnVertical, hit.columnPeriodKey, edgeY, rowRects,
    )
    return {
      kind: 'reorder',
      insertBeforeId: slot.insertBeforeId,
      vertical: hit.columnVertical,
      periodKey: hit.columnPeriodKey,
      parentId: slot.parentId,
    }
  }

  return null
}

function dragCombineTarget(
  board: BoardResponse | null,
  sourceId: string,
  hit: PointerHit,
): boolean {
  const source = findGoal(board, sourceId)
  return !!(
    source
    && hit.underId
    && hit.underRect
    && hit.underId !== sourceId
    && hit.underId !== source.parent_id
    && findGoal(board, hit.underId)
  )
}

/** The ordered slot a CROSS-column drop asks for, in the destination column's own vocabulary.
 *  `null` means "no ordering field" — append, which is what a bare schedule write already does,
 *  so the drop stays one request either way. A drop released below every card, or over a slot we
 *  can no longer resolve, is exactly that case. */
export function scheduleOrdering(
  board: BoardResponse | null,
  sourceId: string,
  target: { insertBeforeId: string | null; vertical: string; periodKey: string | null },
): { after_id: string } | { position: 'first' } | null {
  if (target.insertBeforeId === null) return null
  const siblings = idsInColumn(board, target.vertical, target.periodKey)
    .filter((id) => id !== sourceId)
  const index = siblings.indexOf(target.insertBeforeId)
  if (index === -1) return null
  // Carryover ghosts render here but belong to their old period; the server refuses them as after_id.
  const before = siblings.slice(0, index)
    .filter((id) => findGoal(board, id)?.period_key === target.periodKey)
  return before.length ? { after_id: before[before.length - 1] } : { position: 'first' }
}

// --- reorder write ---------------------------------------------------------------------------

export interface ReorderPatch {
  after_id?: string
  position?: 'first'
}

/** Builds the PATCH body for a `{kind: 'reorder'}` target, or returns `null` when the drop would
 *  not change anything — docs/PLANNER_DND.md §6's no-op rule ("picking a card up and putting
 *  it back exactly where it was... does not sync"), reimplemented over `after_id`/`position`
 *  instead of the incumbent's own `(droppableId, index)` pair since that is the vocabulary our
 *  wire actually has. Compares the *current* adjacent-predecessor id against the one the drop
 *  would produce; identical means the drop landed back where the drag started. */
export function reorderWrite(
  board: BoardResponse | null,
  sourceId: string,
  target: { insertBeforeId: string | null },
): { patch: ReorderPatch } | null {
  const source = findGoal(board, sourceId)
  if (!source) return null
  // The rendered group is wider than the POSITION group the server reorders within: a carryover
  // ghost renders in today's column while its `period_key` stays the old period's, and naming it
  // as `after_id` gets a 422 ("not a sibling"). Filter to the source's own `(vertical, period_key)`
  // — for a nested-idea group this same filter also reproduces the server's `vertical IS NULL` cut.
  // The server orders this group by position; the wire order bands it by value.
  const full = siblingIds(board, sourceId)
    .map((id) => findGoal(board, id))
    .filter((g): g is NonNullable<typeof g> => !!g && g.vertical === source.vertical
      && (g.period_key ?? null) === (source.period_key ?? null))
    .sort((a, b) => a.position - b.position || a.id.localeCompare(b.id))
    .map((g) => g.id)
  const filtered = full.filter((id) => id !== sourceId)
  if (filtered.length === 0) return null // only member of its own group: nowhere to move to

  const desiredAfterId =
    target.insertBeforeId === null
      ? filtered[filtered.length - 1]
      : (filtered[filtered.indexOf(target.insertBeforeId) - 1] ?? null)

  const idx = full.indexOf(sourceId)
  const currentAfterId = idx > 0 ? full[idx - 1] : null

  if (desiredAfterId === currentAfterId) return null
  return desiredAfterId === null ? { patch: { position: 'first' } } : { patch: { after_id: desiredAfterId } }
}
