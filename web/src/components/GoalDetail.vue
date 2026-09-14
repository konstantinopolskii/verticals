<script setup lang="ts">
/* D248 WP-C: the modal/drawer surface is gone. This component renders ONLY the board-hosted
   inline detail (`goal-detail-inline`) — GoalCard.vue mounts/unmounts it per card
   (`v-if="isInlineDetailHost"`), so there is no cross-goal lifecycle to manage here beyond the
   inline open/close animation and body edit/save flow below. P-28 keeps one safe rendered DOM in
   read/edit states, with optimistic local state and debounced Markdown PATCHes. */
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { KChip } from '@konstantinopolskii/vue'
import GoalDetailEditor from './GoalDetailEditor.vue'
import SubgoalAddRow from './SubgoalAddRow.vue'
import ShotSizeFields from '../kit-ext/shot-size-fields/ShotSizeFields.vue'
import { store } from '../store'
import { renderBodyElement, serializeBodyElement } from '../lib/bodyMarkdown'
import { useCommentAnchoring } from '../lib/commentAnchoring'
import {
  handleBodyBeforeInput,
  handleBodyKeydown,
  handleBodyPaste,
  normalizeBodyInput,
  resetBodyHistory,
} from '../lib/bodyTextarea'

const goal = computed(() => store.state.goalDetail)
const loading = computed(() => store.state.goalDetailLoading)
const closing = ref(false)
const surfaceVisible = computed(() => store.state.openGoalId !== null || closing.value)
const surfaceState = computed(() => closing.value ? 'closed' : 'open')
let closeTimer: number | null = null

const INLINE_CLOSE_MS = 360

function requestClose() {
  if (closing.value || store.state.openGoalId === null) return
  closing.value = true
  closeTimer = window.setTimeout(() => {
    closeTimer = null
    store.closeGoal()
    closing.value = false
  }, window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 0 : INLINE_CLOSE_MS)
}

function onDetailKeydown(event: KeyboardEvent) {
  if (store.state.openGoalId === null || closing.value) return
  const hosted = document.querySelector<HTMLElement>(
    '#dropdownPortal [data-popover-surface][data-state="open"]',
  )
  if (event.key === 'Escape') {
    if (hosted) return
    event.preventDefault()
    requestClose()
  }
}

function onInlinePointerDown(event: PointerEvent) {
  if (closing.value || store.state.openGoalId === null) return
  const target = event.target as HTMLElement | null
  if (!target) return
  // WP-B2: the comments panel now docks to the viewport edge, mounted at `App.vue`'s own level
  // (`CommentsPanel.vue`'s header comment) — no longer a descendant of `[data-goal-id]`. Without
  // this, writing a reply or clicking Resolve inside the panel would register as a pointerdown
  // OUTSIDE the card and collapse it mid-write.
  if (target.closest('#goal-detail, #dropdownPortal, [data-goal-id], [data-role="comments-panel"]')) return
  requestClose()
}

onMounted(() => {
  document.addEventListener('keydown', onDetailKeydown)
  document.addEventListener('pointerdown', onInlinePointerDown)
})
onBeforeUnmount(() => {
  if (closeTimer !== null) window.clearTimeout(closeTimer)
  document.removeEventListener('keydown', onDetailKeydown)
  document.removeEventListener('pointerdown', onInlinePointerDown)
})

const editingBody = ref(false)
const bodyDraft = ref('')
const bodyInputEl = ref<HTMLElement | null>(null)
const bodyIsLong = ref(false)
const bodyExpanded = ref(false)
const INLINE_BODY_PREVIEW_HEIGHT = 220
const BODY_SAVE_DEBOUNCE_MS = 1_000
const bodySaveTimers = new Map<string, { timer: number; body: string }>()
let bodySessionStart = ''
let bodySessionId: string | null = null
let bodySessionPersisted = ''

// docs/COMMENTS_SPEC.md WP-B: selection-to-comment affordance, highlight repaint, and highlight
// click-through — shared with DocDetail.vue via this one composable (see its own header comment).
const anchoring = useCommentAnchoring({
  bodyEl: bodyInputEl,
  editing: editingBody,
  targetType: 'goal',
  targetId: () => goal.value?.id ?? null,
})

function measureBodyLength(): void {
  void nextTick(() => {
    bodyIsLong.value = Boolean(
      bodyInputEl.value
      && bodyInputEl.value.scrollHeight > INLINE_BODY_PREVIEW_HEIGHT,
    )
  })
}

function paintBody(body: string): void {
  void nextTick(() => {
    if (bodyInputEl.value && !editingBody.value) {
      renderBodyElement(bodyInputEl.value, body)
      measureBodyLength()
      anchoring.paintHighlights()
    }
  })
}

function flushBodySave(id: string, keepalive = false) {
  const pending = bodySaveTimers.get(id)
  if (!pending) return
  window.clearTimeout(pending.timer)
  bodySaveTimers.delete(id)
  if (id === bodySessionId) bodySessionPersisted = pending.body
  void store.updateGoal(id, { body: pending.body }, keepalive)
}

function flushAllBodySaves(keepalive = false) {
  for (const id of [...bodySaveTimers.keys()]) flushBodySave(id, keepalive)
}

function onBodyVisibilityChange() {
  if (document.visibilityState === 'hidden') flushAllBodySaves(true)
}

function onBodyPageHide() {
  flushAllBodySaves(true)
}

onMounted(() => {
  document.addEventListener('visibilitychange', onBodyVisibilityChange)
  window.addEventListener('pagehide', onBodyPageHide)
  window.addEventListener('resize', measureBodyLength)
})
onBeforeUnmount(() => {
  document.removeEventListener('visibilitychange', onBodyVisibilityChange)
  window.removeEventListener('pagehide', onBodyPageHide)
  window.removeEventListener('resize', measureBodyLength)
  flushAllBodySaves()
})

// Follow the loaded record without replacing an active draft; goal switches close stale edits.
watch(
  () => goal.value?.id,
  (id, previousId) => {
    if (previousId && id !== previousId) flushBodySave(previousId)
    editingBody.value = false
    bodyIsLong.value = false
    bodyExpanded.value = false
    bodySessionId = null
    // docs/COMMENTS_SPEC.md WP-B: the icon's own "open-thread count" badge needs real data
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
  if (link && !editingBody.value) return
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
  if (bodyInputEl.value) renderBodyElement(bodyInputEl.value, bodyDraft.value)
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
  if (bodyInputEl.value) renderBodyElement(bodyInputEl.value, bodySessionStart)
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

// Existing detail children support render/toggle/add. Enter commits add; blur abandons it.

const detailAdd = ref<{ openEditor: () => void } | null>(null)

function onSubgoalAdd(title: string) {
  void store.addDetailChild(title)
}

function openSubgoalAdd() {
  detailAdd.value?.openEditor()
}
</script>

<template>
  <div
    v-if="surfaceVisible"
    id="goal-detail"
    class="goal-detail-root goal-detail-inline"
    :data-state="surfaceState"
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
                @add-subgoal="openSubgoalAdd"
              >
                <template #before-body>
                  <SubgoalAddRow
                    ref="detailAdd"
                    :show-trigger="false"
                    commit-on-enter
                    @commit="onSubgoalAdd"
                  />
                </template>
                <template #meta-start>
                  <ShotSizeFields
                    v-if="goal.vertical === 'week' || goal.vertical === 'day'"
                    :expected="goal.size_expected"
                    :actual="goal.size_actual"
                    @change-expected="(value) => goal && store.updateGoal(goal.id, { size_expected: value })"
                  />
                </template>
                <!-- `is-selectable`: the app's global `user-select: none` (style.css, owner
                     ruling 2026-08-09 — "restrict text selection except where you edit") would
                     otherwise block a read-mode drag-select entirely, and docs/COMMENTS_SPEC.md
                     WP-B needs exactly that to capture an anchor quote — `style.css`'s own
                     comment names this class as the documented opt-in for precisely this case
                     ("a future non-form surface that still needs to be copyable"). -->
                <div
                  ref="bodyInputEl"
                  class="goal-detail__body is-selectable"
                  :class="{
                    'goal-detail__body--collapsed': bodyIsLong && !bodyExpanded && !editingBody,
                  }"
                  :style="{ '--goal-body-preview-height': `${INLINE_BODY_PREVIEW_HEIGHT}px` }"
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
                  v-if="bodyIsLong && !bodyExpanded && !editingBody"
                  type="button"
                  class="goal-detail__body-see-all"
                  @click="bodyExpanded = true"
                >See all</button>
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
                <!-- D250 WP-3 / D251: linked docs (`schemas.py::goal_to_detail`'s `docs` field) —
                     click navigates to the Docs view and opens the target, the goal-side mirror
                     of `DocDetail.vue`'s own linked-goal chips. D251: `goal.docs` already sorts
                     own entries before inherited ones (own wins the dedupe on the server side),
                     so this loop draws them in server order with no re-sort — inherited docs
                     (`doc.inherited_from` set) render "ghosted": one muted-colour cue
                     (`goal-doc-chip--inherited` in ./goalDetail.css, the same reduced-emphasis
                     move `kit-ext/carryover-ghost` uses elsewhere), attribution on the native
                     `title` tooltip rather than a second visible cue, click behaves identically
                     to an own chip. -->
                <div v-if="goal.docs.length" class="chip-wrap goal-detail__docs" data-role="goal-doc-chips">
                  <KChip
                    v-for="doc in goal.docs"
                    :key="doc.id"
                    data-role="goal-doc-chip"
                    :data-doc-id="doc.id"
                    :data-inherited="doc.inherited_from ? 'true' : undefined"
                    :class="{ 'goal-doc-chip--inherited': doc.inherited_from }"
                    :title="doc.inherited_from ? `via ${doc.inherited_from.title}` : undefined"
                    @click="store.openDocFromGoal(doc.id)"
                  >{{ doc.title || doc.path }}</KChip>
                </div>
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
