// The circle at the bottom of the board (docs/design-handoff S1.P1): one state at a time, and the caption for the job
// it is doing. The field sets `pointed` and `focused`; the conversation's store sets working and the answer (S2.P3,
// S2.P4); moving a goal sets `moving` (S5.P3).
import { computed, reactive } from 'vue'
import { commandFilter } from './commandFilter'
import { agentChat, openAsk } from './agentChat'
import { frontWindow } from './windows'

export type CircleJob = 'board' | 'goal' | 'moving'
export type CircleState = 'rest' | 'open' | 'typing' | 'working' | 'answer' | 'moving'

const CAPTIONS: Record<CircleJob, string> = {
  board: 'Find or ask',
  goal: 'Ask about this goal',
  moving: 'Find a goal',
}

export const circle = reactive({
  job: 'board' as CircleJob,
  pointed: false,
  focused: false,
  moving: false,
})

/** Once an answer has gone up into the conversation, the field asks the agent (S1.P1.015). */
export const circleCaption = computed(() => {
  if (circle.job !== 'board') return CAPTIONS[circle.job]
  if (frontWindow.value?.kind === 'goal') return CAPTIONS.goal
  return agentChat.engaged ? 'Ask the agent' : CAPTIONS.board
})

/** What the circle holds while the conversation is hidden: the answer, or the ask the agent waits on (S2.P4, S2.P1.044). */
export const circleWords = computed(() => {
  if (agentChat.open) return null
  if (openAsk.value) return { kind: 'ask' as const, text: openAsk.value.title }
  if (agentChat.answer) return { kind: 'answer' as const, text: agentChat.answer.text }
  return null
})

export const circleState = computed<CircleState>(() => {
  if (commandFilter.text) return 'typing'
  if (circle.moving) return 'moving'
  if (circle.focused) return 'open'
  if (circleWords.value) return 'answer'
  if (agentChat.running) return 'working'
  if (circle.pointed) return 'open'
  return 'rest'
})

/** A goal the circle should look at: made (a jump) or moved (a blink). Set by the board watcher, read by the mascot. */
export const circleNews = reactive({ made: null as { id: string; at: number } | null, moved: null as { id: string; at: number } | null })
