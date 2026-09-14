// D237 (KK, 2026-08-15) / D245 (KK, 2026-08-18): the board's change-feed reload — lifted out of
// store.ts to hold its 750-line cap (S-90a), same reasoning `lib/boardViewState.ts`/
// `lib/dragActions.ts` already record (same factory seam those two, and `createSearchActions`/
// `createDetailSurface` before them, already use). `quietReload` is silent and epoch-guarded
// (`lib/boardEpoch.ts`) exactly the way `store.ts`'s own `loadBoard` guards its loud path — this
// is `loadBoard`'s quiet twin, and it doubles as `lib/dragActions.ts`'s failure-path resync dep: a
// write that lands optimistically and then fails needs the identical "discard if stale" fetch,
// not a second implementation of it.
//
// D245 supersedes D237's old "never gated on a drag" clause: a doorbell arriving mid-gesture no
// longer fetches at all — `createDeferredRun` (`lib/boardEpoch.ts`) marks one flush pending and
// fires it the instant `drag.id`/`drag.settling` both clear, coalescing any number of doorbells
// that rang while busy into that single flush. The layout the drag started on is the layout it
// finishes on.

import { startLiveUpdates } from './liveUpdates'
import { createDeferredRun, current as currentBoardEpoch } from './boardEpoch'
import { fetchBoard, fetchTags, type BoardResponse, type TagMeta } from './api'
import type { DragState } from './drag'

export interface LiveBoardState {
  board: BoardResponse | null
  tagMeta: TagMeta[]
  valueFilter: string | null
  drag: DragState
}

export function createLiveBoard(state: LiveBoardState, todayIso: () => string) {
  async function quietReload(): Promise<void> {
    const epoch = currentBoardEpoch()
    try {
      const date = state.board?.anchor_date ?? todayIso()
      const [board, tags] = await Promise.all([fetchBoard(date, state.valueFilter), fetchTags()])
      if (currentBoardEpoch() !== epoch) return
      state.board = board
      state.tagMeta = tags.tags
    } catch {
      // The feed rings again on the next write; a user action reloads anyway. Silence is right.
    }
  }

  const liveReload = createDeferredRun(
    () => Boolean(state.drag.id || state.drag.settling),
    () => void quietReload(),
  )

  /** Start following `/api/events`; returns the stop function (App.vue owns the lifecycle,
   *  mirroring `startDayRollover`). */
  function startLiveBoard(): () => void {
    return startLiveUpdates(liveReload)
  }

  return { quietReload, startLiveBoard }
}
