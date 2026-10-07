<script setup lang="ts">
// The windows over the board (docs/design-handoff S3.P2, S3.P3): one in the centre, 720 px, 32 px from the top; the
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

/* A document's head (round 2, frame f2b): its facts, then its versions and its open comments, each opening its own
   place: history in Documents, the comments' sidebar. */
type HeadPart = { text: string; act?: 'versions' | 'comments' }
function headParts(win: VtWindow): HeadPart[] {
  const parts: HeadPart[] = (win.facts ?? []).map((text) => ({ text }))
  if ((win.versions ?? 0) > 1) parts.push({ text: `${win.versions} versions`, act: 'versions' })
  const comments = store.unresolvedCommentCount('doc', win.target)
  if (comments > 0) parts.push({ text: `${comments} ${comments === 1 ? 'comment' : 'comments'}`, act: 'comments' })
  return parts
}
function commentsOpenFor(win: VtWindow): boolean {
  const c = store.state.comments
  return c.open && c.targetType === 'doc' && c.targetId === win.target
}
function onHeadAct(win: VtWindow, act: 'versions' | 'comments'): void {
  if (act === 'comments') {
    if (commentsOpenFor(win)) store.closeCommentsPanel()
    else store.openCommentsPanel('doc', win.target)
    return
  }
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
                  :aria-expanded="part.act === 'comments' ? commentsOpenFor(win) : undefined"
                  @click.stop="onHeadAct(win, part.act)">{{ part.text }}</button>
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

<style>
.window-stack { position: fixed; inset: 0; z-index: 285; pointer-events: none; }
.vt-window {
  position: absolute;
  top: calc(32px + var(--titlebar-height));
  box-sizing: border-box;
  max-height: min(738px, 80vh);
  display: flex;
  flex-direction: column;
  border-radius: var(--vt-radius-window);
  background: #fff;
  overflow: hidden;
  pointer-events: auto;
  transform: scale(var(--vt-window-scale, 1));
  transition: left var(--vt-dur-shape) var(--vt-ease-large), transform var(--vt-dur-shape) var(--vt-ease-large),
    box-shadow var(--vt-dur-shape) var(--vt-ease-large);
  will-change: transform;
}
.vt-window.vt-shadow--lit { background: rgb(var(--vt-pale)); }
.vt-window--front.vt-shadow--back { transition-duration: var(--vt-dur-step); }
.vt-window--side { cursor: pointer; }
.vt-window--side .vt-window__button, .vt-window--side .goal-card-tools { visibility: hidden; }
.vt-window--side .vt-window__body { pointer-events: none; }
.vt-window__head { display: flex; align-items: center; gap: 8px; min-height: 52px; padding: 12px 12px 0 24px; box-sizing: border-box; }
.vt-window__name { flex: 1; min-width: 0; margin: 0; overflow: hidden; color: #000; font: 600 14px/20px var(--font-body);
  text-overflow: ellipsis; white-space: nowrap; }
/* A document's head, from the frame (round 5's `.dw-bar`): 52 px, the page icon, the facts at 13/20 in grey with its
   actions in black, the title at 14 px once it has scrolled up, a hairline under it then. */
.vt-window__head--doc { flex: none; height: 52px; min-height: 0; padding: 0 12px 0 24px; gap: 0; transition: box-shadow var(--vt-dur-fade) linear; }
.vt-window__head--doc.is-titled { box-shadow: 0 1px 0 rgb(45 48 54 / 10%); }
.vt-window__icon { flex: none; margin-right: 8px; color: rgb(0 0 0 / 38%); }
.vt-window__facts { flex: 1; min-width: 0; margin: 0; overflow: hidden; color: rgb(0 0 0 / 50%); font: 400 13px/20px var(--font-body);
  text-overflow: ellipsis; white-space: nowrap; }
.vt-window__title { color: #000; font-size: 14px; font-weight: 600; }
.vt-window__sep { margin: 0 6px; }
.vt-window__act { padding: 0; border: 0; background: none; color: #000; font: inherit; font-weight: 500; cursor: pointer; }
.vt-window__act:hover { text-decoration: underline; text-underline-offset: .2em; }
.vt-window__head--doc .vt-window__button { width: 32px; height: 32px; margin-left: 12px; border-radius: 16px; }
.vt-window__button { display: grid; flex: none; width: 28px; height: 28px; place-items: center; padding: 0; border: 0;
  border-radius: 14px; background: transparent; color: rgb(0 0 0 / 55%); cursor: pointer; }
.vt-window__button:hover { background: rgb(0 0 0 / 6%); color: #000; }
.vt-window__close { position: absolute; top: 14px; right: 12px; z-index: 5; }
.vt-window__body { min-height: 0; overflow-y: auto; overscroll-behavior: contain; }
.vt-window--front.vt-shadow--back .vt-window__body { overflow: hidden; }
.vt-window-enter-active, .vt-window-leave-active { transition: opacity var(--vt-dur-back) var(--vt-ease-large); }
.vt-window-enter-from, .vt-window-leave-to { opacity: 0; }
@media (prefers-reduced-motion: reduce) {
  .vt-window { transition: opacity var(--vt-crossfade) linear; }
}
</style>
