/* The open goal's own controls: the date that IS the schedule trigger, the
   hero title edited in place, and the quiet bottom row (comments, add subtask, repeat, tags). The body is GoalDetail's
   and comes in as `children`; `beforeBody` and `metaStart` are two more content slots. Inline (on the board) it draws
   only the slots. */
import { keyboardHelpOpen } from '../lib/keyboard'
import type { KeyboardEvent as ReactKeyboardEvent, ReactNode } from 'react'
import { computed, nextTick, ref, watch } from '../reactivity'
import { KCheckbox, KChip, KInlineAdd } from '../kit'
import { AppIcon } from './AppIcon'
import { PopoverEngine } from './PopoverEngine'
import { RepeatPopover } from './RepeatPopover'
import { store } from '../store'
import { MONTH_NAMES, periodLabel, type VerticalScale } from '../lib/periods'
import type { RepeatRule } from '../lib/api'
import { SchedulePopover } from './SchedulePopover'
import { fallthrough, valueOf } from '../bind'
import { tracked } from '../tracked'
import { listen, useSetup, withDefaults } from '../setup'
import './goalDetailEditor.css'

interface Props {
  id: string
  title: string
  done: boolean
  tags: string[]
  vertical: string | null
  periodKey: string | null
  anchorDate: string | null
  repeat: RepeatRule | null
  inline?: boolean
  onAddSubgoal?: () => void
  beforeBody?: ReactNode
  metaStart?: ReactNode
  children?: ReactNode
}
const DEFAULTS = { inline: false }

const SCHEDULE_LABELS: Record<VerticalScale, string> = {
  life: 'Life',
  decade: '3 years',
  year: 'Year',
  quarter: 'Quarter',
  month: 'Month',
  week: 'Week',
  day: 'Day',
}

export const GoalDetailEditor = tracked(function GoalDetailEditor(raw: Props & Record<string, unknown>) {
  const {
    id, title, done, tags, vertical, periodKey, anchorDate, repeat, inline, onAddSubgoal, beforeBody, metaStart, children,
    ...attrs
  } = withDefaults(raw, DEFAULTS)
  const s = useSetup({ id, title, done, tags, vertical, periodKey, anchorDate, repeat, inline, onAddSubgoal }, (props) => {
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

    // Life goals never recur, so they get no Repeat trigger.
    const repeatVertical = computed(() => (
      props.inline && props.vertical && props.vertical !== 'life' ? props.vertical : null
    ))

    function onSchedule(scale: VerticalScale, periodKey: string) {
      void store.scheduleGoalTo(props.id, scale, periodKey)
    }

    function onComplete(done: boolean) {
      void store.completeGoal(props.id, done)
    }

    // A tag is taken literally (the server neither strips nor case-folds it) and removed by exact match.
    function addTag(tag: string) {
      if (props.tags.includes(tag)) return
      void store.updateGoal(props.id, { tags: [...props.tags, tag] })
    }
    function removeTag(tag: string) {
      void store.updateGoal(props.id, { tags: props.tags.filter((t) => t !== tag) })
    }

    const editingTitle = ref(false)
    const titleDraft = ref(props.title)
    const titleInputEl = ref<HTMLTextAreaElement | null>(null)
    let titleCommitGuard = false

    // A textarea glued to its wrapped height, so the hero keeps its lines while it is edited.
    function autosizeTitle() {
      const el = titleInputEl.value
      if (!el) return
      el.style.height = '0'
      el.style.height = `${el.scrollHeight}px`
    }

    // The draft follows the record: another goal opened in this same editor, or a landed PATCH.
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

    // A click puts the caret where it landed; Enter (no point to aim at) selects the whole title.
    function startTitleEdit(event?: MouseEvent | KeyboardEvent) {
      titleCommitGuard = false
      titleDraft.value = props.title
      // A keyboard-synthesised click reports `detail` 0 and clientX/clientY 0.
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

    // At most once per edit: Enter hides the textarea, and its removal fires blur into here again.
    function commitTitle() {
      if (titleCommitGuard) return
      titleCommitGuard = true
      editingTitle.value = false
      const next = titleDraft.value.trim()
      if (next && next !== props.title) void store.updateGoal(props.id, { title: next })
      else titleDraft.value = props.title
    }
    listen(titleInputEl, 'blur', () => { if (!keyboardHelpOpen.value) commitTitle() })

    function cancelTitleEdit() {
      titleCommitGuard = true
      titleDraft.value = props.title
      editingTitle.value = false
    }

    return {
      commentCount, commentsOpenHere, onToggleComments, scheduleLabel, repeatVertical, onSchedule, onComplete, addTag,
      removeTag, editingTitle, titleDraft, titleInputEl, autosizeTitle, startTitleEdit, commitTitle, cancelTitleEdit,
    }
  })

  function onHeroKey(event: ReactKeyboardEvent<HTMLDivElement>) {
    if (event.key !== 'Enter') return
    event.preventDefault()
    s.startTitleEdit(event.nativeEvent)
  }
  // `.stop` on Escape keeps it from also closing the surface around (KModal listens on document).
  function onTitleInputKey(event: ReactKeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === 'Enter') {
      event.preventDefault()
      s.commitTitle()
    }
    if (event.key === 'Escape') {
      event.stopPropagation()
      s.cancelTitleEdit()
    }
  }

  return (
    <div {...fallthrough({ className: 'goal-detail__surface' }, attrs)}>
      {!inline ? (
        <header className="goal-detail__header">
          <div className="goal-detail__top">
            <SchedulePopover
              {...store.scheduleGrid.value.props}
              onSelect={s.onSchedule}
              onNavigate={store.navigateSchedule}
              onOpen={() => store.resetScheduleView()}
              trigger={({ open }) => (
                <button
                  type="button"
                  className="goal-detail__date t-caption t-muted"
                  data-cap="schedule"
                  aria-haspopup="menu"
                  aria-expanded={String(open) as 'true' | 'false'}
                >
                  {s.scheduleLabel.value}
                </button>
              )}
            />
          </div>
        </header>
      ) : null}

      <div className="modal__body goal-detail__editor">
        {!inline ? (
          <KCheckbox
            className="goal-detail__complete"
            data-role="detail-complete"
            size="xl"
            modelValue={done}
            onUpdate:modelValue={s.onComplete}
          />
        ) : null}

        {!inline && !s.editingTitle.value ? (
          <div
            className="goal-detail__hero t-hero"
            data-cap="edit-title"
            tabIndex={0}
            aria-label="Edit title"
            onClick={(event) => s.startTitleEdit(event.nativeEvent)}
            onKeyDown={onHeroKey}
          >{title}</div>
        ) : !inline ? (
          <textarea
            {...valueOf(s.titleDraft.value, (event) => {
              s.titleDraft.value = event.currentTarget.value
              s.autosizeTitle()
            }, s.titleInputEl)}
            className="goal-detail__hero goal-detail__hero-input t-hero"
            data-cap="edit-title"
            rows={1}
            onKeyDown={onTitleInputKey}
          />
        ) : null}

        {beforeBody}

        {children}

        {!inline ? <hr className="goal-detail__rule" /> : null}
        {!inline ? (
          <div className="goal-detail__meta">
            {metaStart}
            <div className="goal-detail__meta-controls">
              {inline ? (
                <SchedulePopover
                  {...store.scheduleGrid.value.props}
                  onSelect={s.onSchedule}
                  onNavigate={store.navigateSchedule}
                  onOpen={() => store.resetScheduleView()}
                  trigger={({ open }) => (
                    <button
                      type="button"
                      className="goal-detail__date goal-detail__date--inline t-caption t-muted"
                      data-cap="schedule"
                      aria-haspopup="menu"
                      aria-expanded={String(open) as 'true' | 'false'}
                    >
                      <span>{s.scheduleLabel.value}</span>
                      <AppIcon name="calendar" size={18} />
                    </button>
                  )}
                />
              ) : null}
              <button
                type="button"
                className="goal-detail__meta-trigger"
                data-cap="open-comments"
                aria-expanded={String(s.commentsOpenHere.value) as 'true' | 'false'}
                aria-label="Comments"
                onClick={s.onToggleComments}
              >
                <AppIcon name="comment" size={18} />
                {s.commentCount.value > 0 ? (
                  <span className="goal-detail__comments-badge" data-role="comments-badge">{s.commentCount.value}</span>
                ) : null}
              </button>
              {inline ? (
                <button
                  type="button"
                  className="goal-detail__meta-trigger"
                  data-cap="add-subgoal"
                  aria-label="Add subtask"
                  onClick={() => onAddSubgoal?.()}
                >
                  <AppIcon name="subtask" size={18} />
                </button>
              ) : null}
              {s.repeatVertical.value ? (
                <RepeatPopover compact id={id} vertical={s.repeatVertical.value} repeat={repeat} />
              ) : null}
              <PopoverEngine
                trigger={({ open }) => (
                  <button
                    type="button"
                    className="goal-detail__meta-trigger"
                    aria-haspopup="menu"
                    aria-expanded={String(open) as 'true' | 'false'}
                    aria-label="Tags"
                  >
                    <AppIcon name="tag" size={18} />
                  </button>
                )}
              >
                <div className="goal-detail__tags-panel" data-role="tag-chips">
                  {tags.length ? (
                    <div className="chip-wrap">
                      {tags.map((tag) => (
                        <KChip
                          key={tag}
                          data-cap="set-tags"
                          aria-label={`Remove ${tag}`}
                          onClick={() => s.removeTag(tag)}
                        >{tag} <AppIcon name="x" size={12} /></KChip>
                      ))}
                    </div>
                  ) : null}
                  <KInlineAdd data-cap="set-tags" placeholder="Add tag…" onAdd={s.addTag} />
                </div>
              </PopoverEngine>
            </div>
          </div>
        ) : null}
      </div>
    </div>
  )
})
