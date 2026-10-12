<script setup lang="ts">
/* All of a document's comments, as a list over the field (docs/design/doc-comments-inline.md: "The count opens all the
   comments as a list over the field; a click on one takes you to its words"). The open ones first, in the order they were
   made; the resolved ones after, under their own small heading, so an unresolved one can still be reached. A row is the
   words the comment is about and the last thing said on it; a click closes the list and takes the window to those words,
   where the comment opens (DocCommentCard.vue). */
import { computed } from 'vue'
import { store } from '../store'
import { docThreads, threadWords } from '../lib/docComments'
import type { CommentThread } from '../lib/api'
import './docCommentList.css'

interface Row {
  thread: CommentThread
  /** "Agent" when the last thing said is the agent's: the one author worth naming. */
  who: string
  words: string
  resolved: boolean
  /** The first resolved one, which the small heading stands over. */
  first: boolean
}

const rows = computed<Row[]>(() => {
  const all = [
    ...docThreads.value.filter((thread) => thread.resolved_at === null),
    ...docThreads.value.filter((thread) => thread.resolved_at !== null),
  ]
  return all.map((thread, i) => {
    const last = thread.messages[thread.messages.length - 1]
    const resolved = thread.resolved_at !== null
    return {
      thread, who: last?.author === 'agent' ? 'Agent' : '', words: last?.body ?? '', resolved,
      first: resolved && (i === 0 || all[i - 1]!.resolved_at === null),
    }
  })
})
</script>

<template>
  <section class="doc-list" data-role="doc-comments-list" role="group" aria-label="Comments">
    <template v-for="row in rows" :key="row.thread.id">
      <h3 v-if="row.first" class="doc-list__head">Resolved</h3>
      <button
        type="button"
        class="doc-list__row"
        :class="{ 'doc-list__row--resolved': row.resolved }"
        data-role="doc-comments-row"
        :data-thread-id="row.thread.id"
        @click="store.openCard(row.thread.id)"
      >
        <span class="doc-list__words">{{ threadWords(row.thread) }}</span>
        <span class="doc-list__said"><b v-if="row.who">{{ row.who }}</b> {{ row.words }}</span>
      </button>
    </template>
  </section>
</template>
