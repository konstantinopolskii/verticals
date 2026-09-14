<script setup lang="ts">
import AppIcon from './AppIcon.vue'
import { ref } from 'vue'
import {
  GOAL_LAYOUT_SECTIONS,
  devGoalLayout,
  resetGoalLayout,
  saveGoalLayout,
  type GoalLayoutControl,
} from '../lib/devGoalLayout'

const open = ref(false)

function controlId(control: GoalLayoutControl): string {
  return `goal-layout-${control.variable.slice(2)}`
}

function update(control: GoalLayoutControl, event: Event): void {
  const input = event.target as HTMLInputElement | HTMLSelectElement
  if (control.kind === 'text') {
    if (!input.value.trim()) return
    devGoalLayout[control.variable] = input.value
  } else {
    const value = Number(input.value)
    if (!Number.isFinite(value)) return
    devGoalLayout[control.variable] = value
  }
  saveGoalLayout()
}
</script>

<template>
  <button
    type="button"
    class="dev-goal-layout-panel__trigger"
    aria-label="Open goal layout settings"
    :aria-expanded="open"
    @click="open = !open"
  >Layout</button>

  <aside
    v-if="open"
    class="dev-goal-layout-panel"
    data-role="dev-goal-layout-panel"
    aria-label="Goal column layout"
  >
    <header class="dev-goal-layout-panel__header">
      <div>
        <strong>Goal column layout</strong>
        <p>Live preview. Saved in this browser.</p>
      </div>
      <button type="button" class="dev-goal-layout-panel__close" aria-label="Close goal layout settings" @click="open = false">
        <AppIcon name="x" :size="16" />
      </button>
    </header>

    <details v-for="section in GOAL_LAYOUT_SECTIONS" :key="section.title" :open="section.open">
      <summary>{{ section.title }}</summary>
      <div v-for="control in section.controls" :key="control.variable" class="dev-goal-layout-panel__row">
        <label :for="controlId(control)">{{ control.label }}</label>
        <input
          v-if="control.kind === 'slider'"
          :id="controlId(control)"
          type="range"
          :min="control.min"
          :max="control.max"
          :step="control.step"
          :value="devGoalLayout[control.variable]"
          @input="update(control, $event)"
        >
        <input
          v-else-if="control.kind === 'text'"
          :id="controlId(control)"
          type="text"
          :value="devGoalLayout[control.variable]"
          @change="update(control, $event)"
        >
        <select
          v-else
          :id="controlId(control)"
          :value="devGoalLayout[control.variable]"
          @change="update(control, $event)"
        >
          <option v-for="option in control.options" :key="option.value" :value="option.value">{{ option.label }}</option>
        </select>
        <output v-if="control.kind === 'slider'">{{ devGoalLayout[control.variable] }}{{ control.unit }}</output>
      </div>
    </details>

    <button type="button" class="dev-goal-layout-panel__reset" @click="resetGoalLayout">Reset layout</button>
  </aside>
</template>

<style>
.dev-goal-layout-panel__trigger {
  position: fixed;
  right: 196px;
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
.dev-goal-layout-panel__trigger:hover,
.dev-goal-layout-panel__close:hover,
.dev-goal-layout-panel__reset:hover { background: rgb(45 48 54 / 7%); }
.dev-goal-layout-panel {
  position: fixed;
  right: 16px;
  bottom: 56px;
  z-index: 301;
  width: 390px;
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
.dev-goal-layout-panel__header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  margin-bottom: 10px;
}
.dev-goal-layout-panel__header strong { font-size: 14px; font-weight: 600; }
.dev-goal-layout-panel__header p { margin: 3px 0 0; color: rgb(45 48 54 / 52%); font-size: 11px; }
.dev-goal-layout-panel__close {
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
.dev-goal-layout-panel details { border-top: 1px solid rgb(45 48 54 / 8%); }
.dev-goal-layout-panel summary {
  padding: 8px 0;
  color: rgb(45 48 54 / 74%);
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
}
.dev-goal-layout-panel__row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 140px 48px;
  align-items: center;
  gap: 7px;
  min-height: 30px;
}
.dev-goal-layout-panel__row label { font-size: 11px; }
.dev-goal-layout-panel__row input[type='range'] { width: 140px; accent-color: rgb(45 48 54 / 70%); }
.dev-goal-layout-panel__row input[type='text'],
.dev-goal-layout-panel__row select {
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
.dev-goal-layout-panel__row output { color: rgb(45 48 54 / 62%); font-size: 10px; text-align: right; }
.dev-goal-layout-panel__reset {
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
  .dev-goal-layout-panel { right: 8px; width: calc(100vw - 16px); }
  .dev-goal-layout-panel__trigger { right: 196px; }
}
</style>
