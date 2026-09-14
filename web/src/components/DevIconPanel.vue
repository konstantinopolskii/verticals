<script setup lang="ts">
import { ref } from 'vue'
import AppIcon from './AppIcon.vue'
import {
  devIcons,
  resetIconTuning,
  saveIconTuning,
  type IconTuning,
} from '../lib/devIcons'

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

<style>
.dev-icon-panel__trigger {
  position: fixed;
  right: 136px;
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
.dev-icon-panel__trigger:hover,
.dev-icon-panel__actions button:hover,
.dev-icon-panel__close:hover { background: rgb(45 48 54 / 7%); }
.dev-icon-panel {
  position: fixed;
  right: 16px;
  bottom: 56px;
  z-index: 301;
  width: 330px;
  box-sizing: border-box;
  padding: 14px;
  border: 1px solid rgb(45 48 54 / 14%);
  border-radius: 8px;
  background: #fff;
  color: rgb(45 48 54);
  box-shadow: 0 8px 30px rgb(0 0 0 / 16%);
}
.dev-icon-panel__header { display: flex; align-items: flex-start; justify-content: space-between; margin-bottom: 12px; }
.dev-icon-panel__header strong { font-size: 14px; font-weight: 600; }
.dev-icon-panel__header p { margin: 3px 0 0; color: rgb(45 48 54 / 52%); font-size: 11px; }
.dev-icon-panel__close { display: grid; width: 20px; height: 20px; place-items: center; padding: 0; border: 0; background: transparent; color: rgb(45 48 54 / 55%); cursor: pointer; }
.dev-icon-panel__row { display: grid; grid-template-columns: 1fr 130px 52px; align-items: center; gap: 8px; min-height: 34px; border-top: 1px solid rgb(45 48 54 / 8%); }
.dev-icon-panel__row label { font-size: 12px; }
.dev-icon-panel__row input[type='range'] { width: 130px; accent-color: rgb(45 48 54 / 70%); }
.dev-icon-panel__row output { color: rgb(45 48 54 / 62%); font-size: 11px; text-align: right; }
.dev-icon-panel__actions { margin-top: 12px; }
.dev-icon-panel__actions button { width: 100%; padding: 6px 8px; border: 0; border-radius: 5px; background: transparent; color: rgb(45 48 54 / 66%); font: inherit; font-size: 11px; cursor: pointer; }
</style>
