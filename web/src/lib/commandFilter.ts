import { computed, reactive } from 'vue'
import { store } from '../store'
import type { BoardColumnData, GoalCardData } from '../types'
import { asksServer, found, termsOf } from './finding'
import type { GoalCard } from './api'

// The field's words (docs/design-handoff S1.P2): the board follows every letter, a search and a message alike. From a
// word of three letters the server's matches decide (S1.P3), notes included; below that, titles on the board do.
export const commandFilter = reactive({ text: '' })
export const queryTerms = computed(() => termsOf(commandFilter.text))
export const filterActive = computed(() => queryTerms.value.length > 0)

function titleMatches(title: string): boolean {
  const lower = title.toLocaleLowerCase()
  return queryTerms.value.every(term => lower.includes(term))
}

/** The server's matches for the words on screen, or null while only the board is searched. While a newer word is on
 *  its way, the last answer narrows by title. */
export const serverMatches = computed<GoalCard[] | null>(() => {
  const result = found.result
  if (!result || !asksServer(commandFilter.text)) return null
  if (found.text === commandFilter.text.trim()) return result.goals
  return result.goals.filter(goal => titleMatches(goal.title))
})
const serverIds = computed(() => serverMatches.value ? new Set(serverMatches.value.map(goal => goal.id)) : null)

export function goalMatchesFilter(goal: GoalCardData): boolean {
  if (!filterActive.value) return true
  return serverIds.value ? serverIds.value.has(goal.id) : titleMatches(goal.title)
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
const matchedIds = computed(() => serverIds.value ?? new Set(boardMatches.value.map(match => match.id)))

/** The matches and their parents: what the board keeps while you type (S1.P3.013). */
const keptIds = computed(() => {
  const kept = new Set<string>()
  if (!filterActive.value) return kept
  if (serverMatches.value) {
    for (const goal of serverMatches.value) {
      kept.add(goal.id)
      for (const parent of found.result?.parents[goal.id] ?? []) kept.add(parent.id)
    }
  } else {
    for (const match of boardMatches.value) {
      kept.add(match.id)
      for (const ancestor of store.state.board?.ancestors[match.id] ?? []) kept.add(ancestor.id)
    }
  }
  return kept
})

export function filterColumns(columns: BoardColumnData[]): BoardColumnData[] {
  if (!filterActive.value) return columns
  const visit = (goals: GoalCardData[]): GoalCardData[] => goals.flatMap(goal => {
    const children = visit(goal.children ?? [])
    return keptIds.value.has(goal.id) || children.length ? [{ ...goal, children }] : []
  })
  return columns.map(column => ({ ...column, goals: visit(column.goals) }))
}

/** A parent shown in grey for a match of its (S1.P3.013). */
export function isContextGoal(id: string): boolean {
  return filterActive.value && !matchedIds.value.has(id)
}

/** Nothing matches anywhere: the board turns off (S1.P3.014). */
export const nothingFound = computed(() => filterActive.value
  && !matchedIds.value.size && !(serverMatches.value?.length))

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
