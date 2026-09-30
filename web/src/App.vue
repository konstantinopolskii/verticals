<script setup lang="ts">
/* Issue 1: navigation, search, areas and agent access share one solid bottom surface.
   Supersedes D10/D111's floating bottom-left navigation and D238's permanent area buttons. */
import { nextTick, onMounted, onUnmounted, ref } from 'vue'
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
import DevTuningPanel from './components/DevTuningPanel.vue'
import './lib/look'
import { DEV_TUNING_ENABLED } from './lib/devTuning'
import { store, todayIso } from './store'
import { commandFilter } from './lib/commandFilter'
import { agentChat, currentThread, openForGoal, openThread, send, startAgentChat } from './lib/agentChat'
import { carryOver, FIRST_MESSAGE, replanTask } from './lib/replan'
import { closeWindows, frontWindow, openWindow, outOfFocus, stepWindow, windows } from './lib/windows'
import WindowStack from './components/WindowStack.vue'
import AgentConversation from './components/AgentConversation.vue'
import AgentStep from './components/AgentStep.vue'
import AgentTag from './components/AgentTag.vue'

/* The shell, not `Board.vue`, owns the day-rollover watcher: it is mounted for the whole life of
   the tab, while `Board` unmounts every time Inbox is active — a planner left on Inbox overnight
   would otherwise come back to yesterday's board. See `store.ts`'s own rollover comment. */
let stopDayRollover: (() => void) | null = null
let stopLiveBoard: (() => void) | null = null
const devPanelsVisible = ref(false)
const searchBar = ref<InstanceType<typeof SearchBar> | null>(null)

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

/* The conversation (docs/design-handoff S2.P1–S2.P6): your words rise into it, the field is the circle again and the
   board goes out of focus; a click on the board sends it away into the circle. No agent, and ↵ does nothing. */
/* The goal conversation Discuss is opening; a message sent meanwhile waits for it. */
let goalOpening: Promise<void> | null = null
async function onSubmit(text: string): Promise<void> {
  if (!agentChat.available) return
  agentChat.open = true
  agentChat.engaged = true
  commandFilter.text = ''
  ;(document.activeElement as HTMLElement | null)?.blur()
  if (goalOpening) await goalOpening
  const front = frontWindow.value
  if (front?.kind === 'goal' && currentThread.value?.goal?.id !== front.target) await openForGoal({ id: front.target, title: front.title })
  void send(text)
}
function onVeilClick(): void {
  agentChat.open = false
}
/* Links in the conversation: a document or a web page opens as a window in the centre, at the part the link names
   (S3.P4); a goal or a board date moves the board in place. */
function onConversationLink(url: string, web: boolean, from: Element | null): void {
  if (web) {
    openWindow({ kind: 'page', target: url, title: new URL(url).hostname }, from)
    agentChat.open = false
    return
  }
  const doc = /^#doc\/([^#]+)(?:#(.+))?$/.exec(url)
  if (doc) {
    openWindow({ kind: 'doc', target: decodeURIComponent(doc[1]!), title: from?.textContent?.trim() || 'Document',
      part: doc[2] ? decodeURIComponent(doc[2]) : undefined }, from)
    agentChat.open = false
    return
  }
  agentChat.open = false
  closeWindows()
  if (url.startsWith('#')) { location.hash = url; return }
  history.pushState(history.state, '', url)
  window.dispatchEvent(new PopStateEvent('popstate', { state: history.state }))
}
/* Discuss with agent: the goal pops out of its row into a window, the board goes out of focus, and the goal's latest
   conversation rises over the card (S3.P2.002, S3.P1.002). */
function onDiscussGoal(event: Event): void {
  const { id, session } = ((event as CustomEvent).detail ?? {}) as { id?: string; session?: string }
  if (!id || !agentChat.available) return
  const row = document.querySelector<HTMLElement>(`.goal-card[data-goal-id="${CSS.escape(id)}"] > .goal-card__row`)
  const title = row?.querySelector<HTMLElement>('.goal-card__title-text')?.innerText.trim() || 'Goal'
  openWindow({ kind: 'goal', target: id, title }, row)
  if (session) openThread(session, { id, title })
  else goalOpening = openForGoal({ id, title }).finally(() => { goalOpening = null })
  agentChat.open = true
  agentChat.engaged = true
  // The menu that asked gives its focus back on its next tick; the field takes it after that (S3.P2.016).
  void nextTick(() => nextTick(() => searchBar.value?.focusField()))
}
/* "Replan": the task pops out as a goal's window with its conversation over it, and our first message goes from you
   when the task has no conversation yet (S4.P4.004-.006, .032). */
async function onReplan(event: Event): Promise<void> {
  const from = ((event as CustomEvent).detail?.from ?? null) as Element | null
  let task = replanTask(store.state.board)
  if (!task && await carryOver(todayIso())) {
    await store.reloadBoard()
    task = replanTask(store.state.board)
  }
  if (!task || !agentChat.available) return
  openWindow({ kind: 'goal', target: task.id, title: task.title }, from)
  agentChat.open = true
  agentChat.engaged = true
  goalOpening = openForGoal(task).finally(() => { goalOpening = null })
  await goalOpening
  if (!agentChat.history.some((e) => e.t === 'user')) void send(FIRST_MESSAGE)
}
/* Esc, when nothing smaller takes it, sends the windows away; ⌘[ and ⌘] move one window (S3.P2.011, S3.P3.017). */
function onWindowsKey(event: KeyboardEvent): void {
  if (!windows.list.length || event.defaultPrevented) return
  const target = event.target instanceof HTMLElement ? event.target : null
  if ((event.metaKey || event.ctrlKey) && (event.key === '[' || event.key === ']')) {
    event.preventDefault()
    stepWindow(event.key === '[' ? -1 : 1)
    return
  }
  if (event.key === 'Escape' && !target?.closest('input, textarea, [contenteditable="true"], [role="dialog"], [role="menu"]')) {
    event.preventDefault()
    if (agentChat.open) agentChat.open = false
    else closeWindows()
  }
}
onMounted(() => {
  void startAgentChat()
  window.addEventListener('verticals:discuss-goal', onDiscussGoal)
  window.addEventListener('verticals:replan', onReplan)
  window.addEventListener('keydown', onWindowsKey)
  void carryOver(todayIso())
})
onUnmounted(() => {
  window.removeEventListener('verticals:discuss-goal', onDiscussGoal)
  window.removeEventListener('verticals:replan', onReplan)
  window.removeEventListener('keydown', onWindowsKey)
})

</script>

<template>
  <div class="app-shell">
    <div v-if="store.state.activeView === 'verticals' && store.state.openGoalVertical !== 'search' && !outOfFocus" class="board-bottom-fade" data-role="board-bottom-fade" aria-hidden="true"></div>
    <div class="app-veil" :class="{ 'is-shown': outOfFocus }" data-role="out-of-focus" aria-hidden="true" @click="onVeilClick"></div>
    <WindowStack />
    <AgentConversation @link="onConversationLink" />
    <AgentStep />
    <SearchBar id="verticals-command-bar" ref="searchBar" :agent-available="agentChat.available" @submit="onSubmit">
      <template #agent-tag><AgentTag /></template>
    </SearchBar>
    <div class="app-content" :class="{ 'app-content--out-of-focus': outOfFocus }">
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
    <DevTuningPanel />
  </template>
</template>

<style>
:root { --app-bar-height: 0px; --radius: 12px; }
.app-shell { display: block; height: 100%; overflow: hidden; background: #fff; }
.board-bottom-fade { position: fixed; inset: auto 0 0; height: 80px; z-index: 299; pointer-events: none; background: linear-gradient(to bottom, rgba(255,255,255,0) 0, #fff 16px, #fff 100%); }
.app-content { box-sizing: border-box; height: 100%; min-width: 0; overflow: hidden; position: relative;
  transition: filter var(--vt-dur-sent) var(--vt-ease-large); }
/* Out of focus (S2.P6): the board blurred until no word reads, under a light veil; only while the conversation or a
   window is open. Its layer stays composited while it is, so WebKit doesn't stall (unknowns.md section 4). */
.app-content--out-of-focus { filter: blur(var(--vt-focus-blur)) saturate(var(--vt-focus-saturate)); will-change: filter; pointer-events: none; }
.app-veil { position: fixed; inset: 0; z-index: 280; background: var(--vt-focus-veil); opacity: 0; visibility: hidden;
  transition: opacity var(--vt-dur-sent) var(--vt-ease-large), visibility 0s linear var(--vt-dur-sent); }
.app-veil.is-shown { opacity: 1; visibility: visible; transition: opacity var(--vt-dur-sent) var(--vt-ease-large), visibility 0s; }
@media (prefers-reduced-motion: reduce) {
  .app-content, .app-veil, .app-veil.is-shown { transition-duration: var(--vt-crossfade); }
}
.search-goal-surface { box-sizing: border-box; max-width: 720px; height: 100%; margin: 0 auto; padding: 32px 16px 80px; overflow-y: auto; }
</style>
