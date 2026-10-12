<script setup lang="ts">
/* The board is CSS-only composition (A7, style.css): a plain .card-stack (not the --columns
   modifier — that variant's equal-width shrink and 768px collapse don't match this board's
   unequal, non-shrinking columns and 390px breakpoint) wearing the .pattern-vertical-board class.
   Relies on Vue's automatic attribute/class fallthrough: a component with a single root element
   merges an unrecognised `class` binding from its caller onto that root, so
   `<KCardStack class="pattern-vertical-board">` produces
   `<div class="card-stack pattern-vertical-board">` with no wrapper element and no prop plumbing
   needed on KCardStack for a class it doesn't know about. */
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { KButton, KCardStack } from '@konstantinopolskii/vue'
import Column from './Column.vue'
import DragOverlay from './DragOverlay.vue'
import SpansBoard from './SpansBoard.vue'
import { openSpans, spans, type SpanScale } from '../lib/spans'
import { store, todayIso } from '../store'
import { AUTOSCROLL_TICK_MS } from '../lib/drag'
import { wheelIntent } from '../lib/boardWheel'
import {
  adjacentPeriodAnchor,
  type AdjustableVertical,
  type PeriodDirection,
} from '../lib/periodNavigation'
import type { BoardColumnData } from '../types'
import { mountIridescentOverlay } from '../kit-ext/iridescent'
import { devDeck } from '../lib/devDeck'
import { commandFilter, filterColumns, nothingFound } from '../lib/commandFilter'
import './board.css'

const props = withDefaults(defineProps<{ columns: BoardColumnData[]; showSampleBanner?: boolean }>(), {
  showSampleBanner: false,
})
const emit = defineEmits<{ 'remove-sample': [] }>()
const boardRoot = ref<{ $el?: Element } | null>(null)
const iridescentCanvas = ref<HTMLCanvasElement | null>(null)
let unmountIridescentOverlay: (() => void) | null = null

watch(
  [boardRoot, iridescentCanvas],
  ([root, canvas]) => {
    unmountIridescentOverlay?.()
    unmountIridescentOverlay = null
    const element = root?.$el
    if (element instanceof HTMLElement && canvas) {
      unmountIridescentOverlay = mountIridescentOverlay(element, canvas)
    }
  },
  { flush: 'post' },
)
onBeforeUnmount(() => unmountIridescentOverlay?.())

/** Ruling 1 (owner, 2026-08-09): "There's no need to show Maybe as a left column. Make it same
 *  tab as inbox." Supersedes `ARCHITECTURE.md`:445's "an eighth column, pinned left of Day,
 *  labelled Maybe" — the board now draws the **seven dated** columns only; the unverticaled pile
 *  is reached through the nav's existing "Inbox" link (`App.vue`, `InboxView.vue`), which was
 *  already wired to the same data before this ruling landed.
 *
 *  `props.columns` still carries all eight buckets `store.ts::columns` computes — that computed
 *  is `InboxView.vue`'s own source too (`store.columns.value.find(c => c.vertical === 'maybe')`),
 *  so narrowing it upstream, in the store, would take the Maybe bucket away from the one view
 *  that still needs it. This is the "deletion on the board side, plus a payload change" the
 *  ruling called for: nothing server-side moved (`verticals/core/board.py` still returns all eight
 *  columns in one statement, IR-07), and `store.ts` still projects all eight — the board is the
 *  one place that now drops a column before drawing it. */
const dated = computed(() => filterColumns(props.columns).filter((c) => c.vertical !== 'maybe'))

/** D234: the value bar's buttons — parentless life-vertical goals, in the life column's own
 *  (position) order. Read from the same projected columns the board draws; the life column is
 *  exempt from the value filter server-side, so this list is complete even mid-filter. */
// Hover is a transient deck preview. D186 gives persistent main ownership to an opened card's
// rendered column; Day owns that role only while no board-hosted detail is open.
const deckActiveVertical = ref('day')
const mainVertical = computed(() => (
  store.state.openGoalId !== null && store.state.openGoalVertical
    ? store.state.openGoalVertical
    : 'day'
))
watch(() => store.state.openGoalId, (id) => {
  if (id === null) deckActiveVertical.value = 'day'
})
function previewColumn(vertical: string) {
  if (store.state.openGoalId !== null || vertical === mainVertical.value) return
  deckActiveVertical.value = vertical
}
const deckStyle = computed(() => ({
  '--deck-day-width': devDeck.dayWidth > 0 ? `${devDeck.dayWidth}px` : 'auto',
  '--deck-active-gap-left': `${devDeck.activeGapLeft}px`,
  '--deck-active-gap-right': `${devDeck.activeGapRight}px`,
  '--deck-card-width': `clamp(8rem, ${devDeck.width}vw, 19rem)`,
  '--deck-card-overlap': `calc(-1 * clamp(0rem, ${devDeck.overlap}vw, 17.5rem))`,
  '--deck-card-perspective': `${devDeck.perspective}px`,
  '--deck-card-rotate-y': `${devDeck.rotateY}deg`,
  '--deck-card-rotate-x': `${devDeck.rotateX}deg`,
  '--deck-card-scale': String(devDeck.scale / 100),
  '--deck-card-active-rotate-y': `${devDeck.activeRotateY}deg`,
  '--deck-card-active-scale': String(devDeck.activeScale / 100),
  '--deck-card-offset-y': `${devDeck.offsetY}px`,
  '--deck-card-active-offset-y': `${devDeck.activeOffsetY}px`,
}))

const periodDirection = ref<PeriodDirection>(1)
const periodSwapId = ref(0)

async function loadPeriod(anchor: string, direction: PeriodDirection) {
  periodDirection.value = direction
  // In the board's own tick: a column must still hold its old period when the swap starts.
  await store.loadBoard(anchor, () => { periodSwapId.value += 1 })
}

function navigatePeriod(vertical: string, direction: PeriodDirection) {
  const anchor = store.state.board?.anchor_date
  if (!anchor) return
  void loadPeriod(adjacentPeriodAnchor(anchor, vertical as AdjustableVertical, direction), direction)
}

/* The `t` key, and the single bar a column away from today shows (docs/design/column-bars.md): every column back on the
   period that holds today. */
function navigateToday() {
  const today = todayIso()
  const current = store.state.board?.anchor_date
  if (!current || current === today) return
  void loadPeriod(today, current < today ? 1 : -1)
}

/** The middle bar of a column's sign opens that column's spans: the mode a dragged goal opens when it rests on the
 *  column's corner (`lib/spansDrag.ts`), with nothing in the hand. It starts at this period, as the corner's does, and
 *  floats the next column up (docs/design/column-bars.md). */
function openMode(vertical: string, periodKey: string | null) {
  if (spans.vertical) return
  void openSpans(vertical as SpanScale, vertical, periodKey, todayIso())
}

// --- drag (AC-220/S-145) ------------------------------------------------------------------------
//
// The window-level pointer listeners for the gesture are NOT here any more — they moved to
// `App.vue` (D90). `GoalCard.vue`'s row fires `pointerdown` from BOTH views, and this component
// unmounts whenever Inbox is active, so a press held past `DESKTOP_HOLD_MS` on an Inbox card armed
// a drag that nothing was left listening to release: `drag.id` stuck forever and the card rendered
// `goal-card--source-gap-closed` (height 0) in every later view. Same lifetime argument the day
// rollover already lost here (D69). What stays is genuinely board-only: the horizontal wheel strip
// and the `t` shortcut.
function onWindowKeyDown(event: KeyboardEvent) {
  const target = event.target as HTMLElement | null
  if (
    event.key.toLowerCase() === 't'
    && !event.repeat
    && !target?.matches('input, textarea, [contenteditable="true"]')
  ) {
    navigateToday()
  }
}
/* Capture phase, non-passive: the column boxes between the pointer and the strip are
   overflow:hidden scroll containers, so by the time a horizontal delta bubbles it has already
   been eaten. See lib/boardWheel.ts. */
function onWindowWheel(event: WheelEvent) {
  const target = event.target instanceof Element ? event.target : null
  const strip = target?.closest<HTMLElement>('.pattern-vertical-board')
  if (!strip) return
  const intent = wheelIntent(
    event.deltaX,
    event.deltaY,
    strip.scrollLeft,
    strip.scrollWidth,
    strip.clientWidth,
  )
  if (!intent) return
  strip.scrollLeft += intent.scrollBy
  event.preventDefault()
}
onMounted(() => {
  window.addEventListener('wheel', onWindowWheel, { capture: true, passive: false })
  window.addEventListener('keydown', onWindowKeyDown)
})
onBeforeUnmount(() => {
  window.removeEventListener('wheel', onWindowWheel, { capture: true })
  window.removeEventListener('keydown', onWindowKeyDown)
})

let autoScrollTimer: number | null = null
watch(
  () => store.state.drag.id,
  (id) => {
    if (autoScrollTimer !== null) window.clearInterval(autoScrollTimer)
    autoScrollTimer = id
      ? window.setInterval(() => store.autoScrollDrag(), AUTOSCROLL_TICK_MS)
      : null
  },
)
onBeforeUnmount(() => {
  if (autoScrollTimer !== null) window.clearInterval(autoScrollTimer)
})

/* Selection stays available at rest and on press, then locks from arm through settle. */
const isDragging = computed(
  () => store.state.drag.id !== null || store.state.drag.settling !== null,
)

// `document.body`, not a class on this component's own (fragment, no single root) template — the
// gesture can start over any card in any column. The same global state supplies the measured
// grabbing cursor through settle.
watch(isDragging, (dragging) => {
  document.body.classList.toggle('pattern-vertical-board__no-select', dragging)
})
onBeforeUnmount(() => document.body.classList.remove('pattern-vertical-board__no-select'))

</script>

<template>
  <!-- Stage 0 (S-61, S-62): sentence case, no emoji (house Texts rule), removal is one click and
       asks nothing — `store.ts::removeSample` is the no-confirmation call, pinned §10-D12. Board-
       level, not app-level: whether this shows is entirely a function of the loaded board's own
       data (`store.ts::hasSampleData`), not of routing or page chrome. -->
  <div v-if="showSampleBanner" class="pattern-vertical-board__banner" data-cap="sample-banner">
    <p class="t-body">This is sample data, here to show how the board works.</p>
    <KButton data-cap="remove-sample" @click="emit('remove-sample')">Remove sample data</KButton>
  </div>
  <!-- `data-role="column-strip"` marks the one element that scrolls horizontally (S-76: the strip
       must satisfy `scrollWidth > clientWidth` inside its own container while `document.body` does
       not). That element is this one — `.pattern-vertical-board` is the overflow-x container in the
       kit's A7 CSS — so the attribute goes on it rather than on a new wrapper; it rides the same
       automatic fallthrough as the `class` above, no prop on KCardStack.

       `v-if="dated.length"`, not `columns.length` — `dated` is this file's own seven-column
       projection (see the script's own header comment, ruling 1). A loaded board always has all
       seven dated columns once it has any (`core/board.py` builds the full set every time and
       this file only ever drops the eighth), so this is still exactly "no board data yet", never
       a legitimate empty state being hidden. It is load-bearing, not cosmetic: an empty
       `.pattern-vertical-board` still lays out at full size, so it satisfied
       `expect(strip).to_be_visible()` while the `GET /api/board` behind it was still in flight,
       and any check that reads cards immediately after the strip appears saw zero of them
       (measured on `/h/2025-01-06`: 0 cards at first paint, both rows present ~1.5 s later).
       Rendering the strip only once it has columns makes "the board is visible" and "the board
       has its rows" the same instant. A pending spinner may occupy the empty shell, but no
       partial column or placeholder copy appears. -->
  <div
    v-if="store.state.loading && !dated.length"
    class="pattern-vertical-board__spinner"
    role="status"
    aria-label="Loading"
  />
  <!-- Moving a goal: one vertical's periods in a row, in the board's place (docs/design-handoff S5.P1). -->
  <!-- Typing goes back to the regular board and its matches; clearing brings the spans back (S5.P3.016). -->
  <SpansBoard v-if="spans.vertical && !commandFilter.text" />
  <KCardStack
    v-if="dated.length && (!spans.vertical || commandFilter.text)"
    ref="boardRoot"
    class="pattern-vertical-board"
    :class="{
      _loading: store.state.loading,
      'pattern-vertical-board--flat': !devDeck.use3D,
      'pattern-vertical-board--family': store.familyLight.value !== null,
      'pattern-vertical-board--light-fast': store.state.lightFast,
      'pattern-vertical-board--nothing-found': nothingFound,
    }"
    :style="deckStyle"
    data-role="column-strip"
  >
    <Column
      v-for="column in dated"
      :key="column.vertical"
      :vertical="column.vertical"
      :title="column.title"
      :sub-label="column.subLabel"
      :shorter="column.shorter"
      :label="column.label"
      :active="column.active"
      :deck-main="mainVertical === column.vertical"
      :deck-active="store.state.openGoalId === null
        && column.vertical !== mainVertical
        && deckActiveVertical === column.vertical"
      :add-placeholder="column.addPlaceholder"
      :goals="column.goals"
      :period-key="column.periodKey"
      :away="column.away"
      :period-direction="periodDirection"
      :period-swap-id="periodSwapId"
      @mouseenter="previewColumn(column.vertical)"
      @pointermove="previewColumn(column.vertical)"
      @period-step="navigatePeriod"
      @period-today="navigateToday"
      @period-mode="openMode"
    />
  </KCardStack>
  <canvas
    ref="iridescentCanvas"
    data-role="iridescent-overlay"
    aria-hidden="true"
    hidden
  />
  <DragOverlay />
  <!-- The value filter is nav items in the app shell (D238, App.vue), not a board-owned bar. -->
</template>
