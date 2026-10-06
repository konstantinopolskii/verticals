// The Inbox (Inbox and Documents redesign, rounds 3–7, KK 6–7 Oct 2026): everything with no date. What was written today
// stands on top as cards, newest first; the rest lies on shelves by the column each task left. You write in the field,
// which rests open here saying "Write anything"; ↵ puts your words first in Today at once, and the agent, in a turn
// nobody watches, looks for the goal they belong under. The app files the card there and the card shows it. Nothing is
// planned or started. Words the agent reads as a request to it go on as a conversation instead.
import { computed, reactive } from 'vue'
import { createGoal, deleteGoal, fetchInbox, patchGoal, reparentGoal, type InboxGoal } from './api'
import { agentChat, newThread, quietTurn, send } from './agentChat'
import { isoDate } from './schedule'
import { todayIso } from '../store'
import { moving } from './moving'

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
    const { goals } = await fetchInbox()
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

/** The rest, on the shelf of the column each left (`parked_from_vertical`, which the schema keeps whenever a goal has no
 *  date); one with none, Life's. Newest first; an empty shelf isn't shown. */
export const shelves = computed(() => {
  const now = todayIso()
  const older = inbox.goals.filter((g) => dayOf(g.created_at) !== now && g.id !== moving.goalId)
  return SHELVES
    .map(([vertical, name]) => ({ vertical, name, goals: older.filter((g) => (g.parked_from_vertical ?? 'life') === vertical) }))
    .filter((shelf) => shelf.goals.length)
})

export function timeOf(iso: string): string {
  return new Date(iso).toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' })
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
