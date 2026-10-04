// The carried box changes what it shows as one movement (KK, 4 Oct 2026, from a mockup: when the box followed a goal,
// its plans "appear out of nowhere"). When the box follows a goal, lets it go or opens the rest (`lib/carriedFilter.ts`),
// what leaves fades out where it stood, what stays slides to its new place and what arrives fades in, in the 200 ms the
// box's height and colour take: the board's own rule for a list that changes (`lib/familyMotion.ts`), at the box's pace.
//
//   · What leaves is a copy, left where it stood while the box lays out the new list; it goes quicker than the rest moves.
//   · A plan leaving where another one lands lies under it: its edge goes with the plan that slides over it, so words never
//     cover words.
//   · What arrives waits for most of what leaves to be gone, and lands with the rest.
//   · The mascot and "N more" / "See all" are things in the box like the plans: new words leave and arrive the same way.
//   · A change that comes while the last one still moves starts from where everything stands.
//   · With reduced motion nothing slides: what leaves and what arrives cross-fade.

import { reducedMotion, timing } from './motion'

const MOVE_MS = 200 // the box's height and colour take as long (carriedFilter.ts `ease`, CarriedGroup.vue)
const LEAVE_MS = 120 // what leaves goes quicker than the rest moves
const ARRIVE_AT_MS = 50 // what arrives waits for most of what leaves to be gone
const STRIPPED = ['id', 'data-goal-id', 'data-row-key', 'data-role', 'data-parent-id'] // a copy is never taken for the thing

type Rect = { top: number; left: number; width: number; height: number; bottom: number }
interface Item { key: string; els: HTMLElement[]; rect: Rect; opacity: number; copies?: HTMLElement[]; wrap?: string }
export interface BoxPicture { items: Map<string, Item> }

/** What the box shows: its plans (a plan's card and its steps), the mascot while it is on, and its last line. */
function itemsOf(box: HTMLElement): Array<[string, HTMLElement[]]> {
  const items: Array<[string, HTMLElement[]]> = []
  for (const card of box.querySelectorAll<HTMLElement>(':scope > [data-section="carried"] > .goal-card[data-goal-id]')) {
    const list = card.nextElementSibling
    items.push([`plan:${card.dataset.goalId}`, list instanceof HTMLElement && list.classList.contains('goal-card__children') ? [card, list] : [card]])
  }
  const mascot = box.querySelector<HTMLElement>(':scope > .carried-gap--on > .carried-gap__mascot')
  if (mascot) items.push([`mascot:${mascot.textContent?.trim() ?? ''}`, [mascot]])
  const more = box.querySelector<HTMLElement>(':scope > [data-role="carried-more"]')
  if (more) items.push([`more:${more.textContent?.trim() ?? ''}`, [more]])
  return items
}

/** Where elements stand in the box, in the box's own px: a lift's scale on the box doesn't count. */
function rectIn(box: HTMLElement, els: HTMLElement[]): Rect {
  const b = box.getBoundingClientRect()
  const k = box.offsetWidth ? b.width / box.offsetWidth : 1
  const rs = els.map((el) => el.getBoundingClientRect()).filter((r) => r.width || r.height)
  if (!rs.length) return { top: 0, left: 0, width: 0, height: 0, bottom: 0 }
  const top = Math.min(...rs.map((r) => r.top)), bottom = Math.max(...rs.map((r) => r.bottom))
  const left = Math.min(...rs.map((r) => r.left)), right = Math.max(...rs.map((r) => r.right))
  return { top: (top - b.top) / k, bottom: (bottom - b.top) / k, left: (left - b.left) / k, width: (right - left) / k, height: (bottom - top) / k }
}

function copyOf(el: HTMLElement): HTMLElement {
  const copy = el.cloneNode(true) as HTMLElement
  for (const node of [copy, ...copy.querySelectorAll<HTMLElement>('*')]) for (const name of STRIPPED) node.removeAttribute(name)
  return copy
}

/** A copy stands in what held the original, so it looks the same: a plan in a stack, the mascot in its room. */
function wrapOf(el: HTMLElement): string {
  return el.classList.contains('goal-card') ? (el.parentElement?.className ?? '')
    : el.classList.contains('carried-gap__mascot') ? (el.parentElement?.className ?? '') : ''
}

const read = (box: HTMLElement, copies: boolean): Map<string, Item> => new Map(itemsOf(box).map(([key, els]) => [key, {
  key, els, rect: rectIn(box, els), opacity: parseFloat(getComputedStyle(els[0]!).opacity) || 0,
  copies: copies ? els.map(copyOf) : undefined, wrap: copies ? wrapOf(els[0]!) : undefined,
}]))

/** Reads the box before a change: where everything stands now, a running movement included, and copies of it. */
export function readBox(box: HTMLElement): BoxPicture {
  return { items: read(box, true) }
}

const slides = new WeakMap<HTMLElement, Animation>() // this module's slide on an element, so the next change can stop it

/** The copies of what leaves, laid over the box (CarriedGroup.vue `.carried-ghosts`); the box holds them while they go. */
function layerOf(box: HTMLElement): HTMLElement {
  let layer = box.querySelector<HTMLElement>(':scope > .carried-ghosts')
  if (!layer) {
    layer = document.createElement('div')
    layer.className = 'carried-ghosts'
    layer.setAttribute('aria-hidden', 'true')
    layer.inert = true
    box.style.position = 'relative' // only while it holds copies: at rest the box lays out as it always has
    box.append(layer)
  }
  return layer
}
function done(box: HTMLElement, layer: HTMLElement, ghost: HTMLElement): void {
  ghost.remove()
  if (layer.childElementCount) return
  layer.remove()
  box.style.removeProperty('position')
}

/** After the change, laid out and measured, before the box's height starts to ease (`grows`: it will get taller). */
export function moveBox(box: HTMLElement, before: BoxPicture, grows: boolean): void {
  // the last change's slides end where they stand: they were read there, and slide on from there
  for (const [, els] of itemsOf(box)) for (const el of els) { slides.get(el)?.cancel(); slides.delete(el) }
  const after = read(box, false)
  const reduced = reducedMotion()
  const stayed = [...after.keys()].filter((key) => before.items.has(key))

  /* What leaves lies under the plans that move over it: the nearest plan above it that sinks takes its top edge down,
     and the nearest one below it that rises takes its bottom edge up, on the same path (familyMotion.ts `curtain`). */
  const curtain = (rect: Rect): Keyframe[] | null => {
    let above: { was: Rect; now: Rect } | null = null
    let below: { was: Rect; now: Rect } | null = null
    for (const key of stayed) {
      if (!key.startsWith('plan:')) continue
      const was = before.items.get(key)!.rect, now = after.get(key)!.rect
      if (was.bottom <= rect.top + 1 && now.bottom > was.bottom + 0.5 && (!above || was.bottom > above.was.bottom)) above = { was, now }
      if (was.top >= rect.bottom - 1 && now.top < was.top - 0.5 && (!below || was.top < below.was.top)) below = { was, now }
    }
    if (!above && !below) return null
    const edge = (v: number) => `${Math.min(rect.height, Math.max(0, v))}px`
    const inset = (top: number, bottom: number) => `inset(${edge(top)} -40px ${edge(bottom)} -40px)`
    return [
      { clipPath: inset(above ? above.was.bottom - rect.top : 0, below ? rect.bottom - below.was.top : 0) },
      { clipPath: inset(above ? above.now.bottom - rect.top : 0, below ? rect.bottom - below.now.top : 0) },
    ]
  }

  for (const item of before.items.values()) {
    if (after.has(item.key) || !item.copies?.length || item.opacity < 0.02 || !item.rect.height) continue
    const layer = layerOf(box)
    const ghost = document.createElement('div')
    ghost.className = `carried-ghost ${item.wrap ?? ''}`.trim()
    Object.assign(ghost.style, { left: `${item.rect.left}px`, top: `${item.rect.top}px`, width: `${item.rect.width}px`, height: `${item.rect.height}px` })
    ghost.append(...item.copies)
    layer.append(ghost)
    const out = ghost.animate([{ opacity: item.opacity }, { opacity: 0 }], timing(LEAVE_MS, 'large', { fill: 'forwards' }))
    const cover = reduced ? null : curtain(item.rect)
    if (cover) ghost.animate(cover, timing(MOVE_MS, 'large', { fill: 'forwards' }))
    out.onfinish = () => done(box, layer, ghost)
    out.oncancel = () => done(box, layer, ghost)
  }

  for (const item of after.values()) {
    const was = before.items.get(item.key)
    if (!was) {
      for (const el of item.els) {
        el.animate([{ opacity: 0 }, { opacity: 1 }], reduced ? timing(LEAVE_MS, 'large', { fill: 'backwards' })
          : timing(MOVE_MS - ARRIVE_AT_MS, 'large', { delay: ARRIVE_AT_MS, fill: 'backwards' }))
      }
      continue
    }
    if (reduced || item.key.startsWith('mascot:')) continue // the mascot stands in its room, which the box's height moves
    // the last line follows the box's bottom edge: the room above it does that when the box gets shorter
    if (item.key.startsWith('more:') && !grows) continue
    const dy = was.rect.top - item.rect.top
    if (Math.abs(dy) < 0.5) continue
    for (const el of item.els) {
      const slide = el.animate([{ transform: `translateY(${dy}px)` }, { transform: 'none' }], timing(MOVE_MS, 'large'))
      slides.set(el, slide)
      slide.onfinish = () => { if (slides.get(el) === slide) slides.delete(el) }
    }
  }
}
