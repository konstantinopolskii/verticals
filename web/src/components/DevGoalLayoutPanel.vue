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
import './devGoalLayoutPanel.css'

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
