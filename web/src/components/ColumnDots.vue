<script setup lang="ts">
// The dots (docs/design-handoff S5.P2): while a goal is dragged they stand in a column's corner, in place of its period
// controls; resting the goal over them melts it in, and they grow and take its colours while the column's spans open.
import { computed } from 'vue'
import { store } from '../store'
import { goalLight } from '../lib/look'
import { findGoal } from '../lib/boardIndex'
import { spanGoal, VIEW_NAMES, type SpanScale } from '../lib/spans'
import { dots } from '../lib/spansDrag'

const props = defineProps<{ vertical: SpanScale }>()
const held = computed(() => dots.held === props.vertical)
const colours = computed(() => {
  const out: Record<string, string> = {}
  if (!held.value) return out
  const id = store.state.drag.id ?? dots.goalId
  const color = id ? (findGoal(store.state.board, id) ?? spanGoal(id))?.color ?? null : null
  const light = goalLight(color)
  if (light && color) Object.assign(out, { '--dot-full': color, '--dot-light': `rgb(${light['--vt-tint']})` })
  return out
})
</script>

<template>
  <div
    class="column-dots"
    :class="{ 'column-dots--held': held }"
    :style="colours"
    data-role="column-dots"
    :data-dots-vertical="vertical"
    role="img"
    :aria-label="`Open ${VIEW_NAMES[vertical].toLowerCase()}`"
  >
    <i class="column-dots__dot"></i><i class="column-dots__dot column-dots__dot--middle"></i><i class="column-dots__dot"></i>
  </div>
</template>

<style>
/* 5 px dots in a 25 px row ending at the column's right padding, on the name's line; held, 9 px, 6 px apart, in the
   goal's colours with a soft glow (S5.P2.006, .009, .014). */
.column-dots {
  position: absolute;
  z-index: 3;
  top: 6px;
  right: 14px;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 5px;
  width: 25px;
  height: 20px;
  animation: column-dots-in 120ms ease-out;
}
.column-dots__dot {
  flex: none;
  width: 5px;
  height: 5px;
  border-radius: 50%;
  background: #d3d4d7;
  transition: width 200ms var(--vt-ease-large), height 200ms var(--vt-ease-large), background-color 200ms var(--vt-ease-large),
    box-shadow 200ms var(--vt-ease-large);
}
.column-dots__dot--middle { background: #2d3036; }
.column-dots--held { gap: 6px; }
.column-dots--held .column-dots__dot {
  width: 9px;
  height: 9px;
  background: var(--dot-light, #c9ea9a);
  box-shadow: 0 0 8px var(--dot-light, #c9ea9a);
}
.column-dots--held .column-dots__dot--middle { background: var(--dot-full, #92ce14); }
@keyframes column-dots-in { from { opacity: 0; } }
@media (prefers-reduced-motion: reduce) {
  .column-dots__dot { transition: none; }
}
</style>
