// Three words over a carried plan (docs/design/carried-pills.md; the owner's sketch, 21 Oct 2026): pointing at a plan in a
// carried box shows one capsule just above the plan's lit block, "Keep · Idk · Fuck it", in the plan's own light and its
// title's own type, so the card and the capsule read as one object. Keep puts the plan in the column's current period, Idk
// adds a line to its notes and sends it to the Inbox, Fuck it deletes it. 1, 2 and 3 do the same while a plan is pointed
// at. Each goes through the store as the card's menu does, so the board's history and ⌘Z, the sound and the field's Undo
// are the menu's. The markup is `components/CarriedPills.tsx`; this keeps the rules.
//
//   · The capsule is drawn in <body>: the column's scroller clips what is inside it, and the capsule may stand over the box's
//     line or the plan above. Out of the box's DOM, moving onto it is leaving the box and the card, so the box keeps it as its
//     own (CarriedGroup's pointerleave, `carriedFilter.ts`'s column), the plan's family stays lit, and its row keeps its
//     light (`data-pills`, carriedGroup.css). The capsule reaches down to the block, so the pointer crosses no gap to it.
//   · It stands where the block is, through the box's lift and a scroll, and glides to the next plan the pointer takes.
//   · A click or a key: the card leaves as it does from the menu. Once the column is still, the plan on the capsule's line
//     (or under the pointer, when it is over the box) has it, without the pointer moving: a list is sorted 1, 1, 3, 2...
//     Until then the capsule waits, and another click or key does nothing.
//   · Pointer only; not while a goal is held or a menu is open, and not on the box's open plan.

import { computed, onBeforeUnmount, ref, watch, type Ref } from '../reactivity'
import { store, todayIso } from '../store'
import { editsText } from './boardHistory'
import { anyMenuOpen, menuGoalId } from './cardLift'
import { goalLight } from './look'
import { reducedMotion, timing } from './motion'
import type { VerticalScale } from './periods'
import { isoDate, localDate, periodKeyFor } from './schedule'
import { realignLine } from './realign'
import { playSound } from './sound'
import type { GoalCardData } from '../types'

const AIR = 4 // px between the capsule and the plan's lit block
const FOLLOW_MS = 400 // after anything that may move the card, the pills look where it is for this long
const GO_MS = 2000 // the longest a click waits for its plan to leave the box (Idk reads and writes the notes first)
const SETTLE_MS = 600 // and then for its column to stop moving

const PLANS = ':scope > [data-section="carried"] > .goal-card[data-goal-id]'

/* Where the pointer is, and whether it is a finger. */
let at = { x: Number.NaN, y: Number.NaN }
let finger = false
const fine = typeof window !== 'undefined' && window.matchMedia ? window.matchMedia('(hover: hover) and (pointer: fine)') : null
if (typeof window !== 'undefined') {
  window.addEventListener('pointermove', (event) => {
    at = { x: event.clientX, y: event.clientY }
    finger = event.pointerType === 'touch'
  }, { capture: true, passive: true })
}

function cardOf(box: HTMLElement, id: string): HTMLElement | null {
  return [...box.querySelectorAll<HTMLElement>(PLANS)].find((card) => card.dataset.goalId === id) ?? null
}
const within = (r: DOMRect, p: { x: number; y: number }): boolean => p.x >= r.left && p.x <= r.right && p.y >= r.top && p.y <= r.bottom
/** An animation that ends: the mascot's breath never does, and is no reason to wait. */
const ends = (a: Animation): boolean => a.playState === 'running' && Number.isFinite(Number(a.effect?.getComputedTiming().endTime))

/** The window's top that the board can use: under the desktop app's title bar. */
function topOfBoard(): number {
  return parseFloat(getComputedStyle(document.documentElement).getPropertyValue('--titlebar-height')) || 0
}

/* 1, 2 and 3 while a plan is pointed at (no hint on screen: the words are the hint). Heard as this module loads, before the
   field's own listener (SearchBar.tsx, once mounted), which would take any printable key as its first letter; a key it
   uses here goes no further. Inside a text field the keys stay the field's. */
interface Keys { keep(): void; idk(): void; remove(): void }
let pointed: Keys | null = null
const KEYS: Record<string, keyof Keys> = { 1: 'keep', 2: 'idk', 3: 'remove', Digit1: 'keep', Digit2: 'idk', Digit3: 'remove' }
if (typeof window !== 'undefined') {
  window.addEventListener('keydown', (event) => {
    const keys = pointed
    if (!keys || event.defaultPrevented || event.isComposing || event.metaKey || event.ctrlKey || event.altKey) return
    const name = KEYS[event.key] ?? (event.shiftKey ? undefined : KEYS[event.code])
    if (!name || editsText(event.target)) return
    event.preventDefault()
    event.stopImmediatePropagation()
    if (!event.repeat) keys[name]()
  }, true)
}

export type CarriedPillsApi = ReturnType<typeof useCarriedPills>

export function useCarriedPills(o: {
  vertical: () => string
  /** The period the box's column shows: carried plans are drawn only in the current one. */
  periodKey: () => string | null
  plans: () => GoalCardData[]
  box: Ref<HTMLElement | null>
  /** A plan of the box is open. */
  open: () => boolean
  /** The box's own pointer in and out (`carriedFilter.ts`). */
  enter: () => void
  leave: () => void
}) {
  const el = ref<HTMLElement | null>(null)
  const target = ref<string | null>(null) // the plan the pills act on
  const waiting = ref(false) // a click is being carried out
  const tone = ref<Record<string, string> | null>(null) // the plan's light, kept while the pills fade
  let gone = false

  const plan = computed(() => o.plans().find((g) => g.id === target.value) ?? null)
  const blocked = computed(() => o.open() || store.state.drag.id !== null || store.state.drag.pending !== null || menuGoalId.value !== null)
  const shown = computed(() => !blocked.value && (waiting.value || plan.value !== null))

  /* The plan's row keeps its light while the pointer is on its pills. */
  let marked: HTMLElement | null = null
  function mark(): void {
    const box = o.box.value
    const card = shown.value && !waiting.value && target.value && box ? cardOf(box, target.value) : null
    if (card === marked) return
    marked?.removeAttribute('data-pills')
    card?.setAttribute('data-pills', '')
    marked = card
  }
  watch(shown, mark, { flush: 'post' })

  /* Where the capsule stands: just above the plan's lit block, its left edge on the block's, AIR between them; just below
     when the window has no room above. The root reaches to the block with no paint, so the way there has no gap. */
  let glide: Animation | null = null
  let last = ''
  let lastPaint = ''
  let line = Number.NaN // the middle of the lit block the capsule stood by, where the next plan rises after a click
  function set(): HTMLElement | null {
    return (el.value?.firstElementChild as HTMLElement | null) ?? null
  }
  /** The block's own colour and the title's own type: the box's ground under the plan's light at the plan's strength, as
   *  the card draws it (goalCard.css `.goal-card__row::before`), in either appearance and as the Layout panel tunes it. */
  function paint(root: HTMLElement, box: HTMLElement, card: HTMLElement, title: HTMLElement | null): void {
    const light = getComputedStyle(card)
    const type = title ? getComputedStyle(title) : null
    const values: Record<string, string> = {
      '--carried-pill-ground': getComputedStyle(box).backgroundColor,
      '--carried-pill-light': light.getPropertyValue('--goal-hover-background').trim(),
      '--carried-pill-strength': light.getPropertyValue('--goal-light-tint').trim() || '.7',
    }
    if (type) {
      Object.assign(values, {
        '--carried-pill-ink': type.color, '--carried-pill-family': type.fontFamily, '--carried-pill-size': type.fontSize,
        '--carried-pill-weight': type.fontWeight, '--carried-pill-line': type.lineHeight,
      })
    }
    const now = Object.values(values).join('|')
    if (now === lastPaint) return
    lastPaint = now
    for (const [name, value] of Object.entries(values)) root.style.setProperty(name, value)
  }
  function place(): void {
    const root = el.value
    const pills = set()
    const box = o.box.value
    const card = box && target.value ? cardOf(box, target.value) : null
    const row = card?.querySelector<HTMLElement>(':scope > .goal-card__row') ?? null
    if (!root || !pills || !box || !card || !row) return
    paint(root, box, card, row.querySelector<HTMLElement>('.goal-card__title'))
    const r = row.getBoundingClientRect()
    const k = row.offsetHeight ? r.height / row.offsetHeight : 1 // the box's lift scales what is in it
    const wash = getComputedStyle(row, '::before') // the lit block reaches past the row by its wash
    const left = Math.round(r.left + (parseFloat(wash.left) || 0) * k)
    const top = r.top + (parseFloat(wash.top) || 0) * k
    const bottom = r.bottom - (parseFloat(wash.bottom) || 0) * k
    const h = pills.offsetHeight
    line = (top + bottom) / 2
    const above = top - AIR - h >= topOfBoard()
    const y = Math.round(above ? top - AIR - h : bottom)
    const now = `${left} ${y} ${above}`
    if (now === last) return
    last = now
    root.style.transform = `translate(${left}px, ${y}px)`
    root.style.padding = above ? `0 0 ${AIR}px` : `${AIR}px 0 0`
  }

  let frame = 0
  let until = 0
  /** The card may move for a while (the box lifting, a scroll): the pills stand where it is, frame by frame. */
  function follow(): void {
    until = performance.now() + FOLLOW_MS
    if (frame) return
    const step = (): void => {
      frame = 0
      if (gone || !target.value || performance.now() > until) return
      place()
      frame = requestAnimationFrame(step)
    }
    frame = requestAnimationFrame(step)
  }

  /** The pills take another plan, or none. Moving from one plan to the next, they glide there from where they stand
   *  (`from`, read by the caller when it changes what is shown first). */
  function retarget(id: string | null, from?: DOMRect | null): void {
    if (waiting.value) return
    if (id && (!fine?.matches || finger || anyMenuOpen() || store.sameVerticalParentId(id))) id = null
    if (id === target.value) { mark(); return }
    const pills = set()
    if (from === undefined) from = shown.value && pills ? pills.getBoundingClientRect() : null
    target.value = id
    if (id) {
      tone.value = goalLight(plan.value?.color)
      glide?.cancel()
      glide = null
      place()
      follow()
      if (from && pills && !reducedMotion()) {
        const to = pills.getBoundingClientRect()
        const dx = from.left - to.left
        const dy = from.top - to.top
        if (Math.abs(dx) + Math.abs(dy) >= 1) {
          glide = pills.animate([{ transform: `translate(${dx}px, ${dy}px)` }, { transform: 'none' }], timing('fade', 'small'))
        }
      }
    }
    mark()
  }

  /** After a click, once the column is still: the plan that rose where the last one stood, when the pointer is on the
   *  capsule, or the plan under the pointer, when it is over the box, takes the capsule, and the wait ends. */
  function resolve(): void {
    const box = o.box.value
    const root = el.value
    const pills = set()
    if (!box || gone) return
    const b = box.getBoundingClientRect()
    const s = pills && shown.value ? pills.getBoundingClientRect() : null
    const onPills = !!root && !!s && within(root.getBoundingClientRect(), at)
    const point = onPills ? { x: b.left + b.width / 2, y: line } : at
    let id: string | null = null
    if (!blocked.value && Number.isFinite(point.x) && within(b, point)) {
      const hit = document.elementsFromPoint(point.x, point.y).find((node) => box.contains(node))
      const card = hit?.closest<HTMLElement>('.goal-card[data-goal-id]')
      if (card && card.parentElement?.dataset.section === 'carried') id = card.dataset.goalId ?? null
    }
    const before = target.value
    waiting.value = false
    retarget(id, s)
    if (id) store.setHoverChain(id) // the card's own enter may never come: the pointer didn't move
    else if (onPills) {
      if (before && store.state.hoverChainId === before) store.setHoverChain(null)
      o.leave()
    }
  }

  /** A pill was clicked: the plan goes, and the pills wait for the column to be still before they take the next one. */
  function act(run: (id: string) => void): void {
    const id = target.value
    if (!id || waiting.value || !shown.value) return
    waiting.value = true
    mark()
    if (store.state.hoverChainId === id) store.setHoverChain(null) // its family's light leaves with it
    run(id)
    const box = o.box.value
    const column = box?.closest('.pattern-vertical-board__column') ?? null
    const start = performance.now()
    let left = 0 // when the plan was seen gone; a write that failed leaves it, and the wait ends at GO_MS
    const check = (): void => {
      if (gone) return
      const now = performance.now()
      if (!left && box && cardOf(box, id) && now - start < GO_MS) { requestAnimationFrame(check); return }
      left ||= now
      const moving = column?.getAnimations({ subtree: true }).some(ends) ?? false
      if (moving && now - left < SETTLE_MS) { requestAnimationFrame(check); return }
      resolve()
    }
    requestAnimationFrame(() => requestAnimationFrame(check)) // the change is drawn, and its movement started, first
  }
  function keep(): void {
    act((id) => {
      const scale = o.vertical() as VerticalScale
      const today = localDate(todayIso())
      const key = o.periodKey() ?? periodKeyFor(scale, today)
      void store.scheduleGoalQuick(id, scale, key, periodKeyFor(scale, today) === key ? isoDate(today) : undefined)
    })
  }
  function idk(): void {
    const g = plan.value
    act((id) => void store.realignToInbox(id, realignLine(g?.vertical, g?.anchorDate, localDate(todayIso()))))
  }
  function remove(): void {
    act((id) => {
      playSound('goal_deleted')
      void store.removeGoal(id)
    })
  }

  /* The pointer over the box: a plan takes the pills; the box's line, "N more", the mascot or a plan's step lets them go;
     the box's own ground between them changes nothing. */
  function over(event: PointerEvent): void {
    const box = o.box.value
    const node = event.target instanceof Element ? event.target : null
    if (!box || !node || event.pointerType === 'touch') return
    const card = node.closest<HTMLElement>('.goal-card[data-goal-id]')
    if (card && box.contains(card)) retarget(card.parentElement?.dataset.section === 'carried' ? card.dataset.goalId ?? null : null)
    else if (node !== box && !node.matches('[data-section="carried"], .carried-ghosts, .carried-ghosts *')) retarget(null)
  }
  /** Whether a node is the pills' (the box's pointerleave asks: moving onto them is not leaving). */
  function owns(node: EventTarget | null): boolean {
    return node instanceof Node && !!el.value?.contains(node)
  }
  /** The pointer left the box for somewhere else than the pills. */
  function away(): void {
    retarget(null)
  }

  /* The pointer on the pills: they are the box's. Off them, unless back into the box, it has left the box. */
  function onEnter(): void {
    o.enter()
  }
  function onMouseEnter(): void {
    if (target.value) store.setHoverChain(target.value) // after the card's own leave, which let its family go
  }
  function onLeave(event: PointerEvent): void {
    const box = o.box.value
    if (box && event.relatedTarget instanceof Node && box.contains(event.relatedTarget)) return
    const id = target.value
    retarget(null)
    if (id && store.state.hoverChainId === id) store.setHoverChain(null)
    o.leave()
  }

  // A goal held, a menu or the plan opened: the pills let their plan go, and come back when the pointer next points.
  watch(blocked, (now) => { if (now) retarget(null) })
  // The keys are this box's while it shows its capsule (and while a click is carried out, so a key then does nothing).
  const keys: Keys = { keep, idk, remove }
  watch(shown, (now) => {
    if (now) pointed = keys
    else if (pointed === keys) pointed = null
  }, { flush: 'sync' })

  const onScroll = (): void => { if (target.value) follow() }
  if (typeof window !== 'undefined') {
    window.addEventListener('scroll', onScroll, { capture: true, passive: true })
    window.addEventListener('resize', onScroll, { passive: true })
  }
  onBeforeUnmount(() => {
    gone = true
    if (frame) cancelAnimationFrame(frame)
    glide?.cancel()
    marked?.removeAttribute('data-pills')
    if (pointed === keys) pointed = null
    window.removeEventListener('scroll', onScroll, { capture: true })
    window.removeEventListener('resize', onScroll)
  })

  return {
    el, target, shown, waiting, tone, column: o.vertical, keep, idk, remove, over, owns, away, follow,
    onEnter, onMouseEnter, onLeave,
  }
}
