// The carried box's filter (docs/design-handoff S4.P3, KK 2026-10-02): which goal's family the box shows, how long it
// keeps it, where its height goes and what the pointer inside it does. The component keeps the markup; this keeps the
// rules, in the shape of `inlineTitleEdit.ts` and `cardFamily.ts`.
//
//   · A box shows the plans of the goal the pointer rests on, DWELL_MS, and keeps them. A goal with plans in the box
//     takes an unfiltered box at once; after that, passing over goals changes nothing: only a goal the pointer rests on.
//   · A goal with nothing here sends a filtered box back to everything; at rest, a box doesn't react to it.
//   · A plan is not a filter, and while the pointer is in the box its filter stands.
//   · The filter lives on the way between its goal and its box: the columns from one to the other. Out of them, or off
//     the board, the box returns to everything after LEAVE_MS (unless another goal is about to take it).
//   · A goal in the box's own column keeps its place: the box changes inside the space it had, shorter, and the empty
//     space belongs to the mascot. A list that doesn't fit shows what fits, and "N more".
//   · "N more", "See all": the way out. It shows everything and ends the filter.
//   · A plan of the box opened: the box is only its header line (the count, "Replan"), and the opened plan stands under it,
//     alone; the rest comes back when it closes, in the filter it had. The plan stays where it was clicked, by this
//     module's own hold: nothing here waits for the column to scroll the family to the top (that glide is not ours).

import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch, type Ref } from 'vue'
import { store } from '../store'
import { findGoal } from './boardIndex'
import { liftScale } from './cardLift'
import { goalLight } from './look'
import { reducedMotion, timing } from './motion'
import type { GoalCardData } from '../types'

export const SHOWN = 3
const DWELL_MS = 250 // the pointer rests on a goal this long before a filtered box follows it
const LEAVE_MS = 250 // the pointer is out of the filter's way this long before the box returns to everything
const UNPIN_MS = 250 // a slip out of the box over a gap doesn't count as leaving it
const MIN_GAP = 52 // the empty place holds the mascot from this height

const COLUMN = '.pattern-vertical-board__column[data-vertical]'

/* Where the pointer is: the column and the goal under it. One listener for every box. */
export const pointerColumn = ref<string | null>(null)
export const pointerGoal = ref<string | null>(null)
let tracking = false
function track(): void {
  if (tracking || typeof window === 'undefined') return
  tracking = true
  window.addEventListener('pointerover', (event) => {
    const el = event.target instanceof Element ? event.target : null
    pointerColumn.value = el?.closest(COLUMN)?.getAttribute('data-vertical') ?? null
    pointerGoal.value = el?.closest('[data-goal-id]')?.getAttribute('data-goal-id') ?? null
  }, { capture: true, passive: true })
  document.addEventListener('pointerout', (event) => {
    if (!event.relatedTarget) { pointerColumn.value = null; pointerGoal.value = null }
  }, { passive: true })
}

/* The plans in every box: a plan is never a filter, in whichever box it stands. */
const registry = new Map<symbol, () => string[]>()
function isCarriedPlan(id: string): boolean {
  for (const ids of registry.values()) if (ids().includes(id)) return true
  return false
}

/** The column a goal stands in (its card, outside the carried boxes), or its own vertical when it is not drawn. */
function columnOf(id: string): string | null {
  const card = [...document.querySelectorAll<HTMLElement>(`[data-goal-id="${CSS.escape(id)}"]`)]
    .find((el) => !el.closest('[data-role="carried-group"]'))
  return card?.closest<HTMLElement>(COLUMN)?.dataset.vertical ?? findGoal(store.state.board, id)?.vertical ?? null
}
function columnOrder(): string[] {
  return [...new Set([...document.querySelectorAll<HTMLElement>(COLUMN)].map((el) => el.dataset.vertical ?? ''))]
}

/** A node's height, eased from where it stands now (a running move included) to where its content puts it. */
const runs = new WeakMap<HTMLElement, Animation>()
function stop(node: HTMLElement): void {
  const run = runs.get(node)
  if (run) { runs.delete(node); run.cancel() }
  node.style.overflow = ''
}
function ease(node: HTMLElement, from: number, to: number, force = false): void {
  if (reducedMotion() || (!force && Math.abs(from - to) < 1)) return
  node.style.overflow = 'hidden'
  const run = node.animate([{ height: `${from}px` }, { height: `${to}px` }], timing(200, 'large'))
  runs.set(node, run)
  const done = () => { if (runs.get(node) === run) { runs.delete(node); node.style.overflow = '' } }
  run.onfinish = done
  run.oncancel = done
}
/** The column's scroller around an element. */
function scrollerOf(el: HTMLElement | null): HTMLElement | null {
  let node = el?.parentElement ?? null
  while (node && !/auto|scroll/.test(getComputedStyle(node).overflowY)) node = node.parentElement
  return node
}
/** Where an element stands in the scroller's window, as laid out: a lift's scale and rise don't count. */
function restingTop(el: HTMLElement, scroller: HTMLElement): number {
  let y = 0
  for (let e: HTMLElement | null = el; e && e !== scroller; e = e.offsetParent as HTMLElement | null) y += e.offsetTop
  return y - scroller.scrollTop
}
/** Layout height: a lift's transform doesn't change it, a running height animation does. */
const heightOf = (el: HTMLElement): number => parseFloat(getComputedStyle(el).height) || el.offsetHeight

type Filter = { src: string; col: string | null; ids: string[]; shown: number }

export function useCarriedFilter(o: {
  vertical: () => string
  /** The box's plans, newest first. */
  plans: () => GoalCardData[]
  box: Ref<HTMLElement | null>
  place: Ref<HTMLElement | null>
}) {
  track()
  const filter = ref<Filter | null>(null)
  const hold = ref(0) // px: the place the box keeps while a goal under it is pointed at; 0 when it keeps none
  const expanded = ref(false)
  const pinned = ref(false) // the pointer is in the box
  const gap = ref(false) // the empty place is tall enough for the mascot
  const dwelling = ref(false)
  const lift = ref<string | null>(null)

  const token = Symbol('carried-box')
  registry.set(token, () => o.plans().map((g) => g.id))

  /** The plan of this box that is open, or one of its steps (going deeper keeps the plan as the path's first level). */
  const openPlan = computed(() => {
    if (store.state.openGoalVertical !== o.vertical()) return null
    const root = store.state.openPath[0]
    return root ? o.plans().find((g) => g.id === root) ?? null : null
  })

  /* What the box lists. */
  const family = computed(() => {
    const f = filter.value
    return f ? o.plans().filter((g) => f.ids.includes(g.id)) : null
  })
  const visible = computed(() => {
    if (openPlan.value) return [openPlan.value]
    if (family.value) return family.value.slice(0, filter.value?.shown ?? SHOWN)
    return expanded.value ? o.plans() : o.plans().slice(0, SHOWN)
  })
  const hidden = computed(() => o.plans().length - visible.value.length)
  /** The button under the list: the rest, the way out of an empty filter, or "Show fewer" once everything is open. */
  const button = computed(() => {
    if (openPlan.value) return null
    if (family.value && visible.value.length === 0) return 'See all'
    if (hidden.value > 0) return `${hidden.value} more`
    return !family.value && expanded.value && o.plans().length > SHOWN ? 'Show fewer' : null
  })
  const opened = computed(() => !family.value && expanded.value && button.value === 'Show fewer')
  /** The box takes its family's colour, or the colour of the plan the pointer is on; an empty filter has none. */
  const lit = computed(() => {
    if (openPlan.value) return null
    const f = family.value
    if (f) return f.length ? goalLight(f[0]!.color) : null
    const id = store.state.hoverChainId
    const plan = pinned.value && id ? o.plans().find((g) => g.id === id) : undefined
    return plan ? goalLight(plan.color) : null
  })

  /* One change of what the box shows, and the height it makes: the box and its place are both measured after the change,
     before either starts to move, so the place follows its own height and not the box's animated one. */
  let pass = 0
  async function commit(change: () => void, fit = false): Promise<void> {
    const box = o.box.value
    const place = o.place.value
    if (!box || !place) { change(); return }
    const mine = ++pass
    const fromBox = heightOf(box)
    const fromPlace = heightOf(place)
    change()
    await nextTick()
    if (mine !== pass) return
    stop(box)
    stop(place)
    if (fit) await trim(box, mine)
    if (mine !== pass) return
    const toBox = heightOf(box)
    const toPlace = heightOf(place)
    gap.value = !!filter.value && hold.value > 0 && hold.value - toBox >= MIN_GAP
    ease(box, fromBox, toBox)
    ease(place, fromPlace, toPlace, Math.abs(fromBox - toBox) >= 1)
  }
  /** A box that keeps its place shows as many of the family as fit in it. */
  async function trim(box: HTMLElement, mine: number): Promise<void> {
    while (filter.value && hold.value > 0 && filter.value.shown > 0 && heightOf(box) > hold.value + 1) {
      filter.value = { ...filter.value, shown: filter.value.shown - 1 }
      await nextTick()
      if (mine !== pass) return
    }
  }

  function apply(id: string, plans: GoalCardData[]): void {
    const own = columnOf(id) === o.vertical()
    const space = hold.value || (o.place.value ? heightOf(o.place.value) : 0)
    void commit(() => {
      hold.value = own ? space : 0
      filter.value = { src: id, col: columnOf(id), ids: plans.map((g) => g.id), shown: Math.min(SHOWN, plans.length) }
    }, own)
  }
  function rest(): void {
    if (!filter.value && !hold.value) return
    void commit(() => { filter.value = null; hold.value = 0 })
  }
  /** "N more" or "See all" in a filtered box: everything, and the filter ends. At rest it opens and closes the rest. */
  function more(): void {
    void commit(() => {
      if (filter.value) { filter.value = null; hold.value = 0; expanded.value = true } else expanded.value = !expanded.value
    })
  }

  /* Which goal the box follows. */
  let dwell: { id: string; timer: ReturnType<typeof setTimeout> } | null = null
  function clearDwell(): void {
    if (dwell) clearTimeout(dwell.timer)
    dwell = null
    dwelling.value = false
  }
  function wanted(id: string): GoalCardData[] {
    const chain = store.hoverChain.value
    if (!chain || chain.id !== id) return []
    return o.plans().filter((g) => chain.set.has(g.id))
  }
  function follow(id: string): void {
    const plans = wanted(id)
    if (!plans.length && columnOf(id) !== o.vertical()) rest()
    else apply(id, plans)
  }
  function consider(id: string | null): void {
    if (!id) return
    if (openPlan.value) { clearDwell(); return } // a plan is open: the box is its header, and nothing follows
    if (pinned.value || isCarriedPlan(id)) { clearDwell(); return }
    const f = filter.value
    if (f && f.src === id) { clearDwell(); return }
    if (dwell && dwell.id !== id) clearDwell()
    const plans = wanted(id)
    if (!f && plans.length) { clearDwell(); apply(id, plans); return }
    if (!f && columnOf(id) !== o.vertical()) { clearDwell(); return }
    if (dwell) return
    dwelling.value = true
    dwell = {
      id,
      timer: setTimeout(() => {
        dwell = null
        dwelling.value = false
        if (store.state.hoverChainId === id && pointerGoal.value !== null && !pinned.value) follow(id)
      }, DWELL_MS),
    }
  }
  watch(() => store.state.hoverChainId, consider)
  watch(pointerGoal, (goal) => { if (goal === null) clearDwell() }) // leaving a goal is not resting on it

  /* The plans above the clicked one go with the opening, which moves the card up the column. The column is made to keep it
     where it was clicked (as far as its scroll allows; at the top it can't, and the card stands right under the header
     line): read where the card is before, and put it back after the new layout. Idempotent with any other hold or glide of
     the column: it only moves the scroll by what the card still is off its place. */
  watch(openPlan, async (plan) => {
    if (!plan) return
    clearDwell()
    hold.value = 0
    gap.value = false
    const card = o.place.value?.querySelector<HTMLElement>(`[data-goal-id="${CSS.escape(plan.id)}"]`) ?? null
    const scroller = scrollerOf(card)
    if (!card || !scroller) return
    const before = restingTop(card, scroller)
    await nextTick()
    scroller.scrollTop += restingTop(card, scroller) - before
  }, { flush: 'pre' })

  /* The way between the goal and the box. */
  const onTheWay = computed(() => {
    const f = filter.value
    if (!f) return true
    const here = pointerColumn.value
    if (!here) return false
    const order = columnOrder()
    const from = order.indexOf(f.col ?? o.vertical())
    const to = order.indexOf(o.vertical())
    const at = order.indexOf(here)
    return at >= 0 && at >= Math.min(from, to) && at <= Math.max(from, to)
  })
  let leaving: ReturnType<typeof setTimeout> | null = null
  let leaveDue = false
  watch([filter, onTheWay], () => {
    if (leaving) clearTimeout(leaving)
    leaving = null
    leaveDue = false
    if (!filter.value || onTheWay.value) return
    leaving = setTimeout(() => {
      leaving = null
      if (dwelling.value) leaveDue = true // another goal is about to take the box: no step through "everything"
      else rest()
    }, LEAVE_MS)
  })
  watch(dwelling, (now) => {
    if (!now && leaveDue && filter.value && !onTheWay.value) { leaveDue = false; rest() }
  })

  /* The pointer in the box: it lifts as one piece, and its filter stands. */
  let unpin: ReturnType<typeof setTimeout> | null = null
  function measureLift(): void {
    const box = o.box.value
    if (box) lift.value = liftScale(box.offsetWidth, box.offsetHeight).toFixed(4)
  }
  function enter(): void {
    if (unpin) clearTimeout(unpin)
    unpin = null
    clearDwell()
    pinned.value = true
    measureLift()
  }
  function leave(): void {
    if (unpin) return
    unpin = setTimeout(() => {
      unpin = null
      pinned.value = false
      consider(store.state.hoverChainId)
    }, UNPIN_MS)
  }
  let sizes: ResizeObserver | null = null
  onMounted(() => {
    sizes = typeof ResizeObserver === 'undefined' ? null : new ResizeObserver(() => { if (pinned.value) measureLift() })
    if (o.box.value) sizes?.observe(o.box.value)
  })

  onBeforeUnmount(() => {
    registry.delete(token)
    clearDwell()
    for (const timer of [leaving, unpin]) if (timer) clearTimeout(timer)
    sizes?.disconnect()
    for (const node of [o.box.value, o.place.value]) if (node) stop(node)
  })

  return {
    filter, hold, expanded, pinned, gap, lift, lit, visible, family, button, opened, more, openPlan,
    enter, leave,
  }
}
