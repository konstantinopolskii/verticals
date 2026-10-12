<script setup lang="ts">
// The dots (docs/design-handoff S5.P2): while a goal is dragged they stand in a column's corner, in place of its period
// controls; resting the goal over them melts it in, and they grow and take its colours while the column's spans open.
import { computed } from 'vue'
import { store } from '../store'
import { goalLight } from '../lib/look'
import { findGoal } from '../lib/boardIndex'
import { spanGoal, VIEW_NAMES, type SpanScale } from '../lib/spans'
import { dots } from '../lib/spansDrag'
import './columnDots.css'

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
