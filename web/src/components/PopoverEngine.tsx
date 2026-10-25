/* The app's popover and menu engine: the surface in #dropdownPortal, its placement,
   the safe pointer path to a nested panel, the keys. Slots: `#trigger="{ open, toggle }"` → `trigger` (a node, or a
   function of PopoverTriggerSlot); the default slot → `children`, the `items` buttons when it draws nothing. Emits
   `select`/`open`/`close` → `onSelect`/`onOpen`/`onClose`. provide/inject('popover-parent') → a React context. */
import {
  createContext, Fragment, isValidElement, useContext, useMemo, type MouseEvent as ReactMouseEvent, type ReactNode,
  type Ref as ReactRef, type SyntheticEvent,
} from 'react'
import { createPortal } from 'react-dom'
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch, type Ref } from '../reactivity'
import { placePopover, type PopoverPlacement as Placement, type PopoverRect } from '../lib/popover'
import { bindRef, cx, fallthrough } from '../bind'
import { tracked } from '../tracked'
import { useSetup, withDefaults } from '../setup'
import './popoverEngine.css'

export type MenuItem = string | { label: string; value: unknown }
type InlineMode = boolean | 'auto'
type SurfaceAttrs = Record<string, string | number | boolean | undefined>
export interface PopoverTriggerSlot {
  open: boolean
  toggle: () => void
}
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

const PopoverParent = createContext<ParentContext | null>(null)

export interface PopoverEngineProps {
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
  onSelect?: (item: MenuItem) => void
  onOpen?: () => void
  onClose?: () => void
  trigger?: ReactNode | ((slot: PopoverTriggerSlot) => ReactNode)
  children?: ReactNode
  ref?: ReactRef<HTMLDivElement>
  className?: string
}
const DEFAULTS = { label: 'Options', items: [] as MenuItem[], nested: false, inline: 'auto' as InlineMode, mobile: false, darkBody: false }

/* A teleported surface is not inside the components around the engine in the DOM, so its events never reach them; React
   bubbles them along the component tree instead. They stop at the surface for React handlers only: the browser's own
   bubbling to document and window goes on, as it does from the teleported node. */
function stayInSurface(event: SyntheticEvent): void {
  event.isPropagationStopped = () => true
}
const SURFACE_EVENTS = Object.fromEntries([
  'onAuxClick', 'onClick', 'onDoubleClick', 'onContextMenu', 'onMouseDown', 'onMouseUp', 'onMouseMove', 'onMouseOver',
  'onMouseOut', 'onPointerDown', 'onPointerUp', 'onPointerMove', 'onPointerCancel', 'onPointerOver', 'onPointerOut',
  'onKeyDown', 'onKeyUp', 'onKeyPress', 'onBeforeInput', 'onInput', 'onChange', 'onFocus', 'onBlur', 'onSubmit',
  'onWheel', 'onTouchStart', 'onTouchMove', 'onTouchEnd', 'onTouchCancel', 'onDragStart', 'onDrag', 'onDragEnd',
  'onDragEnter', 'onDragOver', 'onDragLeave', 'onDrop', 'onCopy', 'onCut', 'onPaste', 'onCompositionStart',
  'onCompositionUpdate', 'onCompositionEnd',
].map((name) => [name, stayInSurface]))

/** A slot that draws nothing (only false/null, empty fragments) gives way to the fallback content. */
export function drawsSomething(node: ReactNode): boolean {
  if (node == null || typeof node === 'boolean') return false
  if (Array.isArray(node)) return node.some(drawsSomething)
  if (isValidElement(node) && node.type === Fragment) return drawsSomething((node.props as { children?: ReactNode }).children)
  return true
}

export const PopoverEngine = tracked(function PopoverEngine(raw: PopoverEngineProps & Record<string, unknown>) {
  const {
    label, items, placement, fixedWidth, offset, nested, inline, mobile, darkBody, surfaceClass, surfaceAttrs, onSelect,
    onOpen, onClose, trigger, children, ref: outerRef, ...attrs
  } = withDefaults(raw, DEFAULTS)
  const parent = useContext(PopoverParent)
  const s = useSetup({
    label, items, placement, fixedWidth, offset, nested, inline, mobile, darkBody, surfaceClass, surfaceAttrs, onSelect,
    onOpen, onClose,
  }, (props) => {
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

    /* The menu layer and the goal detail modal both stand at `z-index: 5000`, so document order breaks the tie, and
       GoalDetail teleports to body, after `#app` where the portal lives: a popover opened from an open goal drew behind
       it. The portal goes back to body's last child at each open. */
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
      props.onOpen?.()
      await nextTick()
      beginAutoUpdate()
      await updatePosition()
      if (focusRootSurface && open.value) focusSurface()
    }

    function closeMenu(restoreFocus = !props.nested) {
      if (!open.value) return
      const hadKeys = !!surfaceEl.value?.contains(document.activeElement)
      parentState.activeChild?.close()
      parentState.activeChild = null
      open.value = false
      stopAutoUpdate?.()
      stopAutoUpdate = null
      stopSafePolygon()
      if (props.nested) parent?.clearChild(id)
      else document.body.classList.remove('popover-engine-open')
      decorateTarget()
      props.onClose?.()
      // The board holds still while a menu is open; cards the pointer reached meanwhile react now (`lib/cardLift.ts`).
      if (!props.nested) window.dispatchEvent(new CustomEvent('verticals:root-popover-close', { detail: id }))
      // A submenu that had the keys gives them back to its item in the menu above.
      if (restoreFocus || (props.nested && hadKeys)) void nextTick(() => targetEl.value?.focus())
    }

    function toggle() {
      if (open.value) closeMenu()
      else void openMenu()
    }

    function choose(item: MenuItem) {
      props.onSelect?.(item)
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
      // Keyboard-generated activation has no preceding mousedown. It opens a submenu with the keys in it.
      if (event.detail !== 0 || !targetEl.value?.contains(event.target as Node)) return
      if (open.value) closeMenu()
      else void openMenu(true)
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
      else pressItemKey(event)
    }

    /** A letter picks the item that names it (`data-key`), as a click does, and ⌫ the item named "delete"; a field in the
     *  menu keeps its keys. A layout without Latin letters takes the key in the same place. Only the menu that has the
     *  focus answers: a submenu's letters are its own. */
    function pressItemKey(event: KeyboardEvent) {
      const surface = surfaceEl.value
      const target = event.target as HTMLElement | null
      if (!surface || target?.closest('.popover-engine__surface') !== surface || event.metaKey || event.ctrlKey
        || event.altKey || event.isComposing || target.closest('input, textarea, [contenteditable="true"]')) return
      const key = event.key === 'Backspace' || event.key === 'Delete' ? 'delete'
        : /^[a-z]$/i.test(event.key) ? event.key.toLowerCase() : /^Key[A-Z]$/.test(event.code) ? event.code.slice(3).toLowerCase() : null
      const item = key ? surface.querySelector<HTMLElement>(`[data-key="${key}"]:not([disabled])`) : null
      if (!item || item.closest('.popover-engine__surface') !== surface) return
      event.preventDefault()
      event.stopImmediatePropagation()
      if (event.repeat) return
      item.click()
      // An item that turns the menu into a step takes the focused item away: the menu keeps the keys.
      void nextTick(() => { if (open.value && !surface.contains(document.activeElement)) surface.focus() })
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

    /* mouseenter/mouseleave on the elements themselves: React's follow the component tree, where the surface is inside
       the root, and would not fire as the pointer crosses from the trigger to the surface. */
    function hover(el: Ref<HTMLElement | null>, enter: () => void, leave: (event: MouseEvent) => void) {
      watch(el, (node, old) => {
        old?.removeEventListener('mouseenter', enter)
        old?.removeEventListener('mouseleave', leave)
        node?.addEventListener('mouseenter', enter)
        node?.addEventListener('mouseleave', leave)
      }, { flush: 'sync' })
    }
    hover(rootEl, onTriggerEnter, onTriggerLeave)
    hover(surfaceEl, onSurfaceEnter, onSurfaceLeave)

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

    return {
      rootEl, surfaceEl, open, resolvedPlacement, parentState, inlineActive, context, toggle, choose, onSurfaceClick,
      onRootMousedown, onRootClick, backToParent,
    }
  })

  const rootRef = useMemo(() => {
    const own = bindRef(s.rootEl)
    return (node: HTMLDivElement | null) => {
      own(node)
      if (typeof outerRef === 'function') outerRef(node)
      else if (outerRef) outerRef.current = node
    }
  }, [outerRef])

  const open = s.open.value
  const slot = typeof trigger === 'function' ? trigger({ open, toggle: s.toggle }) : trigger
  const portal = open ? document.getElementById('dropdownPortal') : null
  const surface = (
    <div
      {...SURFACE_EVENTS}
      {...surfaceAttrs}
      ref={bindRef(s.surfaceEl)}
      className={cx('Menu-floating ContextMenu dropdown__popover popover-engine__surface',
        [surfaceClass, { 'popover-engine__surface--inline': s.inlineActive.value }])}
      role="menu"
      tabIndex={-1}
      data-state="open"
      data-popover-surface=""
      data-placement={s.resolvedPlacement.value}
      data-dark-body={darkBody ? 'true' : undefined}
      data-inline-parent-hidden={s.parentState.activeChild?.inline ? 'true' : undefined}
      onClick={(event: ReactMouseEvent) => {
        s.onSurfaceClick(event.nativeEvent)
        stayInSurface(event)
      }}
    >
      {s.inlineActive.value ? (
        <button type="button" className="dropdown__item popover-engine__back" role="menuitem" onClick={() => s.backToParent()}>
          Back
        </button>
      ) : null}
      {drawsSomething(children) ? children : items.map((item, index) => (
        <button key={index} type="button" className="dropdown__item" role="menuitem" onClick={() => s.choose(item)}>
          {typeof item === 'string' ? item : item.label}
        </button>
      ))}
    </div>
  )

  return (
    <PopoverParent.Provider value={s.context}>
      <div
        {...fallthrough({
          className: 'dropdown popover-engine',
          'data-dropdown': '',
          onMouseDown: (event: ReactMouseEvent) => s.onRootMousedown(event.nativeEvent),
          onClick: (event: ReactMouseEvent) => s.onRootClick(event.nativeEvent),
        }, attrs)}
        ref={rootRef}
      >
        {drawsSomething(slot) ? slot : <button type="button" className="button t-subtitle">{label}</button>}
        {portal ? createPortal(surface, portal) : null}
      </div>
    </PopoverParent.Provider>
  )
})
