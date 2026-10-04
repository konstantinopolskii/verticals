/** Compact-board view state (COMPACT_BOARD_HANDOFF.md §3, §5 — KK rulings 2026-08-17, D244).
 *
 *  Session-only, client-only: which column is expanded and which card's family chain is hovered.
 *  Lifted out of `store.ts` unchanged for ARCHITECTURE.md §2's 750-line module rule (S-90a) —
 *  the same move `boardProjection.ts` records. Nothing here closes over store internals: every
 *  function mutates (or reads) the reactive state slice the store passes in, so reactivity and
 *  ownership stay the store's.
 */

import { ancestorIds, subtreeIds } from './boardIndex'
import { whenPointerRests } from './pointerRest'
import type { BoardResponse } from './api'

/** The slice of the store's `State` these helpers touch. `store.ts`'s own reactive `state`
 *  satisfies it structurally. */
export interface BoardViewState {
  board: BoardResponse | null
  expandedVertical: string | null
  hoverChainId: string | null
  restChainId: string | null
  /** Ids whose child lists are locally collapsed (S-67 nested view). Local view state only,
   *  never persisted — lists are expanded by default. Moved here from `store.ts` itself (S-90a,
   *  the module's own 750-line cap) alongside every other session-only board view toggle. */
  collapsed: string[]
}

// --- expand / collapse (nested subgoal lists) ---------------------------------------------------
//
// Local view state only — nothing is written and nothing is persisted across a reload. The two
// events this toggle stands for are named `vertical_expanded` and `vertical_collapsed`
// (`RESEARCH.md` §3's observed asset list, two of S-74's eight); the toggle button carries those
// names in `data-sound-event` so the scenario that wires audio has the hook and does not have to
// re-derive which gesture fires which asset. No audio is constructed here — that mechanism, and
// its eight assets, is S-74's own build.

export function isCollapsed(view: BoardViewState, id: string): boolean {
  return view.collapsed.includes(id)
}

export function toggleCollapsed(view: BoardViewState, id: string): void {
  const at = view.collapsed.indexOf(id)
  if (at === -1) view.collapsed.push(id)
  else view.collapsed.splice(at, 1)
}

/** Header click: expand this column, collapsing whichever was expanded; a second click on the
 *  expanded column returns the board to all-compact. */
export function toggleExpandedColumn(view: BoardViewState, vertical: string): void {
  view.expandedVertical = view.expandedVertical === vertical ? null : vertical
}

/** Card click and direct-URL opens land here: opening a card expands its column (one gesture,
 *  never a toggle — opening a second card in the same column must not collapse it). */
export function expandColumn(view: BoardViewState, vertical: string): void {
  view.expandedVertical = vertical
}

/** Clearing waits a beat; setting is instant. Without the grace, "click the swapped stack face"
 *  (COMPACT_BOARD_HANDOFF.md §5) is physically impossible: the pointer must LEAVE the hovered
 *  card to travel to the stack, that mouseleave would clear the chain, and the face would revert
 *  before the click lands. Any card entered during the window cancels the pending clear, so
 *  moving within the family keeps the swap and moving to an unrelated card retargets instantly.
 *
 *  The family light waits for the pointer to rest (KK, the board motion review of 3 Oct 2026), so a hand crossing the
 *  board no longer relights three columns on every card it passes. A rest is the hand slowing down on the card
 *  (`lib/pointerRest.ts`), not a fixed wait: a fixed 250 ms after entering made the light come late and trail the hand
 *  (KK, 4 Oct 2026). `restChainId` takes the card the moment the pointer settles on it, or HOVER_REST_MS after it
 *  entered when it keeps moving over it; leaving the card first calls it off. The card's own lift stays instant, and
 *  so does `hoverChainId`, which the carried box and the mascot read with rests of their own (`lib/carriedFilter.ts`).
 *
 *  The card under the hand answers first, on its own: it lifts in its own colour at once (goalCard.css), and the light
 *  the rest moves across the board follows once that frame is drawn. A hand already slowing as it reached a goal of
 *  another family rested in the same moment it entered, so the whole board's light swap was worked out in the card's
 *  own frame, and the card lit late and in one jump with everything else (KK, 4 Oct 2026, a recording: "immediately
 *  light the one that is hovered right now and decouple the animation of the others"). */
const HOVER_CLEAR_GRACE_MS = 250
const HOVER_REST_MS = 250
let hoverClearTimer: ReturnType<typeof setTimeout> | null = null
let hoverRestTimer: ReturnType<typeof setTimeout> | null = null
let hoverRestWatch: (() => void) | null = null
let restToken = 0 // a rest waiting for the card's frame, called off by any newer hover
/** Runs `fn` once the next frame has been drawn. */
function afterNextFrame(fn: () => void): void {
  if (typeof requestAnimationFrame !== 'function') { fn(); return }
  requestAnimationFrame(() => requestAnimationFrame(fn))
}

export function setHoverChain(view: BoardViewState, id: string | null): void {
  restToken++
  if (hoverClearTimer !== null) {
    clearTimeout(hoverClearTimer)
    hoverClearTimer = null
  }
  if (hoverRestTimer !== null) {
    clearTimeout(hoverRestTimer)
    hoverRestTimer = null
  }
  hoverRestWatch?.()
  hoverRestWatch = null
  if (id === null) {
    hoverClearTimer = setTimeout(() => {
      hoverClearTimer = null
      view.hoverChainId = null
      view.restChainId = null
    }, HOVER_CLEAR_GRACE_MS)
    return
  }
  view.hoverChainId = id
  if (view.restChainId === id) return
  const rest = (): void => {
    if (hoverRestTimer !== null) clearTimeout(hoverRestTimer)
    hoverRestTimer = null
    hoverRestWatch?.()
    hoverRestWatch = null
    const token = restToken
    afterNextFrame(() => { if (token === restToken && view.hoverChainId === id) view.restChainId = id })
  }
  hoverRestTimer = setTimeout(rest, HOVER_REST_MS)
  hoverRestWatch = whenPointerRests(rest)
}

/** A card's family line — itself, every ancestor, every descendant — as one id set. Pure
 *  client-side reads over the loaded board (HC-11). The store wraps these in a `computed`; called
 *  during evaluation, the reactive property reads below register the dependency tracking
 *  themselves. */
function chainOf(view: BoardViewState, id: string | null): { id: string; set: Set<string> } | null {
  if (!id || !view.board) return null
  const set = subtreeIds(view.board, id)
  for (const ancestor of ancestorIds(view.board, id)) set.add(ancestor)
  return { id, set }
}

/** The hovered card's family line, null when nothing is hovered: the carried box reads it. */
export function hoverChainOf(view: BoardViewState): { id: string; set: Set<string> } | null {
  return chainOf(view, view.hoverChainId)
}

/** The family line of the card the pointer rests on: `GoalCard.vue` binds the wash class off it. */
export function restChainOf(view: BoardViewState): { id: string; set: Set<string> } | null {
  return chainOf(view, view.restChainId)
}
