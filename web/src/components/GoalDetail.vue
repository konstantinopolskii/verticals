<script setup lang="ts">
/* D248 WP-C: the modal/drawer surface is gone. This component renders ONLY the board-hosted
   inline detail (`goal-detail-inline`) — GoalCard.vue mounts/unmounts it per card
   (`v-if="isInlineDetailHost"`), so there is no cross-goal lifecycle to manage here beyond the
   inline open/close animation and body edit/save flow below. P-28 keeps one safe rendered DOM in
   read/edit states, with optimistic local state and debounced Markdown PATCHes.

   The cleaned-up card (KK, 27 Sep 2026: "I love it. Let's implement"): this is the open goal's notes, at the end of
   its piece, after its steps. The title, its facts line and the steps are the card's (GoalCard.vue, GoalFacts.vue),
   so nothing here repeats them: no icon row, no pills. The documents the agent linked on lines of their own leave the
   notes for one line after them; long notes show ten lines and say what is left; the card never scrolls inside. */
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import GoalDetailEditor from './GoalDetailEditor.vue'
import GoalLinks from './GoalLinks.vue'
import { store } from '../store'
import { internalLinkOf, renderBodyElement, serializeBodyElement } from '../lib/bodyMarkdown'
import { useCommentAnchoring } from '../lib/commentAnchoring'
import { onBeforeQuit } from '../lib/beforeQuit'
import { MONTH_NAMES } from '../lib/periods'
import { leaveRoom, roomFor } from '../lib/columnRoom'
import {
  handleBodyBeforeInput,
  handleBodyKeydown,
  handleBodyPaste,
  normalizeBodyInput,
  resetBodyHistory,
} from '../lib/bodyTextarea'

const goal = computed(() => store.state.goalDetail)
const loading = computed(() => store.state.goalDetailLoading)
const OPEN_MS = 360 // `goalDetail.css`'s opening: the column scrolls in step with it

/* Closing is at once: the card's facts line, "Add…" and these notes fold away together in GoalCard.vue's leave
   transitions. It used to wait out a 360 ms fold that never ran (the opening animation's fill held the notes open),
   then snap shut (the motion trace, 27 Sep 2026). */
function requestClose() {
  if (store.state.openGoalId === null) return
  store.closeFamily()
}

/* A goal in a window goes with its window: Esc and × there (docs/design-handoff S3.P2.011), never a press beside it. */
const inWindow = () => store.state.openGoalVertical === 'window'

function onDetailKeydown(event: KeyboardEvent) {
  if (store.state.openGoalId === null || inWindow()) return
  const hosted = document.querySelector<HTMLElement>(
    '#dropdownPortal [data-popover-surface][data-state="open"]',
  )
  if (event.key === 'Escape') {
    if (hosted || store.state.drag.id !== null || store.state.drag.settling) return // Esc in a drag cancels only the drag
    event.preventDefault()
    store.goUp() // flow 4: up one level; at the first level, close
  }
}

function onInlinePointerDown(event: PointerEvent) {
  if (store.state.openGoalId === null || inWindow()) return
  const target = event.target as HTMLElement | null
  if (!target) return
  // WP-B2: the comments panel now docks to the viewport edge, mounted at `App.vue`'s own level
  // (`CommentsPanel.vue`'s header comment) — no longer a descendant of `[data-goal-id]`. Without
  // this, writing a reply or clicking Resolve inside the panel would register as a pointerdown
  // OUTSIDE the card and collapse it mid-write. The open goal's steps list (`data-open-region`)
  // is part of the card: a press between its steps is not a press outside. A view's tag over the circle closes the goal
  // itself when its click changes the view; closed first, on the press, the goal rewound the address to the view it was
  // opened from, and that rewind landed after the click: leaving Inbox over an open Inbox goal stayed in Inbox.
  if (target.closest('#goal-detail, #dropdownPortal, [data-goal-id], [data-open-region], [data-role="comments-panel"], .circle-tag')) return
  requestClose()
}

onMounted(() => {
  document.addEventListener('keydown', onDetailKeydown)
  document.addEventListener('pointerdown', onInlinePointerDown)
  void nextTick(fitIntoView) // at the click, not once the notes have loaded
})
onBeforeUnmount(() => {
  document.removeEventListener('keydown', onDetailKeydown)
  document.removeEventListener('pointerdown', onInlinePointerDown)
  stopScroll()
  leaveRoom(rootEl.value?.closest<HTMLElement>('.pattern-vertical-board__body') ?? null)
})

const rootEl = ref<HTMLElement | null>(null)
const editingBody = ref(false)
const bodyDraft = ref('')
const bodyInputEl = ref<HTMLElement | null>(null)
const bodyExpanded = ref(false)
const BODY_SAVE_DEBOUNCE_MS = 1_000
const bodySaveTimers = new Map<string, { timer: number; body: string }>()
let bodySessionStart = ''
let bodySessionId: string | null = null
let bodySessionPersisted = ''

/* Ten lines, then the rest behind "N more lines" (D210's preview, kept in round one: at 30 lines a goal's notes pushed
   its siblings off the screen). Notes up to five lines longer show in full: a fold that hides two lines saves nothing. */
const LINE_PX = 22
const PREVIEW_LINES = 10
const FOLD_AT_LEAST = 5
const PREVIEW_PX = LINE_PX * PREVIEW_LINES
const moreLines = ref(0)
const folded = computed(() => moreLines.value > 0 && !bodyExpanded.value && !editingBody.value)
const moreLabel = computed(() => `${moreLines.value} more ${moreLines.value === 1 ? 'line' : 'lines'}`)

// docs/COMMENTS_SPEC.md WP-B: selection-to-comment affordance, highlight repaint, and highlight
// click-through — shared with DocDetail.vue via this one composable (see its own header comment).
const anchoring = useCommentAnchoring({
  bodyEl: bodyInputEl,
  editing: editingBody,
  targetType: 'goal',
  targetId: () => goal.value?.id ?? null,
})

/** A paragraph that is one link to a document and nothing else is a document the agent linked. Such lines leave the
 *  notes for one line after them, "3 documents · latest 24 Sep", that opens the list (KK, 27 Sep 2026: "I wanted it
 *  to be a simple item like for mentioned docs, same here, different wording"); editing the notes shows them where they
 *  stand. A link inside a sentence stays a link. */
const linkedDocs = ref<Array<{ path: string; title: string }>>([])
function markDocumentLines(root: HTMLElement): void {
  const found: Array<{ path: string; title: string }> = []
  for (const block of root.children) {
    const link = block.tagName === 'P' && block.children.length === 1 ? block.firstElementChild : null
    const target = link instanceof HTMLAnchorElement ? internalLinkOf(link) : null
    const isDoc = target?.kind === 'doc' && block.textContent?.trim() === link?.textContent?.trim()
    block.classList.toggle('goal-detail__doc-line', isDoc)
    if (isDoc && target && !found.some((d) => d.path === target.target)) {
      found.push({ path: target.target, title: link?.textContent?.trim() || target.target })
    }
  }
  linkedDocs.value = found
}

function renderBody(root: HTMLElement, body: string): void {
  renderBodyElement(root, body)
  markDocumentLines(root)
}

function measureBodyLength(): void {
  void nextTick(() => {
    const el = bodyInputEl.value
    if (!el) return
    const extra = Math.round(el.scrollHeight / LINE_PX) - PREVIEW_LINES
    moreLines.value = extra >= FOLD_AT_LEAST ? extra : 0
    void nextTick(fitIntoView)
  })
}

function paintBody(body: string): void {
  void nextTick(() => {
    if (bodyInputEl.value && !editingBody.value) {
      renderBody(bodyInputEl.value, body)
      measureBodyLength()
      anchoring.paintHighlights()
    }
  })
}

function flushBodySave(id: string, keepalive = false): Promise<void> {
  const pending = bodySaveTimers.get(id)
  if (!pending) return Promise.resolve()
  window.clearTimeout(pending.timer)
  bodySaveTimers.delete(id)
  if (id === bodySessionId) bodySessionPersisted = pending.body
  return store.updateGoal(id, { body: pending.body }, keepalive)
}

function flushAllBodySaves(keepalive = false): Promise<void[]> {
  return Promise.all([...bodySaveTimers.keys()].map((id) => flushBodySave(id, keepalive)))
}

function onBodyVisibilityChange() {
  if (document.visibilityState === 'hidden') void flushAllBodySaves(true)
}

function onBodyPageHide() {
  void flushAllBodySaves(true)
}

const stopBeforeQuit = onBeforeQuit(() => flushAllBodySaves())

onMounted(() => {
  document.addEventListener('visibilitychange', onBodyVisibilityChange)
  window.addEventListener('pagehide', onBodyPageHide)
  window.addEventListener('resize', measureBodyLength)
})
onBeforeUnmount(() => {
  document.removeEventListener('visibilitychange', onBodyVisibilityChange)
  window.removeEventListener('pagehide', onBodyPageHide)
  window.removeEventListener('resize', measureBodyLength)
  stopBeforeQuit()
  void flushAllBodySaves()
})

// Follow the loaded record without replacing an active draft; goal switches close stale edits.
watch(
  () => goal.value?.id,
  (id, previousId) => {
    if (previousId && id !== previousId) void flushBodySave(previousId)
    editingBody.value = false
    moreLines.value = 0
    bodyExpanded.value = false
    openList.value = null
    fitted = false
    bodySessionId = null
    // docs/COMMENTS_SPEC.md WP-B: the facts line's open-comment count needs real data
    // regardless of whether the panel has ever been opened (`lib/comments.ts`'s own header
    // comment on this same call) — fetched the moment this goal's own detail loads, not gated
    // behind the panel. Closing on `id === undefined` covers both a real close and a host swap.
    if (id) void store.loadCommentsFor('goal', id)
    else store.closeCommentsPanel()
  },
)
watch(
  () => goal.value?.body,
  () => {
    if (!editingBody.value) {
      bodyDraft.value = goal.value?.body ?? ''
      paintBody(bodyDraft.value)
    }
  },
  { immediate: true },
)

function onBodyClick(event: MouseEvent) {
  // A highlighted anchor quote (docs/COMMENTS_SPEC.md WP-B) opens its thread instead of starting
  // an edit — checked first, same "carve-out before the general dispatch" shape the link check
  // right below already uses.
  if (anchoring.onBodyClick(event)) return
  const link = (event.target as HTMLElement).closest('a')
  // S-72: read-mode anchor clicks stay links and never enter edit mode.
  if (link && !editingBody.value) {
    const internal = internalLinkOf(link)
    if (internal) {
      event.preventDefault()
      void store.followBodyLink(internal)
    }
    return
  }
  if (link) event.preventDefault()
  // A click that just produced a comment-selection (`anchoring.onBodyMouseUp`, bound on `mouseup`,
  // already ran by the time `click` reaches here) is a drag-to-select gesture, not a
  // position-the-caret click — entering edit mode would yank the reader into typing mode the
  // instant they finish selecting a quote to comment on.
  if (!editingBody.value && !anchoring.pendingSelection.value) startBodyEdit()
}

function startBodyEdit() {
  if (!goal.value) return
  bodyDraft.value = goal.value.body
  bodySessionStart = goal.value.body
  bodySessionId = goal.value.id
  bodySessionPersisted = goal.value.body
  bodyExpanded.value = true
  editingBody.value = true
  anchoring.clearForEdit()
  void nextTick(() => {
    if (!bodyInputEl.value) return
    resetBodyHistory(bodyInputEl.value)
    bodyInputEl.value.focus({ preventScroll: true })
  })
}

function queueBodySave(id: string, body: string) {
  const pending = bodySaveTimers.get(id)
  if (pending) window.clearTimeout(pending.timer)
  const timer = window.setTimeout(() => flushBodySave(id), BODY_SAVE_DEBOUNCE_MS)
  bodySaveTimers.set(id, { timer, body })
}

function onBodyInput(event: InputEvent) {
  if (!goal.value || !bodyInputEl.value || !editingBody.value) return
  normalizeBodyInput(event)
  const body = serializeBodyElement(bodyInputEl.value)
  bodyDraft.value = body
  goal.value.body = body
  queueBodySave(goal.value.id, body)
}

function finishBodyEdit() {
  if (!editingBody.value) return
  // Navigation fires blur before pagehide. Keep this flush alive so pagehide cannot find an
  // already-consumed timer whose ordinary request is then aborted by the navigation.
  if (bodySessionId) flushBodySave(bodySessionId, true)
  if (bodyInputEl.value) renderBody(bodyInputEl.value, bodyDraft.value)
  editingBody.value = false
  bodySessionId = null
  measureBodyLength()
  anchoring.paintHighlights()
}

function cancelBodyEdit() {
  const cancelledId = bodySessionId
  if (bodySessionId) {
    const pending = bodySaveTimers.get(bodySessionId)
    if (pending) window.clearTimeout(pending.timer)
    bodySaveTimers.delete(bodySessionId)
  }
  if (goal.value?.id === bodySessionId) {
    goal.value.body = bodySessionStart
  }
  bodyDraft.value = bodySessionStart
  if (bodyInputEl.value) renderBody(bodyInputEl.value, bodySessionStart)
  editingBody.value = false
  bodySessionId = null
  measureBodyLength()
  anchoring.paintHighlights()
  // A debounce may already have reached storage. Escape reverts the entire session there too.
  if (cancelledId && bodySessionPersisted !== bodySessionStart) {
    void store.updateGoal(cancelledId, { body: bodySessionStart }, true)
  }
}

function onBodySurfaceKeydown(event: KeyboardEvent) {
  if (!editingBody.value) {
    if (event.key === 'Enter') {
      event.preventDefault()
      startBodyEdit()
    }
    return
  }
  if (event.key === 'Escape') {
    event.preventDefault()
    event.stopPropagation()
    cancelBodyEdit()
    return
  }
  handleBodyKeydown(event)
}

/* Two lines of documents after the notes, one look, each opening its list, newest first:
   - the goal's own, which the agent linked on lines of their own: "3 documents · latest 24 Sep", and after them the
     ones its parents link, greyed as D251's chips were, under "From" and the parent's name, nearest parent first (KK
     picked it on 29 Sep 2026: a step keeps its parents' documents in view; its own link to the same document wins);
   - the ones that mention the goal (their text links to it) and aren't in its notes: "Mentioned in 13 documents · latest
     24 Sep". They used to be pills, 21 on one goal. Two documents with one title show once, the newer: the 25 Sep
     migration left copies of some under `migration/`. */
type DocItem = { key: string; id?: string; title: string; updated: string | null; open: () => void; from?: string; fromId?: string }
const openList = ref<'documents' | 'mentions' | null>(null)
const newestFirst = (a: DocItem, b: DocItem) => (b.updated ?? '').localeCompare(a.updated ?? '')
const documents = computed<DocItem[]>(() => {
  // a document's own title: the link's words are the sentence's ("the review document")
  const known = new Map(store.state.docs.list.map((d) => [d.path, d]))
  const own = linkedDocs.value.map((d) => ({
    key: d.path,
    id: known.get(d.path)?.id,
    title: known.get(d.path)?.title || d.title,
    updated: known.get(d.path)?.updated_at ?? null,
    open: () => void store.followBodyLink({ kind: 'doc', target: d.path }),
  })).sort(newestFirst)
  const mine = new Set(own.map((d) => d.key))
  const ancestors = goal.value?.ancestors ?? []
  const nearness = new Map(ancestors.map((a, i) => [a.id, ancestors.length - i])) // 1 is the parent
  const parents = (goal.value?.docs ?? [])
    .filter((d) => d.source === 'goal' && d.inherited_from && !mine.has(d.path))
    .map((d) => ({
      key: d.path,
      id: d.id,
      title: d.title || known.get(d.path)?.title || d.path,
      updated: known.get(d.path)?.updated_at ?? null,
      open: () => store.openDocFromGoal(d.id),
      from: d.inherited_from?.title,
      fromId: d.inherited_from?.id,
    }))
    .sort((a, b) => ((nearness.get(a.fromId ?? '') ?? 99) - (nearness.get(b.fromId ?? '') ?? 99)) || newestFirst(a, b))
  return [...own, ...parents]
})
const mentions = computed<DocItem[]>(() => {
  const g = goal.value
  if (!g) return []
  const inNotes = new Set(g.docs.filter((d) => d.source === 'goal' && !d.inherited_from).map((d) => d.id))
  const seen = new Set<string>()
  const dated = new Map(store.state.docs.list.map((d) => [d.id, d.updated_at]))
  const all: DocItem[] = []
  for (const d of g.docs) {
    if (d.source !== 'doc' || d.inherited_from || inNotes.has(d.id)) continue
    all.push({ key: d.id, title: d.title || d.path, updated: dated.get(d.id) ?? null, open: () => store.openDocFromGoal(d.id) })
  }
  return all.sort(newestFirst).filter((d) => !seen.has(d.title) && seen.add(d.title))
})
/* The goal's own documents, its parents' after them, are rows of its links (S3.P1.007); the ones that mention it stay a
   line of their own. */
const links = computed(() => documents.value.map((d) => ({ key: d.id ?? d.key, path: d.key, title: d.title, updated: d.updated, open: d.open, from: d.from })))
const docLines = computed(() => [
  { role: 'goal-mentions', list: 'mentions' as const, docs: mentions.value, label: (n: number) => `Mentioned in ${n} ${n === 1 ? 'document' : 'documents'}` },
].filter((line) => line.docs.length).map((line) => ({
  ...line,
  latest: line.docs.reduce<string | null>((max, d) => (d.updated && (!max || d.updated > max) ? d.updated : max), null),
})))
watch(() => documents.value.length + mentions.value.length, (n) => {
  if (n && !store.state.docs.list.length && !store.state.docs.listLoading) void store.loadDocs()
}, { immediate: true })
function shortDate(iso: string | null): string {
  if (!iso) return ''
  const d = new Date(iso)
  return `${d.getDate()} ${MONTH_NAMES[d.getMonth()].slice(0, 3)}`
}

/* The opened goal is seen whole. If it fits where it was clicked, the column stays; otherwise it scrolls just enough,
   16 px from the window's edge or the board's bottom fade, and a goal taller than the window shows its top. A goal near
   the column's end gets room after the last card (`lib/columnRoom.ts`). The goal grows while it opens, so the target
   is read every frame until nothing moves; the glide takes 360-600 ms by distance. Once per opening; closing
   scrolls back (`lib/familyView.ts`); any wheel, key or press takes over. */
const GAP = 16
let fitted = false
let tween = 0
function stopScroll(): void {
  if (tween) cancelAnimationFrame(tween)
  tween = 0
  for (const type of ['wheel', 'pointerdown', 'keydown', 'touchstart']) window.removeEventListener(type, stopScroll, true)
}
/** Where `el` starts inside `scroller`'s content, as laid out: the lift's scale and rise don't count. */
function contentTop(el: HTMLElement, scroller: HTMLElement): number {
  let y = 0
  for (let e: HTMLElement | null = el; e && e !== scroller; e = e.offsetParent as HTMLElement | null) y += e.offsetTop
  return y
}
function fitIntoView(): void {
  if (fitted || tween) return
  if (store.state.drag.id !== null) { fitted = true; return } // flow 4: opened by a held drag, it stays under the hand
  const detail = rootEl.value
  // Flow 4: the family counts from its first line, so the levels stepped through stay in view above the card.
  let list = detail?.parentElement ?? null
  while (list?.parentElement?.closest('.goal-card__children')) list = list.parentElement.closest<HTMLElement>('.goal-card__children')
  const card = list?.previousElementSibling as HTMLElement | null
  let scroller = list?.parentElement ?? null
  while (scroller && !/auto|scroll/.test(getComputedStyle(scroller).overflowY)) scroller = scroller.parentElement
  if (!detail || !list || !card || !scroller) return
  fitted = true
  const el = scroller
  const open = list
  const body = el.querySelector<HTMLElement>(':scope > .pattern-vertical-board__body')
  const fade = document.querySelector<HTMLElement>('[data-role="board-bottom-fade"]')
  // Where the goal ends once open: its list and notes still grow from nothing (`lib/cardFamily.ts`'s growList).
  const bottom = (): number => {
    const clip = open.querySelector<HTMLElement>('.goal-detail-inline__clip')
    const notes = clip ? Math.max(0, clip.scrollHeight - clip.getBoundingClientRect().height) : 0
    return contentTop(open, el) + Math.max(open.offsetHeight, open.scrollHeight + notes)
  }
  const seen = (): number => Math.min(el.clientHeight, (fade?.getBoundingClientRect().top ?? window.innerHeight) - el.getBoundingClientRect().top)
  const target = (from: number): number => {
    // The column's top padding lies under the desktop title bar (App.vue): the goal stops below it.
    const top = contentTop(card, el) - GAP - (parseFloat(getComputedStyle(el).paddingTop) || 0)
    const to = Math.max(0, Math.min(top, Math.max(from, bottom() + GAP - seen())))
    if (body) roomFor(el, body, to)
    return to
  }
  // The glide starts from wherever the first frame finds the column: GoalCard.vue holds the clicked card in place first.
  // Without motion the column jumps at once, and keeps up with the goal while it grows.
  const reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches
  if (reduced) el.scrollTop = target(el.scrollTop)
  let from = reduced ? el.scrollTop : Number.NaN
  let ms = OPEN_MS
  let start = performance.now()
  let last = Number.NaN
  let still = 0
  const step = () => {
    // performance.now(), not the frame's time stamp: the opening's own work delays the first frame, and a stale stamp
    // made the glide think 80 ms had passed and jump 278 px
    const now = performance.now()
    if (Number.isNaN(from)) {
      from = el.scrollTop
      ms = Math.min(600, Math.max(OPEN_MS, 250 + 0.3 * Math.abs(target(from) - from)))
      start = now
    }
    const t = Math.min(1, (now - start) / ms)
    const to = target(from)
    el.scrollTop = reduced ? to : from + (to - from) * (1 - (1 - t) ** 3)
    still = Math.abs(to - last) < 0.5 ? still + 1 : 0
    last = to
    tween = t < 1 || (still < 3 && now - start < ms + 600) ? requestAnimationFrame(step) : 0
    if (!tween) stopScroll()
  }
  tween = requestAnimationFrame(step)
  for (const type of ['wheel', 'pointerdown', 'keydown', 'touchstart']) window.addEventListener(type, stopScroll, { capture: true, passive: true })
}
</script>

<template>
  <div
    id="goal-detail"
    ref="rootEl"
    class="goal-detail-root goal-detail-inline"
    data-state="open"
    data-role="inline-detail"
    aria-hidden="false"
  >
    <div class="goal-detail-inline__clip">
      <div class="goal-detail__drawer-plane">
        <div
          class="goal-detail-inline__dialog"
          role="group"
          :aria-label="goal?.title ?? 'Goal'"
          @click.stop
        >
          <div class="goal-detail__drawer-card">
            <p v-if="loading" class="goal-detail__loading t-caption t-muted">Loading…</p>
            <template v-else-if="goal">
              <GoalDetailEditor
                :id="goal.id"
                :title="goal.title"
                :done="goal.done_at !== null"
                :tags="goal.tags"
                :vertical="goal.vertical"
                :period-key="goal.period_key"
                :anchor-date="goal.anchor_date"
                :repeat="goal.repeat"
                :has-children="goal.children.length > 0"
                :inline="true"
              >
                <!-- `is-selectable`: the app's global `user-select: none` (style.css, owner
                     ruling 2026-08-09 — "restrict text selection except where you edit") would
                     otherwise block a read-mode drag-select entirely, and docs/COMMENTS_SPEC.md
                     WP-B needs exactly that to capture an anchor quote — `style.css`'s own
                     comment names this class as the documented opt-in for precisely this case
                     ("a future non-form surface that still needs to be copyable"). -->
                <div
                  ref="bodyInputEl"
                  class="goal-detail__body is-selectable"
                  :class="{ 'goal-detail__body--collapsed': folded }"
                  :style="{ '--goal-body-preview-height': `${PREVIEW_PX}px` }"
                  data-cap="edit-body"
                  data-placeholder="Notes"
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
                  @keydown="onBodySurfaceKeydown"
                  @paste="handleBodyPaste"
                  @blur="finishBodyEdit"
                  @mousedown="anchoring.onBodyMouseDown"
                  @mouseup="anchoring.onBodyMouseUp"
                ></div>
                <button
                  v-if="folded"
                  type="button"
                  class="goal-detail__body-more"
                  data-role="body-more"
                  @click="bodyExpanded = true"
                >{{ moreLabel }}</button>
                <!-- docs/COMMENTS_SPEC.md WP-B: selecting body text offers this, positioned at the
                     selection's own bounding box (`commentAnchoring.ts::onBodyMouseUp`). -->
                <button
                  v-if="anchoring.pendingSelection.value"
                  type="button"
                  class="goal-detail__comment-selection"
                  data-cap="comment-selection"
                  :style="{ left: `${anchoring.selectionButtonPos.value.x}px`, top: `${anchoring.selectionButtonPos.value.y}px` }"
                  @mousedown.prevent="anchoring.commitSelectionToComment"
                >Comment</button>
                <GoalLinks :goal-id="goal!.id" :goal-title="goal!.title" :body="goal!.body" :docs="links"
                  :in-window="store.state.openGoalVertical === 'window'" />
                <template v-for="line in docLines" :key="line.list">
                  <button
                    type="button"
                    class="goal-detail__mentions"
                    :data-role="line.role"
                    :aria-expanded="openList === line.list"
                    @click="openList = openList === line.list ? null : line.list"
                  ><b>{{ line.label(line.docs.length) }}</b><template v-if="line.latest"><span class="goal-detail__mentions-sep" aria-hidden="true">·</span>latest {{ shortDate(line.latest) }}</template></button>
                  <ul v-if="openList === line.list" class="goal-detail__mention-list" :data-role="`${line.role}-list`">
                    <template v-for="(doc, i) in line.docs" :key="doc.key">
                      <li v-if="doc.fromId && doc.fromId !== line.docs[i - 1]?.fromId" class="goal-detail__mention-from">From {{ doc.from }}</li>
                      <li>
                        <button
                          type="button"
                          :data-doc="doc.key"
                          :data-inherited="doc.fromId ? 'true' : undefined"
                          @click="doc.open()"
                        >
                          <span>{{ doc.title }}</span><span class="goal-detail__mention-date">{{ shortDate(doc.updated) }}</span>
                        </button>
                      </li>
                    </template>
                  </ul>
                </template>
              </GoalDetailEditor>
            </template>
            <p v-else class="goal-detail__loading t-caption t-muted">Could not load this goal.</p>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<!-- Presentation lives in ./goalDetail.css (unscoped global classes, same rules byte-for-byte)
     — extracted when this SFC crossed the 750-line module cap (ARCHITECTURE.md S-90a). -->
<style src="./goalDetail.css"></style>
