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

   Agent-authored messages: `KCommentThread` already sets `data-author-role="agent"` on a message
   whose `role` prop is `'agent'` (compiled source, confirmed) — the kit ships no CSS for that
   attribute (it exists only to gate the kebab's own Approve item), so this file's own `<style>`
   block is what makes an agent message visibly distinct, via that same attribute. */
import { computed, nextTick, reactive, ref, watch } from 'vue'
import { KCommentNew, KCommentStack, KCommentThread } from '@konstantinopolskii/vue'
import AppIcon from './AppIcon.vue'
import { store } from '../store'
import type { CommentThread } from '../lib/api'

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
    v-if="store.state.comments.open"
    ref="rootEl"
    class="comments-panel"
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

<style>
/* Global, matching every other product-side component's own convention (new classes only).
   WP-B2 (KK ruling 2026-08-25, D255): a real viewport-docked sidebar overlay, not a block laid
   out inside whatever surface opened it — `position: fixed` against the viewport, not the card/
   doc pane, so it reads as "the sidebar" regardless of which one is open. Same fixed-panel idiom
   the dev panels already use (`DevColorPanel.vue` etc.: `position: fixed`, explicit background,
   a soft shadow to read as raised over the content it overlaps) rather than inventing a new one.
   `--inspector-w` is the kit's own token for exactly this width class (declared, unconsumed by
   kit CSS — vars.css's own comment says so — so this is its first consumer, on the product side,
   same as `--ease-quart` one token over). No backdrop, no scrim, no trapped focus: the board stays
   visible and clickable everywhere the panel does not physically cover (D248 — this is a docked
   panel, not a modal). `z-index: 250` sits above the fixed app nav (200) and the dev-only debug
   panels (300/301 — those are developer tooling, not product chrome, and are expected to still
   win on top when both are visible) but below the popover/menu layer (5000, `PopoverEngine.vue`)
   so an in-panel control never fights a tag/schedule popover for the top slot. */
.comments-panel {
  position: fixed;
  top: 0;
  right: 0;
  bottom: 0;
  z-index: 250;
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
  width: var(--inspector-w);
  max-width: 100vw;
  box-sizing: border-box;
  padding: var(--space-4) var(--space-5) var(--space-4) var(--space-4);
  border-left: 0.5px solid var(--color-border-strong);
  background: #ffffff;
  box-shadow: -2px 0 8px rgb(0 0 0 / 8%);
  overflow-y: auto;
}
.comments-panel__header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.comments-panel__close {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 24px;
  height: 24px;
  padding: 0;
  border: 0;
  border-radius: 4px;
  background: transparent;
  color: var(--color-text-muted);
  cursor: pointer;
}
.comments-panel__close:hover { background: var(--color-surface-overlay); color: var(--color-text); }

.comments-panel__anchor-preview {
  display: flex;
  align-items: baseline;
  gap: var(--space-1);
  padding: var(--space-2) var(--space-3);
  border-radius: 8px;
  background: var(--color-surface-overlay);
}
.comments-panel__anchor-quote {
  flex: 1 1 auto;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.comments-panel__anchor-clear {
  flex: 0 0 auto;
  display: flex;
  border: 0;
  background: transparent;
  color: var(--color-text-muted);
  cursor: pointer;
}

.comments-panel__stack { gap: var(--space-2); }
.comments-panel__state { padding: var(--space-2) var(--card-inset-x, 12px); }

.comments-panel__thread-row { display: flex; flex-direction: column; }
.comments-panel__thread-foot {
  display: flex;
  justify-content: flex-end;
  padding: 0 var(--card-inset-x, 12px);
}
.comments-panel__resolve {
  border: 0;
  background: transparent;
  padding: 4px 0;
  color: var(--color-text-muted);
  font-size: var(--fs-caption);
  cursor: pointer;
}
.comments-panel__resolve:hover { color: var(--color-text); }
.comments-panel__reply { margin: 0 var(--card-inset-x, 12px) var(--space-2); }

/* Agent-authored messages, visibly distinct — the kit sets `data-author-role="agent"`
   (KCommentThread's own render) but ships no styling for it (that attribute exists only to gate
   the kit's own Approve kebab item); this is the whole cue, applied here rather than upstream
   since it is this product's own voice choice, not a kit default. One cue (the label + rule),
   consistent with "one cue per state." */
.comment-msg[data-author-role='agent'] {
  border-left: 2px solid var(--color-border-strong);
  padding-left: calc(var(--card-inset-x, 12px) - 2px);
}
.comment-msg[data-author-role='agent']::before {
  content: 'Agent';
  display: block;
  color: var(--color-text-muted);
  font-size: var(--fs-micro);
  font-weight: var(--fw-bold);
  text-transform: uppercase;
  letter-spacing: 0.04em;
}

/* A highlighted anchor quote in the goal/doc body (`commentAnchor.ts::applyAnchorHighlights`). Not
   scoped to this component's own DOM (this `<style>` block is already global, matching every other
   component in this tree) — the mark itself lives inside GoalDetail.vue's/DocDetail.vue's body,
   never inside this panel, so the rule has to reach there regardless of which file declares it. */
mark.comment-highlight {
  background: color-mix(in srgb, var(--color-goal-yellow, #ecce32) 35%, transparent);
  color: inherit;
  cursor: pointer;
  border-radius: 2px;
}
mark.comment-highlight:hover {
  background: color-mix(in srgb, var(--color-goal-yellow, #ecce32) 55%, transparent);
}
</style>
