// D245 (KK, 2026-08-18): monotonic board-epoch counter, plus the small gesture-aware reload gate
// built on it. A local write that changes placement (an optimistic drag commit, a reorder, a
// reparent, a schedule, a removal — `lib/boardPlacement.ts`'s five mutators all call `bump()` the
// instant they apply, on both the optimistic apply and any later rollback) invalidates every board
// fetch already in flight: `loadBoard`/`liveReload` (store.ts) record `current()` before their own
// `fetchBoard` call and apply the response only if the epoch has not moved since. A response
// describing a world the epoch has since outrun is stale by definition and is discarded, never
// assigned to `state.board`. This is what makes out-of-order `loadBoard`/`liveReload` responses
// harmless instead of a race — the old detach flow's reload-BETWEEN-writes (KK recording
// 2026-08-18 23:38:43, `lib/dragActions.ts`) was exactly this race, papered over by forcing a
// reload to happen between two writes instead of ever making a stale response harmless to land.

import { watch } from 'vue'

let epoch = 0

/** Call the instant a local write changes `state.board`'s placement — before the matching network
 *  write fires, not after: the point is to outrun a fetch already in flight, not to race it. */
export function bump(): number {
  epoch += 1
  return epoch
}

export function current(): number {
  return epoch
}

/** D245's live-reload deferral, generic over what "busy" and "run" mean so store.ts only wires
 *  it, never re-implements it. While `busy()` reads true, a request to run marks one flush
 *  pending instead of firing; the `watch` below fires that single pending flush the moment
 *  `busy()` next turns false, coalescing any number of requests made while busy into it. No
 *  timer anywhere — nothing to leak across repeated gestures, and nothing to cancel either. */
export function createDeferredRun(busy: () => boolean, run: () => void): () => void {
  let pending = false
  watch(busy, (isBusy) => {
    if (!isBusy && pending) {
      pending = false
      run()
    }
  })
  return () => {
    if (busy()) pending = true
    else run()
  }
}
