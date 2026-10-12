<script setup lang="ts">
// A task written today, in the Inbox's centre (Inbox and Documents redesign, round 11; .local-design/inbox-and-docs/final,
// section 2): at the wide column's size (the board's expanded goal, 500 24/32, a 22 px square), and above it its goal at a
// step's size, as the wide column shows a parent (goalCard.css's path line: 500 15/19, a 16 px square, inset 6 px). While
// the agent looks for that goal the squares and the line wait in grey, "Looking for its goal…". No time and no border;
// under the pointer it turns white. A click opens the task; its square completes it.
import { computed } from 'vue'
import GoalAffordance from '../kit-ext/goal-affordance/GoalAffordance.vue'
import type { InboxGoal } from '../lib/api'
import { completeInboxGoal } from '../lib/inbox'
import { goalWashInk } from '../lib/goalColor'
import { devPaletteFor, rgbaFromHex } from '../lib/devPalette'
import { isPrivate } from '../lib/privacy'
import { openWindow } from '../lib/windows'
import { pressCard, wasCarried } from '../lib/inboxCarry'
import './inboxCard.css'

const props = defineProps<{ item: InboxGoal; finding?: boolean }>()

const color = computed(() => (props.finding ? null : props.item.value_color))
/* The goal's square takes the value's colour as the board paints it (GoalAffordance.vue). */
const mark = computed(() => {
  if (!color.value) return '#e5e5e5'
  const box = devPaletteFor(color.value)?.box
  return box ? rgbaFromHex(box.color, box.opacity) : `rgb(${goalWashInk(color.value).washRgb})`
})
const hidden = computed(() => isPrivate(props.item.id))

function open(event: MouseEvent): void {
  if (wasCarried()) return
  openWindow({ kind: 'goal', target: props.item.id, title: props.item.title }, event.currentTarget as Element)
}
</script>

<template>
  <article
    class="inbox-card"
    :class="{ 'inbox-card--private': hidden }"
    :data-goal-id="item.id"
    data-role="inbox-card"
    role="button"
    tabindex="0"
    @pointerdown="pressCard($event, item)"
    @click="open"
    @keydown.enter.prevent="open($event as unknown as MouseEvent)"
  >
    <div v-if="finding || item.parent" class="inbox-card__goal" :class="{ 'inbox-card__goal--finding': finding }">
      <i class="inbox-card__mark" :style="{ background: mark }" aria-hidden="true"></i>
      <span v-if="finding" data-role="inbox-finding">Looking for its goal…</span>
      <span v-else data-role="inbox-goal">{{ item.parent!.title }}</span>
    </div>
    <div class="inbox-card__row">
      <span class="inbox-card__square" @click.stop>
        <GoalAffordance kind="square" :color="color" @toggle="(done: boolean) => done && completeInboxGoal(item.id)" />
      </span>
      <p class="inbox-card__words">{{ item.title }}</p>
    </div>
  </article>
</template>
