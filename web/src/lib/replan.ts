// Replan over the whole board (docs/design/replan-whole-board.md; KK 21 Oct 2026: "take into account the whole board and
// replan not just one group of due task but refresh the whole due list"): Replan in any box asks the agent, in a conversation
// of its own, to sort out every plan that carried over on the board, all columns at once, in about five minutes. Each plan
// goes with what it takes to judge it: the box it sits in, its own scale and planned date, and what it belongs to. The agent
// reads the board, asks at most three questions with its guesses first (Claude's question tool, shown in the field as its
// asks), writes one document sorted by decision and applies it when you say go (desktop/chat/chat.py's REPLAN_ASK_RULES).
// Nothing is made until you click Replan (Inbox and Documents redesign, round 8).
import { fetchBoard, type BoardResponse } from './api'
import { findGoal } from './boardIndex'
import { store, todayIso } from '../store'

export interface CarriedPlan {
  id: string
  title: string
  /** The box it sits in: the column it carried into (`week`, `month`, …), which can be larger than its own scale. */
  column: string
  /** Its own scale (`goals.vertical`). */
  vertical: string | null
  /** The date it was planned for, which its scale makes a day, a week, a month… */
  anchor_date: string | null
  /** The title of what it belongs to. */
  parent: string | null
}

/** Your words, as your balloon: one sentence; the plans themselves go with it in the message's context. */
export const REPLAN_ASK = 'Sort out every plan that carried over: what matters now, and where each goes.'

/** Every plan that carried over on these boards, each once: the carried rows of each column, those just ticked done left out,
 *  as the boxes leave them out (`lib/boardProjection.ts`). A plan under another carried plan of its box is a plan too. */
export function carriedPlans(boards: (BoardResponse | null)[]): CarriedPlan[] {
  const out: CarriedPlan[] = []
  const seen = new Set<string>()
  for (const board of boards) {
    for (const column of board?.columns ?? []) {
      if (column.vertical === null) continue
      for (const goal of column.goals) {
        if (!goal.ghost || goal.done_at !== null || seen.has(goal.id)) continue
        seen.add(goal.id)
        const parent = goal.parent_id
          ? findGoal(board, goal.parent_id)?.title ?? board?.ancestors[goal.id]?.find((a) => a.id === goal.parent_id)?.title ?? null
          : null
        out.push({ id: goal.id, title: goal.title, column: column.vertical, vertical: goal.vertical, anchor_date: goal.anchor_date, parent })
      }
    }
  }
  return out
}

/** What Replan sends: the carried plans of the board on screen, and of today's whole board when that is not the one on screen.
 *  A box shows carried plans only while its column holds today, so a board paged away from today has fewer, and a value
 *  filter narrows every box; Replan sorts all of them. No request when the board on screen is today's whole board. */
export async function replanPlans(): Promise<CarriedPlan[]> {
  const board = store.state.board
  const whole = board && board.anchor_date === todayIso() && !store.state.valueFilter
    ? null : await fetchBoard(todayIso()).catch(() => null)
  return carriedPlans([board, whole])
}
