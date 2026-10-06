<script setup lang="ts">
/* The Inbox (Inbox and Documents redesign, round 7, KK 7 Oct 2026; .local-design/inbox-and-docs/round7): everything with
   no date (`core/inbox.py`), tasks only, on the desk's grey. What you wrote today stands on top as cards, newest first,
   and keeps the window's first 80 %; below it the rest lies on shelves, one for each column a task left, in the board's
   own rows. You write in the field, which rests open here saying "Write anything" (`lib/circle.ts`); ↵ puts your words
   first in Today (`lib/inbox.ts`). While you write, the desk goes quiet behind the field, as the board does (S1.P3).

   Documents never lie here (KK, 7 Oct: "Mixind documents together with tasks honestly looks bad"): the ones no goal
   holds are first in Documents, under "No goal" (`DocsDesk.vue`). This replaces the day note above the Maybe column
   (WP-C, 2026-08-25): the field is the place to write now. */
import { onMounted, watch } from 'vue'
import GoalAffordance from '../kit-ext/goal-affordance/GoalAffordance.vue'
import InboxCard from './InboxCard.vue'
import { store } from '../store'
import { commandFilter } from '../lib/commandFilter'
import { inboxWriting } from '../lib/circle'
import { completeInboxGoal, inbox, loadInbox, shelves, today } from '../lib/inbox'
import { isPrivate } from '../lib/privacy'
import { openWindow } from '../lib/windows'
import { carry, pressCard, wasCarried } from '../lib/inboxCarry'
import { moving } from '../lib/moving'

onMounted(() => void loadInbox())
// Every board load follows a write somewhere (yours, the agent's, a live event): the Inbox reads again with it.
watch(() => store.state.board, () => void loadInbox())
// The card beside the field goes when the move ends: placed, sent with your words, or taken off (lib/moving.ts).
watch(() => moving.goalId, (id) => { if (!id || id !== carry.beside?.id) carry.beside = null })

function open(id: string, title: string, event: Event): void {
  if (wasCarried()) return
  openWindow({ kind: 'goal', target: id, title }, event.currentTarget as Element)
}
</script>

<template>
  <div class="inbox-desk" :class="{ 'inbox-desk--writing': inboxWriting && !!commandFilter.text }" data-cap="inbox">
    <h1 class="t-title inbox-desk__title">Inbox</h1>
    <section v-if="today.length" class="inbox-desk__today" data-role="inbox-today">
      <h2 class="inbox-desk__head">Today<span>{{ today.length }}</span></h2>
      <div class="inbox-desk__cards">
        <InboxCard v-for="item in today" :key="item.id" :item="item" :finding="inbox.finding.includes(item.id)" />
      </div>
    </section>
    <section v-for="shelf in shelves" :key="shelf.vertical" class="inbox-desk__shelf" :data-shelf="shelf.vertical">
      <h2 class="inbox-desk__head">{{ shelf.name }}<span>{{ shelf.goals.length }}</span></h2>
      <div class="inbox-desk__rows">
        <div
          v-for="goal in shelf.goals"
          :key="goal.id"
          class="inbox-row"
          :class="{ 'inbox-row--private': isPrivate(goal.id) }"
          :data-goal-id="goal.id"
          role="button"
          tabindex="0"
          @pointerdown="pressCard($event, goal)"
          @click="open(goal.id, goal.title, $event)"
          @keydown.enter.prevent="open(goal.id, goal.title, $event)"
        >
          <span class="inbox-row__square" @click.stop>
            <GoalAffordance kind="square" :color="goal.value_color" @toggle="(done: boolean) => done && completeInboxGoal(goal.id)" />
          </span>
          <span class="inbox-row__title">{{ goal.title }}</span>
        </div>
      </div>
    </section>
    <Teleport to="body">
      <div v-if="carry.item" class="inbox-carried" :style="{ left: `${carry.x}px`, top: `${carry.y}px`, width: `${Math.max(carry.width, 300)}px` }">
        <InboxCard :item="carry.item" />
      </div>
      <div v-if="carry.beside && moving.goalId === carry.beside.id" class="inbox-beside" data-role="inbox-beside">
        <InboxCard :item="carry.beside" />
      </div>
    </Teleport>
    <p v-if="inbox.loaded && !inbox.goals.length" class="inbox-desk__empty">Nothing waits here. What you write in the field lands in Today.</p>
  </div>
</template>

<style>
/* The desk: the window's grey ground, the board's column headline for its title, content 46 px in. */
.inbox-desk {
  box-sizing: border-box; height: 100%; min-width: 0; overflow-y: auto; padding: 0 46px 168px;
  background: #f5f5f7; color: #000;
}
.inbox-desk > * { transition: opacity 120ms ease; }
.inbox-desk--writing > * { opacity: .28; }
/* The title is the board's own column headline (`.t-title` at 31/40, as the kit sets it in a board header), not a
   heavier one (KK, 7 Oct 2026: "Why heavy headline for docs and inbox?"). */
.inbox-desk__title.t-title { margin: 18px 0 0 -24px; font-size: 31px; line-height: 40px; }
.inbox-desk__head { display: flex; align-items: baseline; gap: 8px; margin: 0; font: 500 15px/20px var(--font-body, Commissioner, system-ui, sans-serif); }
.inbox-desk__head span { color: rgb(45 48 54 / 52%); font-weight: 400; }
/* Today keeps the window's first 80 %: the shelves start below it however few cards there are. */
.inbox-desk__today { box-sizing: border-box; min-height: calc(80vh - 58px); padding: 38px 0 64px; }
.inbox-desk__cards { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 24px; align-items: start; margin-top: 12px; }
@media (max-width: 1100px) { .inbox-desk__cards { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
@media (max-width: 720px) { .inbox-desk__cards { grid-template-columns: minmax(0, 1fr); } }
.inbox-desk__shelf { padding-top: 30px; }
.inbox-desk__today + .inbox-desk__shelf { padding-top: 0; }
.inbox-desk__title + .inbox-desk__shelf { padding-top: 38px; }
/* The shelf's tasks in the board's own rows, six to a line. */
.inbox-desk__rows { display: grid; grid-template-columns: repeat(6, minmax(0, 1fr)); align-items: start; margin-top: 6px; }
@media (max-width: 1100px) { .inbox-desk__rows { grid-template-columns: repeat(4, minmax(0, 1fr)); } }
@media (max-width: 720px) { .inbox-desk__rows { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
/* The board's own compact rows (goalCard.css's collapsed goals): the same type, square, rounding and gap. */
.inbox-row { display: flex; align-items: flex-start; gap: var(--kkov-collapsed-goal-checkbox-text-gap, 8px); padding: 6px 16px 6px 0;
  border-radius: 6px; cursor: default; outline: none; }
.inbox-row:hover .inbox-row__title, .inbox-row:focus-visible .inbox-row__title { color: rgb(0 0 0 / 70%); }
.inbox-row__square { flex: none; display: block; width: var(--kkov-collapsed-goal-checkbox-size, 14px);
  height: var(--kkov-collapsed-goal-line-height, 19px); }
.inbox-row__square .goal-affordance, .inbox-row__square .goal-affordance .checkbox__box {
  width: var(--kkov-collapsed-goal-checkbox-size, 14px); height: var(--kkov-collapsed-goal-checkbox-size, 14px);
  min-width: var(--kkov-collapsed-goal-checkbox-size, 14px); min-height: var(--kkov-collapsed-goal-checkbox-size, 14px);
  border-radius: var(--kkov-collapsed-goal-checkbox-radius, 3px); }
.inbox-row__square .goal-affordance { position: relative; top: var(--kkov-collapsed-goal-checkbox-top, -1px); }
.inbox-row__title { min-width: 0; font: var(--kkov-collapsed-goal-font-weight, 500) var(--kkov-collapsed-goal-font-size, 12px)/var(--kkov-collapsed-goal-line-height, 19px)
  var(--kkov-collapsed-goal-font-family, Commissioner, system-ui, sans-serif); overflow-wrap: break-word; }
.inbox-row--private .inbox-row__title { color: transparent; background: #e4e4e4; border-radius: 2px; }
/* The card in the hand, and the card waiting beside the field: on its line, 12 px to its left, at its Today size. */
.inbox-carried { position: fixed; z-index: 290; pointer-events: none; transform: rotate(-1deg) scale(1.02); }  /* under the field (300), which takes it */
.inbox-carried .inbox-card { box-shadow: 0 0 0 .5px rgba(16, 18, 32, .06), 0 24px 60px -10px rgba(16, 18, 32, .3); }
.inbox-beside { position: fixed; z-index: 299; bottom: 24px; width: 443px; max-width: calc(50vw - 160px);
  left: calc(50% - var(--moving-field-width, 300px) / 2 - 12px - min(443px, calc(50vw - 160px)));
  transition: left 300ms var(--vt-ease-large); animation: inbox-beside-in 300ms var(--vt-ease-large) both; }
@keyframes inbox-beside-in { from { opacity: 0; transform: translateX(40px) scale(.96); } }
@media (prefers-reduced-motion: reduce) { .inbox-beside { transition: none; animation: none; } }
.inbox-desk__empty { margin: 38px 0 0; font: 400 15px/22px var(--font-body, Commissioner, system-ui, sans-serif); color: rgb(45 48 54 / 52%); }
</style>
