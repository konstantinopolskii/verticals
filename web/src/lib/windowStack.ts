// How the windows over the board stand and move: one in the centre, 720 px; its neighbours at the sides, 200 px of each
// in view, stepped back to 94%; beyond them the rest wait off the screen in the order they opened.
import { curve, reducedMotion, timing } from './motion'
import { stepWindow } from './windows'

const SIDE = 200
const GAP = 24

export interface WindowPlace {
  left: number
  origin: string
  scale: string
  z: number
}

export function windowWidth(room: number): number {
  return Math.min(720, room - 32)
}

/** `offset` is the window's place in the row from the one in the centre. */
export function placeWindow(offset: number, room: number, chatOpen: boolean): WindowPlace {
  const width = windowWidth(room)
  if (offset === 0) return { left: (room - width) / 2, origin: '50% 0', scale: chatOpen ? 'var(--vt-step-back)' : '1', z: 286 }
  const shows = room >= width + 2 * SIDE + 2 * GAP ? SIDE : 0
  const stepped = width * 0.94 + GAP
  const edge = shows ? 0 : GAP
  if (offset < 0) {
    return { left: shows - (-offset - 1) * stepped - edge - width, origin: '100% 0', scale: 'var(--vt-step-side)', z: 285 }
  }
  return { left: room - shows + (offset - 1) * stepped + edge, origin: '0 0', scale: 'var(--vt-step-side)', z: 285 }
}

/** The window grows out of the row or link it was opened from (S3.P2.013). */
export function popOut(el: HTMLElement, from: DOMRect): void {
  if (reducedMotion()) {
    el.animate([{ opacity: 0 }, { opacity: 1 }], timing('fade', 'large'))
    return
  }
  const to = el.getBoundingClientRect()
  const scale = Math.max(0.1, from.width / to.width)
  el.animate([
    { transform: `translate(${from.left - to.left}px, ${from.top - to.top}px) scale(${scale})`, opacity: 0.6 },
    { transform: 'none', opacity: 1 },
  ], { duration: 400, easing: curve('large') })
}

let swiped = 0
let swipeAt = 0
let swipeUsed = false

/** A two-finger swipe moves one window over, unless what is under it scrolls sideways (S3.P3.010, .025). */
export function swipeWindows(event: WheelEvent): void {
  if (Math.abs(event.deltaX) <= Math.abs(event.deltaY)) return
  const body = (event.target as HTMLElement).closest<HTMLElement>('.vt-window__body, .doc-window, .page-window')
  if (body && body.scrollWidth > body.clientWidth) return
  const now = performance.now()
  if (now - swipeAt > 300) {
    swiped = 0
    swipeUsed = false
  }
  swipeAt = now
  if (swipeUsed) return
  swiped += event.deltaX
  if (Math.abs(swiped) < 60) return
  stepWindow(swiped > 0 ? 1 : -1)
  swipeUsed = true
}
