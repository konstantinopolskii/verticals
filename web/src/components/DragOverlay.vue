<script setup lang="ts">
// The flying goal while it is dragged and while it settles (split out of `Board.vue`, docs/design-handoff S5.P1.038):
// a pointer-transparent clone of the rendered row at its grab offset, and the live measure of the drop preview.
import { computed, nextTick, shallowRef, watch } from 'vue'
import { store } from '../store'
import { SETTLE_EASING } from '../lib/drag'
import { dots } from '../lib/spansDrag'
import { spanGoal, spans } from '../lib/spans'
import { findGoal } from '../lib/boardIndex'
import { goalLight } from '../lib/look'
import { atRest } from '../lib/cardLift'

/* Clone the rendered row itself. Copying computed styles before Vue applies the source-ghost
   class preserves every current control and line at the measured footprint without creating a
   second interactive GoalCard instance. */
const overlayHost = shallowRef<HTMLElement | null>(null)
const dragVisualId = computed(() => store.state.drag.id ?? store.state.drag.settling?.id ?? null)
/* Over the spans the goal in the hand is its colour's light wash, lit from under (docs/design-handoff S5.P1.F01). */
const light = computed(() => {
  const id = dragVisualId.value
  if (!spans.vertical || !id) return null
  return goalLight((findGoal(store.state.board, id) ?? spanGoal(id))?.color ?? null)
})

function cloneRenderedRow(id: string): HTMLElement | null {
  // A goal waiting above the field is the one in the hand (docs/design-handoff S5.P3.018).
  const source = document.querySelector<HTMLElement>(`[data-parked][data-goal-id="${CSS.escape(id)}"] > .goal-card__row`)
    ?? document.querySelector<HTMLElement>(`[data-goal-id="${CSS.escape(id)}"] > .goal-card__row`)
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
  /* A coloured goal paints its wash on a layer behind the row (goalCard.css, one highlight shape) and leaves its own box
     clear; the flying card takes that colour, as it did when the box carried it. */
  const layer = getComputedStyle(source, '::before')
  const fromLayer = cardStyle.backgroundColor === 'rgba(0, 0, 0, 0)' && layer.opacity === '1'
  box.style.backgroundColor = fromLayer ? layer.backgroundColor : cardStyle.backgroundColor
  if (fromLayer) box.style.backgroundImage = layer.backgroundImage // a lifted card's wash is laid over its base
  // The goal in the hand is lit as a lifted one is on the board: its wash at the hover strength, over the board.
  else if (cardStyle.backgroundColor === 'rgba(0, 0, 0, 0)') box.style.backgroundColor = liftedWash(card)
  box.style.borderRadius = cardStyle.borderRadius
  box.style.overflow = 'hidden'
  box.style.pointerEvents = 'none'
  box.setAttribute('aria-hidden', 'true')
  box.appendChild(clone)
  return box
}

/* A goal with subtasks drawn under it flies as the whole piece the board shows: its card and its list, copied as they
   look and where they sit around the row. */
function liftedWash(card: HTMLElement): string {
  const style = getComputedStyle(card)
  const wash = style.getPropertyValue('--goal-hover-background').trim() || 'rgb(215, 215, 215)'
  const tint = parseFloat(style.getPropertyValue('--goal-light-tint')) || 0.7
  const ground = style.getPropertyValue('--color-bg').trim() || '#fff'
  return `color-mix(in srgb, ${wash} ${Math.round(tint * 100)}%, ${ground})`
}

function frozenCopy(source: HTMLElement): HTMLElement {
  const clone = source.cloneNode(true) as HTMLElement
  const sources = [source, ...source.querySelectorAll<HTMLElement>('*')]
  const clones = [clone, ...clone.querySelectorAll<HTMLElement>('*')]
  sources.forEach((node, index) => {
    const style = getComputedStyle(node)
    for (const property of style) clones[index].style.setProperty(property, style.getPropertyValue(property))
    clones[index].style.pointerEvents = 'none'
    clones[index].style.visibility = 'visible'
    // A copy must never answer a lookup for the real goal.
    for (const name of ['id', 'data-goal-id', 'data-row-key', 'data-role']) clones[index].removeAttribute(name)
  })
  return clone
}

function cloneFamily(id: string): HTMLElement | null {
  return atRest(() => copyFamily(id))
}

function copyFamily(id: string): HTMLElement | null {
  const row = document.querySelector<HTMLElement>(`[data-parked][data-goal-id="${CSS.escape(id)}"] > .goal-card__row`)
    ?? document.querySelector<HTMLElement>(`[data-goal-id="${CSS.escape(id)}"] > .goal-card__row`)
  const card = row?.parentElement
  const list = card?.nextElementSibling
  if (!row || !card || !(list instanceof HTMLElement) || !list.classList.contains('goal-card__children')) return null
  const origin = row.getBoundingClientRect()
  const family = document.createElement('div')
  family.style.position = 'absolute'
  family.style.left = '0'
  family.style.top = '0'
  family.style.pointerEvents = 'none'
  family.setAttribute('aria-hidden', 'true')
  for (const part of [card, list]) {
    const box = part.getBoundingClientRect()
    const copy = frozenCopy(part)
    copy.style.position = 'absolute'
    copy.style.margin = '0'
    copy.style.transform = 'none'
    copy.style.left = `${box.left - origin.left}px`
    copy.style.top = `${box.top - origin.top}px`
    copy.style.width = `${box.width}px`
    copy.style.height = `${box.height}px`
    // Lit as a lifted piece is on the board (lib/cardLift.ts), without its growth: the copy holds its size.
    copy.classList.add(part === card ? 'goal-card--lifted' : 'goal-card__children--lifted')
    family.appendChild(copy)
  }
  return family
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
    const clone = cloneFamily(id) ?? cloneRenderedRow(id)
    if (!clone) return
    void nextTick(() => overlayHost.value?.replaceChildren(clone))
  },
  { flush: 'sync' },
)

const dragPreviewKey = computed(() => {
  const drag = store.state.drag
  if (!drag.id) return ''
  // Keyed on `slot`: re-measuring during a combine would resize the held placeholder.
  const slot = drag.slot
  // D249: `parentId` is part of the key too — two different rendered groups sharing one column
  // can both resolve `insertBeforeId: null` (each group's own append slot), and without the
  // group owner in the key those two genuinely different targets would collapse onto the same
  // measurement, leaving the preview sized off whichever indicator happened to render first.
  if (slot) {
    return `${drag.id}:reorder:${slot.vertical}:${slot.periodKey ?? ''}:${slot.insertBeforeId ?? ''}:${slot.parentId ?? ''}`
  }
  const target = drag.target
  return target?.kind === 'combine' ? `${drag.id}:combine:${target.targetId}` : `${drag.id}:none`
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
    if (!drag.slot && target?.kind === 'combine') {
      const row = document.querySelector<HTMLElement>(
        `[data-goal-id="${CSS.escape(target.targetId)}"] > .goal-card__row`,
      )
      const rect = row?.getBoundingClientRect()
      if (rect) store.setDragPreviewSize(rect.width, renderedRowHeightAtWidth(id, rect.width) ?? drag.height)
      return
    }
    if (!drag.slot) {
      store.setDragPreviewSize(drag.width, drag.height)
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
  <!-- P-02/M2: pointer-transparent clone of the complete rendered row at its grab offset. -->
  <div
    v-if="dragVisualId"
    ref="overlayHost"
    class="pattern-vertical-board__drag-overlay"
    :class="{ 'drag-overlay--melted': dots.melted, 'drag-overlay--lit': light }"
    data-role="drag-overlay"
    data-dnd-overlay
    :style="[overlayStyle, light ?? {}, { '--grab-x': `${store.state.drag.offsetX}px`, '--grab-y': `${store.state.drag.offsetY}px` }]"
  />
</template>

<style>
/* Resting on a column's dots the goal melts into them, and grows back out under the hand once the spans have come
   (docs/design-handoff S5.P2.013, .015). */
.pattern-vertical-board__drag-overlay > * {
  transform-origin: var(--grab-x) var(--grab-y);
  transition: transform 200ms var(--vt-ease-large), filter 200ms var(--vt-ease-large), opacity 200ms var(--vt-ease-large);
}
.drag-overlay--melted > * { transform: scale(.55); filter: blur(3px); opacity: 0; }
.drag-overlay--lit > * {
  background-color: rgb(var(--vt-pale)) !important;
  box-shadow: 0 0 0 1px rgba(var(--vt-tint), .07), 0 8px 20px -4px rgba(var(--vt-tint), .15), 0 52px 128px -12px rgba(var(--vt-tint), .35);
}
@media (prefers-reduced-motion: reduce) {
  .pattern-vertical-board__drag-overlay > * { transition: opacity 120ms linear; }
  .drag-overlay--melted > * { transform: none; filter: none; }
}
</style>
