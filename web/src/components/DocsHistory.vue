<script setup lang="ts">
/* D250 WP-3: the right pane's history mode — `DocsView.vue` swaps this in for `DocDetail.vue`
   while `store.state.docs.historyOpen` is true. Two states, never a modal (D248's own doctrine
   carried over: this app has one render world, and a history browser is not an exception) —
   the revision LIST (`store.state.docs.history`) and, once a row is clicked, one revision's text
   read-only (`store.state.docs.viewingRevision`). Restoring copies that text forward as a NEW
   revision (`core.docs.restore()`'s own docstring) and returns to the live doc; the UI says so
   rather than implying a rewind (`lib/docsView.ts::restoreRevision`'s own toast). */
import { nextTick, watch, ref } from 'vue'
import AppIcon from './AppIcon.vue'
import { store } from '../store'
import { internalLinkOf, renderBodyElement } from '../lib/bodyMarkdown'
import './docsHistory.css'

const bodyEl = ref<HTMLElement | null>(null)

function paintRevisionBody(): void {
  void nextTick(() => {
    const revision = store.state.docs.viewingRevision
    if (bodyEl.value && revision) renderBodyElement(bodyEl.value, revision.body)
  })
}
watch(() => store.state.docs.viewingRevision?.revision, paintRevisionBody, { immediate: true })

function onBodyClick(event: MouseEvent): void {
  const internal = internalLinkOf((event.target as HTMLElement).closest('a'))
  if (!internal) return
  event.preventDefault()
  void store.followBodyLink(internal)
}

function formatSavedAt(iso: string): string {
  return new Date(iso).toLocaleString()
}
</script>

<template>
  <div class="docs-history" data-role="docs-history">
    <div class="docs-history__toolbar">
      <button
        v-if="store.state.docs.viewingRevision"
        type="button"
        class="docs-history__back"
        data-role="docs-history-back"
        @click="store.backToHistoryList()"
      >
        <AppIcon name="arrow-left" :size="14" /> Back to history
      </button>
      <span v-else class="t-caption t-muted">History</span>
      <button
        type="button"
        class="docs-history__close"
        data-role="docs-history-close"
        aria-label="Close history"
        @click="store.closeHistory()"
      >
        <AppIcon name="x" :size="16" />
      </button>
    </div>

    <p v-if="store.state.docs.historyLoading" class="t-caption t-muted">Loading…</p>

    <template v-else-if="store.state.docs.viewingRevision">
      <div class="docs-history__revision-meta">
        <p class="t-caption t-muted">
          Revision {{ store.state.docs.viewingRevision.revision }} ·
          {{ formatSavedAt(store.state.docs.viewingRevision.saved_at) }}
        </p>
        <button
          type="button"
          class="docs-history__restore"
          data-role="docs-history-restore"
          @click="store.restoreRevision(store.state.docs.viewingRevision.revision)"
        >Restore this revision (as a new revision)</button>
      </div>
      <h2 class="docs-history__revision-title">
        {{ store.state.docs.viewingRevision.title || '(untitled)' }}
      </h2>
      <div
        ref="bodyEl"
        class="goal-detail__body"
        data-role="docs-history-body"
        :data-hide-title="store.state.docs.viewingRevision.title ?? undefined"
        @click="onBodyClick"
      ></div>
    </template>

    <ul v-else class="docs-history__list" data-role="docs-history-list">
      <li v-if="store.state.docs.history && store.state.docs.history.length === 0" class="t-caption t-muted">
        No saved revisions yet.
      </li>
      <li
        v-for="rev in store.state.docs.history ?? []"
        :key="rev.revision"
        class="docs-history__row"
        data-role="docs-history-row"
        :data-revision="rev.revision"
        role="button"
        tabindex="0"
        @click="store.viewRevision(rev.revision)"
        @keydown.enter.prevent="store.viewRevision(rev.revision)"
      >
        <span class="docs-history__row-revision">Rev {{ rev.revision }}</span>
        <span class="docs-history__row-title">{{ rev.title || '(untitled)' }}</span>
        <span class="docs-history__row-meta t-caption t-muted">
          {{ formatSavedAt(rev.saved_at) }} · {{ rev.body_length }} chars
        </span>
      </li>
    </ul>
  </div>
</template>
