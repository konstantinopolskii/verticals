// Pure reads over one `GET /api/board` payload. No reactivity, no network, no state — every
// function here takes the board it should answer about and returns a plain value, which is the
// same shape `lib/schedule.ts` and `lib/periods.ts` already follow in this tree.
//
// This module exists because `store.ts` crossed the 750-line module cap (ARCHITECTURE.md §2) when
// the board-surface gestures landed, and because these six answers are the half of that work that
// has nothing to do with mutation: which group a card belongs to, what sits under it, which
// ancestors a rollup has to touch, and which sibling a reorder should name. `store.ts` keeps the
// writes and the reactive tree; this keeps the arithmetic.
//
// Two structural facts about the payload every function here depends on, both from
// `core/board.py`:
//   * `columns[].goals` is the top-level card set, already ordered by `(position, id)`. Nothing
//     here re-sorts it — that order *is* "adjacent in position order" (docs/E2E.md S-71).
//   * `progress`, `ancestors` and `children` are keyed by **card** id. A pure subgoal (`vertical
//     IS NULL` under a parent) is reachable through `children` but has no `ancestors` entry of its
//     own, which is why `ancestorIds` below walks `parent_id` rather than reading that map.

import type { BoardResponse, GoalCard } from './api'

/** One goal's live record from anywhere in the payload — a column card or a nested child.
 *  Returns the object *in* the payload, not a copy: `store.ts` mutates what this hands back and
 *  relies on that being the same object Vue's `reactive()` is tracking. */
export function findGoal(board: BoardResponse | null, id: string): GoalCard | undefined {
  if (!board) return undefined
  for (const col of board.columns) {
    const hit = col.goals.find((g) => g.id === id)
    if (hit) return hit
  }
  for (const kids of Object.values(board.children)) {
    const hit = kids.find((g) => g.id === id)
    if (hit) return hit
  }
  return undefined
}

/** The ordered ids of the group `id` belongs to — its column's top-level cards, or its parent's
 *  direct children. Empty when `id` is not on this board at all. */
export function siblingIds(board: BoardResponse | null, id: string): string[] {
  if (!board) return []
  for (const col of board.columns) {
    if (col.goals.some((g) => g.id === id)) return col.goals.map((g) => g.id)
  }
  for (const kids of Object.values(board.children)) {
    if (kids.some((g) => g.id === id)) return kids.map((g) => g.id)
  }
  return []
}

/** `id` and every id under it, breadth-first through `board.children`. */
export function subtreeIds(board: BoardResponse | null, id: string): Set<string> {
  const out = new Set<string>([id])
  const queue = [id]
  while (queue.length) {
    const next = queue.shift() as string
    for (const kid of board?.children[next] ?? []) {
      if (!out.has(kid.id)) {
        out.add(kid.id)
        queue.push(kid.id)
      }
    }
  }
  return out
}

/** Every ancestor id of `id`, nearest first.
 *
 *  Walks `parent_id` through the payload rather than reading `board.ancestors`, because that map
 *  is keyed by card id only and a nested subgoal has no entry in it — F2's own `SYNSUB01` is
 *  exactly that case, and its six-link chain (`SYNDAY01` … `SYNLIF01`) is what S-70 asserts
 *  against. A loaded board always carries all eight columns, so a chain that starts anywhere on
 *  screen resolves whole; `board.ancestors` is used only as a top-up for the highest node the walk
 *  reached, never as the walk.
 *
 *  `seen` bounds the loop. `path` is acyclic by a database CHECK, but a half-applied optimistic
 *  reparent must not be able to hang the render thread on a cycle that exists for one frame. */
export function ancestorIds(board: BoardResponse | null, id: string): string[] {
  const out: string[] = []
  const seen = new Set<string>([id])
  let cursor = findGoal(board, id)
  while (cursor?.parent_id && !seen.has(cursor.parent_id)) {
    seen.add(cursor.parent_id)
    out.push(cursor.parent_id)
    const next = findGoal(board, cursor.parent_id)
    if (!next) break
    cursor = next
  }
  const highest = out.length ? out[out.length - 1] : id
  for (const a of board?.ancestors[highest] ?? []) {
    if (!seen.has(a.id)) {
      seen.add(a.id)
      out.push(a.id)
    }
  }
  return out
}

/** The menu route's target list for a reparent (docs/E2E.md S-67): every goal on this board that
 *  `id` could legally move under, in board order — columns left to right, each column top to
 *  bottom, each card's nested children directly under it. `id`'s own subtree is excluded because
 *  `core/tree.py#move` refuses it (`CycleRefused`, 409) and an affordance that offers a refusal is
 *  not an affordance; `id`'s current parent is excluded because moving there writes nothing. */
export function reparentTargets(
  board: BoardResponse | null,
  id: string,
): { id: string; title: string }[] {
  if (!board) return []
  const excluded = subtreeIds(board, id)
  const current = findGoal(board, id)?.parent_id
  if (current) excluded.add(current)
  const out: { id: string; title: string }[] = []
  const seen = new Set<string>()
  const push = (g: GoalCard): void => {
    if (!excluded.has(g.id) && !seen.has(g.id)) {
      seen.add(g.id)
      out.push({ id: g.id, title: g.title })
    }
    for (const kid of board.children[g.id] ?? []) push(kid)
  }
  for (const col of board.columns) for (const g of col.goals) push(g)
  return out
}

// `reorderTarget`/`reorderPatch` (the menu-driven "Move up"/"Move down" `after_id`/`position:
// 'first'` calculators) were removed here, this pass — see `store.ts`'s own "reorder within a
// group" section header for the full removal note (KK ruling 2026-08-09 deleted their one caller,
// `docs/PENDING_DOC_FIXES.md` row 127 named both as orphaned and invited this cleanup, and a grep
// confirmed zero remaining callers before deletion). The capability they served stays reachable
// over HTTP and MCP regardless (`core/moves.py::move_between`, unaffected by this file).

export type BoardGoalHost = {
  columnVertical: string
  parentId: string | null
  depth: number
  hostKey: string
}

/** Resolve the same rendered host identity GoalCard uses for a direct URL open. This walks the
 * projected columns, not raw wire vertical fields: same-vertical children render recursively under
 * their parent, while lower-vertical children are root cards in their own column. */
export function boardGoalHost(board: BoardResponse | null, id: string): BoardGoalHost | null {
  const walk = (
    cards: GoalCard[],
    columnVertical: string,
    columnCards: Map<string, GoalCard>,
    depth: number,
  ): BoardGoalHost | null => {
    for (const card of cards) {
      if (card.id === id) {
        const parentId = card.parent_id ?? null
        return {
          columnVertical,
          parentId,
          depth,
          hostKey: [columnVertical, parentId ?? 'root', depth, id].join(':'),
        }
      }
      const nested = walk(
        [...columnCards.values()].filter(
          (child) => child.parent_id === card.id && child.vertical !== null
            && child.vertical === card.vertical && !!child.ghost === !!card.ghost,
        ),
        columnVertical,
        columnCards,
        depth + 1,
      )
      if (nested) return nested
    }
    return null
  }
  for (const column of board?.columns ?? []) {
    if (column.vertical === null) continue
    const columnCards = new Map(column.goals.filter(goal => !(goal.ghost && goal.done_at !== null)).map(goal => [goal.id, goal]))
    const roots = [...columnCards.values()].filter((card) => {
      if (!card.parent_id) return true
      const parent = columnCards.get(card.parent_id)
      return !parent || parent.vertical !== card.vertical || !!parent.ghost !== !!card.ghost
    })
    const found = walk(roots, column.vertical, columnCards, 0)
    if (found) return found
  }
  return null
}
