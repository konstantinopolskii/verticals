// The sorting task (docs/design-handoff S4.P1, S4.P4): the task in this week that holds the carried plans in its
// document, made and filled by the server once a day (`core/replan.py`); "Replan" opens it as a goal's window with our
// first message sent, and its page waits on the circle (`lib/waiting.ts`).
import { runReplan, type BoardResponse } from './api'

export const REPLAN_TITLE = 'Replan carried-over plans'
export const FIRST_MESSAGE = 'Read this task and its document and help me sort these plans out: where each goes, based on when I planned it and what it belongs to.'

/** The open task, if there is one: in this week since the redesign, in the Inbox before it. */
export function replanTask(board: BoardResponse | null): { id: string; title: string } | null {
  for (const column of board?.columns ?? []) {
    const task = column.goals.find((goal) => goal.title === REPLAN_TITLE && goal.done_at === null && goal.origin === 'app' && !goal.ghost)
    if (task) return { id: task.id, title: task.title }
  }
  return null
}

let ranOn: string | null = null
/** The day's carry-over into the task (S4.P1.017), asked once a day from this tab on start and when the day turns. */
export async function carryOver(today: string): Promise<string | null> {
  if (ranOn === today) return null
  ranOn = today
  try {
    return (await runReplan(today)).task_id
  } catch {
    ranOn = null
    return null
  }
}
