// The sessions of tasks (docs/design/task-sessions.md): every task's conversation is one session with two doors, Verticals and
// the place it lives, Claude or Codex. The gateway keeps the sessions of each task and watches their files; this reads what it
// knows every couple of seconds (a size and a time on disk, no model, no token) and starts and opens sessions. The web build has
// no gateway, so nothing here runs there.
import { reactive } from '../reactivity'
import { toast } from '../kit'
import { agentChat, agentOf, newThreadWith, send, type GoalRef } from './agentChat'

export interface TaskSession {
  /** The conversation's key: Discuss and the thread list know the session by it. */
  session: string
  provider: string
  title: string
  /** When it last moved (ms): its file's time on disk, or Verticals' last turn in it. */
  movedAt: number
  /** It went on in Claude or Codex without Verticals. */
  outside: boolean
  working: boolean
}
export interface TaskSessions {
  /** Newest first. */
  sessions: TaskSession[]
  /** Some session of the task works now: Verticals' agent is answering, or a file that went on outside is being written. */
  working: boolean
  /** The agent of the newest session that went on outside, until Verticals drives it again. */
  outside: { provider: string; at: number } | null
}

const POLL_MS = 2000
export const taskSessions = reactive({ goals: {} as Record<string, TaskSessions>, now: Date.now() })

interface Wire { session: string; provider: string; title?: string; movedAt: number; outside?: boolean; working?: boolean }
const shape = (wire: Wire): TaskSession => ({
  session: wire.session, provider: wire.provider, title: wire.title ?? '', movedAt: wire.movedAt * 1000,
  outside: !!wire.outside, working: !!wire.working,
})

let lastAnswer = ''
export async function refreshSessions(): Promise<void> {
  if (!agentChat.available) return
  try {
    const res = await fetch('/__chat/sessions')
    if (!res.ok) return
    const text = await res.text()
    taskSessions.now = Date.now()
    if (text === lastAnswer) return // nothing moved: the cards and the lists keep what they show
    const { goals } = JSON.parse(text) as { goals?: Record<string, { sessions: Wire[]; working: boolean; outside: { provider: string; at: number } | null }> }
    const next: Record<string, TaskSessions> = {}
    for (const [id, entry] of Object.entries(goals ?? {})) {
      next[id] = { sessions: entry.sessions.map(shape), working: entry.working,
        outside: entry.outside ? { provider: entry.outside.provider, at: entry.outside.at * 1000 } : null }
    }
    taskSessions.goals = next
    lastAnswer = text
  } catch { /* the gateway is away: what was known stays */ }
}

let timer: ReturnType<typeof setInterval> | null = null
/** Once the agent is there: look now, and again every couple of seconds while the page is in sight. */
export function startSessionWatch(): void {
  void refreshSessions()
  if (timer || typeof window === 'undefined') return
  timer = setInterval(() => { if (document.visibilityState === 'visible') void refreshSessions() }, POLL_MS)
  document.addEventListener('visibilitychange', () => { if (document.visibilityState === 'visible') void refreshSessions() })
}

export const sessionsOf = (goalId: string): TaskSession[] => taskSessions.goals[goalId]?.sessions ?? []

/** "Claude" and "Codex", as a session's row and the menu's list name the agent. */
export const agentName = (provider: string): string => provider === 'claude' ? 'Claude' : provider === 'codex' ? 'Codex' : agentOf(provider).label

/** How long ago, as the menu's list and a session's row say it: "just now", "5 min ago", "3 hours ago", "2 days ago", then the date. */
export function ago(at: number, now: number = taskSessions.now): string {
  const seconds = Math.max(0, Math.round((now - at) / 1000))
  if (seconds < 45) return 'just now'
  const minutes = Math.round(seconds / 60)
  if (minutes < 60) return `${minutes} min ago`
  const hours = Math.round(minutes / 60)
  if (hours < 24) return `${hours} ${hours === 1 ? 'hour' : 'hours'} ago`
  const days = Math.round(hours / 24)
  if (days < 7) return `${days} ${days === 1 ? 'day' : 'days'} ago`
  return new Date(at).toLocaleDateString('en-GB', { day: 'numeric', month: 'short' })
}

/** A session's row in the goal's links, and its line in the menu's list: "Claude · 5 min ago", or "Continued in Claude · 3 min ago"
 *  when it went on without Verticals. */
export const sessionWhen = (session: TaskSession): string => {
  const when = ago(session.movedAt)
  return session.outside ? `Continued in ${agentName(session.provider)} · ${when}` : when
}

/** Open a session where it lives: a Codex thread in the Codex app, a Claude session in the Claude app (the gateway does it). */
export async function openSession(session: TaskSession): Promise<void> {
  try {
    const res = await fetch('/__chat/open', {
      method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ session: session.session }),
    })
    if (res.ok) return
    const { error } = await res.json().catch(() => ({})) as { error?: string }
    toast(error || `${agentName(session.provider)} did not open it`)
  } catch {
    toast(`${agentName(session.provider)} did not open it`)
  }
}

export const START_WORK = 'Start work on this task.'

/** Start work: the agent the task last worked with takes it in a session of its own, in the permission mode of the chat, and
 *  the conversation stays shut: the card shows its turning line while it works, and the field says what it did. */
export async function startWork(goal: GoalRef): Promise<void> {
  if (!agentChat.available) return
  const last = sessionsOf(goal.id)[0]?.provider
  const provider = agentChat.agents.some((agent) => agent.id === last && agent.available) ? last!
    : agentChat.selection?.provider ?? agentChat.agents.find((agent) => agent.available)?.id ?? 'claude'
  newThreadWith(goal, provider)
  agentChat.open = false
  await send(START_WORK)
}

/** "Start work" in a goal's menu: the goal's title is the one its card shows, as Discuss reads it. */
if (typeof window !== 'undefined') {
  window.addEventListener('verticals:start-work', (event) => {
    const { id } = ((event as CustomEvent).detail ?? {}) as { id?: string }
    if (!id) return
    const card = document.querySelector<HTMLElement>(`.goal-card[data-goal-id="${CSS.escape(id)}"] > .goal-card__row .goal-card__title-text`)
    void startWork({ id, title: card?.innerText.trim() || 'Goal' })
  })
}
