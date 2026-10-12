<script setup lang="ts">
// The tags above the field (docs/design-handoff S2.P2): the agent's (its slot), the docs and the Inbox. A view's tag
// pressed again goes back to the board. While the circle rests they stand centred over it, and under the pointer they
// grow from 28 to 38 px (docs/design/field-hover.md).
import AppIcon from './AppIcon.vue'
import { store } from '../store'
import './circleTags.css'

defineProps<{ shown: boolean }>()

const VIEWS = [
  { key: 'docs', name: 'Documents', label: 'Docs', icon: 'file' },
  { key: 'inbox', name: 'Inbox', label: 'Inbox', icon: 'inbox' },
] as const

function open(view: 'docs' | 'inbox'): void {
  store.closeGoal()
  store.setView(store.state.activeView === view ? 'verticals' : view)
}
</script>

<template>
  <div class="circle-tags" :class="{ 'is-shown': shown }" data-role="circle-tags">
    <slot name="agent" />
    <button
      v-for="view in VIEWS"
      :key="view.key"
      type="button"
      class="circle-tag"
      :class="{ 'is-current': store.state.activeView === view.key }"
      :data-tag="view.key"
      :aria-label="view.name"
      :aria-pressed="store.state.activeView === view.key"
      @click="open(view.key)"
    >
      <AppIcon :name="view.icon" :size="16" :stroke="2.2" />
      <span class="circle-tag__name">{{ view.label }}</span>
    </button>
  </div>
</template>
