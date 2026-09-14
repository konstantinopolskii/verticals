<script setup lang="ts">
import './goal-affordance.css'
import { computed } from 'vue'
import { goalWashAlpha, goalWashInk } from '../../lib/goalColor'
import { devPaletteFor, rgbaFromHex } from '../../lib/devPalette'

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
  const wash = goalWashInk(props.color)
  const palette = devPaletteFor(props.color)
  const checkColor = palette?.tick
    ? rgbaFromHex(palette.tick.color, palette.tick.opacity)
    : goalWashAlpha(props.color, 0.65)
  // D225 (KK, 2026-08-14): the no-colour ("black") goal's box swaps greys with the add-row
  // placeholder box — committed items read a shade darker (#e5e5e5) than the add affordance
  // (242), not the other way round. Colourless only; hued boxes keep the wash formula.
  const neutralBox = props.color ? `rgb(${wash.washRgb})` : '#e5e5e5'
  return {
    '--goal-affordance-background': palette?.box
      ? rgbaFromHex(palette.box.color, palette.box.opacity)
      : neutralBox,
    '--goal-affordance-hover-background': palette?.box
      ? rgbaFromHex(palette.box.color, palette.box.opacity)
      : neutralBox,
    '--goal-affordance-check-color': checkColor
      ? checkColor
      : `rgba(${wash.inkRgb}, 0.65)`,
    '--goal-affordance-hover-check-color': '#ffffff',
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
