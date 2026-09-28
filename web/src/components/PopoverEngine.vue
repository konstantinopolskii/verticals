<script setup lang="ts">
import {
  computed,
  inject,
  nextTick,
  onBeforeUnmount,
  onMounted,
  provide,
  reactive,
  ref,
  watch,
} from 'vue'
import {
  placePopover,
  type PopoverPlacement as Placement,
  type PopoverRect,
} from '../lib/popover'

type MenuItem = string | { label: string; value: unknown }
type InlineMode = boolean | 'auto'
type SurfaceAttrs = Record<string, string | number | boolean | undefined>
interface ChildHandle {
  id: symbol
  inline: boolean
  close: () => void
  contains: (target: Node) => boolean
}

interface ParentContext {
  rootTarget: () => HTMLElement | null
  rootPlacement: () => Placement
  activeChild: ChildHandle | null
  activateChild: (child: ChildHandle) => void
  clearChild: (id: symbol) => void
}

const props = withDefaults(defineProps<{
  label?: string
  items?: MenuItem[]
  placement?: Placement
  fixedWidth?: number | string
  offset?: [number, number]
  nested?: boolean
  inline?: InlineMode
  mobile?: boolean
  darkBody?: boolean
  surfaceClass?: string
  surfaceAttrs?: SurfaceAttrs
}>(), {
  label: 'Options',
  items: () => [],
  nested: false,
  inline: 'auto',
  mobile: false,
  darkBody: false,
})

const emit = defineEmits<{
  select: [item: MenuItem]
  open: []
  close: []
}>()

const parent = inject<ParentContext | null>('popover-parent', null)
const id = Symbol('popover')
const rootEl = ref<HTMLElement | null>(null)
const surfaceEl = ref<HTMLElement | null>(null)
const open = ref(false)
const resolvedPlacement = ref<Placement>(props.placement ?? 'bottom-start')
const viewportWidth = ref(typeof window === 'undefined' ? 1024 : window.innerWidth)
const parentState = reactive<Pick<ParentContext, 'activeChild'>>({ activeChild: null })
let stopAutoUpdate: (() => void) | null = null
let hoverTimer: number | null = null
let safeMoveListener: ((event: PointerEvent) => void) | null = null
let stopNextEscapeKeyup = false
let safeOrigin = { x: 0, y: 0 }

const targetEl = computed(() => rootEl.value?.firstElementChild as HTMLElement | null)
const inlineActive = computed(() => props.nested && (
  props.inline === true
  || (props.inline === 'auto' && (props.mobile || viewportWidth.value < 694))
))

function rootTarget(): HTMLElement | null {
  return parent?.rootTarget() ?? targetEl.value
}

const context: ParentContext = {
  rootTarget,
  rootPlacement: () => parent?.rootPlacement() ?? resolvedPlacement.value,
  get activeChild() { return parentState.activeChild },
  set activeChild(value) { parentState.activeChild = value },
  activateChild(child) {
    if (parentState.activeChild?.id !== child.id) parentState.activeChild?.close()
    parentState.activeChild = child
  },
  clearChild(childId) {
    if (parentState.activeChild?.id === childId) parentState.activeChild = null
  },
}
provide<ParentContext>('popover-parent', context)

function decorateTarget() {
  const target = targetEl.value
  if (!target) return
  target.classList.add('Menu-target', 'dropdown__trigger')
  target.classList.toggle('_open', open.value)
  target.dataset.isMenuReference = 'true'
  target.setAttribute('aria-haspopup', 'menu')
  target.setAttribute('aria-expanded', String(open.value))
}

function effectivePlacement(): Placement | undefined {
  if (inlineActive.value) return parent?.rootPlacement()
  if (props.nested) return props.placement ?? 'right'
  return props.placement
}

function effectiveOffset(): [number, number] {
  if (props.offset) return props.offset
  return props.nested && !inlineActive.value ? [4, -8] : [4, 0]
}

function widthCss(value: number | string): string {
  return typeof value === 'number' ? `${value}px` : value
}

function viewportRect(): PopoverRect {
  return { x: 0, y: 0, width: window.innerWidth, height: window.innerHeight }
}

function intersectRects(left: PopoverRect, right: DOMRect): PopoverRect {
  const x = Math.max(left.x, right.left)
  const y = Math.max(left.y, right.top)
  const edgeX = Math.min(left.x + left.width, right.right)
  const edgeY = Math.min(left.y + left.height, right.bottom)
  return { x, y, width: Math.max(0, edgeX - x), height: Math.max(0, edgeY - y) }
}

function clippingRect(surface: HTMLElement): PopoverRect {
  let boundary = viewportRect()
  let ancestor = surface.parentElement
  while (ancestor && ancestor !== document.documentElement) {
    const style = getComputedStyle(ancestor)
    if (/(auto|scroll|hidden|clip)/.test(`${style.overflow} ${style.overflowX} ${style.overflowY}`)) {
      boundary = intersectRects(boundary, ancestor.getBoundingClientRect())
    }
    ancestor = ancestor.parentElement
  }
  return boundary
}

function elementRect(element: Element): PopoverRect {
  const rect = element.getBoundingClientRect()
  return { x: rect.x, y: rect.y, width: rect.width, height: rect.height }
}

function updatePosition() {
  const surface = surfaceEl.value
  const target = inlineActive.value ? parent?.rootTarget() : targetEl.value
  if (!surface || !target || !open.value) return

  if (props.fixedWidth !== undefined) surface.style.width = widthCss(props.fixedWidth)
  else surface.style.removeProperty('width')
  surface.style.maxWidth = 'none'
  surface.style.maxHeight = 'none'
  const anchor = elementRect(target)
  const boundary = clippingRect(surface)
  const config = {
    placement: effectivePlacement() ?? 'auto' as const,
    offset: effectiveOffset(),
    collisionPadding: 8,
    sizeReserve: 16,
  }
  let result = placePopover(anchor, elementRect(surface), boundary, config)
  surface.style.maxHeight = `${result.maxHeight}px`
  surface.style.maxWidth = `${result.maxWidth}px`

  // Width constraints can wrap content. One second pure pass uses final rendered dimensions.
  result = placePopover(anchor, elementRect(surface), boundary, config)
  surface.style.maxHeight = `${result.maxHeight}px`
  surface.style.maxWidth = `${result.maxWidth}px`
  if (!open.value || surface !== surfaceEl.value) return
  surface.style.transform = `translate(${result.x + window.scrollX}px, ${result.y + window.scrollY}px)`
  surface.style.visibility = 'visible'
  resolvedPlacement.value = result.placement
}

function beginAutoUpdate() {
  stopAutoUpdate?.()
  const surface = surfaceEl.value
  const target = inlineActive.value ? parent?.rootTarget() : targetEl.value
  if (!surface || !target) return
  let queued = false
  const queueUpdate = () => {
    if (queued) return
    queued = true
    queueMicrotask(() => {
      queued = false
      updatePosition()
    })
  }
  const resizeObserver = new ResizeObserver(queueUpdate)
  resizeObserver.observe(target)
  resizeObserver.observe(surface)

  const mutationObservers: MutationObserver[] = []
  let ancestor: HTMLElement | null = target
  while (ancestor && ancestor !== document.documentElement) {
    const observer = new MutationObserver(queueUpdate)
    observer.observe(ancestor, { attributes: true, childList: true })
    mutationObservers.push(observer)
    ancestor = ancestor.parentElement
  }

  const intersectionObserver = new IntersectionObserver(queueUpdate, { threshold: [0, 1] })
  intersectionObserver.observe(target)
  let layoutObserver: PerformanceObserver | null = null
  if (typeof PerformanceObserver !== 'undefined'
    && PerformanceObserver.supportedEntryTypes.includes('layout-shift')) {
    layoutObserver = new PerformanceObserver(queueUpdate)
    layoutObserver.observe({ type: 'layout-shift', buffered: false })
  }

  document.addEventListener('scroll', queueUpdate, true)
  window.addEventListener('resize', queueUpdate)
  stopAutoUpdate = () => {
    resizeObserver.disconnect()
    for (const observer of mutationObservers) observer.disconnect()
    intersectionObserver.disconnect()
    layoutObserver?.disconnect()
    document.removeEventListener('scroll', queueUpdate, true)
    window.removeEventListener('resize', queueUpdate)
  }
}

function childHandle(): ChildHandle {
  return {
    id,
    inline: inlineActive.value,
    close: () => closeMenu(false),
    contains: (target) => Boolean(surfaceEl.value?.contains(target) || rootEl.value?.contains(target)),
  }
}

function focusSurface() {
  surfaceEl.value?.focus()
}

/* The menu layer and the goal detail modal BOTH measure `z-index: 5000` in the reference
   (`tests/parity/test_p_21` pins the menu, `test_p_24` pins the modal), so the tie between them
   is broken by document order inside the shared root stacking context — later paints on top.
   `#dropdownPortal` lives inside `#app`, while `GoalDetail` teleports to `body`, which appends it
   AFTER `#app`. The modal therefore won every tie and a popover opened from an open goal (the
   schedule trigger is the reported case) rendered behind it with only its bottom edge showing.
   Re-asserting the portal as body's last child at open time fixes the order without touching
   either measured z-index. Owner report 2026-08-10. */
function raisePortal() {
  const portal = document.getElementById('dropdownPortal')
  if (portal && portal !== document.body.lastElementChild) document.body.appendChild(portal)
}

async function openMenu(focusRootSurface = !props.nested) {
  if (open.value) return
  if (!props.nested) {
    raisePortal()
    window.dispatchEvent(new CustomEvent('verticals:root-popover-open', { detail: id }))
    document.body.classList.add('popover-engine-open')
  } else {
    parent?.activateChild(childHandle())
  }
  open.value = true
  decorateTarget()
  emit('open')
  await nextTick()
  beginAutoUpdate()
  await updatePosition()
  if (focusRootSurface && open.value) focusSurface()
}

function closeMenu(restoreFocus = !props.nested) {
  if (!open.value) return
  parentState.activeChild?.close()
  parentState.activeChild = null
  open.value = false
  stopAutoUpdate?.()
  stopAutoUpdate = null
  stopSafePolygon()
  if (props.nested) parent?.clearChild(id)
  else document.body.classList.remove('popover-engine-open')
  decorateTarget()
  emit('close')
  // The board holds still while a menu is open; cards the pointer reached meanwhile react now (`lib/cardLift.ts`).
  if (!props.nested) window.dispatchEvent(new CustomEvent('verticals:root-popover-close', { detail: id }))
  if (restoreFocus) void nextTick(() => targetEl.value?.focus())
}

function toggle() {
  if (open.value) closeMenu()
  else void openMenu()
}

function choose(item: MenuItem) {
  emit('select', item)
  closeMenu(true)
}

function onSurfaceClick(event: MouseEvent) {
  const item = (event.target as Element).closest<HTMLElement>('[role="menuitem"]')
  if (!item || item.classList.contains('popover-engine__back')) return
  // A nested target belongs to the child lifecycle; its parent surface stays open on desktop.
  if (item.closest('.popover-engine')) return
  closeMenu(true)
}

function onRootMousedown(event: MouseEvent) {
  if (!targetEl.value?.contains(event.target as Node)) return
  if (!props.nested) event.preventDefault()
  if (open.value) closeMenu()
  else void openMenu(!props.nested)
}

function onRootClick(event: MouseEvent) {
  // Keyboard-generated activation has no preceding mousedown.
  if (event.detail !== 0 || !targetEl.value?.contains(event.target as Node)) return
  toggle()
}

function onWindowRootOpen(event: Event) {
  if (!open.value || props.nested) return
  if ((event as CustomEvent<symbol>).detail !== id) closeMenu(false)
}

function moveFocus(event: KeyboardEvent) {
  const surface = surfaceEl.value
  if (!surface?.contains(event.target as Node)) return
  const items = Array.from(surface.querySelectorAll<HTMLElement>('.dropdown__item:not([disabled])'))
  if (!items.length) return
  event.preventDefault()
  event.stopPropagation()
  const current = items.indexOf(document.activeElement as HTMLElement)
  let next = 0
  if (event.key === 'Home') next = 0
  else if (event.key === 'End') next = items.length - 1
  else if (event.key === 'ArrowDown') next = current < 0 ? 0 : (current + 1) % items.length
  else next = current <= 0 ? items.length - 1 : current - 1
  items[next]?.focus()
}

function onWindowKeydown(event: KeyboardEvent) {
  if (!open.value) return
  if (event.key === 'Escape') {
    if (parentState.activeChild && !parentState.activeChild.inline) return
    if (props.nested && inlineActive.value) return
    event.preventDefault()
    event.stopImmediatePropagation()
    stopNextEscapeKeyup = true
    closeMenu(!props.nested)
    return
  }
  if (['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(event.key)) moveFocus(event)
}

function onWindowKeyup(event: KeyboardEvent) {
  if (event.key !== 'Escape' || !stopNextEscapeKeyup) return
  stopNextEscapeKeyup = false
  event.preventDefault()
  event.stopImmediatePropagation()
}

function onWindowPointerdown(event: PointerEvent) {
  if (!open.value) return
  const target = event.target as Node
  if (rootEl.value?.contains(target) || surfaceEl.value?.contains(target)) return
  if (parentState.activeChild?.contains(target)) return
  closeMenu(false)
}

function onViewportResize() {
  viewportWidth.value = window.innerWidth
}

function cancelHoverTimer() {
  if (hoverTimer !== null) window.clearTimeout(hoverTimer)
  hoverTimer = null
}

function onTriggerEnter() {
  if (!props.nested || inlineActive.value) return
  cancelHoverTimer()
  hoverTimer = window.setTimeout(() => void openMenu(false), 75)
}

function pointInPolygon(x: number, y: number, points: Array<[number, number]>): boolean {
  let inside = false
  for (let index = 0, previous = points.length - 1; index < points.length; previous = index++) {
    const [xi, yi] = points[index]!
    const [xj, yj] = points[previous]!
    const crosses = yi > y !== yj > y && x < ((xj - xi) * (y - yi)) / (yj - yi) + xi
    if (crosses) inside = !inside
  }
  return inside
}

function pointInSafePolygon(x: number, y: number): boolean {
  const trigger = targetEl.value?.getBoundingClientRect()
  const surface = surfaceEl.value?.getBoundingClientRect()
  if (!trigger || !surface) return false
  if (
    (x >= trigger.left && x <= trigger.right && y >= trigger.top && y <= trigger.bottom)
    || (x >= surface.left && x <= surface.right && y >= surface.top && y <= surface.bottom)
  ) return true

  const buffer = 8
  const placement = resolvedPlacement.value.split('-')[0]
  let polygon: Array<[number, number]>
  if (placement === 'left') {
    polygon = [
      [safeOrigin.x + 3, safeOrigin.y - 3], [safeOrigin.x + 3, safeOrigin.y + 3],
      [surface.right + 2, surface.bottom + buffer], [surface.right + 2, surface.top - buffer],
    ]
  } else if (placement === 'top') {
    polygon = [
      [safeOrigin.x - 3, safeOrigin.y + 3], [safeOrigin.x + 3, safeOrigin.y + 3],
      [surface.right + buffer, surface.bottom + 2], [surface.left - buffer, surface.bottom + 2],
    ]
  } else if (placement === 'bottom') {
    polygon = [
      [safeOrigin.x - 3, safeOrigin.y - 3], [safeOrigin.x + 3, safeOrigin.y - 3],
      [surface.right + buffer, surface.top - 2], [surface.left - buffer, surface.top - 2],
    ]
  } else {
    polygon = [
      [safeOrigin.x - 3, safeOrigin.y - 3], [safeOrigin.x - 3, safeOrigin.y + 3],
      [surface.left - 2, surface.bottom + buffer], [surface.left - 2, surface.top - buffer],
    ]
  }
  return pointInPolygon(x, y, polygon)
}

function stopSafePolygon() {
  if (safeMoveListener) document.removeEventListener('pointermove', safeMoveListener, true)
  safeMoveListener = null
  document.body.classList.remove('popover-safe-pointer-block')
}

function onTriggerLeave(event: MouseEvent) {
  cancelHoverTimer()
  if (!props.nested || inlineActive.value || !open.value) return
  safeOrigin = { x: event.clientX, y: event.clientY }
  document.body.classList.add('popover-safe-pointer-block')
  safeMoveListener = (event) => {
    if (pointInSafePolygon(event.clientX, event.clientY)) return
    stopSafePolygon()
    closeMenu(false)
  }
  document.addEventListener('pointermove', safeMoveListener, true)
}

function onSurfaceEnter() {
  stopSafePolygon()
}

function onSurfaceLeave(event: MouseEvent) {
  if (!props.nested || inlineActive.value) return
  const next = event.relatedTarget as Node | null
  if (next && targetEl.value?.contains(next)) return
  closeMenu(false)
}

function backToParent() {
  closeMenu(false)
  void nextTick(() => targetEl.value?.focus())
}

watch(open, () => void nextTick(decorateTarget))

onMounted(() => {
  decorateTarget()
  window.addEventListener('verticals:root-popover-open', onWindowRootOpen)
  window.addEventListener('keydown', onWindowKeydown, true)
  window.addEventListener('keyup', onWindowKeyup, true)
  window.addEventListener('pointerdown', onWindowPointerdown, true)
  window.addEventListener('resize', onViewportResize)
})

onBeforeUnmount(() => {
  closeMenu(false)
  cancelHoverTimer()
  stopSafePolygon()
  window.removeEventListener('verticals:root-popover-open', onWindowRootOpen)
  window.removeEventListener('keydown', onWindowKeydown, true)
  window.removeEventListener('keyup', onWindowKeyup, true)
  window.removeEventListener('pointerdown', onWindowPointerdown, true)
  window.removeEventListener('resize', onViewportResize)
})
</script>

<template>
  <div
    ref="rootEl"
    class="dropdown popover-engine"
    data-dropdown
    @mousedown="onRootMousedown"
    @click="onRootClick"
    @mouseenter="onTriggerEnter"
    @mouseleave="onTriggerLeave"
  >
    <slot name="trigger" :open="open" :toggle="toggle">
      <button type="button" class="button t-subtitle">{{ label }}</button>
    </slot>

    <Teleport v-if="open" to="#dropdownPortal">
      <div
        ref="surfaceEl"
        class="Menu-floating ContextMenu dropdown__popover popover-engine__surface"
        :class="[surfaceClass, { 'popover-engine__surface--inline': inlineActive }]"
        v-bind="surfaceAttrs"
        role="menu"
        tabindex="-1"
        data-state="open"
        data-popover-surface
        :data-placement="resolvedPlacement"
        :data-dark-body="darkBody ? 'true' : undefined"
        :data-inline-parent-hidden="parentState.activeChild?.inline ? 'true' : undefined"
        @click="onSurfaceClick"
        @mouseenter="onSurfaceEnter"
        @mouseleave="onSurfaceLeave"
      >
        <button
          v-if="inlineActive"
          type="button"
          class="dropdown__item popover-engine__back"
          role="menuitem"
          @click="backToParent"
        >
          Back
        </button>
        <slot>
          <button
            v-for="(item, index) in items"
            :key="index"
            type="button"
            class="dropdown__item"
            role="menuitem"
            @click="choose(item)"
          >
            {{ typeof item === 'string' ? item : item.label }}
          </button>
        </slot>
      </div>
    </Teleport>
  </div>
</template>

<style>
.Menu-floating.popover-engine__surface.dropdown__popover {
  position: absolute;
  top: 0;
  left: 0;
  min-width: 200px;
  box-sizing: border-box;
  display: flex;
  flex-direction: column;
  padding: 8px 0;
  overflow: auto;
  z-index: 5000;
  visibility: hidden;
  /* Light, like the board it opens over (KK, 27 Sep 2026, the cleaned-up card's menu: "light, one text edge, nothing
     the card already shows"). It was black with light ink, a copy of the reference's look. */
  background: #fff;
  border: 0;
  border-radius: 10px;
  box-shadow: 0 0 0 1px rgb(0 0 0 / 8%), 0 10px 28px rgb(0 0 0 / 12%);
  color: #000;
  outline: none;
  user-select: none;
  -webkit-user-select: none;
  -webkit-touch-callout: none;
  animation: popover-engine-enter 120ms ease-out forwards;
}

.Menu-floating.popover-engine__surface.dropdown__popover[data-dark-body='true'] {
  border-radius: 10px;
}

.Menu-floating.popover-engine__surface .dropdown__item {
  color: inherit;
  cursor: pointer;
  outline: none;
  user-select: none;
  -webkit-user-select: none;
  -webkit-touch-callout: none;
}

/* Form controls do NOT inherit `color` from an ancestor — the UA sheet gives every `input` and
   `textarea` its own black text — so a field dropped into the surface when it was dark rendered
   black-on-#1b1b1b and read as an empty box. That is exactly what the tags panel looked like
   (owner, 2026-08-10: "кнопка тега кривая и у неё нихуя внутри нету"): the input, its value and
   its placeholder were all there, all invisible. Fixed once here rather than per consumer —
   every popover that ever holds a field inherits the surface's own colour from now on. */
.Menu-floating.popover-engine__surface input,
.Menu-floating.popover-engine__surface textarea {
  color: inherit;
  background: transparent;
  caret-color: currentColor;
}
.Menu-floating.popover-engine__surface input::placeholder,
.Menu-floating.popover-engine__surface textarea::placeholder {
  color: rgb(0 0 0 / 40%);
}

/* Same trap one component up: the kit's `.chip` pins its ink, hairline and hover wash to page
   tokens (`--color-text` #000, `--color-border-strong` and `--color-surface-overlay` both black
   at low alpha) tuned for the white page. On this surface the tags panel's chip rendered black
   on #1b1b1b: the tag and its remove icon were there, unreadable (owner, 2026-09-15). The chip
   takes the surface's ink instead; the hairline keeps the kit's 20% of ink, the hover reuses
   `.dropdown__item`'s wash. */
.Menu-floating.popover-engine__surface .chip {
  color: inherit;
  border-color: rgb(0 0 0 / 16%);
}
.Menu-floating.popover-engine__surface .chip:hover {
  background: rgb(0 0 0 / 5%);
}
.Menu-floating.popover-engine__surface .chip:focus-visible {
  outline-color: currentColor;
}

.Menu-floating.popover-engine__surface .dropdown__item:not(:disabled):hover,
.Menu-floating.popover-engine__surface .dropdown__item:not(:disabled):focus,
.Menu-floating.popover-engine__surface .dropdown__item:not(:disabled):focus-visible {
  background: rgb(0 0 0 / 5%);
}

/* A refused action must LOOK refused. The hover rule above had no `:disabled` guard and nothing
   else styled the state, so the Repeat item on a goal with subgoals — which the app correctly
   refuses — highlighted exactly like a live one and its only signal was a native `title` tooltip:
   one cue per state, and this state had none (D91, found live 2026-08-11). 25% of the surface's
   own ink, the treatment `.period-nav__today:disabled` already set as this app's convention;
   `currentColor` carries it to the item's icon too. */
.Menu-floating.popover-engine__surface .dropdown__item:disabled {
  color: rgb(0 0 0 / 35%);
  background: transparent;
  cursor: default;
}

.Menu-target {
  cursor: pointer;
}

.popover-engine__surface[data-inline-parent-hidden='true'] {
  visibility: hidden !important;
}

.popover-engine__back {
  flex: 0 0 auto;
}

body.popover-engine-open .WithTooltip-popover,
body.popover-engine-open .tooltip__bubble,
body.popover-engine-open [role='tooltip'] {
  display: none !important;
}

body.popover-safe-pointer-block .app-shell {
  pointer-events: none;
}

body.popover-safe-pointer-block .Menu-floating {
  pointer-events: auto;
}

@keyframes popover-engine-enter {
  from { opacity: 0; }
  to { opacity: 1; }
}

@media (prefers-reduced-motion: reduce) {
  .Menu-floating.popover-engine__surface.dropdown__popover {
    animation: none;
  }
}
</style>
