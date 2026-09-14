import { ApiError, type BoardResponse } from './api'
import { findGoal } from './boardIndex'
import type { VerticalScale } from './periods'

export function messageForError(err: unknown): string {
  return err instanceof ApiError ? err.message : 'Something went wrong.'
}

/** Turn only structured parent-placement refusal into human copy. Other 422s stay raw. */
export function placementScheduleError(err: unknown, board: BoardResponse | null): string {
  if (!(err instanceof ApiError) || err.status !== 422 || !err.body)
    return messageForError(err)
  const body = err.body as Record<string, unknown>
  if (!Array.isArray(body.detail) || !body.detail[0] || typeof body.detail[0] !== 'object')
    return messageForError(err)
  const refusal = body.detail[0] as Record<string, unknown>
  const isPlacement = refusal.field === 'vertical'
    && typeof refusal.child_id === 'string'
    && typeof refusal.child_vertical === 'string'
    && typeof refusal.parent_id === 'string'
    && Object.prototype.hasOwnProperty.call(refusal, 'parent_vertical')
  if (!isPlacement) return messageForError(err)
  const parentId = refusal.parent_id as string
  const parent = findGoal(board, parentId)
  const ancestor = Object.values(board?.ancestors ?? {}).flat()
    .find((candidate) => candidate.id === parentId)
  const title = parent?.title ?? ancestor?.title
  return title
    ? `Subgoals stay at or below their parent — move "${title}" first.`
    : messageForError(err)
}

/** Scheduled parent scale, including an off-period parent carried only in ancestor refs. */
export function placementParentVertical(
  board: BoardResponse | null, id: string,
): VerticalScale | undefined {
  const goal = findGoal(board, id)
  if (!goal?.parent_id) return undefined
  const parent = findGoal(board, goal.parent_id)
  const ancestor = board?.ancestors[id]?.find((candidate) => candidate.id === goal.parent_id)
  return (parent?.vertical ?? ancestor?.vertical ?? undefined) as VerticalScale | undefined
}

/** Board labels originate in `core/vertical.py::menu_label`, including day -> "Today". */
export function verticalMenuLabel(board: BoardResponse | null, scale: VerticalScale): string {
  return board?.columns.find((column) => column.vertical === scale)?.label ?? scale
}

export function cascadeToastText(count: number, label: string): string {
  return `${count} ${count === 1 ? 'subgoal' : 'subgoals'} moved to ${label} with it`
}
