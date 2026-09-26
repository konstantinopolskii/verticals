<script setup lang="ts">
import { computed, nextTick, ref } from 'vue'
import type { GoalCardData } from '../types'
import { CARRYOVER_ACTIONS, resolveCarryover, type CarryoverAction } from '../lib/carryover'
import PopoverEngine from './PopoverEngine.vue'

const props = defineProps<{ goals: GoalCardData[]; vertical: string }>()
const open = ref(false)
const busy = ref(false)
const status = ref('')
const trigger = ref<HTMLButtonElement | null>(null)
const answers = ref<HTMLElement | null>(null)
const closeButton = ref<HTMLButtonElement | null>(null)
// Include nested carried-over goals once, in the same reading order as their column.
const pending = computed(() => {
  const found: GoalCardData[] = []
  const seen = new Set<string>()
  function visit(goals: GoalCardData[]) {
    for (const goal of goals) {
      if (goal.ghost && !seen.has(goal.id)) { found.push(goal); seen.add(goal.id) }
      visit(goal.children ?? [])
    }
  }
  visit(props.goals)
  return found
})
const current = computed(() => pending.value[0])
const descriptions: Record<CarryoverAction, string> = {
  done: 'Finished on time',
  move: 'Keep its vertical',
  missed: 'Record as missed',
  later: 'Hide for this period',
}
async function answer(action: CarryoverAction) {
  const goal = current.value
  if (!goal || busy.value) return
  const restoreFocus = answers.value?.contains(document.activeElement)
  busy.value = true
  status.value = 'Saving…'
  try {
    await resolveCarryover(goal, action)
    await nextTick()
    // Existing actions toast failures; only the refreshed board can remove a queue entry.
    status.value = pending.value.some(item => item.id === goal.id)
      ? 'Not updated. Try again.'
      : `${CARRYOVER_ACTIONS.find(item => item.action === action)?.label}. ${pending.value.length ? 'Next goal.' : 'All reviewed.'}`
  } finally {
    busy.value = false
    await nextTick()
    if (open.value && restoreFocus) {
      const next = answers.value?.querySelector<HTMLButtonElement>(`[data-carryover-action="${action}"]`)
      ;(next ?? closeButton.value)?.focus()
    }
  }
}
function close() { trigger.value?.click() }
function onClose() {
  const column = trigger.value?.closest('[data-vertical]')
  open.value = false
  if (!pending.value.length) void nextTick(() => {
    column?.querySelector<HTMLElement>('.goal-card__row')?.focus({ preventScroll: true })
  })
}
</script>

<template>
  <PopoverEngine
    v-if="pending.length || open"
    class="carryover-review"
    surface-class="carryover-review__surface"
    :surface-attrs="{ 'data-cap': 'carryover-review', 'aria-label': `${vertical} carried-over goals` }"
    :fixed-width="360"
    placement="bottom-start"
    @open="open = true; status = ''"
    @close="onClose"
  >
    <template #trigger>
      <button
        ref="trigger"
        type="button"
        class="carryover-review__count"
        :class="{ 'carryover-review__count--empty': !pending.length }"
        data-cap="review-carryovers"
      >{{ pending.length ? `${pending.length} carried over` : 'All reviewed' }}</button>
    </template>
    <!-- Keep the queue open after each answer; reuse the engine's focus/arrow/Escape handling. -->
    <div class="carryover-review__content" @click.stop>
      <div class="carryover-review__heading">
        <span>{{ pending.length ? `${pending.length} left` : 'All reviewed' }}</span>
        <button ref="closeButton" type="button" class="carryover-review__close dropdown__item" aria-label="Close carry-over review" @click="close">×</button>
      </div>
      <template v-if="current">
        <p class="carryover-review__title" :data-review-goal-id="current.id">{{ current.title }}</p>
        <div ref="answers" class="carryover-review__answers" :aria-busy="busy">
          <button
            v-for="item in CARRYOVER_ACTIONS"
            :key="item.action"
            type="button"
            role="menuitem"
            class="carryover-review__answer dropdown__item"
            :data-carryover-action="item.action"
            :disabled="busy"
            @click="answer(item.action)"
          >
            <span>{{ item.label }}</span>
            <small>{{ descriptions[item.action] }}</small>
          </button>
        </div>
      </template>
      <p v-else class="carryover-review__title">No carried-over goals left in this column.</p>
      <p class="carryover-review__status" role="status" aria-live="polite">{{ status }}</p>
    </div>
  </PopoverEngine>
</template>

<style>
.carryover-review { margin: 0 12px 8px; }
.carryover-review__count {
  display: block;
  min-height: 32px;
  padding: 4px 0;
  border: 0;
  background: transparent;
  color: #b42342;
  font: inherit;
  font-size: 13px;
  font-weight: 500;
  line-height: 20px;
  text-align: left;
  cursor: pointer;
  -webkit-tap-highlight-color: transparent;
}
.carryover-review__count--empty { color: #616161; }
.carryover-review__count:hover { text-decoration: underline; }
.carryover-review__count:focus-visible { outline: 2px solid currentColor; outline-offset: 3px; }
.Menu-floating.popover-engine__surface.carryover-review__surface {
  padding: 16px;
  background: #fff;
  color: #252525;
  border: 1px solid #d6d6d6;
  border-radius: 4px;
  box-shadow: 0 4px 16px rgb(0 0 0 / 12%);
  animation: none;
}
.Menu-floating.carryover-review__surface:focus { outline: 2px solid #252525; outline-offset: 2px; }
.carryover-review__heading { display: flex; align-items: center; justify-content: space-between; color: #616161; font-size: 13px; }
.carryover-review__surface .carryover-review__close { flex: 0 0 32px; width: 32px; height: 32px; padding: 0; border: 0; border-radius: 4px; background: transparent; font: inherit; font-size: 24px; line-height: 1; text-align: center; }
.carryover-review__heading > span { white-space: nowrap; }
.carryover-review__title { margin: 8px 0 16px; max-height: 30vh; overflow: auto; font-size: 15px; line-height: 1.45; font-weight: 500; overflow-wrap: anywhere; }
.carryover-review__answers { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
.carryover-review__surface .carryover-review__answer { display: flex; flex-direction: column; align-items: flex-start; justify-content: center; min-height: 60px; padding: 8px; border: 1px solid #d6d6d6; border-radius: 4px; background: #fff; font: inherit; font-size: 14px; text-align: left; }
.carryover-review__answer small { margin-top: 2px; color: #616161; font-size: 12px; }
.carryover-review__surface .dropdown__item:focus-visible { outline: 2px solid #252525; outline-offset: 1px; }
.carryover-review__surface .carryover-review__answer:disabled { color: #616161; opacity: .6; }
.carryover-review__status { min-height: 18px; margin: 12px 0 0; color: #616161; font-size: 12px; line-height: 18px; }
@media (pointer: coarse) { .carryover-review__count { min-height: 44px; } .carryover-review__surface .carryover-review__close { flex-basis: 44px; width: 44px; height: 44px; } }
</style>
