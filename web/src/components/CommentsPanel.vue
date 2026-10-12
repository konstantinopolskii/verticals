<script setup lang="ts">
/* docs/COMMENTS_SPEC.md WP-B, reworked WP-B2 (KK ruling 2026-08-25 — see docs/parity/DECISIONS.md
   D255): WP-B's first cut rendered this INLINE wherever its caller placed it — a stacked block at
   the bottom of `GoalDetail.vue`'s card, a right-hand column inside `DocDetail.vue`'s own wrapper.
   KK, verbatim, on the card: "Does it look like a sidebar, bro? ... the sidebar opens where you
   have the selected comment field and you can write." WP-B2's fix: ONE instance, mounted once at
   `App.vue`'s own root (`<CommentsPanel />`, no props), docked to the viewport's right edge,
   overlaying the board — not a second DOM copy per surface, not a child of the card/doc it is
   commenting on. Still not a modal (D248 stays true: "an overlay sidebar is a docked panel, not a
   modal" — no backdrop, no `role="dialog"`, no focus trap; the board underneath stays scrollable
   and clickable). `targetType` used to be a caller-supplied prop (`GoalDetail.vue`/`DocDetail.vue`
   each knew which kind of target they were); now that there is exactly one instance for the whole
   app, it reads `store.state.comments.targetType` directly instead — the same field that already
   decided which thread list to show. Fed entirely from `store.state.comments.threads` — structured
   rows, never the kit's own localStorage `innerHTML` snapshot (KK decision 5).

   Kit usage: `KCommentStack`/`KCommentThread`/`KCommentNew` are all used for real (not the
   plain-CSS-classes fallback the spec allows) — `KCommentThread`'s actual render
   (`@konstantinopolskii/vue/dist/index.js`) is a plain `title` + `messages[]` structural card with
   NO baked kebab menu, reply field, or `useCommentFlow` dependency; the kebab/reply chrome visible
   in the kit's own demo pages is hand-authored markup those demos build directly with
   `KCard`/`KCardCollapsible`, not something `KCommentThread` itself renders. Confirmed by reading
   the compiled component (not just the .d.ts) before committing to this — see the report for the
   full trail. `data-resolved="true"` is the kit's own documented pre-render hook for an
   already-resolved thread (`design-system/docs/integration/comment.md`'s own data-attribute
   table): it falls through as a plain HTML attribute (KCommentThread declares no `resolved` prop)
   and the kit's OWN CSS (`.comment-thread[data-resolved="true"] .card__collapsible{display:none}`)
   collapses the message list — "resolved threads collapse per kit behavior" is this one attribute,
   not custom accordion logic. Resolve/unresolve and reply are both domain actions the kit's own
   comment vocabulary does not model (it ships Approve/Edit/Archive/Delete, tied to
   `useCommentFlow`'s own local-DOM thread ids) — those live in the wrapper markup below as plain
   buttons and a `KCommentNew`, not inside `KCommentThread` itself (it has no slots to inject into).

   A document's comments are not here any more: they stand on their words and open over them (`DocCommentCard.vue`,
   docs/design/doc-comments-inline.md), so the panel stays shut while the target is a document; a goal's comments are
   as they were.

   Agent-authored messages: `KCommentThread` already sets `data-author-role="agent"` on a message
   whose `role` prop is `'agent'` (compiled source, confirmed) — the kit ships no CSS for that
   attribute (it exists only to gate the kebab's own Approve item), so `commentsPanel.css`
   is what makes an agent message visibly distinct, via that same attribute. */
import { computed, nextTick, reactive, ref, watch } from 'vue'
import { KCommentNew, KCommentStack, KCommentThread } from '@konstantinopolskii/vue'
import AppIcon from './AppIcon.vue'
import { store } from '../store'
import { windows } from '../lib/windows'
import type { CommentThread } from '../lib/api'
import './commentsPanel.css'

const rootEl = ref<HTMLElement | null>(null)
const newDraft = ref('')
const replyDrafts = reactive<Record<string, string>>({})

const threads = computed(() => store.state.comments.threads)
const pendingAnchor = computed(() => store.state.comments.pendingAnchor)
// One mount for the whole app (WP-B2) — the target kind is whatever the store currently has open,
// not a prop a per-surface caller would have supplied.
const targetType = computed(() => store.state.comments.targetType)

const QUOTE_TITLE_MAX = 60

function threadTitle(thread: CommentThread): string {
  const quote = thread.anchor?.quote.trim()
  if (quote) return quote.length > QUOTE_TITLE_MAX ? `${quote.slice(0, QUOTE_TITLE_MAX)}…` : quote
  return targetType.value === 'doc' ? 'Whole document' : 'Whole card'
}

function threadMessages(thread: CommentThread) {
  return thread.messages.map((m) => ({
    id: m.id,
    body: m.body,
    role: m.author === 'agent' ? 'agent' : undefined,
  }))
}

const composerTitle = computed(() => {
  if (pendingAnchor.value) return 'Comment on selection'
  return targetType.value === 'doc' ? 'Comment on this document' : 'Comment on this card'
})

async function commitNewThread(): Promise<void> {
  const body = newDraft.value
  if (!body.trim()) return
  const ok = await store.submitNewThread(body)
  if (ok) newDraft.value = ''
}

async function commitReply(threadId: string): Promise<void> {
  const body = replyDrafts[threadId] ?? ''
  if (!body.trim()) return
  const ok = await store.submitReply(threadId, body)
  if (ok) replyDrafts[threadId] = ''
}

function toggleResolve(thread: CommentThread): void {
  void store.setThreadResolved(thread.id, thread.resolved_at === null)
}

function close(): void {
  store.closeCommentsPanel()
}

// A highlight click (GoalDetail.vue/DocDetail.vue's own `commentAnchoring.ts::onBodyClick`) sets
// `focusThreadId`; this scrolls that thread's row into view once and clears the request so a
// second click on the same highlight still re-scrolls (a `watch` on the SAME value would not
// re-fire otherwise).
watch(
  () => store.state.comments.focusThreadId,
  (id) => {
    if (!id) return
    void nextTick(() => {
      const row = rootEl.value?.querySelector(`[data-role="comment-thread-row"][data-thread-id="${id}"]`)
      row?.scrollIntoView({ block: 'nearest', behavior: 'smooth' })
      store.state.comments.focusThreadId = null
    })
  },
)
</script>

<template>
  <aside
    v-if="store.state.comments.open && store.state.comments.targetType !== 'doc'"
    ref="rootEl"
    class="comments-panel"
    :class="{ 'comments-panel--over-windows': windows.list.length > 0 }"
    data-role="comments-panel"
    aria-label="Comments"
  >
    <div class="comments-panel__header">
      <span class="t-subtitle">Comments</span>
      <button
        type="button"
        class="comments-panel__close"
        data-role="comments-close"
        aria-label="Close comments"
        @click="close"
      ><AppIcon name="x" :size="16" /></button>
    </div>

    <div v-if="pendingAnchor" class="comments-panel__anchor-preview" data-role="comments-pending-anchor">
      <span class="t-caption t-muted">Commenting on:</span>
      <span class="t-caption comments-panel__anchor-quote">&ldquo;{{ pendingAnchor.quote }}&rdquo;</span>
      <button
        type="button"
        class="comments-panel__anchor-clear"
        aria-label="Comment on the whole card instead"
        @click="store.clearPendingAnchor()"
      ><AppIcon name="x" :size="12" /></button>
    </div>

    <KCommentStack class="comments-panel__stack">
      <KCommentNew
        data-role="comments-new"
        :title="composerTitle"
        placeholder="Write a comment…"
        commit-label="Comment"
        :model-value="newDraft"
        @update:model-value="newDraft = $event"
        @commit="commitNewThread"
      />

      <p v-if="store.state.comments.loading && !threads.length" class="t-caption t-muted comments-panel__state">
        Loading…
      </p>
      <p v-else-if="!threads.length" class="t-caption t-muted comments-panel__state" data-role="comments-empty">
        No comments yet.
      </p>

      <div
        v-for="thread in threads"
        :key="thread.id"
        class="comments-panel__thread-row"
        data-role="comment-thread-row"
        :data-thread-id="thread.id"
      >
        <KCommentThread
          :title="threadTitle(thread)"
          state="active"
          :messages="threadMessages(thread)"
          data-role="comment-thread"
          :data-thread-id="thread.id"
          :data-resolved="thread.resolved_at ? 'true' : undefined"
        />
        <div class="comments-panel__thread-foot">
          <button
            type="button"
            class="comments-panel__resolve"
            data-role="comment-resolve-toggle"
            @click="toggleResolve(thread)"
          >{{ thread.resolved_at ? 'Unresolve' : 'Resolve' }}</button>
        </div>
        <label v-if="!thread.resolved_at" class="field comment-thread__reply comments-panel__reply">
          <input
            class="t-caption field__input"
            type="text"
            placeholder="Reply…"
            data-role="comment-reply-input"
            :value="replyDrafts[thread.id] ?? ''"
            @input="replyDrafts[thread.id] = ($event.target as HTMLInputElement).value"
            @keydown.enter.prevent="commitReply(thread.id)"
          >
        </label>
      </div>
    </KCommentStack>
  </aside>
</template>
