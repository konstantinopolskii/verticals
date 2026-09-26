/** The wire shape -> component props projection.
 *
 *  `core/board.py`'s wire shape and `types.ts`'s `BoardColumnData`/`GoalCardData` (WP-12) are
 *  deliberately different shapes (field names, nesting) — this file is the one place that
 *  reconciles them, so every component downstream renders from the same projection.
 *
 *  Pure functions of their arguments, lifted out of `store.ts` unchanged for ARCHITECTURE.md §2's
 *  750-line module rule (S-90a). They read no store state and hold none.
 */

import { columnPeriodLabel, verticalHeadline } from './schedule'
import type { BoardColumn, BoardResponse, GoalCard } from './api'
import type { BoardColumnData, GoalCardData } from '../types'
import { carryoverFirst } from './carryoverState'

function completedLast(goals: GoalCard[]): GoalCard[] {
  return [...goals].sort((left, right) => Number(left.done_at !== null) - Number(right.done_at !== null))
}

function goalById(board: BoardResponse, id: string): GoalCard | undefined {
  for (const column of board.columns) {
    const found = column.goals.find((goal) => goal.id === id)
    if (found) return found
  }
  for (const children of Object.values(board.children)) {
    const found = children.find((goal) => goal.id === id)
    if (found) return found
  }
  return undefined
}

export function toCardData(
  g: GoalCard,
  board: BoardResponse,
  projectTags: ReadonlySet<string> = new Set(),
  columnIds: ReadonlySet<string> = new Set(),
): GoalCardData {
  // Column records carry ghost/ghost_until; children records deliberately do not. Resolve
  // the canonical visible record before recursing so nested carryovers keep their metadata.
  if (columnIds.has(g.id)) g = goalById(board, g.id) ?? g
  const kids = board.children[g.id] ?? []
  // R7: the wire lists every direct child. A child nests under this card EXACTLY when
  // `toColumnData` below dropped its top-level copy from the column this card renders in —
  // same vertical AND a member of the same column (`columnIds`). One predicate, two sides, or
  // rows leak: period_key equality is the wrong test because the "3 years" column legitimately
  // folds legacy period keys (multiple period_keys, one column — found live via S-102: a 2023-
  // triennium child under a 2020-triennium parent, both in today's column, vanished from the
  // DOM), and bare scale equality is also wrong (a week child anchored in some OTHER week has
  // its own off-view column and must not smuggle into this one — S-102's earlier "extra in
  // DOM"). Lower-vertical children keep only their own column card; vertical-NULL children are
  // ideas and render in detail surfaces only. `subgoalCount` stays the unfiltered database
  // count because it describes the family, not the visible inline subset.
  const sameVerticalKids = completedLast(
    kids.filter(
      (k) => k.vertical !== null && k.vertical === g.vertical && columnIds.has(k.id),
    ),
  )
  // D231: `g.color` arrives DERIVED from the server (the value root's colour, or null for a
  // tree with no life-vertical root) — the old client-side `valueColorFor` walk is gone with it.
  return {
    id: g.id,
    parentId: g.parent_id,
    title: g.title,
    done: g.done_at !== null,
    color: g.color,
    vertical: g.vertical,
    repeat: g.repeat,
    tags: g.tags,
    projectTags: g.tags.filter((tag) => projectTags.has(tag)),
    foil: g.foil,
    ghost: g.ghost ?? false,
    ghostUntil: g.ghost_until ?? null,
    // S-70/AC-033: `done/total` over descendants, computed server-side in the same board query.
    // A leaf has no entry and renders no label, which is AC-033's "leaves report no progress".
    progress: board.progress[g.id],
    // `child_counts` and not `kids.length`: the two agree exactly on a column card, but
    // `board.children` is keyed by column cards alone, so a card rendered one level down by
    // `GoalCard.vue`'s recursion has no entry there and used to report 0 however many children
    // it really had (`docs/PENDING_DOC_FIXES.md` rows 93, 116(a)). The server now carries the
    // count for both levels. `?? kids.length` is the fallback for a response predating the
    // field, not a second source of truth.
    subgoalCount: board.child_counts?.[g.id] ?? kids.length,
    children: sameVerticalKids.map((k) => toCardData(k, board, projectTags, columnIds)),
  }
}

/** `BoardColumn.vertical` is `null` for exactly one column (the Maybe bucket — see `lib/api.ts`'s
 *  own note on why). `data-vertical` must read the literal string `"maybe"` there — this is the
 *  one place that translation happens, so `types.ts`'s `BoardColumnData.vertical: string` never
 *  needed to become nullable just to carry the wire shape through.
 *
 *  This mapping still has a job after ruling 1 (owner, 2026-08-09) took the Maybe *column* off
 *  the board (`Board.vue`'s own `dated` computed drops it before drawing, but this function still
 *  builds it — `columns` below stays the unfiltered eight-column projection, since `InboxView.vue`
 *  reads its Maybe entry off this same computed: `store.columns.value.find(c => c.vertical ===
 *  'maybe')`). Two live callers depend on the literal surviving: that `find`, and
 *  `Column.vue`'s own `props.vertical`, which `createGoalOn` below branches on directly
 *  (`verticalBucket === 'maybe' ? {title} : {title, vertical, anchor_date}`) — the sentinel is what
 *  tells a capture gesture apart from a schedule gesture, on the Inbox screen exactly as it did
 *  on the old eighth column. Dropping the mapping would not simplify anything; it would just move
 *  the `?? 'maybe'` fallback into two call sites instead of one. */
export function toColumnData(
  col: BoardColumn,
  board: BoardResponse,
  anchor: Date,
  today: Date,
  projectTags: ReadonlySet<string> = new Set(),
  expandedVertical: string | null = null,
): BoardColumnData {
  const verticalKey = col.vertical ?? 'maybe'
  const cardIds = new Set(col.goals.map((goal) => goal.id))
  const addLabel: Record<string, string> = {
    maybe: 'Idea…',
    day: 'Focus…',
    week: 'Execute…',
    month: 'Plan…',
    quarter: 'Achieve…',
    year: 'Bet…',
    decade: 'Visualise…',
    life: 'Become…',
  }
  return {
    vertical: verticalKey,
    title: verticalHeadline(verticalKey),
    // Every dated column gets the period-specific context above its stable generic headline.
    subLabel: columnPeriodLabel(col, anchor, today),
    // COMPACT_BOARD_HANDOFF.md §3 (supersedes the "day is 1.78x, always" rule): `active` now
    // means THE expanded column — the one the user clicked, at most one, none by default. Day
    // gets no special width any more (KK ruling 2026-08-17).
    active: verticalKey !== 'maybe' && verticalKey === expandedVertical,
    addPlaceholder: addLabel[verticalKey] ?? 'Add…',
    goals: carryoverFirst(completedLast(col.goals.filter((goal) => {
      if (!goal.parent_id) return true
      const parent = goalById(board, goal.parent_id)
      // R7 dedupes only when the parent is another card in this exact column. A same-vertical
      // parent can be outside the visible period; in that case the child remains a top-level
      // card because there is no parent card here to render it recursively. `cardIds` passed
      // into toCardData is the OTHER half of the same predicate: exactly the ids dropped here
      // are the ids toCardData nests, so no row can fall through the gap between the two.
      return !parent || parent.vertical !== goal.vertical || !cardIds.has(parent.id)
    })).map((g) => toCardData(g, board, projectTags, cardIds)), verticalKey, col.period_key),
    // `types.ts::BoardColumnData.periodKey`'s own doc comment: the same field `columnTitle` above
    // just read to build `title`, carried through unchanged for `dropOnColumn` below.
    periodKey: col.period_key,
  }
}
