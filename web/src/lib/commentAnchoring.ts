/** The Vue-facing half of anchored comments (docs/COMMENTS_SPEC.md WP-B) — `commentAnchor.ts`'s
 *  pure DOM functions, wired to `store` and to one component's own body ref/editing flag. Shared
 *  between `GoalDetail.vue` and `DocDetail.vue` (both render markdown into the same
 *  contenteditable-toggle node and both need the identical selection affordance, highlight repaint,
 *  and highlight-click-through) rather than duplicated per component — the two call sites differ
 *  only in target type/id and which ref is their body. Imports `store` directly, the same way the
 *  two components themselves already do (`import { store } from '../store'`); this is a composable
 *  consumed BY components, not a slice `store.ts` itself spreads in, so there is no circularity the
 *  way there would be if `lib/comments.ts` imported this back. */
import { computed, ref, watch, type Ref } from 'vue'
import { store } from '../store'
import { applyAnchorHighlights, captureSelectionAnchor, clearHighlights, type AnchorContext } from './commentAnchor'
import type { CommentTargetType } from './comments'

export interface CommentAnchoringOptions {
  bodyEl: Ref<HTMLElement | null>
  editing: Ref<boolean>
  targetType: CommentTargetType
  /** A getter, not a plain id — `GoalDetail.vue` keeps ONE instance across goal switches (the
   *  inline-detail host is reused per D226/D248), so the target id changes under this composable's
   *  feet; a getter reads the current one on every call instead of closing over a stale id. */
  targetId: () => string | null
}

export function useCommentAnchoring(opts: CommentAnchoringOptions) {
  const pendingSelection = ref<AnchorContext | null>(null)
  const selectionButtonPos = ref<{ x: number; y: number }>({ x: 0, y: 0 })

  /** This target's own anchored threads, in the `{id, quote, prefix, suffix}` shape
   *  `applyAnchorHighlights` wants. Empty (not stale data from a previous target) whenever
   *  `store.state.comments` is not currently loaded for `(targetType, targetId)` — the same guard
   *  `lib/comments.ts::unresolvedCommentCount` applies for the identical reason. */
  const anchoredThreads = computed(() => {
    const c = store.state.comments
    if (c.targetType !== opts.targetType || c.targetId !== opts.targetId()) return []
    return c.threads
      .filter((t) => t.anchor !== null)
      .map((t) => ({ id: t.id, quote: t.anchor!.quote, prefix: t.anchor!.prefix, suffix: t.anchor!.suffix }))
  })

  /** Called after every markdown (re)render, read-mode only — `bodyMarkdown.ts::renderBodyElement`
   *  fully replaces the body's children each time (`root.replaceChildren`), so there is never stale
   *  mark state to fight; `applyAnchorHighlights` itself still clears defensively (its own doc
   *  comment) for the case this runs twice with no render between (a threads-only update, below). */
  function paintHighlights(): void {
    const el = opts.bodyEl.value
    if (!el || opts.editing.value) return
    applyAnchorHighlights(el, anchoredThreads.value)
  }

  // A threads change with NO body re-render in between (a reply landed, a resolve toggled) still
  // needs a repaint — `paintHighlights` is idempotent and cheap (one DOM walk), so just re-running
  // it here rather than threading a "did threads change" flag through every render call site.
  watch(anchoredThreads, () => paintHighlights())

  /** Strips this component's own highlight marks before contenteditable turns on — a mark left in
   *  place is harmless to `serializeBodyElement` (unknown tags fall through to their text content,
   *  `bodyMarkdown.ts::serializeInlineNode`'s own default case), but leaving it would highlight text
   *  the user is actively editing, which reads as a stray artifact, not a feature. Call from each
   *  component's own "start editing" function. */
  function clearForEdit(): void {
    const el = opts.bodyEl.value
    if (el) clearHighlights(el)
  }

  /** A fresh mousedown always retires whatever "Comment" affordance the LAST selection raised —
   *  starting a new selection (or just clicking to place a caret) means the old one is no longer
   *  what the reader is looking at. */
  function onBodyMouseDown(): void {
    pendingSelection.value = null
  }

  /** Read-mode only (`editing` guard) — a mouseup while `contenteditable` is on is ordinary text
   *  editing, not a comment selection. Positions the floating button at the selection's own
   *  bounding box, top-center, so it reads as pointing at what was just selected. */
  function onBodyMouseUp(): void {
    if (opts.editing.value) return
    const el = opts.bodyEl.value
    const selection = window.getSelection()
    if (!el || !selection) {
      pendingSelection.value = null
      return
    }
    const anchor = captureSelectionAnchor(el, selection)
    if (!anchor) {
      pendingSelection.value = null
      return
    }
    const rect = selection.getRangeAt(0).getBoundingClientRect()
    pendingSelection.value = anchor
    selectionButtonPos.value = { x: rect.left + rect.width / 2, y: rect.top }
  }

  /** The floating "Comment" button's own click — stages the anchor, opens the panel armed with it
   *  (COMMENTS_SPEC.md WP-B: "creating captures quote/prefix/suffix from the selection"), and
   *  releases the browser's own text selection so it does not linger, visually competing with the
   *  panel that is about to open. */
  function commitSelectionToComment(): void {
    const id = opts.targetId()
    const anchor = pendingSelection.value
    if (!id || !anchor) return
    window.getSelection()?.removeAllRanges()
    pendingSelection.value = null
    // `openCommentsPanel` BEFORE `stageAnchor`, not after: `openCommentsPanel` -> `loadCommentsFor`
    // resets `state.comments.pendingAnchor` to null the moment it (re)establishes the current
    // target (`lib/comments.ts::loadCommentsFor`'s own "switching target" branch) — which fires
    // here whenever this is the first real commit against this target, not only on an actual
    // target SWITCH, because the goal/doc-open auto-fetch that seeds the badge count
    // (`GoalDetail.vue`'s own `watch` on `goal.value?.id`) can still be in flight when a fast
    // reader selects text and clicks Comment before it settles. Staging the anchor AFTER the
    // open call, rather than before, means it always lands on top of whatever that reset did,
    // synchronously, in the same tick `openCommentsPanel` returns in (its own `loadCommentsFor`
    // call is fire-and-forget past the first `await`, but the reset itself is the SYNCHRONOUS
    // half of that function, already complete by the time this line runs).
    store.openCommentsPanel(opts.targetType, id)
    store.stageAnchor(anchor)
  }

  /** Highlight click-through — called from each component's own existing body `@click` handler,
   *  BEFORE that handler's own read/edit-mode dispatch, so a highlight always opens its thread
   *  rather than also starting a body edit. Returns whether it handled the click, so the caller
   *  knows to stop (`GoalDetail.vue`'s own link-click carve-out is the precedent for this shape). */
  function onBodyClick(event: MouseEvent): boolean {
    const target = event.target as HTMLElement | null
    const mark = target?.closest?.('.comment-highlight')
    if (!mark) return false
    const threadId = mark.getAttribute('data-thread-id')
    const id = opts.targetId()
    if (!threadId || !id) return false
    event.preventDefault()
    store.openCommentsPanel(opts.targetType, id, threadId)
    return true
  }

  return {
    pendingSelection,
    selectionButtonPos,
    anchoredThreads,
    paintHighlights,
    clearForEdit,
    onBodyMouseDown,
    onBodyMouseUp,
    commitSelectionToComment,
    onBodyClick,
  }
}
