<script setup lang="ts">
/* The Inbox (Inbox and Documents redesign, rounds 3–11, KK 6–7 Oct 2026; .local-design/inbox-and-docs/final, section 2):
   everything with no date (`core/undated.py`) and every document, on the desk's grey. What you wrote today stands on top
   in the middle two quarters, big, as the wide column shows a goal, each with its goal above it: the last three, the rest
   behind "N more". Under it Earlier, the older tasks, and Documents, every document newest first, each a row you swipe
   as Finder's Recents; "Show all" opens a row in place onto shelves in the board's own order. A task and a document are
   one size, a quarter of the desk, and stay ghosts until the pointer brings one to life. The title and × stay at the top
   while the desk scrolls. You write in the field, which rests open here saying "Write to inbox" (`lib/circle.ts`); ↵ puts
   your words first in Today (`lib/inbox.ts`). While you write, the desk goes quiet behind the field, as the board does.
   Under Documents, Sources (docs/design/sources.md): the documents the morning report reads from, as the same chips, each
   with its state, red ones first; a source is not in Documents twice (`lib/sources.ts`). */
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
import { cardOf, loadSources, noteOf, sources } from '../lib/sources'
import { carry } from '../lib/inboxCarry'
import './inboxView.css'

/* A row holds the newest; "Show all" holds everything. */
const ROW = 24

const todayShown = computed(() => (inboxView.allToday ? today.value : today.value.slice(0, TODAY_SHOWN)))
const hiddenToday = computed(() => today.value.length - TODAY_SHOWN)

const onDocEdited = () => { void loadDesk(); void loadSources() }
onMounted(() => {
  void loadInbox()
  void loadDesk()
  void loadSources()
  window.addEventListener('verticals:doc-edited', onDocEdited)
})
onBeforeUnmount(() => window.removeEventListener('verticals:doc-edited', onDocEdited))
// Every board load follows a write somewhere (yours, the agent's, a live event, an answer to a source's check): the Inbox
// reads again with it.
watch(() => store.state.board, () => { void loadInbox(); void loadSources() })
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

    <section v-if="sources.list.length" class="inbox-desk__section" data-role="inbox-sources">
      <h2 class="inbox-desk__head">
        Sources<span class="inbox-desk__count">{{ sources.list.length }}</span>
        <button v-if="sources.list.length > 4" type="button" class="inbox-desk__all" data-role="inbox-sources-all" @click="inboxView.sources = !inboxView.sources">
          {{ inboxView.sources ? 'Show less' : 'Show all' }}
        </button>
      </h2>
      <div :class="inboxView.sources ? 'inbox-desk__grid' : 'inbox-desk__row'">
        <DocChip
          v-for="source in (inboxView.sources ? sources.list : sources.list.slice(0, ROW))" :id="source.id" :key="source.id"
          :doc="cardOf(source)" :note="noteOf(source).text" :tone="noteOf(source).tone"
        />
      </div>
    </section>

    <p v-if="inbox.loaded && desk.loaded && !inbox.goals.length && !recentDocs.length && !sources.list.length" class="inbox-desk__empty">
      Nothing waits here. What you write in the field lands at the top.
    </p>

    <Teleport to="body">
      <div v-if="carry.item" class="inbox-carried" data-role="inbox-carried" :style="{ left: `${carry.x}px`, top: `${carry.y}px`, width: `${carry.width}px` }">
        <InboxTile :item="carry.item" />
      </div>
    </Teleport>
  </div>
</template>
