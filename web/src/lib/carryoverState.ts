import { reactive } from 'vue'
import type { GoalCardData } from '../types'

export const carryoverState = reactive({
  vertical: null as string | null,
  goalId: null as string | null,
  busy: false,
  reviewError: null as string | null,
  kept: {} as Record<string, string[]>,
  displayOrder: {} as Record<string, { periodKey: string | null; ids: string[] }>,
  notices: {} as Record<string, { text: string; action: string; onAction: () => void; detail?: string }>,
})

export function carriedGoals(goals: GoalCardData[]): GoalCardData[] {
  const result: GoalCardData[] = []
  const seen = new Set<string>()
  function visit(items: GoalCardData[]) {
    for (const goal of items) {
      if (goal.ghost && !seen.has(goal.id)) { seen.add(goal.id); result.push(goal) }
      visit(goal.children ?? [])
    }
  }
  visit(goals)
  return result
}

/** Keep carried families together without breaking the full parent/child tree. */
export function carryoverFirst(goals: GoalCardData[], vertical: string, periodKey: string | null): GoalCardData[] {
  const snapshot = carryoverState.displayOrder[vertical]
  const order = snapshot?.periodKey === periodKey ? snapshot.ids : undefined
  const rank = (goal: GoalCardData): number => {
    const index = order?.indexOf(goal.id) ?? -1
    if (index >= 0) return index
    const childRank = Math.min(...(goal.children ?? []).map(rank))
    if (Number.isFinite(childRank)) return childRank
    return goal.ghost ? -1 : Number.POSITIVE_INFINITY
  }
  return goals.map(goal => ({ ...goal, children: carryoverFirst(goal.children ?? [], vertical, periodKey) }))
    .sort((left, right) => rank(left) - rank(right))
}
