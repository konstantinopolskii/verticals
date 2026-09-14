<script setup lang="ts">
/* The application shell: full-viewport content with a compact fixed nav, replacing main.ts's old direct
   `h(SearchBar), h(Board)` mount. Geometry was `docs/UI_MEASURED.md` §1, re-probed live against
   the committed reference fixtures (`tests/uidiff/reference/{board,inbox,search}.html`) rather
   than trusted blind — all three surfaces shared one shell (`.App [0,0,1458,739]`, nav
   `[0,0,310,739]`, content pane `[310,0,1148,739]`).

   Nav is now 240px wide, items starting 10px from the window's left edge, not the measured 310px
   (70px empty rail + 240px panel) above — owner ruling (2026-08-09): "from the items we have
   extra space that is not needed make the space simple 10px from the left side." The rail carried
   no content and nothing since the original measurement ever claimed it, so it is gone outright
   rather than kept and hidden; content pane width follows the nav's own `flex: 1 1 auto`
   automatically and needed no number of its own changed. See `.app-nav`'s own style comment below
   for the exact before/after.

   Hand-rolled, not `KApp`/`KSidebar`/`KNavGroup` — a deliberate, documented deviation from using
   a kit *component* here (the kit's own CSS tokens/classes are still used throughout: --space-*,
   --color-border, KField via SearchBar). Each kit component was checked against the target shape
   and did not fit:
     - `KApp`: a 3-pane doc-site grid (sidebar/.book/inspector) with a max-width-capped reading
       column and a forced inspector pane — wrong shape for a 2-pane product shell.
     - `KSidebar`: single-band padding, no rail concept, no explicit width — this shell needs a
       310px = 70px rail + 240px bordered panel split the kit has no equivalent for.
     - `KSidebarNav`: a scroll-spy TOC generator over `.book__section` headings
       (IntersectionObserver-driven) — irrelevant to a static, three-item menu (ruling 2, owner,
       2026-08-09, trimmed this from eight — see `NAV_ITEMS`'s own comment below).
     - `KNavGroup`: always renders a heading element (`nav-group__head` link or `<h4>`) — this
       menu has no heading at all (`SubMenu-block` in the reference is a bare link list). A real
       kit gap for a headingless flat menu, not worked around by force-fitting it here.
   Revert path: this file and `InboxView.vue` are net-new (delete them), plus the four `store.ts`
   lines marked "nav (app shell)" and `main.ts`'s one changed import/mount call — nothing here
   edits kit source or overrides a kit CSS rule, so there is nothing upstream to unwind. */
import { computed, onMounted, onUnmounted, ref } from 'vue'
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

/** `NavItem` shape per the kit's own `index.d.ts` (`{ label, href, current? }`) is not used
 *  verbatim: there is no `vue-router` in this app (dependency cap, `docs/DEPENDENCIES.md`) and no
 *  page navigation happens here at all — every item is an in-place content-pane swap or (for the
 *  one remaining unwired item) a no-op, never a URL. `href` would be a value nothing reads, so
 *  `key`/`wired` replace it; `label` is carried over unchanged since it is the one field this menu
 *  actually needs from that shape. `current` becomes the `store.state.activeView` comparison below
 *  instead of a per-item boolean, since exactly one of two (not three) views is ever active.
 *
 *  Ruling 2 (owner, 2026-08-09): "Remove tabs days weeks months quarters and years from left
 *  menu." Supersedes this array's own prior claim to be `tools/uiref/render.mjs`'s literal,
 *  pinned eight-item list — that pin describes the *reference* fixture's nav, used for the S-100/
 *  S-101 pixel gate, which `tests/harness/report.py::backlog` already defers for unrelated
 *  reasons (`docs/PENDING_DOC_FIXES.md` row 85) and stays deferred; this array no longer tracks
 *  it and the two are allowed to disagree. Five items are gone outright (`days`, `weeks`,
 *  `months`, `quarters`, `years`) — removed, not hidden, per the owner's own word "remove".
 *
 *  The owner now keeps only the two real view switches. The scale labels are board columns, not
 *  navigation destinations, so no third tab is needed.
 *
 *  D250 WP-3: a third, real view switch joins them — "Docs", documents as first-class residents
 *  alongside goals. Same in-place content-pane swap as the other two, no URL of its own beyond
 *  the `#doc/<id>` fragment `main.ts`'s boot path reads (mirroring `#goal/<id>`). */
type NavKey = 'inbox' | 'verticals' | 'docs'
const NAV_ITEMS: { key: NavKey; label: string; wired: boolean }[] = [
  { key: 'inbox', label: 'Inbox', wired: true },
  { key: 'verticals', label: 'Verticals', wired: true },
  { key: 'docs', label: 'Docs', wired: true },
]

/* D238 (KK, 2026-08-15, correcting D234): the value filter lives HERE, as more items in the one
 * nav row this shell already has — "Inbox | Verticals | Money | Health | Family" — not in an
 * invented bottom pill bar with colour dots (that component is gone). Same `.app-nav__link`
 * class, plain text, no colour identity in the menu: the board's cards already wear the derived
 * colour (D231), the menu does not repeat it. "Verticals" doubles as the unfiltered board, so no
 * separate "All" button exists; a value click from Inbox switches to the board filtered. */
/* D240: sourced from the board's own `values` list, NOT the life column — a selected value
 * narrows the life column with the rest of the board, and a menu read off the column would
 * collapse to the one active button, eating its own escape hatch. `values` is unfiltered by
 * contract (core/board.py). */
const values = computed(() => store.state.board?.values ?? [])

/* D239: each element of the menu is ONE word — the value's explicit `short_label` (set via
 * MCP/API, value roots only), falling back to the title's first word for values that have not
 * been given one yet. The full title never renders in the nav. */
function valueLabel(id: string, title: string): string {
  return store.state.board?.short_labels?.[id] ?? title.split(/\s+/)[0] ?? title
}

function onNavClick(item: (typeof NAV_ITEMS)[number]): void {
  if (item.key === 'inbox' || item.key === 'verticals' || item.key === 'docs') {
    // Closes any open goal detail through the same path the X button/Escape use. `GoalDetail` no
    // longer risks losing `KModal`'s close-side cleanup here — it is mounted at this file's own
    // level now (see `detailMounted`'s header comment above), not as a child `Board` could tear
    // down mid-close — but switching the main nav section while a goal's detail is still open is
    // still a real state change worth resolving deliberately rather than leaving stale, so the
    // close stays.
    store.closeGoal()
    store.setView(item.key)
    // "Verticals" is the whole board (D238): reaching it through the menu clears any value filter,
    // the same way it would read to a user — the wider item resets the narrower one.
    if (item.key === 'verticals') void store.setValueFilter(null)
  }
}

function onValueClick(id: string): void {
  store.closeGoal()
  store.setView('verticals')
  void store.setValueFilter(id)
}

function valueActive(id: string): boolean {
  return store.state.activeView === 'verticals' && store.state.valueFilter === id
}
</script>

<template>
  <div class="app-shell">
    <nav class="app-nav" data-cap="nav">
      <div class="app-nav__panel">
        <div class="app-nav__menu">
          <!-- Search stays first; view buttons float immediately to its right. -->
          <div class="app-nav__search">
            <SearchBar />
          </div>
          <!-- data-cap on the row: the value links below are the filter_value gesture (S-77). -->
          <div class="app-nav__links" data-cap="value-filter">
            <button
              v-for="item in NAV_ITEMS"
              :key="item.key"
              type="button"
              class="app-nav__link"
              :class="{
                'app-nav__link--active':
                  item.key === store.state.activeView &&
                  (item.key !== 'verticals' || store.state.valueFilter === null),
              }"
              :data-nav-item="item.key"
              :aria-current="item.key === store.state.activeView ? 'page' : undefined"
              @click="onNavClick(item)"
            >
              {{ item.label }}
            </button>
            <!-- D238: one plain link per value (parentless life root), same component as the two
                 view links above. Active = that value's filtered board is what the pane shows. -->
            <button
              v-for="v in values"
              :key="v.id"
              type="button"
              class="app-nav__link"
              :class="{ 'app-nav__link--active': valueActive(v.id) }"
              :data-value-id="v.id"
              :aria-current="valueActive(v.id) ? 'page' : undefined"
              @click="onValueClick(v.id)"
            >
              {{ valueLabel(v.id, v.title) }}
            </button>
          </div>
        </div>
      </div>
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
/* Global, matching every other product-side component's convention (GoalCard.vue,
   SchedulePopover.vue, Board.vue, InboxView.vue) — plain CSS, new classes only, no kit rule
   touched. Every number is docs/UI_MEASURED.md §1, re-verified live against the reference
   fixtures before this file was written (see this file's own header comment). */
.app-shell {
  display: block;
  height: 100%;
  overflow: hidden;
  background: #ffffff;
}

.app-nav {
  position: fixed;
  left: 16px;
  bottom: 16px;
  z-index: 200;
  width: auto;
}

.app-nav__panel {
  width: max-content;
}

.app-nav__menu {
  box-sizing: border-box;
  padding: 0;
  display: flex;
  align-items: center;
  gap: 8px;
}

.app-nav__links {
  display: flex;
  align-items: center;
  gap: 4px;
}

.app-nav__link {
  display: flex;
  align-items: center;
  height: 32px;
  padding: 0 10px 0 16px;
  border: 0;
  border-radius: 6px;
  width: auto;
  background: transparent;
  color: rgb(121, 121, 120);
  font-size: 15px;
  line-height: 32px;
  font-weight: 400;
  letter-spacing: 0.15px;
  text-align: left;
  cursor: pointer;
}
.app-nav__link:hover:not(.app-nav__link--active) {
  background: var(--color-surface-overlay);
}
.app-nav__link--active {
  color: rgb(45, 48, 54);
  background: rgba(226, 226, 226, 0.77);
}

.app-nav__search {
}

.app-content {
  flex: 1 1 auto;
  height: 100%;
  /* Without this, a flex item's default `min-width: auto` refuses to shrink below its content's
     intrinsic width — and Board's own content is deliberately wider than the viewport
     (design-system/style.css's A7 comment: "2340px content against a 1148px visible area... the
     board scrolls horizontally"). Omitting `min-width: 0` here does not show up as a broken
     layout in a quick look; it shows up as the content pane silently refusing to stay at 1148px
     and the whole shell gaining a page-level horizontal scrollbar. */
  min-width: 0;
  overflow: hidden;
  position: relative;
}
</style>
