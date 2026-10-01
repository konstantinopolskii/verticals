// Finding (docs/design-handoff S1.P3): from a word of three letters the server matches titles and notes in every
// period and returns each match's parents; with shorter words only the board on screen is searched, and nothing is
// asked. Matches from periods a column doesn't show stand under that period's headline: what is coming first, nearest
// first, then what is closed, latest first.
import { reactive, watch, type WatchStopHandle } from 'vue'
import { findGoals, type FindResponse, type GoalCard, type SearchParent } from './api'
import { plannedPeriodLabel } from './schedule'
import { defineKnobs, knob } from './tuning'
import type { GoalCardData } from '../types'

export const MIN_LETTERS = 3

defineKnobs('Finding', [
  { key: 'finding.debounceMs', label: 'Ask the server once the keys rest for', value: 180, min: 0, max: 1000, step: 10, unit: 'ms' },
])

export const found = reactive({ text: '', result: null as FindResponse | null })

export function termsOf(text: string): string[] {
  return text.trim().split(/\s+/).filter(Boolean).map((word) => word.toLocaleLowerCase())
}
export function asksServer(text: string): boolean {
  return termsOf(text).some((term) => term.length >= MIN_LETTERS)
}

/** One request per settled word, again when the board changes under it. */
export function followWords(words: () => string, board: () => unknown): WatchStopHandle {
  let timer: ReturnType<typeof setTimeout> | null = null
  let version = 0
  return watch([words, board], ([text]) => {
    if (timer) clearTimeout(timer)
    if (!asksServer(text)) {
      version++
      found.text = ''
      found.result = null
      return
    }
    const q = text.trim().slice(0, 200)
    timer = setTimeout(async () => {
      const mine = ++version
      try {
        const result = await findGoals(q)
        if (mine !== version) return
        found.text = q
        found.result = result
      } catch {
        // The board keeps what it shows; the next word asks again.
      }
    }, knob('finding.debounceMs'))
  })
}

export interface FoundSection {
  key: string
  headline: string
  coming: boolean
  goals: GoalCardData[]
}

type Node = { id: string; parentId: string | null; title: string; done: boolean; color: string | null; vertical: string | null;
  anchorDate: string | null; periodKey: string; position: number }

/** A column's matches and their parents from periods it doesn't show, one section per period. */
export function sectionsFor(
  vertical: string,
  shownPeriod: string | null,
  matches: readonly GoalCard[],
  parents: Readonly<Record<string, SearchParent[]>>,
  onBoard: ReadonlySet<string>,
): FoundSection[] {
  const nodes = new Map<string, Node>()
  const take = (goal: GoalCard | SearchParent, color: string | null) => {
    if (goal.vertical !== vertical || !goal.period_key || goal.period_key === shownPeriod || onBoard.has(goal.id)) return
    if (nodes.has(goal.id)) return
    nodes.set(goal.id, {
      id: goal.id, parentId: goal.parent_id, title: goal.title, done: goal.done_at !== null, color, vertical: goal.vertical,
      anchorDate: goal.anchor_date, periodKey: goal.period_key, position: goal.position,
    })
  }
  for (const match of matches) {
    take(match, match.color)
    for (const parent of parents[match.id] ?? []) take(parent, match.color)
  }
  const periods = new Map<string, Node[]>()
  for (const node of nodes.values()) periods.set(node.periodKey, [...(periods.get(node.periodKey) ?? []), node])
  const card = (node: Node, group: Node[]): GoalCardData => ({
    id: node.id, parentId: node.parentId, title: node.title, done: node.done, color: node.color, vertical: node.vertical,
    anchorDate: node.anchorDate,
    children: group.filter((child) => child.parentId === node.id).sort(byPlace).map((child) => card(child, group)),
  })
  const sections = [...periods.entries()].map(([key, group]) => {
    const ids = new Set(group.map((node) => node.id))
    const top = group.filter((node) => !node.parentId || !ids.has(node.parentId)).sort(byPlace)
    return {
      key,
      headline: plannedPeriodLabel({ vertical, anchor_date: group[0]!.anchorDate, period_key: key }),
      coming: shownPeriod === null || key > shownPeriod,
      goals: top.map((node) => card(node, group)),
    }
  })
  const coming = sections.filter((section) => section.coming).sort((a, b) => a.key.localeCompare(b.key))
  const closed = sections.filter((section) => !section.coming).sort((a, b) => b.key.localeCompare(a.key))
  return [...coming, ...closed]
}

function byPlace(a: Node, b: Node): number {
  return (a.anchorDate ?? '').localeCompare(b.anchorDate ?? '') || a.position - b.position
}

const NOTHING: Record<string, string> = {
  day: 'Nothing today.',
  week: 'Nothing this week.',
  month: 'Nothing this month.',
  quarter: 'Nothing this quarter.',
  year: 'Nothing this year.',
  decade: 'Nothing in 3 years.',
  life: 'Nothing in Life.',
}
export function nothingIn(vertical: string): string {
  return NOTHING[vertical] ?? 'Nothing here.'
}
