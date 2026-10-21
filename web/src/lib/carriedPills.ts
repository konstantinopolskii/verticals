// Three pills beside a carried plan (docs/design/carried-pills.md, the owner, 21 Oct 2026): pointing at a plan in a carried
// box shows "This week" (the box's column's own period: "This month", "This quarter"...), "To Inbox" and "Delete" to the
// right of the box, level with the plan's first line, on the box's own lit colour. Each is the card menu's own action
// (`GoalCardTools.tsx`), so the board's history and ⌘Z, the sound and the field's Undo are the menu's. The markup is
// `components/CarriedPills.tsx`; this keeps the rules.
//
//   · The pills are drawn in <body>: the column's scroller clips what is inside it at its sides, and they float over the
//     next column (or the one before, where the window has no room). Out of the box's DOM, moving onto them is leaving
//     the box and the card, so the box keeps them as its own (CarriedGroup's pointerleave, `carriedFilter.ts`'s column),
//     the plan's family stays lit, and its row keeps its light (`data-pills`, carriedGroup.css). The pills reach back to
//     the card, so the pointer crosses no gap to them.
//   · They stand where their card is, through the box's lift and a scroll, and glide to the next plan the pointer takes.
//   · A click: the card leaves as it does from the menu. Once the column is still, the plan on the pills' line (or under
//     the pointer, when it is over the box) has them, without the pointer moving: a list is sorted click, click, click.
//     Until then the pills wait, and a second click does nothing.
//   · Pointer only; not while a goal is held or a menu is open, and not on the box's open plan.

import { computed, onBeforeUnmount, ref, watch, type Ref } from '../reactivity'
import { store, todayIso } from '../store'
import { anyMenuOpen, menuGoalId } from './cardLift'
import { goalLight } from './look'
import { reducedMotion, timing } from './motion'
import type { VerticalScale } from './periods'
import { isoDate, localDate, periodKeyFor } from './schedule'
import { playSound } from './sound'
import type { GoalCardData } from '../types'

/** What keeping a plan in its column says: the column's own period. */
const KEEP: Record<string, string> = {
  day: 'Today', week: 'This week', month: 'This month', quarter: 'This quarter', year: 'This year', decade: 'These three years',
}
const GAP = 8 // px between the box and the pills, and kept from the window's edge
const FOLLOW_MS = 400 // after anything that may move the card, the pills look where it is for this long
const SETTLE_MS = 600 // the longest a click waits for its column to stop moving

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
  const keepLabel = computed(() => KEEP[o.vertical()] ?? 'Keep')

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

  /* Where the pills stand: right of the box, centred on the card's first line; left of it, over the column before, when the
     window has no room on the right (the box of the last column but Life: three pills are wider than a box, so over the
     card they would hide the plan they sort). The root reaches back to the card's edge with no paint, so the way there
     has no gap. */
  let glide: Animation | null = null
  let last = ''
  function set(): HTMLElement | null {
    return (el.value?.firstElementChild as HTMLElement | null) ?? null
  }
  function place(): void {
    const root = el.value
    const pills = set()
    const box = o.box.value
    const card = box && target.value ? cardOf(box, target.value) : null
    if (!root || !pills || !box || !card) return
    const title = card.querySelector<HTMLElement>(':scope > .goal-card__row .goal-card__title')
    const b = box.getBoundingClientRect()
    const c = card.getBoundingClientRect()
    let line = c.top + c.height / 2
    if (title) {
      const t = title.getBoundingClientRect()
      const k = title.offsetHeight ? t.height / title.offsetHeight : 1 // the box's lift scales what is in it
      line = t.top + (parseFloat(getComputedStyle(title).lineHeight) || title.offsetHeight) * k / 2
    }
    const w = pills.offsetWidth
    const right = b.right + GAP + w <= window.innerWidth - GAP
    const left = Math.round(right ? b.right + GAP : Math.max(GAP, b.left - GAP - w))
    const from = right ? Math.min(left, Math.round(c.right)) : left
    const back = right ? left - from : Math.max(0, Math.round(c.left) - left - w) // the unpainted way to the card
    const top = Math.round(line - pills.offsetHeight / 2)
    const now = `${from} ${back} ${right} ${top}`
    if (now === last) return
    last = now
    root.style.transform = `translate(${from}px, ${top}px)`
    root.style.paddingLeft = right ? `${back}px` : '0px'
    root.style.paddingRight = right ? '0px' : `${back}px`
    root.dataset.side = right ? 'right' : 'left' // on the left the order turns: the mild one stays nearest the card
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

  /** After a click, once the column is still: the plan on the pills' line when the pointer is on them, or under the
   *  pointer when it is over the box, takes them, and the wait ends. */
  function resolve(): void {
    const box = o.box.value
    const root = el.value
    const pills = set()
    if (!box || gone) return
    const b = box.getBoundingClientRect()
    const s = pills && shown.value ? pills.getBoundingClientRect() : null
    const onPills = !!root && !!s && within(root.getBoundingClientRect(), at)
    const point = onPills && s ? { x: b.left + b.width / 2, y: s.top + s.height / 2 } : at
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
    const column = o.box.value?.closest('.pattern-vertical-board__column') ?? null
    const start = performance.now()
    const check = (): void => {
      if (gone) return
      const moving = column?.getAnimations({ subtree: true }).some(ends) ?? false
      if (moving && performance.now() - start < SETTLE_MS) { requestAnimationFrame(check); return }
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
  function inbox(): void {
    act((id) => void store.moveGoalToInbox(id))
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
    window.removeEventListener('scroll', onScroll, { capture: true })
    window.removeEventListener('resize', onScroll)
  })

  return {
    el, target, shown, waiting, tone, keepLabel, column: o.vertical, keep, inbox, remove, over, owns, away, follow,
    onEnter, onMouseEnter, onLeave,
  }
}
