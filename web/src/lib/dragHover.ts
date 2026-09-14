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

export interface DragHoverCallbacks {
  /** D246: expand this column. `lib/dragActions.ts`'s own wrapper is the one that skips the call
   *  when `vertical` is already the expanded column and schedules the post-render recapture — this
   *  module only decides WHEN to call it (once per distinct column entered, after the dwell). The
   *  one-at-a-time fold-previous law itself lives in `boardViewState.ts::expandColumn`. */
  onExpandColumn: (vertical: string) => void
}

export interface DragHoverController {
  /** Feed every armed pointermove with the column vertical under the pointer (or null off-board). */
  onMove(columnVertical: string | null): void
  /** Clears the dwell timer and forgets the last-seen column. Call on arm (defensively) and on
   *  every release/cancel — no timer may outlive its own gesture. */
  reset(): void
}

export function createDragHover(cb: DragHoverCallbacks): DragHoverController {
  let dwellColumn: string | null = null
  let dwellTimer: ReturnType<typeof setTimeout> | null = null

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
      cb.onExpandColumn(columnVertical)
    }, COLUMN_DWELL_MS)
  }

  return {
    onMove(columnVertical) {
      trackColumnDwell(columnVertical)
    },
    reset() {
      clearDwell()
      dwellColumn = null
    },
  }
}
