// What waits for you on the circle (Inbox and Documents redesign, round 5, frames m1–m2; KK 6 Oct 2026: "the morning
// report should be near the |, not near the task"): a document a rule made stands on the field's circle as its page while
// its task is open. The morning report (`core/morning.py`) and Replan (`core/replan.py`) both work this way; yesterday's
// report not dealt with stands beside today's. Only the page opens the document; a click on the task opens the task.
import { computed, reactive, watch } from 'vue'
import { getDoc, getGoal, type GoalCard } from './api'
import { REPLAN_TITLE } from './replan'
import { store } from '../store'

export const MORNING_TITLE = 'Morning report'

export interface WaitingPage {
  taskId: string
  docId: string
  kind: 'morning' | 'replan'
  title: string
  path: string
  excerpt: string
  updated_at: string
  /** The page's one line of facts: when the rule made it. */
  facts: string
}

const pages = reactive(new Map<string, WaitingPage | null>())

/** The rule's open tasks on the board, a carried one included: the morning reports newest first, then Replan. */
export const waitingTasks = computed<GoalCard[]>(() => {
  const found = new Map<string, GoalCard>()
  for (const column of store.state.board?.columns ?? []) {
    for (const goal of column.goals) {
      if (goal.origin === 'app' && goal.done_at === null && (goal.title === MORNING_TITLE || goal.title === REPLAN_TITLE)) {
        if (!found.has(goal.id)) found.set(goal.id, goal)
      }
    }
  }
  const rank = (g: GoalCard) => (g.title === MORNING_TITLE ? 0 : 1)
  return [...found.values()].sort((a, b) => rank(a) - rank(b) || b.created_at.localeCompare(a.created_at))
})

function factsFor(task: GoalCard, kind: WaitingPage['kind']): string {
  if (kind === 'replan') return 'This week · Replan'
  const made = new Date(task.created_at)
  const time = made.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' })
  const day = made.toDateString() === new Date().toDateString()
    ? 'Today'
    : made.toLocaleDateString('en-GB', { weekday: 'short', day: 'numeric', month: 'short' })
  return `${day} · made ${time}`
}

async function resolve(task: GoalCard): Promise<void> {
  pages.set(task.id, null)
  try {
    const detail = await getGoal(task.id)
    const kind = task.title === MORNING_TITLE ? 'morning' : 'replan'
    const link = detail.docs.find((d) => !d.inherited_from && d.path.startsWith(kind === 'morning' ? 'reports/morning/' : 'replan/'))
    if (!link) { pages.delete(task.id); return }
    const doc = await getDoc(link.id)
    pages.set(task.id, { taskId: task.id, docId: doc.id, kind, title: doc.title || doc.path, path: doc.path,
      excerpt: doc.body.slice(0, 1500), updated_at: doc.updated_at, facts: factsFor(task, kind) })
  } catch {
    pages.delete(task.id)
  }
}

watch(waitingTasks, (tasks) => { for (const task of tasks) if (!pages.has(task.id)) void resolve(task) }, { immediate: true })

/** The pages standing on the circle now, in the tasks' order. */
export const waitingPages = computed(() => waitingTasks.value.map((t) => pages.get(t.id)).filter((p): p is WaitingPage => !!p))

/** A document changed: its page reads it again. */
export function refreshWaiting(docId: string): void {
  for (const [taskId, page] of pages) if (page?.docId === docId) pages.delete(taskId)
  for (const task of waitingTasks.value) if (!pages.has(task.id)) void resolve(task)
}
