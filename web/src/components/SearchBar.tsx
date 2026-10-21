/* The circle and the field at the bottom of every screen: one black shape that is the
   mascot at rest, the field you type into, the agent's step, answer and ask, with the tags and what waits while a goal
   moves above it. */
import { useLayoutEffect, type MouseEvent, type ReactNode } from 'react'
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch, type Ref } from '../reactivity'
import { store } from '../store'
import { commandFilter, filterText } from '../lib/commandFilter'
import { historyKey } from '../lib/boardHistory'
import { fieldUndo } from '../lib/fieldUndo'
import { circle, circleCaption, circleState, circleWords, inboxWriting } from '../lib/circle'
import { carry } from '../lib/inboxCarry'
import { QUESTION_TOOL, agentChat, decide, openAsk, stop } from '../lib/agentChat'
import { answerUndo } from '../lib/answerUndo'
import { plainWords } from '../lib/chatMarkdown'
import { closeWindows, windows } from '../lib/windows'
import { mascot, useMascot, watchBoardNews } from '../lib/mascot'
import { followWords } from '../lib/finding'
import { curve, reducedMotion } from '../lib/motion'
import { launch } from '../lib/chatFlight'
import { anyMenuOpen } from '../lib/cardLift'
import { defineKnobs, knob } from '../lib/tuning'
import { AgentChips } from './AgentChips'
import { AnswerUndo } from './AnswerUndo'
import { AnswerSuggestions } from './AnswerSuggestions'
import { CircleGame } from './CircleGame'
import { CircleTags } from './CircleTags'
import { chipLinks, withoutChipLines } from '../lib/chipLinks'
import { MovingStack } from './MovingStack'
import { backspace as pickBackspace, escape as movingEscape, tab as pickTab } from '../lib/moving'
import { dots } from '../lib/spansDrag'
import { pictures, picturesBackspace, picturesEscape, reporting, stackRoom, watchPictureInput } from '../lib/reportPictures'
import { brush, type Brush } from '../lib/brush'
import { AgentStep } from './AgentStep'
import { bindRef, cx, fallthrough, sx } from '../bind'
import { tracked } from '../tracked'
import { exposeTo, listen, useSetup } from '../setup'
import './circleField.css'

export interface SearchBarApi {
  focusField(): void
}

interface Props {
  agentAvailable: boolean
  onSubmit?: (text: string) => void
  expose?: Ref<SearchBarApi | null>
  /** Drawn first in the space above the field. */
  above?: ReactNode
  /** The agent's tag among the tags above the field. */
  agentTag?: ReactNode
}

const ANSWER_MEASURE = 376
const ANSWER_PAD = 44
const PAD_LEFT = 32
const PAD_RIGHT = 84
const PAD_Y = 24
const LINE = 36
const CIRCLE = 84
/* While the agent works the circle is a pill with its step written beside the turning line (AgentStep): the line stays where
   the circle's centre was, 42 px in, and the stop square takes the right end. One width for every phrase, so the black moves
   when the work begins and ends, not with each step. */
const STEP_WIDTH = 360
/* The open field's caption has 32 px on each side. */
const PAD_CAPTION = 32
const OPEN_WIDTH = 272
/* A message bringing chips is the balloon in the field: the words 376 px wide, two lines of them, 32 px in from the sides,
   then the chips with 14 px between (the balloon's own), three at most and "N more" for the rest. */
const CHIPS_PAD = 32
const CHIPS_SHOWN = 3
const CHIPS_GAP = 14
const CHIP_HEIGHT = { doc: 67, goal: 44 }
/* An answer that changed the board has its Undo at its end, under its words and its chips (AnswerUndo): the notice's
   pill, 40 px tall and about 80 wide, 12 px under what is above it. */
const UNDO_ROW = 52
const UNDO_W = 80

export const SearchBar = tracked(function SearchBar(raw: Props & Record<string, unknown>) {
  const { agentAvailable, onSubmit, expose, above, agentTag, ...attrs } = raw
  const s = useSetup({ agentAvailable, onSubmit, expose }, (props) => {
    defineKnobs('The field', [
      { key: 'field.maxLines', label: 'Lines before the field scrolls', value: 10, min: 1, max: 20, step: 1 },
    ])

    const body = ref<HTMLElement | null>(null)
    const shape = ref<HTMLElement | null>(null)
    const surface = ref<HTMLElement | null>(null)
    const line = ref<HTMLElement | null>(null)
    const input = ref<HTMLTextAreaElement | null>(null)
    const mirror = ref<HTMLElement | null>(null)
    const pivot = ref<HTMLElement | null>(null)
    const answerMeasure = ref<HTMLElement | null>(null)
    const answerLines = ref(1)
    const leadMeasure = ref<HTMLElement | null>(null)
    const leadLines = ref(0)
    const answerWidth = ref(0)

    const hand = ref<{ x: number; y: number } | null>(null)
    const onTags = ref(false)
    const caret = ref<{ x: number; y: number }>({ x: 0, y: 0 })
    const selecting = ref(false)
    /* The shape follows the words' flight at its pace: 280 ms when they are sent, 300 ms when the answer goes up. */
    const flying = ref<'sent' | 'reply' | null>(null)
    let flyingTimer: ReturnType<typeof setTimeout> | null = null
    function fly(kind: 'sent' | 'reply'): void {
      flying.value = kind
      if (flyingTimer) clearTimeout(flyingTimer)
      flyingTimer = setTimeout(() => { flying.value = null }, 420)
    }
    const still = ref(true)
    const lines = ref(1)
    const room = reactive({ width: typeof innerWidth === 'number' ? innerWidth : 1440 })

    const state = circleState
    const text = computed(() => commandFilter.text)
    const maxWidth = computed(() => Math.max(CIRCLE, Math.min(720, room.width - 32)))

    /* Under a pointer that can hover, the resting circle only widens: 116 px, its line 5 × 46 px and upright, the buttons
       above it 38 px (circleField.css). It opens on a click, a key or ⌘K, never on the pointer (docs/design/field-hover.md). */
    const hoverQuery = typeof matchMedia === 'function' ? matchMedia('(hover: hover) and (pointer: fine)') : null
    const canHover = ref(hoverQuery?.matches ?? false)
    function onCanHover(event: MediaQueryListEvent): void { canHover.value = event.matches }
    const hovered = computed(() => circle.pointed && canHover.value && state.value === 'rest')

    let measureCtx: CanvasRenderingContext2D | null = null
    /* A face loads its glyphs as they are first used (Cyrillic, say): until then words are measured in the fallback face,
       so the field measures them again once a face has loaded, or a pasted line wraps out of sight. */
    const fontsLoaded = ref(0)
    function onFontsLoaded(): void { fontsLoaded.value += 1 }
    function textWidth(value: string): number {
      void fontsLoaded.value
      if (!input.value) return 0
      measureCtx ??= document.createElement('canvas').getContext('2d')
      if (!measureCtx) return 0
      const style = getComputedStyle(input.value)
      measureCtx.font = `${style.fontWeight} ${style.fontSize} ${style.fontFamily}`
      return Math.max(0, ...value.split('\n').map((part) => measureCtx!.measureText(part).width))
    }

    /* What the answer made or changed, under its words as in its balloon: the first few chips, the rest counted. */
    const answerChips = computed(() => (circleWords.value?.kind === 'answer' ? chipLinks(circleWords.value.text) : []))
    const shownChips = computed(() => answerChips.value.slice(0, CHIPS_SHOWN))
    const moreChips = computed(() => answerChips.value.length - shownChips.value.length)
    /* Whether the answer in the circle has an Undo: it changed the board, and has not been let go. */
    const undoable = computed(() => {
      const words = circleWords.value
      const entry = words?.kind === 'answer' && words.answer ? answerUndo.entries[words.answer] : undefined
      return !!entry && entry.state !== 'spent'
    })
    const answerText = computed(() => {
      if (!circleWords.value) return ''
      return plainWords(answerChips.value.length ? withoutChipLines(circleWords.value.text) : circleWords.value.text)
    })
    /* What the answer says to one who does not see it: its words, or the names of what it made when it has none. */
    const answerSays = computed(() => answerText.value || answerChips.value.map((chip) => chip.label).join(', '))
    const leadText = computed(() => (circleWords.value?.kind === 'ask' && circleWords.value.lead ? plainWords(withoutChipLines(circleWords.value.lead)) : ''))
    /* The chips' height is theirs to say (a title takes one line or two): measured, with the first guess until they are drawn. */
    const chipsBox = ref<HTMLElement | null>(null)
    const chipsMeasured = ref(0)
    const chipsHeight = computed(() => {
      if (chipsMeasured.value) return chipsMeasured.value
      const guess = shownChips.value.reduce((sum, chip) => sum + CHIP_HEIGHT[chip.kind] + 12, -12)
      return guess + (moreChips.value ? 12 + 22 : 0)
    })
    /* The words above the chips: two lines at most, and 14 px to the first chip. */
    const chipWords = computed(() => (answerText.value ? Math.min(2, answerLines.value) * 22 + CHIPS_GAP : 0))
    /* An ask says what it will change under its question: the goal and its date (lib/askDetail.ts). */
    const changesText = computed(() => (circleWords.value?.kind === 'ask' ? circleWords.value.changes : ''))
    /* A question of the agent's brings up to four options (docs/design/replan-whole-board.md): the field takes the full
       measure for them, and their rows, measured as drawn, set its height. */
    const question = computed(() => circleWords.value?.kind === 'ask' && openAsk.value?.tool === QUESTION_TOOL)
    const choicesBox = ref<HTMLElement | null>(null)
    const choicesMeasured = ref(0)
    const stopping = computed(() => state.value === 'working' && circle.pointed)
    /* With an ask waiting in the open conversation the circle only waits (no turning line, no step). The step is a
       conversation's: while a report is made from pictures the line turns with none (docs/design/bug-reports.md). */
    const stepShown = computed(() => state.value === 'working' && agentChat.running && !openAsk.value)
    /* Holding a goal over the spans, the field is a pill with the mascot; let go over it, it widens to hold what stands above
       it (S5.P3.002, .007, .039). Let go anywhere else, it stays the pill while the goal lands and the board comes back. */
    const holding = computed(() => carry.over
      // In the Inbox the card waiting above the field, carried out again, is held the same way (docs/design/inbox-carry-stack.md).
      || (state.value === 'moving' && (store.state.drag.id !== null || dots.landing || carry.item !== null)))

    /* The caption that was there blurs out while the new one comes in. */
    const captionLeaving = ref<string | null>(null)
    watch(circleCaption, (_, old) => { captionLeaving.value = old ?? null })
    watch(text, (words) => { if (words) captionLeaving.value = null })

    /* Open, the field is as wide as "Write to inbox" at least, and wider only for a longer caption. */
    const openWidth = computed(() => Math.min(maxWidth.value,
      Math.max(OPEN_WIDTH, Math.ceil(PAD_CAPTION + textWidth(circleCaption.value) + PAD_CAPTION))))

    const baseWidth = computed(() => {
      if (carry.over) return 120
      if (state.value === 'answer' && answerChips.value.length) return ANSWER_MEASURE + 2 * CHIPS_PAD
      if (state.value === 'answer') {
        const wide = Math.min((leadLines.value || question.value ? ANSWER_MEASURE : answerWidth.value) + 2 * ANSWER_PAD, ANSWER_MEASURE + 2 * ANSWER_PAD)
        return Math.max(CIRCLE, wide, undoable.value ? UNDO_W + 2 * ANSWER_PAD : 0)
      }
      if (stepShown.value) return Math.min(STEP_WIDTH, maxWidth.value)
      if (stopping.value) return 132
      // Typing, it grows around your words and never gets narrower than it was open, so the first key moves nothing.
      if (state.value === 'typing') {
        return Math.min(maxWidth.value, Math.max(openWidth.value, Math.ceil(PAD_LEFT + PAD_RIGHT + textWidth(text.value) + 5)))
      }
      if (state.value === 'open') return openWidth.value
      if (holding.value) return 120
      // The buttons stand at the stack's left end whenever they are shown, pointed at or holding the keys, and the stack
      // stands right of them (S5.P3.010, .012): the field is wide enough for both, with the hand on it or away.
      if (state.value === 'moving') return Math.min(tagsShown.value ? 434 : 300, maxWidth.value)
      return mascot.game ? 132 : CIRCLE
    })
    /* Pictures waiting above the field widen it to hold them: the stack, and what stands at its left end (4 px, or the tags
       and 8) and keeps the stack's room as CSS reads it (FieldPictures). It is as wide as the stack needs and the open field
       was, at once (docs/design/bug-reports.md). */
    const tagsShift = ref(0)
    const width = computed(() => Math.min(maxWidth.value,
      Math.max(baseWidth.value, reporting.value ? stackRoom(pictures.list) + Math.max(8, 4 + tagsShift.value) : 0)))
    const shownLines = computed(() => Math.min(lines.value, knob('field.maxLines')))
    const height = computed(() => {
      if (state.value === 'typing') return PAD_Y * 2 + shownLines.value * LINE
      if (state.value === 'answer' && answerChips.value.length) {
        return Math.max(CIRCLE, PAD_Y * 2 + chipWords.value + chipsHeight.value + (undoable.value ? UNDO_ROW : 0))
      }
      if (state.value === 'answer') {
        // 10 px above the buttons and a row of 32 at least; their rows as drawn when a question's options wrap.
        const choices = openAsk.value?.options.length ? Math.max(44, choicesMeasured.value + 12) : 0
        const ask = circleWords.value?.kind === 'ask' ? choices + (leadLines.value ? leadLines.value * 22 + 8 : 0) : 0
        return Math.max(CIRCLE, PAD_Y * 2 + answerLines.value * 22 + ask + (undoable.value ? UNDO_ROW : 0))
      }
      return CIRCLE
    })
    /* The turning line stays 42 px from the left end, the circle's centre, while the circle is a pill: the pivot moves there
       and follows the shape's own timing (circleField.css), so the line holds its place as the black widens and narrows. */
    const stepShift = computed(() => (stepShown.value ? CIRCLE / 2 - width.value / 2 : 0))
    const wide = computed(() => state.value === 'open' || state.value === 'typing' || state.value === 'answer'
      || (state.value === 'moving' && !holding.value))
    const tagsShown = computed(() => hovered.value || (circle.pointed && wide.value) || circle.focused || agentChat.open)

    /* Where the line stands: the mascot's at rest, upright under the pointer, your hand over the field, your caret once the
       field has it. */
    const lineMode = computed(() => {
      if (carry.over) return 'mascot'
      if (state.value === 'answer') return 'hidden'
      // Under the pointer the circle only widens: its line neither leans towards a goal nor follows the hand
      // (docs/design/field-hover.md).
      if (hovered.value) return 'upright'
      if (!wide.value) return 'mascot'
      // Resting open in the Inbox, the field is an invitation to write, not the agent: no line until you write (lib/inbox.ts).
      if (inboxWriting.value && state.value === 'open' && !circle.focused && !hand.value) return 'hidden'
      if (circle.focused) return selecting.value ? 'hidden' : 'caret'
      if (hand.value && !onTags.value) return 'hand'
      return state.value === 'typing' ? 'caret' : 'home'
    })

    const { mover } = useMascot({
      line, surface, body,
      center: () => {
        const box = shape.value?.getBoundingClientRect()
        return box ? { x: box.left + box.width / 2, y: box.top + box.height / 2 } : null
      },
    }, () => !wide.value)

    let lastMode = 'mascot'
    watch([lineMode, hand, caret, width, height], () => {
      const m = mover()
      if (!m) return
      const mode = lineMode.value
      if (mode === 'hand' && hand.value) m.set({ x: hand.value.x, y: hand.value.y, r: 0, sy: 1 })
      // At once, a lean in flight included: the change comes with the pointer.
      else if (mode === 'upright') { if (lastMode !== 'upright') m.set({ x: 0, y: 0, r: 0, sy: 1 }) }
      else if (mode === 'caret') {
        const slide = lastMode !== 'caret' && lastMode !== 'hidden'
        if (slide) void m.to({ ...caret.value, r: 0, sy: 1 }, 140, curve('large'))
        else m.set({ ...caret.value, r: 0, sy: 1 })
      } else if (mode === 'home' && lastMode !== 'home') void m.to({ x: 0, y: 0, r: 0, sy: 1 }, 160, curve('large'))
      else if (mode === 'mascot' && lastMode !== 'mascot') void m.to({ x: 0, y: 0, r: 0, sy: 1 }, 160, curve('large'))
      lastMode = mode
    }, { flush: 'post' })

    function measure(): void {
      const el = input.value
      const copy = mirror.value
      if (!el || !copy) return
      const set = el.style.height
      el.style.height = '0px'
      lines.value = Math.max(1, Math.round(el.scrollHeight / LINE))
      el.style.height = set
      const at = el.selectionStart ?? el.value.length
      selecting.value = el.selectionStart !== el.selectionEnd
      copy.textContent = el.value.slice(0, at)
      const mark = document.createElement('span')
      mark.textContent = '​'
      copy.appendChild(mark)
      const x = el.value ? mark.offsetLeft + 2 : -4
      const y = mark.offsetTop - el.scrollTop
      caret.value = { x: PAD_LEFT + x + 1.5 - width.value / 2, y: PAD_Y + y + LINE / 2 - height.value / 2 }
    }
    let stillTimer: ReturnType<typeof setTimeout> | null = null
    function moved(): void {
      still.value = false
      if (stillTimer) clearTimeout(stillTimer)
      stillTimer = setTimeout(() => { still.value = true }, 500)
      void nextTick(measure)
    }
    watch([text, width, height], () => void nextTick(measure))

    /* The answer's shape hugs its words: one line as wide as they are, more at the 376 px measure, three at most (S2.P4.040). */
    watch([answerText, changesText], async () => {
      await nextTick()
      const el = answerMeasure.value
      if (!el) return
      answerLines.value = Math.min(3, Math.max(1, Math.round(el.getBoundingClientRect().height / 22)))
      // The blinking line after the words takes its 5 px on the last line.
      answerWidth.value = answerLines.value > 1 ? ANSWER_MEASURE : Math.min(ANSWER_MEASURE, Math.ceil(el.scrollWidth) + 6)
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
    let choicesWatch: ResizeObserver | null = null
    watch(choicesBox, (el) => {
      choicesWatch?.disconnect()
      choicesWatch = null
      choicesMeasured.value = 0
      if (!el || typeof ResizeObserver === 'undefined') return
      choicesWatch = new ResizeObserver(() => { choicesMeasured.value = Math.round(el.offsetHeight) })
      choicesWatch.observe(el)
    }, { flush: 'post' })
    /* An ask in the field carries the agent's last words on top, two lines at most (S2.P1.044). */
    watch(leadText, async () => {
      await nextTick()
      const el = leadMeasure.value
      leadLines.value = el && leadText.value ? Math.min(2, Math.max(1, Math.round(el.getBoundingClientRect().height / 22))) : 0
    }, { immediate: true, flush: 'post' })

    /* The conversation measures itself against the field (S2.P1.009), and moves up when the tags come in (S2.P2.013). */
    watch(height, (value) => document.documentElement.style.setProperty('--vt-field-height', `${value}px`), { immediate: true })
    watch(tagsShown, (shown) => document.documentElement.style.setProperty('--vt-tags-lift', shown ? '44px' : '0px'), { immediate: true })
    watch(width, (value) => document.documentElement.style.setProperty('--moving-field-width', `${value}px`), { immediate: true })
    /* Pointed at in the moving mode, the tags take the stack's left end and the stack moves right by their width and 8 px
       (S5.P3.010, .012). */
    watch(tagsShown, async (shown) => {
      await nextTick()
      const tags = shown ? document.querySelector<HTMLElement>('.circle-tags')?.offsetWidth ?? 0 : 0
      tagsShift.value = tags ? tags + 8 : 0
      document.documentElement.style.setProperty('--moving-tags-shift', `${tagsShift.value}px`)
    }, { immediate: true })

    /* While the agent works the line turns; when it answers it ends upright (S2.P3.003). */
    watch(() => state.value === 'working', (working, was) => {
      const el = pivot.value
      if (!el || working || !was) return
      const from = getComputedStyle(el).transform
      if (from && from !== 'none') el.animate([{ transform: from }, { transform: 'none' }], { duration: 165, easing: curve('large') })
    })

    /* The answer goes back into the circle and the conversation keeps it: Esc does it, and so does brushing it away with a
       sideways swipe or a drag down (lib/brush.ts; docs/design/agent-fixes.md, fix 8). */
    function sendBack(): void {
      agentChat.answer = null
    }
    /* The answer goes up into the conversation as its last balloon, and the field takes the caret (S2.P4.003). */
    function reply(): void {
      const words = shape.value?.querySelector('.circle-field__answer-words')?.getBoundingClientRect()
      if (words) launch('reply', words.left, words.top)
      // A press first, then the answer goes up as the black shrinks into the open field (S2.P4.015, .016).
      if (!reducedMotion()) {
        shape.value?.animate([{ transform: 'scale(1)' }, { transform: 'scale(.98)' }, { transform: 'scale(1)' }],
          { duration: 90, easing: curve('large') })
      }
      fly('reply')
      agentChat.answer = null
      agentChat.open = true
      agentChat.engaged = true
      focusField()
    }

    /* ⌘Z in the field is the field's own, a run of typing at a time (`lib/fieldUndo.ts`): the browser's would take a letter. */
    const words = fieldUndo({
      get: () => commandFilter.text,
      set: (text) => {
        commandFilter.text = text
        void nextTick(() => {
          input.value?.setSelectionRange(text.length, text.length)
          moved()
        })
      },
    })
    watch(() => commandFilter.text, (now) => words.changed(now))
    function onInput(event: Event): void {
      const value = (event.target as HTMLTextAreaElement).value
      words.typing(commandFilter.text, (event as InputEvent).inputType ?? '')
      commandFilter.text = value
      words.typed(value)
      moved()
    }
    function focusField(): void {
      const el = input.value
      if (!el) return
      // Typing, or a click on the field, brings the conversation back; over a window, always (S2.P1.011, .018).
      if (windows.list.length && agentChat.available) agentChat.engaged = true
      // In the Inbox the field writes: an earlier conversation stays where it is until you ask (lib/inbox.ts).
      if (agentChat.engaged && !agentChat.open && (store.state.activeView !== 'inbox' || windows.list.length)) agentChat.open = true
      el.focus({ preventScroll: true })
      const end = el.value.length
      el.setSelectionRange(end, end)
      moved()
    }
    /* A question's suggestion changed the words (lib/answerSuggestions.ts): the field shows them and takes the caret at their end. */
    function onFocusAsked(): void {
      if (input.value) input.value.value = commandFilter.text
      focusField()
    }
    function clear(): void {
      commandFilter.text = ''
      moved()
    }
    function send(): void {
      const words = commandFilter.text.trim()
      if (!words) return
      // In the Inbox they become the first card in Today, and with pictures above the field they are the report's: no
      // balloon takes them up (lib/inbox.ts, lib/report.ts).
      if (inboxWriting.value || reporting.value) {
        props.onSubmit?.(words)
        return
      }
      // Your words rise from where they stand into your balloon, and the field is the circle again (S2.P3.019).
      const box = input.value?.getBoundingClientRect()
      if (box) launch('sent', box.left, box.top + (LINE - 22) / 2)
      fly('sent')
      props.onSubmit?.(words)
    }
    function onKeyDown(event: KeyboardEvent): void {
      if (event.isComposing) return
      const history = historyKey(event)
      if (history) {
        // Inside the field the key is the field's own, and never the board's (`lib/boardHistory.ts`).
        event.preventDefault()
        words.step(history)
        return
      }
      if (event.key === 'Enter' && !event.shiftKey) {
        event.preventDefault()
        send()
        return
      }
      // On an empty field with pictures above it, Backspace picks the last and a second takes it off (docs/design/bug-reports.md).
      if (!commandFilter.text && event.key === 'Backspace' && picturesBackspace()) {
        event.preventDefault()
        return
      }
      // On an empty field in the moving mode, Backspace and Tab pick up what stands above it (S5.P4.002, .003).
      if (!commandFilter.text && circle.moving && ((event.key === 'Backspace' && pickBackspace()) || (event.key === 'Tab' && pickTab()))) {
        event.preventDefault()
        return
      }
      if (event.key === 'Escape') {
        event.preventDefault()
        event.stopPropagation()
        if (commandFilter.text) clear()
        else if (picturesEscape()) return
        else if (movingEscape()) return
        else if (agentChat.open) agentChat.open = false
        else if (windows.list.length) closeWindows()
        else {
          agentChat.engaged = false
          input.value?.blur()
        }
        return
      }
      if (event.key === 'Tab' && !event.shiftKey && !commandFilter.text) {
        // The tags are reached with Tab from the open field, in their order (S2.P2.020).
        const first = document.querySelector<HTMLElement>('.circle-tags .circle-tag')
        if (first) { event.preventDefault(); first.focus() }
        return
      }
      if (['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown', 'Home', 'End'].includes(event.key)) moved()
    }
    // Native listeners on the field: `inputType` and the real `beforeinput`, `select` and a keydown whose stopPropagation
    // stops at the field.
    listen(input, 'beforeinput', (event) => words.history(event))
    listen(input, 'input', onInput)
    listen(input, 'keydown', onKeyDown)
    listen(input, 'select', moved)

    function fromCentre(event: PointerEvent): { x: number; y: number } | null {
      const box = shape.value?.getBoundingClientRect()
      if (!box) return null
      const half = Math.max(0, width.value / 2 - 20)
      const clamp = (v: number, m: number) => Math.max(-m, Math.min(m, v))
      return { x: clamp(event.clientX - box.left - box.width / 2, half), y: clamp(event.clientY - box.top - box.height / 2, 24) }
    }
    function onShapeMove(event: PointerEvent): void {
      if (event.pointerType === 'touch') return
      circle.pointed = true
      onTags.value = false
      hand.value = fromCentre(event)
    }
    function onTagsEnter(): void { onTags.value = true }
    function onLeave(): void {
      circle.pointed = false
      hand.value = null
      onTags.value = false
    }

    /* Any printable key on the board is the field's first letter; ⌘K opens it from anywhere (S1.P2.012, .024). */
    function onWindowKeyDown(event: KeyboardEvent): void {
      if (event.defaultPrevented || event.isComposing) return
      if ((event.metaKey || event.ctrlKey) && !event.altKey && event.key.toLowerCase() === 'k') {
        event.preventDefault()
        event.stopImmediatePropagation()
        focusField()
        return
      }
      if ((event.metaKey || event.ctrlKey) && event.key === '.' && agentChat.running) {
        event.preventDefault()
        void stop()
        return
      }
      if (event.key === 'Escape' && circleWords.value?.kind === 'answer' && !anyMenuOpen()) {
        event.preventDefault() // one press does one thing: the answer goes back, and nothing under it closes with it
        sendBack()
        return
      }
      if (event.metaKey || event.ctrlKey || event.altKey || event.key.length !== 1 || event.key === ' ') return
      const target = event.target instanceof HTMLElement ? event.target : null
      if (target?.closest('input, textarea, select, button, [contenteditable="true"], [role="dialog"], [role="menu"]')) return
      if (anyMenuOpen() || store.state.drag.id || store.state.drag.pending) return
      event.preventDefault()
      if (circleWords.value?.kind === 'answer') reply()
      words.typing(commandFilter.text, 'insertText')
      commandFilter.text += event.key
      words.typed(commandFilter.text)
      focusField()
    }
    function onShapeClick(): void {
      if (brushing?.swallowed()) return // the end of a drag is no click on the answer
      if (circleWords.value?.kind === 'answer') reply()
      else if (!circleWords.value) focusField()
    }
    function onResize(): void { room.width = innerWidth }

    exposeTo(props.expose, { focusField })

    let stopNews: (() => void) | null = null
    let stopFinding: (() => void) | null = null
    let stopPictures: (() => void) | null = null
    let brushing: Brush | null = null
    onMounted(() => {
      if (shape.value) brushing = brush(shape.value, () => state.value === 'answer' && circleWords.value?.kind === 'answer', sendBack)
      const match = /^\/search\/(.*)/.exec(location.pathname)
      if (match?.[1]) { try { commandFilter.text = decodeURIComponent(match[1]) } catch { commandFilter.text = match[1] } }
      window.addEventListener('keydown', onWindowKeyDown, true)
      window.addEventListener('verticals:focus-field', onFocusAsked)
      window.addEventListener('resize', onResize)
      hoverQuery?.addEventListener('change', onCanHover)
      document.fonts?.addEventListener('loadingdone', onFontsLoaded)
      stopNews = watchBoardNews()
      stopFinding = followWords(() => filterText.value, () => store.state.board)
      stopPictures = watchPictureInput()
      void document.fonts?.ready.then(() => void nextTick(measure))
    })
    onBeforeUnmount(() => {
      chipsWatch?.disconnect()
      brushing?.stop()
      window.removeEventListener('keydown', onWindowKeyDown, true)
      window.removeEventListener('verticals:focus-field', onFocusAsked)
      window.removeEventListener('resize', onResize)
      hoverQuery?.removeEventListener('change', onCanHover)
      document.fonts?.removeEventListener('loadingdone', onFontsLoaded)
      stopNews?.()
      stopFinding?.()
      stopPictures?.()
      if (stillTimer) clearTimeout(stillTimer)
      if (flyingTimer) clearTimeout(flyingTimer)
    })

    return {
      body, shape, surface, line, input, mirror, pivot, answerMeasure, leadMeasure, chipsBox, choicesBox, flying, still, lines, state,
      hovered, answerChips, shownChips, moreChips, undoable, answerText, answerSays, leadText, changesText, stopping,
      stepShown, holding, width, shownLines, height, stepShift, tagsShown, lineMode, measure, moved, send, onShapeMove,
      onTagsEnter, onLeave, onShapeClick, captionLeaving,
    }
  })

  const text = commandFilter.text
  // The field's value is the element's property, put back after each drawing where it differs. A controlled React
  // textarea would also write the words into its text content.
  useLayoutEffect(() => {
    const el = s.input.value
    if (el && el.value !== text) el.value = text
  })

  const state = s.state.value
  const words = circleWords.value
  const ask = openAsk.value
  const answerChips = s.answerChips.value
  const answerText = s.answerText.value
  const leadText = s.leadText.value
  const changesText = s.changesText.value
  const moreChips = s.moreChips.value
  const stopping = s.stopping.value
  const stepShown = s.stepShown.value
  const tagsShown = s.tagsShown.value
  const lineMode = s.lineMode.value
  const shownLines = s.shownLines.value
  const stopClick = (event: MouseEvent, then: () => void) => {
    event.stopPropagation()
    then()
  }
  return (
    <div {...fallthrough({
      className: 'circle-field',
      'data-cap': 'search',
      'data-state': state,
      'data-game': mascot.game ?? undefined,
      'data-pointed': s.hovered.value ? '' : undefined,
      'data-focused': circle.focused ? '' : undefined,
      'data-holding': s.holding.value ? '' : undefined,
      'data-flying': s.flying.value ?? undefined,
      onPointerLeave: s.onLeave,
    }, attrs)}>
      <div className="circle-field__above">
        {above}
        <MovingStack />
        <CircleTags shown={tagsShown} onPointerEnter={s.onTagsEnter} agent={agentTag} />
        <div className={cx('circle-field__bridge', { 'is-shown': tagsShown })} aria-hidden="true"></div>
      </div>
      <div ref={bindRef(s.body)} className="circle-field__body">
        <div
          ref={bindRef(s.shape)}
          className="circle-field__shape"
          style={sx({ width: `${s.width.value}px`, height: `${s.height.value}px` })}
          onPointerEnter={(event) => s.onShapeMove(event.nativeEvent)}
          onPointerMove={(event) => s.onShapeMove(event.nativeEvent)}
          onClick={s.onShapeClick}
        >
          <div ref={bindRef(s.surface)} className="circle-field__surface" aria-hidden="true"></div>
          <div className="circle-field__words" data-cap="search-input">
            <textarea
              ref={bindRef(s.input)}
              rows={1}
              aria-label={circleCaption.value}
              autoComplete="off"
              spellCheck="false"
              style={sx({ height: `${shownLines * LINE}px`, overflowY: s.lines.value > shownLines ? 'auto' : 'hidden' })}
              onKeyUp={() => s.moved()}
              onPointerUp={() => s.moved()}
              onScroll={() => s.measure()}
              onFocus={() => {
                circle.focused = true
                s.moved()
              }}
              onBlur={() => { circle.focused = false }}
            ></textarea>
            <div ref={bindRef(s.mirror)} className="circle-field__mirror" aria-hidden="true"></div>
            {!text && s.captionLeaving.value ? (
              <span key={`out:${s.captionLeaving.value}`} className="circle-field__caption circle-field__caption--out" aria-hidden="true"
                onAnimationEnd={() => { s.captionLeaving.value = null }}>{s.captionLeaving.value}</span>
            ) : null}
            {!text ? <span key={circleCaption.value} className="circle-field__caption" aria-hidden="true">{circleCaption.value}</span> : null}
          </div>
          <button
            type="button"
            className={cx('circle-field__send', { 'is-shown': !!text })}
            aria-label={reporting.value ? 'Make the report' : inboxWriting.value ? 'Write it down' : 'Send to the agent'}
            tabIndex={text ? 0 : -1}
            onClick={(event) => stopClick(event, s.send)}
          >
            <svg viewBox="0 0 24 24" width="24" height="24" aria-hidden="true">
              <path d="M12 21.5V3M12 3 5 10M12 3l7 7" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          </button>
          {words && state === 'answer' ? (
            <div
              className={cx('circle-field__answer', [`circle-field__answer--${words.kind}`, { 'circle-field__answer--chips': answerChips.length }])}
              data-role="circle-answer"
              aria-label={words.kind === 'answer' ? `${s.answerSays.value}. Press any key to reply` : undefined}
            >
              {leadText ? <p className="circle-field__answer-lead">{leadText}</p> : null}
              {answerText || !answerChips.length ? (
                <p className="circle-field__answer-words">{answerText}{words.kind === 'answer'
                  ? <span className="circle-field__answer-caret" aria-hidden="true"></span> : null}</p>
              ) : null}
              {changesText ? <p className="circle-field__answer-changes" data-role="circle-ask-changes">{changesText}</p> : null}
              {answerChips.length ? (
                <div ref={bindRef(s.chipsBox)} className="circle-field__answer-chips">
                  <AgentChips links={s.shownChips.value} />
                  {moreChips ? <p className="circle-field__answer-more" data-role="circle-answer-more">{`${moreChips} more`}</p> : null}
                </div>
              ) : null}
              {s.undoable.value && words.kind === 'answer' ? <AnswerUndo answer={words.answer} className="circle-field__answer-undo" /> : null}
              {words.kind === 'ask' && ask?.options.length ? (
                <div ref={bindRef(s.choicesBox)} className="circle-field__answer-choices">
                  {ask.tool === QUESTION_TOOL ? <AnswerSuggestions options={ask.options} /> : ask.options.map((option) => (
                    <button key={option.value} type="button" className="circle-field__answer-choice"
                      onClick={(event) => stopClick(event, () => void decide(openAsk.value!.requestId, option.value))}>{option.label}</button>
                  ))}
                </div>
              ) : null}
            </div>
          ) : null}
          <p ref={bindRef(s.answerMeasure)} className="circle-field__answer-measure" aria-hidden="true">
            {answerText}{changesText ? <><br />{changesText}</> : null}
          </p>
          <p ref={bindRef(s.leadMeasure)} className="circle-field__answer-measure circle-field__answer-measure--lead" aria-hidden="true">{leadText}</p>
          {stopping ? (
            <button type="button" className="circle-field__stop" aria-label="Stop the agent" onClick={(event) => stopClick(event, () => void stop())}>
              <span aria-hidden="true"></span>
            </button>
          ) : null}
          <AgentStep shown={stepShown} />
          <span
            ref={bindRef(s.pivot)}
            className={cx('circle-field__pivot', { 'is-turning': state === 'working' && !ask, 'is-stopping': stopping && !stepShown })}
            style={sx({ translate: `${s.stepShift.value}px 0` })}
          >
            <span
              ref={bindRef(s.line)}
              className={cx('circle-field__line', {
                'is-blinking': lineMode === 'caret' && circle.focused && s.still.value, 'is-hidden': lineMode === 'hidden',
              })}
              aria-hidden="true"
            ></span>
          </span>
          {mascot.game ? <CircleGame key={mascot.game} game={mascot.game} /> : null}
        </div>
      </div>
    </div>
  )
})
