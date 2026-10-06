<script setup lang="ts">
// The circle and the field (docs/design-handoff S1.P1, S1.P2): one black shape. At rest a circle with the mascot's line;
// pointed at, focused or holding words, a field whose line is your cursor, then your caret. Enter sends the words
// (`submit`); the board follows every letter through `commandFilter`.
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { store } from '../store'
import { commandFilter } from '../lib/commandFilter'
import { circle, circleCaption, circleState, circleWords, inboxWriting } from '../lib/circle'
import { agentChat, decide, openAsk, stop } from '../lib/agentChat'
import { plainWords } from '../lib/chatMarkdown'
import { closeWindows, windows } from '../lib/windows'
import { mascot, useMascot, watchBoardNews } from '../lib/mascot'
import { followWords } from '../lib/finding'
import { curve, reducedMotion } from '../lib/motion'
import { launch } from '../lib/chatFlight'
import { anyMenuOpen } from '../lib/cardLift'
import { defineKnobs, knob } from '../lib/tuning'
import CircleTags from './CircleTags.vue'
import MovingStack from './MovingStack.vue'
import { backspace as pickBackspace, escape as movingEscape, tab as pickTab } from '../lib/moving'
import { dots } from '../lib/spansDrag'
import './circleField.css'

defineKnobs('The field', [
  { key: 'field.maxLines', label: 'Lines before the field scrolls', value: 10, min: 1, max: 20, step: 1 },
])

defineProps<{ agentAvailable: boolean }>()
const emit = defineEmits<{ submit: [text: string] }>()

const ANSWER_MEASURE = 376
const ANSWER_PAD = 44
const PAD_LEFT = 32
const PAD_RIGHT = 84
const PAD_Y = 24
const LINE = 36
const CIRCLE = 84

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

const answerText = computed(() => (circleWords.value ? plainWords(circleWords.value.text) : ''))
const leadText = computed(() => (circleWords.value?.kind === 'ask' && circleWords.value.lead ? plainWords(circleWords.value.lead) : ''))
const stopping = computed(() => state.value === 'working' && circle.pointed)
/* Holding a goal over the spans, the field is a pill with the mascot; let go over it, it widens to hold what stands above
   it (S5.P3.002, .007, .039). Let go anywhere else, it stays the pill while the goal lands and the board comes back. */
const holding = computed(() => state.value === 'moving' && (store.state.drag.id !== null || dots.landing))

const width = computed(() => {
  if (state.value === 'answer') return Math.max(CIRCLE, Math.min((leadLines.value ? ANSWER_MEASURE : answerWidth.value) + 2 * ANSWER_PAD, ANSWER_MEASURE + 2 * ANSWER_PAD))
  if (stopping.value) return 132
  if (state.value === 'typing') {
    return Math.min(maxWidth.value, Math.max(300, Math.ceil(PAD_LEFT + PAD_RIGHT + textWidth(text.value) + 5)))
  }
  if (state.value === 'open') return Math.min(300, maxWidth.value)
  if (holding.value) return 120
  if (state.value === 'moving') return Math.min(circle.pointed ? 434 : 300, maxWidth.value)
  return mascot.pong ? 132 : CIRCLE
})
const shownLines = computed(() => Math.min(lines.value, knob('field.maxLines')))
const height = computed(() => {
  if (state.value === 'typing') return PAD_Y * 2 + shownLines.value * LINE
  if (state.value === 'answer') {
    const ask = circleWords.value?.kind === 'ask' ? 44 + (leadLines.value ? leadLines.value * 22 + 8 : 0) : 0
    return Math.max(CIRCLE, PAD_Y * 2 + answerLines.value * 22 + ask)
  }
  return CIRCLE
})
const wide = computed(() => state.value === 'open' || state.value === 'typing' || state.value === 'answer'
  || (state.value === 'moving' && !holding.value))
const tagsShown = computed(() => (circle.pointed && wide.value) || circle.focused || agentChat.open)

/* Where the line stands: the mascot's at rest, your hand over the field, your caret once the field has it. */
const lineMode = computed(() => {
  if (state.value === 'answer') return 'hidden'
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
watch(answerText, async () => {
  await nextTick()
  const el = answerMeasure.value
  if (!el) return
  answerLines.value = Math.min(3, Math.max(1, Math.round(el.getBoundingClientRect().height / 22)))
  // The blinking line after the words takes its 5 px on the last line.
  answerWidth.value = answerLines.value > 1 ? ANSWER_MEASURE : Math.min(ANSWER_MEASURE, Math.ceil(el.scrollWidth) + 6)
}, { immediate: true, flush: 'post' })
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
  document.documentElement.style.setProperty('--moving-tags-shift', `${tags ? tags + 8 : 0}px`)
}, { immediate: true })

/* While the agent works the line turns; when it answers it ends upright (S2.P3.003). */
watch(() => state.value === 'working', (working, was) => {
  const el = pivot.value
  if (!el || working || !was) return
  const from = getComputedStyle(el).transform
  if (from && from !== 'none') el.animate([{ transform: from }, { transform: 'none' }], { duration: 165, easing: curve('large') })
})

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

function onInput(event: Event): void {
  commandFilter.text = (event.target as HTMLTextAreaElement).value
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
function clear(): void {
  commandFilter.text = ''
  moved()
}
function send(): void {
  const words = commandFilter.text.trim()
  if (!words) return
  // In the Inbox they become the first card in Today, so no balloon takes them up (lib/inbox.ts).
  if (inboxWriting.value) {
    emit('submit', words)
    return
  }
  // Your words rise from where they stand into your balloon, and the field is the circle again (S2.P3.019).
  const box = input.value?.getBoundingClientRect()
  if (box) launch('sent', box.left, box.top + (LINE - 22) / 2)
  fly('sent')
  emit('submit', words)
}
function onKeyDown(event: KeyboardEvent): void {
  if (event.isComposing) return
  if (event.key === 'Enter' && !event.shiftKey) {
    event.preventDefault()
    send()
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
  if (event.key === 'Escape' && circleWords.value?.kind === 'answer') {
    agentChat.answer = null
    return
  }
  if (event.metaKey || event.ctrlKey || event.altKey || event.key.length !== 1 || event.key === ' ') return
  const target = event.target instanceof HTMLElement ? event.target : null
  if (target?.closest('input, textarea, select, button, [contenteditable="true"], [role="dialog"], [role="menu"]')) return
  if (anyMenuOpen() || store.state.drag.id || store.state.drag.pending) return
  event.preventDefault()
  if (circleWords.value?.kind === 'answer') reply()
  commandFilter.text += event.key
  focusField()
}
function onShapeClick(): void {
  if (circleWords.value?.kind === 'answer') reply()
  else if (!circleWords.value) focusField()
}
function onResize(): void { room.width = innerWidth }

defineExpose({ focusField })

let stopNews: (() => void) | null = null
let stopFinding: (() => void) | null = null
onMounted(() => {
  const match = /^\/search\/(.*)/.exec(location.pathname)
  if (match?.[1]) { try { commandFilter.text = decodeURIComponent(match[1]) } catch { commandFilter.text = match[1] } }
  window.addEventListener('keydown', onWindowKeyDown, true)
  window.addEventListener('resize', onResize)
  document.fonts?.addEventListener('loadingdone', onFontsLoaded)
  stopNews = watchBoardNews()
  stopFinding = followWords(() => commandFilter.text, () => store.state.board)
  void document.fonts?.ready.then(() => void nextTick(measure))
})
onBeforeUnmount(() => {
  window.removeEventListener('keydown', onWindowKeyDown, true)
  window.removeEventListener('resize', onResize)
  document.fonts?.removeEventListener('loadingdone', onFontsLoaded)
  stopNews?.()
  stopFinding?.()
  if (stillTimer) clearTimeout(stillTimer)
  if (flyingTimer) clearTimeout(flyingTimer)
})
</script>

<template>
  <div
    class="circle-field"
    data-cap="search"
    :data-state="state"
    :data-pong="mascot.pong ? '' : undefined"
    :data-focused="circle.focused ? '' : undefined"
    :data-holding="holding ? '' : undefined"
    :data-flying="flying ?? undefined"
    @pointerleave="onLeave"
  >
    <div class="circle-field__above">
      <slot name="above" />
      <MovingStack />
      <CircleTags :shown="tagsShown" @pointerenter="onTagsEnter">
        <template #agent><slot name="agent-tag" /></template>
      </CircleTags>
      <div class="circle-field__bridge" :class="{ 'is-shown': tagsShown }" aria-hidden="true"></div>
    </div>
    <div ref="body" class="circle-field__body">
      <div
        ref="shape"
        class="circle-field__shape"
        :style="{ width: `${width}px`, height: `${height}px` }"
        @pointerenter="onShapeMove"
        @pointermove="onShapeMove"
        @click="onShapeClick"
      >
        <div ref="surface" class="circle-field__surface" aria-hidden="true"></div>
        <div class="circle-field__words" data-cap="search-input">
          <textarea
            ref="input"
            :value="commandFilter.text"
            rows="1"
            :aria-label="circleCaption"
            autocomplete="off"
            spellcheck="false"
            :style="{ height: `${shownLines * LINE}px`, overflowY: lines > shownLines ? 'auto' : 'hidden' }"
            @input="onInput"
            @keydown="onKeyDown"
            @keyup="moved"
            @pointerup="moved"
            @select="moved"
            @scroll="measure"
            @focus="circle.focused = true; moved()"
            @blur="circle.focused = false"
          ></textarea>
          <div ref="mirror" class="circle-field__mirror" aria-hidden="true"></div>
          <span v-if="!commandFilter.text" class="circle-field__caption" aria-hidden="true">{{ circleCaption }}</span>
        </div>
        <button
          type="button"
          class="circle-field__send"
          :class="{ 'is-shown': !!commandFilter.text }"
          :aria-label="inboxWriting ? 'Write it down' : 'Send to the agent'"
          :tabindex="commandFilter.text ? 0 : -1"
          @click.stop="send"
        >
          <svg viewBox="0 0 24 24" width="24" height="24" aria-hidden="true">
            <path d="M12 21.5V3M12 3 5 10M12 3l7 7" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round" />
          </svg>
        </button>
        <div v-if="circleWords" class="circle-field__answer" :class="`circle-field__answer--${circleWords.kind}`" data-role="circle-answer"
          :aria-label="circleWords.kind === 'answer' ? `${answerText}. Press any key to reply` : undefined">
          <p v-if="leadText" class="circle-field__answer-lead">{{ leadText }}</p>
          <p class="circle-field__answer-words">{{ answerText }}<span v-if="circleWords.kind === 'answer'" class="circle-field__answer-caret" aria-hidden="true"></span></p>
          <div v-if="circleWords.kind === 'ask' && openAsk" class="circle-field__answer-choices">
            <button v-for="option in openAsk.options" :key="option.value" type="button" class="circle-field__answer-choice"
              @click.stop="decide(openAsk.requestId, option.value)">{{ option.label }}</button>
          </div>
        </div>
        <p ref="answerMeasure" class="circle-field__answer-measure" aria-hidden="true">{{ answerText }}</p>
        <p ref="leadMeasure" class="circle-field__answer-measure circle-field__answer-measure--lead" aria-hidden="true">{{ leadText }}</p>
        <button v-if="stopping" type="button" class="circle-field__stop" aria-label="Stop the agent" @click.stop="stop()">
          <span aria-hidden="true"></span>
        </button>
        <span ref="pivot" class="circle-field__pivot" :class="{ 'is-turning': state === 'working' && !openAsk, 'is-stopping': stopping }">
        <span
          ref="line"
          class="circle-field__line"
          :class="{ 'is-blinking': lineMode === 'caret' && circle.focused && still, 'is-hidden': lineMode === 'hidden' }"
          aria-hidden="true"
        ></span>
        </span>
        <template v-if="mascot.pong">
          <span class="circle-field__line circle-field__line--second" aria-hidden="true"></span>
          <span class="circle-field__ball-run" aria-hidden="true"><span class="circle-field__ball"></span></span>
        </template>
      </div>
    </div>
  </div>
</template>
