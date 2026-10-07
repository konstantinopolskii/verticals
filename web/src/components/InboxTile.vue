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

<style>
.inbox-tile { box-sizing: border-box; height: 92px; min-width: 0; padding: 12px 16px 12px 14px; border-radius: 12px; background: transparent;
  box-shadow: inset 0 0 0 1px rgb(45 48 54 / 5%); color: #000; cursor: default; outline: none;
  transition: background-color 200ms ease, box-shadow 200ms ease, transform 200ms var(--vt-ease-large); }
@media (hover: hover) and (pointer: fine) {
  .inbox-tile:hover { background: #fff; transform: translateY(-1px); transition-duration: 0s;
    box-shadow: 0 0 0 .5px rgb(16 18 32 / 5%), 0 1px 3px rgb(16 18 32 / 4%), 0 8px 22px -12px rgb(16 18 32 / 14%); }
}
.inbox-tile:focus-visible { background: #fff; box-shadow: 0 0 0 2px #007aff; }
.inbox-tile__row { display: flex; align-items: flex-start; gap: 10px; }
.inbox-tile__square { flex: none; display: block; width: 16px; height: 20px; }
.inbox-tile__square .goal-affordance, .inbox-tile__square .goal-affordance .checkbox__box {
  width: 16px; height: 16px; min-width: 16px; min-height: 16px; border-radius: 4px; }
.inbox-tile__square .goal-affordance { position: relative; top: 2px; vertical-align: top; }
.inbox-tile__words { display: -webkit-box; min-width: 0; overflow: hidden; -webkit-box-orient: vertical; -webkit-line-clamp: 2;
  font: 500 15px/20px var(--font-body, Commissioner, system-ui, sans-serif); overflow-wrap: break-word; }
.inbox-tile__left { margin: 2px 0 0 26px; overflow: hidden; white-space: nowrap; text-overflow: ellipsis;
  font: 400 13px/18px var(--font-body, Commissioner, system-ui, sans-serif); color: rgb(45 48 54 / 60%); }
.inbox-tile--private .inbox-tile__words { color: transparent; background: #e4e4e4; border-radius: 2px; }
@media (prefers-reduced-motion: reduce) { .inbox-tile { transition: none; } .inbox-tile:hover { transform: none; } }
</style>
