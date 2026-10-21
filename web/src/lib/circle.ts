// The circle at the bottom of the board (docs/design-handoff S1.P1): one state at a time, and the caption for the job
// it is doing. The field sets `pointed` and `focused`; the conversation's store sets working and the answer (S2.P3,
// S2.P4); moving a goal sets `moving` (S5.P3). Pointing at the resting circle only widens it (SearchBar.tsx); the field
// opens on a click, a key or ⌘K (docs/design/field-hover.md).
import { computed, reactive } from '../reactivity'
import { commandFilter } from './commandFilter'
import { agentChat, balloons, openAsk } from './agentChat'
import { askLine } from './askDetail'
import { frontWindow, windows } from './windows'
import { pictures, reporting } from './reportPictures'
import { store } from '../store'

export type CircleJob = 'board' | 'goal' | 'moving'
export type CircleState = 'rest' | 'open' | 'typing' | 'working' | 'answer' | 'moving'

const CAPTIONS: Record<CircleJob, string> = {
  board: 'Find or ask',
  goal: 'Ask about this goal',
  moving: 'Find a goal',
}
/** In the Inbox the field is where you write (KK, 7 Oct 2026: "place for writing could be right inside the field and it
 *  simply can invite us to do that"): it rests open with its invitation, and ↵ writes your words down (`lib/inbox.ts`).
 *  Round 9: “"Write to inbox" in field actually.” */
export const INBOX_CAPTION = 'Write to inbox'
/** With pictures waiting above it the field is a report's (docs/design/bug-reports.md): it rests open and asks for the words,
 *  whether something is wrong or could be better. While a file is dragged over the window it says what the drop will do. */
export const REPORT_CAPTION = 'Say what you see and what you want'
export const DROP_CAPTION = 'Drop pictures'

export const circle = reactive({
  job: 'board' as CircleJob,
  pointed: false,
  focused: false,
  moving: false,
})

/** The field writes things down: the Inbox is open, with no window over it, no conversation and nothing being moved. */
export const inboxWriting = computed(() => store.state.activeView === 'inbox' && !windows.list.length && !agentChat.open
  && !circle.moving)

/** Once an answer has gone up into the conversation, the field asks the agent (S1.P1.015). */
export const circleCaption = computed(() => {
  if (pictures.over) return DROP_CAPTION
  if (reporting.value) return REPORT_CAPTION
  if (inboxWriting.value) return INBOX_CAPTION
  if (circle.job !== 'board') return CAPTIONS[circle.job]
  if (frontWindow.value?.kind === 'goal') return CAPTIONS.goal
  return agentChat.engaged ? 'Ask the agent' : CAPTIONS.board
})

/** The agent's last words, shown on top of an ask in the field (S2.P1.044). */
function lastAgentWords(): string {
  for (let i = balloons.value.length - 1; i >= 0; i--) {
    const balloon = balloons.value[i]!
    if (balloon.who === 'agent' && balloon.text.trim()) return balloon.text
  }
  return ''
}

/** What the circle holds while the conversation is hidden: the answer, or the ask the agent waits on (S2.P4, S2.P1.044). */
export const circleWords = computed(() => {
  if (agentChat.open) return null
  // The app's own ask (the sign-in, docs/design/agent-sign-in.md) is not the agent's: no words of the agent's lead it.
  const ask = openAsk.value
  if (ask) return { kind: 'ask' as const, text: ask.title, lead: ask.note ? '' : lastAgentWords(), changes: askLine(ask) }
  if (agentChat.answer) return { kind: 'answer' as const, text: agentChat.answer.text, answer: agentChat.answer.answer }
  return null
})

export const circleState = computed<CircleState>(() => {
  if (commandFilter.text) return 'typing'
  if (circle.moving) return 'moving'
  // The report is being made from the pictures: the line turns, as it does while the agent works.
  if (pictures.sending) return 'working'
  if (circle.focused || reporting.value || pictures.over) return 'open'
  if (circleWords.value) return 'answer'
  if (agentChat.running) return 'working'
  // Pointing at the circle doesn't open it: it stays `rest` and the field widens it (docs/design/field-hover.md).
  if (inboxWriting.value) return 'open'
  return 'rest'
})

/** A goal the circle should look at: made (a jump) or moved (a blink). Set by the board watcher, read by the mascot. */
export const circleNews = reactive({ made: null as { id: string; at: number } | null, moved: null as { id: string; at: number } | null })
