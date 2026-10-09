<script setup lang="ts">
import './goal-affordance.css'
import { computed } from 'vue'
import { goalSquare } from '../../lib/look'

const props = withDefaults(defineProps<{
  kind: 'square' | 'ring'
  checked?: boolean
  done?: number
  total?: number
  color?: string | null
}>(), {
  checked: false,
  done: 0,
  total: 0,
  color: null,
})

const emit = defineEmits<{ toggle: [value: boolean] }>()

function onChange(event: Event) {
  emit('toggle', (event.target as HTMLInputElement).checked)
}

const squareStyle = computed(() => {
  const { box, check } = goalSquare(props.color)
  return {
    '--goal-affordance-background': box,
    '--goal-affordance-hover-background': box,
    '--goal-affordance-check-color': check,
    '--goal-affordance-hover-check-color': '#000000',
  }
})
</script>

<template>
  <label
    class="checkbox checkbox--size-s goal-affordance"
    :class="`goal-affordance--${kind}`"
    :data-role="kind === 'ring' ? 'milestone-ring' : 'leaf-square'"
    data-cap="complete"
    role="checkbox"
    :aria-checked="checked"
    :aria-label="kind === 'ring' ? `Milestone progress ${done} of ${total}` : 'Mark complete'"
    @click.stop
    @pointerdown.stop
  >
    <input
      type="checkbox"
      class="checkbox__input"
      :checked="checked"
      @change="onChange"
    >
    <span
      class="checkbox__box goal-affordance__square"
      data-role="checkbox-box"
      aria-hidden="true"
      :style="squareStyle"
    />
  </label>
</template>
