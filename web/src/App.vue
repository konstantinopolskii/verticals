<script setup lang="ts">
/* Issue 1: navigation, search, areas and agent access share one solid bottom surface.
   Supersedes D10/D111's floating bottom-left navigation and D238's permanent area buttons. */
import { onMounted, onUnmounted, ref } from 'vue'
import Board from './components/Board.vue'
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

type NavKey = 'inbox' | 'verticals' | 'docs'
const NAV_ITEMS: { key: NavKey; label: string }[] = [
  { key: 'inbox', label: 'Inbox' },
  { key: 'verticals', label: 'Verticals' },
  { key: 'docs', label: 'Docs' },
]
const search = ref<InstanceType<typeof SearchBar> | null>(null)
const agentState = ref({ available: false, expanded: false, needsYou: false, working: false })

function onAgentState(event: Event) {
  const detail = (event as CustomEvent).detail
  if (detail) agentState.value = { ...agentState.value, ...detail }
}
function openAgent() {
  search.value?.dismiss()
  window.dispatchEvent(new CustomEvent('verticals:agent-open'))
}
function onNavClick(item: (typeof NAV_ITEMS)[number]): void {
  search.value?.dismiss()
  store.closeGoal()
  store.setView(item.key)
  // The Verticals segment always returns to the whole board.
  if (item.key === 'verticals') void store.setValueFilter(null)
}
function onNavKeyDown(event: KeyboardEvent, index: number) {
  let next = index
  if (event.key === 'ArrowRight') next = (index + 1) % NAV_ITEMS.length
  else if (event.key === 'ArrowLeft') next = (index + NAV_ITEMS.length - 1) % NAV_ITEMS.length
  else if (event.key === 'Home') next = 0
  else if (event.key === 'End') next = NAV_ITEMS.length - 1
  else return
  event.preventDefault()
  const item = NAV_ITEMS[next]!
  onNavClick(item)
  document.querySelector<HTMLButtonElement>(`[data-nav-item="${item.key}"]`)?.focus()
}
onMounted(() => {
  window.addEventListener('verticals:agent-state', onAgentState)
  window.dispatchEvent(new CustomEvent('verticals:agent-request-state'))
})
onUnmounted(() => window.removeEventListener('verticals:agent-state', onAgentState))

</script>

<template>
  <div class="app-shell">
    <nav id="verticals-command-bar" class="app-nav" data-cap="nav" aria-label="Workspace">
      <div class="app-nav__links" aria-label="Views">
        <button
          v-for="(item, index) in NAV_ITEMS"
          :key="item.key"
          type="button"
          class="app-nav__link"
          :class="{ 'app-nav__link--active': item.key === store.state.activeView }"
          :data-nav-item="item.key"
          :aria-current="item.key === store.state.activeView ? 'page' : undefined"
          @click="onNavClick(item)"
          @keydown="onNavKeyDown($event, index)"
        >{{ item.label }}</button>
      </div>
      <SearchBar ref="search" class="app-nav__search" :agent-available="agentState.available" />
      <button
        type="button"
        class="app-nav__agent"
        data-cap="agent-open"
        :disabled="!agentState.available"
        :aria-expanded="agentState.expanded"
        :title="agentState.available ? 'Open agent conversation' : 'Agent is unavailable in this browser'"
        @click="openAgent"
      >{{ agentState.needsYou ? 'Agent · needs you' : agentState.working ? 'Agent · working' : 'Agent' }}</button>
    </nav>
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
      <InboxView v-if="store.state.activeView === 'inbox'" />
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
:root { --app-bar-height: 72px; }
.app-shell {
  display: block;
  height: 100%;
  overflow: hidden;
  background: #fff;
}
.app-nav {
  box-sizing: border-box;
  position: fixed;
  inset: auto 0 0;
  z-index: 300;
  height: var(--app-bar-height);
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 12px 16px;
  border-top: 1px solid #dedede;
  background: #fff;
  color: #2d3036;
  font-family: var(--font-body);
}
.app-nav__links {
  flex: 0 0 auto;
  display: flex;
  gap: 2px;
  padding: 0;
  background: #f0f0f0;
  border-radius: 8px;
}
.app-nav__link,
.app-nav__agent {
  box-sizing: border-box;
  display: flex;
  align-items: center;
  justify-content: center;
  height: 44px;
  width: auto;
  padding: 0 12px;
  border: 0;
  border-radius: 6px;
  background: transparent;
  color: #626262;
  font: 400 15px/20px var(--font-body);
  white-space: nowrap;
  cursor: pointer;
}
.app-nav__link:hover,
.app-nav__agent:hover { background: #e7e7e7; color: #2d3036; }
.app-nav__link--active { background: #fff; color: #2d3036; }
.app-nav__agent { flex: 0 0 auto; color: #2d3036; }
.app-nav__agent:disabled { color: #626262; cursor: default; }
.app-nav__link:focus-visible,
.app-nav__agent:focus-visible { outline: 2px solid #2d3036; outline-offset: 2px; }
.app-nav__search { flex: 1 1 auto; min-width: 0; }
.app-content {
  box-sizing: border-box;
  height: calc(100% - var(--app-bar-height));
  min-width: 0;
  overflow: hidden;
  position: relative;
}
@media (max-width: 900px) {
  .app-nav { gap: 8px; padding-inline: 12px; }
  .app-nav__link { padding-inline: 10px; }
}
</style>
