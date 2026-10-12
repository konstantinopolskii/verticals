<script setup lang="ts">
import { ref } from 'vue'
import AppIcon from './AppIcon.vue'
import {
  devIcons,
  resetIconTuning,
  saveIconTuning,
  type IconTuning,
} from '../lib/devIcons'
import './devIconPanel.css'

const open = ref(false)

const controls: Array<{
  key: keyof IconTuning
  label: string
  min: number
  max: number
  step?: number
}> = [
  { key: 'base', label: 'UI icons', min: 10, max: 32 },
  { key: 'arrows', label: 'Arrows', min: 8, max: 28 },
  { key: 'search', label: 'Search', min: 12, max: 40 },
  { key: 'menu', label: 'Three dots size', min: 6, max: 24 },
  { key: 'menuStroke', label: 'Three dots weight', min: 0.8, max: 2.2, step: 0.1 },
]

function update(key: keyof IconTuning, event: Event): void {
  const value = Number((event.target as HTMLInputElement).value)
  if (!Number.isFinite(value)) return
  devIcons[key] = value
  saveIconTuning()
}
</script>

<template>
  <button
    type="button"
    class="dev-icon-panel__trigger"
    aria-label="Open icon settings"
    :aria-expanded="open"
    @click="open = !open"
  >Icons</button>

  <aside v-if="open" class="dev-icon-panel" data-role="dev-icon-panel" aria-label="Icon settings">
    <header class="dev-icon-panel__header">
      <div>
        <strong>Icon settings</strong>
        <p>Live preview. Saved in this browser.</p>
      </div>
      <button type="button" class="dev-icon-panel__close" aria-label="Close icon settings" @click="open = false">
        <AppIcon name="x" :size="16" />
      </button>
    </header>
    <div v-for="control in controls" :key="control.key" class="dev-icon-panel__row">
      <label :for="`icon-${control.key}`">{{ control.label }}</label>
      <input
        :id="`icon-${control.key}`"
        type="range"
        :min="control.min"
        :max="control.max"
        :step="control.step ?? 1"
        :value="devIcons[control.key]"
        @input="update(control.key, $event)"
      >
      <output>{{ devIcons[control.key] }}{{ control.key === 'menuStroke' ? '' : 'px' }}</output>
    </div>
    <div class="dev-icon-panel__actions">
      <button type="button" @click="resetIconTuning">Reset icons</button>
    </div>
  </aside>
</template>
