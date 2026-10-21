/* A goal card's dots and the menu under them: the agent's work, when, where, tags of
   the open goal, and Delete, each group under a small grey word; Date and Into a goal take the menu's place as a step.
   One place for the menu: it hangs below the dots, starting at them, and goes above only when there's no room below. */
import type { MouseEvent as ReactMouseEvent, ReactNode, Ref as ReactRef } from 'react'
import { AppIcon } from './AppIcon'
import { computed, ref, type Ref } from '../reactivity'
import { KChip, KInlineAdd } from '../kit'
import type { VerticalScale } from '../lib/periods'
import { isoDate, localDate, periodKeyFor } from '../lib/schedule'
import { playSound } from '../lib/sound'
import { store, todayIso } from '../store'
import { agentChat as agentChatState } from '../lib/agentChat'
import { PopoverEngine, type PopoverTriggerSlot } from './PopoverEngine'
import { RepeatPopover } from './RepeatPopover'
import { OpenInMenu } from './OpenInMenu'
import { MoveStep, type MoveStepName } from './MoveStep'
import type { RepeatRule } from '../lib/api'
import { bindRef, fallthrough } from '../bind'
import { tracked } from '../tracked'
import { exposeTo, useSetup } from '../setup'
import './goalCardTools.css'

export interface GoalCardToolsApi {
  openMenu(): void
}

interface Props {
  id: string
  vertical?: string | null
  repeat?: RepeatRule | null
  /** The card is the open goal: the menu keeps only what the card doesn't show. */
  open?: boolean
  onOpenChange?: (open: boolean) => void
  expose?: Ref<GoalCardToolsApi | null>
  ref?: ReactRef<HTMLDivElement>
  className?: string
}

const MENU_ATTRS = { 'data-role': 'goal-context-menu' }
const TAGS_ATTRS = { 'data-role': 'tag-chips' }

export const GoalCardTools = tracked(function GoalCardTools(raw: Props & Record<string, unknown>) {
  const { id, vertical, repeat, open, onOpenChange, expose, ...attrs } = raw
  const s = useSetup({ id, vertical, repeat, open, onOpenChange, expose }, (props) => {
    const trigger = ref<HTMLButtonElement | null>(null)
    const open = ref(false)
    /* The Agent section, only where an agent exists; the open card's facts line offers Discuss already. */
    const showAgent = computed(() => agentChatState.available)
    function discuss() {
      window.dispatchEvent(new CustomEvent('verticals:discuss-goal', { detail: { id: props.id } }))
      closeMenu()
    }
    function startWork() {
      window.dispatchEvent(new CustomEvent('verticals:start-work', { detail: { id: props.id } }))
      closeMenu()
    }
    const repeatVertical = computed(() => (props.vertical && props.vertical !== 'life' ? props.vertical : null))
    /* Every goal has the same menu. A step under a parent of its own column had no Reschedule or Move here (D179), as a
       step taken off the board then showed nowhere; a step's date now decides where it shows, and one with no date lives
       inside its parent (docs/design/checklist-steps.md), so it is rescheduled, moved and taken to the Inbox like any goal. */
    function onOpen() {
      open.value = true
      props.onOpenChange?.(true)
    }

    function onClose() {
      open.value = false
      step.value = null
      props.onOpenChange?.(false)
    }

    function openMenu() {
      if (!open.value) trigger.value?.click()
    }

    function closeMenu() {
      if (open.value) trigger.value?.click()
    }

    /* Tomorrow and Next week move the goal at once; Date and Into a goal open a step in place. */
    const step = ref<MoveStepName | null>(null)
    function day(offset: number): Date {
      const t = localDate(todayIso())
      return new Date(t.getFullYear(), t.getMonth(), t.getDate() + offset)
    }
    const tomorrow = computed(() => day(1))
    const nextWeek = computed(() => { const t = day(0); return day(7 - ((t.getDay() + 6) % 7)) })
    function moveToInbox() {
      void store.moveGoalToInbox(props.id)
      closeMenu()
    }
    function moveTo(scale: VerticalScale, date: Date) {
      void store.scheduleGoalQuick(props.id, scale, periodKeyFor(scale, date), isoDate(date))
      closeMenu()
    }

    /* Tags are the open goal's, read off its loaded detail. */
    const tags = computed(() => (store.state.goalDetail?.id === props.id ? store.state.goalDetail.tags : []))
    function addTag(tag: string) {
      if (tags.value.includes(tag)) return
      void store.updateGoal(props.id, { tags: [...tags.value, tag] })
    }
    function removeTag(tag: string) {
      void store.updateGoal(props.id, { tags: tags.value.filter((t) => t !== tag) })
    }

    function remove() {
      playSound('goal_deleted')
      void store.removeGoal(props.id)
    }

    exposeTo(props.expose, { openMenu })
    return {
      trigger, open, showAgent, discuss, startWork, repeatVertical, onOpen, onClose,
      closeMenu, step, tomorrow, nextWeek, moveToInbox, moveTo, tags, addTag, removeTag, remove,
    }
  })

  const toStep = (name: MoveStepName) => (event: ReactMouseEvent) => {
    event.stopPropagation()
    s.step.value = name
  }
  const arrow = <span data-role="submenu-arrow" aria-hidden="true"><AppIcon name="chevron-right" size={14} /></span>

  // The engine draws the menu only while it is open, so a closed card reads none of it: built here only then.
  function menu(): ReactNode {
    if (s.step.value) return <MoveStep id={id} step={s.step.value} onGo={(next) => (s.step.value = next)} onDone={s.closeMenu} />
    const repeatVertical = s.repeatVertical.value
    const tags = s.tags.value
    return (
      <div className="goal-actions__content" data-role="goal-actions-menu">
        {s.showAgent.value ? (
          <div className="goal-actions__section" data-menu-section="agent" role="group" aria-label="Agent">
            <p className="goal-actions__heading" aria-hidden="true">Agent</p>
            {!open ? (
              <button type="button" role="menuitem" className="dropdown__item goal-actions__item" data-menu-item="discuss"
                onClick={s.discuss}>Discuss</button>
            ) : null}
            <button type="button" role="menuitem" className="dropdown__item goal-actions__item" data-menu-item="start-work"
              onClick={s.startWork}>Start work</button>
            <OpenInMenu id={id} onDone={s.closeMenu} />
          </div>
        ) : null}

        <div className="goal-actions__section" data-menu-section="reschedule" role="group" aria-label="Reschedule">
          <p className="goal-actions__heading" aria-hidden="true">Reschedule</p>
          <button type="button" role="menuitem" className="dropdown__item goal-actions__item" data-move="tomorrow" data-cap="schedule"
            onClick={() => s.moveTo('day', s.tomorrow.value)}>Tomorrow</button>
          <button type="button" role="menuitem" className="dropdown__item goal-actions__item" data-move="next-week"
            onClick={() => s.moveTo('week', s.nextWeek.value)}>Next week</button>
          <button type="button" role="menuitem" className="dropdown__item goal-actions__item" data-move="date" onClick={toStep('date')}>
            <span>Date</span>{arrow}
          </button>
          {repeatVertical ? <RepeatPopover id={id} vertical={repeatVertical} repeat={repeat ?? null} /> : null}
        </div>

        <div className="goal-actions__section" data-menu-section="move" role="group" aria-label="Move">
          <p className="goal-actions__heading" aria-hidden="true">Move</p>
          <button type="button" role="menuitem" className="dropdown__item goal-actions__item" data-move="under" onClick={toStep('under')}>
            <span>Into a goal</span>{arrow}
          </button>
          {vertical ? (
            <button type="button" role="menuitem" className="dropdown__item goal-actions__item" data-move="inbox" data-action="inbox"
              onClick={s.moveToInbox}>To Inbox</button>
          ) : null}
        </div>

        {open ? (
          <div className="goal-actions__section" data-menu-section="tags">
            <PopoverEngine
              nested
              data-action="tags"
              surfaceClass="goal-actions__submenu goal-actions__tags"
              surfaceAttrs={TAGS_ATTRS}
              trigger={(
                <button type="button" role="menuitem" className="dropdown__item goal-actions__item">
                  <span>Tags…</span>
                  {arrow}
                </button>
              )}
            >
              <div className="goal-actions__tags-panel">
                {tags.length ? (
                  <div className="chip-wrap">
                    {tags.map((tag) => (
                      <KChip key={tag} data-cap="set-tags" aria-label={`Remove ${tag}`} onClick={() => s.removeTag(tag)}>
                        {`${tag} `}<AppIcon name="x" size={12} />
                      </KChip>
                    ))}
                  </div>
                ) : null}
                <KInlineAdd data-cap="set-tags" placeholder="Add tag…" onAdd={s.addTag} />
              </div>
            </PopoverEngine>
          </div>
        ) : null}

        <div className="goal-actions__section" data-menu-section="delete">
          <button type="button" role="menuitem" className="dropdown__item goal-actions__item goal-actions__item--danger" data-action="delete"
            data-cap="delete" onClick={s.remove}>
            <AppIcon name="trash" data-icon="trash" />
            <span>Delete</span>
          </button>
        </div>
      </div>
    )
  }

  return (
    <PopoverEngine
      {...fallthrough({ className: 'goal-card__tools' }, attrs)}
      placement="bottom-start"
      surfaceClass="goal-actions__menu"
      surfaceAttrs={MENU_ATTRS}
      onOpen={s.onOpen}
      onClose={s.onClose}
      trigger={({ open: engineOpen }: PopoverTriggerSlot) => (
        <button
          ref={bindRef(s.trigger)}
          type="button"
          className="goal-actions__trigger"
          data-role="goal-actions-trigger"
          data-cap="reparent"
          aria-label="Goal actions"
          aria-haspopup="menu"
          aria-expanded={engineOpen}
        >
          <AppIcon name="dots" data-cap="delete" size={24} />
        </button>
      )}
    >
      {s.open.value ? menu() : null}
    </PopoverEngine>
  )
})
