// Flow 4's motion (KK's sketches, 28 Sep 2026): "One level in: the clicked step grows in place into the card while the
// card above shrinks into its line and the siblings slide below; the light across the board moves in the same
// movement; about 350 ms, easing out, no bounce. Back up: the same path in reverse, interruptible from where it is.
// Sideways: one movement." The light itself moves by CSS (goalCard.css); this module moves the wide column.
//
// One mechanism for every change of the open family in a column (in, out, sideways, back to a line, another goal,
// closing): read where everything is, change the state, read where everything went, and animate each thing from the
// first place to the second.
// - A goal's row glides there (a transform), so nothing jumps and the ground under the pointer stays solid.
// - Its colour is a shape of its own (the row's ::before, `lib/goalWash.ts`): the shape morphs from its old box to its
//   new one, so the card's colour runs from the step into the card and from the card into the line above. While the
//   column moves, colours are solid and rows are drawn darken, so two shapes of one colour that cross make one shape,
//   never a darker patch (goalCard.css, `body[data-family-moving]`).
// - A title that changes size fades through: its old look fades out on its way in the first 18% of the time, and the
//   new one fades in after it, growing from where the old one was; a word never hops between lines, never two titles.
// - What only was there (the old card's steps, notes and "Add…") fades out where it was by 10%, drawn as a still copy;
//   what only is there now fades in from 20%. A row that would pass through another does the same, and comes back later.
// A change during a movement starts from wherever everything is at that moment: the positions read include the running
// transforms, and the old movement is dropped.

import { shallowRef } from 'vue'
import { placeAllWashes } from './goalWash'
import { curve, reducedMotion } from './motion'

const DURATION = 360 // the opening's time and curve (GoalCard.vue's OPENING, goalDetail.css), one rhythm
const GONE = 0.1 // what only was there is gone by 10% of the time (exits are quicker), so nothing glides over it,
const OUT = 0.2 // and what only is there now fades in from 20%
const TITLE_OUT = 0.18 // a title's old look is gone by 18%, and its new look fades in from there to 50%: never two titles
const TITLE_IN: [number, number] = [0.18, 0.5]
const CROSS_OUT = 0.08 // a row that would cross another is gone by 8% where it was, and back from 45% where it goes,
const CROSS_IN = 0.45 // after the rows gliding past its new place have gone by

let running: Animation[] = []
let ghostLayer: HTMLElement | null = null
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
const PARTS = '.goal-card__add-step, #goal-detail, .goal-facts, .column-now-line, .column-add-row'

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

function layer(column: HTMLElement): HTMLElement {
  if (!ghostLayer) {
    ghostLayer = document.createElement('div')
    ghostLayer.className = 'family-ghosts'
    ghostLayer.setAttribute('aria-hidden', 'true')
  }
  if (ghostLayer.parentElement !== column) column.append(ghostLayer)
  return ghostLayer
}

function place(copy: HTMLElement, rect: DOMRect, column: HTMLElement): void {
  const home = column.getBoundingClientRect()
  copy.style.position = 'absolute'
  copy.style.left = `${rect.left - home.left}px`
  copy.style.top = `${rect.top - home.top}px`
  copy.style.width = `${rect.width}px`
  copy.style.height = `${rect.height}px`
}

function stop(): void {
  for (const animation of running) animation.cancel()
  running = []
  ghostLayer?.replaceChildren()
}

const timing = (extra: KeyframeAnimationOptions = {}): KeyframeAnimationOptions => ({ duration: DURATION, easing: curve('large'), ...extra })

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
export function columnScroller(vertical: string): HTMLElement | null {
  return typeof document === 'undefined' ? null
    : document.querySelector<HTMLElement>(`.pattern-vertical-board__column[data-vertical="${vertical}"] .period-slide:not([data-state="outgoing"])`)
}

/** Run `change` (a change of the open family in the wide column `vertical`) and move the column from how it looked to
 *  how it looks after. `titles` are the goals whose titles change size: the old card and the new one. `anchor`, the new
 *  path's row key, is set when a held drag opens it: that row stays under the hand. */
export async function moveFamily(
  vertical: string,
  titles: readonly (string | null)[],
  change: () => void,
  settled: () => Promise<void>,
  anchor?: string,
): Promise<void> {
  const column = typeof document !== 'undefined'
    ? document.querySelector<HTMLElement>(`.pattern-vertical-board__column--active[data-vertical="${vertical}"]`)
    : null
  const still = reducedMotion()
  if (!column || still) {
    change()
    return
  }
  const view = column.getBoundingClientRect()
  const before = read(column)
  // copies of what may be gone after the change, as it looks now: the rows of the open family and the open card's parts
  const block = column.querySelector('.goal-card--detail-open, .goal-card--path-line')
  for (const [key, entry] of before) {
    if (entry.rect.bottom < view.top || entry.rect.top > view.bottom) continue
    const inBlock = !!block && (key.startsWith('row:') ? !!entry.el.closest('.goal-card__children--family, .goal-card--detail-open, .goal-card--path-line') : !key.startsWith('now') && !key.startsWith('column'))
    const resized = !!entry.id && titles.includes(entry.id)
    if (inBlock || resized) entry.ghost = stillCopy(entry)
  }
  stop()
  moving = true
  familyMovingNow.value = true
  document.body.dataset.familyMoving = vertical // on the body: Vue rewrites the column's classes
  const token = ++moveToken
  change()
  await settled()
  // the parts that arrive have their own opening animations (goalDetail.css); the move draws their arrival instead
  for (const animation of document.getAnimations()) {
    const target = (animation.effect as KeyframeEffect | null)?.target
    if (animation instanceof CSSAnimation && target instanceof Element && column.contains(target)) animation.finish()
  }
  if (anchor) keepInPlace(column, before, `row:${anchor}`)
  placeAllWashes()
  const after = read(column)
  const ghosts = layer(column)
  const fadeOut = (copy: HTMLElement, rect: DOMRect, to?: DOMRect, scale = 1, gone = to ? TITLE_OUT : GONE) => {
    place(copy, rect, column)
    copy.style.transformOrigin = '0 0'
    ghosts.append(copy)
    // gone early, on the same path as what it turns into
    running.push(copy.animate([{ opacity: 1 }, { opacity: 0, offset: gone }, { opacity: 0 }], timing({ easing: 'linear', fill: 'forwards' })))
    if (to) {
      running.push(copy.animate(
        [{ transform: 'none' }, { transform: `translate(${to.left - rect.left}px, ${to.top - rect.top}px) scale(${scale})` }],
        timing({ fill: 'forwards' }),
      ))
    }
  }
  // to whatever it is now, a turned-off row's faded look included
  const fadeIn = (el: HTMLElement, from = OUT) => running.push(el.animate(
    [{ opacity: 0, offset: 0 }, { opacity: 0, offset: from, easing: 'cubic-bezier(.23, 1, .32, 1)' }],
    timing({ easing: 'linear' }),
  ))
  // Nothing solid passes through anything (kk-motion: "Things at rest don't pass through each other, and no text lies on
  // text"). A row whose order would flip against another gliding row fades out where it was and in where it goes: the
  // new card never does, the old card does only when it would cross the new one (sideways), otherwise the one that
  // travels farther does.
  const [oldSun, newSun] = titles
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
      if (was.ghost) fadeOut(was.ghost, was.rect, undefined, 1, CROSS_OUT)
      fadeIn(now.el, CROSS_IN)
      continue
    }
    const dx = was.rect.left - now.rect.left
    const dy = was.rect.top - now.rect.top
    if (Math.abs(dx) > 0.5 || Math.abs(dy) > 0.5) {
      running.push(now.el.animate([{ transform: `translate(${dx}px, ${dy}px)` }, { transform: 'none' }], timing()))
    }
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
    // a title that changes size fades through: the old look leaves toward the new place, the new one grows from the old
    if (was.title && now.title && Math.abs(was.title.size - now.title.size) > 0.5) {
      const scale = was.title.size / now.title.size
      const tx = was.title.rect.left - now.title.rect.left - dx
      const ty = was.title.rect.top - now.title.rect.top - dy
      now.title.el.style.transformOrigin = '0 0'
      running.push(now.title.el.animate([{ transform: `translate(${tx}px, ${ty}px) scale(${scale})` }, { transform: 'none' }], timing()))
      running.push(now.title.el.animate(
        [{ opacity: 0, offset: 0 }, { opacity: 0, offset: TITLE_IN[0] }, { opacity: 1, offset: TITLE_IN[1] }, { opacity: 1 }],
        timing({ easing: 'linear' }),
      ))
      if (was.ghost) {
        const title = was.ghost.querySelector<HTMLElement>('.goal-card__title')
        const titleCopy = title?.cloneNode(true) as HTMLElement | undefined
        if (titleCopy && title) {
          titleCopy.style.margin = '0'
          fadeOut(titleCopy, was.title.rect, now.title.rect, now.title.size / was.title.size)
          // the rest of its old look (its facts line, its box) goes with the old row's copy, minus the title
          title.style.visibility = 'hidden'
        }
      }
    }
  }
  for (const [key, was] of before) {
    if (after.has(key) || !was.ghost) continue
    fadeOut(was.ghost, was.rect)
  }
  // settles when its own animations end (a newer move takes over and settles itself)
  await Promise.all(running.map((animation) => animation.finished.catch(() => undefined)))
  if (token !== moveToken) return
  moving = false
  familyMovingNow.value = false
  delete document.body.dataset.familyMoving
  ghostLayer?.replaceChildren()
  running = []
}
