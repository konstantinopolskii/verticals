<script setup lang="ts">
// Above the field while you move a goal (docs/design-handoff S5.P3, S5.P4): "Weeks" names the view, and the goal let go
// over the field waits beside it, the same card, out of its group. Picked, one springs up with its shadow and the other
// steps aside; the goal is dragged from here to its place.
import { computed } from 'vue'
import { store } from '../store'
import { findGoal } from '../lib/boardIndex'
import { goalLight } from '../lib/look'
import { spanGoal, spans, VIEW_NAMES } from '../lib/spans'
import { moving, tap } from '../lib/moving'

const view = computed(() => (spans.vertical ? VIEW_NAMES[spans.vertical] : null))
const goal = computed(() => (moving.goalId ? findGoal(store.state.board, moving.goalId) ?? spanGoal(moving.goalId) ?? null : null))
const lit = computed(() => goalLight(goal.value?.color) ?? {})
const inHand = computed(() => !!goal.value && store.state.drag.id === goal.value.id)
/* The goal's own card stays out of its group while it waits here (S5.P3.017). */
const hideSource = computed(() => (moving.goalId
  ? `[data-goal-id="${CSS.escape(moving.goalId)}"]:not([data-parked]) { display: none !important; }` : ''))

function onGoalDown(event: PointerEvent): void {
  const id = goal.value?.id
  if (!id || event.button !== 0) return
  const row = (event.currentTarget as HTMLElement).querySelector<HTMLElement>('.goal-card__row')
  if (!row) return
  store.pointerDownCard(id, event.clientX, event.clientY, row.getBoundingClientRect(), event.pointerType, event.altKey)
}
</script>

<template>
  <div v-if="view || goal" class="moving-stack" :class="{ 'moving-stack--holding': !!store.state.drag.id && !goal }" data-role="moving-stack">
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
      :class="{ 'is-picked': moving.picked === 'goal', 'is-aside': moving.picked === 'view', 'is-in-hand': inHand }"
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
  </div>
</template>

<style>
/* "Weeks": 36 px, 18 px corners, black, words 15/20 at 500; the goal is its card at 12 px, lit softly green from under;
   they stand 8 px apart on one baseline, 4 px in from the field's left (S5.P3.006, .043). */
.moving-stack {
  position: absolute;
  left: calc(50% - var(--moving-field-width, 300px) / 2 + 4px + var(--moving-tags-shift, 0px));
  bottom: 8px;
  display: flex;
  align-items: flex-end;
  gap: 8px;
  max-width: calc(var(--moving-field-width, 300px) - 8px);
  transition: left 200ms var(--vt-ease-large);
  pointer-events: auto;
}
.moving-stack__view {
  flex: none;
  height: 36px;
  padding: 0 16px;
  border: 0;
  border-radius: 18px;
  background: #000;
  color: #fff;
  font: 500 15px/20px var(--font-body);
  cursor: pointer;
}
.moving-stack__goal {
  min-width: 0;
  max-width: 220px;
  padding: 8px 12px;
  border-radius: 8px;
  background: rgb(var(--vt-pale, 240, 240, 240));
  box-shadow: 0 6px 24px -8px rgba(var(--vt-tint, 200, 200, 200), .9);
  cursor: grab;
  touch-action: none;
}
.moving-stack__row { display: flex; align-items: flex-start; gap: 10px; }
.moving-stack__box { flex: none; width: 14px; height: 14px; margin-top: 2px; border-radius: 3px; background: rgb(var(--vt-tint, 210, 210, 210)); }
.moving-stack__title {
  display: -webkit-box;
  overflow: hidden;
  color: #000;
  font: 500 12px/18px var(--font-body);
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 2;
}
.moving-stack__goal.is-in-hand { visibility: hidden; }
/* Picked: 14% bigger and 10 px higher on a spring, a strong shadow in its colour; the other steps aside (S5.P4.007). */
.moving-stack__view,
.moving-stack__goal { transition: transform 290ms var(--vt-ease-large), box-shadow 290ms ease; }
.moving-stack__view.is-aside,
.moving-stack__goal.is-aside { transition-timing-function: var(--vt-ease-sway); }
.moving-stack__view.is-picked { transform: translateY(-10px) scale(1.14); box-shadow: 0 16px 26px -6px rgb(0 0 0 / 45%), 0 46px 100px -12px rgb(0 0 0 / 35%); }
.moving-stack__goal.is-picked {
  transform: translateY(-10px) scale(1.14);
  background: rgb(var(--vt-tint, 220, 220, 220));
  box-shadow: 0 16px 26px -6px rgba(var(--vt-tint, 200, 200, 200), .62), 0 46px 100px -12px rgba(var(--vt-tint, 200, 200, 200), .62);
}
.moving-stack__view.is-aside { transform: translateX(-12px); }
.moving-stack__goal.is-aside { transform: translateX(14px); }
@media (prefers-reduced-motion: reduce) {
  .moving-stack__view, .moving-stack__goal, .moving-stack { transition: none; }
}
</style>
