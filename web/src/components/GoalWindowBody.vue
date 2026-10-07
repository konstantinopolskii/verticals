<script setup lang="ts">
// A goal in a window (docs/design-handoff S3.P2): going deeper's opened card, in full, in its colour, drawn in the window
// instead of its column. It holds the open goal while it is in front, and gives it back when it goes.
import { computed, onBeforeUnmount, watch } from 'vue'
import GoalCard from './GoalCard.vue'
import { store } from '../store'
import { closeWindow, windows } from '../lib/windows'
import type { GoalCardData } from '../types'

const props = defineProps<{ id: string; front: boolean }>()
const hostKey = computed(() => `window:root:0:${props.id}`)

watch(() => [props.id, props.front] as const, ([id, front]) => {
  if (front && (store.state.openGoalId !== id || store.state.openGoalVertical !== 'window')) {
    void store.openGoal(id, 'window', hostKey.value)
  }
}, { immediate: true })
/* A step opened inside the window becomes the window's goal. */
watch(() => [store.state.openGoalId, store.state.openGoalVertical] as const, ([id, vertical]) => {
  if (!props.front || vertical !== 'window' || !id || id === props.id) return
  const win = windows.list.find((w) => w.kind === 'goal' && w.target === props.id)
  if (win) { win.target = id; win.key = `goal:${id}` }
})
/* The address left the goal (Back, a view's tag): the window goes with it. */
watch(() => store.state.openGoalId, (id, was) => {
  if (!props.front || id !== null || was !== props.id) return
  const win = windows.list.find((w) => w.kind === 'goal' && w.target === props.id)
  if (win) closeWindow(win.key)
})
onBeforeUnmount(() => {
  if (store.state.openGoalVertical === 'window' && store.state.openGoalId === props.id) store.closeGoal()
})

const detail = computed(() => (store.state.goalDetail?.id === props.id ? store.state.goalDetail : null))
const steps = computed<GoalCardData[]>(() => (detail.value?.children ?? []).map((child) => ({
  id: child.id,
  parentId: child.parent_id,
  title: child.title,
  done: child.done_at !== null,
  color: detail.value?.color ?? null,
  vertical: child.vertical,
  repeat: child.repeat,
})))
</script>

<template>
  <div class="goal-window" data-role="goal-window" :data-goal-id-window="id">
    <GoalCard
      v-if="detail"
      :id="id"
      :title="detail.title"
      :done="!!detail.done_at"
      :color="detail.color"
      :vertical="detail.vertical"
      :repeat="detail.repeat"
      :children="steps"
      :subgoal-count="steps.length"
      column-vertical="window"
    />
    <p v-else class="goal-window__loading">Loading…</p>
  </div>
</template>

<style>
.goal-window { padding: 12px 40px 20px 12px; }
/* The window is the opened card: its colour runs to the window's edges, so the card draws no wash of its own here
   (docs/design-handoff S3.P2.004, .005, S0.P1.F01). A goal with no colour stands on light grey, as S4.P4.F02 draws. */
.vt-window[data-window='goal']:not(.vt-shadow--lit) { background: #f3f3f4; }
.goal-window { --color-bg: transparent; --color-surface-overlay: transparent; }
.goal-window > .goal-card > .goal-card__row::before { opacity: 0 !important; }
.goal-window__loading { margin: 0; padding: 24px; color: rgb(0 0 0 / 45%); font: 400 14px/20px var(--font-body); }
</style>
