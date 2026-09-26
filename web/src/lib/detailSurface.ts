// The goal-detail surface's open/close/cache/prefetch slice, extracted from `store.ts` the same
// way `lib/search.ts` and `lib/boardIndex.ts` were when that file first crossed the 750-line
// module cap (ARCHITECTURE.md §2). Same contract as `createSearchActions`: this factory shares
// the store's one reactive state tree and its error reporter — no second state container and no
// transport policy of its own.
//
// No `vue-router` (AC-086/183's dependency cap names it explicitly as absent, and it stays
// absent) — "the URL changes by hash/param only" (AC-107/S-68) is met by hand, but NOT here any
// more: `lib/urlState.ts` projects `openGoalId` onto the fragment and applies Back/Forward back
// onto it. `openGoal`/`closeGoal` below set state and nothing else, so the two of them plus the
// nav's own `closeGoal + setView` pair cannot disagree about what the address bar should say.

import { createGoal, getGoal, patchGoal, type BoardResponse, type GoalDetail } from './api'
import { boardGoalHost, findGoal } from './boardIndex'
import { asOneHistoryStep } from './urlState'
import type { DragState } from './drag'

/** The detail-owned fields in the app's reactive state, plus the two slices the cache sweep has
 *  to consult: the board (which details are worth prefetching) and the drag gesture (when to
 *  yield the lane). Structural, like `SearchState` in `lib/search.ts`. `activeView` is read/written
 *  by `navigateToGoal` below (D248 WP-D) — the same field `store.ts::setView` flips, added here so
 *  a navigation that lands off-board can switch to the Inbox view without a second dep. */
interface DetailState {
  board: BoardResponse | null
  drag: DragState
  openGoalId: string | null
  openGoalVertical: string | null
  openGoalHostKey: string | null
  goalDetail: GoalDetail | null
  goalDetailLoading: boolean
  hasOpenedGoal: boolean
  activeView: 'verticals' | 'inbox' | 'docs'
}

export function createDetailSurface(
  state: DetailState,
  deps: {
    reportError: (err: unknown) => void
    reloadBoard: () => Promise<void>
    /** `store.ts::loadBoard` — D248 WP-D's off-board case (c) reloads at the goal's own anchor
     *  date so its host can be re-resolved on the newly loaded board. */
    loadBoard: (date: string) => Promise<boolean>
    /** `store.ts::openBoardGoalExpanded` — the one "expand column + open" gesture every board
     *  open already goes through (KK ruling 2026-08-17). Taken as a dep so `navigateToGoal`
     *  reuses it rather than re-implementing the expand step. */
    openOnBoard: (id: string) => Promise<void>
  },
) {
  // D226 (KK, 2026-08-14): "data of the items on verticals should be preloaded. Not load when u
  // open." One session-lifetime cache, filled two ways: every detail fetch lands in it, and after
  // each board load an idle-time sweep pulls the details the board can open (best-effort,
  // abandoned when a newer board arrives). `openGoal` paints the cached detail instantly and
  // still revalidates over the network every time, so the cache is never trusted longer than one
  // round-trip — stale-while-revalidate, not a second source of truth.
  const detailCache = new Map<string, GoalDetail>()

  async function fetchGoalDetail(id: string, prefetch = false): Promise<GoalDetail> {
    const detail = await getGoal(id, prefetch)
    detailCache.set(id, detail)
    return detail
  }

  let detailPrefetchGeneration = 0

  function boardDetailIds(): string[] {
    const ids: string[] = []
    for (const column of state.board?.columns ?? []) {
      for (const goal of column.goals) ids.push(goal.id)
    }
    for (const nested of Object.values(state.board?.children ?? {})) {
      for (const child of nested) ids.push(child.id)
    }
    return ids
  }

  function prefetchBoardDetails(): void {
    const generation = detailPrefetchGeneration
    const pending = [...new Set(boardDetailIds())].filter((id) => !detailCache.has(id))
    const worker = async (): Promise<void> => {
      while (pending.length && generation === detailPrefetchGeneration) {
        // A drag owns the main thread: per-move drop-target recomputes are latency-sensitive, and
        // background response handling visibly degrades gesture targeting. Hold the lane until the
        // pointer settles instead of racing it.
        if (state.drag.pending || state.drag.id) {
          await new Promise((resolve) => setTimeout(resolve, 250))
          continue
        }
        const id = pending.shift()
        if (!id) return
        // Revalidate against the CURRENT board, not the sweep-start snapshot: a goal deleted
        // out from under the queue (the user's own remove, or an agent write arriving over
        // D237's live feed) would otherwise still be fetched — a guaranteed 404 on the wire
        // for a detail nothing can open anymore.
        if (!findGoal(state.board, id)) continue
        try {
          await fetchGoalDetail(id, true)
        } catch {
          // Best-effort: a failed prefetch costs nothing — opening fetches live regardless.
        }
      }
    }
    // One lane, not a fan-out: the sweep's only deadline is "before the user opens something",
    // and a single queued request per round-trip keeps the main thread and the connection pool
    // free for whatever the user is actually doing.
    void worker()
  }

  function schedulePrefetchBoardDetails(): void {
    detailPrefetchGeneration += 1
    const idle = (globalThis as { requestIdleCallback?: (cb: () => void) => void }).requestIdleCallback
    if (idle) idle(() => prefetchBoardDetails())
    else setTimeout(prefetchBoardDetails, 300)
  }

  /** Opens the detail surface on `id` — `GoalCard.vue`'s title click and every `GoalDetail.vue`
   *  breadcrumb entry both call this directly (same convention as `completeGoal`/`scheduleGoalTo`:
   *  components reach into the store for their own actions, no emit-and-bubble chain). A cached
   *  detail paints instantly (D226); with a cold cache the previous detail is cleared first so a
   *  fast re-open (breadcrumb click while a detail is already open) never shows a stale body under
   *  the new title while the fetch is in flight. */
  async function openGoal(
    id: string,
    sourceVertical: string | null = state.openGoalVertical,
    hostKey: string | null = state.openGoalHostKey,
  ): Promise<void> {
    state.openGoalId = id
    state.openGoalVertical = sourceVertical
    state.openGoalHostKey = hostKey
    if (hostKey === null) state.hasOpenedGoal = true
    const cached = detailCache.get(id) ?? null
    state.goalDetail = cached
    state.goalDetailLoading = cached === null
    try {
      const detail = await fetchGoalDetail(id)
      // A faster rival open may have landed while this fetch was in flight; the surface belongs
      // to whichever goal is open NOW, so a late response for another id must not repaint it.
      if (state.openGoalId === id) state.goalDetail = detail
    } catch (err) {
      deps.reportError(err)
    } finally {
      if (state.openGoalId === id) state.goalDetailLoading = false
    }
  }

  /** Open a board goal in its own rendered host. Detail-child clicks cannot reuse the parent's
   * host key: doing so leaves the parent's compact title above the child's fetched body. */
  function openBoardGoal(id: string): Promise<void> {
    const host = boardGoalHost(state.board, id)
    return openGoal(id, host?.columnVertical ?? state.openGoalVertical, host?.hostKey ?? null)
  }

  // --- subgoal list in the detail surface (owner ruling 2026-08-09) ---------------------------
  //
  // "There's still not possible to see the subtasks." The children already ride `GET
  // /api/goals/{id}` (`schemas.py::goal_to_detail`, cards not details); these two writes reuse the
  // exact routes the board uses and then re-fetch the open detail, so the modal's list and the
  // board can never disagree about what just happened.

  async function toggleDetailChild(childId: string, done: boolean): Promise<void> {
    const openId = state.openGoalId
    if (!openId) return
    try {
      await patchGoal(childId, { done })
      state.goalDetail = await fetchGoalDetail(openId)
      await deps.reloadBoard()
    } catch (err) {
      deps.reportError(err)
    }
  }

  async function addDetailChild(title: string): Promise<void> {
    const openId = state.openGoalId
    const trimmed = title.trim()
    if (!openId || !trimmed) return
    try {
      await createGoal({ title: trimmed, parent_id: openId })
      state.goalDetail = await fetchGoalDetail(openId)
      await deps.reloadBoard()
    } catch (err) {
      deps.reportError(err)
    }
  }

  // --- navigate-to-goal (D248 WP-D) -----------------------------------------------------------
  //
  // The modal is dead (WP-C) and open cards render in place on the board (WP-B); every path that
  // used to fall back to the modal now navigates to the goal and expands it in place instead — KK
  // ruling, verbatim: "Search simply moves u to vertical. In inbox simply expands as in vertical."
  // `SearchBar.vue`'s result click and `main.ts`'s `#goal/<id>` boot fragment both call this one
  // function; neither hand-rolls host resolution anymore (that duplication is exactly what left
  // the null-host branch summoning the retired modal in the first place).

  /** Shared tail of ladder steps (a) and (c): the goal has (or now has, after a reload) a
   *  resolvable board host, so open it through the same expand+open gesture every board card
   *  click already uses. */
  async function openViaBoardHost(id: string): Promise<void> {
    state.activeView = 'verticals'
    await deps.openOnBoard(id)
  }

  /** Decision ladder:
   *  (a) already on the current board — expand + open there.
   *  (b) no host, and the fetched detail's `vertical` is null — the goal lives in the Maybe/Inbox
   *      bucket (`MAYBE_PREDICATE`: `vertical IS NULL AND parent_id IS NULL`); switch to the Inbox
   *      view and open with the exact host key an Inbox `GoalCard` computes for it
   *      (`detailHostKey` in `GoalCard.vue`), so the surface opens on the SAME rendered card
   *      Inbox itself would mount rather than a stale-default key that matches nothing.
   *  (c) no host, but the detail carries a real `anchor_date` — a dated goal that just is not on
   *      the board that happens to be loaded. Reload at its own anchor date and retry (a)'s path.
   *      A host that still does not resolve after that reload is reported, never swallowed. */
  async function walkToGoal(id: string): Promise<void> {
    if (boardGoalHost(state.board, id)) {
      await openViaBoardHost(id)
      return
    }

    let detail: GoalDetail
    try {
      detail = await fetchGoalDetail(id)
    } catch (err) {
      deps.reportError(err)
      return
    }

    if (detail.vertical === null) {
      state.activeView = 'inbox'
      // Parked goals and parented ideas are absent from the Inbox projection. The shell
      // renders the same GoalCard/detail surface for this explicit host instead of opening
      // a key with no corresponding card.
      const inInbox = state.board?.columns.find(column => column.vertical === null)?.goals.some(goal => goal.id === id)
      await openGoal(id, inInbox ? 'maybe' : 'search', [inInbox ? 'maybe' : 'search', 'root', 0, id].join(':'))
      return
    }

    if (detail.anchor_date === null) {
      deps.reportError(new Error(`navigateToGoal: goal ${id} has a vertical but no anchor_date`))
      return
    }

    await deps.loadBoard(detail.anchor_date)
    if (!boardGoalHost(state.board, id)) {
      state.activeView = 'verticals'
      await openGoal(id, 'search', ['search', 'root', 0, id].join(':'))
      return
    }
    await openViaBoardHost(id)
  }

  /** The ladder above as a single history entry — step (c)'s board reload must not leave a stop
   *  of its own behind the goal it was loading for. */
  function navigateToGoal(id: string): Promise<void> {
    return asOneHistoryStep(() => walkToGoal(id))
  }

  /** Escape (via `KModal`'s own handling, `GoalDetail.vue`) or the modal's scrim/close button both
   *  land here. Guarded against a redundant call (nothing open) so a stray second close is not a
   *  state change `lib/urlState.ts` would have to answer for. */
  function closeGoal(): void {
    if (state.openGoalId === null) return
    state.openGoalId = null
    state.openGoalVertical = null
    state.openGoalHostKey = null
    state.goalDetail = null
  }

  return {
    fetchGoalDetail,
    schedulePrefetchBoardDetails,
    openGoal,
    openBoardGoal,
    navigateToGoal,
    toggleDetailChild,
    addDetailChild,
    closeGoal,
  }
}
