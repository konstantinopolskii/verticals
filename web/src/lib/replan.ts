// The sorting task (docs/design-handoff S4.P1, S4.P4): the Inbox task that holds the carried plans, made and filled by
// the server once a day; "Replan" opens it as a goal's window with our first message sent.
import { runReplan, type BoardResponse } from './api'

export const REPLAN_TITLE = 'Replan carried-over plans'
export const FIRST_MESSAGE = 'Read this task and help me sort these plans out: where each goes, based on when I planned it and what it belongs to.'

/** The open task in the Inbox, if there is one. */
export function replanTask(board: BoardResponse | null): { id: string; title: string } | null {
  const inbox = board?.columns.find((column) => column.vertical === null)?.goals ?? []
  const task = inbox.find((goal) => goal.title === REPLAN_TITLE && goal.done_at === null && goal.origin === 'app')
  return task ? { id: task.id, title: task.title } : null
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
