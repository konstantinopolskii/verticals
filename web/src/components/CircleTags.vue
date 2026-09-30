<script setup lang="ts">
// The tags above the field (docs/design-handoff S2.P2): the agent's (its slot), the docs and the Inbox. A view's tag
// pressed again goes back to the board.
import AppIcon from './AppIcon.vue'
import { store } from '../store'

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
  <div class="circle-tags" :class="{ 'is-shown': shown }" data-role="circle-tags" :aria-hidden="!shown">
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
      :tabindex="shown ? 0 : -1"
      @click="open(view.key)"
    >
      <AppIcon :name="view.icon" :size="16" :stroke="2.2" />
      <span class="circle-tag__name">{{ view.label }}</span>
    </button>
  </div>
</template>

<style>
.circle-tags {
  display: flex;
  align-items: flex-end;
  gap: 6px;
  padding-left: 16px;
  opacity: 0;
  transform: translateY(6px);
  pointer-events: none;
  transition: opacity var(--vt-dur-close) ease-out, transform var(--vt-dur-close) var(--vt-ease-large);
}
.circle-tags.is-shown {
  opacity: 1;
  transform: none;
  pointer-events: auto;
  transition-duration: var(--vt-dur-open);
}
.circle-tag {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  height: 28px;
  min-width: 28px;
  box-sizing: border-box;
  padding: 0 6px;
  border: 0;
  border-radius: var(--vt-radius-tag);
  background: #000;
  color: #fff;
  font: 500 12px/16px var(--font-body);
  cursor: pointer;
}
.circle-tag:hover, .circle-tag:focus-visible, .circle-tag.is-current { background: #2b2b2b; }
.circle-tag:focus-visible { outline: 2px solid #000; outline-offset: 2px; }
.circle-tag__name {
  max-width: 0;
  overflow: hidden;
  white-space: nowrap;
  opacity: 0;
  transition: max-width var(--vt-dur-open) var(--vt-ease-large), opacity var(--vt-dur-fade) ease-out,
    margin var(--vt-dur-open) var(--vt-ease-large);
}
.circle-tag:hover .circle-tag__name, .circle-tag:focus-visible .circle-tag__name {
  max-width: 80px;
  margin: 0 2px 0 4px;
  opacity: 1;
}
@media (prefers-reduced-motion: reduce) {
  .circle-tags, .circle-tags.is-shown { transform: none; transition: opacity var(--vt-crossfade) linear; }
  .circle-tag__name { transition: opacity var(--vt-crossfade) linear; }
}
</style>
