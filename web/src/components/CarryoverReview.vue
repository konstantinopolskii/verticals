<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import type { GoalCardData } from '../types'
import { CARRYOVER_ACTIONS, carriedGoals, carryoverState, keepAllCarryovers, resolveCarryover, startCarryoverReview, stopCarryoverReview } from '../lib/carryover'
import { filterActive } from '../lib/commandFilter'

const props = defineProps<{ goals: GoalCardData[]; vertical: string }>()
const pending = computed(() => carriedGoals(props.goals))
const notice = computed(() => carryoverState.notices[props.vertical])
const header = ref<HTMLElement | null>(null)
const reservedHeight = ref(0)
async function keepAll() {
  reservedHeight.value = header.value?.getBoundingClientRect().height ?? 0
  await keepAllCarryovers(pending.value, props.vertical)
}
function onKeydown(event: KeyboardEvent) {
  if (carryoverState.vertical !== props.vertical || !carryoverState.goalId) return
  const target = event.target as HTMLElement | null
  // The focused composer/title owns its Escape; review shortcuts act on the board.
  if (target?.closest('input, textarea, [contenteditable="true"]')) return
  if (event.key === 'Escape') {
    event.preventDefault()
    event.stopImmediatePropagation()
    stopCarryoverReview()
    return
  }
  if (event.metaKey || event.ctrlKey || event.altKey) return
  const action = CARRYOVER_ACTIONS.find(item => item.key.toLowerCase() === event.key.toLowerCase())
  const goal = pending.value.find(item => item.id === carryoverState.goalId)
  if (!action || !goal || event.repeat) return
  event.preventDefault()
  event.stopImmediatePropagation()
  void resolveCarryover(goal, action.action)
}
onMounted(() => document.addEventListener('keydown', onKeydown, true))
onBeforeUnmount(() => document.removeEventListener('keydown', onKeydown, true))
</script>

<template>
  <div v-if="notice && !filterActive" class="carryover-header carryover-header--notice" data-role="carryover-notice" role="status" :title="notice.detail" :style="{ minHeight: `${reservedHeight}px` }">
    <span>{{ notice.text }} ·</span>
    <button type="button" :disabled="carryoverState.busy" @click="notice.onAction">{{ notice.action }}</button>
  </div>
  <div v-else-if="pending.length && !filterActive" ref="header" class="carryover-header" data-role="carryover-header">
    <span class="carryover-header__label"><strong data-role="carryover-count">{{ pending.length }}</strong> <span>carried over</span></span>
    <span class="carryover-header__actions">
      <button type="button" data-cap="keep-all-carryovers" :disabled="carryoverState.busy" @click="keepAll">Keep all</button>
      <button type="button" data-cap="review-carryovers" :disabled="carryoverState.busy" @click="startCarryoverReview(vertical)">Review</button>
    </span>
  </div>
  <div v-else-if="reservedHeight && !filterActive" class="carryover-header__reserved" :style="{ height: `${reservedHeight}px` }" aria-hidden="true" />
</template>

<style>
.carryover-header { display: flex; align-items: baseline; justify-content: space-between; flex-wrap: nowrap; gap: 4px; margin: 0 4px 8px 12px; overflow-x: auto; scrollbar-width: none; font-size: 12px; line-height: 20px; color: #686868; }
.carryover-header::-webkit-scrollbar { display: none; }
.carryover-header__label { white-space: nowrap; }
.carryover-header strong { color: #242424; font-weight: 600; }
.carryover-header__actions { display: inline-flex; flex: 0 0 auto; gap: 4px; margin-left: auto; white-space: nowrap; }
.carryover-header button { padding: 2px 0; border: 0; background: transparent; color: #242424; font: inherit; cursor: pointer; }
.carryover-header button:hover { text-decoration: underline; }
.carryover-header button:focus-visible { outline: 2px solid #242424; outline-offset: 2px; }
.carryover-header button:disabled { opacity: .5; cursor: wait; }
.carryover-header__reserved { margin: 0 4px 8px 12px; }
.carryover-header--notice { justify-content: flex-start; white-space: nowrap; }
.carryover-header--notice > span, .carryover-header--notice > button { flex: 0 0 auto; }
</style>
