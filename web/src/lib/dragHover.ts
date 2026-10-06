// The one hover-driven side effect of an ARMED drag: holding over a goal opens it (flow 4). `lib/drag.ts` stays pure
// geometry; this module owns the hold timer. Fed from `lib/dragActions.ts`'s `pointerMoveDrag` wrapper.
//
// D246's dwell-expand is gone: columns keep their width for the whole gesture.
// A column widening under the hand moved every card the pointer was aiming at.
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

/** Flow 4 (KK, 28 Sep 2026: "The same while dragging ... Great."): holding a dragged goal over a goal opens it, over a
 *  step goes one level in, over a line above goes back up, exactly as a click there does. About half a second, as the
 *  sketches said: long enough that passing over goals on the way opens nothing, short enough to feel like waiting on it.
 *  Only from a goal's middle, where a drop means "into it" (KK picked it on 29 Sep 2026): its edges, where a drop means
 *  "before it" or "after it", only reorder. A pause there to aim used to open the goal, move the column, and once land
 *  the reorder in the wrong place. */
export const GOAL_HOLD_MS = 500

export interface DragHoverCallbacks {
  /** Whether holding over this row may open it: only in the wide column, where an open goal fits without a resize. */
  canHold: (row: HTMLElement) => boolean
  /** Flow 4: the pointer has held over this goal's row (`GOAL_HOLD_MS`): do what a click on it does. */
  onHoldGoal: (row: HTMLElement) => void
}

export interface DragHoverController {
  /** Feed every armed pointermove with where the pointer is and the goal a drop there would go into, if any. */
  onMove(x: number, y: number, into: string | null): void
  /** Clears the hold timer. Call on arm (defensively) and on every release/cancel — no timer may outlive its gesture. */
  reset(): void
}

export function createDragHover(cb: DragHoverCallbacks): DragHoverController {
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
    const row = under && under.dataset.goalId === into && cb.canHold(under) ? under : null
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

  return {
    onMove(x, y, into) {
      trackGoalHold(x, y, into)
    },
    reset() {
      clearHold()
      holdRow = null
    },
  }
}
