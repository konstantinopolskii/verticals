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

<style>
.inbox-card { position: relative; box-sizing: border-box; margin: 0 -14px 0 -12px; padding: 10px 14px 12px 12px; border-radius: 12px;
  background: transparent; color: #000; cursor: default; outline: none;
  transition: background-color 200ms ease, box-shadow 200ms ease, transform 200ms var(--vt-ease-large); }
/* Under the pointer it turns white and comes alive at once; it settles back in 200 ms (round 9). */
@media (hover: hover) and (pointer: fine) {
  .inbox-card:hover { background: #fff; transform: translateY(-1px); transition-duration: 0s;
    box-shadow: 0 0 0 .5px rgb(16 18 32 / 5%), 0 1px 3px rgb(16 18 32 / 4%), 0 8px 22px -12px rgb(16 18 32 / 14%); }
}
.inbox-card:focus-visible { background: #fff; box-shadow: 0 0 0 2px #007aff; }
/* The goal above, at a step's size, its words on the task's own edge. */
.inbox-card__goal { display: flex; align-items: flex-start; gap: 12px; margin: 4px 0 4px 6px; font: 500 15px/19px var(--font-body, Commissioner, system-ui, sans-serif); }
.inbox-card__goal--finding { color: rgb(45 48 54 / 45%); }
.inbox-card__mark { flex: none; width: 16px; height: 16px; margin-top: 1px; border-radius: 3px; transition: background-color 160ms ease; }
.inbox-card__row { display: flex; align-items: flex-start; gap: 12px; }
.inbox-card__square { flex: none; display: block; width: 22px; height: 32px; }
.inbox-card__square .goal-affordance, .inbox-card__square .goal-affordance .checkbox__box {
  width: 22px; height: 22px; min-width: 22px; min-height: 22px; border-radius: 6px; }
.inbox-card__square .goal-affordance { position: relative; top: 5px; vertical-align: top; }
.inbox-card__words { margin: 0; min-width: 0; font: 500 24px/32px var(--font-body, Commissioner, system-ui, sans-serif); overflow-wrap: break-word; }
.inbox-card--private .inbox-card__words, .inbox-card--private .inbox-card__goal span {
  color: transparent; background: #e4e4e4; border-radius: 2px; -webkit-box-decoration-break: clone; box-decoration-break: clone;
}
@media (prefers-reduced-motion: reduce) { .inbox-card { transition: none; } .inbox-card:hover { transform: none; } }
</style>
