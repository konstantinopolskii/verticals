<script setup lang="ts">
import AppIcon from './AppIcon.vue'
import { ref } from 'vue'
import { knobSections, resetKnobs, setKnob, tuning, type Knob } from '../lib/tuning'
import './devTuningPanel.css'

const open = ref(false)

function update(knob: Knob, event: Event): void {
  const input = event.target as HTMLInputElement
  if (typeof knob.value === 'number') {
    const value = Number(input.value)
    if (Number.isFinite(value)) setKnob(knob.key, value)
  } else if (input.value.trim()) {
    setKnob(knob.key, input.value.trim())
  }
}
</script>

<template>
  <button
    type="button"
    class="dev-tuning-panel__trigger"
    aria-label="Open motion settings"
    :aria-expanded="open"
    @click="open = !open"
  >Motion</button>

  <aside v-if="open" class="dev-tuning-panel" data-role="dev-tuning-panel" aria-label="Motion and look settings">
    <header class="dev-tuning-panel__header">
      <div>
        <strong>Motion and look</strong>
        <p>Live preview. Saved in this browser.</p>
      </div>
      <button type="button" class="dev-tuning-panel__close" aria-label="Close motion settings" @click="open = false">
        <AppIcon name="x" :size="16" />
      </button>
    </header>

    <details v-for="section in knobSections" :key="section.title">
      <summary>{{ section.title }}</summary>
      <div v-for="knob in section.knobs" :key="knob.key" class="dev-tuning-panel__row">
        <label :for="`tuning-${knob.key}`">{{ knob.label }}</label>
        <template v-if="typeof knob.value === 'number'">
          <input
            :id="`tuning-${knob.key}`"
            type="range"
            :min="knob.min"
            :max="knob.max"
            :step="knob.step"
            :value="tuning[knob.key]"
            @input="update(knob, $event)"
          >
          <output>{{ tuning[knob.key] }}{{ knob.unit }}</output>
        </template>
        <input
          v-else
          :id="`tuning-${knob.key}`"
          type="text"
          :value="tuning[knob.key]"
          @change="update(knob, $event)"
        >
      </div>
    </details>

    <button type="button" class="dev-tuning-panel__reset" @click="resetKnobs">Reset motion and look</button>
  </aside>
</template>
