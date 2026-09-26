<script setup lang="ts">
/* Issue 1: navigation, search, areas and agent access share one solid bottom surface.
   Supersedes D10/D111's floating bottom-left navigation and D238's permanent area buttons. */
import { onMounted, onUnmounted, ref } from 'vue'
import Board from './components/Board.vue'
import GoalCard from './components/GoalCard.vue'
import InboxView from './components/InboxView.vue'
import DocsView from './components/DocsView.vue'
import SearchBar from './components/SearchBar.vue'
import CommentsPanel from './components/CommentsPanel.vue'
import DevColorPanel from './components/DevColorPanel.vue'
import DevDeckPanel from './components/DevDeckPanel.vue'
import DevIconPanel from './components/DevIconPanel.vue'
import DevGoalLayoutPanel from './components/DevGoalLayoutPanel.vue'
import { DEV_TUNING_ENABLED } from './lib/devTuning'
import { store } from './store'

/* The shell, not `Board.vue`, owns the day-rollover watcher: it is mounted for the whole life of
   the tab, while `Board` unmounts every time Inbox is active — a planner left on Inbox overnight
   would otherwise come back to yesterday's board. See `store.ts`'s own rollover comment. */
let stopDayRollover: (() => void) | null = null
let stopLiveBoard: (() => void) | null = null
const devPanelsVisible = ref(false)

/* And, by the same argument, the shell owns the DRAG lifecycle (D90). `GoalCard.vue`'s row fires
   `pointerdown` wherever it is rendered, and `InboxView` renders the same card as `Board` does, so
   arming is view-independent — but `Board` unmounted with the release listeners in it. A press
   held past `DESKTOP_HOLD_MS` (200 ms — a synthetic click or a loaded machine reaches it) on an
   Inbox card armed a drag nothing could release: `drag.id` stayed set for the rest of the session
   and that card rendered `goal-card--source-gap-closed`, height 0, in every view after — the goal
   simply vanished from the board. Arm and release must live in the same lifetime, and this is the
   only one that spans both views.

   Not merged into one listener block with the rollover above: these are cleaned up per listener,
   and keeping the pairing visible is the point. */
function onWindowPointerMove(event: PointerEvent) {
  store.pointerMoveDrag(event.clientX, event.clientY, event.altKey)
  if (store.state.drag.id) event.preventDefault()
}
function onWindowPointerUp(event: PointerEvent) {
  // The commit must read the release POSITION, not the last processed move: under background
  // load the browser coalesces pointermoves, and an armed drag can otherwise drop on a target
  // computed several pixels (or one whole card) behind the pointer.
  if (store.state.drag.id) store.pointerMoveDrag(event.clientX, event.clientY)
  store.pointerUpDrag()
}
function onWindowPointerCancel() {
  store.pointerUpDrag(true)
}
function onWindowKeyDown(event: KeyboardEvent) {
  const target = event.target instanceof HTMLElement ? event.target : null
  const editing = target?.closest('input, textarea, select, [contenteditable="true"]') !== null
  if (
    DEV_TUNING_ENABLED
    && !editing
    && !event.repeat
    && !event.altKey
    && !event.ctrlKey
    && !event.metaKey
    && (event.code === 'Backslash' || event.key === '\\' || event.key === 'Backslash')
  ) {
    devPanelsVisible.value = !devPanelsVisible.value
    event.preventDefault()
    return
  }
  if (event.key === 'Alt' && (store.state.drag.pending || store.state.drag.id)) {
    store.setDragCombineMode(true)
    event.preventDefault()
    return
  }
  if (event.key === 'Escape' && (store.state.drag.pending || store.state.drag.id)) {
    store.pointerUpDrag(true)
  }
}
function onWindowKeyUp(event: KeyboardEvent) {
  if (event.key === 'Alt' && (store.state.drag.pending || store.state.drag.id)) {
    store.setDragCombineMode(false)
    event.preventDefault()
  }
}

onMounted(() => {
  stopDayRollover = store.startDayRollover()
  stopLiveBoard = store.startLiveBoard()
  window.addEventListener('pointermove', onWindowPointerMove)
  window.addEventListener('pointerup', onWindowPointerUp)
  window.addEventListener('pointercancel', onWindowPointerCancel)
  window.addEventListener('keydown', onWindowKeyDown)
  window.addEventListener('keyup', onWindowKeyUp)
})
onUnmounted(() => {
  stopDayRollover?.()
  stopDayRollover = null
  stopLiveBoard?.()
  stopLiveBoard = null
  window.removeEventListener('pointermove', onWindowPointerMove)
  window.removeEventListener('pointerup', onWindowPointerUp)
  window.removeEventListener('pointercancel', onWindowPointerCancel)
  window.removeEventListener('keydown', onWindowKeyDown)
  window.removeEventListener('keyup', onWindowKeyUp)
})

const agentState = ref({ available: false, expanded: false, needsYou: false, working: false })
function onAgentState(event: Event) {
  const detail = (event as CustomEvent).detail
  if (detail) agentState.value = { ...agentState.value, ...detail }
}
onMounted(() => {
  window.addEventListener('verticals:agent-state', onAgentState)
  window.dispatchEvent(new CustomEvent('verticals:agent-request-state'))
})
onUnmounted(() => window.removeEventListener('verticals:agent-state', onAgentState))

</script>

<template>
  <div class="app-shell">
    <div v-if="store.state.activeView === 'verticals' && store.state.openGoalVertical !== 'search'" class="board-bottom-fade" data-role="board-bottom-fade" aria-hidden="true"></div>
    <SearchBar id="verticals-command-bar" :agent-available="agentState.available" />
    <div class="app-content">
      <!-- Mutually exclusive (`v-if`/`v-else`), not `v-show`: before ruling 1 (owner, 2026-08-09),
           `InboxView` rendered the same Maybe-bucket goals as Board's own eighth column
           (deliberately — see InboxView.vue's header comment), so keeping both mounted at once
           (`v-show`, tried first) put two `[data-goal-id]`/`.inline-add` nodes on the page for the
           same goal, one of them `display:none` — `test_s63_eight_columns`'s (since renamed,
           `test_s63_seven_columns`) bare `[data-goal-id]` query, `test_s65`'s `count() == 1`
           assertion on the Maybe column's inline-add input, and `test_s66`'s schedule-trigger
           click all resolved to whichever element was first in DOM order, hidden or not, and hung
           or miscounted when that was the wrong copy. Measured live (four of eight `ui` suite
           tests failed), not guessed. Ruling 1 removed the Maybe column from `Board.vue` outright
           (`Board.vue`'s own `dated` computed), so that particular double-render hazard cannot
           recur any more — `v-if`/`v-else` is kept anyway, both because it still matches every
           other pair of alternatives in this app and because `GoalDetail` moved out from under
           `Board` this pass (see `detailMounted`'s own header comment above) specifically so an
           "Inbox" click no longer tears an open goal detail down with it. -->
      <div v-if="store.state.openGoalVertical === 'search' && store.state.openGoalId" class="search-goal-surface">
        <GoalCard :id="store.state.openGoalId" :title="store.state.goalDetail?.title ?? 'Loading…'" :done="!!store.state.goalDetail?.done_at" :color="store.state.goalDetail?.color" :vertical="store.state.goalDetail?.vertical" column-vertical="search" />
      </div>
      <InboxView v-else-if="store.state.activeView === 'inbox'" />
      <DocsView v-else-if="store.state.activeView === 'docs'" />
      <Board
        v-else
        :columns="store.columns.value"
        :show-sample-banner="store.hasSampleData.value"
        @remove-sample="() => void store.removeSample()"
      />
    </div>
  </div>
  <div id="dropdownPortal" aria-live="off"></div>
  <!-- docs/COMMENTS_SPEC.md WP-B2 (KK ruling 2026-08-25, D255): the comments panel is ONE instance
       for the whole app, mounted here rather than by whichever surface (`GoalDetail.vue`,
       `DocDetail.vue`) opened it — a viewport-docked overlay reads as "the sidebar" only if there
       is exactly one of it, positioned against the window, not nested inside a board card or a
       doc pane. It is entirely store-driven (`store.state.comments`) and takes no props; see
       `CommentsPanel.vue`'s own header comment for the full story. -->
  <CommentsPanel />
  <template v-if="DEV_TUNING_ENABLED && devPanelsVisible">
    <DevColorPanel />
    <DevDeckPanel />
    <DevIconPanel />
    <DevGoalLayoutPanel />
  </template>
</template>

<style>
:root { --app-bar-height: 0px; --shadow-float: 0 8px 24px rgba(0,0,0,.12), 0 1px 2px rgba(0,0,0,.08); --radius: 12px; }
.app-shell { display: block; height: 100%; overflow: hidden; background: #fff; }
.board-bottom-fade { position: fixed; inset: auto 0 0; height: 80px; z-index: 299; pointer-events: none; background: linear-gradient(to bottom, rgba(255,255,255,0) 0, #fff 16px, #fff 100%); }
.app-content { box-sizing: border-box; height: 100%; min-width: 0; overflow: hidden; position: relative; }
.search-goal-surface { box-sizing: border-box; max-width: 720px; height: 100%; margin: 0 auto; padding: 32px 16px 80px; overflow-y: auto; }
</style>
