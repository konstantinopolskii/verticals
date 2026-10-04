// The light crossing the column's veil (KK, 4 Oct 2026: "everything ... as smooth as hover on green").
import { queuePostFlushCb } from 'vue'

interface Seen { opacity: number; filter: string; wash: number }
interface Change { row: HTMLElement | null; seen: Seen | null; done: () => void }
const pending: Change[] = []

/** Vue has not patched this card yet. Keep an interrupted crossing's actual look, then start all changed cards
 *  together after the patch. The open goal uses reversible CSS transitions already; only crossings need this. */
export function finishLightMove(card: HTMLElement | null, done: () => void): void {
  const row = card?.querySelector<HTMLElement>(':scope > .goal-card__row') ?? null
  let seen: Seen | null = null
  if (row && card && !card.classList.contains('goal-card--detail-open')
    && (card.dataset.lightMove || card.classList.contains('goal-card--settling'))) {
    const style = getComputedStyle(row)
    seen = { opacity: Number(style.opacity), filter: style.filter, wash: Number(getComputedStyle(row, '::before').opacity) }
  }
  pending.push({ row, seen, done })
  // Still inside Vue's render task, before mutation observers or other microtasks can start an expensive read.
  if (pending.length === 1) queuePostFlushCb(run)
}

async function run(): Promise<void> {
  const changes = pending.splice(0)
  const rows = new Set(changes.map((change) => change.row))
  const animations = document.getAnimations().filter((animation) => {
    // An opening can still be moving these rows. Its programmatic animations keep their own clock.
    if (!(animation instanceof CSSTransition)
      && !(animation instanceof CSSAnimation && animation.animationName.startsWith('goal-light-'))) return false
    const effect = animation.effect as KeyframeEffect
    const target = effect.target
    if (!(target instanceof HTMLElement)) return false
    const row = target.classList.contains('goal-card__children--open')
      ? target.previousElementSibling?.querySelector<HTMLElement>(':scope > .goal-card__row') : target
    return !!row && rows.has(row) && effect.getKeyframes().some((frame) => 'opacity' in frame || 'filter' in frame)
  })
  // Capture the promises before a reversal can cancel them. Reading `finished` after cancellation would wait forever
  // on the animation's next play, and leave the card above the veil.
  const finished = Promise.allSettled(animations.map((animation) => animation.finished))
  // A layout read during Vue's patch can already assign a start time, even though no frame has been presented.
  const fresh = animations.filter((animation) => animation.playState === 'running')
  const crossings = new Map<Element, { from: number; to: number; wash?: number }>()
  for (const animation of fresh) {
    if (!(animation instanceof CSSAnimation) || !animation.animationName.startsWith('goal-light-')) continue
    const effect = animation.effect as KeyframeEffect
    const row = effect.target!
    const frames = effect.getKeyframes()
    const seen = changes.find((change) => change.row === row)?.seen
    if (seen) {
      frames[0] = { ...frames[0], opacity: seen.opacity, filter: seen.filter }
      effect.setKeyframes(frames)
    }
    crossings.set(row, { from: Number(frames[0].opacity), to: Number(frames[frames.length - 1].opacity), wash: seen?.wash })
  }
  for (const animation of fresh) {
    const effect = animation.effect as KeyframeEffect
    const crossing = effect.target && crossings.get(effect.target)
    if (!crossing || effect.pseudoElement !== '::before') continue
    const frames = effect.getKeyframes()
    if (!frames.every((frame) => 'opacity' in frame)) continue
    const from = crossing.wash ?? Number(frames[0].opacity), to = Number(frames[frames.length - 1].opacity)
    const a = crossing.from, b = crossing.to
    // A wash inside a fading row otherwise fades twice: their opacities multiply. Give the wash the remaining share
    // so the colour on screen crosses once, at the same pace as the ink. Twenty intervals keep rounding below a pixel.
    effect.setKeyframes(Array.from({ length: 21 }, (_, i) => {
      const p = i / 20
      const rowOpacity = a * (1 - p) + b * p
      // The layout slider permits zero off-opacity. An invisible row needs no compensation at that endpoint.
      return { offset: p, opacity: rowOpacity ? (from * a * (1 - p) + to * b * p) / rowOpacity : p ? to : from }
    }))
  }
  // WebKit presents newly composited rows late. Hold the starting look while it draws the layers, then start their
  // clocks together. A 170 ms wall-clock cleanup used to expire before the visible fade had finished.
  fresh.forEach((animation) => { animation.pause(); animation.currentTime = 0 })
  await new Promise((resolve) => requestAnimationFrame(resolve))
  await new Promise((resolve) => requestAnimationFrame(resolve))
  fresh.forEach((animation) => { if (animation.playState === 'paused') animation.play() })
  await finished
  changes.forEach((change) => change.done())
}
