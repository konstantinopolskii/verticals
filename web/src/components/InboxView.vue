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

onMounted(() => void loadInbox())
// Every board load follows a write somewhere (yours, the agent's, a live event): the Inbox reads again with it.
watch(() => store.state.board, () => void loadInbox())

function open(id: string, title: string, event: Event): void {
  openWindow({ kind: 'goal', target: id, title }, event.currentTarget as Element)
}
</script>

<template>
  <div class="inbox-desk" :class="{ 'inbox-desk--writing': inboxWriting && !!commandFilter.text }" data-cap="inbox">
    <h1 class="inbox-desk__title">Inbox</h1>
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
    <p v-if="inbox.loaded && !inbox.goals.length" class="inbox-desk__empty">Nothing waits here. What you write in the field lands in Today.</p>
  </div>
</template>

<style>
/* The desk: the window's grey ground, the board's column head for its title (15/24 over 31/40), content 46 px in. */
.inbox-desk {
  box-sizing: border-box; height: 100%; min-width: 0; overflow-y: auto; padding: 0 46px 168px;
  background: #f5f5f7; color: #000;
}
.inbox-desk > * { transition: opacity 120ms ease; }
.inbox-desk--writing > * { opacity: .28; }
.inbox-desk__title { margin: 18px 0 0 -24px; font: 800 31px/40px var(--font-body, Commissioner, system-ui, sans-serif);
  letter-spacing: -.01em; }
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
.inbox-row { display: flex; align-items: flex-start; gap: 7.5px; padding: 6px 16px 6px 0; border-radius: 6px; cursor: default; outline: none; }
.inbox-row:hover .inbox-row__title, .inbox-row:focus-visible .inbox-row__title { color: rgb(0 0 0 / 70%); }
.inbox-row__square { flex: none; display: grid; place-items: center; width: 14px; height: 19px; }
.inbox-row__title { min-width: 0; font: 500 12px/19px var(--font-body, Commissioner, system-ui, sans-serif); overflow-wrap: break-word; }
.inbox-row--private .inbox-row__title { color: transparent; background: #e4e4e4; border-radius: 2px; }
.inbox-desk__empty { margin: 38px 0 0; font: 400 15px/22px var(--font-body, Commissioner, system-ui, sans-serif); color: rgb(45 48 54 / 52%); }
</style>
