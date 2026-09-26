import { computed, reactive } from 'vue'
import { store } from '../store'
import type { BoardColumnData, GoalCardData } from '../types'
import type { GoalCard } from './api'

export interface CommandToken { key: string; label: string; kind: 'view' | 'area' | 'vertical' | 'state'; value: string }
export const commandFilter = reactive({ text: '', tokens: [] as CommandToken[], chatOpen: false })
export const commandSuggestions = computed<CommandToken[]>(() => [
  ...['Inbox', 'Docs'].map(label => ({ key: label.toLowerCase(), label, kind: 'view' as const, value: label.toLowerCase() })),
  ...(store.state.board?.values ?? []).map(goal => ({ key: `area:${goal.id}`, label: store.state.board?.short_labels?.[goal.id] ?? goal.title.split(/\s+/)[0] ?? goal.title, kind: 'area' as const, value: goal.id })),
  ...['Day', 'Week', 'Month', 'Quarter', 'Year'].map(label => ({ key: label.toLowerCase(), label, kind: 'vertical' as const, value: label.toLowerCase() })),
  ...['Due', 'Done', 'Parked'].map(label => ({ key: label.toLowerCase(), label, kind: 'state' as const, value: label.toLowerCase() })),
])
export function recognizeCommand(word: string) {
  return commandSuggestions.value.find(item => item.label.toLocaleLowerCase() === word.toLocaleLowerCase())
}
// Bare filter keywords apply immediately. View names stay inert until explicitly tokenized.
export const effectiveTokens = computed(() => {
  const typed = commandFilter.text.trim().split(/\s+/).map(recognizeCommand).filter((item): item is CommandToken => !!item && item.kind !== 'view')
  return commandFilter.chatOpen ? [] : [...commandFilter.tokens, ...typed]
})
export const queryTerms = computed(() => commandFilter.chatOpen ? [] : commandFilter.text.trim().split(/\s+/).filter(word => word && !recognizeCommand(word)).map(word => word.toLocaleLowerCase()))
export const filterActive = computed(() => !commandFilter.chatOpen && (queryTerms.value.length > 0 || effectiveTokens.value.some(token => token.kind !== 'view')))

function hasArea(id: string, area: string) {
  if (id === area) return true
  return store.state.board?.ancestors[id]?.some(ancestor => ancestor.id === area) ?? false
}
export function goalMatchesFilter(goal: GoalCardData, columnVertical = goal.vertical ?? 'maybe'): boolean {
  if (!filterActive.value) return true
  if (!queryTerms.value.every(term => goal.title.toLocaleLowerCase().includes(term))) return false
  return effectiveTokens.value.every(token => {
    if (token.kind === 'area') return hasArea(goal.id, token.value)
    if (token.kind === 'vertical') return columnVertical === token.value
    if (token.kind === 'state') {
      if (token.value === 'due') return !!goal.ghost && !goal.done
      if (token.value === 'done') return !!goal.done
      if (token.value === 'parked') return false
    }
    return true
  })
}
export function filterColumns(columns: BoardColumnData[]): BoardColumnData[] {
  if (!filterActive.value) return columns
  const visit = (goals: GoalCardData[], vertical: string): GoalCardData[] => goals.flatMap(goal => {
    const children = visit(goal.children ?? [], vertical)
    return goalMatchesFilter(goal, vertical) || children.length ? [{ ...goal, children }] : []
  })
  return columns.map(column => ({ ...column, goals: visit(column.goals, column.vertical) }))
}
export const filteredColumns = computed(() => filterColumns(store.columns.value))
export const boardMatches = computed(() => {
  const result: { id: string; vertical: string }[] = []
  const visit = (goals: GoalCardData[], vertical: string) => {
    for (const goal of goals) {
      if (goalMatchesFilter(goal, vertical)) result.push({ id: goal.id, vertical })
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
    if (goal) return !goalMatchesFilter(goal, column.vertical)
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
export function remoteMatchesFilter(goal: GoalCard, ancestors: string[] = []): boolean {
  if (!queryTerms.value.every(term => goal.title.toLocaleLowerCase().includes(term))) return false
  return effectiveTokens.value.every(token => {
    if (token.kind === 'area') return goal.id === token.value || ancestors.includes(token.value) || hasArea(goal.id, token.value)
    if (token.kind === 'vertical') return goal.vertical === token.value
    if (token.kind === 'state') {
      if (token.value === 'done') return !!goal.done_at
      if (token.value === 'parked') return !!goal.parked_from_vertical
      if (token.value === 'due') return !!goal.ghost && !goal.done_at
    }
    return true
  })
}
