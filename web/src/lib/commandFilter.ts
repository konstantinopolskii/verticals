import { computed, reactive } from 'vue'
import { store } from '../store'
import type { BoardColumnData, GoalCardData } from '../types'

// The field's words (docs/design-handoff S1.P2): the board follows every letter, a search and a message alike.
export const commandFilter = reactive({ text: '' })
export const queryTerms = computed(() => commandFilter.text.trim().split(/\s+/).filter(Boolean).map(word => word.toLocaleLowerCase()))
export const filterActive = computed(() => queryTerms.value.length > 0)

export function goalMatchesFilter(goal: GoalCardData): boolean {
  if (!filterActive.value) return true
  const title = goal.title.toLocaleLowerCase()
  return queryTerms.value.every(term => title.includes(term))
}
export function filterColumns(columns: BoardColumnData[]): BoardColumnData[] {
  if (!filterActive.value) return columns
  const visit = (goals: GoalCardData[]): GoalCardData[] => goals.flatMap(goal => {
    const children = visit(goal.children ?? [])
    return goalMatchesFilter(goal) || children.length ? [{ ...goal, children }] : []
  })
  return columns.map(column => ({ ...column, goals: visit(column.goals) }))
}
export const boardMatches = computed(() => {
  const result: { id: string; vertical: string }[] = []
  const visit = (goals: GoalCardData[], vertical: string) => {
    for (const goal of goals) {
      if (goalMatchesFilter(goal)) result.push({ id: goal.id, vertical })
      visit(goal.children ?? [], vertical)
    }
  }
  for (const column of store.columns.value) if (column.vertical !== 'maybe') visit(column.goals, column.vertical)
  return result
})
export function isContextGoal(id: string, columnVertical?: string | null): boolean {
  if (!filterActive.value) return false
  const find = (goals: GoalCardData[]): GoalCardData | undefined => {
    for (const goal of goals) { if (goal.id === id) return goal; const child = find(goal.children ?? []); if (child) return child }
  }
  for (const column of store.columns.value) {
    if (columnVertical && column.vertical !== columnVertical) continue
    const goal = find(column.goals)
    if (goal) return !goalMatchesFilter(goal)
  }
  return false
}
export function highlightTitle(title: string): { text: string; match: boolean }[] {
  const lower = title.toLocaleLowerCase()
  const highlighted = Array<boolean>(title.length).fill(false)
  for (const term of queryTerms.value) {
    let at = lower.indexOf(term)
    while (at !== -1) { highlighted.fill(true, at, at + term.length); at = lower.indexOf(term, at + term.length) }
  }
  const parts: { text: string; match: boolean }[] = []
  for (let i = 0; i < title.length; i++) {
    const match = !!highlighted[i]
    const last = parts[parts.length - 1]
    if (last?.match === match) last.text += title[i]
    else parts.push({ text: title[i]!, match })
  }
  return parts
}
