<script setup lang="ts">
// Out of focus for a window (docs/design-handoff S2.P6): under the conversation the window is itself at 1 px and four
// still copies of it, each more blurred and shown from further down, so its name reads and its foot is soft; its veil
// builds the same way in its own pale colour. At the side, its whole body below the name takes the strongest step. The
// copies are pictures of the window taken as it steps back and again when its words change; they stay out of the
// reader's selection and the find bar.
import { nextTick, onBeforeUnmount, ref, watch } from 'vue'

const props = withDefaults(defineProps<{
  mode: 'none' | 'under' | 'side'
  /** The window's pale colour, "r, g, b". */
  pale?: string
  /** How far down the name reaches, for the side's blur. */
  head?: number
  /** The element that scrolls the window, whose visible part the copies show. */
  scroller?: HTMLElement | null
}>(), { pale: '245, 245, 247', head: 64, scroller: null })

const live = ref<HTMLElement | null>(null)
const copies = ref<HTMLElement[]>([])
const frame = ref({ top: 0, height: 0 })
const STEPS = [
  { r: 'var(--vt-blur-1)', a: 0.06, b: 0.16 },
  { r: 'var(--vt-blur-2)', a: 0.16, b: 0.3 },
  { r: 'var(--vt-blur-3)', a: 0.3, b: 0.44 },
  { r: 'var(--vt-blur-4)', a: 0.44, b: 0.6 },
]

let observer: MutationObserver | null = null
let pending = 0
function paint(): void {
  pending = 0
  const source = live.value
  if (!source || props.mode === 'none') return
  const scroller = props.scroller
  frame.value = { top: scroller?.scrollTop ?? 0, height: scroller?.clientHeight ?? source.offsetHeight }
  for (const copy of copies.value) {
    const picture = source.cloneNode(true) as HTMLElement
    picture.removeAttribute('data-live')
    // A picture, not a second window: nothing in it may be found as a goal, a control or a field.
    for (const el of [picture, ...picture.querySelectorAll<HTMLElement>('*')]) {
      for (const name of ['id', 'data-goal-id', 'data-row-key', 'data-role', 'data-cap', 'data-doc', 'data-link', 'contenteditable', 'tabindex']) {
        el.removeAttribute(name)
      }
    }
    picture.style.transform = `translateY(${-frame.value.top}px)`
    copy.replaceChildren(picture)
  }
}
function schedule(): void {
  if (!pending) pending = requestAnimationFrame(paint)
}
watch(() => props.mode, async (mode) => {
  observer?.disconnect()
  observer = null
  if (mode === 'none') return
  await nextTick()
  paint()
  if (live.value && typeof MutationObserver !== 'undefined') {
    observer = new MutationObserver(schedule)
    observer.observe(live.value, { subtree: true, childList: true, characterData: true, attributes: true })
  }
}, { immediate: true })
onBeforeUnmount(() => {
  observer?.disconnect()
  if (pending) cancelAnimationFrame(pending)
})
</script>

<template>
  <div class="pblur" :class="`pblur--${mode}`" :style="{ '--pale': pale, '--pblur-top': `${frame.top}px`, '--pblur-height': `${frame.height}px`, '--pblur-head': `${head}px` }">
    <div ref="live" class="pblur__live" data-live><slot /></div>
    <template v-if="mode === 'under'">
      <div
        v-for="(step, i) in STEPS"
        :key="i"
        :ref="(el) => { if (el) copies[i] = el as HTMLElement }"
        class="pblur__copy"
        :style="{ '--r': step.r, '--a': step.a, '--b': step.b }"
        inert
        aria-hidden="true"
      ></div>
      <div class="pblur__veil" aria-hidden="true"></div>
    </template>
    <template v-else-if="mode === 'side'">
      <div :ref="(el) => { if (el) copies[0] = el as HTMLElement }" class="pblur__copy pblur__copy--side" inert aria-hidden="true"></div>
      <div class="pblur__veil pblur__veil--side" aria-hidden="true"></div>
    </template>
  </div>
</template>

<style>
.pblur { position: relative; }
.pblur--under > .pblur__live { filter: blur(var(--vt-blur-0)); }
.pblur__copy {
  position: absolute;
  left: 0;
  right: 0;
  top: var(--pblur-top);
  height: var(--pblur-height);
  overflow: hidden;
  pointer-events: none;
  user-select: none;
  filter: blur(var(--r));
  will-change: opacity;
  -webkit-mask-image: linear-gradient(to bottom, transparent calc(var(--a) * 100%), #000 calc(var(--b) * 100%));
  mask-image: linear-gradient(to bottom, transparent calc(var(--a) * 100%), #000 calc(var(--b) * 100%));
}
.pblur__copy--side {
  --r: var(--vt-blur-4);
  -webkit-mask-image: linear-gradient(to bottom, transparent var(--pblur-head), #000 calc(var(--pblur-head) + 12px));
  mask-image: linear-gradient(to bottom, transparent var(--pblur-head), #000 calc(var(--pblur-head) + 12px));
}
.pblur__veil {
  position: absolute;
  left: 0;
  right: 0;
  top: var(--pblur-top);
  height: var(--pblur-height);
  pointer-events: none;
  background: linear-gradient(to bottom, rgba(var(--pale), .04) 0, rgba(var(--pale), .16) 12%, rgba(var(--pale), .44) 40%,
    rgba(var(--pale), .6) 60%, rgba(var(--pale), .6));
}
.pblur__veil--side {
  background: linear-gradient(to bottom, rgba(var(--pale), 0) var(--pblur-head), rgba(var(--pale), .6) calc(var(--pblur-head) + 12px));
}
</style>
