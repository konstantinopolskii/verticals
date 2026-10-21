// A step's date decides where it shows (docs/design/checklist-steps.md). The owner, 21 Oct 2026: "if u select the date
// specifically, it means that u want to CONTROL it and see in vertical. And if no date is selected, it's more of untracked
// task". A step with a date stands on the board in its column, as every goal does. A step with no date is not on the
// board: its parent, opened in place, lists it after its dated steps (`cardFamily.ts::listKids`), and the Inbox lists it.
//
// Nothing is fetched for it. The board carries every direct child of each goal it draws, the undated ones too
// (`core/board.py`); a goal the board keys no children for, such as an undated step opened in turn, has its own in its
// detail (`GET /api/goals/{id}`), which opening it reads anyway (`detailSurface.ts::fetchGoalDetail`).

import { reactive } from '../reactivity'
import type { BoardResponse, GoalCard, GoalDetail } from './api'

/** The board's columns. A goal window, the Inbox and a search list a goal's steps their own way. */
const BOARD_COLUMNS: ReadonlySet<string> = new Set(['day', 'week', 'month', 'quarter', 'year', 'decade', 'life'])

/** The direct children of every goal whose detail was read. */
const fromDetails = reactive<Record<string, GoalCard[]>>({})

/** Every goal detail read passes through here, so its undated steps can show when it is opened. */
export function noteDetail(detail: GoalDetail): void {
  fromDetails[detail.id] = detail.children
}

/** The steps with no date that a card drawn in `column` lists once it is open, in their order. A step taken off the
 *  board ("To Inbox", `park`) is one of them: it keeps the column it left only as its Inbox shelf (`parked_from_vertical`).
 *  A Life value lists none: what has no date under a value is its ideas, which its detail keeps apart (`core/ideas.py`). */
export function undatedSteps(
  board: BoardResponse | null, card: { id: string; parentId: string | null }, column: string | null | undefined,
): GoalCard[] {
  if (!column || !BOARD_COLUMNS.has(column) || (column === 'life' && card.parentId === null)) return []
  return (board?.children[card.id] ?? fromDetails[card.id] ?? []).filter((goal) => goal.vertical === null)
}

/** An undated step known only from a detail (a step of an undated step), for the writes that look a goal up on the board. */
export function detailStep(id: string): GoalCard | undefined {
  for (const kids of Object.values(fromDetails)) {
    const hit = kids.find((goal) => goal.id === id)
    if (hit) return hit
  }
  return undefined
}
