<script setup lang="ts">
// The circle and the field (docs/design-handoff S1.P1, S1.P2): one black shape. At rest a circle with the mascot's line;
// pointed at, focused or holding words, a field whose line is your cursor, then your caret. Enter sends the words
// (`submit`); the board follows every letter through `commandFilter`.
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { store } from '../store'
import { commandFilter } from '../lib/commandFilter'
import { circle, circleCaption, circleState } from '../lib/circle'
import { mascot, useMascot, watchBoardNews } from '../lib/mascot'
import { followWords } from '../lib/finding'
import { curve } from '../lib/motion'
import { anyMenuOpen } from '../lib/cardLift'
import { defineKnobs, knob } from '../lib/tuning'
import CircleTags from './CircleTags.vue'

defineKnobs('The field', [
  { key: 'field.tagsWhileTyping', label: 'Tags also show while typing (1 = on)', value: 0, min: 0, max: 1, step: 1 },
  { key: 'field.maxLines', label: 'Lines before the field scrolls', value: 10, min: 1, max: 20, step: 1 },
])

defineProps<{ agentAvailable: boolean }>()
const emit = defineEmits<{ submit: [text: string] }>()

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

const hand = ref<{ x: number; y: number } | null>(null)
const onTags = ref(false)
const caret = ref<{ x: number; y: number }>({ x: 0, y: 0 })
const selecting = ref(false)
const still = ref(true)
const lines = ref(1)
const room = reactive({ width: typeof innerWidth === 'number' ? innerWidth : 1440 })

const state = circleState
const text = computed(() => commandFilter.text)
const maxWidth = computed(() => Math.max(CIRCLE, Math.min(720, room.width - 32)))

let measureCtx: CanvasRenderingContext2D | null = null
function textWidth(value: string): number {
  if (!input.value) return 0
  measureCtx ??= document.createElement('canvas').getContext('2d')
  if (!measureCtx) return 0
  const style = getComputedStyle(input.value)
  measureCtx.font = `${style.fontWeight} ${style.fontSize} ${style.fontFamily}`
  return Math.max(0, ...value.split('\n').map((part) => measureCtx!.measureText(part).width))
}

const width = computed(() => {
  if (state.value === 'typing') {
    return Math.min(maxWidth.value, Math.max(300, Math.ceil(PAD_LEFT + PAD_RIGHT + textWidth(text.value) + 5)))
  }
  if (state.value === 'open') return Math.min(300, maxWidth.value)
  return mascot.pong ? 132 : CIRCLE
})
const shownLines = computed(() => Math.min(lines.value, knob('field.maxLines')))
const height = computed(() => (state.value === 'typing' ? PAD_Y * 2 + shownLines.value * LINE : CIRCLE))
const wide = computed(() => state.value === 'open' || state.value === 'typing')
const tagsShown = computed(() => (circle.pointed && wide.value)
  || (knob('field.tagsWhileTyping') === 1 && circle.focused))

/* Where the line stands: the mascot's at rest, your hand over the field, your caret once the field has it. */
const lineMode = computed(() => {
  if (!wide.value) return 'mascot'
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

function onInput(event: Event): void {
  commandFilter.text = (event.target as HTMLTextAreaElement).value
  moved()
}
function focusField(): void {
  const el = input.value
  if (!el) return
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
  emit('submit', words)
}
function onKeyDown(event: KeyboardEvent): void {
  if (event.isComposing) return
  if (event.key === 'Enter' && !event.shiftKey) {
    event.preventDefault()
    send()
    return
  }
  if (event.key === 'Escape') {
    event.preventDefault()
    event.stopPropagation()
    if (commandFilter.text) clear()
    else input.value?.blur()
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
  if (event.metaKey || event.ctrlKey || event.altKey || event.key.length !== 1 || event.key === ' ') return
  const target = event.target instanceof HTMLElement ? event.target : null
  if (target?.closest('input, textarea, select, button, [contenteditable="true"], [role="dialog"], [role="menu"]')) return
  if (anyMenuOpen() || store.state.drag.id || store.state.drag.pending) return
  event.preventDefault()
  commandFilter.text += event.key
  focusField()
}
function onCommandFocus(): void { clear(); focusField() }
function onComposerDraft(event: Event): void {
  commandFilter.text = (event as CustomEvent).detail?.text ?? ''
  focusField()
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
  window.addEventListener('verticals:command-focus', onCommandFocus)
  window.addEventListener('verticals:composer-draft', onComposerDraft)
  stopNews = watchBoardNews()
  stopFinding = followWords(() => commandFilter.text, () => store.state.board)
  void document.fonts?.ready.then(() => void nextTick(measure))
})
onBeforeUnmount(() => {
  window.removeEventListener('keydown', onWindowKeyDown, true)
  window.removeEventListener('resize', onResize)
  window.removeEventListener('verticals:command-focus', onCommandFocus)
  window.removeEventListener('verticals:composer-draft', onComposerDraft)
  stopNews?.()
  stopFinding?.()
  if (stillTimer) clearTimeout(stillTimer)
})
</script>

<template>
  <div
    class="circle-field"
    data-cap="search"
    :data-state="state"
    :data-pong="mascot.pong ? '' : undefined"
    :data-focused="circle.focused ? '' : undefined"
    @pointerleave="onLeave"
  >
    <div class="circle-field__above">
      <slot name="above" />
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
        @click="focusField"
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
          aria-label="Send to the agent"
          :tabindex="commandFilter.text ? 0 : -1"
          @click.stop="send"
        >
          <svg viewBox="0 0 24 24" width="24" height="24" aria-hidden="true">
            <path d="M12 21.5V3M12 3 5 10M12 3l7 7" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round" />
          </svg>
        </button>
        <span
          ref="line"
          class="circle-field__line"
          :class="{ 'is-blinking': lineMode === 'caret' && circle.focused && still, 'is-hidden': lineMode === 'hidden' }"
          aria-hidden="true"
        ></span>
        <template v-if="mascot.pong">
          <span class="circle-field__line circle-field__line--second" aria-hidden="true"></span>
          <span class="circle-field__ball-run" aria-hidden="true"><span class="circle-field__ball"></span></span>
        </template>
      </div>
    </div>
  </div>
</template>

<style>
.circle-field {
  position: fixed;
  left: 50%;
  bottom: 24px;
  z-index: 300;
  display: flex;
  flex-direction: column;
  align-items: center;
  transform: translateX(-50%);
  pointer-events: none;
  font-family: var(--font-body);
}
/* Toasts stand above the circle and its tags. */
.toast-stack[data-toast-stack] { bottom: calc(24px + 84px + 8px); }
.circle-field__above {
  position: relative;
  display: flex;
  align-items: flex-end;
  align-self: stretch;
  min-height: 28px;
}
.circle-field__above > * { pointer-events: auto; }
.circle-field__above > .circle-tags:not(.is-shown) { pointer-events: none; }
/* The 8 px between the tags and the field still counts as the field (S2.P2.012). */
.circle-field__bridge { position: absolute; left: 0; right: 0; bottom: -8px; height: 8px; pointer-events: none; }
.circle-field__bridge.is-shown { pointer-events: auto; }
.circle-field__body { margin-top: 8px; }
.circle-field__shape {
  position: relative;
  box-sizing: border-box;
  cursor: none;
  pointer-events: auto;
  transition: width var(--vt-dur-close) var(--vt-ease-large), height var(--vt-dur-close) var(--vt-ease-large);
}
.circle-field[data-state='open'] .circle-field__shape { transition-duration: var(--vt-dur-open); }
.circle-field[data-state='typing'] .circle-field__shape { transition: none; }
.circle-field[data-pong] .circle-field__shape { transition-duration: var(--vt-dur-shape); }
.circle-field[data-focused] .circle-field__shape { cursor: text; }
.circle-field__surface {
  position: absolute;
  inset: 0;
  border-radius: var(--vt-radius-field);
  background: #000;
}
.circle-field__words {
  position: absolute;
  left: 32px;
  right: 84px;
  bottom: 24px;
  color: #fff;
  opacity: 0;
  transition: opacity 100ms ease-out;
}
.circle-field:is([data-state='open'], [data-state='typing']) .circle-field__words { opacity: 1; }
.circle-field__words textarea,
.circle-field__mirror {
  display: block;
  box-sizing: border-box;
  width: 100%;
  margin: 0;
  padding: 0;
  border: 0;
  font: 400 28px/36px var(--font-body);
  letter-spacing: 0;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}
.circle-field__words textarea {
  position: relative;
  resize: none;
  outline: none;
  background: transparent;
  color: #fff;
  caret-color: transparent;
  cursor: inherit;
  scrollbar-width: none;
}
.circle-field__words textarea::-webkit-scrollbar { display: none; }
.circle-field__words textarea::selection { background: rgb(255 255 255 / 30%); }
.circle-field__mirror { position: absolute; left: 0; top: 0; visibility: hidden; pointer-events: none; }
.circle-field__caption {
  position: absolute;
  left: 0;
  bottom: 0;
  color: rgb(255 255 255 / 40%);
  font: 400 28px/36px var(--font-body);
  white-space: nowrap;
  pointer-events: none;
}
.circle-field__send {
  position: absolute;
  right: 30px;
  bottom: 30px;
  display: grid;
  width: 24px;
  height: 24px;
  place-items: center;
  padding: 0;
  border: 0;
  background: none;
  color: #fff;
  opacity: 0;
  pointer-events: none;
  cursor: pointer;
  transition: opacity var(--vt-dur-fade) ease-out;
}
.circle-field__send.is-shown { opacity: 1; pointer-events: auto; }
.circle-field__send:focus-visible { outline: 2px solid #fff; outline-offset: 3px; border-radius: 4px; }
.circle-field__line {
  position: absolute;
  left: 50%;
  top: 50%;
  width: 3px;
  height: 24px;
  margin: -12px 0 0 -1.5px;
  border-radius: 1.5px;
  background: #fff;
  pointer-events: none;
}
.circle-field__line.is-hidden { opacity: 0; }
.circle-field__line.is-blinking { animation: circle-field-blink 1060ms steps(1) infinite; }
@keyframes circle-field-blink { 0%, 55% { opacity: 1; } 56%, 100% { opacity: 0; } }

/* Pong (S1.P1.067): the oval, two lines and a ball. */
.circle-field[data-pong] .circle-field__line { animation: circle-field-paddle 1300ms var(--vt-ease-breath) infinite alternate; --side: -50px; }
.circle-field[data-pong] .circle-field__line--second { --side: 50px; animation-delay: -650ms; }
@keyframes circle-field-paddle {
  from { transform: translate(var(--side), -10px); }
  to { transform: translate(var(--side), 10px); }
}
.circle-field__ball-run {
  position: absolute;
  left: 50%;
  top: 50%;
  animation: circle-field-ball-x 900ms linear infinite alternate;
}
.circle-field__ball {
  display: block;
  width: 6px;
  height: 6px;
  margin: -3px 0 0 -3px;
  border-radius: 3px;
  background: #fff;
  animation: circle-field-ball-y 1300ms var(--vt-ease-breath) infinite alternate;
}
@keyframes circle-field-ball-x { from { transform: translateX(-44px); } to { transform: translateX(44px); } }
@keyframes circle-field-ball-y { from { transform: translateY(-12px); } to { transform: translateY(12px); } }

@media (prefers-reduced-motion: reduce) {
  .circle-field__shape, .circle-field[data-state='open'] .circle-field__shape { transition: none; }
  .circle-field__words { transition: opacity var(--vt-crossfade) linear; }
  .circle-field__line.is-blinking { animation: none; }
}
</style>
