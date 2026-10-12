<script setup lang="ts">
// An older task in the Inbox's Earlier row (Inbox and Documents redesign, rounds 8–10): a quarter of the desk wide, as a
// document's chip; its square and words, and right under them the column it left and the day you wrote it, "Year · 1 Oct".
// A ghost on the desk, a border you can barely see, until the pointer brings it to life. A click opens the task; its square
// completes it; pressed and moved, it is carried (lib/inboxCarry.ts).
import { computed } from 'vue'
import GoalAffordance from '../kit-ext/goal-affordance/GoalAffordance.vue'
import type { InboxGoal } from '../lib/api'
import { completeInboxGoal, leftOn } from '../lib/inbox'
import { isPrivate } from '../lib/privacy'
import { openWindow } from '../lib/windows'
import { pressCard, wasCarried } from '../lib/inboxCarry'
import './inboxTile.css'

const props = defineProps<{ item: InboxGoal }>()
const hidden = computed(() => isPrivate(props.item.id))

function open(event: MouseEvent): void {
  if (wasCarried()) return
  openWindow({ kind: 'goal', target: props.item.id, title: props.item.title }, event.currentTarget as Element)
}
</script>

<template>
  <article
    class="inbox-tile"
    :class="{ 'inbox-tile--private': hidden }"
    :data-goal-id="item.id"
    data-role="inbox-tile"
    role="button"
    tabindex="0"
    @pointerdown="pressCard($event, item)"
    @click="open"
    @keydown.enter.prevent="open($event as unknown as MouseEvent)"
  >
    <div class="inbox-tile__row">
      <span class="inbox-tile__square" @click.stop>
        <GoalAffordance kind="square" :color="item.value_color" @toggle="(done: boolean) => done && completeInboxGoal(item.id)" />
      </span>
      <span class="inbox-tile__words">{{ item.title }}</span>
    </div>
    <p class="inbox-tile__left">{{ leftOn(item) }}</p>
  </article>
</template>
