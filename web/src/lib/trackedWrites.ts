// The store's writes a person starts, each made a step of the board's history (docs/design/board-undo.md). The store hands
// over its own verbs; what comes back does the same and records what it changed (`track` in `lib/boardHistory.ts`). The
// components call these through `store`, so every tick, rename, move and reparent counts without a line in any component.
// Lifted out of `store.ts`, which has no lines to spare (S-90a's 750).
import { getGoal, patchGoal, type GoalCard, type UpdatePatch } from './api'
import { PATCH_FIELDS } from './boardShots'
import { makeStep, track } from './boardHistory'
import { createdStep } from './goalSteps'
import { toast } from '../kit'
import { withLine, withNote } from './realign'
import { messageForError } from './scheduleFeedback'
import type { VerticalScale } from './periods'
import { takeOccurrence, withOccurrence } from './repeatSteps'

export interface Writes {
  completeGoal(id: string, done: boolean): Promise<void>
  updateGoal(id: string, patch: UpdatePatch, keepalive?: boolean): Promise<void>
  scheduleGoalTo(id: string, scale: VerticalScale, periodKey: string, optimisticDrag?: boolean, insertBeforeId?: string | null): Promise<void>
  scheduleGoalQuick(id: string, scale: VerticalScale, periodKey: string, day?: string): Promise<void>
  moveGoalToInbox(id: string): Promise<void>
  reparent(id: string, parentId: string | null, optimisticDrag?: boolean): Promise<void>
  reparentQuick(id: string, parentId: string | null): Promise<void>
  combineInto(id: string, targetId: string): Promise<void>
  toggleDetailChild(childId: string, done: boolean): Promise<void>
}

/** The writes that make a goal: they hand back its id (`null` when nothing was made). */
export interface Makes {
  createGoalOn(verticalBucket: string, title: string, periodKey?: string | null): Promise<string | null>
  addDetailChild(title: string): Promise<string | null>
}

/** Whether a patch changes anything the history keeps: not the notes, which have their own undo. */
const undoable = (patch: UpdatePatch): boolean => PATCH_FIELDS.some((field) => field in patch)

export type TrackedWrites = Omit<Writes, 'completeGoal'> & {
  completeGoal(id: string, done: boolean, record?: boolean): Promise<void>
  /** Idk on a carried plan (`lib/realign.ts`): `line` after its notes, then the Inbox, as one step. */
  realignToInbox(id: string, line: string): Promise<void>
  createGoalOn(verticalBucket: string, title: string, periodKey?: string | null): Promise<void>
  addDetailChild(title: string): Promise<void>
}

/** A make that is a step: undo sends the goal to the trash and redo brings it back under its id. */
function made(title: string, make: () => Promise<string | null>): Promise<void> {
  return makeStep(async () => {
    const id = await make()
    return id ? createdStep(id, title.trim()) : null
  })
}

/** A tick, which makes the next occurrence of a goal that repeats: the step takes it back with the tick. */
function ticked(id: string, tick: () => Promise<void>): Promise<void> {
  let occurrence: GoalCard | null = null
  return track(id, async () => {
    await tick()
    occurrence = takeOccurrence(id)
  }, false, (step) => withOccurrence(step, occurrence))
}

export function trackedWrites(raw: Writes & Makes): TrackedWrites {
  return {
    createGoalOn: (verticalBucket, title, periodKey) => made(title, () => raw.createGoalOn(verticalBucket, title, periodKey)),
    addDetailChild: (title) => made(title, () => raw.addDetailChild(title)),
    /** `record: false` for a tick the app makes on its own account (the morning task, once its report is read). */
    completeGoal: (id, done, record = true) => (record ? ticked(id, () => raw.completeGoal(id, done)) : raw.completeGoal(id, done)),
    updateGoal: (id, patch, keepalive) => (undoable(patch) ? track(id, () => raw.updateGoal(id, patch, keepalive)) : raw.updateGoal(id, patch, keepalive)),
    // A move takes the goal's steps with it, so the family is read as well.
    scheduleGoalTo: (id, scale, periodKey, optimisticDrag, insertBeforeId) =>
      track(id, () => raw.scheduleGoalTo(id, scale, periodKey, optimisticDrag, insertBeforeId), true),
    scheduleGoalQuick: (id, scale, periodKey, day) => track(id, () => raw.scheduleGoalQuick(id, scale, periodKey, day), true),
    moveGoalToInbox: (id) => track(id, () => raw.moveGoalToInbox(id), true),
    realignToInbox: (id, line) => {
      // The notes are read first, so the line goes after what is there; then the move, which the step is made of.
      let before = ''
      let after = ''
      return track(id, async () => {
        try {
          before = (await getGoal(id)).body
          after = withLine(before, line)
          await patchGoal(id, { body: after })
        } catch (err) {
          toast(messageForError(err))
          return
        }
        await raw.moveGoalToInbox(id)
      }, true, (step) => withNote(step, before, after))
    },
    reparent: (id, parentId, optimisticDrag) => track(id, () => raw.reparent(id, parentId, optimisticDrag), true),
    reparentQuick: (id, parentId) => track(id, () => raw.reparentQuick(id, parentId), true),
    combineInto: (id, targetId) => track(id, () => raw.combineInto(id, targetId), true),
    toggleDetailChild: (childId, done) => ticked(childId, () => raw.toggleDetailChild(childId, done)),
  }
}
