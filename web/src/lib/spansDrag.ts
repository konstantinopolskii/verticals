// The drag's side of the spans (docs/design-handoff S5.P1, S5.P2, S5.P6): resting the held goal on a column's dots melts
// it in and opens that column's spans; the screen's edges move them on, or send the floating column to the other side;
// letting go lands the goal as a drop does and then gives the board back.
import { nextTick, reactive } from 'vue'
import { knob } from './tuning'
import { closeSpans, homeSpans, openSpans, spans, stepSpans, swapSide, type SpanScale } from './spans'
import { moving, park, unpark } from './moving'
import type { DragState } from './drag'

export const dots = reactive({
  /** The column whose dots hold the melted goal. */
  held: null as SpanScale | null,
  goalId: null as string | null,
  /** The held goal has melted into the dots and not yet grown back (S5.P2.013, .015). */
  melted: false,
  /** Let go in the spans: the goal lands and the board comes back, the move is over. */
  landing: false,
})

export interface SpansDragPorts {
  drag: DragState
  today: () => string
  /** The rendered rows moved under the hand: read them again and retarget at the pointer. */
  retarget: () => void
  reload: () => Promise<void>
  /** The board's wide column: a hover on the way to the dots may widen one, and the board comes back as it was. */
  expanded: () => string | null
  setExpanded: (vertical: string | null) => void
}

let ports: SpansDragPorts | null = null
let dotsEl: Element | null = null
let dotsTimer = 0
let edgeTimer = 0
let edgeDir = 0
let meltVersion = 0
let expandedBefore: string | null | undefined

export function bindSpansDrag(p: SpansDragPorts): void {
  ports = p
}

function wait(ms: number): Promise<void> {
  return new Promise((resolve) => window.setTimeout(resolve, ms))
}

function afterLayout(): void {
  void nextTick(() => requestAnimationFrame(() => ports?.retarget()))
}
/* The rows slide in or over for a while: read them again once they stand still, so the drop lands where it shows. */
let settleTimer = 0
function afterMotion(ms: number): void {
  afterLayout()
  window.clearTimeout(settleTimer)
  settleTimer = window.setTimeout(afterLayout, ms + 20)
}

/** Every move of an armed drag. */
export function onDragMove(x: number, y: number): void {
  if (expandedBefore === undefined) expandedBefore = ports?.expanded() ?? null
  const el = document.elementFromPoint(x, y)?.closest<HTMLElement>('[data-role="column-dots"]') ?? null
  if (el !== dotsEl) {
    window.clearTimeout(dotsTimer)
    dotsEl = el
    const scale = el?.dataset.dotsVertical as SpanScale | undefined
    // Passing over the dots without resting opens nothing (S5.P2.020).
    if (scale && scale !== spans.vertical) dotsTimer = window.setTimeout(() => void melt(scale), knob('dotsHold'))
  }
  edge(spans.vertical ? x : -1)
}

async function melt(scale: SpanScale): Promise<void> {
  const drag = ports?.drag
  if (!drag?.id) return
  const version = ++meltVersion
  dots.held = scale
  dots.goalId = drag.id
  dots.melted = true
  await wait(200)
  if (version !== meltVersion || !drag.id) return
  await openSpans(scale, drag.sourceVertical ?? 'maybe', drag.sourcePeriodKey, ports!.today())
  if (version !== meltVersion) return
  dots.held = null
  afterMotion(400)
  await wait(400)
  if (version === meltVersion) dots.melted = false
}

/* The screen's last pixels move the spans by one every step; pushed into the side where the floating column stands, the
   column goes to the other side first (S5.P1.019, .020, .052). */
function edge(x: number): void {
  const zone = knob('spanEdge')
  const dir = x < 0 ? 0 : x >= window.innerWidth - zone ? 1 : x <= zone ? -1 : 0
  if (dir === edgeDir) return
  window.clearInterval(edgeTimer)
  edgeDir = dir
  if (dir) edgeTimer = window.setInterval(() => edgeTick(dir as 1 | -1), knob('spanStep'))
}
function edgeTick(dir: 1 | -1): void {
  if (!spans.vertical) return
  if ((spans.side === 'right' ? 1 : -1) === dir) swapSide()
  else stepSpans(dir)
  afterMotion(300)
}

function stopTimers(): void {
  window.clearTimeout(dotsTimer)
  window.clearTimeout(settleTimer)
  window.clearInterval(edgeTimer)
  dotsEl = null
  edgeDir = 0
}

/** Let go over the field while the spans are open: the goal waits above it instead of landing (S5.P3.037). */
let cancelledRelease = false
export function beforeRelease(cancelled: boolean): boolean {
  cancelledRelease = cancelled
  const drag = ports?.drag
  if (cancelled || !drag?.id || !spans.vertical) return false
  if (!document.elementFromPoint(drag.x, drag.y)?.closest('.circle-field')) return false
  park(drag.id)
  return true
}

/** The drag ended: once the goal has landed (or flown back), the board comes back as it was (S5.P6.005, .006). */
export function afterRelease(settleMs: number, parked = false): void {
  stopTimers()
  meltVersion += 1
  dots.held = null
  dots.melted = false
  dots.goalId = null
  // A goal kept above the field is one move with the drag that takes it on: the board comes back as it was before both.
  if (parked) return
  const before = expandedBefore ?? null
  expandedBefore = undefined
  if (moving.goalId) unpark()
  if (!spans.vertical) return
  // Cancelled: the spans scroll back to the goal's period while it flies home, then the board returns (S5.P1.027).
  const homing = cancelledRelease && spans.offset !== 0
  if (homing) homeSpans()
  dots.landing = true
  window.setTimeout(() => {
    dots.landing = false
    closeSpans()
    ports?.setExpanded(before)
    void ports?.reload()
  }, homing ? Math.max(settleMs, 320) : settleMs)
}

/** Esc or a cancelled view: the spans go and nothing moves. */
export function cancelSpans(): void {
  stopTimers()
  meltVersion += 1
  dots.held = null
  dots.melted = false
  dots.landing = false
  closeSpans()
}
