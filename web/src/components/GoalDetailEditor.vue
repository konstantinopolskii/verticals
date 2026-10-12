<script setup lang="ts">
/* The detail surface's own controls, redesigned end to end per `docs/GOAL_DETAIL_SPEC.md`
   (owner rulings, 2026-08-09 — "your task editing wysiwyg looks like a piece of shit"). The old
   shape was a settings form: a labelled bordered input per field, a mode toggle hiding the body.
   The spec's own words for the replacement: "no field labels anywhere on this surface", title as
   hero, metadata "collapses into one quiet icon row at the bottom", and the date "is a schedule
   popup" rather than a field next to one.

   This file now owns exactly three things, top to bottom on the surface: the date/schedule
   control (top-left, small, muted, IS the trigger — spec §2), the title (hero, click-to-edit
   in place), and the bottom icon row (schedule and tags; no assignee, share, attachment,
   colour, more, or priority controls). The body — rendered markdown, also click-to-edit in place — is deliberately
   NOT here: `GoalDetail.vue` already owns the IR-09 renderer S-72/S-73 are written against, so it
   also owns the body's edit surface, and hands it to this component's default slot to place
   between the hero and the meta row (`<slot />` below). That keeps the "two guarantees survive"
   rule (spec §4) inside the one file that already has to reason about it, rather than smearing
   body-editing state across two components the way the old `v-model:editing-body` did.

   Reads `store.updateGoal`/`store.scheduleGoalTo`/`scheduleGrid` directly, same convention this
   file used before the redesign — every value it edits still arrives as a prop, so the parent
   stays the single reader of `store.state.goalDetail`.

   Kit composition: `SchedulePopover` (reused verbatim, only its `#trigger` slot content changes —
   see note 2), `PopoverEngine` for the tags popover, `KChip`
   for a removable tag pill, `KInlineAdd` for the "type and Enter" add-a-tag control (its own
   built-in trim-and-clear-on-Enter behaviour is exactly what a one-tag-at-a-time input needs, and
   writing that by hand would just be a worse copy of it). Title's click-to-edit-in-place input
   is hand-rolled too — the kit's `KField` is a bordered, labelled
   field by construction (`field__label`, `field` box), which is the exact shape this redesign
   kills; there is no kit control for "an element that IS the rendered text until clicked, then
   becomes a borderless input of the same size in the same place" (the body gets the same
   treatment, in `GoalDetail.vue`, for the same reason).

   Two things worth flagging:

   1. **The commit-guard, not a `focusout`-on-a-wrapper trick.** Vue's own re-render, not a second
      user gesture, is what usually races a commit-on-blur handler here: `commitTitle` sets
      `editingTitle.value = false` (e.g. from Enter), which hides the input on the *next* render;
      removing a focused element from the DOM fires a real `blur` event at that point (confirmed
      live in Chromium, the engine Playwright drives), and that blur reaches the very same handler
      a second time. A plain `if (next === current) return` guard does not save this — the first
      call already changed `editingTitle`/`titleDraft` in a way the second call's comparison can
      race against, depending on whether the store's optimistic update has landed yet. A
      one-shot boolean (`titleCommitGuard`, reset only when a fresh edit starts) makes the commit
      idempotent regardless of how many of Enter/blur/Escape fire for one edit session, which is
      the actual property needed — not "commit once from the right event" but "commit at most
      once per session, from whichever event gets there first". `GoalDetail.vue`'s body editor
      uses the identical pattern, for the identical reason.

   2. **Schedule (KK ruling 2026-08-09, spec §2 "August 8 is a schedule popup").** Still the same
      integration as before the redesign — `SchedulePopover` reused verbatim, `data-cap="schedule"`
      on the one button a reader or a test can click, `store.scheduleGrid`/`scheduleGoalTo` the
      same two calls the board card used to make directly. What changed is presentation only: the
      trigger used to sit in a labelled `Schedule` field row; now it IS the date line, top-left,
      `t-caption t-muted` (small and muted per spec), with no field around it. For a `day`-scale
      goal it reads as a real date ("August 8", `MONTH_NAMES[m - 1] + ' ' + d`, string-sliced out
      of `anchor_date` — `periods.ts`'s own "reads, never derives" charter: no `Date` parsing, so
      no timezone-boundary bug from turning a date-only string into a `Date` and back) rather than
      "Day 8"; every other scale keeps the `<Scale> <period>` shape the old trigger already used. */
import { computed, nextTick, ref, watch } from 'vue'
import { KCheckbox, KChip, KInlineAdd } from '@konstantinopolskii/vue'
import AppIcon from './AppIcon.vue'
import PopoverEngine from './PopoverEngine.vue'
import RepeatPopover from './RepeatPopover.vue'
import { store } from '../store'
import { MONTH_NAMES, periodLabel, type VerticalScale } from '../lib/periods'
import type { RepeatRule } from '../lib/api'
import SchedulePopover from './SchedulePopover.vue'
import './goalDetailEditor.css'

const props = defineProps<{
  id: string
  title: string
  done: boolean
  tags: string[]
  /** `goal.vertical` off the wire — `null` for a card that sits only in Maybe (or a pure
   *  subgoal). Together with `periodKey`/`anchorDate`, this is the current-schedule label the
   *  trigger shows; none of the three is ever computed here, only read. */
  vertical: string | null
  /** `goal.period_key` off the wire — `null` exactly when `vertical` is `null`. */
  periodKey: string | null
  /** `goal.anchor_date` off the wire, `YYYY-MM-DD` or `null` — read for the `day`-scale label
   *  only (note 3 above); every other scale's label comes from `periodKey` alone. */
  anchorDate: string | null
  repeat: RepeatRule | null
  /** Board-hosted Things-style surface; schedule moves into the quiet footer row. */
  inline?: boolean
}>()

const emit = defineEmits<{
  addSubgoal: []
}>()

/** Mirrors `SchedulePopover.vue`'s own row order (life, decade, year, quarter, month, week, day)
 *  — a lookup table, not a switch, since every value is a plain noun with no branching of its
 *  own. Used for every scale except `day` (note 3: `day` gets a real date instead). */
const SCHEDULE_LABELS: Record<VerticalScale, string> = {
  life: 'Life',
  decade: '3 years',
  year: 'Year',
  quarter: 'Quarter',
  month: 'Month',
  week: 'Week',
  day: 'Day',
}

/* docs/COMMENTS_SPEC.md WP-B: "a comment icon 'in the line with the calendar' — the bottom icon
   row... Click opens a sidebar panel." Reads/writes `store.state.comments` directly, the same
   convention this file already uses for schedule/tags — the panel itself (`CommentsPanel.vue`) is
   mounted once at `App.vue`'s own level (WP-B2, D255: a viewport-docked overlay, not nested in
   this card), so this button only toggles shared state, same as `SchedulePopover`'s own trigger
   does for `store.scheduleGrid`. */
const commentCount = computed(() => store.unresolvedCommentCount('goal', props.id))
const commentsOpenHere = computed(() => {
  const c = store.state.comments
  return c.open && c.targetType === 'goal' && c.targetId === props.id
})
function onToggleComments() {
  if (commentsOpenHere.value) store.closeCommentsPanel()
  else store.openCommentsPanel('goal', props.id)
}

const scheduleLabel = computed(() => {
  if (!props.vertical || !props.periodKey) return 'Not scheduled'
  const scale = props.vertical as VerticalScale
  if (scale === 'life') return 'Life'
  if (scale === 'day' && props.anchorDate) {
    const [, month, day] = props.anchorDate.split('-')
    return `${MONTH_NAMES[Number(month) - 1]} ${Number(day)}`
  }
  return `${SCHEDULE_LABELS[scale] ?? scale} ${periodLabel(scale, props.periodKey)}`
})

/** The vertical the Repeat trigger works in, or `null` when there is no trigger. Life goals get
 *  none: they are for the whole life and never recur, the same rule `GoalCardTools.vue` applies
 *  to its own Repeat item. */
const repeatVertical = computed(() => (
  props.inline && props.vertical && props.vertical !== 'life' ? props.vertical : null
))

/** Same call the board card used to make directly before schedule moved into the detail surface. */
function onSchedule(scale: VerticalScale, periodKey: string) {
  void store.scheduleGoalTo(props.id, scale, periodKey)
}

function onComplete(done: boolean) {
  void store.completeGoal(props.id, done)
}

/** `core.goals._validate_tag` takes a tag literally — not stripped, not case-folded — so a tag is
 *  added exactly as `KInlineAdd` hands it (already trimmed by its own `onKeydown`, nothing more)
 *  and removed by exact string match. No draft, no comma-parsing: one gesture, one tag. */
function addTag(tag: string) {
  if (props.tags.includes(tag)) return
  void store.updateGoal(props.id, { tags: [...props.tags, tag] })
}
function removeTag(tag: string) {
  void store.updateGoal(props.id, { tags: props.tags.filter((t) => t !== tag) })
}

// --- title: hero, click-to-edit in place (spec §2) -------------------------------------------

const editingTitle = ref(false)
const titleDraft = ref(props.title)
const titleInputEl = ref<HTMLTextAreaElement | null>(null)
let titleCommitGuard = false

/** The edit control is a TEXTAREA sized to its content, not an `<input>` — owner-reported
 *  defect, 2026-08-09: "When I try to edit the headline of the task it supidly jumps to one
 *  line." The hero renders wrapped (`overflow-wrap: anywhere`, possibly three lines tall), and
 *  swapping it for a single-line input mid-click collapsed those lines into one scrolling row —
 *  the surface visibly jumped under the caret. A textarea keeps the wrapped shape; this keeps
 *  its height glued to the wrapped content (`scrollHeight` after zeroing, the standard autosize
 *  step — zeroing first so shrinking works too). Enter still commits (`.prevent` keeps the
 *  newline out: a title is one logical line however many visual ones it wraps to). */
function autosizeTitle() {
  const el = titleInputEl.value
  if (!el) return
  el.style.height = '0'
  el.style.height = `${el.scrollHeight}px`
}

// A draft follows the record, not the other way round: opening a second goal (a breadcrumb click
// re-uses this component rather than remounting it) and a landed PATCH both arrive here as a prop
// change, and a draft left holding the previous goal's text would be an edit box quietly pointed
// at the wrong row.
watch(
  () => [props.id, props.title],
  () => {
    if (!editingTitle.value) titleDraft.value = props.title
  },
)
watch(
  () => props.id,
  () => {
    editingTitle.value = false
  },
)

/** Character offset under a click, resolved against the element that was actually clicked.
 *  `caretPositionFromPoint` is the standards name, `caretRangeFromPoint` the WebKit/Blink one;
 *  neither is universal, so both are tried and a miss simply means "no opinion". */
function offsetAtPoint(clientX: number, clientY: number): number | null {
  const doc = document as Document & {
    caretPositionFromPoint?: (x: number, y: number) => { offsetNode: Node; offset: number } | null
    caretRangeFromPoint?: (x: number, y: number) => Range | null
  }
  const position = doc.caretPositionFromPoint?.(clientX, clientY)
  if (position) return position.offset
  const range = doc.caretRangeFromPoint?.(clientX, clientY)
  return range ? range.startOffset : null
}

/** Click-to-edit places the caret WHERE THE USER CLICKED. It used to `select()` the whole title,
 *  so aiming at one word armed a replace-everything edit and a stray keystroke wiped the goal's
 *  name (owner, 2026-08-10: "он весь выделяется вместо того чтобы поставить курсор ровно туда
 *  куда ты нажал"). Keyboard activation (Enter) has no point to aim at and keeps selecting all,
 *  which is the right default for a control reached without a pointer. */
function startTitleEdit(event?: MouseEvent | KeyboardEvent) {
  titleCommitGuard = false
  titleDraft.value = props.title
  // `detail > 0` is the real-pointer test: a keyboard-synthesised click reports 0 and carries
  // clientX/clientY of 0, which would otherwise plant the caret at character 0.
  const pointer = event && 'clientX' in event && event.detail > 0 ? event : null
  const caret = pointer ? offsetAtPoint(pointer.clientX, pointer.clientY) : null
  editingTitle.value = true
  void nextTick(() => {
    autosizeTitle()
    const el = titleInputEl.value
    if (!el) return
    el.focus()
    if (caret === null) el.select()
    else {
      const at = Math.min(caret, el.value.length)
      el.setSelectionRange(at, at)
    }
  })
}

/** See note 1 above — idempotent regardless of whether Enter, blur, or both fire for one edit. */
function commitTitle() {
  if (titleCommitGuard) return
  titleCommitGuard = true
  editingTitle.value = false
  const next = titleDraft.value.trim()
  // `core.goals.update` refuses an empty title (1..250 after strip) — refusing it here as well
  // keeps a cleared field from becoming a toast.
  if (next && next !== props.title) void store.updateGoal(props.id, { title: next })
  else titleDraft.value = props.title
}

/** Escape reverts and sends nothing (spec §2, verbatim) — `.stop` keeps this Escape from also
 *  reaching `KModal`'s own document-level listener and closing the whole surface on top of it;
 *  a second, unmodified Escape (nothing left editing) still closes the surface as normal. */
function cancelTitleEdit() {
  titleCommitGuard = true
  titleDraft.value = props.title
  editingTitle.value = false
}
</script>

<template>
  <div class="goal-detail__surface">
    <!-- Top-left, small, muted, and IS the schedule control (spec §2: "August 8 is a schedule
         popup") — no other schedule trigger exists on this surface. -->
    <header v-if="!props.inline" class="goal-detail__header">
      <div class="goal-detail__top">
        <SchedulePopover
          v-bind="store.scheduleGrid.value.props"
          @select="onSchedule"
          @navigate="store.navigateSchedule"
          @open="store.resetScheduleView()"
        >
          <template #trigger="{ open }">
            <button
              type="button"
              class="goal-detail__date t-caption t-muted"
              data-cap="schedule"
              aria-haspopup="menu"
              :aria-expanded="open"
            >
              {{ scheduleLabel }}
            </button>
          </template>
        </SchedulePopover>
      </div>
    </header>

    <div class="modal__body goal-detail__editor">
      <KCheckbox
        v-if="!props.inline"
        class="goal-detail__complete"
        data-role="detail-complete"
        size="xl"
        :model-value="done"
        @update:model-value="onComplete"
      />

      <!-- Hero title — large, bold, no border, no box, click and type in place. -->
      <div
        v-if="!props.inline && !editingTitle"
        class="goal-detail__hero t-hero"
        data-cap="edit-title"
        tabindex="0"
        aria-label="Edit title"
        @click="startTitleEdit"
        @keydown.enter.prevent="startTitleEdit"
      >{{ props.title }}</div>
      <!-- Textarea, not input — see `autosizeTitle`'s doc comment (the single-line jump). -->
      <textarea
        v-else-if="!props.inline"
        ref="titleInputEl"
        class="goal-detail__hero goal-detail__hero-input t-hero"
        data-cap="edit-title"
        rows="1"
        :value="titleDraft"
        @input="titleDraft = ($event.target as HTMLTextAreaElement).value; autosizeTitle()"
        @keydown.enter.prevent="commitTitle"
        @keydown.esc.stop="cancelTitleEdit"
        @blur="commitTitle"
      />

      <!-- Same-vertical linked rows can sit between the hero and body. The default slot remains the
           body plus cross-vertical groups, so legacy/global detail keeps its existing order. -->
      <slot name="before-body" />

      <!-- The body (rendered markdown / click-to-edit textarea) lands here — owned and supplied by
           `GoalDetail.vue` (this file's own header note). -->
      <slot />

      <!-- Metadata: quiet schedule and tags row; the legacy modal keeps its divider, while the
           inline card pins this compact pair to the bottom-right without one. -->
      <hr v-if="!props.inline" class="goal-detail__rule" />
      <!-- The inline card has no icon row (KK, 27 Sep 2026, the cleaned-up card): its date, size, comments and the
           agent are its facts line (GoalFacts.vue), a step is added at the end of its steps, tags and repeat are in
           its "…" menu. -->
      <div v-if="!props.inline" class="goal-detail__meta">
      <slot name="meta-start" />
      <div class="goal-detail__meta-controls">
      <SchedulePopover
        v-if="props.inline"
        v-bind="store.scheduleGrid.value.props"
        @select="onSchedule"
        @navigate="store.navigateSchedule"
        @open="store.resetScheduleView()"
      >
        <template #trigger="{ open }">
          <button
            type="button"
            class="goal-detail__date goal-detail__date--inline t-caption t-muted"
            data-cap="schedule"
            aria-haspopup="menu"
            :aria-expanded="open"
          >
            <span>{{ scheduleLabel }}</span>
            <AppIcon name="calendar" :size="18" />
          </button>
        </template>
      </SchedulePopover>
      <button
        type="button"
        class="goal-detail__meta-trigger"
        data-cap="open-comments"
        :aria-expanded="commentsOpenHere"
        aria-label="Comments"
        @click="onToggleComments"
      >
        <AppIcon name="comment" :size="18" />
        <span v-if="commentCount > 0" class="goal-detail__comments-badge" data-role="comments-badge">{{ commentCount }}</span>
      </button>
      <button
        v-if="props.inline"
        type="button"
        class="goal-detail__meta-trigger"
        data-cap="add-subgoal"
        aria-label="Add subtask"
        @click="emit('addSubgoal')"
      >
        <AppIcon name="subtask" :size="18" />
      </button>
      <RepeatPopover
        v-if="repeatVertical"
        compact
        :id="props.id"
        :vertical="repeatVertical"
        :repeat="props.repeat"
      />
      <PopoverEngine>
        <template #trigger="{ open }">
          <button
            type="button"
            class="goal-detail__meta-trigger"
            aria-haspopup="menu"
            :aria-expanded="open"
            aria-label="Tags"
          >
            <AppIcon name="tag" :size="18" />
          </button>
        </template>
        <div class="goal-detail__tags-panel" data-role="tag-chips">
          <div v-if="props.tags.length" class="chip-wrap">
            <KChip
              v-for="tag in props.tags"
              :key="tag"
              data-cap="set-tags"
              :aria-label="`Remove ${tag}`"
              @click="removeTag(tag)"
            >{{ tag }} <AppIcon name="x" :size="12" /></KChip>
          </div>
          <KInlineAdd data-cap="set-tags" placeholder="Add tag…" @add="addTag" />
        </div>
      </PopoverEngine>
      </div>
      </div>
    </div>
  </div>
</template>
