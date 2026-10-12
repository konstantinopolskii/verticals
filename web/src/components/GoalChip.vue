<script setup lang="ts">
// A goal as one thing in a message (docs/design/agent-chips.md): the document chip's anatomy and type, with the goal's own
// square, as the board paints it, where the page is. DocChip's columns exactly: a 50 px column on the left, the square in
// the middle of it and level with the title's first line, and the title 14 px after the column, at 64 px, where a
// document's starts, always, a goal chip alone as well. On the right its title, two lines at most, and one grey line saying
// where it is and when ("Today · made just now", "Week · changed 2 min ago"). It stands on a message's black, as DocChip
// does there (`dark`), the field's answer and the agent's balloon alike. A click opens the goal as its window, as the
// Inbox opens one (S3.P2). The square is only drawn: it is the board's own box without its input, so a press on it is a
// press on the chip. In privacy mode a private goal's title is hidden as the board and the Inbox hide it (lib/privacy.ts).
import { computed } from 'vue'
import '../kit-ext/goal-affordance/goal-affordance.css'
import { chipLine, useGoalChip, useNow } from '../lib/goalChip'
import { goalSquare } from '../lib/look'
import { isPrivate } from '../lib/privacy'
import { openWindow } from '../lib/windows'
import './goalChip.css'

const props = defineProps<{ id: string; label?: string }>()

const { goal } = useGoalChip(() => props.id)
const now = useNow()
const gone = computed(() => goal.value === 'gone')
/* The board's own rule: privacy mode is on and the goal is one it hides (a private goal and everything under it). */
const hidden = computed(() => isPrivate(props.id))
const data = computed(() => (goal.value && goal.value !== 'gone' ? goal.value : null))
/* Until the goal is read the chip has the words of the link that brought it. */
const name = computed(() => data.value?.title || props.label || 'Goal')
const line = computed(() => (gone.value ? 'Not on the board' : data.value ? chipLine(data.value, now.value) : ''))
const square = computed(() => {
  const { box, check } = goalSquare(data.value?.color)
  return { '--goal-affordance-background': box, '--goal-affordance-check-color': check }
})

function open(event: Event): void {
  if (gone.value) return
  openWindow({ kind: 'goal', target: props.id, title: name.value }, event.currentTarget as Element)
}
</script>

<template>
  <button type="button" class="goal-chip" :class="{ 'goal-chip--private': hidden }" data-role="goal-chip" :data-goal-id="id"
          :aria-disabled="gone || undefined" @click.stop="open">
    <span class="goal-chip__page" aria-hidden="true">
      <span class="goal-chip__mark checkbox checkbox--size-s goal-affordance">
        <span class="checkbox__box goal-affordance__square" :class="{ 'is-done': data?.done }" :style="square" data-role="goal-chip-square"></span>
      </span>
    </span>
    <span class="goal-chip__text">
      <span class="goal-chip__name">{{ name }}</span>
      <span class="goal-chip__when" data-role="goal-chip-when">{{ line }}</span>
    </span>
  </button>
</template>
