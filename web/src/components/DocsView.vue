<script setup lang="ts">
/* D250 WP-3: the Docs view — documents as first-class residents alongside goals (WP-1's own
   REST surface). Two panes, same shape as every other product view in this tree (Board's
   column strip, InboxView's single column): LEFT is the folder tree derived client-side from the
   flat `GET /api/docs` list (`lib/docsView.ts::docTree` — `core/docs.py`'s own "no folder table"
   rule, client side); RIGHT is either the open doc's editor (`DocDetail.vue`), its history
   (`DocsHistory.vue`), or an empty state when nothing is open yet.

   `DocDetail.vue` is mounted with `:key="...currentId"` deliberately — a fresh instance per doc,
   not one instance reacting to a changing prop. See that file's own header comment for why this
   is what keeps a debounced body-save safe across a doc switch. */
import { computed, nextTick, onMounted, ref } from 'vue'
import AppIcon from './AppIcon.vue'
import DocsTreeFolder from './DocsTreeFolder.vue'
import DocDetail from './DocDetail.vue'
import DocsHistory from './DocsHistory.vue'
import { store } from '../store'
import { docTree } from '../lib/docsView'

const tree = computed(() => docTree(store.state.docs.list))

// --- new doc: type a full path (subfolders included via '/') and commit on Enter ----------------
// Same "type + Enter commits" shape as `InlineAdd.vue`/`SubgoalAddRow.vue` — a path containing
// '/' is what CREATES the intermediate folder(s) in the tree (there is no separate "new folder"
// action; a folder is nothing but a shared path prefix, core/docs.py's own docstring).

const creating = ref(false)
const newPathDraft = ref('')
const newPathInput = ref<HTMLInputElement | null>(null)

function startCreate(): void {
  creating.value = true
  newPathDraft.value = ''
  void nextTick(() => newPathInput.value?.focus())
}

function cancelCreate(): void {
  creating.value = false
  newPathDraft.value = ''
}

async function commitCreate(): Promise<void> {
  const path = newPathDraft.value.trim()
  if (!path) return
  const withExt = path.endsWith('.md') ? path : `${path}.md`
  const ok = await store.createDoc(withExt)
  if (ok) cancelCreate()
}

onMounted(() => void store.loadDocs())
</script>

<template>
  <div class="docs-view" data-cap="docs">
    <aside class="docs-view__tree" data-role="docs-tree">
      <div class="docs-view__tree-header">
        <span class="t-caption t-muted">Documents</span>
        <button
          type="button"
          class="docs-view__new-trigger"
          data-role="docs-new-trigger"
          aria-label="New document"
          @click="creating ? cancelCreate() : startCreate()"
        >
          <AppIcon name="plus" :size="14" />
        </button>
      </div>
      <div v-if="creating" class="docs-view__new-row">
        <input
          ref="newPathInput"
          class="docs-view__new-input"
          data-role="docs-new-input"
          placeholder="folder/doc-name"
          :value="newPathDraft"
          @input="newPathDraft = ($event.target as HTMLInputElement).value"
          @keydown.enter.prevent="commitCreate"
          @keydown.esc.stop.prevent="cancelCreate"
          @blur="() => { if (!newPathDraft.trim()) cancelCreate() }"
        >
      </div>
      <p v-if="store.state.docs.listLoading" class="t-caption t-muted docs-view__loading">Loading…</p>
      <DocsTreeFolder v-else :folder="tree" />
    </aside>
    <section class="docs-view__panel">
      <DocsHistory v-if="store.state.docs.historyOpen" />
      <DocDetail
        v-else-if="store.state.docs.current"
        :key="store.state.docs.currentId ?? undefined"
        :doc="store.state.docs.current"
      />
      <p v-else-if="store.state.docs.currentLoading" class="t-caption t-muted docs-view__loading">Loading…</p>
      <div v-else class="docs-view__empty" data-role="docs-empty">
        <p class="t-caption t-muted">Select a document, or create one.</p>
      </div>
    </section>
  </div>
</template>

<style>
/* Global, matching every other product-side view's own convention (Board.vue, InboxView.vue) —
   new classes only. Two-pane layout mirrors the app shell's own nav+content split at a smaller
   scale, same box-sizing and overflow discipline. */
.docs-view {
  display: flex;
  height: 100%;
  min-width: 0;
  overflow: hidden;
}
.docs-view__tree {
  box-sizing: border-box;
  flex: 0 0 260px;
  width: 260px;
  height: 100%;
  padding: var(--space-4) var(--space-3);
  overflow-y: auto;
  border-right: 0.5px solid var(--color-border-strong);
}
.docs-view__tree-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 var(--space-2) var(--space-2);
}
.docs-view__new-trigger {
  width: 22px;
  height: 22px;
  display: flex;
  align-items: center;
  justify-content: center;
  border: 0;
  border-radius: 6px;
  background: transparent;
  color: var(--color-text-muted);
  cursor: pointer;
}
.docs-view__new-trigger:hover { background: var(--color-surface-overlay); color: var(--color-text); }
.docs-view__new-row {
  padding: 0 var(--space-2) var(--space-2);
}
.docs-view__new-input {
  box-sizing: border-box;
  width: 100%;
  height: 30px;
  padding: 0 8px;
  border: 1px solid var(--color-border-strong);
  border-radius: 6px;
  background: #fff;
  font-size: 13px;
}
.docs-view__loading {
  padding: var(--space-2);
}
.docs-view__panel {
  flex: 1 1 auto;
  min-width: 0;
  height: 100%;
  overflow: hidden;
}
.docs-view__empty {
  display: flex;
  align-items: center;
  justify-content: center;
  height: 100%;
}
</style>
