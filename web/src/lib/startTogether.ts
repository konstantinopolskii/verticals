// Starting the many animations of one change together, once the change is on screen (lib/familyMotion.ts).

/* A move's clock starts once its first frame is on screen. That frame lays out and draws the changed board, and an
   engine that makes a moving thing's layer only when it starts to move (the system WebKit) took 130 ms over it when a
   goal opened in another column: the clock had run most of the move by the time the frame came out, so the goal showed
   up 92% of the way, after frames with rows missing (filmed frame by frame, 4 Oct 2026). Everything the change started
   (the move's animations, the light's and the lifts' transitions) is held at its first frame by a delay, which the
   engine draws itself; what moves gets its layer in that frame; and on the next frame the clocks start together. */
export async function startTogether(): Promise<void> {
  const HOLD = 10000
  const held = document.getAnimations().filter((animation) => animation.playState === 'running' && animation.startTime === null)
    .map((animation) => {
      const effect = animation.effect as KeyframeEffect
      const { delay = 0, fill = 'auto' } = effect.getTiming()
      effect.updateTiming({ delay: delay + HOLD, fill: fill === 'forwards' || fill === 'both' ? 'both' : 'backwards' })
      const target = effect.target
      if (target instanceof HTMLElement && !effect.pseudoElement
        && effect.getKeyframes().some((key) => 'transform' in key || 'opacity' in key || 'translate' in key)) {
        target.style.willChange = 'transform, opacity'
        layered.push(target)
      }
      return { animation, delay, fill }
    })
  await new Promise((resolve) => requestAnimationFrame(resolve)) // the frame that draws the change
  await new Promise((resolve) => requestAnimationFrame(resolve)) // the next one, after it is drawn
  const now = Number(document.timeline.currentTime)
  for (const { animation, delay, fill } of held) {
    if (animation.playState !== 'running') continue
    // Chrome may not have set a start time yet (a compositor's animation gets it when the compositor starts it): such
    // an animation starts on the next frame anyway
    const late = animation.startTime === null ? 0 : now - Number(animation.startTime)
    animation.effect!.updateTiming({ delay: delay + late, fill })
  }
}
/** The things a move gave layers to, until it settles or the next one takes over. */
let layered: HTMLElement[] = []
export function unlayer(): void {
  for (const el of layered) el.style.removeProperty('will-change')
  layered = []
}
