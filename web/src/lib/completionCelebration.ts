/** The all-subgoals-done celebration on a card: the sound, the overlay fade, the media sweep.
 *
 *  Lifted out of `GoalCard.vue` unchanged for ARCHITECTURE.md §2's 750-line module rule (S-90a).
 *  It is a self-contained side effect keyed on one boolean, so it moves whole: same constants,
 *  same keyframes, same durations, same teardown. The component keeps the three refs it renders.
 */

import { nextTick, onBeforeUnmount, ref, watch, type Ref } from 'vue'
import { playSound } from './sound'

/** The reference's own Lottie parameters, kept verbatim — the media duration below is derived
 *  from them rather than restated as a magic number. */
export const COMPLETION_LOTTIE = {
  width: 2000,
  height: 2000,
  frameRate: 29.9700012207031,
  firstFrame: 0,
  lastFrame: 300.00001221925,
} as const

/** The two element refs stay OWNED BY THE COMPONENT and are passed in: they are template refs,
 *  bound by `ref="..."` in the markup, so they have to be top-level bindings there. */
export function useCompletionCelebration(
  childrenAllDone: Ref<boolean>,
  completionLayer: Ref<HTMLElement | null>,
  completionMedia: Ref<SVGSVGElement | null>,
) {
  const completionActive = ref(false)
  let completionTimer: number | null = null

  watch(childrenAllDone, (allDone, wasAllDone) => {
    if (!allDone || wasAllDone) return
    playSound('all_completed')
    completionActive.value = true
    void nextTick(() => {
      completionLayer.value?.animate(
        [
          { opacity: 0, offset: 0 },
          { opacity: 1, offset: .2 },
          { opacity: 1, offset: .8 },
          { opacity: 0, offset: 1 },
        ],
        { duration: 5000, easing: 'ease' },
      )
      const mediaDuration = (
        (COMPLETION_LOTTIE.lastFrame - COMPLETION_LOTTIE.firstFrame)
        / COMPLETION_LOTTIE.frameRate
      ) * 1000
      completionMedia.value?.animate(
        [
          { transform: 'scale(.72) rotate(0deg)', opacity: .2 },
          { transform: 'scale(1) rotate(16deg)', opacity: 1, offset: .35 },
          { transform: 'scale(1.08) rotate(32deg)', opacity: .75, offset: .7 },
          { transform: 'scale(1.18) rotate(48deg)', opacity: 0 },
        ],
        { duration: mediaDuration, easing: 'linear', iterations: 1, fill: 'forwards' },
      )
    })
    if (completionTimer !== null) window.clearTimeout(completionTimer)
    completionTimer = window.setTimeout(() => {
      completionActive.value = false
      completionTimer = null
    }, 6000)
  })

  onBeforeUnmount(() => {
    if (completionTimer !== null) window.clearTimeout(completionTimer)
  })

  return { completionActive }
}
