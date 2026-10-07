// The Inbox (Inbox and Documents redesign, rounds 3–11, KK 6–7 Oct 2026; .local-design/inbox-and-docs/final, section 2):
// everything with no date, and every document. What was written today stands on top, big, the last three and the rest
// behind "N more"; under it Earlier, the older tasks, and Documents, every document newest first, each a row you swipe
// that "Show all" opens in place onto the board's sizes. You write in the field, which rests open here saying "Write to
// inbox"; ↵ puts your words first in Today at once, and the agent, in a turn nobody watches, looks for the goal they
// belong under. The app files the card there and the card shows it. Nothing is planned or started. Words the agent reads
// as a request to it go on as a conversation instead.
import { computed, reactive } from 'vue'
import { createGoal, deleteGoal, fetchUndated, patchGoal, reparentGoal, type InboxGoal } from './api'
import { agentChat, newThread, quietTurn, send } from './agentChat'
import { isoDate } from './schedule'
import { todayIso } from '../store'
import { moving } from './moving'
import { desk } from './docsDesk'
import type { DeskDoc } from './api'

export const SHELVES: ReadonlyArray<readonly [string, string]> = [
  ['day', 'Day'], ['week', 'Week'], ['month', 'Month'], ['quarter', 'Quarter'], ['year', 'Year'], ['decade', '3 years'],
  ['life', 'Life'],
]

export const inbox = reactive({
  goals: [] as InboxGoal[],
  loaded: false,
  /** Cards whose goal the agent is still looking for. */
  finding: [] as string[],
})

let epoch = 0
export async function loadInbox(): Promise<void> {
  const mine = ++epoch
  try {
    const { goals } = await fetchUndated()
    if (mine !== epoch) return
    inbox.goals = goals
    inbox.loaded = true
    const open = new Set(goals.filter((g) => !g.parent).map((g) => g.id))
    inbox.finding = inbox.finding.filter((id) => open.has(id))
  } catch {
    // The next board change asks again.
  }
}

const dayOf = (iso: string) => isoDate(new Date(iso))

/** Written today, newest first (the server's order). */
export const today = computed(() => {
  const now = todayIso()
  return inbox.goals.filter((g) => dayOf(g.created_at) === now && g.id !== moving.goalId)
})

/** Today shows its last three; “N more” unfolds the rest where they are (round 11). */
export const TODAY_SHOWN = 3
/** What is open in place: all of today, Earlier's shelves, Documents' shelves. */
export const inboxView = reactive({ allToday: false, earlier: false, docs: false })

/** The column a task left (`parked_from_vertical`, which the schema keeps whenever a goal has no date); none, Life. */
export const columnOf = (g: InboxGoal): string => g.parked_from_vertical ?? 'life'
export const shelfName = (vertical: string): string => SHELVES.find(([v]) => v === vertical)?.[1] ?? 'Life'

/** Earlier: the tasks written before today, newest first. */
export const earlier = computed(() => {
  const now = todayIso()
  return inbox.goals.filter((g) => dayOf(g.created_at) !== now && g.id !== moving.goalId)
})

/** “Show all” on Earlier: the shelf of the column each task left, in the board's order; an empty shelf isn't shown. */
export const shelves = computed(() => SHELVES
  .map(([vertical, name]) => ({ vertical, name, goals: earlier.value.filter((g) => columnOf(g) === vertical) }))
  .filter((shelf) => shelf.goals.length))

/** Documents: every document, newest edit first, as Finder's Recents (round 8). Read with the Documents desk. */
export const recentDocs = computed<DeskDoc[]>(() => Object.values(desk.data?.docs ?? {})
  .sort((a, b) => b.updated_at.localeCompare(a.updated_at)))

/** A document has no column, so “Show all” puts it on the shelf of its age, by its last edit: today on Day, up to a week
 *  on Week, a month on Month, three on Quarter, a year on Year, older on Life. */
const AGE_LIMITS: ReadonlyArray<readonly [string, number]> = [['day', 0], ['week', 7], ['month', 31], ['quarter', 92], ['year', 366], ['life', Infinity]]
export function ageOf(doc: DeskDoc, now: string = todayIso()): string {
  if (dayOf(doc.updated_at) === now) return 'day'
  const days = (new Date(now).getTime() - new Date(dayOf(doc.updated_at)).getTime()) / 86_400_000
  return AGE_LIMITS.find(([v, limit]) => v !== 'day' && days <= limit)?.[0] ?? 'life'
}
export const docShelves = computed(() => {
  const now = todayIso()
  return SHELVES
    .map(([vertical, name]) => ({ vertical, name, docs: recentDocs.value.filter((d) => ageOf(d, now) === vertical) }))
    .filter((shelf) => shelf.docs.length)
})

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
/** Under an older task: the column it left and the day you wrote it, “Year · 1 Oct”. */
export function leftOn(g: InboxGoal): string {
  const d = new Date(g.created_at)
  return `${shelfName(columnOf(g))} · ${d.getDate()} ${MONTHS[d.getMonth()]}`
}

/** A goal's title holds one line of at most 250 characters (`field_rules.py`): your words are joined into one line, and
 *  longer ones cut at a word with the whole text kept as the goal's description. */
export function wordsToGoal(text: string): { title: string; body?: string } {
  const line = text.replace(/\s+/g, ' ').trim()
  if (line.length <= 250) return { title: line }
  const cut = line.slice(0, 249)
  const at = cut.lastIndexOf(' ')
  return { title: `${(at > 150 ? cut.slice(0, at) : cut).trimEnd()}…`, body: text.trim() }
}

export async function completeInboxGoal(id: string): Promise<void> {
  const index = inbox.goals.findIndex((g) => g.id === id)
  if (index < 0) return
  const [goal] = inbox.goals.splice(index, 1)
  try {
    await patchGoal(id, { done: true })
  } catch {
    inbox.goals.splice(index, 0, goal!)
  }
}

const WARM_UP = (words: string) => `Inbox warm-up. I wrote this down in my Inbox:

«${words}»

Do not change anything: no writes, no plans, no new goals. Read the board (search, board, outline) and find the one existing goal these words belong under. Answer with exactly one line and nothing else:
- goal:<id> for that goal;
- none, if no goal fits;
- ask, if the words are a request to you to do or answer something now.`

/** ↵ in the Inbox: the words land first in Today at once; the agent then looks for their goal. */
export async function writeDown(text: string): Promise<void> {
  const words = text.trim()
  if (!words) return
  const created = await createGoal(wordsToGoal(words))
  inbox.goals.unshift({
    id: created.id, title: created.title, parent: null, value_color: null, parked_from_vertical: created.parked_from_vertical,
    created_at: created.created_at, body_chars: created.body_chars, origin: created.origin, private: false,
  })
  if (!agentChat.available) return
  inbox.finding.push(created.id)
  const reply = (await quietTurn(WARM_UP(words), { inbox: true })).trim()
  const goal = /goal:([A-Za-z0-9]{8})/.exec(reply)?.[1]
  try {
    if (goal && goal !== created.id) {
      await reparentGoal(created.id, goal)
    } else if (/^ask\b/i.test(reply)) {
      // A request, not a note: it goes on as a conversation, and the card it briefly was goes away.
      await deleteGoal(created.id)
      inbox.goals = inbox.goals.filter((g) => g.id !== created.id)
      newThread()
      agentChat.open = true
      agentChat.engaged = true
      void send(words)
    }
  } catch {
    // The card stays where it landed, with no goal.
  }
  inbox.finding = inbox.finding.filter((id) => id !== created.id)
  await loadInbox()
}
