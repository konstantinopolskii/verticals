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
import DocCommentCard from './DocCommentCard.vue'
import { store } from '../store'
import { openWindow } from '../lib/windows'
import type { DocDetail as DocDetailWire } from '../lib/api'
import { internalLinkOf, renderBodyElement, serializeBodyElement, type InternalLink } from '../lib/bodyMarkdown'
import { useCommentAnchoring } from '../lib/commentAnchoring'
import { clearRewritten, lightRewritten, rewritten } from '../lib/docChanges'
import { onBeforeQuit } from '../lib/beforeQuit'
import {
  handleBodyBeforeInput,
  handleBodyKeydown,
  handleBodyPaste,
  normalizeBodyInput,
  resetBodyHistory,
} from '../lib/bodyTextarea'
import './docDetail.css'

/* `inWindow`: drawn in a document's window (S3.P4, DocWindowBody.vue) rather than in Documents. The window's one-line
   head stands for the path and the actions row (round 2, frame f2b): its facts, its versions that open history, its
   comments, its ×. Links in a window open beside it. */
const props = defineProps<{ doc: DocDetailWire; inWindow?: boolean }>()

const revision = ref(props.doc.revision)
const rootEl = ref<HTMLElement | null>(null)

// --- body: click-to-edit contenteditable, debounced save (mirrors GoalDetail.vue's body) -------

const BODY_SAVE_DEBOUNCE_MS = 1000
const bodyEl = ref<HTMLElement | null>(null)
const editingBody = ref(false)
let bodySaveTimer: number | null = null
let bodySaveDraft: string | null = null
/** The save on its way to the API, if any: "Check again" waits for it (lib/checkAgain.ts, `flushPending`). */
let bodySaving: Promise<void> | null = null

// docs/COMMENTS_SPEC.md WP-B — `DocsView.vue` mounts this component fresh per doc (`:key="doc.id"`,
// this file's own header comment), so `targetId` can just read `props.doc.id` directly; no reuse-
// across-switches case the way GoalDetail.vue's inline host has. A document's comments stand on their words and open
// over them (`inline`; docs/design/doc-comments-inline.md): DocCommentCard.vue.
const anchoring = useCommentAnchoring({
  bodyEl,
  editing: editingBody,
  targetType: 'doc',
  targetId: () => props.doc.id,
  inline: true,
})

/** A comment is open on its words, or being written on them. */
const cardOpen = computed(() => {
  const c = store.state.comments
  return c.targetType === 'doc' && c.targetId === props.doc.id && (c.cardId !== null || c.pendingAnchor !== null)
})

function paintBody(): void {
  void nextTick(() => {
    if (bodyEl.value && !editingBody.value) {
      renderBodyElement(bodyEl.value, props.doc.body)
      anchoring.paintHighlights()
      // What an agent rewrote is lit until you write in the document (lib/checkAgain.ts, lib/docChanges.ts).
      const lit = rewritten[props.doc.id]
      if (lit) lightRewritten(bodyEl.value, lit.before)
    }
  })
}
paintBody()
// A new look at the document by the agent starts clean: its earlier light goes out as the next one is made.
watch(() => rewritten[props.doc.id], (now, was) => { if (!now && was && bodyEl.value) clearRewritten(bodyEl.value) })

async function flushBodySave(): Promise<void> {
  if (bodySaveTimer !== null) {
    window.clearTimeout(bodySaveTimer)
    bodySaveTimer = null
  }
  if (bodySaveDraft === null) {
    await bodySaving
    return
  }
  const body = bodySaveDraft
  bodySaveDraft = null
  const saving = (async () => {
    const fresh = await store.saveDoc(props.doc.id, revision.value, { body })
    if (fresh) revision.value = fresh.revision
  })()
  bodySaving = saving
  await saving
  if (bodySaving === saving) bodySaving = null
}

function queueBodySave(body: string): void {
  bodySaveDraft = body
  if (bodySaveTimer !== null) window.clearTimeout(bodySaveTimer)
  bodySaveTimer = window.setTimeout(() => void flushBodySave(), BODY_SAVE_DEBOUNCE_MS)
}

function startBodyEdit(): void {
  editingBody.value = true
  anchoring.clearForEdit()
  // Writing puts the light out, and a comment open on words that are about to be written over closes.
  if (bodyEl.value) clearRewritten(bodyEl.value)
  delete rewritten[props.doc.id]
  store.closeCard()
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
      if (props.inWindow) void openBeside(internal, link)
      else void store.followBodyLink(internal)
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

onBeforeUnmount(onBeforeQuit(flushBodySave))
onBeforeUnmount(() => void flushBodySave())

// docs/COMMENTS_SPEC.md WP-B: this instance IS one doc's whole lifetime (this file's own header
// comment — a fresh mount per doc, never reused across a doc switch), so load-on-mount/close-on-
// unmount is the whole story; no id-change watcher the way GoalDetail.vue's reused host needs.
onMounted(() => void store.loadCommentsFor('doc', props.doc.id))
onBeforeUnmount(() => {
  store.closeCommentsPanel()
  delete rewritten[props.doc.id]
})

// An agent's rewrite (Check again, lib/checkAgain.ts) arrives as a newer copy of the document: the next save builds on it,
// unless words of yours are still waiting out their debounce.
watch(() => props.doc.revision, (next) => { if (bodySaveDraft === null && next > revision.value) revision.value = next })

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
  // Enter unmounts the input, and Chromium then fires blur: without this, a second PATCH on a stale revision.
  if (!editingTitle.value) return
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
  if (!editingPath.value) return
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

function onLinkedGoalClick(goalId: string, event?: MouseEvent): void {
  if (props.inWindow) {
    const title = props.doc.linked_goals.find((g) => g.goal_id === goalId)?.title ?? 'Goal'
    openWindow({ kind: 'goal', target: goalId, title }, (event?.currentTarget as Element | null) ?? null)
  } else {
    void store.navigateToGoal(goalId)
  }
}

/* In a window a link opens its goal or document as one more window beside it (S3.P4), as GoalLinks.vue does, and the
   board stays where it is. */
async function openBeside(link: InternalLink, from: HTMLAnchorElement): Promise<void> {
  const title = from.textContent?.trim()
  if (link.kind === 'goal') {
    openWindow({ kind: 'goal', target: link.target, title: title || 'Goal' }, from)
    return
  }
  const id = await store.docIdByPath(link.target)
  if (id) openWindow({ kind: 'doc', target: id, title: title || link.target }, from)
}

watch(() => [props.doc.body, props.doc.title], () => { if (!editingBody.value) paintBody() })
</script>

<template>
  <div ref="rootEl" class="doc-detail" data-role="doc-detail">
    <div v-if="!inWindow" class="doc-detail__header">
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
      :data-hide-title="props.doc.title ?? undefined"
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
    <!-- A comment on its words, or the field to write one in, stands under them (docs/design/doc-comments-inline.md). -->
    <DocCommentCard v-if="cardOpen && rootEl && bodyEl" :host="rootEl" :body="bodyEl" :paints="anchoring.paints.value" />
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
        @click="onLinkedGoalClick(goal.goal_id, $event)"
      >{{ goal.title }}</KChip>
    </div>
  </div>
</template>
