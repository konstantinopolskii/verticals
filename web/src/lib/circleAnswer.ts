/* The agent's answer or ask in the circle (components/FieldAnswer.tsx): its words, the chips of what it made, its Undo,
   and the measures the field takes its size from (lib/fieldSize.ts). */
import { computed, nextTick, onBeforeUnmount, ref, watch } from '../reactivity'
import { circleWords } from './circle'
import { answerUndo } from './answerUndo'
import { plainWords } from './chatMarkdown'
import { chipLinks, withoutChipLines } from './chipLinks'
import { openAsk } from './agentChat'
import { ANSWER_MEASURE, answerLinesOf, CHIPS_SHOWN, chipsGuess } from './fieldSize'

/* What the answer made or changed, under its words as in its balloon: the first few chips, the rest counted. */
export const answerChips = computed(() => (circleWords.value?.kind === 'answer' ? chipLinks(circleWords.value.text) : []))
export const shownChips = computed(() => answerChips.value.slice(0, CHIPS_SHOWN))
export const moreChips = computed(() => answerChips.value.length - shownChips.value.length)
/* Whether the answer in the circle has an Undo: it changed the board, and has not been let go. */
export const undoable = computed(() => {
  const words = circleWords.value
  const entry = words?.kind === 'answer' && words.answer ? answerUndo.entries[words.answer] : undefined
  return !!entry && entry.state !== 'spent'
})
export const answerText = computed(() => {
  if (!circleWords.value) return ''
  return plainWords(answerChips.value.length ? withoutChipLines(circleWords.value.text) : circleWords.value.text)
})
/* What the answer says to one who does not see it: its words, or the names of what it made when it has none. */
export const answerSays = computed(() => answerText.value || answerChips.value.map((chip) => chip.label).join(', '))
export const leadText = computed(() => (circleWords.value?.kind === 'ask' && circleWords.value.lead ? plainWords(withoutChipLines(circleWords.value.lead)) : ''))
/* An ask says what it will change under its question: the goal and its date (lib/askDetail.ts). */
export const changesText = computed(() => (circleWords.value?.kind === 'ask' ? circleWords.value.changes : ''))
export const choices = computed(() => (circleWords.value?.kind === 'ask' ? openAsk.value?.options ?? [] : []))

/** The answer's measures, inside useSetup: its lines and width, the lead's lines, the chips' height. */
export function answerSize() {
  const answerMeasure = ref<HTMLElement | null>(null)
  const leadMeasure = ref<HTMLElement | null>(null)
  const chipsBox = ref<HTMLElement | null>(null)
  const answerLines = ref(1)
  const answerWidth = ref(0)
  const leadLines = ref(0)
  const chipsMeasured = ref(0)

  /* The answer's shape hugs its words: one line as wide as they are, more at the 376 px measure, three at most (S2.P4.040). */
  watch([answerText, changesText], async () => {
    await nextTick()
    const el = answerMeasure.value
    if (!el) return
    answerLines.value = answerLinesOf(el, 3)
    // The blinking line after the words takes its 5 px on the last line.
    answerWidth.value = answerLines.value > 1 ? ANSWER_MEASURE : Math.min(ANSWER_MEASURE, Math.ceil(el.scrollWidth) + 6)
  }, { immediate: true, flush: 'post' })
  /* An ask in the field carries the agent's last words on top, two lines at most (S2.P1.044). */
  watch(leadText, async () => {
    await nextTick()
    const el = leadMeasure.value
    leadLines.value = el && leadText.value ? answerLinesOf(el, 2) : 0
  }, { immediate: true, flush: 'post' })
  /* The chips' height, as they are drawn: a title takes one line or two, and a goal's line arrives once the goal is read. */
  let chipsWatch: ResizeObserver | null = null
  watch(chipsBox, (el) => {
    chipsWatch?.disconnect()
    chipsWatch = null
    chipsMeasured.value = 0
    if (!el || typeof ResizeObserver === 'undefined') return
    chipsWatch = new ResizeObserver(() => { chipsMeasured.value = Math.round(el.offsetHeight) })
    chipsWatch.observe(el)
  }, { flush: 'post' })
  onBeforeUnmount(() => chipsWatch?.disconnect())

  const chipsHeight = computed(() => chipsMeasured.value || chipsGuess(shownChips.value, moreChips.value))
  return { answerMeasure, leadMeasure, chipsBox, answerLines, answerWidth, leadLines, chipsHeight }
}
