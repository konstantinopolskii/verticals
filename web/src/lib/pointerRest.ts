/** Whether the pointer rests on what it is over (KK, 4 Oct 2026: a family light that waited a fixed 250 ms after the
 *  pointer entered a card came late and trailed the hand). A hand stopping on a card slows to under REST_PX per
 *  WINDOW_MS a frame or two before it stops; a hand passing over cards on its way elsewhere covers 20 px and more in
 *  that time. One listener for the whole board. */
const WINDOW_MS = 50
const REST_PX = 6

type Sample = { x: number; y: number; t: number }
const samples: Sample[] = []
const waiting = new Set<() => void>()
let tracking = false

function track(): void {
  if (tracking || typeof window === 'undefined') return
  tracking = true
  window.addEventListener('pointermove', (event) => {
    if (event.pointerType === 'touch') return
    samples.push({ x: event.clientX, y: event.clientY, t: performance.now() })
    for (const check of [...waiting]) check()
  }, { capture: true, passive: true })
}

/** How far the pointer went over the last WINDOW_MS: from where it stood then to where it is now. */
function travel(now: number): number {
  while (samples.length > 1 && samples[1]!.t <= now - WINDOW_MS) samples.shift()
  const first = samples[0]
  const last = samples[samples.length - 1]
  return first && last ? Math.hypot(last.x - first.x, last.y - first.y) : 0
}

/** Calls `rested` once the pointer rests: at once when it already does, else as it slows down or stops. Returns the
 *  way to call it off. */
export function whenPointerRests(rested: () => void): () => void {
  track()
  let timer: ReturnType<typeof setTimeout> | null = null
  const cancel = (): void => {
    waiting.delete(check)
    if (timer !== null) clearTimeout(timer)
    timer = null
  }
  function check(): void {
    if (travel(performance.now()) < REST_PX) {
      cancel()
      rested()
      return
    }
    // a pointer that stops sends no more moves: look again once this one has left the window
    if (timer !== null) clearTimeout(timer)
    timer = setTimeout(check, WINDOW_MS + 1)
  }
  waiting.add(check)
  check()
  return cancel
}
