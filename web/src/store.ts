// One reactive board state tree; write helpers mutate records in place for immediate rendering.

import { reactive, computed, type ComputedRef } from 'vue'
import { toast } from '@konstantinopolskii/vue'
import {
  fetchBoard,
  fetchTags,
  createGoal,
  patchGoal,
  scheduleGoal,
  deleteGoal,
  reparentGoal as apiReparentGoal,
  parkGoal as apiParkGoal,
  type BoardResponse,
  type GoalCard,
  type GoalDetail,
  type UpdatePatch,
  type TagMeta,
} from './lib/api'
import {
  ancestorIds,
  boardGoalHost as indexBoardGoalHost,
  findGoal,
  reparentTargets as indexReparentTargets,
} from './lib/boardIndex'
import * as viewState from './lib/boardViewState'
import { createDetailSurface } from './lib/detailSurface'
import { createFamilyView } from './lib/familyView'
import { createGoalDelete } from './lib/goalDelete'
import { createDocsView, createInitialDocsState, type DocsState } from './lib/docsView'
import { createCommentsPanel, createInitialCommentsState, type CommentsState } from './lib/comments'
import { isoDate, localDate } from './lib/schedule'
import { scheduleOrdering, type DragState } from './lib/drag'
import { createDragActions } from './lib/dragActions'
import { toColumnData } from './lib/boardProjection'
import { createDayRollover } from './lib/dayRollover'
import { createSearchActions } from './lib/search'
import { cascadeToastText, verticalMenuLabel, messageForError, placementParentVertical, placementScheduleError } from './lib/scheduleFeedback'
import {
  patchPlacement,
  removePlacement,
  reparentPlacement,
  schedulePlacement,
} from './lib/boardPlacement'
import {
  navigateSchedule,
  resetScheduleView,
  scheduleGrid,
} from './lib/scheduleView'
import { createLiveBoard } from './lib/liveBoard'
import { bump as bumpBoardEpoch, current as currentBoardEpoch } from './lib/boardEpoch'
import type { VerticalScale } from './lib/periods'
import type { BoardColumnData } from './types'
import { carryOver } from './lib/replan'
import { captureRows, slideIntoGroups } from './lib/rollSlide'

/** Today, as the client reads it. Plain `new Date()` — the `ui` suite pins this transparently via
 *  `page.clock.setFixedTime` (`docs/E2E.md` §1 instrumentation entry 3); production reads the real
 *  clock. No test-specific branch anywhere in this file, on purpose. */
export function todayIso(): string {
  return isoDate(new Date())
}
const SAMPLE_TAG = 'sample'

interface State {
  board: BoardResponse | null
  tagMeta: TagMeta[]
  loading: boolean
  /** Failed `loadBoard` message; writes roll back and toast per action instead. */
  error: string | null
  searchQuery: string
  searchTag: string | null
  searchResults: GoalCard[]
  searchTruncated: boolean
  openGoalId: string | null
  /** Board rendering context that owns the inline detail surface. Null keeps the global fallback. */
  openGoalVertical: string | null
  /** Stable rendered-card host. Internal breadcrumb/subgoal navigation reuses this host. */
  openGoalHostKey: string | null
  /** Flow 4: the levels stepped through, the open goal last; its light moves fast while it swaps under the pointer. */
  openPath: string[]
  lightFast: boolean
  goalDetail: GoalDetail | null
  goalDetailLoading: boolean
  activeView: 'verticals' | 'inbox' | 'docs'
  docs: DocsState // D250 WP-3: the whole Docs view slice, owned/typed by `lib/docsView.ts`.
  comments: CommentsState // WP-B: the comments panel slice, owned/typed by `lib/comments.ts`.
  /** D233: the selected value's id (a parentless life-vertical goal), or null for the whole
   *  board. Single-select on purpose (KK ruling 2026-08-15). Every board load carries it. */
  valueFilter: string | null
  /** Mount detail late, then retain it so modal close cleanup always runs. */
  hasOpenedGoal: boolean
  /** Ids whose child lists are locally collapsed. Lists are expanded by default. */
  collapsed: string[]
  /** COMPACT_BOARD_HANDOFF.md §3: the one expanded column (at most one, toggle), or null for
   *  all-compact. Session-only view state by ruling — never persisted, never sent anywhere. */
  expandedVertical: string | null
  /** §5 chain hover: the hovered card's id while a pointer rests on it. Drives the wash class
   *  on every board-visible member of that card's tree. */
  hoverChainId: string | null
  /** Pointer-drag gesture (AC-220/S-145) — see `lib/drag.ts::DragState`'s own doc comment. */
  drag: DragState
}

const state = reactive<State>({
  board: null,
  tagMeta: [],
  loading: false,
  error: null,
  searchQuery: '',
  searchTag: null,
  searchResults: [],
  searchTruncated: false,
  activeView: 'verticals',
  docs: createInitialDocsState(),
  comments: createInitialCommentsState(),
  valueFilter: null,
  openGoalId: null,
  openGoalVertical: null,
  openGoalHostKey: null,
  openPath: [],
  lightFast: false,
  goalDetail: null,
  goalDetailLoading: false,
  hasOpenedGoal: false,
  collapsed: [],
  expandedVertical: null,
  hoverChainId: null,
  drag: {
    pending: null, id: null, x: 0, y: 0, offsetX: 0, offsetY: 0,
    width: 0, height: 0, previewWidth: 0, previewHeight: 0,
    slotWidth: 0, slotHeight: 0,
    slotInsetTop: 0, slotInsetRight: 0, slotInsetBottom: 0, slotInsetLeft: 0,
    sourceVertical: null, sourcePeriodKey: null,
    combineMode: false, target: null, slot: null, settling: null,
  },
})
const { runSearch, loadRecentSearch, filterByTag, clearSearch } = createSearchActions(
  state,
  (err) => toast(messageForError(err)),
)

// --- board loading -------------------------------------------------------------------------

/** D245: bumps the board epoch FIRST — before this call's own `fetchBoard` even starts — so a
 *  user-initiated load (navigation, date change, value filter) always outruns whatever fetch is
 *  already in flight (a live/quiet reload, an older overlapping `loadBoard`). The bump also
 *  covers every `reloadBoard()` call site below, `reloadBoard` being a bare pass-through to this
 *  function: "any write that reloads afterward" needs no reload-site-local bump of its own. The
 *  response then only lands if the epoch this call captured is still current — an answer to a
 *  question a newer load or a newer local write has since superseded is discarded, not applied. */
async function loadBoard(date: string): Promise<boolean> {
  const epoch = bumpBoardEpoch()
  state.loading = true
  state.error = null
  try {
    const [board, tags] = await Promise.all([fetchBoard(date, state.valueFilter), fetchTags()])
    if (currentBoardEpoch() !== epoch) return true
    state.board = board
    state.tagMeta = tags.tags
    schedulePrefetchBoardDetails()
    return true
  } catch (err) {
    if (currentBoardEpoch() !== epoch) return false
    state.error = messageForError(err)
    toast(state.error)
    return false
  } finally {
    state.loading = false
  }
}

/** Re-fetches the same anchor date the board is already showing — the shape every write below
 *  uses to pick up server-side effects it does not model itself (a create's real id and position,
 *  a schedule's new column, a cascade delete's exact remaining rows). `completeGoal` is the one
 *  exception (S-64's one-request rule): it reconciles from the PATCH response instead. */
async function reloadBoard(): Promise<void> {
  await loadBoard(state.board?.anchor_date ?? todayIso())
}

/** D233/D234: single-select value filter (the bottom bar's one action). The reload is the whole
 *  effect — the server owns the filter's semantics (subtree membership, the maybe/life column
 *  exemptions, unknown-id refusal), the client only re-asks with the parameter set. */
async function setValueFilter(value: string | null): Promise<void> {
  if (state.valueFilter === value) return
  state.valueFilter = value
  await reloadBoard()
}

// D237 (KK, 2026-08-15) / D245 (KK, 2026-08-18): the change-feed reload — factory lives in
// `lib/liveBoard.ts` (S-90a's 750-line cap), same factory seam `createSearchActions`/
// `createDetailSurface`/`createDragActions` already use in this file. `quietReload` is also
// `lib/dragActions.ts`'s failure-path resync dep (wired below); see that module's own header
// comment for what "epoch-guarded" and "deferred while a gesture is in flight" mean here.
const { quietReload, startLiveBoard } = createLiveBoard(state, todayIso)

/* Day rollover (D69) — policy lives in `lib/dayRollover.ts`; the store supplies the board. */
const dayRollover = createDayRollover({
  today: todayIso,
  anchorDate: () => state.board?.anchor_date ?? null,
  busy: () => Boolean(state.drag.id || state.drag.settling),
  // The day turned: the carry-over first, so the board it loads holds the day's Replan task (S4.P1.017); the plans left
  // over slide into their groups (S4.P1.013).
  load: async (date) => {
    await carryOver(date)
    const before = captureRows()
    await loadBoard(date)
    await slideIntoGroups(before)
  },
})
const checkDayRollover = dayRollover.check
const startDayRollover = dayRollover.start

/** One goal's live record from anywhere in `state.board` — a column card or a nested subgoal.
 *  Returns a reference into the reactive tree, not a copy (see this file's header comment); the
 *  search itself is `lib/boardIndex.ts`, which owns every pure read over a board payload. */
function findGoalById(id: string): GoalCard | undefined {
  return findGoal(state.board, id)
}

/** The rendered host identity of a board goal — the pure walk lives in `lib/boardIndex.ts`
 *  (`boardGoalHost`); this is the store's thin bind of the current board, same shape as
 *  `reparentTargets` below. */
function boardGoalHost(id: string) {
  return indexBoardGoalHost(state.board, id)
}

function parentVertical(id: string): VerticalScale | undefined {
  return placementParentVertical(state.board, id)
}

/** Same-vertical children are visually nested, but may be scheduled down into another vertical.
 * Reparent/detach still stays blocked: scheduling changes time scale, not family identity. */
function sameVerticalParentId(id: string): string | null {
  const goal = findGoalById(id)
  if (!goal?.parent_id || !goal.vertical) return null
  const parent = findGoalById(goal.parent_id)
  const parentScale = parent?.vertical ?? state.board?.ancestors[id]
    ?.find((ancestor) => ancestor.id === goal.parent_id)?.vertical
  return parentScale === goal.vertical ? goal.parent_id : null
}

// --- board -> component props ---------------------------------------------------------------
//
// `core/board.py`'s wire shape and `types.ts`'s `BoardColumnData`/`GoalCardData` (WP-12) are
// deliberately different shapes (field names, nesting) — this section is the one place that
// reconciles them, so every component downstream renders from the same projection.

const projectedColumns: ComputedRef<BoardColumnData[]> = computed(() => {
  if (!state.board) return []
  const today = new Date()
  const board = state.board
  const projectTags = new Set(state.tagMeta.filter((meta) => meta.project).map((meta) => meta.tag))
  // The board's own anchor, not the clock: every dated column's header names the period the
  // board is currently ON (owner report 2026-08-10). `anchor_date` is always present on a loaded
  // board; the fallback only covers the type, never a real payload.
  const anchor = localDate(board.anchor_date ?? isoDate(today))
  return board.columns.map((c) => toColumnData(c, board, anchor, today, projectTags))
})
/** Which column is wide is laid over the projection, not built into it: widening a column keeps every card's data as it
 *  was, so the cards don't all draw themselves again (flow 4: the first opening's redrawing went from 20.7 to 13.2 ms in a
 *  profile, 29 Sep 2026). */
const columns: ComputedRef<BoardColumnData[]> = computed(() => projectedColumns.value.map((c) => {
  const active = c.vertical !== 'maybe' && c.vertical === state.expandedVertical
  return active === c.active ? c : { ...c, active }
}))

// --- compact board view state (COMPACT_BOARD_HANDOFF.md §3, §5 — KK rulings 2026-08-17) --------
// Behaviour lives in `lib/boardViewState.ts` (lifted for S-90a); the store binds it to `state`.

const toggleExpandedColumn = (vertical: string): void => viewState.toggleExpandedColumn(state, vertical)
const expandColumn = (vertical: string): void => viewState.expandColumn(state, vertical)
const setHoverChain = (id: string | null): void => viewState.setHoverChain(state, id)
const hoverChain: ComputedRef<{ id: string; set: Set<string> } | null> = computed(() =>
  viewState.hoverChainOf(state),
)

/** Show sample controls when any root goal belongs to sample data. */
const hasSampleData: ComputedRef<boolean> = computed(() => {
  if (!state.board) return false
  const roots = state.board.columns.flatMap((c) => c.goals)
  return roots.some((g) => g.parent_id === null && g.tags.includes(SAMPLE_TAG))
})

// --- writes ------------------------------------------------------------------------------------

const completionVersions = new Map<string, number>()

/** Optimistic one-PATCH completion with stale-response protection and rollback. */
async function completeGoal(id: string, done: boolean): Promise<void> {
  const goal = findGoalById(id)
  if (!goal) return
  const version = (completionVersions.get(id) ?? 0) + 1
  completionVersions.set(id, version)
  const previous = goal.done_at
  const wasDone = previous !== null
  goal.done_at = done ? new Date().toISOString() : null
  // Ancestor progress counts done descendants; one completion changes each ancestor by one.
  const delta = (done ? 1 : 0) - (wasDone ? 1 : 0)
  bumpAncestorProgress(id, delta)
  try {
    const updated = await patchGoal(id, { done })
    if (completionVersions.get(id) !== version) return
    goal.done_at = updated.done_at
    // Reconcile: if the server landed somewhere other than the optimistic guess, correct the
    // counters by the difference rather than re-deriving them from a reload.
    const settled = (updated.done_at !== null ? 1 : 0) - (wasDone ? 1 : 0)
    bumpAncestorProgress(id, settled - delta)
  } catch (err) {
    if (completionVersions.get(id) !== version) return
    goal.done_at = previous
    bumpAncestorProgress(id, -delta)
    toast(messageForError(err), { action: 'Retry', onAction: () => void completeGoal(id, done) })
  }
}

/** Adds `delta` to the `done` counter of every ancestor of `id` that this board carries progress
 *  for. `total` never moves — closing a goal does not change how many descendants exist. */
function bumpAncestorProgress(id: string, delta: number): void {
  if (delta === 0 || !state.board) return
  for (const ancestorId of ancestorIds(state.board, id)) {
    const entry = state.board.progress[ancestorId]
    if (entry) entry.done += delta
  }
}

/** Serves both "capture to Maybe" (AC-069: title only, `vertical`/`anchor_date` both null) and
 *  "create on any other visible column" (AC-110-adjacent: schedule the new goal into the column
 *  the inline-add row lives in) from the same call — `board.anchor_date` is, by construction, a
 *  date inside every one of the 7 real-scale columns currently on screen, since each column *is*
 *  "the period containing that anchor date" (`core/board.py`). `verticalBucket` is `Column.vue`'s
 *  own `vertical` prop, which already carries the literal `"maybe"` string for that column
 *  (`toColumnData` above) — so the caller never needs to special-case which column it is. */
async function createGoalOn(verticalBucket: string, title: string): Promise<void> {
  const trimmed = title.trim()
  if (!trimmed) return
  const payload =
    verticalBucket === 'maybe'
      ? { title: trimmed }
      : { title: trimmed, vertical: verticalBucket, anchor_date: state.board?.anchor_date ?? todayIso() }
  try {
    await createGoal(payload)
    await reloadBoard()
  } catch (err) {
    toast(messageForError(err))
  }
}

/** `scheduleGrid.value.anchorDate` turns `(scale, periodKey)` into the real date the schedule wire
 *  wants (`{vertical, anchor_date}`, never a computed `period_key`, AC-010). Popover scheduling
 *  retains its broad reload. Drag scheduling already names a visible destination, so it moves the
 *  local row before the request and reconciles from the returned card without a board refetch. */
async function scheduleGoalTo(
  id: string,
  scale: VerticalScale,
  periodKey: string,
  optimisticDrag = false,
  insertBeforeId: string | null = null,
): Promise<void> {
  const anchor = scheduleGrid.value.anchorDate(scale, periodKey)
  const ordering = optimisticDrag
    ? scheduleOrdering(state.board, id, { insertBeforeId, vertical: scale, periodKey })
    : null
  const placement = optimisticDrag
    ? schedulePlacement(state.board, id, { vertical: scale, periodKey }, anchor, insertBeforeId)
    : null
  try {
    const updated = await scheduleGoal(id, scale, anchor, ordering ?? undefined)
    if (placement) placement.reconcile(updated)
    if (updated.descendants_clamped > 0)
      toast(cascadeToastText(updated.descendants_clamped, verticalMenuLabel(state.board, scale)))
    if (!placement || updated.descendants_clamped > 0) await reloadBoard()
    const open = state.goalDetail
    if (open && open.id !== id && open.children.some((child) => child.id === id)) {
      state.goalDetail = await fetchGoalDetail(open.id)
    }
  } catch (err) {
    placement?.rollback()
    toast(placementScheduleError(err, state.board))
  }
}

/** Card-menu schedule: commit before transport and settle from response without a board GET. */
async function scheduleGoalQuick(id: string, scale: VerticalScale, periodKey: string): Promise<void> {
  const anchor = scheduleGrid.value.anchorDate(scale, periodKey)
  const placement = schedulePlacement(state.board, id, { vertical: scale, periodKey }, anchor)
  try {
    const updated = await scheduleGoal(id, scale, anchor)
    placement?.reconcile(updated)
    if (updated.descendants_clamped > 0) {
      toast(cascadeToastText(updated.descendants_clamped, verticalMenuLabel(state.board, scale)))
      await reloadBoard()
    }
  } catch (err) {
    placement?.rollback()
    toast(placementScheduleError(err, state.board))
  }
}

async function moveGoalToInbox(id: string): Promise<void> {
  // D179's one surviving block (D241 unglued drag detach/reparent): Inbox on a nested child
  // would clear its schedule while the server keeps parent_id, and a parented, unscheduled row
  // renders NOWHERE on the board (MAYBE_PREDICATE needs parent_id NULL) — a vanish, not a move.
  if (sameVerticalParentId(id)) return
  const placement = schedulePlacement(
    state.board,
    id,
    { vertical: null, periodKey: null },
    null,
  )
  try {
    const updated = await scheduleGoal(id, null, null)
    placement?.reconcile(updated)
  } catch (err) {
    placement?.rollback()
    toast(messageForError(err))
  }
}

// `setGoalColor` left with the card menu's colour picker (D231, KK 2026-08-15): colour is
// derived from the value root everywhere the product renders it, so a UI write path would be a
// control whose effect nothing can see. `PATCH color` itself survives (HTTP/MCP, value roots
// only) — that is where value colours are set.

async function parkGoal(id: string): Promise<void> {
  const placement = removePlacement(state.board, id)
  try {
    await apiParkGoal(id)
    placement?.reconcile()
  } catch (err) {
    placement?.rollback()
    toast(messageForError(err))
  }
}

/** S-62: one gesture, no confirmation (pinned, §10-D12 — a confirm dialog would fail the modal-
 *  record assertion outright), removing only the sample chain. Finds the sample root by content
 *  (`tags @> {sample}` and no parent) rather than hardcoding `SAMPLE01`, then issues one
 *  `DELETE ?cascade=true` — `core.goals.delete`'s own body is a single `DELETE ... WHERE id = $1
 *  OR path LIKE $2` inside one `conn.transaction()` (verified in `verticals/core/goals.py`), which
 *  is what makes this "ordered leaf-first inside one transaction" without this file doing any
 *  ordering itself. No-op if no sample root is on the board (button should not be visible then —
 *  see `hasSampleData` — but a stale click racing a second removal must not throw). */
async function removeSample(): Promise<void> {
  if (!state.board) return
  const root = state.board.columns
    .flatMap((c) => c.goals)
    .find((g) => g.parent_id === null && g.tags.includes(SAMPLE_TAG))
  if (!root) return
  try {
    await deleteGoal(root.id, true)
    await reloadBoard()
  } catch (err) {
    toast(messageForError(err))
  }
}

// --- board-surface gestures: collapse, reparent, reorder, delete ------------------------------
//
// Writes plus one purely local view state, all reached from the card itself. Each already had
// a route (`verticals/api/routes_goals.py`) and a typed client function (`lib/api.ts`); what was
// missing was an affordance, which the card interaction layer supplies.
//
// Selection is gone on purpose — owner ruling, 2026-08-09: a plain click OPENS the goal (the
// incumbent's behaviour); click-to-select plus the bulk bar was this board's own invention. Bulk
// update stays reachable over HTTP/MCP only (`PATCH /api/goals` with `ids[]`, S-44/S-133) — the
// F5 manifest records that with a `null` ui_selector, the same shape `reorder` once had.

// Expand/collapse (nested subgoal lists): moved to `lib/boardViewState.ts` (S-90a) — thin binds.
const isCollapsed = (id: string): boolean => viewState.isCollapsed(state, id)
const toggleCollapsed = (id: string): void => viewState.toggleCollapsed(state, id)

// --- reparent (S-67) ---------------------------------------------------------------------------

/** The menu route's target list, from `lib/boardIndex.ts` — a thin bind of the current board so
 *  the card interaction layer reads one argument (the card's own id) and nothing else. */
function reparentTargets(id: string): { id: string; title: string }[] {
  return indexReparentTargets(state.board, id)
}

/** Menu reparent retains its broad reload. Alt-drag already carries a concrete visible target, so
 *  that path updates the local parent/child lists and rollups before the request, then merges the
 *  returned card or rolls the operation back. */
async function reparent(id: string, parentId: string | null, optimisticDrag = false): Promise<void> {
  // D241: no glue clause here anymore — a same-vertical subtask reparents like anything else
  // (the server's own D179 refusal is gone with it). Only the self-parent no-op remains.
  if (id === parentId) return
  const placement = optimisticDrag && parentId
    ? reparentPlacement(state.board, id, parentId)
    : null
  try {
    const updated = await apiReparentGoal(id, parentId)
    if (placement) placement.reconcile(updated)
    else await reloadBoard()
  } catch (err) {
    placement?.rollback()
    toast(messageForError(err))
  }
}

/** D236 (KK, 2026-08-15): a centre-band drop onto a card is "become this card's subtask" —
 *  parentage AND scheduling follow the target ("inherit target's vertical"), and the colour swap
 *  is free because colour is derived from the new value root (D231). Two sequential writes on
 *  purpose: reparent first so the server's hierarchy clamp has the final parent to judge
 *  against, then the schedule write that puts the child in its parent's own column.
 *
 *  D245: `reparent` above already lands its half optimistically. The schedule half now does too
 *  (`schedulePlacement`, unnamed slot — this call never names a drop-target `insertBeforeId`, so
 *  it appends like every other non-drag schedule write) — no reload on success; a failed write
 *  rolls its placement back and toasts, matching the drag-commit paths in `lib/dragActions.ts`. */
async function combineInto(id: string, targetId: string): Promise<void> {
  await reparent(id, targetId, true)
  const parent = findGoalById(targetId)
  const child = findGoalById(id)
  if (!parent || !child) return
  if (child.vertical === parent.vertical && child.anchor_date === parent.anchor_date) return
  const placement = schedulePlacement(
    state.board,
    id,
    { vertical: parent.vertical, periodKey: parent.period_key },
    parent.anchor_date,
  )
  try {
    const updated = await scheduleGoal(id, parent.vertical as VerticalScale | null, parent.anchor_date)
    placement?.reconcile(updated)
  } catch (err) {
    placement?.rollback()
    toast(messageForError(err))
  }
}

async function reparentQuick(id: string, parentId: string | null): Promise<void> {
  if (id === parentId) return
  const placement = reparentPlacement(state.board, id, parentId)
  try {
    const updated = await apiReparentGoal(id, parentId)
    placement?.reconcile(updated)
  } catch (err) {
    placement?.rollback()
    toast(messageForError(err))
  }
}

// The drag gesture's commit layer lives in `lib/dragActions.ts` (S-90a split — the D238-D240
// rounds pushed this module past the 750-line cap). Same factory seam as `createSearchActions`.
const {
  pointerDownCard,
  pointerMoveDrag,
  setDragPreviewSize,
  setDragCombineMode,
  autoScrollDrag,
  pointerUpDrag,
} = createDragActions({
  state,
  findGoalById,
  sameVerticalParentId,
  combineInto,
  scheduleGoalTo,
  anchorDate: (scale, periodKey) => scheduleGrid.value.anchorDate(scale, periodKey),
  quietReload,
  expandedVertical: () => state.expandedVertical,
  expandColumn,
  openFamily: (path, vertical) => family.openFamily(path, vertical), // bound late: the family view is made below
})

// --- delete --------------------------------------------------------------------------------------

const { removeGoal } = createGoalDelete(state) // `lib/goalDelete.ts`

// --- goal detail (S-104, D226) ----------------------------------------------------------------
//
// The whole open/close/cache/prefetch slice lives in `lib/detailSurface.ts` (`createDetailSurface`
// — extracted when this file crossed the 750-line module cap again; same factory contract as
// `createSearchActions` above: shared reactive state, shared error reporter, no second state
// container). The store re-exports its actions unchanged below.
const detail = createDetailSurface(state, {
  reportError: (err) => toast(messageForError(err)),
  reloadBoard,
  loadBoard,
  openOnBoard: (id) => openBoardGoalExpanded(id), // hoisted decl below, called later only
})
const {
  fetchGoalDetail,
  ensureDetail,
  schedulePrefetchBoardDetails,
  openGoal,
  openBoardGoal,
  navigateToGoal,
  toggleDetailChild,
  addDetailChild,
  closeGoal,
} = detail
const family = createFamilyView(state, { openGoal, closeGoal, ensureDetail })

/** Opening a board card expands its column (KK ruling 2026-08-17: card click = expand + open in
 *  one gesture). Central here so direct-URL opens and swapped-face clicks get the same behavior:
 *  a sub-task hidden in a collapsed stack has no rendered detail host until its column unfolds. */
function openBoardGoalExpanded(id: string): Promise<void> {
  const host = indexBoardGoalHost(state.board, id)
  if (host && host.columnVertical !== 'maybe') state.expandedVertical = host.columnVertical
  return openBoardGoal(id)
}

/** Detail edits reconcile card fields from the response. Body editing is already optimistic in
 *  GoalDetail and cards carry only body_chars, so its coalesced PATCH neither replaces newer text
 *  nor reloads the board. Other edits retain broad board reconciliation. */
async function updateGoal(id: string, patch: UpdatePatch, keepalive = false): Promise<void> {
  if (patch.foil !== undefined) {
    const placement = patchPlacement(state.board, id, { foil: patch.foil })
    try {
      const updated = await patchGoal(id, patch, keepalive)
      placement?.reconcile(updated)
      const open = state.goalDetail
      if (open && open.id === id) state.goalDetail = { ...open, ...updated, body: open.body }
    } catch (err) {
      placement?.rollback()
      toast(messageForError(err))
    }
    return
  }
  try {
    const updated = await patchGoal(id, patch, keepalive)
    if (patch.body !== undefined) return
    const open = state.goalDetail
    if (open && open.id === id) {
      state.goalDetail = { ...open, ...updated, body: open.body }
    }
    await reloadBoard()
  } catch (err) {
    toast(messageForError(err))
  }
}

// --- nav (app shell) ------------------------------------------------------------------------

/** App.vue's nav calls this for its two wired items ("Inbox"/"Verticals") only — see App.vue's
 *  own header comment for why the other six nav items (Days..3 years) never call this: no doc
 *  (`docs/JOURNEYS.md`, `docs/E2E.md`) specifies a single-scale view for them, so clicking one is
 *  a no-op today rather than invented navigation. */
function setView(view: 'verticals' | 'inbox' | 'docs'): void {
  state.activeView = view
}

// D250 WP-3: `lib/docsView.ts` owns all Docs-view logic; spread below (not destructured/listed
// like the other factories) to hold the 750-line cap — this module was already at 749.
const docsView = createDocsView(state, {
  reportError: (err) => toast(messageForError(err)),
  navigateToGoal,
  setView,
})

// WP-B: `lib/comments.ts` owns the whole comments-panel slice; same spread-not-destructure shape
// as `docsView` above, for the same reason.
const commentsPanel = createCommentsPanel(state, {
  reportError: (err) => toast(messageForError(err)),
})

export const store = {
  state,
  columns,
  hasSampleData,
  scheduleGrid,
  navigateSchedule,
  resetScheduleView,
  loadBoard,
  reloadBoard,
  checkDayRollover,
  startDayRollover,
  startLiveBoard,
  completeGoal,
  createGoalOn,
  scheduleGoalTo,
  scheduleGoalQuick,
  moveGoalToInbox,
  setValueFilter,
  parkGoal,
  removeSample,
  parentVertical,
  boardGoalHost,
  sameVerticalParentId,
  isCollapsed,
  toggleCollapsed,
  reparentTargets,
  reparent,
  reparentQuick,
  pointerDownCard,
  pointerMoveDrag,
  setDragPreviewSize,
  setDragCombineMode,
  autoScrollDrag,
  pointerUpDrag,
  removeGoal,
  updateGoal,
  toggleDetailChild,
  addDetailChild,
  openGoal,
  ensureDetail,
  openBoardGoal: openBoardGoalExpanded,
  navigateToGoal,
  closeGoal,
  toggleExpandedColumn,
  expandColumn,
  setHoverChain,
  hoverChain,
  ...family,
  runSearch,
  loadRecentSearch,
  filterByTag,
  clearSearch,
  setView,
  ...docsView,
  ...commentsPanel,
}
