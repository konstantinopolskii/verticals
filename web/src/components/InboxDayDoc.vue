<script setup lang="ts">
/* WP-C (KK, 2026-08-25 — verbatim: "In the INBOX SECTION from now on ABOVE the task list THERE
   SHOULD BE LIKE A DOCUMENT OPENED BY DEFAULT, EXACTLY THE ONE THAT WE SAVE TO THE DOC SECTION
   AUTOMATICALLY. AND YOU SIMPLY CAN OPEN INBOX AND WRITE THERE."): the day-log doc
   (`inbox/YYYY-MM-DD.md`, `docs/COMMENTS_SPEC.md`'s own convention) rendered open and editable
   ABOVE `InboxView.vue`'s Maybe column. SAME document `DocsView.vue`/`DocDetail.vue` show for the
   identical path — this component talks to the exact same `lib/api.ts` doc endpoints DocDetail.vue
   uses (`expected_revision` optimistic lock, a 409 becomes the same "changed elsewhere" toast +
   Reload action), so an edit made here shows up in the Docs view on its next open and vice versa,
   no sync code needed beyond the normal fetch-on-open every doc already does.

   Lazy creation (task brief): this surface renders even when today's doc does not exist yet — the
   doc is created on the first COMMITTED (non-empty) body, never on mount, so an empty day never
   creates an empty row. `doc` below starts `null` and stays that way until `flush()`'s own create
   branch runs.

   Body-editing state (paint/debounce-save/edit-toggle) below duplicates the shape of DocDetail.
   vue's own body editor rather than extracting a shared composable: DocDetail's version is wired
   into `useCommentAnchoring` (its `onBodyClick` calls into anchoring before anything else) and is
   covered by `tests/ui/test_docs_view.py` / `test_comments_panel.py` — both OUTSIDE this change's
   gate (KK ruling 2026-08-25: partial E2E only for a delivery, the full suite runs nightly).
   Touching DocDetail.vue without re-running those suites is the riskier move; duplicating the
   ~40-line pattern while reusing the exact same underlying `bodyMarkdown.ts`/`bodyTextarea.ts`
   engine is the boring, low-risk one — flagged in the report, not decided quietly. */
import { nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import { toast } from '@konstantinopolskii/vue'
import { store, todayIso } from '../store'
import {
  ApiError,
  createDoc as apiCreateDoc,
  fetchDocs,
  getDoc,
  saveDoc as apiSaveDoc,
  type DocDetail,
} from '../lib/api'
import { messageForError } from '../lib/scheduleFeedback'
import { internalLinkOf, renderBodyElement, serializeBodyElement } from '../lib/bodyMarkdown'
import {
  handleBodyBeforeInput,
  handleBodyKeydown,
  handleBodyPaste,
  normalizeBodyInput,
  resetBodyHistory,
} from '../lib/bodyTextarea'
import { dayDocPath, dayDocTitle } from '../lib/dayDoc'

const BODY_SAVE_DEBOUNCE_MS = 1000 // matches DocDetail.vue's own constant, same name, same value

// `store.ts`'s own `todayIso()` — the app's one clock read (its header comment: plain `new
// Date()` inside that ONE function, pinned transparently in the `ui` suite via
// `page.clock.setFixedTime`). Read once at setup, not per-render: this component's whole lifetime
// is "today", the same day the board's own rollover (`lib/dayRollover.ts`) would tear it down and
// remount a fresh Inbox for anyway once midnight actually passes.
const iso = todayIso()
const path = dayDocPath(iso)
const title = dayDocTitle(iso)

const doc = ref<DocDetail | null>(null)
const loading = ref(true)
const editing = ref(false) // flips true the moment load() resolves — see enterEdit() below
const bodyEl = ref<HTMLElement | null>(null)

let saveTimer: number | null = null
let saveDraft: string | null = null

function renderCurrent(): void {
  void nextTick(() => {
    if (bodyEl.value && !editing.value) renderBodyElement(bodyEl.value, doc.value?.body ?? '')
  })
}

function enterEdit(): void {
  editing.value = true
  void nextTick(() => {
    if (!bodyEl.value) return
    resetBodyHistory(bodyEl.value)
    bodyEl.value.focus({ preventScroll: true })
  })
}

/** Finds today's doc, if it already exists, by scanning the flat `GET /api/docs` list for its
 *  path — there is no by-path route (`lib/docsView.ts`'s own header: no folder table, no extra
 *  index either side of the wire). Editing starts only once this resolves, deliberately: starting
 *  `editing` true from mount would let a keystroke land in the empty box during the fetch and
 *  then get clobbered the instant an existing doc's body arrives. */
async function load(): Promise<void> {
  try {
    const { docs } = await fetchDocs()
    const summary = docs.find((d) => d.path === path)
    if (summary) doc.value = await getDoc(summary.id)
  } catch (err) {
    toast(messageForError(err))
  } finally {
    loading.value = false
    // `loading` flipping swaps the template's v-if/v-else, so `bodyEl` only exists once Vue has
    // applied that patch — wait the one tick, then paint (unguarded: nothing can be "editing" a
    // component that has not finished mounting yet) and only THEN call enterEdit(), which flips
    // `editing` to true. Calling enterEdit() first would set `editing.value = true` synchronously,
    // before renderCurrent()'s own deferred nextTick runs — its `!editing.value` guard would then
    // see `true` and skip the paint entirely, leaving an existing doc's body never shown. Confirmed
    // live: exactly this ordering bug, caught by `tests/ui/test_inbox_daydoc.py::
    // test_preexisting_today_doc_content_loads_in_inbox`.
    void nextTick(() => {
      if (bodyEl.value) renderBodyElement(bodyEl.value, doc.value?.body ?? '')
      enterEdit()
    })
  }
}

onMounted(() => void load())

/** Create-or-save, mirroring `lib/docsView.ts::saveDoc`'s own 409 handling verbatim (same toast
 *  copy, same Reload action) for the "already exists" branch. The "doesn't exist yet" branch is
 *  this component's own addition — lazy creation has no DocDetail.vue precedent to mirror, since
 *  DocDetail always opens an already-created doc. */
async function flush(): Promise<void> {
  if (saveTimer !== null) {
    window.clearTimeout(saveTimer)
    saveTimer = null
  }
  if (saveDraft === null) return
  const body = saveDraft
  saveDraft = null
  if (!doc.value && body.trim() === '') return // never create an empty day doc
  try {
    if (doc.value) {
      const updated = await apiSaveDoc(doc.value.id, { expected_revision: doc.value.revision, body })
      doc.value = updated
    } else {
      doc.value = await apiCreateDoc({ path, title, body })
    }
    renderCurrent()
  } catch (err) {
    if (err instanceof ApiError && err.status === 409) {
      toast('This document changed elsewhere — your edit was not saved.', {
        action: 'Reload', onAction: () => void load(),
      })
      return
    }
    toast(messageForError(err))
  }
}

function queueSave(body: string): void {
  saveDraft = body
  if (saveTimer !== null) window.clearTimeout(saveTimer)
  saveTimer = window.setTimeout(() => void flush(), BODY_SAVE_DEBOUNCE_MS)
}

function onInput(event: InputEvent): void {
  if (!bodyEl.value || !editing.value) return
  normalizeBodyInput(event)
  queueSave(serializeBodyElement(bodyEl.value))
}

function onClick(event: MouseEvent): void {
  const link = (event.target as HTMLElement).closest('a')
  // S-72 / DocDetail.vue's own onBodyClick: a link stays a link in view mode.
  if (link && !editing.value) {
    const internal = internalLinkOf(link)
    if (internal) {
      event.preventDefault()
      void store.followBodyLink(internal)
    }
    return
  }
  if (link) event.preventDefault()
  if (!editing.value) enterEdit()
}

function finishEdit(): void {
  if (!editing.value) return
  void flush()
  editing.value = false
  renderCurrent()
}

onBeforeUnmount(() => void flush())
</script>

<template>
  <div class="inbox-day-doc" data-cap="inbox-day-doc" data-role="inbox-day-doc">
    <p v-if="loading" class="t-caption t-muted inbox-day-doc__loading" data-role="inbox-day-doc-loading">
      Loading…
    </p>
    <template v-else>
      <div class="t-caption t-muted inbox-day-doc__title" data-role="inbox-day-doc-title">{{ title }}</div>
      <div
        ref="bodyEl"
        class="goal-detail__body doc-detail__body inbox-day-doc__body is-selectable"
        data-role="inbox-day-doc-body"
        data-placeholder="Write…"
        tabindex="0"
        role="textbox"
        aria-multiline="true"
        aria-label="Today's note"
        :contenteditable="editing ? 'true' : 'false'"
        spellcheck="false"
        translate="no"
        @click="onClick"
        @beforeinput="handleBodyBeforeInput"
        @input="onInput"
        @keydown="handleBodyKeydown"
        @paste="handleBodyPaste"
        @blur="finishEdit"
      ></div>
    </template>
  </div>
</template>

<style>
/* Global, matching every other product-side component's own convention (InboxView.vue's own
   header comment states the house rule again) — new classes only, plain CSS, no kit rule
   invented. Plain border + radius from existing tokens (same shape DocDetail.vue's own
   `.doc-detail__links` border-top uses), not the kit's `.card` — that class carries goal-card
   hover/active semantics (`design-system/style.css`) this static surface has no business with. */
.inbox-day-doc {
  flex: 0 0 auto;
  box-sizing: border-box;
  border: 0.5px solid var(--color-border-strong);
  border-radius: var(--radius-md);
  padding: var(--space-4) var(--space-5);
}
.inbox-day-doc__loading {
  margin: 0;
}
.inbox-day-doc__title {
  margin: 0 0 var(--space-2);
}
.inbox-day-doc__body.inbox-day-doc__body {
  min-height: 96px;
}
</style>
