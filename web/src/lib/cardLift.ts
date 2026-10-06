// Hover lift (KK, 27 Sep 2026): "On hover of the card it should have the [hover] background, no need for shadow, also
// subtasks of this should also scale together, so we have like a full card with subtask background highlighted and
// other cards highlighted too", then "I want scaling scale card closer".
//
// Pointing anywhere on a top-level goal (its row, a subgoal, the gaps between them) raises the goal and its rendered
// subgoals as one piece: 2 px up and larger around their shared centre, colour and all. The colour is not this
// module's: every goal paints it with the board's one highlight layer (`lib/goalWash.ts`).
//
// The card (KCard) and its subgoal list are sibling elements, so both get the same scale around one origin. Columns
// give a lifted card 8 px of room past their edge (`Column.vue`, KK: "u still cut the scaled tasks on the left and
// right of each vertical column, because they have this overflow hidden param"), and cards sit 2 px apart with 6 px
// of padding around their words: the piece grows up to 6%, but no more than 7 px a side (1 px short of that room: on
// the clip line the clip shaves the colour's rim) and 4 px an end (plus the 2 px rise), so a wide or tall card grows
// less and never reaches a neighbour's words.
//
// Leaving, the piece settles as one (KK, 4 Oct 2026, from a mockup): after LEAVE_GRACE_MS its colour, its size and its
// subgoals go back together on one curve, and it keeps its layer until it has landed (`goal-card--settling`), so a
// neighbour never covers its coloured edge on the way.
//
// A click keeps the lift, so a lifted card that opens stays lifted (KK: "if you hovered such big unselected card and
// then clicked on it to open, scaling shouldn't disappear"); the opened card lifts like any other and follows its
// column as it widens. Opening moves the card from under a still pointer, and the browser calls that a leave: after a
// click the lift holds until the pointer moves away from where it clicked, and ends then only if it is outside the
// card; meanwhile the card that slid under the pointer waits, so only the clicked card is lifted. Drag measures the
// row at press time (`onRowPointerDown`) from the card at rest (`atRest`), and the lift drops at once when a drag
// starts.

import { onBeforeUnmount, ref, watch, type Ref } from 'vue'

const LEAVE_GRACE_MS = 60 // the pointer crossing the gap between the card and its list must not drop the lift
const SETTLE_MS = 240 // the way back (--motion-lift-out, 220 ms) and a frame: the piece keeps its layer until it lands
const HOLD_MOVE_PX = 3 // after a click, the pointer has moved on once it is this far from where it clicked
const MAX_SCALE = 1.06
const SIDE_GROWTH_PX = 7 // most a side may grow: the column gives 8 px of room past the card's column
const END_GROWTH_PX = 4 // most an end may grow: with the 2 px rise it stays inside the 2 px gap and the neighbour's padding

/** Reads the board as it lies at rest, while a lifted card stays lifted on screen: every lift on the board is taken
 *  off and put back inside this one call, so nothing is painted in between. The whole board, not only this card: a
 *  step pressed inside a lifted piece is lifted by its top-level goal, and a drag measures every row it may land on
 *  (a lifted piece is up to 6% larger: the gap a picked-up card left pushed the cards below 1.5 px). */
export function atRest<T>(read: () => T): T {
  const els = [...document.querySelectorAll<HTMLElement>(`.${LIFTED_CLASS}, .${LIFTED_LIST_CLASS}`)]
  if (!els.length) return read()
  const classes = els.map((el) => (el.classList.contains(LIFTED_CLASS) ? LIFTED_CLASS : LIFTED_LIST_CLASS))
  els.forEach((el, i) => {
    el.style.setProperty('transition', 'none', 'important')
    el.classList.remove(classes[i])
  })
  const value = read()
  els.forEach((el, i) => {
    el.classList.add(classes[i])
    void el.offsetWidth // settle the lifted style before the transition comes back
    el.style.removeProperty('transition')
  })
  return value
}

/** How much a lifted piece grows: up to 6%, but no more than the room around it allows (7 px a side, 4 px an end). The carried
 *  box lifts by the same rule, so a tall one never grows into the margin under it. */
export function liftScale(width: number, height: number): number {
  return Math.min(MAX_SCALE, 1 + (2 * SIDE_GROWTH_PX) / width, 1 + (2 * END_GROWTH_PX) / height)
}

let holder: symbol | null = null // the card holding its lift after a click
const waiting = new Set<() => void>() // cards the pointer entered meanwhile: they lift once the hold ends
function releaseHold(): void {
  holder = null
  const retries = [...waiting]
  waiting.clear()
  retries.forEach((retry) => retry())
}

/* A family's move takes the other lifts off inside its own movement (`lib/familyMotion.ts`): it reads a lifted card
   where it stands and lands it at rest, so a lift that came back after the move was a second movement, 6-9 px at
   430 ms (the motion trace, 3 Oct 2026). Then nothing lifts until the hand moves: what slid under a still pointer is
   not what the hand pointed at. The card the hand clicked keeps its lift through the move (KK, 4 Oct 2026: "keeping
   it scaled"): the move reads it lifted and lands it lifted at its new size, its scale measured again for that size
   (`refreshLifts`) before the move reads where it lands, so the lift changes inside the one movement. */
const releases = new Set<() => void>()
const refreshers = new Set<() => void>()
let quiet: { x: number; y: number } | null = null
export function releaseLifts(at: { x: number; y: number } | null): void {
  quiet = at ?? (Number.isNaN(pointer.x) ? null : { ...pointer })
  releases.forEach((release) => release())
}
/** Measures every lifted card again for the size it has now and writes its lift onto it at once, not on Vue's next
 *  render: the move reads where things land right after the change. */
export function refreshLifts(): void {
  refreshers.forEach((refresh) => refresh())
}
function wake(event: PointerEvent): void {
  if (!quiet || Math.hypot(event.clientX - quiet.x, event.clientY - quiet.y) < HOLD_MOVE_PX) return
  quiet = null
  if (holder === null) releaseHold()
}
export const LIFTED_CLASS = 'goal-card--lifted'
export const LIFTED_LIST_CLASS = 'goal-card__children--lifted'
const SETTLING_CLASSES = ['goal-card--settling', 'goal-card__children--settling']
/** On a card lifted by a click, and its list: its lift rides the move (goalCard.css), where any other lift waits. */
const HELD_ATTR = 'data-lift-held'

/* A goal's "…" menu hangs from its dots (KK, 27 Sep 2026: "it jumps here and there if i click on menu icon"). Moving
   into the menu is leaving the card, so the card used to drop its lift under the open menu, the dots moved, and the
   menu followed them and flipped sides. While a goal's menu is open, its card holds the lift and its family stays lit
   whatever the pointer does, and no other card reacts to the pointer: the menu is the one thing that moves. */
export const menuGoalId = ref<string | null>(null)
export function anyMenuOpen(): boolean {
  return typeof document !== 'undefined' && document.body.classList.contains('popover-engine-open')
}
const afterMenu = new Set<() => void>() // cards the pointer entered while a menu was open: they react once it closes
/** Run `fn` once the open menu closes (`PopoverEngine.vue` announces it). */
export function whenMenuCloses(fn: () => void): void {
  afterMenu.add(fn)
}
let pointer = { x: Number.NaN, y: Number.NaN } // where the pointer last was: a card settles by it when its menu closes
if (typeof window !== 'undefined') {
  window.addEventListener('pointermove', (event) => { pointer = { x: event.clientX, y: event.clientY }; wake(event) }, { capture: true, passive: true })
  window.addEventListener('verticals:root-popover-close', () => {
    const retries = [...afterMenu]
    afterMenu.clear()
    retries.forEach((retry) => retry())
  })
}
export function pointerOver(...els: Array<HTMLElement | null | undefined>): boolean {
  return els.some((el) => {
    const r = el?.getBoundingClientRect()
    return r !== undefined && pointer.x >= r.left && pointer.x <= r.right && pointer.y >= r.top && pointer.y <= r.bottom
  })
}

type LiftStyle = Record<string, string>

export function useCardLift(options: {
  card: () => HTMLElement | null
  list: Ref<HTMLElement | null>
  /** Checked on every enter: only a top-level goal lifts, never while a drag runs. */
  enabled: () => boolean
  /** While true the lift holds whatever the pointer does: the goal's menu, or one of its subgoals', is open. */
  pinned?: () => boolean
}) {
  const lifted = ref(false)
  const settling = ref(false) // lifted no more, on its way back: still on its own layer
  const cardStyle = ref<LiftStyle>({})
  const listStyle = ref<LiftStyle>({})
  let leaveTimer: ReturnType<typeof setTimeout> | null = null
  let settleTimer: ReturnType<typeof setTimeout> | null = null

  function clearTimers(): void {
    if (leaveTimer !== null) { clearTimeout(leaveTimer); leaveTimer = null }
    if (settleTimer !== null) { clearTimeout(settleTimer); settleTimer = null }
  }
  function settle(on: boolean): void {
    if (settleTimer !== null) { clearTimeout(settleTimer); settleTimer = null }
    settling.value = on
    if (on) settleTimer = setTimeout(() => { settleTimer = null; settling.value = false }, SETTLE_MS)
  }

  function measure(): boolean {
    const card = options.card()
    if (!card) return false
    const list = options.list.value
    // offset* are layout boxes, untouched by a transform still easing out; the two siblings share an offsetParent
    const width = card.offsetWidth
    const top = card.offsetTop
    const bottom = Math.max(top + card.offsetHeight, list ? list.offsetTop + list.offsetHeight : 0)
    const scale = liftScale(width, bottom - top)
    const cx = card.offsetLeft + width / 2
    const cy = (top + bottom) / 2
    const origin = (el: HTMLElement) => `${cx - el.offsetLeft}px ${cy - el.offsetTop}px`
    const lift = { '--goal-lift-scale': scale.toFixed(4) }
    cardStyle.value = { transformOrigin: origin(card), ...lift }
    listStyle.value = list ? { transformOrigin: origin(list), ...lift } : {}
    return true
  }

  const me = Symbol('card')
  const retry = () => { if ([options.card(), options.list.value].some((el) => el?.matches(':hover'))) enter() }

  function enter(): void {
    if (leaveTimer !== null) { clearTimeout(leaveTimer); leaveTimer = null }
    if ((holder !== null && holder !== me) || quiet) { waiting.add(retry); return }
    if (!lifted.value && anyMenuOpen()) { whenMenuCloses(retry); return }
    if (lifted.value || !options.enabled() || !measure()) return
    settle(false)
    lifted.value = true
  }

  // The menu closed: the card settles as if the pointer had just moved there.
  watch(() => options.pinned?.() ?? false, (pin, was) => {
    if (was && !pin && !pointerOver(options.card(), options.list.value)) leave()
  })

  // A lifted card whose size changes (it opens, its column widens) scales around its new centre.
  const observer = new ResizeObserver(() => { if (lifted.value) measure() })
  watch([() => options.card(), options.list], ([card, list]) => {
    observer.disconnect()
    for (const el of [card, list]) if (el) observer.observe(el)
  }, { flush: 'post' })

  let held: { x: number; y: number } | null = null // where a click landed, while the lift holds for it

  function leave(): void {
    if (leaveTimer !== null) clearTimeout(leaveTimer)
    waiting.delete(retry)
    afterMenu.delete(retry)
    if (options.pinned?.()) return // its menu is open: it settles when the menu closes
    if (held) return // the card moved, not the pointer: wait for the pointer to move on
    leaveTimer = setTimeout(() => {
      leaveTimer = null
      if (!lifted.value) return
      lifted.value = false
      settle(true)
    }, LEAVE_GRACE_MS)
  }

  function mark(on: boolean): void {
    for (const el of [options.card(), options.list.value]) {
      if (on) el?.setAttribute(HELD_ATTR, '')
      else el?.removeAttribute(HELD_ATTR)
    }
  }
  watch(lifted, (now) => { if (!now) mark(false) })

  function hold(event: MouseEvent): void {
    if (!lifted.value) return
    held = { x: event.clientX, y: event.clientY }
    holder = me
    mark(true)
    window.addEventListener('pointermove', moveOn, { passive: true })
  }

  function moveOn(event: PointerEvent): void {
    if (!held || Math.hypot(event.clientX - held.x, event.clientY - held.y) < HOLD_MOVE_PX) return
    held = null
    window.removeEventListener('pointermove', moveOn)
    if (holder === me) releaseHold()
    const inside = [options.card(), options.list.value].some((el) => {
      const r = el?.getBoundingClientRect()
      return r !== undefined && event.clientX >= r.left && event.clientX <= r.right && event.clientY >= r.top && event.clientY <= r.bottom
    })
    if (!inside) leave()
  }

  /** Back to rest now, with no easing: a drag has started from this card. */
  function drop(): void {
    clearTimers()
    held = null
    window.removeEventListener('pointermove', moveOn)
    if (holder === me) releaseHold()
    mark(false)
    const away = lifted.value || settling.value
    settle(false)
    if (!away) return
    lifted.value = false
    for (const el of [options.card(), options.list.value]) {
      if (!el) continue
      el.style.setProperty('transition', 'none', 'important') // outranks the hover rules' !important transitions
      el.classList.remove(LIFTED_CLASS, LIFTED_LIST_CLASS, ...SETTLING_CLASSES)
      requestAnimationFrame(() => requestAnimationFrame(() => el.style.removeProperty('transition')))
    }
  }

  /* A click holds the lift, heard on the way down to what was clicked. A plain listener, not the card's
     `@click.capture`: Vue runs a handler only for an event newer than the handler by `Date.now()`, so under a clock that
     stands still (the UI suite pins it) only the first Vue handler on an event's path runs, and a capture handler on the
     card is always first: a click on a card's title opened nothing there. */
  let clickHost: HTMLElement | null = null
  watch(() => options.card(), (card) => {
    clickHost?.removeEventListener('click', hold, true)
    clickHost = card
    clickHost?.addEventListener('click', hold, true)
  }, { flush: 'post' })

  const release = (): void => { if (holder !== me) drop() } // the clicked card keeps its lift through the move
  releases.add(release)
  const refresh = (): void => {
    if (!lifted.value || !measure()) return
    if (holder === me) mark(true) // the open card's list may be a new element
    for (const [el, style] of [[options.card(), cardStyle.value], [options.list.value, listStyle.value]] as const) {
      if (!el) continue
      for (const [name, value] of Object.entries(style)) {
        if (name.startsWith('--')) el.style.setProperty(name, value)
        else if (name === 'transformOrigin') el.style.transformOrigin = value
      }
    }
  }
  refreshers.add(refresh)

  onBeforeUnmount(() => {
    releases.delete(release)
    refreshers.delete(refresh)
    clearTimers()
    observer.disconnect()
    clickHost?.removeEventListener('click', hold, true)
    window.removeEventListener('pointermove', moveOn)
    waiting.delete(retry)
    afterMenu.delete(retry)
    if (holder === me) releaseHold()
  })

  return { lifted, settling, cardStyle, listStyle, enter, leave, drop, atRest, hold }
}
