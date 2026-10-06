<script setup lang="ts">
// A card in the Inbox's Today (round 7, .local-design/inbox-and-docs/round7): your words at reading size with the
// board's square, and under them the goal they sit under with its value's colour and the time you wrote them. While
// the agent looks for that goal the square and the line wait in grey, "Looking for its goal…". A click opens the
// goal; the square completes it.
import { computed } from 'vue'
import GoalAffordance from '../kit-ext/goal-affordance/GoalAffordance.vue'
import type { InboxGoal } from '../lib/api'
import { completeInboxGoal, timeOf } from '../lib/inbox'
import { goalWashInk } from '../lib/goalColor'
import { devPaletteFor, rgbaFromHex } from '../lib/devPalette'
import { isPrivate } from '../lib/privacy'
import { openWindow } from '../lib/windows'
import { pressCard, wasCarried } from '../lib/inboxCarry'

const props = defineProps<{ item: InboxGoal; finding?: boolean }>()

const color = computed(() => (props.finding ? null : props.item.value_color))
/* The goal line's small square takes the card's own square colour, as the board paints it (GoalAffordance.vue). */
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
    <div class="inbox-card__row">
      <span class="inbox-card__square" @click.stop>
        <GoalAffordance kind="square" :color="color" @toggle="(done: boolean) => done && completeInboxGoal(item.id)" />
      </span>
      <p class="inbox-card__words">{{ item.title }}</p>
    </div>
    <div class="inbox-card__line">
      <i class="inbox-card__mark" :style="{ background: mark }" aria-hidden="true"></i>
      <span v-if="finding" class="inbox-card__goal inbox-card__goal--finding" data-role="inbox-finding">Looking for its goal…</span>
      <span v-else-if="item.parent" class="inbox-card__goal" data-role="inbox-goal">{{ item.parent.title }}</span>
      <span v-else class="inbox-card__goal"></span>
      <time class="inbox-card__time" :datetime="item.created_at">{{ timeOf(item.created_at) }}</time>
    </div>
  </article>
</template>

<style>
/* The card's paper (round 7's `.tc`): 12 px corners, the floating shadow, the words at 17/26. */
.inbox-card {
  position: relative; box-sizing: border-box; padding: 18px 20px 16px 18px; border-radius: 12px; background: #fff;
  box-shadow: 0 0 0 .5px rgba(16, 18, 32, .05), 0 2px 6px rgba(16, 18, 32, .04), 0 14px 36px -12px rgba(16, 18, 32, .18);
  color: #000; cursor: default; outline: none;
  transition: box-shadow 160ms cubic-bezier(.2, 0, 0, 1), transform 160ms cubic-bezier(.2, 0, 0, 1);
}
.inbox-card:hover, .inbox-card:focus-visible {
  box-shadow: 0 0 0 .5px rgba(16, 18, 32, .06), 0 18px 45px -6px rgba(16, 18, 32, .2), 0 0 120px 12px rgba(16, 18, 32, .08);
  transform: translateY(-1px);
}
.inbox-card__row { display: flex; align-items: flex-start; gap: 12px; }
.inbox-card__square { flex: none; display: block; width: 18px; height: 26px; }
/* Round 7's square at the card's reading size: 18 px, 5 px corners, centred on the first line. */
.inbox-card__square .goal-affordance, .inbox-card__square .goal-affordance .checkbox__box {
  width: 18px; height: 18px; min-width: 18px; min-height: 18px; border-radius: 5px; }
.inbox-card__square .goal-affordance { position: relative; top: 4px; }
.inbox-card__words { margin: 0; min-width: 0; font: 500 17px/26px var(--font-body, Commissioner, system-ui, sans-serif);
  overflow-wrap: break-word; }
.inbox-card__line { display: flex; align-items: flex-start; gap: 7px; margin: 12px 0 0 30px;
  font: 400 13px/18px var(--font-body, Commissioner, system-ui, sans-serif); color: rgb(45 48 54 / 60%); }
.inbox-card__mark { flex: none; width: 10px; height: 10px; margin-top: 4px; border-radius: 2px; transition: background-color 160ms ease; }
.inbox-card__goal { min-width: 0; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
.inbox-card__goal--finding { color: rgb(45 48 54 / 45%); }
.inbox-card__time { flex: none; margin-left: auto; padding-left: 10px; white-space: nowrap; }
.inbox-card--private .inbox-card__words, .inbox-card--private .inbox-card__goal {
  color: transparent; background: #e4e4e4; border-radius: 2px; -webkit-box-decoration-break: clone; box-decoration-break: clone;
}
@media (prefers-reduced-motion: reduce) { .inbox-card { transition: none; } .inbox-card:hover { transform: none; } }
</style>
