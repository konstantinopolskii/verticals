<script setup lang="ts">
/* D250 WP-3: one folder's row plus its own children, recursive by filename (Vue 3.5's own
   self-registration for `<script setup>` SFCs — `docs_view` naming precedent: the SFC file name
   IS the tag `DocsTreeFolder` resolves to inside its own template, no manual `components: {}`
   needed). A folder is nothing but a shared path prefix (`core/docs.py`'s own docstring, "no
   folder table") — `lib/docsView.ts::docTree` already grouped the flat list into this shape, so
   this component only walks and renders it.

   The root call (`DocsView.vue`) passes a folder whose `path` is `''` — the root never gets its
   own header row or a collapse toggle (there is nothing to fold: root IS the visible list). Every
   other folder renders a clickable header (chevron + name) and collapses/expands through
   `store.toggleFolder`/`isFolderCollapsed`, session-only view state `lib/docsView.ts` owns. */
import AppIcon from './AppIcon.vue'
import { store } from '../store'
import type { DocTreeFolder } from '../lib/docsView'

const props = defineProps<{ folder: DocTreeFolder }>()

function fileLabel(title: string | null, path: string): string {
  if (title) return title
  const name = path.split('/').pop() ?? path
  return name.replace(/\.md$/, '')
}
</script>

<template>
  <div class="docs-tree-folder">
    <div
      v-if="props.folder.path"
      class="docs-tree-folder__header"
      role="button"
      tabindex="0"
      data-role="docs-folder"
      :data-folder-path="props.folder.path"
      :aria-expanded="!store.isFolderCollapsed(props.folder.path)"
      @click="store.toggleFolder(props.folder.path)"
      @keydown.enter.prevent="store.toggleFolder(props.folder.path)"
      @keydown.space.prevent="store.toggleFolder(props.folder.path)"
    >
      <AppIcon
        :name="store.isFolderCollapsed(props.folder.path) ? 'chevron-right' : 'chevron-down'"
        :size="14"
      />
      <AppIcon name="folder" :size="15" />
      <span class="docs-tree-folder__name">{{ props.folder.name }}</span>
    </div>
    <div
      v-if="!props.folder.path || !store.isFolderCollapsed(props.folder.path)"
      class="docs-tree-folder__children"
      data-role="docs-folder-children"
    >
      <DocsTreeFolder v-for="child in props.folder.folders" :key="child.path" :folder="child" />
      <button
        v-for="doc in props.folder.docs"
        :key="doc.id"
        type="button"
        class="docs-tree-folder__doc"
        :class="{ 'docs-tree-folder__doc--active': doc.id === store.state.docs.currentId }"
        data-role="docs-tree-doc"
        :data-doc-id="doc.id"
        @click="store.openDoc(doc.id)"
      >
        <AppIcon name="file" :size="14" />
        <span class="docs-tree-folder__doc-title">{{ fileLabel(doc.title, doc.path) }}</span>
      </button>
    </div>
  </div>
</template>

<style>
/* Global, matching every other product-side component's own convention — new classes only. */
.docs-tree-folder__header,
.docs-tree-folder__doc {
  display: flex;
  align-items: center;
  gap: 6px;
  width: 100%;
  box-sizing: border-box;
  height: 30px;
  padding: 0 var(--space-2);
  margin: 0;
  border: 0;
  border-radius: 6px;
  background: transparent;
  color: var(--color-text);
  font-size: 14px;
  line-height: 30px;
  text-align: left;
  cursor: pointer;
}
.docs-tree-folder__header:hover,
.docs-tree-folder__doc:hover {
  background: var(--color-surface-overlay);
}
.docs-tree-folder__header:focus-visible,
.docs-tree-folder__doc:focus-visible {
  outline: 2px solid var(--color-border-strong);
  outline-offset: -2px;
}
.docs-tree-folder__name {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-weight: 500;
}
.docs-tree-folder__doc-title {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--color-text-muted);
}
.docs-tree-folder__doc--active {
  background: rgba(226, 226, 226, 0.77);
}
.docs-tree-folder__doc--active .docs-tree-folder__doc-title {
  color: var(--color-text);
}
.docs-tree-folder__children {
  padding-left: 16px;
}
</style>
