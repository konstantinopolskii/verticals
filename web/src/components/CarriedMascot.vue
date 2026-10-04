<script setup lang="ts">
// The mascot of the carried box's empty room (docs/design-handoff S4.P3, KK 2026-10-02): when the box keeps its place and
// the filter leaves part of it empty, the space is not to be filled. A faint dashed circle with the mascot's line stands
// there, and the line looks at the pointer. It says why the box is emptier ("No plans for this goal": KK 2026-10-04, its
// shy openers like "Ignore me" didn't explain and frustrated). A click makes it blink (the line closes into a dot), hop
// and squash, and say what it did ("Layout fix deployed"), then ask you to stop. Mouse only: it has no keyboard stop and
// no label, and nothing it does touches the board.
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { reducedMotion } from '../lib/motion'

const props = defineProps<{ on: boolean; words: string | null }>()

const POKES = [
  'Layout fix deployed', 'Edge case, handled', 'Please stop clicking', 'Don\'t touch me, please', 'I am focused on the layout',
  'Please', 'Don\'t', 'It can ruin the layout', 'Please', 'I can see you clicking',
]
const LINE = 10.8 // px: the line is this tall; blinking it shrinks it to a dot as wide as it is
const DOT = 1.8

const poked = ref<string | null>(null)
const text = computed(() => poked.value ?? props.words ?? '')
const gap = ref<HTMLElement | null>(null)
const orb = ref<HTMLElement | null>(null)
const line = ref<HTMLElement | null>(null)
const words = ref<HTMLElement | null>(null)
let pokes = 0

/** The height the mascot needs, its words included: the box shows it only where it fits. */
function need(): number {
  const o = orb.value
  const w = words.value
  return o && w ? o.offsetHeight + 4 + w.offsetHeight + 8 : 52
}
defineExpose({ need })

/** The line leans toward the pointer, up to 5 px, the farther the pointer the more. */
function look(event: PointerEvent): void {
  const el = orb.value
  const mark = line.value
  if (!el || !mark) return
  const r = el.getBoundingClientRect()
  const dx = event.clientX - (r.left + r.width / 2)
  const dy = event.clientY - (r.top + r.height / 2)
  const d = Math.hypot(dx, dy) || 1
  const k = Math.min(1, d / 120) * 5
  mark.style.transform = `translate(${((dx / d) * k).toFixed(1)}px, ${((dy / d) * k).toFixed(1)}px)`
}

watch(() => props.on, (on) => {
  if (on) {
    poked.value = null
    pokes = 0
    window.addEventListener('pointermove', look, { passive: true })
  } else {
    window.removeEventListener('pointermove', look)
  }
}, { immediate: true })
// another goal, another story: it tells that first again
watch(() => props.words, () => { poked.value = null; pokes = 0 })
onBeforeUnmount(() => window.removeEventListener('pointermove', look))

function poke(): void {
  const i = pokes
  pokes += 1
  // it explains first, then keeps asking: from the third line on, the asking goes round
  poked.value = POKES[i < POKES.length ? i : 2 + ((i - 2) % (POKES.length - 2))]!
  const el = orb.value
  const mark = line.value
  if (reducedMotion() || !el || !mark) return
  words.value?.animate([{ opacity: 0, transform: 'translateY(3px)' }, { opacity: 1, transform: 'none' }],
    { duration: 160, easing: 'cubic-bezier(.2, 0, 0, 1)' })
  // the blink: the line closes into a dot and opens again; it never fades
  mark.animate([
    { height: `${LINE}px`, marginTop: `${-LINE / 2}px` },
    { height: `${DOT}px`, marginTop: `${-DOT / 2}px`, offset: 0.28 },
    { height: `${DOT}px`, marginTop: `${-DOT / 2}px`, offset: 0.5 },
    { height: `${LINE}px`, marginTop: `${-LINE / 2}px` },
  ], { duration: 300, easing: 'cubic-bezier(.2, 0, 0, 1)' })
  // the hop: as high as the room over the circle allows, never into the plans above; a tight place only squashes
  const from = getComputedStyle(el).transform
  const room = gap.value ? el.getBoundingClientRect().top - gap.value.getBoundingClientRect().top : 12
  const tight = room < 9
  const up = tight ? 0 : Math.min(12, room - 6)
  const out = 'cubic-bezier(.2, .7, .3, 1)'
  const fall = 'cubic-bezier(.5, 0, .9, .6)'
  el.animate([
    { transform: from === 'none' ? 'translateY(0) scale(1, 1)' : from, offset: 0, easing: out },
    { transform: `translateY(-${up}px) scale(.94, ${tight ? 1 : 1.08})`, offset: 0.3, easing: fall },
    { transform: 'translateY(0) scale(1.14, .86)', offset: 0.5, easing: out },
    { transform: `translateY(-${(up / 4).toFixed(1)}px) scale(.97, ${tight ? 1 : 1.04})`, offset: 0.72, easing: fall },
    { transform: 'translateY(0) scale(1.03, .97)', offset: 0.88, easing: out },
    { transform: 'translateY(0) scale(1, 1)', offset: 1 },
  ], { duration: 640 })
}
</script>

<template>
  <div ref="gap" class="carried-gap" :class="{ 'carried-gap--on': on }" data-role="carried-gap" aria-hidden="true">
    <div class="carried-gap__mascot">
      <div ref="orb" class="carried-gap__orb" data-role="carried-mascot" @click="poke"><i ref="line"></i></div>
      <p ref="words" class="carried-gap__words" data-role="carried-words">{{ text }}</p>
    </div>
  </div>
</template>

<style>
/* The room the filter leaves in the box is clear; the mascot's circle is almost invisible there (KK: "even a bit more lighter"). */
.carried-gap { --carried-ghost: rgb(45 48 54 / 20%); flex: 1 1 0; min-height: 0; overflow: hidden; display: flex; }
.carried-gap__mascot {
  width: 100%;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 4px;
  padding: 4px 8px;
  opacity: 0;
  transform: translateY(4px) scale(.94);
  pointer-events: none;
  user-select: none;
  -webkit-user-select: none;
  transition: opacity 100ms cubic-bezier(.2, 0, 0, 1), transform 100ms cubic-bezier(.2, 0, 0, 1);
}
/* In as the plans go (the box keeps its height, so nothing settles first), out at once, so it never stands in the way of
   the plans coming back. */
.carried-gap--on .carried-gap__mascot {
  opacity: 1;
  transform: none;
  pointer-events: auto;
  transition: opacity 180ms cubic-bezier(.2, 0, 0, 1), transform 240ms var(--vt-ease-large);
}
.carried-gap__orb {
  position: relative;
  flex: none;
  box-sizing: border-box;
  width: 29px;
  height: 29px;
  border: 1.4px dashed var(--carried-ghost);
  border-radius: 50%;
  transform-origin: 50% 100%;
  cursor: pointer;
  -webkit-tap-highlight-color: transparent;
}
.carried-gap__orb > i {
  position: absolute;
  left: 50%;
  top: 50%;
  width: 1.8px;
  height: 10.8px;
  margin: -5.4px 0 0 -.9px;
  border-radius: 1px;
  background: var(--carried-ghost);
  transition: transform 140ms cubic-bezier(.2, 0, 0, 1);
}
/* The words say what is happening, so they read like the box's other words (the count, "See all"); the circle stays faint. */
.carried-gap__words { max-width: 100%; margin: 0; color: rgb(45 48 54 / 52%); font: 400 12px/16px var(--font-body); text-align: center; text-wrap: balance; }
.pattern-vertical-board__column--active .carried-gap__words { font-size: 15px; line-height: 20px; }
</style>
