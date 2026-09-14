<script setup lang="ts">
/* The board is CSS-only composition (A7, style.css): a plain .card-stack (not the --columns
   modifier — that variant's equal-width shrink and 768px collapse don't match this board's
   unequal, non-shrinking columns and 390px breakpoint) wearing the .pattern-vertical-board class.
   Relies on Vue's automatic attribute/class fallthrough: a component with a single root element
   merges an unrecognised `class` binding from its caller onto that root, so
   `<KCardStack class="pattern-vertical-board">` produces
   `<div class="card-stack pattern-vertical-board">` with no wrapper element and no prop plumbing
   needed on KCardStack for a class it doesn't know about. */
import { computed, nextTick, onBeforeUnmount, onMounted, ref, shallowRef, watch } from 'vue'
import { KButton, KCardStack } from '@konstantinopolskii/vue'
import Column from './Column.vue'
import { store, todayIso } from '../store'
import { AUTOSCROLL_TICK_MS, SETTLE_EASING } from '../lib/drag'
import { wheelIntent } from '../lib/boardWheel'
import {
  adjacentPeriodAnchor,
  type AdjustableVertical,
  type PeriodDirection,
} from '../lib/periodNavigation'
import type { BoardColumnData } from '../types'
import { mountIridescentOverlay } from '../kit-ext/iridescent'
import { devDeck } from '../lib/devDeck'

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
const dated = computed(() => props.columns.filter((c) => c.vertical !== 'maybe'))

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

async function loadPeriod(anchor: string, direction: PeriodDirection, today = false) {
  periodDirection.value = direction
  if (await store.loadBoard(anchor)) {
    periodSwapId.value += 1
    history.pushState(null, '', today ? '/' : `/h/${anchor}`)
  }
}

function navigatePeriod(vertical: string, direction: PeriodDirection) {
  const anchor = store.state.board?.anchor_date
  if (!anchor) return
  void loadPeriod(adjacentPeriodAnchor(anchor, vertical as AdjustableVertical, direction), direction)
}

function navigateToday() {
  const today = todayIso()
  const current = store.state.board?.anchor_date
  if (!current || current === today) return
  void loadPeriod(today, current < today ? 1 : -1, true)
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

/* Clone the rendered row itself. Copying computed styles before Vue applies the source-ghost
   class preserves every current control and line at the measured footprint without creating a
   second interactive GoalCard instance. */
const overlayHost = shallowRef<HTMLElement | null>(null)
const dragVisualId = computed(() => store.state.drag.id ?? store.state.drag.settling?.id ?? null)

function cloneRenderedRow(id: string): HTMLElement | null {
  const source = document.querySelector<HTMLElement>(
    `[data-goal-id="${CSS.escape(id)}"] > .goal-card__row`,
  )
  if (!source) return null
  const clone = source.cloneNode(true) as HTMLElement
  const sources = [source, ...source.querySelectorAll<HTMLElement>('*')]
  const clones = [clone, ...clone.querySelectorAll<HTMLElement>('*')]
  sources.forEach((node, index) => {
    const style = getComputedStyle(node)
    for (const property of style) clones[index].style.setProperty(property, style.getPropertyValue(property))
    clones[index].style.pointerEvents = 'none'
    // The clone IS the visible artifact, so it can never inherit the ghost's hiding. Copying
    // computed styles off a source that is mid-ghost would otherwise carry `visibility: hidden`
    // onto every node. Only visibility is forced — a node's own opacity is real card design.
    clones[index].style.visibility = 'visible'
  })
  /* Computed-style copying freezes used widths/heights in px. Keep paint exact, but let the row's
     flow boxes resolve against the flying overlay's live width so title wrapping is measurable. */
  clone.style.width = '100%'
  clone.style.height = 'auto'
  for (const element of clone.querySelectorAll<HTMLElement>(
    '.goal-card__text, .goal-card__title, .goal-card__meta, .goal-card__progress',
  )) {
    element.style.width = 'auto'
    element.style.height = 'auto'
  }
  clone.style.opacity = '1'
  clone.classList.remove('goal-card__row--drag-source', 'goal-card__row--drop-candidate')
  /* The resting card is a padded box: background and radius live on the CARD, and the row sits
     inset by the card's own padding (6px, uniform — measured). Painting the card's background
     straight onto the row clone loses that inset, so the flying content hugged its edge while
     the resting content breathes (owner, 2026-08-10: "the dragged card clone ... doesn't have
     the paddings as her original"). All drag geometry — grab offset, hit testing, the indicator
     gap, the settle target — is the ROW box, so the overlay's outer rect must stay the row;
     the card look is a wrapper that BLEEDS the card's padding outward, exactly as the resting
     card's background extends beyond its row. */
  const card = source.parentElement as HTMLElement
  const cardStyle = getComputedStyle(card)
  const pad = {
    top: cardStyle.paddingTop,
    right: cardStyle.paddingRight,
    bottom: cardStyle.paddingBottom,
    left: cardStyle.paddingLeft,
  }
  const box = document.createElement('div')
  box.style.position = 'absolute'
  box.style.top = `-${pad.top}`
  box.style.right = `-${pad.right}`
  box.style.bottom = `-${pad.bottom}`
  box.style.left = `-${pad.left}`
  box.style.padding = `${pad.top} ${pad.right} ${pad.bottom} ${pad.left}`
  box.style.boxSizing = 'border-box'
  box.style.backgroundColor = cardStyle.backgroundColor
  box.style.borderRadius = cardStyle.borderRadius
  box.style.overflow = 'hidden'
  box.style.pointerEvents = 'none'
  box.setAttribute('aria-hidden', 'true')
  box.appendChild(clone)
  return box
}

function renderedRowHeightAtWidth(id: string, width: number): number | null {
  const box = cloneRenderedRow(id)
  const row = box?.querySelector<HTMLElement>(':scope > .goal-card__row')
  if (!row) return null
  const host = document.createElement('div')
  host.style.position = 'fixed'
  host.style.left = '-10000px'
  host.style.top = '0'
  host.style.width = `${width}px`
  host.style.visibility = 'hidden'
  host.style.pointerEvents = 'none'
  host.appendChild(row)
  document.body.appendChild(host)
  const height = row.getBoundingClientRect().height
  host.remove()
  return height > 0 ? height : null
}

watch(
  dragVisualId,
  (id) => {
    if (!id) return
    const clone = cloneRenderedRow(id)
    if (!clone) return
    void nextTick(() => overlayHost.value?.replaceChildren(clone))
  },
  { flush: 'sync' },
)

const dragPreviewKey = computed(() => {
  const drag = store.state.drag
  if (!drag.id) return ''
  const target = drag.target
  if (!target) return `${drag.id}:none`
  // D249: `parentId` is part of the key too — two different rendered groups sharing one column
  // can both resolve `insertBeforeId: null` (each group's own append slot), and without the
  // group owner in the key those two genuinely different targets would collapse onto the same
  // measurement, leaving the preview sized off whichever indicator happened to render first.
  return target.kind === 'combine'
    ? `${drag.id}:combine:${target.targetId}`
    : `${drag.id}:reorder:${target.vertical}:${target.periodKey ?? ''}:${target.insertBeforeId ?? ''}:${target.parentId ?? ''}`
})
let previewMeasureVersion = 0
watch(
  dragPreviewKey,
  async (key) => {
    const version = ++previewMeasureVersion
    const id = store.state.drag.id
    if (!id) return
    await nextTick()
    if (version !== previewMeasureVersion || key !== dragPreviewKey.value) return
    const drag = store.state.drag
    const target = drag.target
    if (!target) {
      store.setDragPreviewSize(drag.width, drag.height)
      return
    }
    if (target.kind === 'combine') {
      const row = document.querySelector<HTMLElement>(
        `[data-goal-id="${CSS.escape(target.targetId)}"] > .goal-card__row`,
      )
      const rect = row?.getBoundingClientRect()
      if (rect) store.setDragPreviewSize(rect.width, renderedRowHeightAtWidth(id, rect.width) ?? drag.height)
      return
    }
    const indicator = document.querySelector<HTMLElement>('[data-role="drop-indicator"]')
    if (!indicator) return
    if (indicator.dataset.box === 'card') {
      const row = indicator.querySelector<HTMLElement>('[data-role="drop-row-target"]')
      const rect = row?.getBoundingClientRect()
      if (rect) store.setDragPreviewSize(rect.width, rect.height)
      return
    }
    const width = indicator.getBoundingClientRect().width
    store.setDragPreviewSize(width, renderedRowHeightAtWidth(id, width) ?? drag.height)
  },
  { flush: 'post' },
)

const overlayStyle = computed(() => {
  const d = store.state.drag
  if (d.settling) {
    const { duration } = d.settling
    // Normally live preview already reached this box before release. Keeping size in the settle
    // branch covers a pointer-up that beats the next-frame destination measurement.
    const width = d.settling.width ?? d.width
    const height = d.settling.height ?? d.height
    return {
      left: `${d.settling.left}px`,
      top: `${d.settling.top}px`,
      width: `${width}px`,
      height: `${height}px`,
      transition: [
        `left ${duration}ms ${SETTLE_EASING}`,
        `top ${duration}ms ${SETTLE_EASING}`,
        `width ${duration}ms ${SETTLE_EASING}`,
        `height ${duration}ms ${SETTLE_EASING}`,
      ].join(', '),
    }
  }
  // D245 (KK ruling 2026-08-18): the flying card holds the PICKUP size (`width`/`height`) for the
  // whole flight, not `previewWidth`/`previewHeight` — those track the live hover target's own
  // geometry (still consumed by Column.vue's drop indicator below) and re-sizing the overlay
  // against them mid-gesture read as the card corrupting itself. No width/height transition is
  // needed any more: the box no longer changes size before release, only position.
  return {
    left: `${d.x - d.offsetX}px`,
    top: `${d.y - d.offsetY}px`,
    width: `${d.width}px`,
    height: `${d.height}px`,
  }
})
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
  <KCardStack
    v-if="dated.length"
    ref="boardRoot"
    class="pattern-vertical-board"
    :class="{ _loading: store.state.loading, 'pattern-vertical-board--flat': !devDeck.use3D }"
    :style="deckStyle"
    data-role="column-strip"
  >
    <Column
      v-for="column in dated"
      :key="column.vertical"
      :vertical="column.vertical"
      :title="column.title"
      :sub-label="column.subLabel"
      :active="column.active"
      :deck-main="mainVertical === column.vertical"
      :deck-active="store.state.openGoalId === null
        && column.vertical !== mainVertical
        && deckActiveVertical === column.vertical"
      :add-placeholder="column.addPlaceholder"
      :goals="column.goals"
      :period-key="column.periodKey"
      :period-direction="periodDirection"
      :period-swap-id="periodSwapId"
      @mouseenter="previewColumn(column.vertical)"
      @pointermove="previewColumn(column.vertical)"
      @period-step="navigatePeriod"
      @period-today="navigateToday"
    />
  </KCardStack>
  <canvas
    ref="iridescentCanvas"
    data-role="iridescent-overlay"
    aria-hidden="true"
    hidden
  />
  <!-- P-02/M2: pointer-transparent clone of the complete rendered row at its grab offset. -->
  <div
    v-if="dragVisualId"
    ref="overlayHost"
    class="pattern-vertical-board__drag-overlay"
    data-role="drag-overlay"
    data-dnd-overlay
    :style="overlayStyle"
  />
  <!-- The value filter is nav items in the app shell (D238, App.vue), not a board-owned bar. -->
</template>

<style>
/* Global, matching every other product-side component in this tree (GoalCard.vue, SchedulePopover
   .vue). New classes only. KButton is full-width by default (kit canon) — wrong for a button
   sharing a row with a line of text, so its flex sizing is overridden the same "doubled class"
   way GoalCard.vue and SchedulePopover.vue already override a kit default: one class heavier,
   order-independent. */
.pattern-vertical-board__banner {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-4);
  padding: var(--space-3) var(--space-4);
  border-bottom: 0.5px solid var(--color-border);
}
.pattern-vertical-board__banner .button.button {
  width: auto;
  flex: 0 0 auto;
}

/* Ruling 3 (owner, 2026-08-09): "Remove the scrollbars when I scroll inside columns." The scroll
   itself is untouched — both rules below hide only the rendered track/thumb, never the
   `overflow` value that makes the element scrollable, so keyboard scrolling (arrow keys/Space on
   a focused descendant), the wheel, and a touch drag all keep working exactly as before; nothing
   here touches `:focus`/`:focus-visible`, so focus rings are unaffected. Two selectors because
   two different `overflow: auto` containers exist: `.pattern-vertical-board` scrolls
   horizontally (the whole column strip), while each current/preserved `.period-slide` scrolls
   its own goal list vertically. `.pattern-vertical-board__column` stays in the list for the Inbox
   view, which still uses that root as its single vertical scrollport.

   Three properties, one per engine actually in `docs/DEPENDENCIES.md`'s tested set
   (Chromium/Firefox/WebKit): `scrollbar-width: none` (Firefox), `-ms-overflow-style: none`
   (legacy Edge/IE, kept for completeness though no scenario targets it), and the WebKit/Blink
   pseudo-element (Chrome/Safari — the two engines every uidiff capture and MCP screenshot
   actually runs on). No new class, no new component: an additive rule over two kit selectors
   already carrying `overflow: auto`, the same "doesn't touch kit source" convention every other
   override in this file already follows. */
.pattern-vertical-board,
.pattern-vertical-board__column,
.period-slide {
  scrollbar-width: none; /* Firefox */
  -ms-overflow-style: none; /* legacy Edge/IE */
}
.pattern-vertical-board::-webkit-scrollbar,
.pattern-vertical-board__column::-webkit-scrollbar,
.period-slide::-webkit-scrollbar {
  display: none; /* WebKit/Blink (Chrome, Safari) */
}

/* Armed drag and settle own cursor globally; armed content cannot be selected. */
body.pattern-vertical-board__no-select {
  user-select: none;
  cursor: grabbing !important;
}
body.pattern-vertical-board__no-select * {
  cursor: grabbing !important;
  user-select: none;
}

.pattern-vertical-board {
  --goal-focus-motion-duration: 360ms;
  --goal-focus-motion-ease: cubic-bezier(.22, 1, .36, 1);
  user-select: text;
  opacity: 1;
  transition: opacity 0s;
}

/* Coin review-card geometry, applied to the columns themselves. The strip remains the real
   horizontal scroll owner; transforms only change the painted column, while negative margin-right
   creates the same overlapping deck as `.review-card` in the landing page's hero-reviews.css. */
@media (min-width: 900px) {
  .pattern-vertical-board {
    --deck-card-width: clamp(8rem, 19vw, 19rem);
    --deck-card-overlap: calc(-1 * clamp(9rem, 17vw, 17.5rem));
    --deck-card-perspective: 200px;
    --deck-card-rotate-y: 15deg;
    --deck-card-rotate-x: 5deg;
    --deck-card-scale: 0.75;
    --deck-card-active-rotate-y: 3deg;
    --deck-card-active-rotate-x: 0deg;
    --deck-card-active-scale: 0.95;
    --deck-card-active-margin-right: -1rem;
  }

  /* Every rule in this block is the OPT-IN 3D deck experiment (dev panel, use3D). The flat
     board — the product since COMPACT_BOARD_HANDOFF.md — is excluded at the selector, so
     Column.vue is the single owner of flat geometry and nothing here needs countermanding. */
  .pattern-vertical-board.pattern-vertical-board:not(.pattern-vertical-board--flat) > .pattern-vertical-board__column {
    flex: 0 0 var(--deck-card-width);
    width: var(--deck-card-width);
    min-width: var(--deck-card-width);
    max-width: var(--deck-card-width);
    margin-right: var(--deck-card-overlap);
    transform: perspective(var(--deck-card-perspective))
      rotateY(var(--deck-card-rotate-y)) rotateX(var(--deck-card-rotate-x));
    transform-origin: left center;
    transform-style: preserve-3d;
    isolation: isolate;
    scale: var(--deck-card-scale);
    filter: none;
    background: #fff;
    backdrop-filter: blur(5px);
    -webkit-backdrop-filter: blur(5px);
    border-radius: 1.2rem;
    opacity: 1;
    transition:
      transform 0.3s ease-out,
      flex-grow var(--goal-focus-motion-duration) var(--goal-focus-motion-ease),
      flex-basis var(--goal-focus-motion-duration) var(--goal-focus-motion-ease),
      width var(--goal-focus-motion-duration) var(--goal-focus-motion-ease),
      min-width var(--goal-focus-motion-duration) var(--goal-focus-motion-ease),
      max-width var(--goal-focus-motion-duration) var(--goal-focus-motion-ease),
      margin-left var(--goal-focus-motion-duration) var(--goal-focus-motion-ease),
      backdrop-filter 0.3s ease,
      -webkit-backdrop-filter 0.3s ease,
      margin-right var(--goal-focus-motion-duration) var(--goal-focus-motion-ease),
      filter 0.3s ease,
      background 0.3s ease,
      box-shadow 0.3s ease;
    will-change: transform, filter;
    translate: 0 var(--deck-card-offset-y);
    overflow: visible;
  }

  /* Main is a transferable role. Day receives it at rest; an opened board card gives it to the
     card's rendered column. The existing Day-width deck setting remains the one main-width token. */
  .pattern-vertical-board.pattern-vertical-board:not(.pattern-vertical-board--flat) >
  .pattern-vertical-board__column.pattern-vertical-board__column--deck-main {
    flex: 1 0 var(--deck-day-width);
    width: var(--deck-day-width);
    min-width: var(--deck-day-width);
    max-width: var(--deck-day-width);
    margin-left: 0;
    margin-right: 0;
    transform: none;
    z-index: 3;
    scale: 1;
    background: #fff;
    translate: 0 0;
  }

  .pattern-vertical-board.pattern-vertical-board:not(.pattern-vertical-board--flat) >
  .pattern-vertical-board__column.pattern-vertical-board__column--deck-active:not(.pattern-vertical-board__column--deck-main) {
    transform: perspective(var(--deck-card-perspective))
      rotateY(var(--deck-card-active-rotate-y)) rotateX(var(--deck-card-active-rotate-x));
    margin-left: var(--deck-active-gap-left);
    margin-right: calc(var(--deck-card-active-margin-right) + var(--deck-active-gap-right));
    z-index: 2;
    filter: blur(0);
    scale: var(--deck-card-active-scale);
    background: #fff;
    translate: 0 var(--deck-card-active-offset-y);
  }

}
.pattern-vertical-board._loading {
  opacity: 0.5;
  transition: opacity var(--motion-loading, 300ms) ease-in var(--motion-loading-delay, 1s);
}
.pattern-vertical-board__spinner {
  width: 20px;
  height: 20px;
  margin: var(--space-6);
  border: 2px solid var(--color-border);
  border-top-color: var(--color-text);
  border-radius: 50%;
  animation: board-spinner-rotation var(--motion-spinner, 700ms) linear infinite;
}
@keyframes board-spinner-rotation {
  to { transform: rotate(360deg); }
}
@media (prefers-reduced-motion: reduce) {
  .pattern-vertical-board.pattern-vertical-board > .pattern-vertical-board__column {
    transition: none;
  }
}

.pattern-vertical-board__drag-overlay {
  /* `fixed`, not `absolute`: the overlay tracks the raw viewport pointer position `Board.vue`'s
     own `overlayStyle` computes, with no ancestor offset to account for. `pointer-events: none`
     is load-bearing, not decorative — without it this element itself would be what `lib/
     drag.ts::hitTest`'s `elementFromPoint` finds under the cursor on every frame, since it is
     the topmost thing painted there. */
  position: fixed;
  z-index: 2147483647;
  pointer-events: none;
  box-sizing: border-box;
  /* The card-look wrapper `cloneRenderedRow` builds BLEEDS the card's own padding beyond this
     element's row-box rect (the resting card's background does the same relative to its row), so
     the overlay itself must not clip or round — the wrapper owns overflow and radius. */
  overflow: visible;
  box-shadow: none;
  opacity: 1;
  will-change: left, top, width, height;
}
</style>
