<script setup lang="ts">
/* The Inbox (Inbox and Documents redesign, rounds 3–11, KK 6–7 Oct 2026; .local-design/inbox-and-docs/final, section 2):
   everything with no date (`core/undated.py`) and every document, on the desk's grey. What you wrote today stands on top
   in the middle two quarters, big, as the wide column shows a goal, each with its goal above it: the last three, the rest
   behind "N more". Under it Earlier, the older tasks, and Documents, every document newest first, each a row you swipe
   as Finder's Recents; "Show all" opens a row in place onto shelves in the board's own order. A task and a document are
   one size, a quarter of the desk, and stay ghosts until the pointer brings one to life. The title and × stay at the top
   while the desk scrolls. You write in the field, which rests open here saying "Write to inbox" (`lib/circle.ts`); ↵ puts
   your words first in Today (`lib/inbox.ts`). While you write, the desk goes quiet behind the field, as the board does. */
import { computed, onBeforeUnmount, onMounted, watch } from 'vue'
import DeskHead from './DeskHead.vue'
import DocChip from './DocChip.vue'
import InboxCard from './InboxCard.vue'
import InboxTile from './InboxTile.vue'
import { store } from '../store'
import { commandFilter } from '../lib/commandFilter'
import { inboxWriting } from '../lib/circle'
import { docShelves, earlier, inbox, inboxView, loadInbox, recentDocs, shelves, today, TODAY_SHOWN } from '../lib/inbox'
import { desk, loadDesk } from '../lib/docsDesk'
import { carry } from '../lib/inboxCarry'
import { moving } from '../lib/moving'

/* A row holds the newest; "Show all" holds everything. */
const ROW = 24

const todayShown = computed(() => (inboxView.allToday ? today.value : today.value.slice(0, TODAY_SHOWN)))
const hiddenToday = computed(() => today.value.length - TODAY_SHOWN)

const onDocEdited = () => void loadDesk()
onMounted(() => {
  void loadInbox()
  void loadDesk()
  window.addEventListener('verticals:doc-edited', onDocEdited)
})
onBeforeUnmount(() => window.removeEventListener('verticals:doc-edited', onDocEdited))
// Every board load follows a write somewhere (yours, the agent's, a live event): the Inbox reads again with it.
watch(() => store.state.board, () => void loadInbox())
// The task beside the field goes when the move ends: placed, sent with your words, or taken off (lib/moving.ts).
watch(() => moving.goalId, (id) => { if (!id || id !== carry.beside?.id) carry.beside = null })
</script>

<template>
  <div class="inbox-desk" :class="{ 'inbox-desk--writing': inboxWriting && !!commandFilter.text }" data-cap="inbox">
    <DeskHead title="Inbox" />
    <section v-if="today.length" class="inbox-desk__today" data-role="inbox-today">
      <InboxCard v-for="item in todayShown" :key="item.id" :item="item" :finding="inbox.finding.includes(item.id)" />
      <button v-if="hiddenToday > 0" type="button" class="inbox-desk__more" data-role="inbox-more" @click="inboxView.allToday = !inboxView.allToday">
        {{ inboxView.allToday ? 'Show fewer' : `${hiddenToday} more` }}
        <svg width="11" height="11" viewBox="0 0 9 9" aria-hidden="true">
          <path :d="inboxView.allToday ? 'M2 5.5 4.5 3 7 5.5' : 'M2 3.5 4.5 6 7 3.5'" fill="none" stroke="currentColor" stroke-width="1.2" stroke-linecap="round" stroke-linejoin="round" />
        </svg>
      </button>
    </section>

    <section v-if="earlier.length" class="inbox-desk__section" data-role="inbox-earlier">
      <h2 class="inbox-desk__head">
        Earlier<span class="inbox-desk__count">{{ earlier.length }}</span>
        <button type="button" class="inbox-desk__all" data-role="inbox-earlier-all" @click="inboxView.earlier = !inboxView.earlier">
          {{ inboxView.earlier ? 'Show less' : 'Show all' }}
        </button>
      </h2>
      <template v-if="inboxView.earlier">
        <template v-for="shelf in shelves" :key="shelf.vertical">
          <h3 class="inbox-desk__shelf" :data-shelf="shelf.vertical">{{ shelf.name }}<span>{{ shelf.goals.length }}</span></h3>
          <div class="inbox-desk__grid"><InboxTile v-for="goal in shelf.goals" :key="goal.id" :item="goal" /></div>
        </template>
      </template>
      <div v-else class="inbox-desk__row"><InboxTile v-for="goal in earlier.slice(0, ROW)" :key="goal.id" :item="goal" /></div>
    </section>

    <section v-if="recentDocs.length" class="inbox-desk__section" data-role="inbox-docs">
      <h2 class="inbox-desk__head">
        Documents<span class="inbox-desk__count">{{ recentDocs.length }}</span>
        <button type="button" class="inbox-desk__all" data-role="inbox-docs-all" @click="inboxView.docs = !inboxView.docs">
          {{ inboxView.docs ? 'Show less' : 'Show all' }}
        </button>
      </h2>
      <template v-if="inboxView.docs">
        <template v-for="shelf in docShelves" :key="shelf.vertical">
          <h3 class="inbox-desk__shelf" :data-shelf="shelf.vertical">{{ shelf.name }}<span>{{ shelf.docs.length }}</span></h3>
          <div class="inbox-desk__grid"><DocChip v-for="doc in shelf.docs" :id="doc.id" :key="doc.id" :doc="doc" /></div>
        </template>
      </template>
      <div v-else class="inbox-desk__row"><DocChip v-for="doc in recentDocs.slice(0, ROW)" :id="doc.id" :key="doc.id" :doc="doc" /></div>
    </section>

    <p v-if="inbox.loaded && desk.loaded && !inbox.goals.length && !recentDocs.length" class="inbox-desk__empty">
      Nothing waits here. What you write in the field lands at the top.
    </p>

    <Teleport to="body">
      <div v-if="carry.item" class="inbox-carried" :style="{ left: `${carry.x}px`, top: `${carry.y}px`, width: `${carry.width}px` }">
        <InboxTile :item="carry.item" />
      </div>
      <div
        v-if="carry.beside && moving.goalId === carry.beside.id"
        class="inbox-beside"
        data-role="inbox-beside"
        :style="{ width: `${carry.width}px`, left: `calc(50% - var(--moving-field-width, 300px) / 2 - 12px - ${carry.width}px)` }"
      >
        <InboxTile :item="carry.beside" />
      </div>
    </Teleport>
  </div>
</template>

<style>
/* The desk: the window's grey ground, content 46 px in; a task and a document are a quarter of it wide (`--unit`). */
.inbox-desk {
  box-sizing: border-box; height: 100%; min-width: 0; overflow-y: auto; padding: 0 46px 168px; scroll-padding-top: 96px;
  background: #f5f5f7; color: #000;
}
.inbox-desk > * { transition: opacity 120ms ease; }
.inbox-desk--writing > * { opacity: .28; }
/* Today: the middle two quarters, the board's wide column; twice the usual space before Earlier (KK, round 11). */
.inbox-desk__today { display: flex; flex-direction: column; align-items: stretch; gap: 10px; box-sizing: border-box;
  width: calc(50% - 8px); min-width: min(100%, 520px); margin: 6px auto 0; padding-bottom: 88px; }
/* "N more": the carried box's own line, under the words. */
.inbox-desk__more { display: inline-flex; align-self: flex-start; align-items: center; gap: 4px; margin: -2px 0 0 34px; padding: 0; border: 0;
  background: none; font: 400 15px/20px var(--font-body, Commissioner, system-ui, sans-serif); color: rgb(45 48 54 / 52%); cursor: pointer; }
.inbox-desk__more:hover { color: #000; }
.inbox-desk__section { margin-top: 8px; }
.inbox-desk__section + .inbox-desk__section { margin-top: 18px; }
.inbox-desk__head { display: flex; align-items: baseline; gap: 8px; height: 20px; margin: 0; white-space: nowrap;
  font: 500 15px/20px var(--font-body, Commissioner, system-ui, sans-serif); }
.inbox-desk__count { color: rgb(45 48 54 / 52%); font-weight: 400; }
/* "Show all" at the section's right end, in black (KK, round 8: "Show all" not blue). */
.inbox-desk__all { margin-left: auto; padding: 0; border: 0; background: none; color: #000; cursor: pointer;
  font: 400 15px/20px var(--font-body, Commissioner, system-ui, sans-serif); }
.inbox-desk__all:hover { color: rgb(0 0 0 / 60%); }
/* A row you swipe: it runs to the window's edges, its scroll bar hidden, room above and below for a lifted card. */
.inbox-desk__row { display: flex; gap: 16px; margin: 0 -46px; padding: 12px 46px 26px; overflow-x: auto; overflow-y: hidden;
  overscroll-behavior-x: contain; scrollbar-width: none; scroll-padding-inline: 46px; }
.inbox-desk__row::-webkit-scrollbar { display: none; }
.inbox-desk__row > * { flex: none; width: calc((100% - 48px) / 4); height: 92px; }
.inbox-desk__shelf { display: flex; align-items: baseline; gap: 8px; margin: 20px 0 0; font: 500 13px/18px var(--font-body, Commissioner, system-ui, sans-serif); }
.inbox-desk__head + .inbox-desk__shelf { margin-top: 14px; }
.inbox-desk__shelf span { color: rgb(45 48 54 / 52%); font-weight: 400; }
.inbox-desk__grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px 16px; padding: 10px 0 6px; }
.inbox-desk__grid > * { height: 92px; }
@media (max-width: 1000px) {
  .inbox-desk__row > * { width: calc((100% - 32px) / 3); }
  .inbox-desk__grid { grid-template-columns: repeat(3, minmax(0, 1fr)); }
}
@media (max-width: 720px) {
  .inbox-desk__row > * { width: calc((100% - 16px) / 2); }
  .inbox-desk__grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}
/* The task in the hand, and the task waiting beside the field: on the field's line, 12 px to its left, at the tile's size. */
.inbox-carried { position: fixed; z-index: 290; pointer-events: none; transform: rotate(-1deg) scale(1.02); }  /* under the field (300), which takes it */
.inbox-carried .inbox-tile { background: #fff; box-shadow: 0 0 0 .5px rgb(16 18 32 / 6%), 0 24px 60px -10px rgb(16 18 32 / 30%); }
.inbox-beside { position: fixed; z-index: 299; bottom: 24px; max-width: calc(50vw - 160px);
  transition: left 300ms var(--vt-ease-large); animation: inbox-beside-in 300ms var(--vt-ease-large) both; }
.inbox-beside .inbox-tile { background: #fff;
  box-shadow: 0 0 0 .5px rgb(16 18 32 / 5%), 0 1px 3px rgb(16 18 32 / 4%), 0 8px 22px -12px rgb(16 18 32 / 14%); }
@keyframes inbox-beside-in { from { opacity: 0; transform: translateX(40px) scale(.96); } }
@media (prefers-reduced-motion: reduce) { .inbox-beside { transition: none; animation: none; } }
.inbox-desk__empty { margin: 6px 0 0; font: 400 15px/22px var(--font-body, Commissioner, system-ui, sans-serif); color: rgb(45 48 54 / 52%); }
</style>
