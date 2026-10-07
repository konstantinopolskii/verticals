// The Documents desk (Inbox and Documents redesign, rounds 2–7, KK 6–7 Oct 2026; .local-design/inbox-and-docs): every
// document as a page, in stacks by the goal it accumulates under (`core/docs_desk.py`), the stacks grouped by value in
// the board's order. The documents no goal holds come first, under "No goal" (KK, 7 Oct: "at the beginning"), one stack
// for each age. The field narrows the desk as it narrows the board (S1.P3): a stack says how many of its pages match,
// and one with none turns off.
import { computed, reactive } from 'vue'
import { fetchDocsDesk, type DeskDoc, type DocsDesk } from './api'
import { commandFilter } from './commandFilter'
import { isoDate } from './schedule'

export interface ShownStack {
  key: string
  /** The stack's name: its goal, or for a stack of documents with no goal the days they were made. */
  name: string
  /** Under the name: the newest page's day, or how many pages a stack with no goal holds. */
  sub: string
  docs: string[]
  /** While the field has words: how many of the pages match, or null. */
  matches: number | null
}
export interface ShownGroup { key: string; name: string; color: string | null; count: number; stacks: ShownStack[] }

export const desk = reactive({
  data: null as DocsDesk | null,
  loaded: false,
  /** The stack laid out over the desk, if any. */
  open: null as string | null,
})

let epoch = 0
export async function loadDesk(): Promise<void> {
  const mine = ++epoch
  try {
    const data = await fetchDocsDesk()
    if (mine !== epoch) return
    desk.data = data
    desk.loaded = true
  } catch {
    // Opening Documents again asks again.
  }
}

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
const WEEKDAYS = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat']
/* The board's own abbreviations ("Sep", not the locale's "Sept"). */
const MONTH = (d: Date) => MONTHS[d.getMonth()]!
const WEEKDAY = (d: Date) => WEEKDAYS[d.getDay()]!

export function shortDay(iso: string): string {
  const d = new Date(iso)
  return `${d.getDate()} ${MONTH(d)}`
}

/** When a document was edited, as its chip says it: the time if today, the day before that ("Today, 07:04", "1 Oct"). */
export function whenEdited(iso: string): string {
  const d = new Date(iso)
  if (isoDate(d) !== isoDate(new Date())) return shortDay(iso)
  return `Today, ${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
}

/** The days a stack's documents were made, as the board writes days: "Thu 1 Oct", "7–15 Sep", "24 Aug – 1 Oct". */
export function daySpan(docs: DeskDoc[]): string {
  const days = docs.map((d) => new Date(d.created_at)).sort((a, b) => a.getTime() - b.getTime())
  const a = days[0]!
  const z = days[days.length - 1]!
  if (isoDate(a) === isoDate(z)) return `${WEEKDAY(z)} ${z.getDate()} ${MONTH(z)}`
  if (a.getMonth() === z.getMonth() && a.getFullYear() === z.getFullYear()) return `${a.getDate()}–${z.getDate()} ${MONTH(z)}`
  return `${a.getDate()} ${MONTH(a)} – ${z.getDate()} ${MONTH(z)}`
}

export const count = (n: number) => `${n} document${n === 1 ? '' : 's'}`

/** A document with no goal has no column, so its stack is its age: a week, a month, a quarter, a year, or more. */
const AGES = [7, 31, 92, 366, Infinity]

const terms = computed(() => commandFilter.text.toLocaleLowerCase().split(/\s+/).filter((t) => t.length > 0))
function matchesWords(doc: DeskDoc): boolean {
  const text = `${doc.title ?? ''} ${doc.path} ${doc.excerpt}`.toLocaleLowerCase()
  return terms.value.every((term) => text.includes(term))
}

export const groups = computed<ShownGroup[]>(() => {
  const data = desk.data
  if (!data) return []
  const searching = terms.value.length > 0
  const matched = (ids: string[]) => (searching ? ids.filter((id) => matchesWords(data.docs[id]!)).length : null)
  const out: ShownGroup[] = []

  if (data.no_goal.length) {
    const now = Date.now()
    const byAge = AGES.map(() => [] as string[])
    for (const id of data.no_goal) {
      const days = (now - new Date(data.docs[id]!.created_at).getTime()) / 86_400_000
      byAge[AGES.findIndex((limit) => days <= limit)]!.push(id)
    }
    const stacks = byAge.filter((ids) => ids.length).map((ids, index) => {
      const docs = ids.map((id) => data.docs[id]!)
      return { key: `age:${index}`, name: daySpan(docs), sub: count(ids.length), docs: ids, matches: matched(ids) }
    })
    out.push({ key: 'no-goal', name: 'No goal', color: null, count: data.no_goal.length, stacks })
  }

  for (const value of data.values) {
    const stacks = value.stacks.map((stack) => ({
      key: `goal:${stack.goal_id}`,
      name: stack.goal_title,
      sub: shortDay(data.docs[stack.docs[0]!]!.updated_at),
      docs: stack.docs,
      matches: matched(stack.docs),
    }))
    out.push({
      key: `value:${value.id ?? 'none'}`, name: value.title ?? 'No value', color: value.color,
      count: stacks.reduce((n, s) => n + s.docs.length, 0), stacks,
    })
  }
  return out
})

export const openStack = computed(() => {
  for (const group of groups.value) {
    const stack = group.stacks.find((s) => s.key === desk.open)
    if (stack) return { ...stack, docs: terms.value.length ? [...stack.docs].sort((a, b) => Number(!matchesWords(desk.data!.docs[a]!)) - Number(!matchesWords(desk.data!.docs[b]!))) : stack.docs }
  }
  return null
})

/** The goal whose stack holds a document, if the desk has been read. */
export function stackGoalOf(id: string): string | null {
  for (const value of desk.data?.values ?? []) {
    for (const stack of value.stacks) if (stack.docs.includes(id)) return stack.goal_title
  }
  return null
}

export function docMatches(id: string): boolean {
  const doc = desk.data?.docs[id]
  return !doc || !terms.value.length || matchesWords(doc)
}
