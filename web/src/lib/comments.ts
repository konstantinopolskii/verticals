// The comments panel's whole state slice (docs/COMMENTS_SPEC.md WP-B) — same factory seam
// `lib/docsView.ts::createDocsView` already uses (see that file's own header comment): this closes
// over a slice of the store's shared reactive state and its error reporter, owns no transport
// policy of its own beyond the five `lib/api.ts` comment calls, and `store.ts` spreads its actions
// in unchanged.
//
// One current target at a time, the same "singular current detail" shape `state.docs.current`/
// `state.goalDetail` already use — a goal and a doc are never both showing comments at once in
// this app (one detail surface is open at a time), so there is exactly one `threads` array here,
// not a per-target cache. Switching target (a different goal opens, the doc pane switches docs)
// clears `threads` and reloads: `docs/COMMENTS_SPEC.md` WP-B's own line, "Refetch threads on panel
// open and after every own write," is the FLOOR, not the ceiling — `GoalDetail.vue`/`DocDetail.vue`
// also call `loadCommentsFor` the moment their own goal/doc loads (not gated on the panel being
// open at all), because the icon's own "open-thread count" badge needs real data to be worth
// anything; see this module's own `loadCommentsFor` doc comment.

import {
  addCommentMessage,
  createComment,
  fetchDocComments,
  fetchGoalComments,
  resolveComment,
  type CommentAnchor,
  type CommentThread,
} from './api'

export type CommentTargetType = 'goal' | 'doc'

export interface CommentsState {
  open: boolean
  targetType: CommentTargetType | null
  targetId: string | null
  threads: CommentThread[]
  loading: boolean
  /** A selection captured in the body, staged before the "new thread" composer commits it — null
   *  means the next commit creates a whole-card/whole-doc thread (COMMENTS_SPEC.md WP-B: "composing
   *  with NO selection creates a whole-card/whole-doc thread, anchor null"). */
  pendingAnchor: CommentAnchor | null
  /** A thread reached by clicking its highlight in the body — the panel scrolls to it once, then
   *  this clears itself (`CommentsPanel.vue`'s own watcher) so a second click on the same highlight
   *  still re-triggers the scroll. */
  focusThreadId: string | null
}

export function createInitialCommentsState(): CommentsState {
  return {
    open: false,
    targetType: null,
    targetId: null,
    threads: [],
    loading: false,
    pendingAnchor: null,
    focusThreadId: null,
  }
}

interface Deps {
  reportError: (err: unknown) => void
}

export function createCommentsPanel(state: { comments: CommentsState }, deps: Deps) {
  /** Fetches every thread for `(targetType, targetId)`. Switching target resets `threads`/
   *  `pendingAnchor`/`focusThreadId` first — a stale thread list or a selection staged against the
   *  PREVIOUS goal must never survive into the next one's panel. Guards its own write against a
   *  target switch that happened while the request was in flight (`state.comments.targetId`
   *  re-checked after the await), the same stale-response shape `docsView.ts::openDoc` uses. */
  async function loadCommentsFor(targetType: CommentTargetType, targetId: string): Promise<void> {
    if (state.comments.targetType !== targetType || state.comments.targetId !== targetId) {
      state.comments.targetType = targetType
      state.comments.targetId = targetId
      state.comments.threads = []
      state.comments.pendingAnchor = null
      state.comments.focusThreadId = null
    }
    state.comments.loading = true
    try {
      const res = targetType === 'goal' ? await fetchGoalComments(targetId) : await fetchDocComments(targetId)
      if (state.comments.targetType === targetType && state.comments.targetId === targetId) {
        state.comments.threads = res.threads
      }
    } catch (err) {
      deps.reportError(err)
    } finally {
      if (state.comments.targetType === targetType && state.comments.targetId === targetId) {
        state.comments.loading = false
      }
    }
  }

  /** The icon click (`GoalDetailEditor.vue`'s bottom row / `DocDetail.vue`'s header) and a
   *  highlight click both land here — `focusThreadId` is only ever set by the latter. Always
   *  refetches (COMMENTS_SPEC.md WP-B: "Refetch threads on panel open"), even when this target's
   *  threads are already loaded from the auto-fetch-on-open above, since a reply/resolve made by an
   *  agent between then and now would otherwise sit stale behind an already-open panel. */
  function openCommentsPanel(
    targetType: CommentTargetType, targetId: string, focusThreadId: string | null = null,
  ): void {
    state.comments.open = true
    state.comments.focusThreadId = focusThreadId
    void loadCommentsFor(targetType, targetId)
  }

  function closeCommentsPanel(): void {
    state.comments.open = false
    state.comments.pendingAnchor = null
    state.comments.focusThreadId = null
  }

  function stageAnchor(anchor: CommentAnchor): void {
    state.comments.pendingAnchor = anchor
  }

  function clearPendingAnchor(): void {
    state.comments.pendingAnchor = null
  }

  /** New whole-card/whole-doc or anchored thread, from whichever selection (if any) is currently
   *  staged. Refetches on success (WP-B: "... and after every own write") rather than splicing the
   *  response in locally — a create's own response is exactly one thread, so a local splice would
   *  save one request, but the refetch is what a reply from an agent racing this same write would
   *  also need, and keeping one reconciliation path is worth the extra round trip on a panel this
   *  low-traffic. */
  async function submitNewThread(body: string): Promise<boolean> {
    const trimmed = body.trim()
    const targetType = state.comments.targetType
    const targetId = state.comments.targetId
    if (!trimmed || !targetType || !targetId) return false
    try {
      await createComment({
        goal_id: targetType === 'goal' ? targetId : undefined,
        doc_id: targetType === 'doc' ? targetId : undefined,
        body: trimmed,
        anchor: state.comments.pendingAnchor ?? undefined,
      })
      state.comments.pendingAnchor = null
      await loadCommentsFor(targetType, targetId)
      return true
    } catch (err) {
      deps.reportError(err)
      return false
    }
  }

  async function submitReply(threadId: string, body: string): Promise<boolean> {
    const trimmed = body.trim()
    const targetType = state.comments.targetType
    const targetId = state.comments.targetId
    if (!trimmed || !targetType || !targetId) return false
    try {
      await addCommentMessage(threadId, trimmed)
      await loadCommentsFor(targetType, targetId)
      return true
    } catch (err) {
      deps.reportError(err)
      return false
    }
  }

  async function setThreadResolved(threadId: string, resolved: boolean): Promise<boolean> {
    const targetType = state.comments.targetType
    const targetId = state.comments.targetId
    if (!targetType || !targetId) return false
    try {
      await resolveComment(threadId, resolved)
      await loadCommentsFor(targetType, targetId)
      return true
    } catch (err) {
      deps.reportError(err)
      return false
    }
  }

  /** The bottom-row/header icon's own badge count — unresolved threads only ("open-thread count").
   *  Reads whatever `threads` currently holds for `(targetType, targetId)`; zero when that is not
   *  the currently loaded target (nothing has fetched yet, or another target has since loaded over
   *  it) rather than a stale count from a target this call no longer names. */
  function unresolvedCommentCount(targetType: CommentTargetType, targetId: string): number {
    if (state.comments.targetType !== targetType || state.comments.targetId !== targetId) return 0
    return state.comments.threads.filter((t) => t.resolved_at === null).length
  }

  return {
    loadCommentsFor,
    openCommentsPanel,
    closeCommentsPanel,
    stageAnchor,
    clearPendingAnchor,
    submitNewThread,
    submitReply,
    setThreadResolved,
    unresolvedCommentCount,
  }
}
