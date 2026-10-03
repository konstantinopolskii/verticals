// Flow 4 · going deeper (KK agreed the bold marker sketches on 28 Sep 2026, light A: "Good.", then "Accepted.").
//
// You open a goal, step into one of its steps, and into that step's step. The wide column stands on one edge: the
// levels you stepped through as step-size lines on top ("the parent of this subgoal should be size of a subgoal (so
// it will work as breadcrumb)", 27 Sep), the open goal as the one big card, its siblings under it and the siblings of
// the level above under them ("siblings always below", 28 Sep). Two levels in is the deepest ("from the second level
// I believe we simply can't open the third level for now, because it's too much of a levels").
//
// The open goal is a sun ("Like it's sun, and it's sunlights are covering rest"): its family keeps its light wherever
// it sits on the board, one step less for every level further away and never none (29 Sep: "make the last step not fully
// transparent"), and the rest of the board turns off, half grey and faded ("we might actually to grayscale and make more
// transparent the other goals on vertical"; 29 Sep: "like 50%, not 100%"). Grey and faded means only "not related".
// Pointing at a turned-off goal swaps the two: the family turns off and the pointed goal lights its chain as hover does
// today ("if you hove the turned off goals, the active cards should grayscale and get same transparency, but the
// hovered should have the lighting get back on track"). Nothing changes while nothing is open ("Don't change the
// default way we right now light stuff on verticals please!!! No dim when nothing is opened").
//
// The path is the one state behind all of it: a click on any goal drawn in the wide column opens the chain it is
// drawn under plus itself, so a step in the card goes one level in, a sibling goes sideways, a line on top goes back
// to its level, and the same rule serves a drag held over a goal (flow 2 reuses it).

import { computed, nextTick, watch, type ComputedRef } from 'vue'
import type { BoardResponse } from './api'
import { ancestorIds, findGoal, subtreeIds } from './boardIndex'
import { columnPlace, moveColumns, moveFamily, scrollBack, type ColumnPlace } from './familyMotion'
import { reducedMotion } from './motion'

/** Full: the open goal and its parent. Light: one level away. Faint: two. Far: related, further away. A goal the map
 *  leaves out is turned off, so the rest of the board needs no light of its own. */
export type Light = 'full' | 'light' | 'faint' | 'far'

/** Vue settles a change and the open card's notes in a few ticks, all before the next frame is drawn. */
async function settled(): Promise<void> {
  for (let i = 0; i < 5; i++) await nextTick()
}

/** A goal, one level in, two levels in: the deepest. */
export const DEEPEST = 3

/** What stays on while a goal is open, with its light: the goal's parents up to the top, all its steps, and the
 *  siblings at each level stepped through. Light falls off by distance in the tree: the parent keeps the open goal's
 *  full light (KK: "The one level up should be same green as opened card"), one level away is light, two faint, and
 *  further on the farthest tint. Anything absent from the map is turned off. */
export function familyLight(board: BoardResponse | null, path: readonly string[]): Map<string, Light> | null {
  if (!board || !path.length) return null
  const sun = path[path.length - 1]
  const distance = new Map<string, number>()
  const reach = (id: string, d: number): void => {
    const was = distance.get(id)
    if (was === undefined || d < was) distance.set(id, d)
  }
  reach(sun, 0)
  const parents = ancestorIds(board, sun)
  parents.forEach((id, i) => reach(id, i + 1))
  let level = [sun]
  for (let d = 1; level.length; d += 1) {
    const next: string[] = []
    for (const id of level) {
      for (const kid of board.children[id] ?? []) {
        if (distance.has(kid.id)) continue
        reach(kid.id, d)
        next.push(kid.id)
      }
    }
    level = next
  }
  const last = path.length - 1
  path.forEach((id, i) => {
    const parent = findGoal(board, id)?.parent_id
    if (!parent) return
    for (const sibling of board.children[parent] ?? []) if (sibling.id !== id) reach(sibling.id, last - i + 2)
  })
  const light = new Map<string, Light>()
  for (const [id, d] of distance) {
    light.set(id, d === 0 || id === parents[0] ? 'full' : d === 1 ? 'light' : d === 2 ? 'faint' : 'far')
  }
  return light
}

/* The tints in between, found from each area's own colour (KK, 29 Sep 2026: "automatically determine those mid-scale
   colours and make the last step not fully transparent"). Full is the area's tuned colour and light the hover's tint,
   both KK's. The farthest level keeps a tint that still reads as the area's colour at a glance: a fixed distance from
   white, the dev Layout panel's "Farthest tint" (OKLab ΔE × 100, 3), or half of light's where light is weaker than
   twice that, as in blue and orange. Faint falls halfway between light and it. A level is the share of the area's
   colour the highlight layer shows: faint .49-.53 and farthest .28-.35 with KK's tuned palette, where they were .4
   and none. */
function oklab(rgb: readonly number[]): readonly number[] {
  const [r, g, b] = rgb.map((v) => (v / 255 <= 0.04045 ? v / 255 / 12.92 : ((v / 255 + 0.055) / 1.055) ** 2.4))
  const l = Math.cbrt(0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b)
  const m = Math.cbrt(0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b)
  const s = Math.cbrt(0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b)
  return [0.2104542553 * l + 0.793617785 * m - 0.0040720468 * s, 1.9779984951 * l - 2.428592205 * m + 0.4505937099 * s,
    0.0259040371 * l + 0.7827717662 * m - 0.808675766 * s]
}
const WHITE = oklab([255, 255, 255])
/** How far from white the colour at `alpha` reads, laid over white the way the board draws it. */
function fromWhite(rgb: readonly number[], alpha: number): number {
  const [L, a, b] = oklab(rgb.map((v) => 255 + (v - 255) * alpha))
  return 100 * Math.hypot(L - WHITE[0], a - WHITE[1], b - WHITE[2])
}
/** The share of the area's colour that reads `distance` from white (it grows with the share: halve the interval). */
function shareAt(rgb: readonly number[], alpha: number, distance: number): number {
  let lo = 0
  let hi = 1
  for (let i = 0; i < 24; i++) {
    const mid = (lo + hi) / 2
    if (fromWhite(rgb, alpha * mid) < distance) lo = mid
    else hi = mid
  }
  return Math.round(((lo + hi) / 2) * 1000) / 1000
}
const tints = new Map<string, { faint: number; far: number }>()
export function levelTints(rgb: readonly number[], alpha: number, lightShare: number, farDistance: number): { faint: number; far: number } {
  const key = `${rgb.join(',')}/${alpha}/${lightShare}/${farDistance}`
  let found = tints.get(key)
  if (!found) {
    const light = fromWhite(rgb, alpha * lightShare)
    const far = Math.min(farDistance, light / 2)
    found = { faint: shareAt(rgb, alpha, (light + far) / 2), far: shareAt(rgb, alpha, far) }
    tints.set(key, found)
  }
  return found
}

/** Pointing at a turned-off goal while a goal is open: it and its chain (ancestors up, steps down) light as hover does
 *  today, and everything else, the open family too, is off. */
function swappedLight(board: BoardResponse, id: string): Map<string, Light> {
  const light = new Map<string, Light>()
  for (const member of subtreeIds(board, id)) light.set(member, 'light')
  for (const member of ancestorIds(board, id)) light.set(member, 'light')
  return light
}

interface FamilyState {
  board: BoardResponse | null
  activeView: 'verticals' | 'inbox' | 'docs'
  openPath: string[]
  openGoalId: string | null
  openGoalVertical: string | null
  expandedVertical: string | null
  /** The goal the pointer rests on: a light swaps only to a goal the hand stops at (lib/boardViewState.ts). */
  restChainId: string | null
  /** The light is swapping under the pointer: it moves in 150 ms instead of the opening's time. */
  lightFast: boolean
  drag: { id: string | null }
}

export function createFamilyView(
  state: FamilyState,
  deps: {
    openGoal: (id: string, vertical: string | null, hostKey: string | null, path: string[]) => Promise<void>
    closeGoal: () => void
    ensureDetail: (id: string) => Promise<void>
  },
) {
  const family = computed(() => (
    state.activeView === 'verticals' && state.openGoalId !== null ? familyLight(state.board, state.openPath) : null
  ))
  /** The open goal's ancestors and its subtree (itself included), found once for every card to look itself up in: each
   *  card walking the board on its own took 13 ms of the first opening (profiled 29 Sep 2026). */
  const openRelatives = computed(() => {
    const id = state.openGoalId
    if (id === null || !state.board) return null
    return { id, ancestors: new Set(ancestorIds(state.board, id)), subtree: subtreeIds(state.board, id) }
  })
  /** The pointer rests on a turned-off goal. */
  const swapped = computed(() => {
    const rest = state.restChainId
    return family.value !== null && rest !== null && !family.value.has(rest) && !!findGoal(state.board, rest)
  })
  const light: ComputedRef<Map<string, Light> | null> = computed(() => (
    swapped.value && state.board && state.restChainId ? swappedLight(state.board, state.restChainId) : family.value
  ))
  watch(swapped, () => { state.lightFast = true }, { flush: 'sync' })
  watch(() => state.openPath, () => { state.lightFast = false }, { flush: 'sync' })

  /** The rendered host of level `i` in a column: `GoalCard.vue`'s `detailHostKey` for the card drawn there. */
  function hostKey(vertical: string, path: readonly string[], i: number): string {
    const parent = i === 0 ? (findGoal(state.board, path[0])?.parent_id ?? null) : path[i - 1]
    return [vertical, parent ?? 'root', i, path[i]].join(':')
  }

  /** Where each column stood before a goal opened in it, held by the goal clicked. */
  const restPlace = new Map<string, ColumnPlace>()
  // However its goal goes, closed or opened elsewhere, the column scrolls back there.
  watch(() => state.openGoalVertical, (now, was) => {
    const place = was === null || now === was ? undefined : restPlace.get(was)
    if (!place || was === null) return
    restPlace.delete(was)
    scrollBack(place)
  }, { flush: 'post' })

  /** Open `path` in `vertical`'s column: the column widens, the last goal is the card, the ones before it are the lines
   *  above it. Deeper than two levels in, nothing opens. A goal opens in its own column; the column that had the open
   *  goal narrows and goes back to where it stood before (KK, 29 Sep 2026: "It opens where it's are. Your current
   *  opened column collapses and goes back to the regular state"). */
  function openFamily(path: string[], vertical: string): Promise<void> {
    if (!path.length || path.length > DEEPEST) return Promise.resolve()
    if (state.openGoalId === null || state.openGoalVertical !== vertical) {
      const place = columnPlace(vertical, path.join('/'))
      if (place) restPlace.set(vertical, place)
    }
    const id = path[path.length - 1]
    const open = () => {
      if (vertical !== 'maybe') state.expandedVertical = vertical
      void deps.openGoal(id, vertical, hostKey(vertical, path, path.length - 1), path)
    }
    // Every opening is one movement (lib/familyMotion.ts): a change inside the wide column moves that column, and a goal
    // opened in another column moves the wide column there. The move reads where everything ends up once the card's notes
    // are laid out: they fold after a few ticks, never a frame. Opened by a held drag, the goal stays under the hand; a
    // drag that opens a goal in another column keeps it pinned there (lib/dragActions.ts). With motion reduced, nothing
    // moves, so a first opening or a goal in another column opens at once and its card holds it where it was clicked
    // (lib/cardFamily.ts).
    const from = state.openGoalId
    const moves = !reducedMotion()
    if (state.expandedVertical === vertical && (from === null ? moves : state.openGoalVertical === vertical)) {
      const anchor = state.drag.id !== null ? path.join('/') : undefined
      return deps.ensureDetail(id).then(() => moveFamily(vertical, [from, id], open, settled, anchor))
    }
    if (vertical !== 'maybe' && state.drag.id === null && moves) {
      return deps.ensureDetail(id).then(() => moveColumns(vertical, [from, id], open, settled))
    }
    open()
    return Promise.resolve()
  }

  /** Close the open family (Esc at the first level, a press on the empty board), moving its column back. */
  function closeFamily(): void {
    const vertical = state.openGoalVertical
    if (state.openGoalId === null) return
    if (vertical && state.expandedVertical === vertical) void moveFamily(vertical, [state.openGoalId], deps.closeGoal, settled)
    else deps.closeGoal()
  }

  /** Back to level `i` (a click on a line on top). */
  function goToLevel(i: number): Promise<void> {
    const vertical = state.openGoalVertical
    if (!vertical || i < 0 || i >= state.openPath.length) return Promise.resolve()
    return openFamily(state.openPath.slice(0, i + 1), vertical)
  }

  /** Esc: up one level; at the first level, close. */
  function goUp(): void {
    if (state.openPath.length > 1) void goToLevel(state.openPath.length - 2)
    else closeFamily()
  }

  return { familyLight: light, familySwapped: swapped, openRelatives, openFamily, closeFamily, goToLevel, goUp }
}
