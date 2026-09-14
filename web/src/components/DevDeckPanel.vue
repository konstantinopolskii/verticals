<script setup lang="ts">
import { ref } from 'vue'
import { devDeck, resetDeckTuning, saveDeckTuning, type DeckTuning } from '../lib/devDeck'

const open = ref(false)

const controls: Array<{
  key: Exclude<keyof DeckTuning, 'use3D'>
  label: string
  min: number
  max: number
  step: number
  suffix: string
}> = [
  { key: 'activeGapLeft', label: 'Active gap left', min: 0, max: 400, step: 1, suffix: 'px' },
  { key: 'activeGapRight', label: 'Active gap right', min: 0, max: 400, step: 1, suffix: 'px' },
  { key: 'dayWidth', label: 'Day width', min: 0, max: 600, step: 10, suffix: 'px' },
  { key: 'width', label: 'Card width', min: 10, max: 30, step: 1, suffix: 'vw' },
  { key: 'perspective', label: 'Perspective', min: 40, max: 5000, step: 10, suffix: 'px' },
  { key: 'rotateY', label: 'Rotate Y', min: 0, max: 70, step: 1, suffix: '°' },
  { key: 'rotateX', label: 'Rotate X', min: -45, max: 45, step: 1, suffix: '°' },
  { key: 'scale', label: 'Rest scale', min: 40, max: 100, step: 1, suffix: '%' },
  { key: 'activeRotateY', label: 'Active rotate Y', min: -10, max: 15, step: 1, suffix: '°' },
  { key: 'activeScale', label: 'Active scale', min: 60, max: 110, step: 1, suffix: '%' },
  { key: 'overlap', label: 'Overlap', min: 0, max: 30, step: 1, suffix: 'vw' },
  { key: 'offsetY', label: 'Rest vertical', min: -100, max: 100, step: 1, suffix: 'px' },
  { key: 'activeOffsetY', label: 'Active vertical', min: -100, max: 100, step: 1, suffix: 'px' },
]

function update(key: Exclude<keyof DeckTuning, 'use3D'>, event: Event): void {
  const value = Number((event.target as HTMLInputElement).value)
  if (!Number.isFinite(value)) return
  devDeck[key] = value
  saveDeckTuning()
}

function toggle3D(event: Event): void {
  devDeck.use3D = (event.target as HTMLInputElement).checked
  saveDeckTuning()
}
</script>

<template>
  <button
    type="button"
    class="dev-deck-panel__trigger"
    aria-label="Open deck settings"
    :aria-expanded="open"
    @click="open = !open"
  >Deck</button>

  <aside v-if="open" class="dev-deck-panel" data-role="dev-deck-panel" aria-label="Deck settings">
    <header class="dev-deck-panel__header">
      <div>
        <strong>Deck settings</strong>
        <p>Live preview only. Saved in this browser.</p>
      </div>
      <button type="button" class="dev-deck-panel__close" aria-label="Close deck settings" @click="open = false">×</button>
    </header>
    <label class="dev-deck-panel__toggle">
      <input type="checkbox" :checked="devDeck.use3D" @change="toggle3D">
      <span>3D transforms</span>
    </label>
    <div v-for="control in controls" :key="control.key" class="dev-deck-panel__row">
      <label :for="`deck-${control.key}`">{{ control.label }}</label>
      <input
        :id="`deck-${control.key}`"
        type="range"
        :min="control.min"
        :max="control.max"
        :step="control.step"
        :value="devDeck[control.key]"
        @input="update(control.key, $event)"
      >
      <output>{{ devDeck[control.key] }}{{ control.suffix }}</output>
    </div>
    <div class="dev-deck-panel__actions">
      <button type="button" @click="resetDeckTuning">Reset deck</button>
    </div>
  </aside>
</template>

<style>
.dev-deck-panel__trigger {
  position: fixed;
  right: 76px;
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
.dev-deck-panel__trigger:hover,
.dev-deck-panel__actions button:hover,
.dev-deck-panel__close:hover { background: rgb(45 48 54 / 7%); }
.dev-deck-panel {
  position: fixed;
  right: 16px;
  bottom: 56px;
  z-index: 301;
  width: 330px;
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
.dev-deck-panel__header { display: flex; align-items: flex-start; justify-content: space-between; margin-bottom: 12px; }
.dev-deck-panel__header strong { font-size: 14px; font-weight: 600; }
.dev-deck-panel__header p { margin: 3px 0 0; color: rgb(45 48 54 / 52%); font-size: 11px; }
.dev-deck-panel__toggle { display: flex; align-items: center; gap: 7px; min-height: 32px; border-top: 1px solid rgb(45 48 54 / 8%); color: rgb(45 48 54 / 72%); font-size: 12px; }
.dev-deck-panel__toggle input { margin: 0; accent-color: rgb(45 48 54 / 70%); }
.dev-deck-panel__close { border: 0; background: transparent; color: rgb(45 48 54 / 55%); font-size: 20px; line-height: 18px; cursor: pointer; }
.dev-deck-panel__row { display: grid; grid-template-columns: 1fr 130px 52px; align-items: center; gap: 8px; min-height: 32px; border-top: 1px solid rgb(45 48 54 / 8%); }
.dev-deck-panel__row label { font-size: 12px; }
.dev-deck-panel__row input[type='range'] { width: 130px; accent-color: rgb(45 48 54 / 70%); }
.dev-deck-panel__row output { color: rgb(45 48 54 / 62%); font-size: 11px; text-align: right; }
.dev-deck-panel__actions { margin-top: 12px; }
.dev-deck-panel__actions button { width: 100%; padding: 6px 8px; border: 0; border-radius: 5px; background: transparent; color: rgb(45 48 54 / 66%); font: inherit; font-size: 11px; cursor: pointer; }
</style>
