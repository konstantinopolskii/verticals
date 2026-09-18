<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, onUpdated, ref, watch } from 'vue'
import type { ComponentPublicInstance } from 'vue'
import { KCard } from '@konstantinopolskii/vue'
import { COMPLETION_LOTTIE, useCompletionCelebration } from '../lib/completionCelebration'
import { useInlineTitleEdit } from '../lib/inlineTitleEdit'
import { playSound } from '../lib/sound'
import {
  registerIridescentCard,
  unregisterIridescentCard,
} from '../kit-ext/iridescent'
import RepeatMark from './RepeatMark.vue'
import GoalCardTools from './GoalCardTools.vue'
import GoalDetail from './GoalDetail.vue'
import GoalAffordance from '../kit-ext/goal-affordance/GoalAffordance.vue'
import { store } from '../store'
import type { GoalCardData } from '../types'
import type { RepeatRule } from '../lib/api'
import { goalWashInk } from '../lib/goalColor'
import { devPaletteFor, rgbaFromHex } from '../lib/devPalette'
import { ancestorIds, subtreeIds } from '../lib/boardIndex'
import '../kit-ext/carryover-ghost/carryover-ghost.css'

const props = withDefaults(
  defineProps<{
    id: string
    parentId?: string | null
    title: string
    done?: boolean
    /** One of the six canon hexes, or unset for no colour (docs/UI_MEASURED.md §5). Arrives
     *  DERIVED since D231: the server resolves every card's colour from its value root. */
    color?: string | null
    /** Polymorphic per docs/UI_MEASURED.md §6 — the caller decides which sense fills this slot. */
    contextLabel?: string
    /** Search-only period slot. Empty string deliberately renders an empty marked element. */
    searchPeriod?: string
    /** Search-only explicit open affordance; board cards retain their existing title/row gesture. */
    searchOpen?: boolean
    /** `goals.vertical`, retained for existing card-menu behavior. */
    vertical?: string | null
    /** Column where this rendered instance lives; owns movable-main detail context (D186). */
    columnVertical?: string | null
    repeat?: RepeatRule | null
    foil?: boolean
    ghost?: boolean
    ghostUntil?: string | null
    /** `BoardResponse.progress[id]` — done/total over descendants. Absent on a leaf. */
    progress?: { done: number; total: number }
    subgoalCount?: number
    children?: GoalCardData[]
    depth?: number
  }>(),
  {
    done: false,
    parentId: null,
    color: null,
    contextLabel: '',
    searchPeriod: undefined,
    searchOpen: false,
    vertical: null,
    columnVertical: null,
    repeat: null,
    foil: false,
    ghost: false,
    ghostUntil: null,
    progress: undefined,
    subgoalCount: 0,
    children: () => [],
    depth: 0,
  },
)

const checked = computed(() => props.done)
const cardStyle = computed(() => {
  const palette = devPaletteFor(props.color)
  return { '--goal-hover-background': palette?.card
    ? rgbaFromHex(palette.card.color, palette.card.opacity)
    : (props.color
    ? `rgb(${goalWashInk(props.color).washRgb})`
    : '#d7d7d7') }
})
const cardRoot = ref<ComponentPublicInstance | null>(null)

function rootElement(): HTMLElement | null {
  return cardRoot.value?.$el instanceof HTMLElement ? cardRoot.value.$el : null
}

function syncIridescentRegistration(): void {
  const element = rootElement()
  if (!element) return
  if (props.foil) registerIridescentCard(element)
  else unregisterIridescentCard(element)
}

onMounted(syncIridescentRegistration)
watch(() => props.foil, syncIridescentRegistration, { flush: 'post' })
// Any re-render can rewrite the class attribute and wipe the imperative foil tier class
// (a D237 live refetch flipping data-colored is the everyday case) — re-assert after updates.
onUpdated(syncIridescentRegistration)
onBeforeUnmount(() => {
  // Scheduling, parking, or moving an expanded card may remove this rendered host before its
  // inline close animation can run. Never leave the board pinned to an owner that no longer exists.
  if (isInlineDetailHost.value) store.closeGoal()
  const element = rootElement()
  if (element) unregisterIridescentCard(element)
})

const isParent = computed(
  () => props.subgoalCount > 0 || (props.progress?.total ?? 0) > 0,
)

function onToggle(value: boolean) {
  playSound(value ? 'checked' : 'unchecked')
  void store.completeGoal(props.id, value)
}

const detailHostKey = computed(() => [
  props.columnVertical ?? 'global', props.parentId ?? 'root', props.depth, props.id,
].join(':'))
const isInlineDetailHost = computed(() => (
  (store.state.activeView === 'verticals' || store.state.activeView === 'inbox')
  && store.state.openGoalHostKey === detailHostKey.value
  && store.state.openGoalVertical === props.columnVertical
))
const isOpenRelated = computed(() => {
  const openId = store.state.openGoalId
  if (!openId || !store.state.board) return false
  if (props.id === openId) return true
  return ancestorIds(store.state.board, openId).includes(props.id)
    || subtreeIds(store.state.board, openId).has(props.id)
})
/* D248 WP-B: self-or-ancestor of the open card ONLY (unlike `isOpenRelated` above, which also
   includes the open card's own subtree). This is the narrower test the children-block guard
   below needs: every card sitting on the path from an opened goal up to its board root must keep
   rendering its children div past the ordinary `depth < 2` cap, or the open card itself would
   never reach the DOM. */
const isSelfOrAncestorOfOpen = computed(() => {
  const openId = store.state.openGoalId
  if (!openId || !store.state.board) return false
  if (props.id === openId) return true
  return ancestorIds(store.state.board, openId).includes(props.id)
})
const showChildren = computed(() => (
  props.children.length > 0 && (props.depth < 2 || isSelfOrAncestorOfOpen.value)
))

function onOpenDetail() {
  // Board cards route through `openBoardGoal`, which expands the card's column first (KK ruling
  // 2026-08-17: card click = expand + open in one gesture). Non-board contexts (search results,
  // inbox) keep the direct open unchanged.
  if (props.columnVertical && props.columnVertical !== 'maybe' && store.state.activeView === 'verticals') {
    void store.openBoardGoal(props.id)
    return
  }
  void store.openGoal(props.id, props.columnVertical, detailHostKey.value)
}

function onTitleClick() {
  if (isInlineDetailHost.value) startInlineTitleEdit()
  else onOpenDetail()
}

/* Hover family chain — D235: both directions, ancestors up and descendants down. The wash class
   is a REACTIVE bind off `store.hoverChain` rather than `ancestorHover.ts`'s old imperative DOM
   toggling, since Vue's class patching drops imperatively-added classes on every patch (the
   iridescent registration fights the same battle with `onUpdated`). One reactive source survives
   any re-render. */
function highlightFamily(): void {
  store.setHoverChain(props.id)
}
function clearFamily(): void {
  if (store.state.hoverChainId === props.id) store.setHoverChain(null)
}
const isChainHovered = computed(() => {
  const chain = store.hoverChain.value
  return chain !== null && chain.id !== props.id && chain.set.has(props.id)
})
// R7 can carry one goal twice on the wire (its filtered top-level copy and its nested copy).
// Completion mutates optimistically and updates the shared progress rollup, so use that rollup
// rather than a possibly stale child copy. Requiring rendered children keeps ancestor cards from
// celebrating the same completion when their descendants live in lower-vertical columns.
const childrenAllDone = computed(() =>
  props.children.length > 0
  && (props.progress?.total ?? 0) > 0
  && props.progress?.done === props.progress?.total,
)
const completionLayer = ref<HTMLElement | null>(null)
const completionMedia = ref<SVGSVGElement | null>(null)
const { completionActive } = useCompletionCelebration(
  childrenAllDone,
  completionLayer,
  completionMedia,
)

const hasMilestone = computed(() => (props.progress?.total ?? 0) > 0)

const menuOpen = ref(false)
const tools = ref<{ openMenu: () => void } | null>(null)

/* Inline title editing — one edit lifecycle, extracted to `lib/inlineTitleEdit.ts` (S-90a). The
   destructured names keep every existing template binding byte-identical; the textarea ref stays
   declared here because the template binds it (same split as the completion layer/media refs). */
const inlineTitleInput = ref<HTMLTextAreaElement | null>(null)
const {
  editing: editingInlineTitle,
  draft: inlineTitleDraft,
  start: startInlineTitleEdit,
  onInput: onInlineTitleInput,
  commit: commitInlineTitle,
  cancel: cancelInlineTitleEdit,
} = useInlineTitleEdit({
  title: () => props.title,
  commit: (next) => void store.updateGoal(props.id, { title: next }),
  input: inlineTitleInput,
})

function onMenuOpenChange(value: boolean) {
  menuOpen.value = value
}

function openContextMenu(): void {
  tools.value?.openMenu()
}

function onAffordanceClick(event: MouseEvent): void {
  if (!isParent.value) return
  event.preventDefault()
  event.stopPropagation()
  openContextMenu()
}

/** Keyboard path (space on the focused checkbox) bypasses the click capture above, so the
 *  parent guard lives here too: a parent affordance never one-click completes. */
function onAffordanceToggle(value: boolean): void {
  if (isParent.value) {
    openContextMenu()
    return
  }
  onToggle(value)
}

function onCardContextMenu(event: MouseEvent): void {
  event.preventDefault()
  openContextMenu()
}

function completeParent(): void {
  playSound('checked'); void store.completeGoal(props.id, true)
}
function toggleFoil(): void { void store.updateGoal(props.id, { foil: !props.foil }) }
function park(): void {
  playSound('goal_deleted')
  void store.parkGoal(props.id)
}
function ignoreGhost(): void {
  if (props.ghostUntil) void store.ignoreGhost(props.id, props.ghostUntil)
}
function ackDue(): void { void store.dueAckGhost(props.id, 'overdue') }
function ackDoneOnTime(): void { void store.dueAckGhost(props.id, 'done_on_time') }

/* The compact row keeps its DOM identity while inline detail is open. Drag state may still hide
   that same row temporarily; opening detail never replaces it with a second editor heading. */
const isDragSource = computed(
  () => store.state.drag.id === props.id || store.state.drag.settling?.id === props.id,
)
const isCombineTarget = computed(
  () => store.state.drag.id !== null
    && store.state.drag.target?.kind === 'combine'
    && store.state.drag.target.targetId === props.id,
)
/* D245 (KK ruling 2026-08-18): collapsing the source to height 0 only works at TOP level
 * (`depth === 0`) because Column.vue's own `__dnd-placeholder__` slot item already reserves that
 * CARD box elsewhere in the column — collapsing the original avoids doubling the gap. Nothing
 * inside `.goal-card__children` plays that role for a nested subtask, so collapsing one there
 * used to shrink the parent's rendered height the instant the drag armed (owner report: "a
 * nested subtask collapses ... its parent card snaps shut"). `isNestedDragHole` below is the
 * nested counterpart: it leaves this card at its natural (untouched) box instead. */
const closesSourceGap = computed(
  () => props.depth === 0 && isDragSource.value && store.state.drag.settling?.cancelled !== true,
)
/* D245: a nested source keeps its own CARD footprint — exactly the box `slotWidth`/`slotHeight`
 * captured at pointer-down, since this element IS that measurement's own target and nothing here
 * changes its size. `goalCard.css`'s `--nested-drag-hole` rule only strips it from hit-testing
 * (`pointer-events: none`), matching what `--source-gap-closed` already does for the top-level
 * case — without it `hitTest`'s `elementFromPoint` would resolve back to this card's own id
 * instead of falling through to whatever is actually under the pointer. */
const isNestedDragHole = computed(() => props.depth > 0 && isDragSource.value)

// --- D249: this card's own nested reorder slot -------------------------------------------------
//
// The mirror of `Column.vue`'s `isReorderHere`/`renderItems`/`insertionSlot`, scoped to whichever
// rendered group THIS card owns (`target.parentId === props.id`) instead of a column identity —
// a resolved slot's group owner is already a specific, globally unique goal id, so no
// vertical/periodKey comparison is needed to know "is this mine" the way Column.vue's own column
// identity check needs. Markup/CSS below is the same slot element Column.vue renders, reused
// verbatim (`pattern-vertical-board__drop-indicator`, same data attributes) — not a new visual.
//
// Known tradeoff (not fixed here): a NESTED drag source keeps its pre-existing D245 treatment —
// `isNestedDragHole` above, natural box, content emptied, no height collapse (`test_hd1_nested_
// pickup_leaves_a_hole` pins this exactly, by class name, and is unrelated to this fix's own
// scope). Top-level sources collapse (`closesSourceGap`) because a compensating placeholder has
// existed at that level since D245; giving a nested source the same treatment now that its own
// compensating placeholder exists too would improve the polish, but risks that pinned invariant
// for a cosmetic gain outside this task's brief — left as a follow-up, not attempted here. The
// practical effect during a same-group nested drag is a slightly taller family block for the
// gesture's duration (the source's own natural-height hole, plus the placeholder), never a
// wrong position or a wrong write.
const dragSlot = computed(() => store.state.drag.slot)
/* D249 hole-is-the-indicator rule, mirroring `reorderWrite`'s own no-op detection in drag.ts
   (same after_id -> null PATCH): when the resolved reorder slot lands exactly where the source
   already sits within THIS card's own children -- its current next sibling, or append when it's
   already last -- render no indicator at all. A nested source never collapses (D245's `test_hd1_
   nested_pickup_leaves_a_hole` pins that), so unlike a top-level drag (whose source collapse
   always cancels the indicator's height, leaving total height unchanged everywhere), a nested
   indicator shown at the no-op position would add a full extra row with nothing compensating it
   -- the family block would grow the instant the card is picked up, before any real move is
   even attempted. The natural, uncollapsed hole already reads as "this card left a gap here";
   stacking a placeholder on top of it is redundant, so this rule only suppresses that redundant
   case -- every other position still renders the indicator normally. */
const isNestedReorderHere = computed(() => {
  const slot = dragSlot.value
  if (!slot || slot.parentId !== props.id) return false
  const sourceId = store.state.drag.id
  const ownIndex = props.children.findIndex((child) => child.id === sourceId)
  if (ownIndex === -1) return true
  const currentNextId = props.children[ownIndex + 1]?.id ?? null
  return slot.insertBeforeId !== currentNextId
})
/* Mirrors Column.vue's own `isSourceSlot`: true when this nested slot sits in the SAME COLUMN the
   drag started in (not necessarily the same parent — adopting into a different nested group in
   that same column still keeps the smaller vacated-CARD sizing, since nothing about the column's
   own width changed crossing parents within it). Sizes the indicator off `slotHeight` (the
   vacated box) instead of `previewHeight` (a measured destination row) — same CARD-vs-ROW law
   Column.vue's own `indicatorStyle` documents, reused rather than reinvented. */
const isNestedSourceSlot = computed(() => {
  const slot = dragSlot.value
  if (!isNestedReorderHere.value || !slot) return false
  return store.state.drag.sourceVertical === slot.vertical
    && (store.state.drag.sourcePeriodKey ?? null) === (slot.periodKey ?? null)
})
const nestedIndicatorStyle = computed(() => {
  const drag = store.state.drag
  if (isNestedSourceSlot.value) return { height: `${drag.slotHeight}px` }
  return {
    height: `${drag.previewHeight}px`,
    marginLeft: `${drag.slotInsetLeft}px`,
    marginRight: `${drag.slotInsetRight}px`,
  }
})
const nestedSourceRowTargetStyle = computed(() => {
  const drag = store.state.drag
  return {
    top: `${drag.slotInsetTop}px`,
    right: `${drag.slotInsetRight}px`,
    bottom: `${drag.slotInsetBottom}px`,
    left: `${drag.slotInsetLeft}px`,
  }
})

type ChildRenderItem =
  | { kind: 'goal'; key: string; goal: GoalCardData }
  | { kind: 'slot'; key: '__dnd-placeholder__' | '__dnd-destination__'; settling: boolean }

/** Mirrors `Column.vue`'s own `renderItems` exactly, scoped to THIS card's own children instead
 *  of a column's top-level list — see that function's own doc comment for the splice shape
 *  (`insertBeforeId: null` appends after every existing child). */
function renderChildren(): ChildRenderItem[] {
  const items: ChildRenderItem[] = props.children.map((goal) => ({ kind: 'goal', key: goal.id, goal }))
  if (!isNestedReorderHere.value) return items
  const beforeId = dragSlot.value?.insertBeforeId ?? null
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

const childrenListEl = ref<HTMLElement | null>(null)
const nestedInsertionSlot = computed(() => (
  isNestedReorderHere.value
    ? (dragSlot.value?.insertBeforeId ?? null)
    : undefined
))
/* The same tiny FLIP Column.vue's own `insertionSlot` watch runs, scoped to this card's own
   children list so a nested reorder's neighbours slide instead of jumping — mirrored, not
   reinvented. */
watch(nestedInsertionSlot, async () => {
  const selector = ':scope > [data-goal-id]'
  const before = new Map(
    [...(childrenListEl.value?.querySelectorAll<HTMLElement>(selector) ?? [])]
      .map((element) => [element.dataset.goalId, element.getBoundingClientRect().top]),
  )
  await nextTick()
  for (const element of childrenListEl.value?.querySelectorAll<HTMLElement>(selector) ?? []) {
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

/* The row is drag entry surface, ordered-slot target, and container of every card control, so
   every pointer handler below ignores anything that started on a control.
   The portalled context menu stops its own events; this guard covers the affordance, title and
   schedule trigger, which are not its descendants. */
function fromControl(event: Event): boolean {
  const el = event.target as HTMLElement | null
  return !!el?.closest(
    'button, input, textarea, label, a, [data-role="tag"], .chip, .goal-card__tools, .dropdown',
  )
}

/* Arms nothing by itself — `store.ts::pointerDownCard` only remembers where the press started
   and the card's own on-screen rect. Moving strictly beyond 5px turns desktop input into a drag (as
   opposed to the plain `click` a tap-and-release produces, handled below unchanged) lives in
   `lib/drag.ts`, read on the next `pointermove` `Board.vue`'s own window listener forwards. */
function onRowPointerDown(event: PointerEvent) {
  if (fromControl(event)) return
  const row = event.currentTarget as HTMLElement
  row.focus({ preventScroll: true })
  const rect = row.getBoundingClientRect()
  store.pointerDownCard(props.id, event.clientX, event.clientY, rect, event.pointerType, event.altKey)
}

/* A `click` fires on the nearest common ancestor of its `pointerdown` and its `pointerup` with no
   intervening drag, so an armed drag (which moved the pointer past the 5px threshold) never
   produces one — open and drop cannot both fire from one gesture, without either handler
   needing to know about the other.

   Owner ruling, 2026-08-09: a plain click OPENS the goal — the incumbent's behaviour — it does
   not select. Click-to-select plus the bulk bar was this board's own invention ("why tasks are
   still can be selected if I click them and shitty stuff on the top appears? I don't need it"),
   and it is gone: no selection state, no shift-click range, no bulk bar. Bulk update itself is
   not a lost capability — it stays reachable over HTTP and MCP (`PATCH /api/goals` with `ids[]`,
   S-44/S-133), it just has no board gesture any more, exactly the shape `reorder` had for one
   pass and the F5 manifest's `null` selector exists to record. */
function onRowClick(event: MouseEvent) {
  if (fromControl(event)) return
  onOpenDetail()
}

function onRowKeydown(event: KeyboardEvent) {
  if (!['/', 'Slash', 'Enter', ' '].includes(event.key)) return
  // Slash is the card-level options shortcut even when focus currently sits on a descendant.
  // Enter/Space remain owned by that descendant so native control activation is unchanged.
  if (!['/', 'Slash'].includes(event.key) && fromControl(event)) return
  event.preventDefault()
  if (event.key === 'Enter') startInlineTitleEdit()
  else if (event.key === ' ') onOpenDetail()
  else openContextMenu()
}

</script>

<template>
  <KCard
    ref="cardRoot"
    dense
    class="goal-card"
    :class="{
      'goal-card--source-gap-closed': closesSourceGap,
      'goal-card--nested-drag-hole': isNestedDragHole,
      'goal-card--menu-open': menuOpen,
      'goal-card--colored': color,
      'goal-card--done': checked,
      'goal-card--detail-open': isInlineDetailHost,
      'goal-card--open-related': isOpenRelated,
      'goal-card--ancestor-hover': isChainHovered,
      foil,
      'carryover-ghost': ghost,
    }"
    :data-goal-id="id"
    :style="cardStyle"
    :data-parent-id="parentId ?? undefined"
    :data-colored="color ? 'true' : 'false'"
    :data-foil="foil ? 'true' : undefined"
    :data-ghost="ghost ? 'true' : undefined"
    @mouseenter="highlightFamily"
    @mouseleave="clearFamily"
  >
    <div
      class="goal-card__row"
      data-role="drop-target"
      data-cap="reorder"
      role="button"
      tabindex="0"
      :aria-hidden="isDragSource ? 'true' : undefined"
      :class="{
        'goal-card__row--detail-open': isInlineDetailHost,
        'goal-card__row--drag-source': isDragSource,
        'goal-card__row--combine-target': isCombineTarget,
        'goal-card__row--combine-target-colored': isCombineTarget && color,
      }"
      :data-dnd-combine-target="isCombineTarget ? '' : undefined"
      @pointerdown="onRowPointerDown"
      @click="onRowClick"
      @contextmenu.stop="onCardContextMenu"
      @keydown="onRowKeydown"
    >
      <span
        class="goal-card__affordance-slot"
        data-role="goal-affordance"
        :data-affordance="isParent ? 'parent' : 'leaf'"
        :role="isParent ? 'button' : undefined"
        :aria-haspopup="isParent ? 'menu' : undefined"
        @click.capture="onAffordanceClick"
      >
        <GoalAffordance
          :kind="hasMilestone ? 'ring' : 'square'"
          :checked="checked"
          :done="progress?.done ?? 0"
          :total="progress?.total ?? 0"
          :color="color"
          @toggle="onAffordanceToggle"
        />
      </span>
      <div class="goal-card__text">
        <p
          v-if="!editingInlineTitle"
          class="goal-card__title"
          :data-cap="isInlineDetailHost ? 'edit-title' : undefined"
          @click.stop="onTitleClick"
        >
          <span class="goal-card__title-text" :class="{ 'goal-card__title-text--repeat': repeat }">
            <RepeatMark v-if="repeat" />
            <span v-if="ghost" class="goal-card__due">Due. </span>{{ title }}
          </span>
        </p>
        <textarea
          v-else
          ref="inlineTitleInput"
          class="goal-card__title goal-card__title-input"
          :data-cap="isInlineDetailHost ? 'edit-title' : undefined"
          rows="1"
          :value="inlineTitleDraft"
          @click.stop
          @pointerdown.stop
          @input="onInlineTitleInput"
          @keydown.enter.prevent.stop="commitInlineTitle"
          @keydown.esc.prevent.stop="cancelInlineTitleEdit"
          @blur="commitInlineTitle"
        />
        <p
          v-if="searchPeriod !== undefined"
          data-role="search-period"
          class="goal-card__meta"
        >{{ searchPeriod }}</p>
        <button
          v-if="searchOpen"
          type="button"
          data-role="search-open"
          class="goal-card__search-open"
          @click.stop="onOpenDetail"
        >Open</button>
        <p v-if="contextLabel" class="goal-card__meta">{{ contextLabel }}</p>
      </div>
      <GoalCardTools
        ref="tools"
        :id="id"
        :has-children="subgoalCount > 0"
        :is-parent="isParent"
        :vertical="vertical"
        :repeat="repeat"
        :foil="foil"
        :show-ignore="ghost"
        @details="onOpenDetail"
        @complete="completeParent"
        @foil="toggleFoil"
        @park="park"
        @ignore="ignoreGhost"
        @ack-due="ackDue"
        @ack-done="ackDoneOnTime"
        @open-change="onMenuOpenChange"
      />
    </div>
    <GoalDetail v-if="isInlineDetailHost" />
  </KCard>
  <div
    v-if="showChildren"
    ref="childrenListEl"
    class="goal-card__children subgoal-recursive-list"
    :style="{ '--subgoal-depth': String(depth) }"
  >
      <div
        v-if="completionActive"
        ref="completionLayer"
        class="goal-card__completion"
        data-role="completion-animation"
      >
        <svg
          ref="completionMedia"
          :viewBox="`0 0 ${COMPLETION_LOTTIE.width} ${COMPLETION_LOTTIE.height}`"
          preserveAspectRatio="xMidYMid slice"
          data-format="lottie"
          :data-width="COMPLETION_LOTTIE.width"
          :data-height="COMPLETION_LOTTIE.height"
          :data-frame-rate="COMPLETION_LOTTIE.frameRate"
          :data-first-frame="COMPLETION_LOTTIE.firstFrame"
          :data-last-frame="COMPLETION_LOTTIE.lastFrame"
          data-loop="false"
          data-autoplay="true"
          aria-hidden="true"
        >
          <g class="goal-card__completion-rays">
            <path d="M1000 100 1000 500M1000 1500 1000 1900M100 1000 500 1000M1500 1000 1900 1000" />
            <path d="m360 360 285 285m710 710 285 285m0-1280-285 285m-710 710-285 285" />
          </g>
          <circle cx="1000" cy="1000" r="270" />
        </svg>
      </div>
      <template v-for="item in renderChildren()" :key="item.key">
        <!-- D249: same slot markup Column.vue renders at the top level, byte-for-byte — a
             rendered nested group's own reorder slot (append included) is a first-class target
             now, so it needs the same visible drop indicator a top-level slot always had. -->
        <div
          v-if="item.kind === 'slot'"
          class="pattern-vertical-board__drop-indicator"
          :data-role="item.settling ? 'drop-destination' : 'drop-indicator'"
          :data-dnd-placeholder="item.settling ? undefined : ''"
          :data-dnd-destination="item.settling ? '' : undefined"
          :data-box="isNestedSourceSlot ? 'card' : 'row'"
          aria-hidden="true"
          :style="nestedIndicatorStyle"
        >
          <div
            v-if="isNestedSourceSlot"
            class="pattern-vertical-board__drop-row-target"
            data-role="drop-row-target"
            :style="nestedSourceRowTargetStyle"
          />
        </div>
        <GoalCard
          v-else
          :id="item.goal.id"
          :parent-id="item.goal.parentId"
          :title="item.goal.title"
          :done="item.goal.done"
          :color="item.goal.color"
          :context-label="item.goal.contextLabel"
          :vertical="item.goal.vertical"
          :column-vertical="columnVertical"
          :foil="item.goal.foil"
          :ghost="item.goal.ghost"
          :ghost-until="item.goal.ghostUntil"
          :progress="item.goal.progress"
          :subgoal-count="item.goal.subgoalCount"
          :children="item.goal.children"
          :depth="depth + 1"
        />
      </template>
  </div>
</template>

<!-- Unscoped on purpose (matches every other component here); rules live in `goalCard.css`
     since the S-90a split — moved byte-for-byte, zero selector or value changes. -->
<style src="./goalCard.css"></style>
