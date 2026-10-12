<script setup lang="ts">
// Above the field while you move a goal (docs/design-handoff S5.P3, S5.P4): "Weeks" names the view, and the goal let go
// over the field waits beside it, the same card, out of its group. Picked, one springs up with its shadow and the other
// steps aside; the goal is dragged from here to its place. A task carried onto the field in the Inbox waits here as well,
// the same card with no view's name beside it, and the Inbox's own drag takes it out again (docs/design/inbox-carry-stack.md).
// The pictures dropped on the window or pasted wait in the same row, after them (FieldPictures.vue; docs/design/bug-reports.md).
import { computed } from 'vue'
import { store } from '../store'
import { findGoal } from '../lib/boardIndex'
import { inbox } from '../lib/inbox'
import { carry, pressCard } from '../lib/inboxCarry'
import { goalLight } from '../lib/look'
import { isPrivate } from '../lib/privacy'
import { spanGoal, spans, VIEW_NAMES } from '../lib/spans'
import { moving, tap } from '../lib/moving'
import { pictures } from '../lib/reportPictures'
import FieldPictures from './FieldPictures.vue'
import './movingStack.css'

const view = computed(() => (spans.vertical ? VIEW_NAMES[spans.vertical] : null))
/* The waiting goal is a card of the board or of the spans; a task from the Inbox has its title and its value's colour,
   which is the colour the board shows it in. */
const task = computed(() => (moving.goalId ? inbox.goals.find((g) => g.id === moving.goalId) ?? null : null))
const goal = computed(() => {
  const id = moving.goalId
  if (!id) return null
  const card = findGoal(store.state.board, id) ?? spanGoal(id)
  if (card) return { id, title: card.title, color: card.color }
  return task.value ? { id, title: task.value.title, color: task.value.value_color } : null
})
const lit = computed(() => goalLight(goal.value?.color) ?? {})
const inHand = computed(() => !!goal.value && (store.state.drag.id === goal.value.id || carry.item?.id === goal.value.id))
const hidden = computed(() => !!goal.value && isPrivate(goal.value.id))
/* The goal's own card stays out of its group while it waits here (S5.P3.017); in the Inbox `lib/inbox.ts` leaves it out of
   its lists, and a copy in the hand is the same goal's. */
const hideSource = computed(() => (moving.goalId && store.state.activeView !== 'inbox'
  ? `[data-goal-id="${CSS.escape(moving.goalId)}"]:not([data-parked]) { display: none !important; }` : ''))

function onGoalDown(event: PointerEvent): void {
  const id = goal.value?.id
  if (!id || event.button !== 0) return
  // In the Inbox no board is in view to land it on: its own drag takes the card out, and lets it go back to its place.
  if (store.state.activeView === 'inbox' && task.value) {
    pressCard(event, task.value)
    return
  }
  const row = (event.currentTarget as HTMLElement).querySelector<HTMLElement>('.goal-card__row')
  if (!row) return
  store.pointerDownCard(id, event.clientX, event.clientY, row.getBoundingClientRect(), event.pointerType, event.altKey)
}
</script>

<template>
  <div v-if="view || goal || pictures.list.length" class="moving-stack" :class="{ 'moving-stack--holding': !!store.state.drag.id && !goal }" data-role="moving-stack">
    <component :is="'style'" v-if="hideSource">{{ hideSource }}</component>
    <button
      v-if="view"
      type="button"
      class="moving-stack__view"
      :class="{ 'is-picked': moving.picked === 'view', 'is-aside': moving.picked === 'goal' }"
      data-role="moving-view"
      @click="tap('view')"
    >{{ view }}</button>
    <div
      v-if="goal"
      class="moving-stack__goal"
      :class="{ 'is-picked': moving.picked === 'goal', 'is-aside': moving.picked === 'view', 'is-in-hand': inHand, 'goal-card--private': hidden }"
      :style="lit"
      :data-goal-id="goal.id"
      data-parked
      data-role="moving-goal"
      @pointerdown="onGoalDown"
      @click="tap('goal')"
    >
      <div class="goal-card__row moving-stack__row">
        <span class="moving-stack__box" aria-hidden="true"></span>
        <span class="goal-card__title-text moving-stack__title">{{ goal.title }}</span>
      </div>
    </div>
    <FieldPictures v-if="pictures.list.length" />
  </div>
</template>
