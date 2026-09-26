import { nextTick } from 'vue'
import { toast } from '@konstantinopolskii/vue'
import { store, todayIso } from '../store'
import { dueAckGoal, fetchBoard, getGoal, patchGoal, scheduleGoal, type GoalCard } from './api'
import { VERTICAL_SCALES, type VerticalScale } from './periods'
import { messageForError } from './scheduleFeedback'
import { carriedGoals, carryoverState } from './carryoverState'
import type { GoalCardData } from '../types'
export { carriedGoals, carryoverState } from './carryoverState'

export type CarryoverAction = 'done' | 'keep' | 'later' | 'missed'
export const CARRYOVER_ACTIONS = [
  { action: 'done', label: 'Done', key: 'D' },
  { action: 'keep', label: 'Keep', key: 'K' },
  { action: 'later', label: 'Later', key: 'L' },
  { action: 'missed', label: 'Missed', key: 'M' },
] as const

type CarriedGoal = { id: string; vertical?: string | null; ghostUntil?: string | null }
function scaleOf(goal: CarriedGoal): VerticalScale {
  if (!VERTICAL_SCALES.includes(goal.vertical as VerticalScale)) throw Error('This goal has no dated vertical.')
  return goal.vertical as VerticalScale
}
function pin(goals: CarriedGoal[], vertical: string) {
  carryoverState.kept[vertical] = [...new Set([...(carryoverState.kept[vertical] ?? []), ...goals.map(goal => goal.id)])]
}
function pending(vertical: string) {
  return carriedGoals(store.columns.value.find(column => column.vertical === vertical)?.goals ?? [])
}
export function stopCarryoverReview() {
  carryoverState.goalId = null
  carryoverState.vertical = null
  carryoverState.reviewError = null
  store.closeGoal()
}
export async function startCarryoverReview(vertical: string) {
  const goal = pending(vertical)[0]
  if (!goal || carryoverState.busy) return
  carryoverState.vertical = vertical
  carryoverState.goalId = goal.id
  carryoverState.reviewError = null
  await store.openBoardGoal(goal.id)
  await nextTick()
  document.querySelector<HTMLElement>(`[data-goal-id="${goal.id}"] [data-carryover-action="done"]`)?.focus({ preventScroll: true })
}
async function collapseReview(id: string, action: CarryoverAction) {
  const card = document.querySelector<HTMLElement>(`[data-goal-id="${id}"]`)
  const parts = action === 'keep'
    ? [...(card?.querySelectorAll<HTMLElement>('[data-role="inline-detail"], [data-role="carryover-answers"]') ?? [])]
    : card ? [card] : []
  if (card) card.dataset.reviewCollapsing = action
  await Promise.all([...parts].map(async element => {
    const animation = element.animate(
      [{ height: `${element.getBoundingClientRect().height}px`, opacity: 1, overflow: 'hidden' }, { height: '0px', minHeight: '0px', paddingTop: '0px', paddingBottom: '0px', marginTop: '0px', marginBottom: '0px', opacity: 0, overflow: 'hidden' }],
      { duration: 200, easing: 'cubic-bezier(0.2, 0, 0, 1)', fill: 'forwards' },
    )
    try { await animation.finished } catch { /* Closing the surface can cancel the animation. */ }
  }))
}

/** All callers use the same API meanings; failures leave the current review item available. */
export async function resolveCarryover(goal: CarriedGoal, action: CarryoverAction): Promise<void> {
  if (carryoverState.busy) return
  const reviewing = carryoverState.goalId === goal.id
  carryoverState.reviewError = null
  const vertical = goal.vertical ?? ''
  const previousPins = [...(carryoverState.kept[vertical] ?? [])]
  carryoverState.busy = true
  try {
    if (action === 'done' || action === 'missed') await dueAckGoal(goal.id, action === 'done' ? 'done_on_time' : 'overdue')
    else if (action === 'later') {
      if (!goal.ghostUntil) throw Error('The carried-over period is unavailable. Reload and try again.')
      await patchGoal(goal.id, { carryover_ignored_until: goal.ghostUntil })
    } else {
      pin([goal], vertical)
      await scheduleGoal(goal.id, scaleOf(goal), todayIso())
    }
    if (reviewing) await collapseReview(goal.id, action)
    // A single answer leaves the pile: resume carried-first grouping rather than retaining
    // the temporary full-column order used to keep a bulk operation visually still.
    delete carryoverState.displayOrder[vertical]
    store.closeGoal()
    await store.reloadBoard()
    if (reviewing && carryoverState.goalId === goal.id) {
      carryoverState.goalId = null
      carryoverState.busy = false
      if (pending(vertical).length) await startCarryoverReview(vertical)
      else stopCarryoverReview()
    }
  } catch (error) {
    if (action === 'keep') carryoverState.kept[vertical] = previousPins
    if (reviewing) carryoverState.reviewError = messageForError(error)
    else toast(messageForError(error))
  } finally {
    carryoverState.busy = false
  }
}

function periodWording(vertical: string) {
  return vertical === 'day' ? 'today' : vertical === 'decade' ? 'this 3-year period' : `this ${vertical}`
}

/** Capture affected schedules before a batch; parent-first restore also reverses cascades. */
export async function keepAllCarryovers(goals: GoalCardData[], vertical: string): Promise<void> {
  if (carryoverState.busy || !goals.length) return
  const selected = new Set(goals.map(goal => goal.id))
  const column = store.columns.value.find(column => column.vertical === vertical)
  const columnGoals = column?.goals ?? []
  const families = columnGoals.filter(goal => carriedGoals([goal]).some(carried => selected.has(carried.id)))
  const flatten = (items: GoalCardData[]): GoalCardData[] => items.flatMap(goal => [goal, ...flatten(goal.children ?? [])])
  const keptOrder = flatten(families).map(goal => goal.id)
  const originalDisplayOrder = { periodKey: column?.periodKey ?? null, ids: flatten(columnGoals).map(goal => goal.id) }
  const ids = new Set<string>()
  const originals: GoalCard[] = []
  const previousPins = [...(carryoverState.kept[vertical] ?? [])]
  carryoverState.busy = true
  // Include ordinary children and ordinary families, not only the carried IDs. API scheduling
  // changes numeric positions, but neither Keep all nor Undo should change this reading order.
  carryoverState.displayOrder[vertical] = originalDisplayOrder
  pin(goals, vertical)
  let kept = 0
  const groups = new Map<string, GoalCard[]>()
  const groupKey = (goal: GoalCard) => `${goal.vertical}:${goal.period_key}`
  try {
    // Undo's move back can pull a previously current-period descendant into the parent's old
    // period (D109). Today's board is incomplete, so snapshot the entire API subtree, including
    // different-period children and ideas, before the first write.
    const queue = [...goals.map(goal => goal.id), ...families.map(goal => goal.id)]
    while (queue.length) {
      const id = queue.shift()!
      if (ids.has(id)) continue
      const detail = await getGoal(id)
      ids.add(id)
      originals.push({ ...detail })
      queue.push(...detail.children.map(child => child.id), ...detail.ideas.map(child => child.id))
    }
    originals.sort((a, b) => a.depth - b.depth || a.position - b.position)
    // Historical columns expose every original sibling, including acknowledged/completed ones
    // absent from today's ghosts. Capture their relative order before moving anything.
    for (const goal of originals) {
      if (!goal.anchor_date || groups.has(groupKey(goal))) continue
      const historical = await fetchBoard(goal.anchor_date)
      groups.set(groupKey(goal), (historical.columns.find(column => column.vertical === goal.vertical)?.goals ?? [])
        .filter(item => item.period_key === goal.period_key).sort((a, b) => a.position - b.position))
    }
    // Reconcile the complete family parent-first. Moving an overdue parent also moves its
    // completed historical descendants (D109); those are not part of Keep all and must retain
    // their dates. Restoring such a parent can in turn move a selected grandchild backwards,
    // so each later descendant is checked against its own desired schedule, not a stale board.
    const today = todayIso()
    for (const goal of originals) {
      const keep = selected.has(goal.id)
      const desiredAnchor = keep ? today : goal.anchor_date
      const current = await getGoal(goal.id)
      if (current.vertical !== goal.vertical || current.anchor_date !== desiredAnchor) {
        await scheduleGoal(goal.id, goal.vertical as VerticalScale | null, desiredAnchor)
      }
      if (keep) kept += 1
    }
    // Persist the same visible family order at the head of this period. Session pins suppress
    // transient reorder while writes settle; the API ordering survives a full page reload.
    for (const id of [...keptOrder].reverse()) await patchGoal(id, { position: 'first' })
    await store.reloadBoard()
    carryoverState.notices[vertical] = {
      text: `${kept} kept for ${periodWording(vertical)}`,
      action: 'Undo', onAction: () => void undoKeep(),
    }
  } catch (error) {
    await store.reloadBoard()
    if (kept) carryoverState.notices[vertical] = {
      text: `${kept} kept for ${periodWording(vertical)}`,
      action: 'Undo', onAction: () => void undoKeep(), detail: messageForError(error),
    }
    else {
      carryoverState.kept[vertical] = previousPins
      carryoverState.displayOrder[vertical] = originalDisplayOrder
      carryoverState.notices[vertical] = {
        text: 'Could not keep goals', action: 'Retry',
        onAction: () => void keepAllCarryovers(goals, vertical), detail: messageForError(error),
      }
    }
  } finally { carryoverState.busy = false }

  async function undoKeep() {
    if (carryoverState.busy) return
    carryoverState.busy = true
    try {
      for (const goal of originals) {
        // Read after restoring each ancestor: its server cascade may have changed this row
        // since the pre-Undo board. Unchanged ideas/lower-vertical children need no write.
        const current = await getGoal(goal.id)
        if (current.vertical !== goal.vertical || current.anchor_date !== goal.anchor_date) {
          await scheduleGoal(goal.id, goal.vertical as VerticalScale | null, goal.anchor_date)
        }
      }
      for (const siblings of groups.values()) {
        for (let index = 0; index < siblings.length; index += 1) {
          const goal = siblings[index]!
          if (!ids.has(goal.id)) continue
          await patchGoal(goal.id, index ? { after_id: siblings[index - 1]!.id } : { position: 'first' })
        }
      }
      carryoverState.kept[vertical] = previousPins
      carryoverState.displayOrder[vertical] = originalDisplayOrder
      await store.reloadBoard()
      delete carryoverState.notices[vertical]
    } catch (error) {
      carryoverState.notices[vertical] = {
        text: 'Could not undo', action: 'Undo', onAction: () => void undoKeep(), detail: messageForError(error),
      }
    }
    finally { carryoverState.busy = false }
  }
}
