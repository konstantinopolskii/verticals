// D249 (KK, 2026-08-19): group-aware reorder-slot resolution — lifted out of `lib/drag.ts` when
// this logic would have pushed that module past ARCHITECTURE.md §2's 750-line cap (the same seam
// `lib/dragHover.ts`/`lib/boardEpoch.ts` already use). `drag.ts` stays hit-testing, combine-band
// geometry and the write/patch arithmetic; this file answers exactly one question —
// "given a column and a pointer Y, which slot (and whose group) does this drop resolve to" — as a
// pure function of the board payload, the column identity and a snapshot of press-time row rects.
//
// Root cause this file exists to fix (task brief, KK 2026-08-19): `drag.ts::computeDropTarget`
// used to resolve a reorder slot against the column's own FLAT top-level list only
// (`idsInColumn`), then re-INFER which group the resolved `insertBeforeId` belonged to
// AFTER THE FACT (the deleted `slotParentId`). An append slot (`insertBeforeId: null`, below
// every card in the render group) was declared "always top-level" by that inference — so hovering
// below the LAST member of a rendered nested group had nowhere to land inside that group; the
// slot resolved top-level instead and a drop there detached the card. This module resolves group
// membership FIRST, at the same time as the position, so an append slot can belong to any rendered
// group, not only the column's own top level.
//
// A "rendered nested group" is a card `P` with at least one same-vertical, same-column child that
// is actually in the DOM right now (has a press-time row rect) — exactly the set `GoalCard.vue`'s
// own `showChildren` gate renders inline (D244 expanded column, D247 spring-open, D248 open card
// all satisfy it the same way: the child has a live row). Group membership itself comes from
// `board.children[P.id]`, filtered by the exact predicate `boardProjection.ts::toCardData` nests
// children by (same vertical, both column members) — the one true definition of "P's rendered
// family in this column", never re-derived differently here.

import { findGoal, subtreeIds } from './boardIndex'
import type { BoardResponse } from './api'

/** The ordered ids of one column's own full member set — every top-level card AND every nested
 *  same-vertical child the wire lists for that column (`core/board.py`'s per-column SQL branch
 *  admits both independently; `boardProjection.ts::toColumnData` is what filters this down to a
 *  top-level-only render list, downstream of this raw wire read). Membership only — callers that
 *  need visual order read live row rects instead (position-sequence numbering is scoped per
 *  parent, not globally comparable across a mixed top-level/nested set — see this file's header). */
export function idsInColumn(
  board: BoardResponse | null,
  vertical: string,
  periodKey: string | null,
): string[] {
  const wireVertical = vertical === 'maybe' ? null : vertical
  return board?.columns.find(
    (column) => column.vertical === wireVertical && column.period_key === periodKey,
  )?.goals.map((goal) => goal.id) ?? []
}

/** D241's own nesting predicate (`boardProjection.ts::toColumnData`'s dedup filter), read the
 *  other way round: true when `id` renders as a TOP-LEVEL card in this column — no parent, or a
 *  parent on a different vertical, or a parent that is not itself a member of this column. */
function isTopLevelInColumn(
  board: BoardResponse | null,
  columnIds: ReadonlySet<string>,
  id: string,
): boolean {
  const goal = findGoal(board, id)
  if (!goal) return false
  if (!goal.parent_id) return true
  const parent = findGoal(board, goal.parent_id)
  return !parent || parent.vertical !== goal.vertical || !columnIds.has(parent.id)
}

/** `parent`'s own same-vertical, same-column children, in `board.children`'s own order — the exact
 *  array `lib/boardPlacement.ts::reorderPlacement`/`reparentPlacement` already splice for a write,
 *  so a candidate list built from it stays consistent with what the write actually reorders. */
function columnChildIds(
  board: BoardResponse | null,
  columnIds: ReadonlySet<string>,
  parent: { id: string; vertical: string | null },
): string[] {
  return (board?.children[parent.id] ?? [])
    .filter((kid) => kid.vertical !== null && kid.vertical === parent.vertical && columnIds.has(kid.id))
    .map((kid) => kid.id)
}

/** First candidate whose press-time row centre sits below the pointer — `null` (append) once the
 *  pointer is below all of them. Cached `rowRects` over a live `querySelector` fallback for the
 *  same press-time-geometry law `drag.ts`'s own version of this function documents: nothing here
 *  may read a mid-gesture resort's live position back into the target it is itself producing. */
function nearestInsertionPoint(
  candidates: readonly string[],
  pointerY: number,
  rowRects: ReadonlyMap<string, DOMRect>,
): string | null {
  for (const id of candidates) {
    const rect = rowRects.get(id)
      ?? document.querySelector(`[data-goal-id="${id}"]`)?.getBoundingClientRect()
    if (rect && pointerY < rect.top + rect.height / 2) return id
  }
  return null
}

/** Extends a rendered group's band past its last child's own bottom edge, to the midpoint of the
 *  gap before whatever rendered row comes next in the column (any other row, top-level or another
 *  group's own child — the reading-order rule "the pointer is closer to what's above it" holds
 *  either way). No next row (this group is the last thing rendered) leaves the band open-ended:
 *  everything further down the column is still this group's own append slot. Pixel comparison,
 *  not wire order — position numbering is scoped per parent group and is not a reliable
 *  cross-group ordering (this file's header), so "what renders next" is answered by geometry, the
 *  one thing that cannot lie about visual adjacency. */
function extendBandBottom(
  columnIds: ReadonlySet<string>,
  rowRects: ReadonlyMap<string, DOMRect>,
  ownIds: ReadonlySet<string>,
  bottom: number,
): number {
  let nextTop = Infinity
  for (const id of columnIds) {
    if (ownIds.has(id)) continue
    const rect = rowRects.get(id)
    if (rect && rect.top >= bottom && rect.top < nextTop) nextTop = rect.top
  }
  return nextTop === Infinity ? Infinity : (bottom + nextTop) / 2
}

export interface ReorderSlot {
  /** Same meaning as `DropTarget`'s own field: the id this drop would insert before, or `null` to
   *  append after every existing member of the resolved group. */
  insertBeforeId: string | null
  /** The resolved group's owner — `null` for the column's own top level, a goal id for a rendered
   *  nested group (append included: an append slot is no longer always top-level, D249). */
  parentId: string | null
}

/** The one entry point: given a column and a live pointer Y, which slot — and whose group — does
 *  this drop resolve to. Checks every rendered nested group in the column FIRST (pointer inside a
 *  group's own band, extended past its last child to the next rendered row); only pointer
 *  positions outside every band fall back to the column's own top-level candidates, exactly as
 *  `drag.ts` resolved every reorder before this file existed — this function only adds the nested
 *  case, it does not change the top-level one. `sourceId`'s own subtree is excluded everywhere (a
 *  card may not nest under itself or a descendant), matching the source-exclusion every other
 *  candidate list here already applies. */
export function resolveReorderSlot(
  board: BoardResponse | null,
  sourceId: string,
  vertical: string,
  periodKey: string | null,
  pointerY: number,
  rowRects: ReadonlyMap<string, DOMRect>,
): ReorderSlot {
  const columnIds = new Set(idsInColumn(board, vertical, periodKey))
  const excluded = subtreeIds(board, sourceId)

  for (const id of columnIds) {
    if (excluded.has(id)) continue
    const parent = findGoal(board, id)
    if (!parent) continue
    const allKids = columnChildIds(board, columnIds, parent)
    const rendered = allKids.filter((kid) => rowRects.has(kid))
    if (!rendered.length) continue
    const rects = rendered.map((kid) => rowRects.get(kid) as DOMRect)
    const top = Math.min(...rects.map((rect) => rect.top))
    const rawBottom = Math.max(...rects.map((rect) => rect.bottom))
    const bottom = extendBandBottom(columnIds, rowRects, new Set(rendered), rawBottom)
    if (pointerY >= top && pointerY < bottom) {
      const candidates = allKids.filter((kid) => kid !== sourceId)
      return { insertBeforeId: nearestInsertionPoint(candidates, pointerY, rowRects), parentId: id }
    }
  }

  const topLevel = [...columnIds].filter(
    (id) => id !== sourceId && isTopLevelInColumn(board, columnIds, id),
  )
  return { insertBeforeId: nearestInsertionPoint(topLevel, pointerY, rowRects), parentId: null }
}
