<script setup lang="ts">
/* D250 WP-3: the right pane's live-doc editor — title, path (rename), body (the SAME markdown
   WYSIWYG machinery `GoalDetail.vue` uses, `lib/bodyMarkdown.ts`/`lib/bodyTextarea.ts` verbatim),
   linked-goal chips, and the History/Delete/Close footer.

   `DocsView.vue` mounts this with `:key="doc.id"` — a fresh instance per doc, not a component
   that reacts to its prop changing in place. That is what makes the body's debounced autosave
   safe: `revision` below is THIS INSTANCE's own local copy, advanced only from saves this
   instance itself performed, and `flushBodySave` on unmount (a doc switch, or leaving the Docs
   view) lands with the exact id/revision this instance opened — never `store.state.docs.current`,
   which may already point at a different doc by the time a debounced timer fires
   (`lib/docsView.ts::saveDoc`'s own header comment states the same reasoning from the other side). */
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { KChip } from '@konstantinopolskii/vue'
import AppIcon from './AppIcon.vue'
import { store } from '../store'
import type { DocDetail as DocDetailWire } from '../lib/api'
import { internalLinkOf, renderBodyElement, serializeBodyElement } from '../lib/bodyMarkdown'
import { useCommentAnchoring } from '../lib/commentAnchoring'
import {
  handleBodyBeforeInput,
  handleBodyKeydown,
  handleBodyPaste,
  normalizeBodyInput,
  resetBodyHistory,
} from '../lib/bodyTextarea'

const props = defineProps<{ doc: DocDetailWire }>()

const revision = ref(props.doc.revision)

// --- body: click-to-edit contenteditable, debounced save (mirrors GoalDetail.vue's body) -------

const BODY_SAVE_DEBOUNCE_MS = 1000
const bodyEl = ref<HTMLElement | null>(null)
const editingBody = ref(false)
let bodySaveTimer: number | null = null
let bodySaveDraft: string | null = null

// docs/COMMENTS_SPEC.md WP-B — `DocsView.vue` mounts this component fresh per doc (`:key="doc.id"`,
// this file's own header comment), so `targetId` can just read `props.doc.id` directly; no reuse-
// across-switches case the way GoalDetail.vue's inline host has.
const anchoring = useCommentAnchoring({
  bodyEl,
  editing: editingBody,
  targetType: 'doc',
  targetId: () => props.doc.id,
})

function paintBody(): void {
  void nextTick(() => {
    if (bodyEl.value && !editingBody.value) {
      renderBodyElement(bodyEl.value, props.doc.body)
      anchoring.paintHighlights()
    }
  })
}
paintBody()

async function flushBodySave(): Promise<void> {
  if (bodySaveTimer !== null) {
    window.clearTimeout(bodySaveTimer)
    bodySaveTimer = null
  }
  if (bodySaveDraft === null) return
  const body = bodySaveDraft
  bodySaveDraft = null
  const fresh = await store.saveDoc(props.doc.id, revision.value, { body })
  if (fresh) revision.value = fresh.revision
}

function queueBodySave(body: string): void {
  bodySaveDraft = body
  if (bodySaveTimer !== null) window.clearTimeout(bodySaveTimer)
  bodySaveTimer = window.setTimeout(() => void flushBodySave(), BODY_SAVE_DEBOUNCE_MS)
}

function startBodyEdit(): void {
  editingBody.value = true
  anchoring.clearForEdit()
  void nextTick(() => {
    if (!bodyEl.value) return
    resetBodyHistory(bodyEl.value)
    bodyEl.value.focus({ preventScroll: true })
  })
}

function onBodyClick(event: MouseEvent): void {
  if (anchoring.onBodyClick(event)) return
  const link = (event.target as HTMLElement).closest('a')
  if (link && !editingBody.value) {
    const internal = internalLinkOf(link)
    if (internal) {
      event.preventDefault()
      void store.followBodyLink(internal)
    }
    return
  }
  if (link) event.preventDefault()
  // See GoalDetail.vue's own onBodyClick for why: a click that just produced a comment-selection
  // is a drag-to-select gesture, not a position-the-caret click.
  if (!editingBody.value && !anchoring.pendingSelection.value) startBodyEdit()
}

function onBodyInput(event: InputEvent): void {
  if (!bodyEl.value || !editingBody.value) return
  normalizeBodyInput(event)
  queueBodySave(serializeBodyElement(bodyEl.value))
}

function finishBodyEdit(): void {
  if (!editingBody.value) return
  void flushBodySave()
  editingBody.value = false
  paintBody()
}

onBeforeUnmount(() => void flushBodySave())

// docs/COMMENTS_SPEC.md WP-B: this instance IS one doc's whole lifetime (this file's own header
// comment — a fresh mount per doc, never reused across a doc switch), so load-on-mount/close-on-
// unmount is the whole story; no id-change watcher the way GoalDetail.vue's reused host needs.
onMounted(() => void store.loadCommentsFor('doc', props.doc.id))
onBeforeUnmount(() => store.closeCommentsPanel())

// --- title: click-to-edit-in-place, commit on blur/Enter, cancel on Escape ----------------------

const editingTitle = ref(false)
const titleDraft = ref(props.doc.title ?? '')
const titleInputEl = ref<HTMLInputElement | null>(null)

function startTitleEdit(): void {
  titleDraft.value = props.doc.title ?? ''
  editingTitle.value = true
  void nextTick(() => titleInputEl.value?.select())
}

async function commitTitle(): Promise<void> {
  editingTitle.value = false
  const next = titleDraft.value.trim()
  const current = props.doc.title ?? ''
  if (next === current) return
  const fresh = await store.saveDoc(props.doc.id, revision.value, { title: next || null })
  if (fresh) revision.value = fresh.revision
}

function cancelTitleEdit(): void {
  editingTitle.value = false
  titleDraft.value = props.doc.title ?? ''
}

// --- path: same click-to-edit shape, renaming moves the doc in the tree -------------------------

const editingPath = ref(false)
const pathDraft = ref(props.doc.path)

function startPathEdit(): void {
  pathDraft.value = props.doc.path
  editingPath.value = true
}

async function commitPath(): Promise<void> {
  editingPath.value = false
  const next = pathDraft.value.trim()
  if (!next || next === props.doc.path) return
  const fresh = await store.saveDoc(props.doc.id, revision.value, { path: next })
  if (fresh) revision.value = fresh.revision
}

function cancelPathEdit(): void {
  editingPath.value = false
  pathDraft.value = props.doc.path
}

// --- delete: same "409/422 refusal surfaces honestly, no confirm dialog" shape as removeGoal ----

function onDelete(): void {
  void store.deleteCurrentDoc()
}

// --- comments: header icon + badge, same affordance shape as GoalDetailEditor.vue's own ----------

const commentCount = computed(() => store.unresolvedCommentCount('doc', props.doc.id))
const commentsOpenHere = computed(() => {
  const c = store.state.comments
  return c.open && c.targetType === 'doc' && c.targetId === props.doc.id
})
function onToggleComments(): void {
  if (commentsOpenHere.value) store.closeCommentsPanel()
  else store.openCommentsPanel('doc', props.doc.id)
}

function onLinkedGoalClick(goalId: string): void {
  void store.navigateToGoal(goalId)
}

watch(() => props.doc.body, () => { if (!editingBody.value) paintBody() })
</script>

<template>
  <div class="doc-detail" data-role="doc-detail">
    <div class="doc-detail__header">
      <div
        v-if="!editingPath"
        class="doc-detail__path t-caption t-muted"
        data-role="doc-path"
        tabindex="0"
        @click="startPathEdit"
        @keydown.enter.prevent="startPathEdit"
      >{{ props.doc.path }}</div>
      <input
        v-else
        class="doc-detail__path-input"
        data-role="doc-path-input"
        :value="pathDraft"
        @input="pathDraft = ($event.target as HTMLInputElement).value"
        @keydown.enter.prevent="commitPath"
        @keydown.esc.stop.prevent="cancelPathEdit"
        @blur="commitPath"
      >
      <div class="doc-detail__actions">
        <!-- docs/COMMENTS_SPEC.md WP-B: "same affordance in DocDetail.vue's header." -->
        <button
          type="button"
          class="doc-detail__action doc-detail__comments-trigger"
          data-cap="open-comments"
          :aria-expanded="commentsOpenHere"
          @click="onToggleComments"
        >
          <AppIcon name="comment" :size="16" /> Comments
          <span v-if="commentCount > 0" class="doc-detail__comments-badge" data-role="comments-badge">{{ commentCount }}</span>
        </button>
        <button type="button" class="doc-detail__action" data-role="doc-history-trigger" @click="store.loadHistory()">
          <AppIcon name="history" :size="16" /> History
        </button>
        <button type="button" class="doc-detail__action" data-role="doc-delete" @click="onDelete">
          <AppIcon name="trash" :size="16" /> Delete
        </button>
        <button type="button" class="doc-detail__action" data-role="doc-close" @click="store.closeDoc()">
          <AppIcon name="x" :size="16" />
        </button>
      </div>
    </div>

    <div
      v-if="!editingTitle"
      class="doc-detail__title t-hero"
      data-role="doc-title"
      tabindex="0"
      @click="startTitleEdit"
      @keydown.enter.prevent="startTitleEdit"
    >{{ props.doc.title || '(untitled)' }}</div>
    <input
      v-else
      ref="titleInputEl"
      class="doc-detail__title doc-detail__title-input t-hero"
      data-role="doc-title-input"
      :value="titleDraft"
      @input="titleDraft = ($event.target as HTMLInputElement).value"
      @keydown.enter.prevent="commitTitle"
      @keydown.esc.stop.prevent="cancelTitleEdit"
      @blur="commitTitle"
    >

    <!-- is-selectable: see GoalDetail.vue's own body div for why (style.css's documented
         opt-in past the app's global user-select:none, needed for WP-B's selection-to-comment
         affordance). -->
    <div
      ref="bodyEl"
      class="goal-detail__body doc-detail__body is-selectable"
      data-role="doc-body"
      data-placeholder="Write…"
      tabindex="0"
      role="textbox"
      aria-multiline="true"
      aria-label="Edit body"
      :contenteditable="editingBody ? 'true' : 'false'"
      spellcheck="false"
      translate="no"
      @click="onBodyClick"
      @beforeinput="handleBodyBeforeInput"
      @input="onBodyInput"
      @keydown="handleBodyKeydown"
      @paste="handleBodyPaste"
      @blur="finishBodyEdit"
      @mousedown="anchoring.onBodyMouseDown"
      @mouseup="anchoring.onBodyMouseUp"
    ></div>
    <!-- docs/COMMENTS_SPEC.md WP-B: selecting body text offers this (GoalDetail.vue's own
         `.goal-detail__comment-selection` — same class, same fixed-position shape, declared once
         in goalDetail.css since the coordinates and styling are identical regardless of which
         body raised it). -->
    <button
      v-if="anchoring.pendingSelection.value"
      type="button"
      class="goal-detail__comment-selection"
      data-cap="comment-selection"
      :style="{ left: `${anchoring.selectionButtonPos.value.x}px`, top: `${anchoring.selectionButtonPos.value.y}px` }"
      @mousedown.prevent="anchoring.commitSelectionToComment"
    >Comment</button>

    <div v-if="props.doc.linked_goals.length" class="chip-wrap doc-detail__links" data-role="doc-linked-goals">
      <KChip
        v-for="goal in props.doc.linked_goals"
        :key="goal.goal_id"
        data-role="doc-linked-goal-chip"
        :data-goal-id="goal.goal_id"
        @click="onLinkedGoalClick(goal.goal_id)"
      >{{ goal.title }}</KChip>
    </div>
  </div>
</template>

<style>
.doc-detail {
  display: flex;
  flex: 1 1 auto;
  flex-direction: column;
  gap: var(--space-3);
  height: 100%;
  min-width: 0;
  /* Bottom clears `.app-nav` (App.vue): fixed 16px from the bottom, 32px tall. */
  padding: var(--space-4) var(--space-5) var(--space-15);
  box-sizing: border-box;
  overflow: auto;
}
.doc-detail__header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-3);
}
.doc-detail__path {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  cursor: text;
}
.doc-detail__path-input {
  flex: 1 1 auto;
  min-width: 0;
  border: 0;
  border-bottom: 1px solid var(--color-border-strong);
  background: transparent;
  font: inherit;
  font-size: 13px;
  color: var(--color-text-muted);
}
.doc-detail__actions {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  flex: 0 0 auto;
}
.doc-detail__action {
  display: flex;
  align-items: center;
  gap: 4px;
  height: 28px;
  padding: 0 8px;
  border: 0;
  border-radius: 6px;
  background: transparent;
  color: var(--color-text-muted);
  font-size: 13px;
  cursor: pointer;
}
.doc-detail__action:hover { background: var(--color-surface-overlay); color: var(--color-text); }
.doc-detail__comments-trigger { position: relative; }
.doc-detail__comments-badge {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 14px;
  height: 14px;
  padding: 0 3px;
  border-radius: var(--radius-full, 9999px);
  background: var(--color-text);
  color: var(--color-bg);
  font-size: 10px;
  line-height: 14px;
}
.doc-detail__title.doc-detail__title {
  margin: 0;
  padding: 0;
  cursor: text;
  font-size: 30px;
  line-height: 38px;
  font-weight: 600;
  overflow-wrap: anywhere;
}
.doc-detail__title-input {
  border: 0;
  background: transparent;
  font-family: inherit;
  color: inherit;
  width: 100%;
}
.doc-detail__body {
  min-height: 200px;
  flex: 1 0 auto;
}
.doc-detail__links {
  padding-top: var(--space-2);
  border-top: 0.5px solid var(--color-border-strong);
}
</style>
