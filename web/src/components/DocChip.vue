<script setup lang="ts">
// A document as one thing in a list (Inbox and Documents redesign, rounds 9–10; .local-design/inbox-and-docs/final, "A
// document as a chip"): its own first page on the left, as tall as three lines (50 × 67), and on the right its name, two
// lines at most, and when it was edited, from the top. In a message it sits on the balloon's black; in the Inbox it is a
// ghost on the desk until the pointer brings it to life. A click opens the document as a window (S3.P4). A source (the
// Inbox's Sources row, lib/sources.ts) is a document too: the line under its name is its state, "checked 07:00", and in red
// "not answering since 06:00", where a document says when it was edited.
import { computed } from 'vue'
import DocPage from './DocPage.vue'
import { docCard, type DocCard } from '../lib/docCard'
import { whenEdited } from '../lib/docsDesk'
import { openWindow } from '../lib/windows'
import './docChip.css'

const props = defineProps<{ id: string; doc?: DocCard | null; dark?: boolean; label?: string; note?: string; tone?: 'ok' | 'grey' | 'red' }>()

const card = computed(() => props.doc ?? docCard(props.id))
/* A document with no title is called by its file's name. */
const name = computed(() => card.value?.title || card.value?.path.split('/').pop() || props.label || 'Document')

function open(event: Event): void {
  openWindow({ kind: 'doc', target: props.id, title: name.value }, event.currentTarget as Element)
}
</script>

<template>
  <button type="button" class="doc-chip" :class="{ 'doc-chip--dark': dark }" data-role="doc-chip" :data-doc-id="id" @click.stop="open">
    <span class="doc-chip__page"><DocPage v-if="card" :doc="card" :width="50" /></span>
    <span class="doc-chip__text">
      <span class="doc-chip__name">{{ name }}</span>
      <span v-if="note" class="doc-chip__when" :class="{ 'doc-chip__when--red': tone === 'red' }" data-role="source-state" :data-tone="tone">{{ note }}</span>
      <span v-else-if="card" class="doc-chip__when">{{ whenEdited(card.updated_at) }}</span>
    </span>
  </button>
</template>
