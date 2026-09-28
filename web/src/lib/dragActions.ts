// The drag gesture's store-side commit layer — extracted verbatim from `store.ts` when the
// D238-D240 value-filter rounds pushed it past S-90a's 750-line frontend cap (the same factory
// seam `createSearchActions`/`createDetailSurface` already use). `lib/drag.ts` stays the pure
// geometry (hit-testing, targets, patch arithmetic); this module is what a release DOES with
// the target: which write fires, which sound plays, which store verbs run. Deps come in as an
// explicit object because everything here mutates or reads the one reactive state tree the
// store owns — nothing in this file talks to the network except through the deps and the two
// direct imports below (`patchGoal` for the reorder PATCH, placement/feedback helpers for its
// optimistic commit), mirroring exactly what the same lines imported while they lived in
// store.ts.

import { nextTick } from 'vue'
import {
  patchGoal,
  reparentGoal as apiReparentGoal,
  type BoardResponse,
  type GoalCard,
  type UpdatePatch,
} from './api'
import {
  armPointerDown,
  autoScrollAtPointer,
  recaptureRowRects,
  releasePointerDrag,
  reorderWrite,
  setCombineMode,
  trackPointerMove,
  type DragState,
} from './drag'
import { createDragHover, type DragHoverController } from './dragHover'
import { pinRow } from './familyMotion'
import { reorderPlacement, reparentPlacement } from './boardPlacement'
import { messageForError } from './scheduleFeedback'
import { playSound } from './sound'
import { verticalRank, type VerticalScale } from './periods'
import { toast } from '@konstantinopolskii/vue'

export interface DragActionDeps {
  state: { drag: DragState; board: BoardResponse | null }
  findGoalById: (id: string) => GoalCard | undefined
  sameVerticalParentId: (id: string) => string | null
  combineInto: (id: string, targetId: string) => Promise<void>
  scheduleGoalTo: (
    id: string,
    scale: VerticalScale,
    periodKey: string,
    optimisticDrag: boolean,
    insertBeforeId: string | null,
  ) => Promise<void>
  /** `scheduleGrid.value.anchorDate`, bound late — the grid is a computed that follows the
   *  board's own date. */
  anchorDate: (scale: VerticalScale, periodKey: string) => string
  /** D245's failure-path resync: a silent, epoch-guarded refetch (store.ts's own `quietReload` —
   *  the same function the D237 live feed calls, minus its gesture-defer gate, since a resync
   *  fired from a write's own catch block is not a doorbell and must not wait on itself). Used
   *  ONLY when an optimistic landing's write fails after the local placement already committed;
   *  the success path never reloads. */
  quietReload: () => Promise<void>
  /** D246 session view-state read/write — a thin pass to `store.ts`'s own `expandColumn`
   *  (`lib/boardViewState.ts`). Read fresh on every check, never cached here: the board reflows
   *  under an armed drag. */
  expandedVertical: () => string | null
  expandColumn: (vertical: string) => void
  /** Flow 4: open the chain a held-over goal is drawn under plus itself, in its column (`lib/familyView.ts`). */
  openFamily: (path: string[], vertical: string) => Promise<void>
}

/** D246: wait for the DOM to catch up with a hover-driven layout change before trusting row
 *  rects again — `nextTick` (Vue's own patch), one `requestAnimationFrame` (paint settles), then
 *  either a real `transitionend` off the column strip or a timeout sized to the columns' own
 *  measured `transition-duration` (0 today — the flat/product board declares no width transition,
 *  see `Column.vue`'s own CSS — so this resolves right after the paint frame; a future transition
 *  is still honoured without this function changing). */
const RECAPTURE_GRACE_MS = 50

function columnTransitionMs(): number {
  const sample = document.querySelector<HTMLElement>('.pattern-vertical-board__column')
  if (!sample) return 0
  const durations = getComputedStyle(sample).transitionDuration
    .split(',')
    .map((part) => parseFloat(part) * 1000)
    .filter((ms) => !Number.isNaN(ms))
  return durations.length ? Math.max(0, ...durations) : 0
}

function scheduleRecapture(): void {
  void nextTick(() => {
    requestAnimationFrame(() => {
      const wait = columnTransitionMs()
      if (wait <= 0) {
        recaptureRowRects()
        return
      }
      const strip = document.querySelector<HTMLElement>('[data-role="column-strip"]')
      let done = false
      const finish = () => {
        if (done) return
        done = true
        strip?.removeEventListener('transitionend', finish)
        recaptureRowRects()
      }
      strip?.addEventListener('transitionend', finish)
      window.setTimeout(finish, wait + RECAPTURE_GRACE_MS)
    })
  })
}

export function createDragActions(deps: DragActionDeps) {
  const { state } = deps

  const dragHover: DragHoverController = createDragHover({
    onExpandColumn: (vertical, held) => {
      if (vertical === deps.expandedVertical()) return
      // flow 4: the goal the hand holds over stays under it while its column widens, so the hold opens what is there
      const keep = held?.isConnected ? pinRow(held) : null
      deps.expandColumn(vertical)
      if (keep) void nextTick(keep)
      scheduleRecapture()
    },
    onHoldGoal: (row) => {
      const vertical = row.closest<HTMLElement>('[data-vertical]')?.dataset.vertical
      const path = (row.dataset.rowKey ?? '').replace(/~$/, '').split('/').filter(Boolean)
      if (!vertical || vertical === 'maybe' || !path.length || path.includes(state.drag.id ?? '')) return
      void deps.openFamily(path, vertical).then(scheduleRecapture)
    },
  })

  // Pointer drag, not HTML5 `draggable` (`docs/DEPENDENCIES.md` dep cap; `docs/PLANNER_DND.md`
  // §0). `Board.vue` owns the window listener/timer lifecycle; these wrappers keep its mutations
  // in the one state tree.
  function pointerDownCard(
    id: string,
    clientX: number,
    clientY: number,
    rect: DOMRect,
    pointerType: string,
    altKey = false,
  ): void {
    dragHover.reset() // no leaks across repeated gestures (a stray earlier release/cancel path)
    armPointerDown(state.drag, state.board, id, clientX, clientY, rect, pointerType, altKey)
  }
  function pointerMoveDrag(clientX: number, clientY: number, altKey = state.drag.combineMode): void {
    const hit = trackPointerMove(state.drag, state.board, clientX, clientY, altKey)
    // D246: only while actually armed (`hit` is null before the threshold arms the drag) — the
    // dwell timer is meaningless during the pre-arm hold.
    if (hit) dragHover.onMove(hit.columnVertical, clientX, clientY)
  }
  function setDragPreviewSize(width: number, height: number): void {
    if (!state.drag.id || width <= 0 || height <= 0) return
    state.drag.previewWidth = width
    state.drag.previewHeight = height
  }
  function setDragCombineMode(enabled: boolean): void {
    setCombineMode(state.drag, state.board, enabled)
  }
  function autoScrollDrag(): void {
    if (autoScrollAtPointer(state.drag)) {
      const hit = trackPointerMove(state.drag, state.board, state.drag.x, state.drag.y)
      if (hit) dragHover.onMove(hit.columnVertical)
    }
  }

  /** Commits ordered slot. Same group reorders; another dated column schedules.
   *
   *  D253 retires D247's spring-open precondition for "landing inside another card expands its
   *  column, so the spot the drop just landed in stays visible" — with nothing ever folded there
   *  is no sprung card to key the expansion off any more. Re-derived directly off the drop
   *  TARGET below, at each call site that actually lands the dragged goal inside another card
   *  (`combineInto`/`adoptIntoSlot`): `deps.expandColumn` fires with that target's own column
   *  vertical right before the write, matching D244's "card click expands + opens" rule without
   *  any drag-scoped state of its own. */
  function pointerUpDrag(cancelled = false): void {
    const released = releasePointerDrag(state.drag, cancelled)
    dragHover.reset()
    if (!released?.target) return
    const { id, target } = released
    const goal = deps.findGoalById(id)
    if (!goal) return
    const sameVerticalParent = deps.sameVerticalParentId(id)
    if (target.kind === 'combine') {
      // D241 (KK, 2026-08-16): a nested same-vertical subtask combines like anything else —
      // D179's glue made D236's gesture a one-way door (easy in, no out) and is superseded.
      playSound('goal_dragging')
      // D253: landing inside another card expands that card's own column, so the spot the drop
      // just landed in stays visible (D244's "card click expands + opens" rule, re-derived here
      // without D247's retired spring precondition).
      deps.expandColumn(deps.findGoalById(target.targetId)?.vertical ?? 'maybe')
      void deps.combineInto(id, target.targetId)
      return
    }
    const goalVertical = goal.vertical ?? 'maybe'
    const sameGroup = goalVertical === target.vertical
      && (goal.period_key ?? null) === (target.periodKey ?? null)
    if (!sameGroup) {
      if (target.vertical === 'maybe') return
      const scale = target.vertical as VerticalScale
      const anchor = deps.anchorDate(scale, target.periodKey ?? '')
      if (goal.vertical === target.vertical && goal.anchor_date === anchor) return
      playSound('goal_dragging')
      // D242 (KK, 2026-08-16): a glued subtask dragged RIGHTWARD (a longer vertical) outgrows
      // its parent — it splits off and wires to the parent's own parent, so the chain to the
      // value survives one link up. Dragged LEFTWARD it is a slice of the parent scheduled
      // sooner, and the link stays — the chain law D241 preserved, now scoped to that side.
      if (
        goal.vertical !== null
        && sameVerticalParent
        && verticalRank(scale) > verticalRank(goal.vertical as VerticalScale)
      ) {
        void splitAcross(id, sameVerticalParent, scale, target)
        return
      }
      // The slot travels with the move. Dropping above another column's first card used to land
      // the row at the BOTTOM of that column (owner report 2026-08-10): this branch sent the
      // destination and threw `insertBeforeId` away, and a schedule write appends.
      void deps.scheduleGoalTo(id, scale, target.periodKey ?? '', true, target.insertBeforeId)
      return
    }
    // D241/D249: a same-column drop reads the slot's own group owner (`target.parentId`,
    // decided at resolution time by `lib/dragSlots.ts::resolveReorderSlot` — no after-the-fact
    // inference) to decide what the drop means, for BOTH a nested source and a top-level one.
    // Nested source (`sameVerticalParent` set): top-level slot = leave the parent for the
    // grandparent and take the slot (the chain to the value survives one link up, as in D242's
    // split); another card's nested slot (including that card's own APPEND slot, D249) = adopt
    // into that card AT the slot (`adoptIntoSlot`, position-preserving — supersedes the old
    // append-only `combineInto` call, which had no slot parameter at all); its own sibling slot =
    // plain reorder, handled by the ordinary write below. Top-level source (no
    // `sameVerticalParent`): another card's nested slot ALSO adopts it there — this was the
    // confirmed defect (WP-E): the whole slot-owner consultation used to live inside the
    // `sameVerticalParent` gate, so a plain top-level card dropped between another card's
    // subtasks fell straight through to the bare `reorderWrite` below, which never writes
    // `parent_id` — the card was never adopted. No nested slot = plain reorder, unchanged.
    // Cross-column drops above stay as they were (reschedule, parent retained — the chain law,
    // test-pinned).
    const slotParent = target.parentId
    if (sameVerticalParent) {
      if (slotParent !== null && slotParent !== sameVerticalParent) {
        playSound('goal_dragging')
        // D253: same "landing inside expands its column" re-derivation as the combine branch
        // above — `target.vertical` is already this drop's own column identity (`DropTarget`'s
        // reorder variant carries it directly), so no extra lookup is needed here.
        deps.expandColumn(target.vertical)
        void adoptIntoSlot(id, slotParent, target)
        return
      }
      if (slotParent === null) {
        playSound('goal_dragging')
        void detachToSlot(id, sameVerticalParent, target)
        return
      }
    } else if (slotParent !== null) {
      playSound('goal_dragging')
      deps.expandColumn(target.vertical)
      void adoptIntoSlot(id, slotParent, target)
      return
    }
    const write = reorderWrite(state.board, id, target)
    if (write) {
      playSound('goal_dragging')
      void reorderGoal(id, write.patch, target)
    }
  }

  /** D241: a nested subtask dropped on its own column's top-level slot leaves its parent and
   *  takes the slot. It climbs to the parent's own parent, not to nowhere (owner report
   *  2026-08-17: a full detach orphaned the row out of its value chain and it went gray) — the
   *  same one-link-up rule D242's split uses, so both unglue gestures keep the chain to the
   *  value alive.
   *
   *  D245 (KK, 2026-08-18) supersedes this function's old reload-BETWEEN-writes shape — reparent,
   *  reload, reorder, reload — which rendered the same goal twice for the length of that first
   *  reload (KK recording 23:38:43, the primary bug): nested under its old parent from the
   *  pre-reload board AND top-level from the just-applied reparent, until the fetch landed.
   *  `reparentPlacement` now applies FIRST, synchronously, no network involved: the board's own
   *  `parent_id` flips immediately and `lib/boardProjection.ts`'s column filter un-nests the row
   *  the same render tick (a same-vertical card lives in its column's flat `goals` list whether
   *  nested or not — nesting is a projection-time filter over `parent_id`, not array membership —
   *  so no reload was ever needed to make that row render top-level). `reorderWrite` reads the
   *  dragged row's sibling group off `state.board` right after, which is why computing it here —
   *  AFTER the reparent placement, not before — reads the correct group without a reload standing
   *  in between: the stale-board race the old reload was papering over no longer exists because
   *  there is no stale board in between any more, just one already-updated one. Both placements
   *  land in the same synchronous frame, so the user sees the final picture at release; the two
   *  writes then fire in order behind it, invisibly. Either failing rolls back both placements (in
   *  reverse order) and resyncs with one quiet, epoch-guarded reload rather than trusting a board
   *  now missing an unknown subset of what it optimistically applied. */
  async function detachToSlot(
    id: string,
    parentId: string,
    target: { insertBeforeId: string | null },
  ): Promise<void> {
    const grandparentId = deps.findGoalById(parentId)?.parent_id ?? null
    const reparent = reparentPlacement(state.board, id, grandparentId)
    const write = reorderWrite(state.board, id, target)
    const reorder = reorderPlacement(state.board, id, target)
    try {
      const updatedReparent = await apiReparentGoal(id, grandparentId)
      reparent?.reconcile(updatedReparent)
      if (write) {
        const updatedReorder = await patchGoal(id, write.patch)
        reorder?.reconcile(updatedReorder)
      }
    } catch (err) {
      reorder?.rollback()
      reparent?.rollback()
      toast(messageForError(err))
      await deps.quietReload()
    }
  }

  /** D247: the mirror gesture to `detachToSlot` above — a card dropped on ANOTHER card's nested
   *  reorder slot (same column) is adopted as that card's child AT the exact slot the drop aimed
   *  at, whether the dragged card was already nested (own another family) or top-level. This is
   *  the position-preserving replacement for `deps.combineInto`, which has no slot parameter at
   *  all and only ever appends. Same-column only (caller guarantees `sameGroup` before reaching
   *  here) — the vertical/period the source already carries is the same one `parentId`'s family
   *  lives in, so no schedule write follows the reparent, unlike `combineInto`'s own two-verb
   *  shape (D236's vertical-inheritance concern does not arise on a same-column drop).
   *
   *  D245 shape, copied verbatim from `detachToSlot`: `reparentPlacement` lands first,
   *  synchronously — the row moves into `parentId`'s children the same frame, appended by that
   *  mutator — then `reorderWrite` reads the dragged row's sibling group off that
   *  already-updated board (now `parentId`'s own children), so the patch it builds is the actual
   *  move into the aimed-at slot, not a no-op read against the stale group. Both placements land
   *  before either network call, so the user sees the final picture at release; the writes trail
   *  invisibly behind it, reparent then reorder, in that order. Either failing rolls back both
   *  placements (in reverse order) and resyncs with one quiet, epoch-guarded reload rather than
   *  trusting a board now missing an unknown subset of what it optimistically applied. */
  async function adoptIntoSlot(
    id: string,
    parentId: string,
    target: { insertBeforeId: string | null },
  ): Promise<void> {
    const reparent = reparentPlacement(state.board, id, parentId)
    const write = reorderWrite(state.board, id, target)
    const reorder = reorderPlacement(state.board, id, target)
    try {
      const updatedReparent = await apiReparentGoal(id, parentId)
      reparent?.reconcile(updatedReparent)
      if (write) {
        const updatedReorder = await patchGoal(id, write.patch)
        reorder?.reconcile(updatedReorder)
      }
    } catch (err) {
      reorder?.rollback()
      reparent?.rollback()
      toast(messageForError(err))
      await deps.quietReload()
    }
  }

  /** D242: the rightward split — structure verb first (parent's own parent, or top level when
   *  the parent is a root), then the ordinary schedule write into the target column.
   *
   *  D245: the reparent lands optimistically, same frame, same reasoning as `detachToSlot` above;
   *  `deps.scheduleGoalTo`'s own `optimisticDrag` path already places the second write the same
   *  way, so nothing here reloads on success. A failed reparent rolls its placement back and
   *  resyncs with one quiet reload; a failed schedule write is `scheduleGoalTo`'s own concern (it
   *  already rolls back and toasts its own placement without this function's help). */
  async function splitAcross(
    id: string,
    parentId: string,
    scale: VerticalScale,
    target: { insertBeforeId: string | null; periodKey: string | null },
  ): Promise<void> {
    const grandparentId = deps.findGoalById(parentId)?.parent_id ?? null
    const placement = reparentPlacement(state.board, id, grandparentId)
    try {
      const updated = await apiReparentGoal(id, grandparentId)
      placement?.reconcile(updated)
    } catch (err) {
      placement?.rollback()
      toast(messageForError(err))
      await deps.quietReload()
      return
    }
    await deps.scheduleGoalTo(id, scale, target.periodKey ?? '', true, target.insertBeforeId)
  }

  // Reorder within a group (AC-220/S-145). Placement commits before PATCH; the returned card only
  // reconciles server-owned fields such as `position`/`updated_at`. No board read follows this
  // write.
  async function reorderGoal(
    id: string,
    patch: UpdatePatch,
    target: { insertBeforeId: string | null },
  ): Promise<void> {
    const placement = reorderPlacement(state.board, id, target)
    try {
      const updated = await patchGoal(id, patch)
      placement?.reconcile(updated)
    } catch (err) {
      placement?.rollback()
      toast(messageForError(err))
    }
  }

  return {
    pointerDownCard,
    pointerMoveDrag,
    setDragPreviewSize,
    setDragCombineMode,
    autoScrollDrag,
    pointerUpDrag,
  }
}
