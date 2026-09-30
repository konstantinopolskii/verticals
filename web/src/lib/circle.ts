// The circle at the bottom of the board (docs/design-handoff S1.P1): one state at a time, and the caption for the job
// it is doing. Later puzzles set `working`, `answer` and `moving`; the field sets `pointed` and `focused`.
import { computed, reactive } from 'vue'
import { commandFilter } from './commandFilter'

export type CircleJob = 'board' | 'goal' | 'moving' | 'conversation'
export type CircleState = 'rest' | 'open' | 'typing' | 'working' | 'answer' | 'moving'

const CAPTIONS: Record<CircleJob, string> = {
  board: 'Find or ask',
  goal: 'Ask about this goal',
  moving: 'Find a goal',
  conversation: 'Ask the agent',
}

export const circle = reactive({
  job: 'board' as CircleJob,
  pointed: false,
  focused: false,
  working: false,
  answer: null as string | null,
  moving: false,
})

export const circleCaption = computed(() => CAPTIONS[circle.job])

export const circleState = computed<CircleState>(() => {
  if (commandFilter.text) return 'typing'
  if (circle.moving) return 'moving'
  if (circle.answer !== null) return 'answer'
  if (circle.working) return 'working'
  if (circle.pointed || circle.focused) return 'open'
  return 'rest'
})

/** A goal the circle should look at: made (a jump) or moved (a blink). Set by the board watcher, read by the mascot. */
export const circleNews = reactive({ made: null as { id: string; at: number } | null, moved: null as { id: string; at: number } | null })
