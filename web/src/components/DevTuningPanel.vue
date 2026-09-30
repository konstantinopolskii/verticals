<script setup lang="ts">
import AppIcon from './AppIcon.vue'
import { ref } from 'vue'
import { knobSections, resetKnobs, setKnob, tuning, type Knob } from '../lib/tuning'

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

<style>
.dev-tuning-panel__trigger {
  position: fixed;
  right: 262px;
  bottom: 16px;
  z-index: 300;
  height: 32px;
  padding: 0 12px;
  border: 1px solid rgb(45 48 54 / 18%);
  border-radius: 6px;
  background: rgb(255 255 255 / 92%);
  color: rgb(45 48 54 / 72%);
  font: inherit;
  font-size: 12px;
  cursor: pointer;
  box-shadow: 0 2px 8px rgb(0 0 0 / 8%);
}
.dev-tuning-panel__trigger:hover,
.dev-tuning-panel__close:hover,
.dev-tuning-panel__reset:hover { background: rgb(45 48 54 / 7%); }
.dev-tuning-panel {
  position: fixed;
  right: 16px;
  bottom: 56px;
  z-index: 301;
  width: 420px;
  max-height: min(700px, calc(100vh - 80px));
  box-sizing: border-box;
  overflow: auto;
  padding: 14px;
  border: 1px solid rgb(45 48 54 / 14%);
  border-radius: 8px;
  background: #fff;
  color: rgb(45 48 54);
  box-shadow: 0 8px 30px rgb(0 0 0 / 16%);
}
.dev-tuning-panel__header { display: flex; align-items: flex-start; justify-content: space-between; margin-bottom: 10px; }
.dev-tuning-panel__header strong { font-size: 14px; font-weight: 600; }
.dev-tuning-panel__header p { margin: 3px 0 0; color: rgb(45 48 54 / 52%); font-size: 11px; }
.dev-tuning-panel__close {
  display: grid;
  width: 20px;
  height: 20px;
  place-items: center;
  padding: 0;
  border: 0;
  background: transparent;
  color: rgb(45 48 54 / 55%);
  cursor: pointer;
}
.dev-tuning-panel details { border-top: 1px solid rgb(45 48 54 / 8%); }
.dev-tuning-panel summary { padding: 8px 0; color: rgb(45 48 54 / 74%); font-size: 12px; font-weight: 600; cursor: pointer; }
.dev-tuning-panel__row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 150px 52px;
  align-items: center;
  gap: 7px;
  min-height: 30px;
}
.dev-tuning-panel__row label { font-size: 11px; }
.dev-tuning-panel__row input[type='range'] { width: 150px; accent-color: rgb(45 48 54 / 70%); }
.dev-tuning-panel__row input[type='text'] {
  grid-column: 2 / 4;
  min-width: 0;
  height: 24px;
  box-sizing: border-box;
  border: 1px solid rgb(45 48 54 / 16%);
  border-radius: 4px;
  background: #fff;
  color: inherit;
  font: inherit;
  font-size: 11px;
}
.dev-tuning-panel__row output { color: rgb(45 48 54 / 62%); font-size: 10px; text-align: right; }
.dev-tuning-panel__reset {
  width: 100%;
  margin-top: 10px;
  padding: 6px 8px;
  border: 0;
  border-radius: 5px;
  background: transparent;
  color: rgb(45 48 54 / 66%);
  font: inherit;
  font-size: 11px;
  cursor: pointer;
}
@media (max-width: 430px) {
  .dev-tuning-panel { right: 8px; width: calc(100vw - 16px); }
}
</style>
