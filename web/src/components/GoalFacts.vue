<script setup lang="ts">
/* One line of facts under an opened goal's title (KK, 27 Sep 2026, the cleaned-up card: "I love it. Let's implement"):
   its date, its size for a week or day goal, its open comments and the way to the agent, in that order. Each fact is
   also the control that changes it, so the card needs no icon row: the date opens the schedule popup (spec §2,
   "August 8 is a schedule popup"), the size its editor, the comments their sidebar (D255). "Discuss with agent" is
   the one action, so it is the one black word. */
import { computed } from 'vue'
import SchedulePopover from './SchedulePopover.vue'
import ShotSizeFields from '../kit-ext/shot-size-fields/ShotSizeFields.vue'
import { store } from '../store'
import { agentChat as agentChatState } from '../lib/agentChat'
import { plannedPeriodLabel } from '../lib/schedule'
import { MONTH_NAMES, type VerticalScale } from '../lib/periods'

const props = defineProps<{ id: string }>()

const goal = computed(() => (store.state.goalDetail?.id === props.id ? store.state.goalDetail : null))

/* The app's own task says where it lives and when it was made: "Inbox · made Mon 28 Sep" (docs/design-handoff S4.P1.012). */
const made = computed(() => {
  const g = goal.value
  if (!g || g.vertical || g.origin !== 'app') return null
  const d = new Date(g.created_at)
  return `made ${['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'][d.getDay()]} ${d.getDate()} ${MONTH_NAMES[d.getMonth()]!.slice(0, 3)}`
})
const dateLabel = computed(() => {
  const g = goal.value
  if (!g?.vertical) return made.value ? 'Inbox' : 'Schedule'
  if (g.vertical === 'life') return 'Life'
  return plannedPeriodLabel(g)
})
const sized = computed(() => goal.value?.vertical === 'week' || goal.value?.vertical === 'day')

const commentCount = computed(() => store.unresolvedCommentCount('goal', props.id))
const commentsOpenHere = computed(() => {
  const c = store.state.comments
  return c.open && c.targetType === 'goal' && c.targetId === props.id
})
function toggleComments(): void {
  if (commentsOpenHere.value) store.closeCommentsPanel()
  else store.openCommentsPanel('goal', props.id)
}

/* Only where an agent exists (docs/design-handoff S2.P1.023). */
const agentChat = computed(() => agentChatState.available)
function discuss(): void {
  window.dispatchEvent(new CustomEvent('verticals:discuss-goal', { detail: { id: props.id } }))
}

function onSchedule(scale: VerticalScale, periodKey: string): void {
  void store.scheduleGoalTo(props.id, scale, periodKey)
}
</script>

<template>
  <p v-if="goal" class="goal-facts" data-role="goal-facts">
    <SchedulePopover
      v-bind="store.scheduleGrid.value.props"
      @select="onSchedule"
      @navigate="store.navigateSchedule"
      @open="store.resetScheduleView()"
    >
      <template #trigger="{ open }">
        <button
          type="button"
          class="goal-facts__item"
          data-cap="schedule"
          aria-haspopup="menu"
          :aria-expanded="open"
        >{{ dateLabel }}</button>
      </template>
    </SchedulePopover>
    <template v-if="made">
      <span class="goal-facts__sep" aria-hidden="true">·</span>
      <span class="goal-facts__made" data-role="goal-made">{{ made }}</span>
    </template>
    <template v-if="sized">
      <span class="goal-facts__sep" aria-hidden="true">·</span>
      <ShotSizeFields
        class="goal-facts__size"
        :expected="goal.size_expected"
        :actual="goal.size_actual"
        @change-expected="(value) => store.updateGoal(props.id, { size_expected: value })"
      />
    </template>
    <template v-if="commentCount > 0">
      <span class="goal-facts__sep" aria-hidden="true">·</span>
      <button
        type="button"
        class="goal-facts__item"
        data-cap="open-comments"
        :aria-expanded="commentsOpenHere"
        @click="toggleComments"
      >{{ commentCount }} {{ commentCount === 1 ? 'comment' : 'comments' }}</button>
    </template>
    <template v-if="agentChat">
      <span class="goal-facts__sep" aria-hidden="true">·</span>
      <button
        type="button"
        class="goal-facts__item goal-facts__item--act"
        data-cap="discuss"
        @click="discuss"
      >Discuss with agent</button>
    </template>
  </p>
</template>

<style>
/* 13/20 grey, the size of every other secondary line on the board; the one action is black. Items never break inside,
   and the line wraps between them. */
.goal-facts {
  margin: 2px 0 0;
  font-size: 13px;
  line-height: 20px;
  font-weight: 400;
  color: rgba(0, 0, 0, .5);
  cursor: default;
}
.goal-facts__item,
.goal-facts .shot-size-fields__summary {
  display: inline;
  padding: 0;
  border: 0;
  background: transparent;
  color: inherit;
  font: inherit;
  white-space: nowrap;
  cursor: pointer;
}
.goal-facts__item:hover,
.goal-facts .shot-size-fields__summary:hover { color: #000; }
.goal-facts__item:focus-visible,
.goal-facts .shot-size-fields__summary:focus-visible { outline: 2px solid var(--color-border-strong); outline-offset: 2px; }
.goal-facts__item--act { color: #000; font-weight: 500; }
.goal-facts__item--act:hover { text-decoration: underline; text-underline-offset: 2.25px; text-decoration-color: rgba(0, 0, 0, .2); }
.goal-facts__sep { padding: 0 4px; color: rgba(0, 0, 0, .28); }
.goal-facts > .schedule-popover-anchor,
.goal-facts .dropdown,
.goal-facts > .shot-size-fields { display: inline; }
.goal-facts > .shot-size-fields { flex: none; min-width: 0; color: inherit; font-size: inherit; line-height: inherit; }
</style>
