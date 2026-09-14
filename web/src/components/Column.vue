<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { KCardStack } from '@konstantinopolskii/vue'
import AppIcon from './AppIcon.vue'
import ColumnHeader from './ColumnHeader.vue'
import GoalCard from './GoalCard.vue'
import InlineAdd from './InlineAdd.vue'
import { store } from '../store'
import { playSound } from '../lib/sound'
import type { PeriodDirection } from '../lib/periodNavigation'
import type { GoalCardData } from '../types'

const props = withDefaults(
  defineProps<{
    vertical: string
    title: string
    subLabel?: string
    active?: boolean
    deckActive?: boolean
    deckMain?: boolean
    addPlaceholder?: string
    goals: GoalCardData[]
    periodKey?: string | null
    periodDirection?: PeriodDirection
    periodSwapId?: number
  }>(),
  {
    subLabel: '', active: false, deckActive: false, deckMain: false, addPlaceholder: 'Add…', periodKey: null,
    periodDirection: 1, periodSwapId: 0,
  },
)

const emit = defineEmits<{
  'period-step': [vertical: string, direction: PeriodDirection]
  'period-today': []
}>()

function onAdd(title: string) {
  if (!title.trim()) return
  playSound('add_goal_clicked')
  void store.createGoalOn(props.vertical, title)
}

// --- compact board (COMPACT_BOARD_HANDOFF.md §3, KK ruling 2026-08-17; D253 KK ruling
// 2026-08-21 retires §4's stacks) --------------------------------------------------------------
//
// `active` still means THE expanded column (at most one, header-click toggle) — that layout law
// (D244 §3) stands. What died with D253: a compact column no longer collapses same-column
// sub-tasks into a "stack" behind a face card. Every column, compact or expanded, now renders
// each goal's full nested subtree exactly as `GoalCard.vue` always has for an expanded one — "no
// fold affordance anywhere" (KK, verbatim: "let's show all sub-task by default now").

function onHeaderClick(): void {
  store.toggleExpandedColumn(props.vertical)
}

/** One props bag per top-level card, forwarded straight through — no face substitution, no
 *  children truncation. The D244 §5 chain-hover wash (`goal-card--ancestor-hover`, GoalCard.vue's
 *  own `isChainHovered`) still lights up every board-visible chain member; only the swapped-face
 *  trick this function used to perform for a HIDDEN member is gone, since nothing is hidden. */
function cardProps(goal: GoalCardData) {
  return {
    id: goal.id,
    parentId: goal.parentId,
    title: goal.title,
    done: goal.done,
    color: goal.color,
    contextLabel: goal.contextLabel,
    vertical: goal.vertical,
    columnVertical: props.vertical,
    foil: goal.foil,
    ghost: goal.ghost,
    ghostUntil: goal.ghostUntil,
    progress: goal.progress,
    subgoalCount: goal.subgoalCount,
    repeat: goal.repeat,
    children: goal.children,
  }
}

const dragTarget = computed(() => store.state.drag.target)
const isReorderHere = computed(() => {
  const target = dragTarget.value
  return target?.kind === 'reorder'
    && target.vertical === props.vertical
    && (target.periodKey ?? null) === (props.periodKey ?? null)
})
/* D249: this column's own TOP-LEVEL splice fires only when the resolved slot's group owner is
   `null` — a rendered nested group's own slot (append included) now belongs to that group's own
   `GoalCard.vue` instance, which reads `dragTarget`/`isReorderHere` off the same store field and
   splices its OWN `.goal-card__children` render instead (mirrors this file's slot markup
   byte-for-byte, D249 doc). Without this gate, a nested-group drop would ALSO render a second,
   misplaced indicator at the top level (`renderItems`' own `findIndex` would just miss and push
   it to the column's very end, since a nested id is never a member of `slide.goals`). */
const isTopLevelReorderHere = computed(() => (
  isReorderHere.value && (dragTarget.value as { parentId: string | null }).parentId === null
))
const isSourceSlot = computed(() => isReorderHere.value
  && store.state.drag.sourceVertical === props.vertical
  && (store.state.drag.sourcePeriodKey ?? null) === (props.periodKey ?? null))
const indicatorStyle = computed(() => {
  const drag = store.state.drag
  if (isSourceSlot.value) return { height: `${drag.slotHeight}px` }
  return {
    height: `${drag.previewHeight}px`,
    marginLeft: `${drag.slotInsetLeft}px`,
    marginRight: `${drag.slotInsetRight}px`,
  }
})
const sourceRowTargetStyle = computed(() => {
  const drag = store.state.drag
  return {
    top: `${drag.slotInsetTop}px`,
    right: `${drag.slotInsetRight}px`,
    bottom: `${drag.slotInsetBottom}px`,
    left: `${drag.slotInsetLeft}px`,
  }
})

type RenderItem =
  | { kind: 'goal'; key: string; goal: GoalCardData }
  | { kind: 'slot'; key: '__dnd-placeholder__' | '__dnd-destination__'; settling: boolean }

type SlideState = 'outgoing' | 'incoming' | 'current'
interface PeriodSlide {
  id: number
  title: string
  subLabel: string
  goals: GoalCardData[]
  periodKey: string | null
  state: SlideState
}

let slideId = 0
function snapshot(state: SlideState): PeriodSlide {
  return {
    id: ++slideId,
    title: props.title,
    subLabel: props.subLabel,
    goals: [...props.goals],
    periodKey: props.periodKey,
    state,
  }
}

function renderItems(slide: PeriodSlide): RenderItem[] {
  const items: RenderItem[] = slide.goals.map((goal) => ({ kind: 'goal', key: goal.id, goal }))
  if (slide.state === 'outgoing' || !isTopLevelReorderHere.value) return items
  const beforeId = (dragTarget.value as { insertBeforeId: string | null }).insertBeforeId
  const found = beforeId === null
    ? items.length
    : items.findIndex((item) => item.kind === 'goal' && item.goal.id === beforeId)
  items.splice(found < 0 ? items.length : found, 0, {
    kind: 'slot',
    key: store.state.drag.settling ? '__dnd-destination__' : '__dnd-placeholder__',
    settling: store.state.drag.settling !== null,
  })
  return items
}

const columnRoot = ref<HTMLElement | null>(null)
const periodTrack = ref<HTMLElement | null>(null)
const slides = ref<PeriodSlide[]>([snapshot('current')])
let latest = slides.value[0]
let swapAnimation: Animation | null = null
let swapVersion = 0

watch(
  () => props.periodSwapId,
  async (swapId) => {
    if (swapId === 0 || props.vertical === 'life') {
      latest = snapshot('current')
      slides.value = [latest]
      return
    }
    const version = ++swapVersion
    swapAnimation?.cancel()
    const outgoing: PeriodSlide = { ...latest, id: ++slideId, state: 'outgoing' }
    const incoming = snapshot('incoming')
    latest = { ...incoming, state: 'current' }
    slides.value = props.periodDirection < 0
      ? [incoming, outgoing]
      : [outgoing, incoming]

    await nextTick()
    if (version !== swapVersion || !periodTrack.value) return
    const frames = props.periodDirection < 0
      ? [{ transform: 'translateX(-50%)' }, { transform: 'translateX(0)' }]
      : [{ transform: 'translateX(0)' }, { transform: 'translateX(-50%)' }]
    const animation = periodTrack.value.animate(frames, {
      duration: 350,
      easing: 'ease',
      fill: 'forwards',
    })
    swapAnimation = animation
    try {
      await animation.finished
    } catch {
      return
    }
    if (version !== swapVersion) return
    slides.value = [{ ...latest, id: ++slideId, state: 'current' }]
    await nextTick()
    animation.cancel()
    if (swapAnimation === animation) swapAnimation = null
  },
  { flush: 'pre' },
)

watch(
  () => [props.title, props.subLabel, props.goals, props.periodKey] as const,
  () => {
    if (slides.value.length !== 1) return
    /* Ordinary writes update the current slide without changing its key. Remounting the whole
       slide here destroys card-local checkbox/completion animations and mutation observers. */
    latest = {
      ...slides.value[0],
      title: props.title,
      subLabel: props.subLabel,
      goals: [...props.goals],
      periodKey: props.periodKey,
      state: 'current',
    }
    slides.value = [latest]
  },
  { flush: 'post' },
)

const insertionSlot = computed(() => {
  if (!isTopLevelReorderHere.value) return undefined
  return (dragTarget.value as { insertBeforeId: string | null }).insertBeforeId
})
watch(insertionSlot, async () => {
  const selector = ':scope > [data-role="period-track"] > [data-state]:not([data-state="outgoing"]) [data-goal-id]'
  const before = new Map(
    [...(columnRoot.value?.querySelectorAll<HTMLElement>(selector) ?? [])]
      .map((element) => [element.dataset.goalId, element.getBoundingClientRect().top]),
  )
  await nextTick()
  for (const element of columnRoot.value?.querySelectorAll<HTMLElement>(selector) ?? []) {
    const oldTop = before.get(element.dataset.goalId)
    if (oldTop === undefined) continue
    const delta = oldTop - element.getBoundingClientRect().top
    if (Math.abs(delta) < 0.5) continue
    element.animate(
      [{ transform: `translateY(${delta}px)` }, { transform: 'translateY(0)' }],
      { duration: 200, easing: 'cubic-bezier(0.2, 0, 0, 1)' },
    )
  }
})

onBeforeUnmount(() => swapAnimation?.cancel())
</script>

<template>
  <div
    ref="columnRoot"
    class="pattern-vertical-board__column"
    :class="{
      'pattern-vertical-board__column--active': active,
      'pattern-vertical-board__column--deck-active': deckActive,
      'pattern-vertical-board__column--deck-main': deckMain,
    }"
    :data-vertical="vertical"
    :data-period-key="periodKey ?? ''"
  >
    <div v-if="vertical !== 'life'" class="column-period-controls" data-cap="period-nav">
      <button
        class="column-period-controls__arrow"
        type="button"
        aria-label="Previous period"
        data-cap="period-prev"
        @click="emit('period-step', vertical, -1)"
      ><AppIcon name="arrow-left" :size="14" /></button>
      <button
        class="column-period-controls__today"
        type="button"
        aria-label="Today"
        data-cap="period-today"
        @click="emit('period-today')"
      ><AppIcon name="today" :size="14" /></button>
      <button
        class="column-period-controls__arrow"
        type="button"
        aria-label="Next period"
        data-cap="period-next"
        @click="emit('period-step', vertical, 1)"
      ><AppIcon name="arrow-right" :size="14" /></button>
    </div>
    <div
      ref="periodTrack"
      class="period-track"
      :class="{ 'period-track--swapping': slides.length === 2 }"
      data-role="period-track"
    >
      <section
        v-for="slide in slides"
        :key="slide.id"
        class="period-slide"
        data-role="period-slide"
        :data-state="vertical === 'life' ? undefined : slide.state"
        :data-period-key="slide.periodKey ?? ''"
      >
        <!-- Header click = expand/unfold toggle (KK ruling 2026-08-17). The pager cluster is a
             sibling of the header, so its own clicks never reach this handler. -->
        <ColumnHeader
          :title="slide.title"
          :sub-label="slide.subLabel"
          data-cap="column-expand"
          @click="onHeaderClick"
        />
        <div class="pattern-vertical-board__body">
          <KCardStack dense>
            <template v-for="item in renderItems(slide)" :key="item.key">
              <div
                v-if="item.kind === 'slot'"
                class="pattern-vertical-board__drop-indicator"
                :data-role="item.settling ? 'drop-destination' : 'drop-indicator'"
                :data-dnd-placeholder="item.settling ? undefined : ''"
                :data-dnd-destination="item.settling ? '' : undefined"
                :data-box="isSourceSlot ? 'card' : 'row'"
                aria-hidden="true"
                :style="indicatorStyle"
              >
                <div
                  v-if="isSourceSlot"
                  class="pattern-vertical-board__drop-row-target"
                  data-role="drop-row-target"
                  :style="sourceRowTargetStyle"
                />
              </div>
              <GoalCard
                v-else
                v-bind="cardProps(item.goal)"
              />
            </template>
            <InlineAdd :placeholder="addPlaceholder" data-cap="create-goal" @add="onAdd" />
          </KCardStack>
        </div>
      </section>
    </div>

  </div>
</template>

<style>
/* Compact board geometry (COMPACT_BOARD_HANDOFF.md §3, HC-1/HC-2): seven EQUAL columns filling
   the viewport exactly — `flex: 1 1 0` shares the strip evenly regardless of content, so there
   is never a horizontal scroll or a dead right gutter. Day gets no special width (KK ruling).
   The expanded column (at most one) takes `100% - 6 * 160px` capped at 400px, which leaves the
   other six exactly 160px each at a 1280px viewport and more above it — the no-scroll law wins
   over the 400px target on narrow screens. */
.pattern-vertical-board.pattern-vertical-board > .pattern-vertical-board__column {
  flex: 1 1 0;
  min-width: 0;
  max-width: 400px;
  position: relative;
  overflow: hidden;
}
.column-period-controls {
  position: absolute;
  z-index: 2;
  top: 6px;
  right: 12px;
  display: flex;
  align-items: baseline;
  gap: 1px;
  opacity: 0;
  pointer-events: none;
  transition: opacity var(--motion-hover) ease;
}
.pattern-vertical-board__column:hover .column-period-controls {
  opacity: 1;
  pointer-events: auto;
}
.column-period-controls__arrow {
  display: inline-flex;
  flex: 0 0 auto;
  align-items: center;
  justify-content: center;
  width: 15px;
  height: 20px;
  margin: 0;
  padding: 0;
  border: 0;
  border-radius: 3px;
  background: transparent;
  color: rgb(45 48 54 / 52%);
  font: inherit;
  font-size: var(--fs-caption, 15px);
  line-height: 20px;
  cursor: pointer;
}
.column-period-controls__arrow:hover,
.column-period-controls__arrow:focus-visible {
  background: rgb(45 48 54 / 8%);
  outline: none;
}
.column-period-controls__arrow:active { background: rgb(45 48 54 / 14%); }
.column-period-controls__today {
  display: inline-flex;
  flex: 0 0 auto;
  align-items: center;
  justify-content: center;
  width: 15px;
  height: 20px;
  margin: 0;
  padding: 0;
  border: 0;
  border-radius: 3px;
  background: transparent;
  color: rgb(45 48 54 / 52%);
  font: inherit;
  font-size: var(--fs-caption, 15px);
  line-height: 20px;
  cursor: pointer;
}
.column-period-controls__today:hover,
.column-period-controls__today:focus-visible {
  background: rgb(45 48 54 / 8%);
  outline: none;
}
.column-period-controls__today:active { background: rgb(45 48 54 / 14%); }
.pattern-vertical-board.pattern-vertical-board
  > .pattern-vertical-board__column.pattern-vertical-board__column--active {
  flex: 0 0 clamp(280px, calc(100% - 6 * 160px), 400px);
  max-width: 400px;
}
/* The whole header is the expand toggle (KK ruling 2026-08-17). */
.pattern-vertical-board__column .pattern-vertical-board__header {
  cursor: pointer;
}
.period-track {
  width: 100%;
  height: 100%;
}
.period-track--swapping {
  display: flex;
  width: 200%;
  will-change: transform;
}
.period-slide {
  position: relative;
  width: 100%;
  height: 100%;
  min-width: 0;
  overflow-x: hidden;
  overflow-y: auto;
  overscroll-behavior: contain;
  scrollbar-width: none;
  -ms-overflow-style: none;
}
.period-slide::-webkit-scrollbar {
  display: none;
}
.period-slide > .pattern-vertical-board__header {
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  height: 72px;
  padding: 4px 12px 0 14px;
}
.period-slide > .pattern-vertical-board__body {
  padding: 88px 2px 64px;
}
.period-track--swapping > .period-slide {
  flex: 0 0 50%;
}
.period-slide[data-state='outgoing'] {
  pointer-events: none;
}
.pattern-vertical-board__drop-indicator {
  position: relative;
  box-sizing: border-box;
  flex: 0 0 auto;
  /* Source reserves the CARD box; destination adds the captured card margins and becomes the ROW
     box. `drag.ts` consumes one of those rendered row boxes raw, never padding-corrected math. */
  align-self: stretch;
  width: auto;
  pointer-events: none;
  border: 0;
  border-radius: 0;
  background: transparent;
  box-shadow: none;
  color: transparent;
  overflow: hidden;
}
.pattern-vertical-board__drop-row-target {
  position: absolute;
  pointer-events: none;
}
@media (max-width: 390px) {
  .pattern-vertical-board.pattern-vertical-board > .pattern-vertical-board__column,
  .pattern-vertical-board.pattern-vertical-board
    > .pattern-vertical-board__column.pattern-vertical-board__column--active {
    flex: 1 0 100%;
    min-width: 100%;
    max-width: none;
  }
}
</style>
