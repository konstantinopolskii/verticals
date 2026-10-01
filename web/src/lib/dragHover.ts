// D246: the one hover-driven side effect of an ARMED drag — dwell-expand the column the pointer
// sits over. `lib/drag.ts` stays pure geometry (hit-testing, targets, patch arithmetic, no more
// timers than its existing hold/settle pair); this module is the state machine that reads a
// `PointerHit`'s column identity every armed pointermove and owns the dwell timer that ruling
// asks for. Fed from `lib/dragActions.ts`'s `pointerMoveDrag` wrapper — see that module for the
// callback wiring (session view-state reads/writes and the render+transition wait before each
// `recaptureRowRects()`).
//
// D247 (spring-loaded card open) RETIRED by D253 (KK, 2026-08-21: "remove the change we've done
// with the sub-tasks in collapsed columns ... let's show all sub-task by default now"). A card's
// same-column children are never folded any more, so there is nothing left for a still-hold timer
// to unfold — the half of this module that used to own that timer (`SPRING_OPEN_MS`,
// `SPRING_STILL_TOLERANCE_PX`, the still-hold/fold-back tracking) is deleted outright, not gated.
// The gesture it enabled — "drop between two of another card's subtasks, choosing the exact
// position" — still works: those children are already rendered in the DOM (dwell-expanded or
// not), so `lib/dragSlots.ts::resolveReorderSlot`'s own nested-group bands (D249) resolve the
// drop directly, with no precondition timer in front of them.

/** D246: how long the pointer must sit over one column, un-flapping, before it expands. */
export const COLUMN_DWELL_MS = 200

/** Flow 4 (KK, 28 Sep 2026: "The same while dragging ... Great."): holding a dragged goal over a goal opens it, over a
 *  step goes one level in, over a line above goes back up, exactly as a click there does. About half a second, as the
 *  sketches said: long enough that passing over goals on the way opens nothing, short enough to feel like waiting on it.
 *  Only from a goal's middle, where a drop means "into it" (KK picked it on 29 Sep 2026): its edges, where a drop means
 *  "before it" or "after it", only reorder. A pause there to aim used to open the goal, move the column, and once land
 *  the reorder in the wrong place. */
export const GOAL_HOLD_MS = 500

export interface DragHoverCallbacks {
  /** D246: expand this column. `lib/dragActions.ts`'s own wrapper is the one that skips the call
   *  when `vertical` is already the expanded column and schedules the post-render recapture — this
   *  module only decides WHEN to call it (once per distinct column entered, after the dwell). The
   *  one-at-a-time fold-previous law itself lives in `boardViewState.ts::expandColumn`. `held` is the
   *  goal row the hand is holding over, if any (flow 4): it stays under the hand as the column widens. */
  onExpandColumn: (vertical: string, held: HTMLElement | null) => void
  /** Flow 4: the pointer has held over this goal's row (`GOAL_HOLD_MS`): do what a click on it does. */
  onHoldGoal: (row: HTMLElement) => void
}

export interface DragHoverController {
  /** Feed every armed pointermove with the column vertical under the pointer (or null off-board), where it is, and the
   *  goal a drop there would go into, if any. */
  onMove(columnVertical: string | null, x?: number, y?: number, into?: string | null): void
  /** Clears the dwell timer and forgets the last-seen column. Call on arm (defensively) and on
   *  every release/cancel — no timer may outlive its own gesture. */
  reset(): void
}

export function createDragHover(cb: DragHoverCallbacks): DragHoverController {
  let dwellColumn: string | null = null
  let dwellTimer: ReturnType<typeof setTimeout> | null = null
  let holdRow: string | null = null
  let holdEl: HTMLElement | null = null
  let holdTimer: ReturnType<typeof setTimeout> | null = null

  /* The held row fills with light while the hold runs, as a press held until it fills (goalCard.css): holding reads as
     deliberate, and moving on before it's full opens nothing. */
  function clearHold(): void {
    if (holdTimer !== null) clearTimeout(holdTimer)
    holdTimer = null
    if (holdEl) delete holdEl.dataset.holding // an attribute: Vue rewrites the card's classes
    holdEl = null
  }

  /** The goal row under the pointer (the flying copy takes no pointer), while a drop there would go into it. A new row
   *  restarts the clock, and so does coming back to the middle from an edge; a row that opened stays the same row, so it
   *  never opens twice. */
  function trackGoalHold(x: number, y: number, into: string | null): void {
    const under = document.elementFromPoint(x, y)?.closest<HTMLElement>('.goal-card[data-goal-id]') ?? null
    const row = under && under.dataset.goalId === into ? under : null
    const key = row?.dataset.rowKey ?? null
    if (key === holdRow) return
    clearHold()
    holdRow = key
    if (!row) return
    holdEl = row
    row.dataset.holding = ''
    holdTimer = setTimeout(() => {
      holdTimer = null
      delete row.dataset.holding
      if (row.isConnected) cb.onHoldGoal(row)
    }, GOAL_HOLD_MS)
  }

  function clearDwell(): void {
    if (dwellTimer !== null) clearTimeout(dwellTimer)
    dwellTimer = null
  }

  function trackColumnDwell(columnVertical: string | null): void {
    if (columnVertical === dwellColumn) return
    // A null vertical (off-board) or a changed one both just reset the clock — crossing columns en
    // route must not flap them open (the ruling's own reason the dwell delay exists at all).
    clearDwell()
    dwellColumn = columnVertical
    if (!columnVertical || columnVertical === 'maybe') return
    dwellTimer = setTimeout(() => {
      dwellTimer = null
      cb.onExpandColumn(columnVertical, holdEl)
    }, COLUMN_DWELL_MS)
  }

  return {
    onMove(columnVertical, x, y, into = null) {
      trackColumnDwell(columnVertical)
      if (x !== undefined && y !== undefined) trackGoalHold(x, y, into)
    },
    reset() {
      clearDwell()
      dwellColumn = null
      clearHold()
      holdRow = null
    },
  }
}
