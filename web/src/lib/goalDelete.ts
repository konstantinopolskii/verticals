import { toast } from '@konstantinopolskii/vue'
import { ApiError, deleteGoal, type BoardResponse } from './api'
import { removePlacement } from './boardPlacement'
import { messageForError } from './scheduleFeedback'

/** Deleting a goal from the board. Lifted out of `store.ts` when flow 4 took that module past the 750-line cap again;
 *  same factory seam as `createSearchActions`: the store's one reactive state, no second container. */
export function createGoalDelete(state: { board: BoardResponse | null }) {
  /** `DELETE /api/goals/{id}`, no confirmation dialog — the same shape `removeSample` already ships
   *  and the same reason (§10-D12; a confirm dialog is also a `role="dialog"` node every "this
   *  happened without a modal" assertion in the suite would then see).
   *
   *  A goal with children is `core.goals.delete`'s own `HasChildren` (409), and this does **not**
   *  silently retry with `?cascade=true`: destroying a subtree nobody asked about is a different act
   *  from deleting the row that was clicked. The 409 surfaces as a toast whose action performs the
   *  cascading delete, so the second, larger write is always a second, deliberate click. */
  async function removeGoal(id: string): Promise<void> {
    const placement = removePlacement(state.board, id)
    try {
      await deleteGoal(id)
      placement?.reconcile()
    } catch (err) {
      placement?.rollback()
      if (err instanceof ApiError && err.status === 409) {
        toast('This goal has subgoals.', {
          action: 'Delete all',
          onAction: () => void removeGoalCascade(id),
        })
        return
      }
      toast(messageForError(err))
    }
  }

  async function removeGoalCascade(id: string): Promise<void> {
    const placement = removePlacement(state.board, id, true)
    try {
      await deleteGoal(id, true)
      placement?.reconcile()
    } catch (err) {
      placement?.rollback()
      toast(messageForError(err))
    }
  }

  return { removeGoal, removeGoalCascade }
}
