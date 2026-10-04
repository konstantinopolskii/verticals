// The weeks under your hand (docs/design-handoff S5.P1): while you move a goal the board can turn into one vertical's
// periods in a row at the regular columns' width, the last one's edge showing and this one next, with one column of the
// regular board floating wide over them at a side. Spans render and load one beyond each edge, so stepping never shows
// one loading or leaving (S5.P1.051).
import { computed, reactive } from 'vue'
import { fetchSpans, type BoardResponse, type GoalCard } from './api'
import { toColumnData } from './boardProjection'
import { ghostOf } from './ghost'
import { adjacentPeriodAnchor, type AdjustableVertical } from './periodNavigation'
import { VERTICAL_SCALES, MONTH_NAMES, verticalRank, type VerticalScale } from './periods'
import { localDate } from './schedule'
import { defineKnobs, knob } from './tuning'
import type { BoardColumnData } from '../types'

export type SpanScale = AdjustableVertical

/** What the view is called above the field (S5.P3.024). */
export const VIEW_NAMES: Record<SpanScale, string> = {
  day: 'Days', week: 'Weeks', month: 'Months', quarter: 'Quarters', year: 'Years', decade: '3 years',
}
defineKnobs('Moving a goal', [
  { key: 'spanEnds', label: 'Week ends in the headers (1 on, 0 off)', value: 1, min: 0, max: 1, step: 1 },
  { key: 'spanEdge', label: 'Screen edge that moves the spans', value: 12, min: 4, max: 40, step: 1, unit: 'px' },
  { key: 'spanStep', label: 'One span every', value: 600, min: 200, max: 1500, step: 50, unit: 'ms' },
  { key: 'dotsHold', label: 'Rest over the dots', value: 150, min: 0, max: 600, step: 10, unit: 'ms' },
])

export const FLOAT_WIDTH = 400
export const EDGE_GAP = 2
/** How much of the last span shows before this one (drawn: "last week shows its last 40 px"). */
const SLIVER = 40

/** The regular board the spans came out of, caught just before they replace it (S5.P1.023, .024). */
export interface SpansIntro { ghost: HTMLElement; float: DOMRect | null; held: DOMRect | null }

export const spans = reactive({
  /** The vertical laid out as spans, or null for the regular board. */
  vertical: null as SpanScale | null,
  /** The regular column that floats wide at a side (S5.P1.015, .050). */
  floating: null as string | null,
  side: 'right' as 'left' | 'right',
  /** The first span in view, counted from this period (0). */
  offset: 0,
  /** How many spans fit beside the floating column. */
  shown: 5,
  /** The loaded spans: `first` is the offset of `board.columns[0]`. */
  board: null as BoardResponse | null,
  first: 0,
  starts: [] as string[],
  /** The regular board as it was, for the spans to come out of (S5.P1.023). */
  intro: null as SpansIntro | null,
  /** Where the goal came from, to fly back to (S5.P6.006). */
  from: null as { vertical: string; periodKey: string | null } | null,
})

let today = ''
let loading = 0

function thisStart(scale: SpanScale, day: string): string {
  return adjacentPeriodAnchor(adjacentPeriodAnchor(day, scale, 1), scale, -1)
}
function stepFrom(scale: SpanScale, start: string, n: number): string {
  let at = start
  for (let i = 0; i < Math.abs(n); i += 1) at = adjacentPeriodAnchor(at, scale, n > 0 ? 1 : -1)
  return at
}

/** The column that floats: the one the goal came from, or the next one up when that is the view itself. */
export function floatingFor(scale: SpanScale, fromVertical: string): string {
  if (fromVertical !== scale && fromVertical !== 'maybe') return fromVertical
  return VERTICAL_SCALES[Math.min(verticalRank(scale) + 1, VERTICAL_SCALES.length - 1)]!
}

async function load(scale: SpanScale | null = spans.vertical): Promise<boolean> {
  if (!scale) return false
  const first = spans.offset - 2
  const count = spans.shown + 3
  const cached = spans.board && spans.vertical === scale
  if (cached && first >= spans.first && first + count <= spans.first + spans.board!.columns.length) return true
  const version = ++loading
  const start = stepFrom(scale, thisStart(scale, today), first)
  const board = await fetchSpans(scale, start, count).catch(() => null)
  if (!board || version !== loading) return false
  spans.board = board
  spans.first = first
  spans.starts = Array.from({ length: count }, (_, i) => stepFrom(scale, start, i))
  return true
}

/** Open a vertical's spans: this period first, the goal's own column (or the next one up) floating (S5.P1.044). */
export async function openSpans(
  scale: SpanScale, fromVertical: string, fromPeriodKey: string | null, day: string,
): Promise<void> {
  today = day
  spans.offset = 0
  spans.shown = fitCount()
  // The view changes once its spans are here, so they come in whole (S5.P1.051).
  if (!await load(scale)) return
  const floating = floatingFor(scale, fromVertical)
  const floatRank = VERTICAL_SCALES.indexOf(floating as VerticalScale)
  spans.side = floatRank >= 0 && floatRank < verticalRank(scale) ? 'left' : 'right'
  spans.floating = floating
  spans.from = { vertical: fromVertical, periodKey: fromPeriodKey }
  spans.intro = catchIntro(scale, floating)
  spans.vertical = scale
}

function catchIntro(scale: SpanScale, floating: string): SpansIntro | null {
  const strip = document.querySelector<HTMLElement>('[data-role="column-strip"]')
  if (!strip) return null
  const column = (vertical: string) => strip.querySelector<HTMLElement>(`:scope > .pattern-vertical-board__column[data-vertical="${vertical}"]`)
  const ghost = ghostOf(strip)
  // The floating column lifts out of its place, so the copy leaves that place empty.
  const lifted = ghost.querySelector<HTMLElement>(`:scope > .pattern-vertical-board__column[data-vertical="${floating}"]`)
  if (lifted) lifted.style.visibility = 'hidden'
  for (const dots of ghost.querySelectorAll<HTMLElement>('.column-dots')) dots.style.visibility = 'hidden'
  return { ghost, float: column(floating)?.getBoundingClientRect() ?? null, held: column(scale)?.getBoundingClientRect() ?? null }
}

export function closeSpans(): void {
  loading += 1
  spans.intro = null
  spans.vertical = null
  spans.floating = null
  spans.board = null
  spans.starts = []
  spans.from = null
}

/** One span on or back (S5.P1.020, .025). */
export function stepSpans(direction: 1 | -1): void {
  if (!spans.vertical) return
  spans.offset += direction
  void load()
}

/** Back to this period, where a cancelled goal flies home (S5.P1.027). */
export function homeSpans(): void {
  if (!spans.vertical || spans.offset === 0) return
  spans.offset = 0
  void load()
}

/** The floating column goes to the other side (S5.P1.052). */
export function swapSide(): void {
  spans.side = spans.side === 'right' ? 'left' : 'right'
}

function windowWidth(): number {
  return typeof window === 'undefined' ? 1458 : window.innerWidth
}
/** Spans at the regular columns' width: the board's seven share the window when none is wide (S5.P1.003). */
export function spanWidth(): number {
  return windowWidth() / 7
}
/** Where the floating column leaves room on the left. */
function lead(): number {
  return spans.side === 'left' ? FLOAT_WIDTH + 2 * EDGE_GAP : 0
}
/** The spans from this one to the window's right edge; the ones at the right run on under the floating column. */
export function fitCount(): number {
  return Math.max(1, Math.ceil((windowWidth() - SLIVER) / spanWidth()))
}
/** The row's left edge: two spans before this one, the nearer showing its last 40 px. */
export function rowLeft(): number {
  return lead() + SLIVER - 2 * spanWidth()
}

/** The start day of a loaded span's period, for the schedule write (S5.P6.003). */
export function spanAnchor(scale: string, periodKey: string): string | null {
  if (!spans.board || scale !== spans.vertical) return null
  const index = spans.board.columns.findIndex((column) => column.period_key === periodKey)
  return index >= 0 ? spans.starts[index] ?? null : null
}

/** "This week", "Next week", "In 2 weeks"; "Last week", "2 weeks ago" (S5.P1.007, .028). */
export function howFar(scale: SpanScale, n: number): string {
  const unit: Record<SpanScale, [string, string]> = {
    day: ['day', 'days'], week: ['week', 'weeks'], month: ['month', 'months'], quarter: ['quarter', 'quarters'],
    year: ['year', 'years'], decade: ['3 years', '3 years'],
  }
  if (scale === 'day') return n === 0 ? 'Today' : n === 1 ? 'Tomorrow' : n === -1 ? 'Yesterday' : n > 0 ? `In ${n} days` : `${-n} days ago`
  if (scale === 'decade') {
    return n === 0 ? 'These 3 years' : n === 1 ? 'Next 3 years' : n === -1 ? 'Last 3 years' : n > 0 ? `In ${3 * n} years` : `${-3 * n} years ago`
  }
  const [one, many] = unit[scale]
  if (n === 0) return `This ${one}`
  if (n === 1) return `Next ${one}`
  if (n === -1) return `Last ${one}`
  return n > 0 ? `In ${n} ${many}` : `${-n} ${many} ago`
}

function short(d: Date): string {
  return `${d.getDate()} ${MONTH_NAMES[d.getMonth()]!.slice(0, 3)}`
}
/** The span's date, big, and its end, small and light (S5.P1.005-.014). */
export function spanDates(scale: SpanScale, start: string): { date: string; end: string } {
  const d = localDate(start)
  switch (scale) {
    case 'day': return { date: short(d), end: ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'][d.getDay()]! }
    case 'week': return { date: short(d), end: short(new Date(d.getFullYear(), d.getMonth(), d.getDate() + 6)) }
    // A month's name fills the header alone; "November 2026" would not fit (S5.P1.014's 184 px).
    case 'month': return { date: MONTH_NAMES[d.getMonth()]!, end: '' }
    case 'quarter': return { date: `Q${Math.floor(d.getMonth() / 3) + 1}`, end: String(d.getFullYear()) }
    case 'year': return { date: String(d.getFullYear()), end: '' }
    case 'decade': return { date: `${d.getFullYear()}–${d.getFullYear() + 2}`, end: '' }
  }
}

export interface SpanColumn {
  n: number
  column: BoardColumnData | null
  how: string
  date: string
  end: string
  start: string
  /** Out of view: 'before' the last one's edge and the one past it, 'after' the window or under the floating column. */
  edge: 'before' | 'after' | null
}

/** Every rendered span, one beyond each edge; one not loaded yet keeps its place empty. */
export const spanRow = computed<SpanColumn[]>(() => {
  const scale = spans.vertical
  const board = spans.board
  if (!scale || !board) return []
  const now = new Date()
  const width = spanWidth()
  const left = rowLeft()
  const right = windowWidth() - (spans.side === 'right' ? FLOAT_WIDTH + 2 * EDGE_GAP : 0)
  const out: SpanColumn[] = []
  for (let n = spans.offset - 2; n <= spans.offset + spans.shown; n += 1) {
    const index = n - spans.first
    const col = board.columns[index]
    const start = spans.starts[index] ?? ''
    const x = left + (n - spans.offset + 2) * width
    const edge = n < spans.offset ? 'before' : x >= right ? 'after' : null
    const { date, end } = start ? spanDates(scale, start) : { date: '', end: '' }
    out.push({
      n, column: col && start ? toColumnData(col, board, localDate(start), now) : null, how: howFar(scale, n), date,
      end: knob('spanEnds') ? end : '', start, edge,
    })
  }
  return out
})

/** The spans in view. */
export const spanColumns = computed(() => spanRow.value.filter((span) => !span.edge && span.column))

/** The board the drag reads while spans are open: the regular board with the loaded spans' goals beside it. */
export function withSpans(board: BoardResponse | null): BoardResponse | null {
  const extra = spans.vertical ? spans.board : null
  if (!board || !extra) return board
  return {
    ...board,
    columns: [...board.columns, ...extra.columns],
    progress: { ...extra.progress, ...board.progress },
    ancestors: { ...extra.ancestors, ...board.ancestors },
    children: { ...extra.children, ...board.children },
    child_counts: { ...extra.child_counts, ...board.child_counts },
  }
}

/** A goal of the loaded spans, when the regular board doesn't have it. */
export function spanGoal(id: string): GoalCard | undefined {
  for (const column of spans.board?.columns ?? []) {
    const hit = column.goals.find((goal) => goal.id === id)
    if (hit) return hit
  }
  return undefined
}
