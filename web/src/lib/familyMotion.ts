// Flow 4's motion (KK's sketches, 28 Sep 2026): "One level in: the clicked step grows in place into the card while the
// card above shrinks into its line and the siblings slide below; the light across the board moves in the same
// movement; about 350 ms, easing out, no bounce. Back up: the same path in reverse, interruptible from where it is.
// Sideways: one movement." The light itself moves by CSS (goalCard.css); this module moves the columns: the wide one
// when its family changes, and the two that trade widths when a goal opens in another column.
//
// One mechanism for every change of the open family (in, out, sideways, back to a line, another goal, closing, another
// column): read where everything is, change the state, read where everything went, and animate each thing from the
// first place to the second.
// - A goal's row glides there (a transform), so nothing jumps and the ground under the pointer stays solid.
// - Its colour is a shape of its own (the row's ::before, `lib/goalWash.ts`): the shape morphs from its old box to its
//   new one, so the card's colour runs from the step into the card and from the card into the line above. While the
//   column moves, colours are solid and rows are drawn darken, so two shapes of one colour that cross make one shape,
//   never a darker patch (goalCard.css, `body[data-family-moving]`).
// - A title that changes size, or wraps differently in a column that changes width, fades through: its old look fades
//   out on its way within the first quarter of the time while the new one fades in from 8%, growing from where the old
//   one was; a word never hops between lines, and the two looks never stand at full strength together.
// - What only was there (the old card's steps, notes and "Add…") fades out where it was in 150 ms, drawn as a still
//   copy; what only is there now fades in from a quarter of the time and lands with the rest. A row that would pass
//   through another fades out and comes back later.
// - The column's scroll is part of the same movement (one driver per click: the motion review of 3 Oct 2026, where the
//   scroll ran its own glide and every click played as two to four jerks). The goal the hand pressed stays where it was
//   pressed, then the open goal is seen whole (`lib/columnFit.ts`, Kirill's rule); the scroll is written before the
//   second read, so every row, the column's name and the box's header travel there by the same transform.
// A change during a movement starts from wherever everything is at that moment: the positions and the opacity read
// include the running animations, and what was on its way out keeps fading from where it is.

import { shallowRef } from 'vue'
import { placeAllWashes } from './goalWash'
import { curve, reducedMotion } from './motion'
import { contentTop, familyBlock, fitScroll } from './columnFit'
import { roomFor } from './columnRoom'
import { releaseLifts } from './cardLift'

const DURATION = 360 // the opening's time and curve (GoalCard.vue's OPENING, goalDetail.css), one rhythm
const LEAVE_MS = 150 // what only was there fades out where it is, quicker than what arrives (exits are quicker),
const ARRIVE = 0.25 // and what only is there now fades in from a quarter of the time, landing with everything else
// A title that changes size or wraps differently hands over from its old look to its new one while both travel the same
// path at the same size: the old look is gone within the first quarter, the new one comes in from 8% to 58%, both on the
// large curve (the review's mockup of the column switch). The two never stand at full strength together, and a column
// never shows a frame with no titles at all.
const TITLE_OUT = 0.25
const TITLE_IN: [number, number] = [0.08, 0.5] // from, for
const CROSS_OUT = 0.08 // a row that would cross another is gone by 8% where it was, and back from 45% where it goes,
const CROSS_IN = 0.45 // after the rows gliding past its new place have gone by

let running: Animation[] = []
let moveToken = 0
let moving = false
/** GoalCard.vue's lists skip their own grow and fold while the family moves: the move draws them. */
export function familyMoving(): boolean {
  return moving
}
/** The same, for templates: the open card's parts switch at once while the family moves (their CSS transitions keep a
 *  leaving part in the page for two frames, and the move must read where everything ends up at once). */
export const familyMovingNow = shallowRef(false)

interface Seen {
  id?: string
  el: HTMLElement
  rect: DOMRect
  opacity: number
  title?: { el: HTMLElement; rect: DOMRect; size: number }
  wash?: { top: number; right: number; bottom: number; left: number; opacity: number }
  ghost?: HTMLElement
}

const ROW = '.goal-card[data-goal-id]'
// The open card's parts, and what else stands in the column and moves with its scroll: its name and the carried box's
// header line and "N more" (the box's ground holds rows, so it can't glide by a transform of its own).
const PARTS = '.goal-card__add-step, #goal-detail, .goal-facts, .column-now-line, .column-add-row, '
  + '.pattern-vertical-board__header, .carried-group__head, .carried-group__more'

function ownerOf(el: HTMLElement): string {
  const list = el.closest<HTMLElement>('.goal-card__children')
  const card = el.closest<HTMLElement>(ROW) ?? (list?.previousElementSibling as HTMLElement | null)
  return card?.dataset.goalId ?? 'column'
}

function keyOf(el: HTMLElement): string {
  if (el.matches(ROW)) return `row:${el.dataset.rowKey ?? el.dataset.goalId}` // one goal may stand twice in a column
  if (el.matches('.goal-card__add-step')) return `add:${ownerOf(el)}`
  if (el.id === 'goal-detail') return `notes:${ownerOf(el)}`
  if (el.matches('.goal-facts')) return `facts:${ownerOf(el)}`
  if (el.matches('.pattern-vertical-board__header')) return 'header'
  if (el.matches('.carried-group__head')) return 'carried-head'
  if (el.matches('.carried-group__more')) return 'carried-more'
  return el.matches('.column-now-line') ? 'now' : 'column-add'
}

/** The moving part of a thing: a goal's row (its card box stays put and holds no colour), or the part itself. */
function mover(el: HTMLElement): HTMLElement {
  return el.matches(ROW) ? (el.querySelector<HTMLElement>(':scope > .goal-card__row') ?? el) : el
}

function washOf(row: HTMLElement): Seen['wash'] {
  const s = getComputedStyle(row, '::before')
  return {
    top: parseFloat(s.top) || 0,
    right: parseFloat(s.right) || 0,
    bottom: parseFloat(s.bottom) || 0,
    left: parseFloat(s.left) || 0,
    opacity: parseFloat(s.opacity) || 0,
  }
}

function read(column: HTMLElement): Map<string, Seen> {
  const seen = new Map<string, Seen>()
  for (const el of column.querySelectorAll<HTMLElement>(`${ROW}, ${PARTS}`)) {
    if (el.closest('[data-state="outgoing"], .family-ghosts')) continue
    const target = mover(el)
    const rect = target.getBoundingClientRect()
    if (rect.width === 0 && rect.height === 0) continue
    const key = keyOf(el)
    if (seen.has(key)) continue
    const entry: Seen = { id: el.dataset.goalId, el: target, rect, opacity: parseFloat(getComputedStyle(target).opacity) || 0 }
    if (el.matches(ROW)) {
      const title = target.querySelector<HTMLElement>(':scope .goal-card__title')
      if (title) entry.title = { el: title, rect: title.getBoundingClientRect(), size: parseFloat(getComputedStyle(title).fontSize) }
      entry.wash = washOf(target)
    }
    seen.set(key, entry)
  }
  return seen
}

/* A still copy of something as it looks now, for fading it out where it was after it is gone from the page. Its look is
   written onto it, since the rules that drew it depend on where it stood; a row's colour becomes a plain box. */
const LOOK = [
  'display', 'flex-direction', 'flex-wrap', 'flex-grow', 'flex-shrink', 'flex-basis', 'align-items', 'align-self',
  'justify-content', 'gap', 'row-gap', 'column-gap', 'box-sizing', 'width', 'height', 'min-width', 'min-height',
  'padding-top', 'padding-right', 'padding-bottom', 'padding-left', 'margin-top', 'margin-right', 'margin-bottom',
  'margin-left', 'border-top-width', 'border-right-width', 'border-bottom-width', 'border-left-width', 'border-top-style',
  'border-right-style', 'border-bottom-style', 'border-left-style', 'border-top-color', 'border-right-color',
  'border-bottom-color', 'border-left-color', 'border-radius', 'background-color', 'background-image', 'box-shadow',
  'color', 'font-family', 'font-size', 'font-weight', 'font-style', 'font-variant-numeric', 'line-height',
  'letter-spacing', 'text-align', 'text-decoration-line', 'text-decoration-color', 'text-decoration-thickness',
  'white-space', 'word-break', 'overflow-wrap', 'opacity', 'visibility', 'position', 'top', 'right', 'bottom', 'left',
  'vertical-align', 'fill', 'stroke', 'filter', 'overflow',
]
function copyLook(from: Element, to: Element): void {
  const look = getComputedStyle(from)
  const style = (to as HTMLElement).style
  if (!style) return
  for (const property of LOOK) style.setProperty(property, look.getPropertyValue(property))
  for (let i = 0; i < from.children.length && i < to.children.length; i++) copyLook(from.children[i], to.children[i])
}
function stillCopy(entry: Seen): HTMLElement {
  const copy = entry.el.cloneNode(true) as HTMLElement
  copy.removeAttribute('id')
  for (const el of copy.querySelectorAll('[id]')) el.removeAttribute('id')
  copyLook(entry.el, copy)
  if (entry.wash && entry.wash.opacity > 0.01) {
    const s = getComputedStyle(entry.el, '::before')
    const shape = document.createElement('div')
    shape.style.cssText = `position:absolute;z-index:-1;top:${entry.wash.top}px;right:${entry.wash.right}px;`
      + `bottom:${entry.wash.bottom}px;left:${entry.wash.left}px;border-radius:${s.borderRadius};`
      + `background:${s.backgroundImage !== 'none' ? `${s.backgroundImage}, ` : ''}${s.backgroundColor};opacity:${entry.wash.opacity}`
    copy.style.isolation = 'isolate'
    copy.prepend(shape)
  }
  for (const el of [copy, ...copy.querySelectorAll<HTMLElement>('*')]) {
    el.style.animation = 'none' // a copy keeps its look: no opening of its own
    el.style.transition = 'none'
  }
  copy.setAttribute('aria-hidden', 'true')
  copy.style.pointerEvents = 'none'
  copy.style.transform = 'none'
  copy.style.margin = '0'
  return copy
}

/** Each moving column draws its copies on a layer of its own, clipped with the column. */
const layers = new Map<HTMLElement, HTMLElement>()
function layer(column: HTMLElement): HTMLElement {
  let ghosts = layers.get(column)
  if (!ghosts) {
    ghosts = document.createElement('div')
    ghosts.className = 'family-ghosts'
    ghosts.setAttribute('aria-hidden', 'true')
    layers.set(column, ghosts)
  }
  if (ghosts.parentElement !== column) column.append(ghosts)
  return ghosts
}
function clearLayers(): void {
  for (const [column, ghosts] of layers) {
    ghosts.replaceChildren()
    if (!column.isConnected) layers.delete(column)
  }
}

function place(copy: HTMLElement, rect: DOMRect, column: HTMLElement): void {
  const home = column.getBoundingClientRect()
  copy.style.position = 'absolute'
  copy.style.left = `${rect.left - home.left}px`
  copy.style.top = `${rect.top - home.top}px`
  copy.style.width = `${rect.width}px`
  copy.style.height = `${rect.height}px`
}

const timing = (extra: KeyframeAnimationOptions = {}): KeyframeAnimationOptions => ({ duration: DURATION, easing: curve('large'), ...extra })

/** Drop the running move. The copies still on their way out keep their look and fade from there; returns those fades. */
function stop(): Animation[] {
  unwiden()
  const leaving = new Set<Element>([...layers.values()].flatMap((ghosts) => [...ghosts.children]))
  for (const animation of running) {
    const target = (animation.effect as KeyframeEffect | null)?.target
    if (target && leaving.has(target)) {
      try { animation.commitStyles() } catch { leaving.delete(target) }
    }
    animation.cancel()
  }
  running = []
  const fades: Animation[] = []
  for (const copy of leaving) {
    const from = parseFloat((copy as HTMLElement).style.opacity || '1')
    if (from < 0.02) { copy.remove(); continue }
    fades.push(copy.animate([{ opacity: from }, { opacity: 0 }], { duration: LEAVE_MS, easing: curve('large'), fill: 'forwards' }))
  }
  return fades
}

/** Where the hand last pressed: the goal it pressed is the one a move holds where it was. */
let press: { x: number; y: number; at: number } | null = null
if (typeof document !== 'undefined') {
  document.addEventListener('pointerdown', (event) => { press = { x: event.clientX, y: event.clientY, at: performance.now() } }, { capture: true, passive: true })
}

/** A row a move holds where it stands, by its place in its column's window as laid out (a hover lift doesn't count). */
interface Held { key: string; offset: number }
/** Where `row` stands in its column's window, as laid out. */
function windowOffset(row: HTMLElement): number | null {
  const scroller = row.closest<HTMLElement>('.period-slide')
  return scroller ? contentTop(row, scroller) - scroller.scrollTop : null
}
/** The row of goal `id` that a move holds where it stands: the one the hand just pressed, or else the first one in view. */
function heldRow(column: HTMLElement, id: string | null | undefined): Held | null {
  if (!id) return null
  const view = column.getBoundingClientRect()
  const rows = [...column.querySelectorAll<HTMLElement>(`${ROW}[data-goal-id="${CSS.escape(id)}"]`)]
    .filter((el) => !el.closest('[data-state="outgoing"], .family-ghosts'))
  const box = (el: HTMLElement) => mover(el).getBoundingClientRect()
  const hand = press && performance.now() - press.at < 2000 ? press : null
  const under = hand ? rows.find((el) => {
    const r = box(el)
    return hand.x >= r.left && hand.x <= r.right && hand.y >= r.top && hand.y <= r.bottom
  }) : undefined
  const pick = under ?? rows.find((el) => { const r = box(el); return r.bottom > view.top && r.top < view.bottom })
  const offset = pick ? windowOffset(pick) : null
  return pick && offset !== null ? { key: keyOf(pick), offset } : null
}

/** Land the column after a change, before the move reads where everything went: the held goal where it stood, as far as
 *  the column can scroll, then the open goal seen whole (`lib/columnFit.ts`), with room after the last card when it
 *  stands near the end (`lib/columnRoom.ts`). */
function land(vertical: string, column: HTMLElement, held: Held | null): void {
  const scroller = columnScroller(vertical)
  if (!scroller) return
  let to = scroller.scrollTop
  const row = held ? rowByKey(column, held.key) : undefined
  const offset = row ? windowOffset(row) : null
  if (held && offset !== null) to += offset - held.offset
  const detail = scroller.querySelector<HTMLElement>('#goal-detail')
  const block = detail ? familyBlock(detail) : null
  to = block
    ? fitScroll(scroller, contentTop(block.card, scroller), contentTop(block.list, scroller) + block.list.offsetHeight, to)
    : Math.max(0, to)
  const body = scroller.querySelector<HTMLElement>(':scope > .pattern-vertical-board__body')
  if (body && block) roomFor(scroller, body, to)
  if (Math.abs(scroller.scrollTop - to) > 0.5) scroller.scrollTop = to
}

/* While a drag is held over the board, the goal under the hand stays under the hand (the brief: "While dragging, the
   goal under the hand stays under the hand"): when its column widens or its family moves, the column scrolls so its row
   stands where it stood, as far as the column can scroll. */
function rowByKey(column: HTMLElement, key: string): HTMLElement | undefined {
  return [...column.querySelectorAll<HTMLElement>(ROW)]
    .find((el) => keyOf(el) === key && !el.closest('[data-state="outgoing"], .family-ghosts'))
}
function scrollTo(column: HTMLElement, row: HTMLElement, top: number): void {
  let scroller = row.parentElement
  while (scroller && column.contains(scroller) && !/auto|scroll/.test(getComputedStyle(scroller).overflowY)) scroller = scroller.parentElement
  if (scroller && column.contains(scroller)) scroller.scrollTop += mover(row).getBoundingClientRect().top - top
}
function keepInPlace(column: HTMLElement, before: Map<string, Seen>, key: string): void {
  const was = before.get(key)
  const row = rowByKey(column, key)
  if (was && row) scrollTo(column, row, was.rect.top)
}
/** Pin `row` where it stands now; call the result once a change of layout is drawn (a column widening under a held drag). */
export function pinRow(row: HTMLElement): () => void {
  const column = row.closest<HTMLElement>('[data-vertical]')
  const key = keyOf(row)
  const top = mover(row).getBoundingClientRect().top
  return () => {
    const home = column?.isConnected ? column : null
    const now = home ? rowByKey(home, key) : undefined
    if (home && now) scrollTo(home, now, top)
  }
}

/** The element that scrolls `vertical`'s column: its current period's slide. */
function columnScroller(vertical: string): HTMLElement | null {
  return typeof document === 'undefined' ? null
    : document.querySelector<HTMLElement>(`.pattern-vertical-board__column[data-vertical="${vertical}"] .period-slide:not([data-state="outgoing"])`)
}

/** Where a column stands: the rows in its window, each with its place there, `anchor` first if it's there, then from
 *  the top edge down, and its scroll. */
export interface ColumnPlace { scroller: HTMLElement; rows: { key: string; offset: number }[]; scrollTop: number; anchored: boolean }

export function columnPlace(vertical: string, anchor?: string): ColumnPlace | null {
  const scroller = columnScroller(vertical)
  if (!scroller) return null
  const rows: ColumnPlace['rows'] = []
  for (const row of scroller.querySelectorAll<HTMLElement>('.goal-card[data-row-key]')) {
    const offset = contentTop(row, scroller) - scroller.scrollTop
    if (offset + row.offsetHeight > 0 && offset < scroller.clientHeight) rows.push({ key: row.dataset.rowKey!, offset })
  }
  const at = rows.findIndex((row) => row.key === anchor)
  if (at > 0) rows.unshift(...rows.splice(at, 1))
  return { scroller, rows, scrollTop: scroller.scrollTop, anchored: at >= 0 }
}

/** Scroll the column back to `place`: its first row where it stood, even when the cards changed size with the column's
 *  width; the next one if it is gone; the old scroll if all are. Without an anchor, a column that was at its top goes
 *  back to its top. */
export function scrollBack(place: ColumnPlace): void {
  const { scroller } = place
  if (!scroller.isConnected) return
  if (place.scrollTop === 0 && !place.anchored) { scroller.scrollTop = 0; return }
  for (const { key, offset } of place.rows) {
    const row = scroller.querySelector<HTMLElement>(`.goal-card[data-row-key="${CSS.escape(key)}"]`)
    if (row) { scroller.scrollTop = contentTop(row, scroller) - offset; return }
  }
  scroller.scrollTop = place.scrollTop
}

/** A column whose rows a move redraws, as it was before the change. */
interface Lane { column: HTMLElement; vertical: string; box: DOMRect; before: Map<string, Seen> }

const ROOM = 8 // a column's clip reaches 8 px past its sides, room for a lifted card (Column.vue)
const FRAME = 1000 / 60

/** The board's columns, in order. */
function boardColumns(column: HTMLElement): HTMLElement[] {
  return [...(column.parentElement?.children ?? [])]
    .filter((el): el is HTMLElement => el instanceof HTMLElement && el.classList.contains('pattern-vertical-board__column'))
}

function columnOf(vertical: string): HTMLElement | null {
  return typeof document === 'undefined' ? null
    : document.querySelector<HTMLElement>(`.pattern-vertical-board__column[data-vertical="${vertical}"]`)
}

/** Run `change` (a change of the open family in the wide column `vertical`) and move the column from how it looked to
 *  how it looks after. `titles` are the goals whose titles change size: the old card and the new one. `anchor`, the new
 *  path's row key, is set when a held drag opens it: that row stays under the hand. */
export function moveFamily(
  vertical: string,
  titles: readonly (string | null)[],
  change: () => void,
  settled: () => Promise<void>,
  anchor?: string,
): Promise<void> {
  const column = typeof document !== 'undefined'
    ? document.querySelector<HTMLElement>(`.pattern-vertical-board__column--active[data-vertical="${vertical}"]`)
    : null
  if (!column || reducedMotion()) {
    change()
    return Promise.resolve()
  }
  return move({ lead: column, lanes: [column], titles, change, settled, anchor, reflow: false })
}

/** Run `change`, which opens a goal in `vertical`'s column while another column is the wide one (or none is), and move
 *  the board in one movement (the motion review of 3 Oct 2026, where the widths and the type size switched in one frame
 *  and the card then assembled in three steps): the two columns trade widths, their rows glide to where they stand and
 *  their titles fade through from one size to the other, the clicked goal stays where it was clicked, and the columns
 *  between them slide along. With no wide column before, every column changes width, so every one is redrawn. */
export function moveColumns(
  vertical: string,
  titles: readonly (string | null)[],
  change: () => void,
  settled: () => Promise<void>,
): Promise<void> {
  const lead = columnOf(vertical)
  if (!lead || reducedMotion()) {
    change()
    return Promise.resolve()
  }
  const columns = boardColumns(lead)
  const wide = columns.find((column) => column.classList.contains('pattern-vertical-board__column--active'))
  const openIn = document.getElementById('goal-detail')?.closest<HTMLElement>('.pattern-vertical-board__column') ?? null
  const lanes = wide
    ? [lead, wide, openIn].filter((column, i, all): column is HTMLElement => !!column && all.indexOf(column) === i)
    : [lead, ...columns.filter((column) => column !== lead)]
  return move({ lead, lanes, titles, change, settled, reflow: true })
}

/** One movement: read where everything is, change the state, land the lead column's scroll, read where everything went,
 *  and animate each thing from the first place to the second. */
async function move(plan: {
  lead: HTMLElement
  lanes: HTMLElement[]
  titles: readonly (string | null)[]
  change: () => void
  settled: () => Promise<void>
  anchor?: string
  /** The lanes change width: any row in them may change its look, so each one in view gets a copy to fade through. */
  reflow: boolean
}): Promise<void> {
  const { lead, titles, change, settled, anchor } = plan
  const [, newSun] = titles
  const columns = boardColumns(lead)
  const boxes = new Map(columns.map((column) => [column, column.getBoundingClientRect()]))
  const held = anchor ? null : heldRow(lead, newSun)
  const lanes: Lane[] = plan.lanes.map((column) => ({
    column, vertical: column.dataset.vertical ?? '', box: boxes.get(column) ?? column.getBoundingClientRect(), before: read(column),
  }))
  // copies of what may be gone after the change, or look different, as it looks now: the rows of the open family, the
  // open card's parts, the titles that change size, and in a column that changes width, every row in view
  for (const lane of lanes) {
    const view = lane.box
    const block = lane.column.querySelector('.goal-card--detail-open, .goal-card--path-line')
    for (const [key, entry] of lane.before) {
      if (entry.rect.bottom < view.top || entry.rect.top > view.bottom) continue
      const inBlock = !!block && (key.startsWith('row:') ? !!entry.el.closest('.goal-card__children--family, .goal-card--detail-open, .goal-card--path-line') : !key.startsWith('now') && !key.startsWith('column'))
      const resized = !!entry.id && titles.includes(entry.id)
      if (inBlock || resized || (plan.reflow && key.startsWith('row:'))) entry.ghost = stillCopy(entry)
    }
  }
  const leaving = stop()
  // the lifts end inside this movement: the rows were read lifted and land at rest (lib/cardLift.ts)
  releaseLifts(press && performance.now() - press.at < 2000 ? { x: press.x, y: press.y } : null)
  moving = true
  familyMovingNow.value = true
  for (const column of columns) delete column.dataset.familyLane
  for (const lane of lanes) lane.column.dataset.familyLane = '' // on the column itself: Vue rewrites its classes
  document.body.dataset.familyMoving = lanes.map((lane) => lane.vertical).join(' ')
  const token = ++moveToken
  running.push(...leaving)
  change()
  await settled()
  // the parts that arrive have their own opening animations (goalDetail.css); the move draws their arrival instead
  for (const animation of document.getAnimations()) {
    const target = (animation.effect as KeyframeEffect | null)?.target
    if (animation instanceof CSSAnimation && target instanceof Element && lanes.some((lane) => lane.column.contains(target))) animation.finish()
  }
  if (anchor) keepInPlace(lead, lanes[0].before, `row:${anchor}`)
  else land(lead.dataset.vertical ?? '', lead, held)
  placeAllWashes()
  for (const lane of lanes) {
    const now = lane.column.getBoundingClientRect()
    const slide = columnScroller(lane.vertical)
    if (slide) widen(slide, Math.max(0, now.left - lane.box.left), Math.max(0, lane.box.right - now.right))
  }
  // A lane's box goes from where it stood to where it stands, its rows inside it; a column that only moves slides along.
  for (const column of columns) {
    const was = boxes.get(column)
    if (!was || !column.isConnected) continue
    const now = column.getBoundingClientRect()
    if (Math.abs(was.left - now.left) < 0.5 && Math.abs(was.width - now.width) < 0.5) continue
    if (column.dataset.familyLane !== undefined) {
      // A clip-path runs on the main thread and the rows' transforms on the compositor, which shows them a frame sooner:
      // at the move's fast start a frame is up to 48 px, and a column's name slid past the clip's edge and came out cut
      // (filmed frame by frame, 4 Oct 2026). The clip starts a frame early, so on screen it meets what it reveals.
      running.push(column.animate(
        [{ clipPath: `inset(0px ${now.right - was.right - ROOM}px 0px ${was.left - now.left - ROOM}px)` },
          { clipPath: `inset(0px ${-ROOM}px 0px ${-ROOM}px)` }],
        timing({ delay: -FRAME }),
      ))
    } else {
      running.push(column.animate([{ transform: `translateX(${was.left - now.left}px)` }, { transform: 'none' }], timing()))
    }
  }
  for (const lane of lanes) drawLane(lane, titles, plan.reflow)
  // settles when its own animations end (a newer move takes over and settles itself)
  await Promise.all(running.map((animation) => animation.finished.catch(() => undefined)))
  if (token !== moveToken) return
  moving = false
  familyMovingNow.value = false
  delete document.body.dataset.familyMoving
  for (const column of columns) delete column.dataset.familyLane
  unwiden()
  clearLayers()
  running = []
}

/* A scroll box clips both ways, so a column that narrows can't show its rows' old, wider look: a colour shape morphing
   from the wide card was cut at the narrow edge. While the move runs, the column's slide paints `left` and `right` px
   further out, its content box staying where it is (nothing is laid out again) and its name with it. */
let widened: Array<() => void> = []
function widen(slide: HTMLElement, left: number, right: number): void {
  if (left < 0.5 && right < 0.5) return
  const look = getComputedStyle(slide)
  const px = (v: string) => parseFloat(v) || 0
  const was = slide.style.cssText
  slide.style.width = `${px(look.width) + left + right}px`
  slide.style.marginLeft = `${px(look.marginLeft) - left}px`
  slide.style.marginRight = `${px(look.marginRight) - right}px`
  slide.style.paddingLeft = `${px(look.paddingLeft) + left}px`
  slide.style.paddingRight = `${px(look.paddingRight) + right}px`
  const header = slide.querySelector<HTMLElement>(':scope > .pattern-vertical-board__header')
  const headerWas = header?.style.cssText ?? ''
  if (header) {
    const h = getComputedStyle(header)
    header.style.left = `${px(h.left) + left}px`
    header.style.right = `${px(h.right) + right}px`
  }
  widened.push(() => {
    slide.style.cssText = was
    if (header) header.style.cssText = headerWas
  })
}
function unwiden(): void {
  widened.forEach((undo) => undo())
  widened = []
}

/** Animate one lane from how it looked (`lane.before`) to how it looks now. */
function drawLane(lane: Lane, titles: readonly (string | null)[], reflow: boolean): void {
  const { column, before } = lane
  const [oldSun, newSun] = titles
  const after = read(column)
  // a goal whose row changed its key (a carried plan, "id~" in the box, opens as itself) is still the same goal
  for (const [key, now] of after) {
    if (before.has(key) || !now.id || !key.startsWith('row:')) continue
    const same = [...before].filter(([k, was]) => was.id === now.id && !after.has(k))
    if (same.length === 1) {
      before.delete(same[0][0])
      before.set(key, same[0][1])
    }
  }
  const ghosts = layer(column)
  const fadeOut = (copy: HTMLElement, rect: DOMRect, to?: DOMRect, scale = 1) => {
    place(copy, rect, column)
    copy.style.transformOrigin = '0 0'
    ghosts.append(copy)
    if (!to) {
      // gone where it was, quicker than the rest moves, and covered by the rows that move over it
      running.push(copy.animate([{ opacity: 1 }, { opacity: 0 }], { duration: LEAVE_MS, easing: curve('large'), fill: 'forwards' }))
      const cover = curtain(rect)
      if (cover) running.push(copy.animate(cover, timing({ fill: 'forwards' })))
      return
    }
    // a title's old look: gone early, on the same path as the look it turns into
    running.push(copy.animate([{ opacity: 1 }, { opacity: 0 }], { duration: DURATION * TITLE_OUT, easing: curve('large'), fill: 'forwards' }))
    running.push(copy.animate(
      [{ transform: 'none' }, { transform: `translate(${to.left - rect.left}px, ${to.top - rect.top}px) scale(${scale})` }],
      timing({ fill: 'forwards' }),
    ))
  }
  // a row that crosses another: gone early where it was
  const crossOut = (copy: HTMLElement, rect: DOMRect) => {
    place(copy, rect, column)
    ghosts.append(copy)
    running.push(copy.animate([{ opacity: 1 }, { opacity: 0, offset: CROSS_OUT }, { opacity: 0 }], timing({ easing: 'linear', fill: 'forwards' })))
  }
  // to whatever it is now, a turned-off row's faded look included
  const fadeIn = (el: HTMLElement, from = ARRIVE) => running.push(el.animate(
    [{ opacity: 0, offset: 0 }, { opacity: 0, offset: from, easing: curve('large') }],
    timing({ easing: 'linear' }),
  ))
  // Nothing solid passes through anything (kk-motion: "Things at rest don't pass through each other, and no text lies on
  // text"). A row whose order would flip against another gliding row fades out where it was and in where it goes: the
  // new card never does, the old card does only when it would cross the new one (sideways), otherwise the one that
  // travels farther does.
  const gliders = [...after.keys()].filter((key) => key.startsWith('row:') && before.has(key))
  const faders = new Set<string>()
  const top = (m: Map<string, Seen>, key: string) => m.get(key)!.rect.top
  const rank = (key: string) => {
    const id = after.get(key)!.id
    return id === newSun ? 3 : id === oldSun ? 2 : 1
  }
  for (let changed = true; changed;) {
    changed = false
    const live = gliders.filter((key) => !faders.has(key))
    for (let i = 0; i < live.length && !changed; i++) {
      for (let j = i + 1; j < live.length && !changed; j++) {
        const a = live[i]
        const b = live[j]
        if (Math.sign(top(before, a) - top(before, b)) * Math.sign(top(after, a) - top(after, b)) >= 0) continue
        const far = (key: string) => Math.abs(top(before, key) - top(after, key))
        const fade = rank(a) !== rank(b) ? (rank(a) < rank(b) ? a : b) : (far(a) >= far(b) ? a : b)
        faders.add(fade)
        changed = true
      }
    }
  }
  // What leaves lies under the rows that move over it, never text on text: the nearest row below it that rises takes its
  // bottom edge up with it, and the nearest row above it that sinks takes its top edge down, on the same path.
  const curtain = (rect: DOMRect): Keyframe[] | null => {
    let below: { was: DOMRect; now: DOMRect } | null = null
    let above: { was: DOMRect; now: DOMRect } | null = null
    for (const key of gliders) {
      const was = before.get(key)!.rect
      const now = after.get(key)!.rect
      if (was.top >= rect.bottom - 1 && now.top < was.top - 0.5 && (!below || was.top < below.was.top)) below = { was, now }
      if (was.bottom <= rect.top + 1 && now.bottom > was.bottom + 0.5 && (!above || was.bottom > above.was.bottom)) above = { was, now }
    }
    if (!below && !above) return null
    const edge = (v: number) => `${Math.min(rect.height, Math.max(0, v))}px`
    const inset = (top: number, bottom: number) => `inset(${edge(top)} -40px ${edge(bottom)} -40px)`
    return [
      { clipPath: inset(above ? above.was.bottom - rect.top : 0, below ? rect.bottom - below.was.top : 0) },
      { clipPath: inset(above ? above.now.bottom - rect.top : 0, below ? rect.bottom - below.now.top : 0) },
    ]
  }
  // the new card's own parts (its steps, "Add…", notes) travel with it: they arrive inside the card, not before it
  const sunKey = [...after.keys()].find((key) => after.get(key)!.id === newSun && before.has(key))
  const sunMove = sunKey ? {
    dx: before.get(sunKey)!.rect.left - after.get(sunKey)!.rect.left,
    dy: before.get(sunKey)!.rect.top - after.get(sunKey)!.rect.top,
  } : null
  // ...and show only inside the card's colour while it grows: its list is clipped to the colour's bottom edge
  if (sunKey) {
    const was = before.get(sunKey)!
    const now = after.get(sunKey)!
    const list = now.el.parentElement?.nextElementSibling as HTMLElement | null
    if (list?.classList.contains('goal-card__children--open') && was.wash && now.wash) {
      const box = list.getBoundingClientRect()
      const edge = (rect: DOMRect, wash: NonNullable<Seen['wash']>) => rect.bottom - wash.bottom - box.top
      const cut = (bottom: number) => `inset(-40px -40px ${Math.max(0, box.height - bottom)}px -40px)`
      running.push(list.animate([{ clipPath: cut(edge(was.rect, was.wash)) }, { clipPath: cut(edge(now.rect, now.wash)) }], timing()))
    }
  }
  const inNewCard = (el: HTMLElement) => {
    const list = el.closest<HTMLElement>('.goal-card__children--open')
    return !!list && (list.previousElementSibling as HTMLElement | null)?.dataset.goalId === newSun
  }
  for (const [key, now] of after) {
    const was = before.get(key)
    if (!was) {
      fadeIn(now.el) // arrives: fades in where it is, after what left has gone
      if (sunMove && (Math.abs(sunMove.dy) > 0.5 || Math.abs(sunMove.dx) > 0.5) && inNewCard(now.el)) {
        running.push(now.el.animate([{ transform: `translate(${sunMove.dx}px, ${sunMove.dy}px)` }, { transform: 'none' }], timing()))
      }
      continue
    }
    if (faders.has(key)) {
      if (was.ghost) crossOut(was.ghost, was.rect)
      fadeIn(now.el, CROSS_IN)
      continue
    }
    const dx = was.rect.left - now.rect.left
    const dy = was.rect.top - now.rect.top
    if (Math.abs(dx) > 0.5 || Math.abs(dy) > 0.5) {
      running.push(now.el.animate([{ transform: `translate(${dx}px, ${dy}px)` }, { transform: 'none' }], timing()))
    }
    // caught halfway in by this move, it goes on from the opacity it had
    if (was.opacity < now.opacity - 0.02) running.push(now.el.animate([{ opacity: was.opacity }, { opacity: now.opacity }], timing()))
    if (was.wash && now.wash) {
      const a = was.wash
      const b = now.wash
      const moved = [a.top - b.top, a.right - b.right, a.bottom - b.bottom, a.left - b.left].some((d) => Math.abs(d) > 0.5)
      // from where the shape was on screen, in the row's box as it now stands (the row itself glides from its old place)
      const from = {
        top: `${a.top + (was.rect.top - now.rect.top) - dy}px`,
        right: `${a.right - (was.rect.right - now.rect.right) + dx}px`,
        bottom: `${a.bottom - (was.rect.bottom - now.rect.bottom) + dy}px`,
        left: `${a.left + (was.rect.left - now.rect.left) - dx}px`,
      }
      if (moved || Math.abs(was.rect.height - now.rect.height) > 0.5 || Math.abs(was.rect.width - now.rect.width) > 0.5) {
        running.push(now.el.animate(
          [{ ...from, opacity: a.opacity }, { top: `${b.top}px`, right: `${b.right}px`, bottom: `${b.bottom}px`, left: `${b.left}px` }],
          timing({ pseudoElement: '::before' }),
        ))
      } else if (Math.abs(a.opacity - b.opacity) > 0.01) {
        running.push(now.el.animate([{ opacity: a.opacity, offset: 0 }], timing({ pseudoElement: '::before' })))
      }
    }
    // A title that changes size fades through: the old look leaves toward the new place, the new one grows from the old.
    // In a column that changes width, a title that wraps differently fades through the same way: no word hops lines.
    const resized = !!was.title && !!now.title && (Math.abs(was.title.size - now.title.size) > 0.5 || (reflow
      && (Math.abs(was.title.rect.width - now.title.rect.width) > 1 || Math.abs(was.title.rect.height - now.title.rect.height) > 1)))
    if (resized && was.title && now.title) {
      const scale = was.title.size / now.title.size
      const tx = was.title.rect.left - now.title.rect.left - dx
      const ty = was.title.rect.top - now.title.rect.top - dy
      now.title.el.style.transformOrigin = '0 0'
      running.push(now.title.el.animate([{ transform: `translate(${tx}px, ${ty}px) scale(${scale})` }, { transform: 'none' }], timing()))
      const title = was.ghost?.querySelector<HTMLElement>('.goal-card__title')
      const titleCopy = title?.cloneNode(true) as HTMLElement | undefined
      if (titleCopy && title) {
        running.push(now.title.el.animate([{ opacity: 0 }, { opacity: 1 }], {
          delay: DURATION * TITLE_IN[0], duration: DURATION * TITLE_IN[1], easing: curve('large'), fill: 'backwards',
        }))
        titleCopy.style.margin = '0'
        fadeOut(titleCopy, was.title.rect, now.title.rect, now.title.size / was.title.size)
        // the rest of its old look (its facts line, its box) goes with the old row's copy, minus the title
        title.style.visibility = 'hidden'
      }
    }
  }
  for (const [key, was] of before) {
    if (after.has(key) || !was.ghost) continue
    fadeOut(was.ghost, was.rect)
  }
}
