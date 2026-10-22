/* The burst over a goal's list when its last subgoal is done (lib/completionCelebration.ts plays it). */
import type { Ref } from '../reactivity'
import { COMPLETION_LOTTIE } from '../lib/completionCelebration'
import { bindRef } from '../bind'
import { tracked } from '../tracked'

interface Props {
  layer: Ref<HTMLElement | null>
  media: Ref<SVGSVGElement | null>
}

export const GoalCompletion = tracked(function GoalCompletion({ layer, media }: Props) {
  return (
    <div ref={bindRef(layer)} className="goal-card__completion" data-role="completion-animation">
      <svg
        ref={bindRef(media)}
        viewBox={`0 0 ${COMPLETION_LOTTIE.width} ${COMPLETION_LOTTIE.height}`}
        preserveAspectRatio="xMidYMid slice"
        data-format="lottie"
        data-width={COMPLETION_LOTTIE.width}
        data-height={COMPLETION_LOTTIE.height}
        data-frame-rate={COMPLETION_LOTTIE.frameRate}
        data-first-frame={COMPLETION_LOTTIE.firstFrame}
        data-last-frame={COMPLETION_LOTTIE.lastFrame}
        data-loop="false"
        data-autoplay="true"
        aria-hidden="true"
      >
        <g className="goal-card__completion-rays">
          <path d="M1000 100 1000 500M1000 1500 1000 1900M100 1000 500 1000M1500 1000 1900 1000" />
          <path d="m360 360 285 285m710 710 285 285m0-1280-285 285m-710 710-285 285" />
        </g>
        <circle cx="1000" cy="1000" r="270" />
      </svg>
    </div>
  )
})
