<script setup lang="ts">
/* Documents (Inbox and Documents redesign, rounds 2–7): the desk of stacks (`DocsDesk.vue`). A document opened by its
   address or a link (`lib/docsView.ts::openDoc`), and its history, take the whole view as before; a page clicked on the
   desk opens as a window instead (S3.P4). The folder tree is gone: a folder was nothing but a shared path prefix
   (`core/docs.py`), and the desk groups by the goal a document accumulates under. A new document still takes a path,
   from the desk's plus.

   `DocDetail.vue` is mounted with `:key="...currentId"` deliberately — a fresh instance per doc,
   not one instance reacting to a changing prop. See that file's own header comment for why this
   is what keeps a debounced body-save safe across a doc switch. */
import AppIcon from './AppIcon.vue'
import DocDetail from './DocDetail.vue'
import DocsDesk from './DocsDesk.vue'
import DocsHistory from './DocsHistory.vue'
import { store } from '../store'
</script>

<template>
  <div class="docs-view" data-cap="docs">
    <!-- The desk (round 7): every document as a page in its stack. A document opened by its address or a link, and its
         history, still take the whole view, as before; the desk comes back when they close. -->
    <section v-if="store.state.docs.historyOpen || store.state.docs.current || store.state.docs.currentLoading" class="docs-view__panel">
      <button type="button" class="docs-view__back" data-role="docs-back" @click="store.closeDoc()">
        <AppIcon name="chevron-left" :size="16" />Documents
      </button>
      <DocsHistory v-if="store.state.docs.historyOpen" />
      <DocDetail
        v-else-if="store.state.docs.current"
        :key="store.state.docs.currentId ?? undefined"
        :doc="store.state.docs.current"
      />
      <p v-else class="t-caption t-muted docs-view__loading">Loading…</p>
    </section>
    <DocsDesk v-else />
  </div>
</template>

<style>
.docs-view { display: flex; height: 100%; min-width: 0; overflow: hidden; }
.docs-view > .docs-desk { flex: 1 1 auto; }
.docs-view__panel { position: relative; flex: 1 1 auto; min-width: 0; height: 100%; overflow: hidden; }
.docs-view__loading { padding: var(--space-2); }
/* Back to the desk from a document opened by its address or a link. */
.docs-view__back { position: absolute; left: 16px; top: 12px; z-index: 2; display: inline-flex; align-items: center; gap: 2px; height: 28px;
  padding: 0 10px 0 4px; border: 0; border-radius: 8px; background: transparent; color: rgb(45 48 54 / 60%);
  font: 500 13px/20px var(--font-body, Commissioner, system-ui, sans-serif); cursor: pointer; }
.docs-view__back:hover { background: rgb(45 48 54 / 7%); color: #000; }
</style>
