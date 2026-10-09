// Operation-local board mutations for drag writes. Each mutation changes the existing reactive
// arrays immediately, then exposes two explicit endings: merge the write response, or restore the
// exact prior placement. Network ownership stays in store.ts; this file only edits one board.
//
// D245 (KK, 2026-08-18): every mutator (and every rollback) bumps `lib/boardEpoch.ts`'s counter
// the instant it changes the board — the one place a "local write changed placement" is true for
// every caller, drag or menu, so `store.ts`'s `loadBoard`/`liveReload` guard has a single source
// to check instead of every write site remembering to call it.

import { ancestorIds, findGoal } from './boardIndex'
import { bump } from './boardEpoch'
import type { BoardColumn, BoardResponse, GoalCard } from './api'

export interface OptimisticPlacement {
  reconcile(updated?: GoalCard): void
  rollback(): void
}

interface GoalSnapshot {
  goal: GoalCard
  value: GoalCard
}

function goalRefs(board: BoardResponse, id: string): GoalCard[] {
  const refs: GoalCard[] = []
  const add = (goal: GoalCard): void => {
    if (goal.id === id && !refs.includes(goal)) refs.push(goal)
  }
  for (const column of board.columns) for (const goal of column.goals) add(goal)
  for (const children of Object.values(board.children)) for (const goal of children) add(goal)
  return refs
}

function snapshotGoals(goals: GoalCard[]): GoalSnapshot[] {
  return goals.map((goal) => ({ goal, value: { ...goal, tags: [...goal.tags] } }))
}

function assignGoal(goal: GoalCard, value: GoalCard): void {
  Object.assign(goal, value, { tags: [...value.tags] })
}

function restoreGoals(snapshots: GoalSnapshot[]): void {
  for (const snapshot of snapshots) assignGoal(snapshot.goal, snapshot.value)
}

/** A card shows its value's colour (D231), i.e. its parent's colour on the board. */
export function valueColor(
  board: BoardResponse,
  goal: Pick<GoalCard, 'parent_id' | 'vertical' | 'color'>,
  fallback: string | null,
): string | null {
  if (goal.parent_id === null) return goal.vertical === 'life' ? goal.color : null
  return findGoal(board, goal.parent_id)?.color ?? fallback
}

/** Write responses carry the stored colour, which is not what the board shows. */
function mergeServerCard(board: BoardResponse, goal: GoalCard, updated: GoalCard): void {
  Object.assign(goal, updated, { tags: [...updated.tags], color: valueColor(board, updated, goal.color) })
}

function reconcileGoals(board: BoardResponse, id: string, updated: GoalCard): void {
  for (const goal of goalRefs(board, id)) mergeServerCard(board, goal, updated)
}

function columnEntry(
  board: BoardResponse,
  id: string,
): { column: BoardColumn; index: number; goal: GoalCard } | null {
  for (const column of board.columns) {
    const index = column.goals.findIndex((goal) => goal.id === id)
    if (index !== -1) return { column, index, goal: column.goals[index] }
  }
  return null
}

function targetColumn(
  board: BoardResponse,
  vertical: string | null,
  periodKey: string | null,
): BoardColumn | undefined {
  const wireVertical = vertical === 'maybe' ? null : vertical
  return board.columns.find(
    (column) => column.vertical === wireVertical && column.period_key === periodKey,
  )
}

/** Mirrors the server's final placement immediately. `insertBeforeId` is the slot a cross-column
 *  DRAG released over — the row goes in there, exactly as the same drop's `after_id`/`position`
 *  will place it server-side. Every other caller (the card menu, the popover, move-to-inbox) names
 *  no slot and appends, which is what a schedule write does on its own. */
export function schedulePlacement(
  board: BoardResponse | null,
  id: string,
  target: { vertical: string | null; periodKey: string | null },
  anchorDate: string | null,
  insertBeforeId: string | null = null,
): OptimisticPlacement | null {
  if (!board) return null
  const refs = goalRefs(board, id)
  const source = columnEntry(board, id)
  const placed = source?.goal ?? refs[0]
  if (!placed) return null
  const wireVertical = target.vertical === 'maybe' ? null : target.vertical
  const needsColumn = wireVertical !== null || placed.parent_id === null
  const destination = needsColumn ? targetColumn(board, wireVertical, target.periodKey) : undefined
  if (needsColumn && !destination) return null

  const snapshots = snapshotGoals(refs)
  if (source) source.column.goals.splice(source.index, 1)
  if (destination) {
    const slot = insertBeforeId === null
      ? -1
      : destination.goals.findIndex((candidate) => candidate.id === insertBeforeId)
    if (slot === -1) destination.goals.push(placed)
    else destination.goals.splice(slot, 0, placed)
  }
  for (const goal of refs) {
    goal.vertical = wireVertical
    goal.anchor_date = anchorDate
    goal.period_key = target.periodKey
    goal.ghost = false
    goal.ghost_until = null
  }
  bump() // D245: outrun any board fetch already in flight — it describes the pre-move world.

  let active = true
  return {
    reconcile(updated) {
      if (!active) return
      if (updated) for (const goal of refs) mergeServerCard(board, goal, updated)
      active = false
    },
    rollback() {
      if (!active) return
      const placedAt = destination?.goals.indexOf(placed) ?? -1
      if (destination && placedAt !== -1) destination.goals.splice(placedAt, 1)
      if (source) source.column.goals.splice(source.index, 0, source.goal)
      restoreGoals(snapshots)
      bump() // D245: the rollback is itself a local placement change.
      active = false
    },
  }
}

/** The array the board renders `id` from: its parent's children when it nests there, else its column. */
function renderedSiblings(board: BoardResponse, id: string): GoalCard[] | null {
  const entry = columnEntry(board, id)
  const goal = entry?.goal ?? findGoal(board, id)
  if (!goal) return null
  if (goal.parent_id) {
    const parent = findGoal(board, goal.parent_id)
    const nested = !!parent
      && (!entry || (parent.vertical === goal.vertical && entry.column.goals.some((g) => g.id === parent.id)))
    const kids = board.children[goal.parent_id]
    if (nested && kids?.some((g) => g.id === id)) return kids
  }
  if (entry) return entry.column.goals
  return Object.values(board.children).find((kids) => kids.some((g) => g.id === id)) ?? null
}

/** Reorder one existing sibling array to its prospective slot. */
export function reorderPlacement(
  board: BoardResponse | null,
  id: string,
  target: { insertBeforeId: string | null },
): OptimisticPlacement | null {
  if (!board) return null
  const siblings = renderedSiblings(board, id)
  if (!siblings) return null
  const sourceIndex = siblings.findIndex((goal) => goal.id === id)
  const goal = siblings[sourceIndex]
  const snapshots = snapshotGoals(goalRefs(board, id))
  siblings.splice(sourceIndex, 1)
  const targetIndex = target.insertBeforeId === null
    ? siblings.length
    : siblings.findIndex((candidate) => candidate.id === target.insertBeforeId)
  siblings.splice(targetIndex === -1 ? siblings.length : targetIndex, 0, goal)
  bump() // D245: outrun any board fetch already in flight — it describes the pre-move world.

  let active = true
  return {
    reconcile(updated) {
      if (!active) return
      if (updated) reconcileGoals(board, id, updated)
      active = false
    },
    rollback() {
      if (!active) return
      const currentIndex = siblings.indexOf(goal)
      if (currentIndex !== -1) siblings.splice(currentIndex, 1)
      siblings.splice(sourceIndex, 0, goal)
      restoreGoals(snapshots)
      bump() // D245: the rollback is itself a local placement change.
      active = false
    },
  }
}

function removeGoal(children: GoalCard[], id: string): void {
  const index = children.findIndex((goal) => goal.id === id)
  if (index !== -1) children.splice(index, 1)
}

/** Reparent locally, including direct-child counts and ancestor progress affected by the move. */
export function reparentPlacement(
  board: BoardResponse | null,
  id: string,
  parentId: string | null,
): OptimisticPlacement | null {
  if (!board) return null
  const refs = goalRefs(board, id)
  const placed = refs[0]
  if (!placed || placed.parent_id === parentId) return null

  const snapshots = snapshotGoals(refs)
  const oldParentId = placed.parent_id
  const oldAncestors = ancestorIds(board, id)
  const sourceColumn = placed.vertical === null && oldParentId === null ? columnEntry(board, id) : null
  const oldChildren = oldParentId ? [...(board.children[oldParentId] ?? [])] : null
  const destinationExisted = parentId !== null
    && Object.prototype.hasOwnProperty.call(board.children, parentId)
  const destinationChildren = parentId ? [...(board.children[parentId] ?? [])] : null
  const detachedColumn = parentId === null && placed.vertical === null
    ? targetColumn(board, null, null)
    : undefined
  const countIds = [oldParentId, parentId].filter((value): value is string => value !== null)
  const countSnapshots = new Map(countIds.map((key) => [key, board.child_counts[key]]))

  if (oldParentId) removeGoal(board.children[oldParentId] ?? [], id)
  if (sourceColumn) sourceColumn.column.goals.splice(sourceColumn.index, 1)
  if (parentId !== null) {
    if (!board.children[parentId]) board.children[parentId] = []
    removeGoal(board.children[parentId], id)
    board.children[parentId].push(placed)
  } else if (detachedColumn && !detachedColumn.goals.includes(placed)) {
    detachedColumn.goals.push(placed)
  }
  const parentRefs = parentId === null ? [] : goalRefs(board, parentId)
  for (const goal of refs) {
    goal.parent_id = parentId
    goal.depth = parentId === null ? 0 : (parentRefs[0]?.depth ?? -1) + 1
    goal.color = valueColor(board, goal, goal.color)
  }
  if (oldParentId) board.child_counts[oldParentId] = board.children[oldParentId]?.length ?? 0
  if (parentId) board.child_counts[parentId] = board.children[parentId].length

  const newAncestors = parentId === null ? [] : [parentId, ...ancestorIds(board, parentId)]
  const progressIds = new Set([...oldAncestors, ...newAncestors])
  const progressSnapshots = new Map(
    [...progressIds].map((key) => [key, board.progress[key] ? { ...board.progress[key] } : undefined]),
  )
  const movedTotal = 1 + (board.progress[id]?.total ?? 0)
  const movedDone = (placed.done_at === null ? 0 : 1) + (board.progress[id]?.done ?? 0)
  for (const ancestorId of oldAncestors) {
    const progress = board.progress[ancestorId]
    if (progress) {
      progress.total -= movedTotal
      progress.done -= movedDone
    }
  }
  for (const ancestorId of newAncestors) {
    const progress = board.progress[ancestorId]
    if (progress) {
      progress.total += movedTotal
      progress.done += movedDone
    }
  }
  bump() // D245: outrun any board fetch already in flight — it describes the pre-move world.

  let active = true
  return {
    reconcile(updated) {
      if (!active) return
      if (updated) for (const goal of refs) mergeServerCard(board, goal, updated)
      active = false
    },
    rollback() {
      if (!active) return
      if (parentId !== null && destinationChildren) {
        board.children[parentId].splice(0, board.children[parentId].length, ...destinationChildren)
        if (!destinationExisted && board.children[parentId].length === 0) delete board.children[parentId]
      }
      if (detachedColumn) removeGoal(detachedColumn.goals, id)
      if (oldParentId && oldChildren) {
        if (!board.children[oldParentId]) board.children[oldParentId] = []
        board.children[oldParentId].splice(0, board.children[oldParentId].length, ...oldChildren)
      }
      if (sourceColumn) sourceColumn.column.goals.splice(sourceColumn.index, 0, sourceColumn.goal)
      for (const [key, value] of countSnapshots) {
        if (value === undefined) delete board.child_counts[key]
        else board.child_counts[key] = value
      }
      for (const [key, value] of progressSnapshots) {
        if (value === undefined) delete board.progress[key]
        else Object.assign(board.progress[key] ?? (board.progress[key] = { ...value }), value)
      }
      restoreGoals(snapshots)
      bump() // D245: the rollback is itself a local placement change.
      active = false
    },
  }
}

/** Patch every rendered copy immediately, then settle or restore only that goal's fields. */
export function patchPlacement(
  board: BoardResponse | null,
  id: string,
  patch: Partial<GoalCard>,
): OptimisticPlacement | null {
  if (!board) return null
  const refs = goalRefs(board, id)
  if (!refs.length) return null
  const snapshots = snapshotGoals(refs)
  for (const goal of refs) Object.assign(goal, patch)
  bump() // D245: outrun any board fetch already in flight — it describes the pre-patch world.
  let active = true
  return {
    reconcile(updated) {
      if (!active) return
      if (updated) for (const goal of refs) mergeServerCard(board, goal, updated)
      active = false
    },
    rollback() {
      if (!active) return
      restoreGoals(snapshots)
      bump() // D245: the rollback is itself a local placement change.
      active = false
    },
  }
}

interface RemovedEntry {
  list: GoalCard[]
  index: number
  goal: GoalCard
}

function descendantIds(board: BoardResponse, rootId: string): Set<string> {
  const ids = new Set([rootId])
  const queue = [rootId]
  while (queue.length) {
    const parentId = queue.shift() as string
    for (const child of board.children[parentId] ?? []) {
      if (ids.has(child.id)) continue
      ids.add(child.id)
      queue.push(child.id)
    }
  }
  return ids
}

/** Remove a goal/subtree from every board index without replacing unrelated reactive state. */
export function removePlacement(
  board: BoardResponse | null,
  id: string,
  cascade = false,
): OptimisticPlacement | null {
  if (!board) return null
  const ids = cascade ? descendantIds(board, id) : new Set([id])
  const lists = [...board.columns.map((column) => column.goals), ...Object.values(board.children)]
  const removed: RemovedEntry[] = []
  for (const list of lists) {
    for (let index = list.length - 1; index >= 0; index -= 1) {
      if (!ids.has(list[index].id)) continue
      removed.push({ list, index, goal: list[index] })
      list.splice(index, 1)
    }
  }
  const childLists = new Map<string, GoalCard[]>()
  const records = new Map<string, {
    progress: BoardResponse['progress'][string] | undefined
    ancestors: BoardResponse['ancestors'][string] | undefined
    count: number | undefined
  }>()
  for (const removedId of ids) {
    if (board.children[removedId]) {
      childLists.set(removedId, board.children[removedId])
      delete board.children[removedId]
    }
    records.set(removedId, {
      progress: board.progress[removedId],
      ancestors: board.ancestors[removedId],
      count: board.child_counts[removedId],
    })
    delete board.progress[removedId]
    delete board.ancestors[removedId]
    delete board.child_counts[removedId]
  }
  bump() // D245: outrun any board fetch already in flight — it describes the pre-removal world.
  let active = true
  return {
    reconcile() { active = false },
    rollback() {
      if (!active) return
      for (const [key, value] of childLists) board.children[key] = value
      for (const entry of removed.sort((a, b) => a.index - b.index)) {
        if (!entry.list.includes(entry.goal)) entry.list.splice(entry.index, 0, entry.goal)
      }
      for (const [key, value] of records) {
        if (value.progress) board.progress[key] = value.progress
        if (value.ancestors) board.ancestors[key] = value.ancestors
        if (value.count !== undefined) board.child_counts[key] = value.count
      }
      bump() // D245: the rollback is itself a local placement change.
      active = false
    },
  }
}
