/* A board column: the period bars on the line pinned at its top (the dots while a goal is
   dragged), the period track whose slides swap when the board pages, and in each slide the line, the header, the
   carried plans, the cards with the drag's slot spliced in, "Add…" and, while you type, the other periods' matches. */
import { computed, nextTick, onBeforeUnmount, reactive, ref, watch } from '../reactivity'
import { KCardStack } from '../kit'
import { ColumnBars } from './ColumnBars'
import { ColumnHeader } from './ColumnHeader'
import { ColumnLine } from './ColumnLine'
import { GoalCard } from './GoalCard'
import { InlineAdd } from './InlineAdd'
import { FindingSections } from './FindingSections'
import { CarriedGroup } from './CarriedGroup'
import { ColumnDots } from './ColumnDots'
import type { SpanScale } from '../lib/spans'
import { store } from '../store'
import { playSound } from '../lib/sound'
import { kindOf, kindTail, pluralOf } from '../lib/columnNames'
import type { PeriodDirection } from '../lib/periodNavigation'
import type { GoalCardData, NameForm } from '../types'
import { filterActive } from '../lib/commandFilter'
import { reducedMotion } from '../lib/motion'
import { bindRef, cx, fallthrough, sx } from '../bind'
import { tracked } from '../tracked'
import { listen, useSetup, withDefaults } from '../setup'
import './column.css'

interface Props {
  vertical: string
  /** The column's name, its period, in full. */
  title: string
  /** The kind, small above the name. */
  subLabel?: string
  /** The name in shorter forms, longest first: its header shows the first that fits. */
  shorter?: NameForm[]
  /** The accessible name: the full name with full years, whichever form is on screen. */
  label?: string
  active?: boolean
  deckActive?: boolean
  deckMain?: boolean
  addPlaceholder?: string
  goals: GoalCardData[]
  periodKey?: string | null
  periodDirection?: PeriodDirection
  periodSwapId?: number
  /** One period of the spans while a goal moves: its header names how far away it is. */
  span?: boolean
  /** The span's end, small and light after its date. */
  end?: string
  /** The wide column that floats over the spans: it doesn't page, so it has neither the period bars nor the line. */
  floating?: boolean
  /** The board is paged away from today and this column's period no longer holds it. */
  away?: boolean
  onPeriodStep?: (vertical: string, direction: PeriodDirection) => void
  /** The single bar of a column that is away from today: the board goes back to it. */
  onPeriodToday?: () => void
  /** The middle bar of a column that holds today: this column's spans. */
  onPeriodMode?: (vertical: string, periodKey: string | null) => void
}
const DEFAULTS = {
  subLabel: '', shorter: [] as NameForm[], label: '', active: false, deckActive: false, deckMain: false, addPlaceholder: 'Add…',
  periodKey: null, periodDirection: 1 as PeriodDirection, periodSwapId: 0, span: false, end: '', floating: false, away: false,
}

type RenderItem =
  | { kind: 'goal'; key: string; goal: GoalCardData }
  | { kind: 'slot'; key: '__dnd-placeholder__' | '__dnd-destination__'; settling: boolean }

type SlideState = 'outgoing' | 'incoming' | 'current'
interface PeriodSlide {
  id: number
  title: string
  subLabel: string
  shorter: NameForm[]
  goals: GoalCardData[]
  periodKey: string | null
  state: SlideState
}

export const Column = tracked(function Column(raw: Props & Record<string, unknown>) {
  const {
    vertical, title, subLabel, shorter, label, active, deckActive, deckMain, addPlaceholder, goals, periodKey, periodDirection,
    periodSwapId, span, end, floating, away, onPeriodStep, onPeriodToday, onPeriodMode, onMouseEnter, ...attrs
  } = withDefaults(raw, DEFAULTS)
  const s = useSetup({
    vertical, title, subLabel, shorter, label, active, deckActive, deckMain, addPlaceholder, goals, periodKey, periodDirection,
    periodSwapId, span, end, floating, away, onMouseEnter: onMouseEnter as ((event: MouseEvent) => void) | undefined,
  }, (props) => {
    function onAdd(title: string) {
      if (!title.trim()) return
      playSound('add_goal_clicked')
      void store.createGoalOn(props.vertical, title, props.periodKey)
    }

    /* `active` is the one expanded column, toggled by a click on its header. Every column renders each goal's whole
       nested subtree. */
    function onHeaderClick(): void {
      if (!props.span) store.toggleExpandedColumn(props.vertical)
    }
    /* The column's accessible name says the full name of its header, the kind first as they read, whichever form of it is
       on screen. A span has no forms, so its own words are its name. */
    const accessibleName = computed(() => props.label || [props.subLabel, props.title].filter(Boolean).join(', '))
    /* While a goal is dragged the dots take the period bars' place; a span has neither. */
    const dragging = computed(() => store.state.drag.id !== null)
    /* The line pinned at the column's top holds the period bars. A span and the column floating over the spans don't
       page, so they have neither; Life has the line and no bars, as it has no period to step. */
    const pinned = computed(() => !props.span && !props.floating)
    const paging = computed(() => pinned.value && props.vertical !== 'life' && props.vertical !== 'maybe')

    /** One props bag per top-level card, forwarded straight through. */
    function cardProps(goal: GoalCardData) {
      return {
        id: goal.id,
        parentId: goal.parentId,
        title: goal.title,
        done: goal.done,
        color: goal.color,
        contextLabel: goal.contextLabel,
        vertical: goal.vertical,
        columnVertical: props.vertical,
        foil: goal.foil,
        ghost: goal.ghost,
        progress: goal.progress,
        subgoalCount: goal.subgoalCount,
        repeat: goal.repeat,
        children: goal.children,
      }
    }

    const dragSlot = computed(() => store.state.drag.slot)
    const isReorderHere = computed(() => {
      const slot = dragSlot.value
      return !!slot
        && slot.vertical === props.vertical
        && (slot.periodKey ?? null) === (props.periodKey ?? null)
    })
    /* This column splices its own top-level slot only when the slot's group owner is `null`: a nested group's slot
       (append included) belongs to that group's GoalCard, which splices its own children list with the same markup. */
    const isTopLevelReorderHere = computed(() => (
      isReorderHere.value && dragSlot.value?.parentId === null
    ))
    const isSourceSlot = computed(() => isReorderHere.value
      && store.state.drag.sourceVertical === props.vertical
      && (store.state.drag.sourcePeriodKey ?? null) === (props.periodKey ?? null))
    const indicatorStyle = computed(() => {
      const drag = store.state.drag
      if (isSourceSlot.value) return { height: `${drag.slotHeight}px` }
      return {
        height: `${drag.previewHeight + drag.tailHeight}px`,
        marginLeft: `${drag.slotInsetLeft}px`,
        marginRight: `${drag.slotInsetRight}px`,
      }
    })
    const sourceRowTargetStyle = computed(() => {
      const drag = store.state.drag
      return {
        top: `${drag.slotInsetTop}px`,
        right: `${drag.slotInsetRight}px`,
        bottom: `${drag.slotInsetBottom}px`,
        left: `${drag.slotInsetLeft}px`,
      }
    })

    let slideId = 0
    function snapshot(state: SlideState): PeriodSlide {
      return {
        id: ++slideId,
        title: props.title,
        subLabel: props.subLabel,
        shorter: props.shorter,
        goals: [...props.goals],
        periodKey: props.periodKey,
        state,
      }
    }

    function renderItems(slide: PeriodSlide): RenderItem[] {
      const items: RenderItem[] = slide.goals.filter(goal => !goal.ghost).map((goal) => ({ kind: 'goal', key: goal.id, goal }))
      if (slide.state === 'outgoing' || !isTopLevelReorderHere.value) return items
      const beforeId = dragSlot.value?.insertBeforeId ?? null
      const found = beforeId === null
        ? items.length
        : items.findIndex((item) => item.kind === 'goal' && item.goal.id === beforeId)
      items.splice(found < 0 ? items.length : found, 0, {
        kind: 'slot',
        key: store.state.drag.settling ? '__dnd-destination__' : '__dnd-placeholder__',
        settling: store.state.drag.settling !== null,
      })
      return items
    }

    function carriedGoals(slide: PeriodSlide): GoalCardData[] {
      // The goal in the hand is out of its group while you hold it.
      return slide.goals.filter(goal => goal.ghost && goal.id !== store.state.drag.id)
    }
    /* "Replan" asks the agent about the carried plans (lib/replan.ts). */
    function onReplan(from: Element, plans: { id: string; title: string }[]): void {
      window.dispatchEvent(new CustomEvent('verticals:replan', { detail: { from, plans, column: props.vertical } }))
    }

    const columnRoot = ref<HTMLElement | null>(null)
    // The board's `@mouseenter` on the column, on its element as Vue binds it: a menu teleported out of a card is not in it.
    listen(columnRoot, 'mouseenter', (event) => props.onMouseEnter?.(event))
    const periodTrack = ref<HTMLElement | null>(null)
    const slides = ref<PeriodSlide[]>([snapshot('current')])
    let latest = slides.value[0]!
    let swapAnimation: Animation | null = null
    let swapVersion = 0

    /* The line pinned at the top of each slide says the header's own words: the kind at the column's top, the period once
       the big name has scrolled under it, each in the form that slide's header chose for its room, which it reports.
       Before it has, the full forms stand. */
    const forms = reactive<Record<number, NameForm>>({})
    function onForm(slide: PeriodSlide, form: NameForm): void {
      forms[slide.id] = form
    }
    function formOf(slide: PeriodSlide): NameForm {
      return forms[slide.id] ?? { name: slide.title, kind: slide.subLabel }
    }
    /* What the kind line carries beyond the kind, the month a short form moved up and the year of a period outside this
       one, goes after the name on the line: "21–27 · Dec ’27", "January · ’27". */
    function nameOf(slide: PeriodSlide): string {
      const form = formOf(slide)
      return form.name + kindTail(form.kind)
    }
    /* Where each slide's words end on its line, in px from the column's left: the left box of the sign grows into the
       room they leave, the longest of the slides on show while two swap. */
    const wordsEnds = reactive<Record<number, number>>({})
    function onWords(slide: PeriodSlide, end: number): void {
      wordsEnds[slide.id] = end
    }
    const wordsEnd = computed(() => Math.max(0, ...slides.value.map((slide) => wordsEnds[slide.id] ?? 0)))
    watch(slides, (list) => {
      const live = new Set(list.map((slide) => String(slide.id)))
      for (const id of Object.keys(forms)) if (!live.has(id)) delete forms[Number(id)]
      for (const id of Object.keys(wordsEnds)) if (!live.has(id)) delete wordsEnds[Number(id)]
    })

    watch(
      () => props.periodSwapId,
      async (swapId) => {
        if (swapId === 0 || props.vertical === 'life') {
          latest = snapshot('current')
          slides.value = [latest]
          return
        }
        if (props.periodKey === latest.periodKey) {
          latest = { ...latest, title: props.title, subLabel: props.subLabel, shorter: props.shorter, goals: [...props.goals] }
          if (slides.value.length === 1) slides.value = [latest]
          return
        }
        const version = ++swapVersion
        swapAnimation?.cancel()
        if (reducedMotion()) {
          // The new period replaces the old at once: sliding them past each other is travel, and laying them on one
          // another to cross-fade doubles every title and date mid-frame.
          latest = snapshot('current')
          slides.value = [latest]
          return
        }
        const outgoing: PeriodSlide = { ...latest, id: ++slideId, state: 'outgoing' }
        const incoming = snapshot('incoming')
        latest = { ...incoming, state: 'current' }
        slides.value = props.periodDirection < 0
          ? [incoming, outgoing]
          : [outgoing, incoming]

        await nextTick()
        if (version !== swapVersion || !periodTrack.value) return
        const frames = props.periodDirection < 0
          ? [{ transform: 'translateX(-50%)' }, { transform: 'translateX(0)' }]
          : [{ transform: 'translateX(0)' }, { transform: 'translateX(-50%)' }]
        const animation = periodTrack.value.animate(frames, {
          duration: 350,
          easing: 'ease',
          fill: 'forwards',
        })
        swapAnimation = animation
        try {
          await animation.finished
        } catch {
          return
        }
        if (version !== swapVersion) return
        slides.value = [{ ...latest, id: ++slideId, state: 'current' }]
        await nextTick()
        animation.cancel()
        if (swapAnimation === animation) swapAnimation = null
      },
      { flush: 'pre' },
    )

    watch(
      () => [props.title, props.subLabel, props.shorter, props.goals, props.periodKey] as const,
      () => {
        if (slides.value.length !== 1) return
        // Ordinary writes update the current slide without changing its key: remounting the slide would end the cards'
        // own checkbox and completion animations and observers.
        latest = {
          ...slides.value[0]!,
          title: props.title,
          subLabel: props.subLabel,
          shorter: props.shorter,
          goals: [...props.goals],
          periodKey: props.periodKey,
          state: 'current',
        }
        slides.value = [latest]
      },
      { flush: 'post' },
    )

    const insertionSlot = computed(() => {
      if (!isTopLevelReorderHere.value) return undefined
      return dragSlot.value?.insertBeforeId ?? null
    })
    watch(insertionSlot, async () => {
      if (reducedMotion()) return // the gap simply opens, the goals below stand where they land
      const selector = ':scope > [data-role="period-track"] > [data-state]:not([data-state="outgoing"]) [data-goal-id]'
      const before = new Map(
        [...(columnRoot.value?.querySelectorAll<HTMLElement>(selector) ?? [])]
          // A hidden card (a goal's subtasks flying with it) has no place to slide from.
          .filter((element) => element.getClientRects().length > 0)
          .map((element) => [element.dataset.goalId, element.getBoundingClientRect().top]),
      )
      await nextTick()
      for (const element of columnRoot.value?.querySelectorAll<HTMLElement>(selector) ?? []) {
        const oldTop = before.get(element.dataset.goalId)
        if (oldTop === undefined) continue
        const delta = oldTop - element.getBoundingClientRect().top
        if (Math.abs(delta) < 0.5) continue
        element.animate(
          [{ transform: `translateY(${delta}px)` }, { transform: 'translateY(0)' }],
          { duration: 200, easing: 'cubic-bezier(0.2, 0, 0, 1)' },
        )
      }
    })

    onBeforeUnmount(() => swapAnimation?.cancel())

    return {
      onAdd, onHeaderClick, accessibleName, dragging, pinned, paging, cardProps, isSourceSlot, indicatorStyle,
      sourceRowTargetStyle, renderItems, carriedGoals, onReplan, columnRoot, periodTrack, slides, onForm, formOf, nameOf,
      onWords, wordsEnd,
    }
  })

  const dragging = s.dragging.value
  const pinned = s.pinned.value
  const slides = s.slides.value
  return (
    <div
      {...fallthrough({
        ref: bindRef(s.columnRoot),
        className: cx('pattern-vertical-board__column', {
          'pattern-vertical-board__column--active': active,
          'pattern-vertical-board__column--deck-active': deckActive,
          'pattern-vertical-board__column--deck-main': deckMain,
        }),
        'data-vertical': vertical,
        'data-period-key': periodKey ?? '',
        role: 'group',
        'aria-label': s.accessibleName.value,
      }, attrs)}
    >
      {/* The period bars, | ||| |, on the line pinned at the top of the slide on show; while a goal is dragged the dots
          stand in their place. They stay put while the slides swap. */}
      {s.paging.value && !dragging ? (
        <ColumnBars
          kind={kindOf(vertical)}
          plural={pluralOf(vertical)}
          away={away}
          wordsEnd={s.wordsEnd.value}
          onStep={(direction) => onPeriodStep?.(vertical, direction)}
          onToday={() => onPeriodToday?.()}
          onMode={() => onPeriodMode?.(vertical, periodKey)}
        />
      ) : null}
      {dragging && vertical !== 'life' && vertical !== 'maybe' && !span ? <ColumnDots vertical={vertical as SpanScale} /> : null}
      <div
        ref={bindRef(s.periodTrack)}
        className={cx('period-track', { 'period-track--swapping': slides.length === 2 })}
        data-role="period-track"
      >
        {slides.map((slide) => {
          const carried = s.carriedGoals(slide)
          return (
            <section
              key={slide.id}
              className={cx('period-slide', { 'period-slide--pinned': pinned })}
              data-role="period-slide"
              data-state={vertical === 'life' ? undefined : slide.state}
              data-period-key={slide.periodKey ?? ''}
            >
              {/* The line pinned at the top of the slide, over the header's kind row and the goals that scroll under it;
                  it scrolls with its slide. A click on its words is a click on the header. */}
              {pinned ? (
                <ColumnLine
                  kind={s.formOf(slide).kind}
                  name={s.nameOf(slide)}
                  onWords={(end: number) => s.onWords(slide, end)}
                  onClick={s.onHeaderClick}
                />
              ) : null}
              <ColumnHeader
                title={slide.title}
                subLabel={slide.subLabel}
                shorter={slide.shorter}
                end={end}
                data-cap={span ? undefined : 'column-expand'}
                // falls through onto the header's root
                onClick={s.onHeaderClick}
                onForm={(form) => s.onForm(slide, form)}
              />
              <div className="pattern-vertical-board__body">
                {carried.length ? <CarriedGroup vertical={vertical} periodKey={slide.periodKey} goals={carried} onReplan={s.onReplan} /> : null}
                <KCardStack dense data-section="planned">
                  {s.renderItems(slide).map((item) => item.kind === 'slot' ? (
                    <div
                      key={item.key}
                      className="pattern-vertical-board__drop-indicator"
                      data-role={item.settling ? 'drop-destination' : 'drop-indicator'}
                      data-dnd-placeholder={item.settling ? undefined : ''}
                      data-dnd-destination={item.settling ? '' : undefined}
                      data-box={s.isSourceSlot.value ? 'card' : 'row'}
                      data-tail={store.state.drag.tailHeight || undefined}
                      aria-hidden="true"
                      style={sx(s.indicatorStyle.value)}
                    >
                      {s.isSourceSlot.value ? (
                        <div
                          className="pattern-vertical-board__drop-row-target"
                          data-role="drop-row-target"
                          style={sx(s.sourceRowTargetStyle.value)}
                        />
                      ) : null}
                    </div>
                  ) : (
                    <GoalCard key={item.key} {...s.cardProps(item.goal)} />
                  ))}
                  {!filterActive.value ? <InlineAdd placeholder={addPlaceholder} data-cap="create-goal" onAdd={s.onAdd} /> : null}
                </KCardStack>
                {filterActive.value && slide.state !== 'outgoing'
                  ? <FindingSections vertical={vertical} periodKey={slide.periodKey} shown={slide.goals} />
                  : null}
              </div>
            </section>
          )
        })}
      </div>
    </div>
  )
})
