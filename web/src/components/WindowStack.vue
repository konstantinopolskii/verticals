<script setup lang="ts">
// The windows over the board (docs/design-handoff S3.P2, S3.P3): one in the centre, 720 px; a goal or a page a card 32 px
// from the top, a document full height, half a pixel from the top and the bottom (docs/design/doc-full-height.md); the
// others at the sides, 200 px of each in view, stepped back to 94%, softer and lit less; beyond the neighbours they wait
// off the screen in the order they opened. Under the conversation the centre one steps back and blurs down its height.
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import AppIcon from './AppIcon.vue'
import ProgressiveBlur from './ProgressiveBlur.vue'
import GoalWindowBody from './GoalWindowBody.vue'
import PageWindowBody from './PageWindowBody.vue'
import DocWindowBody from './DocWindowBody.vue'
import { agentChat } from '../lib/agentChat'
import { closeWindow, closeWindows, focusWindow, stepWindow, windows, type VtWindow } from '../lib/windows'
import { goalLight } from '../lib/look'
import { store } from '../store'
import { curve, reducedMotion, timing } from '../lib/motion'
import './windowStack.css'

const room = reactive({ width: typeof innerWidth === 'number' ? innerWidth : 1440 })
function onResize(): void { room.width = innerWidth }
onMounted(() => window.addEventListener('resize', onResize))
onBeforeUnmount(() => window.removeEventListener('resize', onResize))

const WIDTH = computed(() => Math.min(720, room.width - 32))
const SIDE = 200
const GAP = 24

function colorOf(win: VtWindow): string | null {
  return win.kind === 'goal' ? (store.state.goalDetail?.id === win.target ? store.state.goalDetail?.color ?? null : null) : null
}
function light(win: VtWindow) {
  return goalLight(colorOf(win))
}

/** Where a window stands for its place in the row relative to the one in front. */
function place(index: number) {
  const k = index - windows.front
  const w = WIDTH.value
  const centre = (room.width - w) / 2
  if (k === 0) return { left: centre, origin: '50% 0', scale: agentChat.open ? 'var(--vt-step-back)' : '1', z: 286 }
  const shows = room.width >= w + 2 * SIDE + 2 * GAP ? SIDE : 0
  const stepped = w * 0.94 + GAP
  if (k < 0) {
    const right = shows - (-k - 1) * stepped - (shows ? 0 : GAP)
    return { left: right - w, origin: '100% 0', scale: 'var(--vt-step-side)', z: 285 }
  }
  const left = room.width - shows + (k - 1) * stepped + (shows ? 0 : GAP)
  return { left, origin: '0 0', scale: 'var(--vt-step-side)', z: 285 }
}

function mode(index: number): 'none' | 'under' | 'side' {
  if (index !== windows.front) return 'side'
  return agentChat.open ? 'under' : 'none'
}

const scrollers = ref<Record<string, HTMLElement | null>>({})
const frames = ref<Record<string, HTMLElement | null>>({})

/* Pop out (S3.P2.013): the window grows out of the row or link it was opened from. Its motion is reworked in the
   motion pass (R.074); this is the drawn path. */
watch(() => windows.origin, async (origin) => {
  if (!origin) return
  await nextTick()
  const el = frames.value[origin.key]
  windows.origin = null
  if (!el) return
  const to = el.getBoundingClientRect()
  if (reducedMotion()) {
    el.animate([{ opacity: 0 }, { opacity: 1 }], timing('fade', 'large'))
    return
  }
  const from = origin.rect
  const scale = Math.max(0.1, from.width / to.width)
  el.animate([
    { transform: `translate(${from.left - to.left}px, ${from.top - to.top}px) scale(${scale})`, opacity: 0.6 },
    { transform: 'none', opacity: 1 },
  ], { duration: 400, easing: curve('large') })
})

/* A two-finger swipe moves one window, when the window under it can't scroll that way (S3.P3.010, .025). */
let swiped = 0
let swipeAt = 0
function onWheel(event: WheelEvent): void {
  if (Math.abs(event.deltaX) <= Math.abs(event.deltaY)) return
  const body = (event.target as HTMLElement).closest<HTMLElement>('.vt-window__body, .doc-window, .page-window')
  if (body && body.scrollWidth > body.clientWidth) return
  const now = performance.now()
  if (now - swipeAt > 300) swiped = 0
  swipeAt = now
  swiped += event.deltaX
  if (Math.abs(swiped) < 60) return
  stepWindow(swiped > 0 ? 1 : -1)
  swiped = -Math.sign(swiped) * 1000
}

/* A document's head (round 2, frame f2b): its facts, then its versions, which open history in Documents. Its open comments
   are counted above the field, once (DocCheck.vue, docs/design/doc-comments-inline.md). */
type HeadPart = { text: string; act?: 'versions' }
function headParts(win: VtWindow): HeadPart[] {
  const parts: HeadPart[] = (win.facts ?? []).map((text) => ({ text }))
  if ((win.versions ?? 0) > 1) parts.push({ text: `${win.versions} versions`, act: 'versions' })
  return parts
}
function onHeadAct(win: VtWindow): void {
  closeWindow(win.key)
  void store.openHistoryOf(win.target)
}

function onWindowClick(index: number, event: MouseEvent): void {
  if (index !== windows.front) {
    event.preventDefault()
    event.stopPropagation()
    focusWindow(index)
    return
  }
  if (!agentChat.open) return
  agentChat.open = false
  const field = document.activeElement
  if (field instanceof HTMLElement && field.closest('[data-cap="search-input"]')) field.blur()
}
</script>

<template>
  <div class="window-stack" data-role="window-stack" @wheel.passive="onWheel">
    <TransitionGroup name="vt-window">
      <section
        v-for="(win, index) in windows.list"
        :key="win.key"
        :ref="(el) => { frames[win.key] = el as HTMLElement | null }"
        class="vt-window vt-shadow"
        :class="{
          'vt-shadow--lit': !!light(win),
          'vt-shadow--side': index !== windows.front,
          'vt-shadow--back': index === windows.front && agentChat.open,
          'vt-window--front': index === windows.front,
          'vt-window--side': index !== windows.front,
          'vt-window--full': win.kind === 'doc',
        }"
        :data-window="win.kind"
        :data-key="win.key"
        :aria-label="index === windows.front ? win.title : `${win.title}. Bring to the centre`"
        :style="{
          left: `${place(index).left}px`,
          width: `${WIDTH}px`,
          zIndex: place(index).z,
          transformOrigin: place(index).origin,
          '--vt-window-scale': place(index).scale,
          ...(light(win) ?? {}),
        }"
        @click.capture="onWindowClick(index, $event)"
      >
        <header v-if="win.kind !== 'goal'" class="vt-window__head"
          :class="{ 'vt-window__head--doc': win.kind === 'doc', 'is-titled': win.kind === 'doc' && win.titled }">
          <template v-if="win.kind === 'doc'">
            <AppIcon class="vt-window__icon" name="file" :size="16" />
            <p class="vt-window__facts" data-role="doc-facts">
              <template v-if="win.titled"><b class="vt-window__title" data-role="doc-head-title">{{ win.title }}</b><span class="vt-window__sep">·</span></template>
              <template v-for="(part, i) in headParts(win)" :key="i">
                <span v-if="i" class="vt-window__sep">·</span>
                <button v-if="part.act" type="button" class="vt-window__act" :data-role="`doc-${part.act}`"
                  @click.stop="onHeadAct(win)">{{ part.text }}</button>
                <template v-else>{{ part.text }}</template>
              </template>
            </p>
          </template>
          <h2 v-else class="vt-window__name" :title="win.title">{{ win.title }}</h2>
          <a v-if="win.kind === 'page'" class="vt-window__button" :href="win.target" target="_blank" rel="noreferrer"
            aria-label="Open in Chrome" title="Open in Chrome"><AppIcon name="arrow-up-right" :size="16" /></a>
          <button type="button" class="vt-window__button" aria-label="Close" @click.stop="closeWindow(win.key)"><AppIcon name="x" :size="16" /></button>
        </header>
        <button v-else type="button" class="vt-window__button vt-window__close" aria-label="Back to the board" data-role="window-close"
          @click.stop="closeWindows()"><AppIcon name="x" :size="16" /></button>
        <div :ref="(el) => { scrollers[win.key] = el as HTMLElement | null }" class="vt-window__body">
          <ProgressiveBlur :mode="mode(index)" :pale="light(win)?.['--vt-pale'] ?? '245, 245, 247'" :scroller="scrollers[win.key]">
            <GoalWindowBody v-if="win.kind === 'goal'" :id="win.target" :front="index === windows.front" />
            <DocWindowBody v-else-if="win.kind === 'doc'" :id="win.target" :part="win.part" />
            <PageWindowBody v-else :url="win.target" />
          </ProgressiveBlur>
        </div>
      </section>
    </TransitionGroup>
  </div>
</template>
