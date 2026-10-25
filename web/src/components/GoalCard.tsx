/* A goal on the board: its row (square or ring, title, facts, dots, session mark), and
   under it, as a sibling, the list of its subgoals that it draws again as GoalCards, then "Add…" and the notes of an open
   goal. The row arms the drag (lib/drag.ts through the store), the card and its list lift as one piece (lib/cardLift.ts)
   and carry the open goal's family light (lib/cardFamily.ts). Two roots, so nothing a parent passes falls through. */
import type { KeyboardEvent as ReactKeyboardEvent, MemoExoticComponent, MouseEvent as ReactMouseEvent, ReactNode } from 'react'
import { computed, ref, watch } from '../reactivity'
import { pressToDrag } from './CardDnd'
import { KCard } from '../kit'
import { useCompletionCelebration } from '../lib/completionCelebration'
import { keyboardHelpOpen } from '../lib/keyboard'
import { caretAt, useInlineTitleEdit } from '../lib/inlineTitleEdit'
import { anyMenuOpen, menuGoalId, pointerOver, useCardLift, whenHandMoves, whenMenuCloses } from '../lib/cardLift'
import { useGroupWash } from '../lib/goalWash'
import { useCardDrag } from '../lib/cardDrag'
import { withSlot, type SlotItem } from '../lib/reorderSlot'
import { playSound } from '../lib/sound'
import { GoalCardTools, type GoalCardToolsApi } from './GoalCardTools'
import { SessionMark } from './SessionMark'
import { GoalDetail } from './GoalDetail'
import { GoalFacts } from './GoalFacts'
import { GoalTitle } from './GoalTitle'
import { GoalCompletion } from './GoalCompletion'
import { DropSlot } from './DropSlot'
import { SubgoalAddRow } from './SubgoalAddRow'
import { GoalAffordance } from '../kit-ext/goal-affordance/GoalAffordance'
import { store } from '../store'
import { highlightTitle, isContextGoal } from '../lib/commandFilter'
import type { GoalCardData } from '../types'
import type { RepeatRule } from '../lib/api'
import { goalCardLight } from '../lib/look'
import { isPending, subtreeIds } from '../lib/boardIndex'
import { useCardFamily } from '../lib/cardFamily'
import { familyMovingNow } from '../lib/familyMotion'
import { isPrivate } from '../lib/privacy'
import { bindRef, cx, sx } from '../bind'
import { tracked } from '../tracked'
import { listen, useSetup, withDefaults } from '../setup'
import { Transition } from '../Transition'
import '../kit-ext/carryover-ghost/carryover-ghost.css'
import './goalCard.css'

interface Props {
  id: string
  parentId?: string | null
  title: string
  done?: boolean
  /** One of the six canon hexes, or unset for no colour, derived by the server from the goal's value root. */
  color?: string | null
  /** Polymorphic: the caller decides which sense fills this slot. */
  contextLabel?: string
  /** Search-only period slot. Empty string deliberately renders an empty marked element. */
  searchPeriod?: string
  /** Search-only explicit open affordance; board cards retain their existing title/row gesture. */
  searchOpen?: boolean
  /** `goals.vertical`, retained for existing card-menu behavior. */
  vertical?: string | null
  /** Column where this rendered instance lives; owns movable-main detail context. */
  columnVertical?: string | null
  repeat?: RepeatRule | null
  foil?: boolean
  ghost?: boolean
  /** `BoardResponse.progress[id]`: done/total over descendants. Absent on a leaf. */
  progress?: { done: number; total: number }
  subgoalCount?: number
  /** The goal's subgoals, as data: a GoalCard takes no JSX children. */
  children?: GoalCardData[]
  depth?: number
  /** The goals this one is drawn under in its column, outermost first. A click opens them and it. */
  chain?: string[]
}
const DEFAULTS = {
  done: false,
  parentId: null,
  color: null,
  contextLabel: '',
  searchOpen: false,
  vertical: null,
  columnVertical: null,
  repeat: null,
  foil: false,
  ghost: false,
  subgoalCount: 0,
  children: [] as GoalCardData[],
  depth: 0,
  chain: [] as string[],
}

type GoalItem = { kind: 'goal'; key: string; goal: GoalCardData }

/* The row is the drag's entry surface, a slot target and the home of every card control, so each pointer handler
   ignores what started on a control. The portalled menu stops its own events; this covers the affordance, title and
   schedule trigger. */
function fromControl(event: Event): boolean {
  const el = event.target as HTMLElement | null
  return !!el?.closest('button, input, textarea, label, a, [data-role="tag"], .chip, .goal-card__tools, .dropdown')
}

/** A subgoal drawn under its goal, in the goal's column, one level down. */
function subgoalProps(goal: GoalCardData, parent: { id: string; columnVertical: string | null; depth: number; chain: string[] }) {
  return {
    id: goal.id,
    parentId: goal.parentId,
    title: goal.title,
    done: goal.done,
    color: goal.color,
    contextLabel: goal.contextLabel,
    vertical: goal.vertical,
    columnVertical: parent.columnVertical,
    foil: goal.foil,
    ghost: goal.ghost,
    progress: goal.progress,
    subgoalCount: goal.subgoalCount,
    children: goal.children,
    depth: parent.depth + 1,
    chain: [...parent.chain, parent.id],
  }
}

// Named apart from the export: in its body `GoalCard` is the tracked component its nested steps draw with.
export const GoalCard: MemoExoticComponent<(props: Props) => ReactNode> = tracked(function GoalCardView(raw: Props): ReactNode {
  const props = withDefaults(raw, DEFAULTS)
  const s = useSetup(props, (props) => {
    const blurred = computed(() => props.searchPeriod === undefined && !props.searchOpen && isPrivate(props.id))
    const titleParts = computed(() => props.columnVertical === 'window'
      ? [{ text: props.title, match: false }] : highlightTitle(props.title))
    const filterContext = computed(() => props.columnVertical !== 'window' && isContextGoal(props.id))
    const cardStyle = computed(() => goalCardLight(props.color))
    // KCard's root element itself.
    const cardRoot = ref<HTMLElement | null>(null)
    const rowEl = ref<HTMLElement | null>(null)
    const childrenListEl = ref<HTMLElement | null>(null)

    function rootElement(): HTMLElement | null {
      return cardRoot.value instanceof HTMLElement ? cardRoot.value : null
    }

    const isParent = computed(() => props.subgoalCount > 0 || (props.progress?.total ?? 0) > 0)
    const hasMilestone = computed(() => (props.progress?.total ?? 0) > 0)

    function onToggle(value: boolean) {
      playSound(value ? 'checked' : 'unchecked')
      void store.completeGoal(props.id, value)
    }

    /* Where this card stands in the open goal's family: the open goal, a level stepped through, a step, or a relative
       lit further off (flow 4, `lib/cardFamily.ts`). */
    const {
      isInlineDetailHost, isOpenRelated, isFocus, isInsideOpen, familyDepth, isPathLine, isDeepestStep,
      familyKids, listKids, familyLit, lightMove, showChildren, onOpenDetail, growList, foldList,
    } = useCardFamily(props, rootElement)

    const menuOpen = ref(false)
    const tools = ref<GoalCardToolsApi | null>(null)

    /* Hover family chain, both directions: the wash class is a reactive bind off `store.hoverChain`, since class
       patching drops imperatively-added classes. */
    function highlightFamily(): void {
      // While a menu is open the board holds still; this card lights its family once it closes, if still pointed at.
      if (anyMenuOpen()) {
        whenMenuCloses(() => { if (rootElement()?.matches(':hover')) highlightFamily() })
        return
      }
      store.setHoverChain(props.id)
    }
    function clearFamily(): void {
      if (menuOpen.value) return // its menu is open: the family stays lit until it closes
      if (store.state.hoverChainId === props.id) store.setHoverChain(null)
    }
    const isChainHovered = computed(() => { // lit once the pointer rests on a card (lib/boardViewState.ts)
      const chain = store.restChain.value
      return chain !== null && chain.id !== props.id && chain.set.has(props.id)
    })
    // One goal can come twice on the wire (its filtered top-level copy and its nested copy): the shared progress rollup
    // is fresher than a child copy. Requiring rendered children keeps ancestors from celebrating a completion in a lower
    // column.
    const childrenAllDone = computed(() =>
      props.children.length > 0
      && (props.progress?.total ?? 0) > 0
      && props.progress?.done === props.progress?.total,
    )
    const completionLayer = ref<HTMLElement | null>(null)
    const completionMedia = ref<SVGSVGElement | null>(null)
    const { completionActive } = useCompletionCelebration(childrenAllDone, completionLayer, completionMedia)

    const inlineTitleInput = ref<HTMLTextAreaElement | null>(null)
    const title = useInlineTitleEdit({
      title: () => props.title,
      commit: (next) => void store.updateGoal(props.id, { title: next }),
      input: inlineTitleInput,
    })
    listen(inlineTitleInput, 'blur', () => { if (!keyboardHelpOpen.value) title.commit() })

    function onTitlePress(event: MouseEvent) {
      if (isInlineDetailHost.value) title.start(caretAt(event))
      else onOpenDetail()
    }

    function onMenuOpenChange(value: boolean) {
      menuOpen.value = value
      if (value) menuGoalId.value = props.id
      else {
        if (menuGoalId.value === props.id) menuGoalId.value = null
        if (!pointerOver(rootElement(), childrenListEl.value)) clearFamily()
      }
    }

    const drag = useCardDrag(props, rootElement, listKids, childrenListEl)

    /* The subgoals as drawn: none while folded, unless the card is a line of the open path; the drag's slot among them
       while it is here. */
    const childItems = computed<(GoalItem | SlotItem)[]>(() => {
      if (store.isCollapsed(props.id) && !isPathLine.value) return []
      const items = listKids.value.map((goal): GoalItem => ({ kind: 'goal', key: goal.id, goal }))
      return drag.slotHere.value ? withSlot(items) : items
    })

    /* A goal in a window is the window: it doesn't lift, doesn't leave by drag, and lights nothing on the board behind
       it. Its steps carry the same column, so they open with a click and stay. */
    const inWindow = computed(() => props.columnVertical === 'window')
    /* Hover lift: a top-level goal and its subtasks rise as one piece, `lib/cardLift.ts`. */
    const lift = useCardLift({
      card: rootElement,
      list: childrenListEl,
      enabled: () => props.depth === 0 && !props.ghost && store.state.drag.id === null && !isPathLine.value && !inWindow.value, // a carried plan stays: its box lifts (CarriedGroup)
      // its own menu or a subgoal's hangs from it
      pinned: () => {
        const id = menuGoalId.value
        return id !== null && (id === props.id || (!!store.state.board && subtreeIds(store.state.board, props.id).has(id)))
      },
    })
    watch(() => store.state.drag.id, (id) => { if (id !== null) lift.drop() })
    watch(isPathLine, (line) => { if (line) lift.drop() }) // a line on top doesn't lift: the family under it would rise with it
    /* One highlight shape per goal: a top-level goal sizes its own and its subgoals' shapes, `lib/goalWash.ts`. */
    useGroupWash({
      card: () => (props.depth === 0 ? rootElement() : null),
      list: childrenListEl,
      layoutSources: [() => props.children, showChildren, () => store.state.openGoalId, () => store.state.openPath, familyKids],
    })

    /** "Add…" at the end of an open goal's steps: the new step lives where its parent does, so it shows at once. */
    function onAddStep(title: string): void {
      if (store.isCollapsed(props.id)) store.toggleCollapsed(props.id)
      void store.addDetailChild(title)
    }
    function onCardEnter(): void {
      if (inWindow.value) return
      // After the keys took over, a card that slid under the still pointer lights only once the hand moves.
      whenHandMoves(() => { if (rootElement()?.matches(':hover')) highlightFamily() })
      lift.enter()
      void store.ensureDetail(props.id) // a click here moves the board from its detail (lib/familyMotion.ts): fetch it ahead
    }
    function onCardLeave(): void { clearFamily(); lift.leave() }

    /* A press on the row, handed to dnd-kit's sensor (CardDnd.tsx, lib/dndSensor.ts), which arms it: `pointerDownCard`
       remembers where it started and the row's rect. */
    function pressRow(event: PointerEvent): boolean {
      const row = rowEl.value
      if (!row || fromControl(event) || inWindow.value) return false
      row.focus({ preventScroll: true })
      // A drag starts from the board at rest, lifted or not: its row, the gap it leaves, the rows it may land on.
      lift.atRest(() => store.pointerDownCard(
        props.id, event.clientX, event.clientY, row.getBoundingClientRect(), event.pointerType, event.altKey,
      ))
      return true
    }

    /* An armed drag produces no `click`, so open and drop never both fire from one gesture. A plain click opens the
       goal; there is no selection. */
    function onRowClick(event: ReactMouseEvent) {
      if (fromControl(event.nativeEvent)) return
      onOpenDetail()
    }
    function onRowContextMenu(event: ReactMouseEvent): void {
      event.stopPropagation()
      event.preventDefault()
      tools.value?.openMenu()
    }
    function onRowKeydown(event: ReactKeyboardEvent) {
      if (event.defaultPrevented || event.nativeEvent.isComposing || event.nativeEvent.keyCode === 229
        || event.repeat || event.shiftKey || event.ctrlKey || event.metaKey || event.altKey) return
      if ((event.target as HTMLElement).closest('input, textarea, [contenteditable="true"]')) return
      if (!['/', 'Slash', 'Enter', ' '].includes(event.key)) return
      // Slash is the card-level options shortcut even when focus currently sits on a descendant.
      // Enter/Space remain owned by that descendant so native control activation is unchanged.
      if (!['/', 'Slash'].includes(event.key) && fromControl(event.nativeEvent)) return
      event.preventDefault()
      if (event.key === 'Enter') title.start()
      // Space on the open goal closes it the way Esc does; opening it again only redrew it.
      else if (event.key === ' ') { if (isInlineDetailHost.value) store.goUp(); else onOpenDetail() }
      else tools.value?.openMenu()
    }
    function onSearchOpen(event: ReactMouseEvent): void {
      event.stopPropagation()
      onOpenDetail()
    }

    /* "Show N subtasks" while folded, "Hide" while shown; never on a line of the open path, which lists its steps. */
    const subtasksToggle = computed(() => {
      const count = props.children.length
      const collapsed = store.isCollapsed(props.id)
      if (!count || isPathLine.value || !(showChildren.value || collapsed)) return null
      return { collapsed, label: `${collapsed ? 'Show' : 'Hide'} ${count} ${count === 1 ? 'subtask' : 'subtasks'}` }
    })
    function onToggleSubtasks(event: ReactMouseEvent): void {
      event.stopPropagation()
      store.toggleCollapsed(props.id)
    }

    const cardClass = computed(() => {
      const lit = familyLit.value
      return cx('goal-card', {
        'goal-card--source-gap-closed': drag.closesSourceGap.value,
        'goal-card--nested-drag-hole': drag.isNestedDragHole.value,
        'goal-card--menu-open': menuOpen.value,
        'goal-card--landed-hover': drag.landedHover.value,
        'goal-card--colored': props.color,
        'goal-card--done': props.done,
        'goal-card--detail-open': isInlineDetailHost.value,
        'goal-card--open-related': !lit && isOpenRelated.value && !isInsideOpen.value,
        'goal-card--with-subgoals': props.depth === 0 && showChildren.value && !isInlineDetailHost.value,
        'goal-card--focus': isFocus.value && props.depth > 0,
        'goal-card--path-line': isPathLine.value,
        'goal-card--deepest-step': isDeepestStep.value,
        [`goal-card--lit-${lit}`]: !!lit,
        'goal-card--ancestor-hover': !lit && isChainHovered.value && !isInsideOpen.value,
        'goal-card--lifted': lift.lifted.value,
        'goal-card--settling': lift.settling.value,
        'carryover-ghost': props.ghost,
        'goal-card--private': blurred.value,
      })
    })
    const rowClass = computed(() => {
      const combine = drag.isCombineTarget.value
      return cx('goal-card__row', {
        'goal-card__row--detail-open': isInlineDetailHost.value,
        'goal-card__row--drag-source': drag.isDragSource.value,
        'goal-card__row--combine-target': combine,
        'goal-card__row--combine-target-colored': combine && props.color,
      })
    })
    const listClass = computed(() => cx('goal-card__children subgoal-recursive-list', {
      'goal-card__children--lifted': lift.lifted.value,
      'goal-card__children--settling': lift.settling.value,
      'goal-card__children--drag-source': drag.isDragSource.value,
      'goal-card__children--gap-closed': drag.closesSourceGap.value,
      'goal-card__children--open': isInlineDetailHost.value,
      'goal-card__children--path': isPathLine.value && props.depth > 0,
      'goal-card__children--family': isPathLine.value || (isInlineDetailHost.value && familyDepth.value >= 0),
      'goal-card__children--private': blurred.value,
    }))
    const listStyle = computed(() => sx(cardStyle.value, { '--subgoal-depth': String(props.depth) }, lift.listStyle.value))

    // Native listeners: a menu teleported out of the card is outside it and its list in the DOM, so its events don't reach
    // them.
    listen(cardRoot, 'mouseenter', onCardEnter)
    listen(cardRoot, 'mouseleave', onCardLeave)
    listen(childrenListEl, 'mouseenter', lift.enter)
    listen(childrenListEl, 'mouseleave', lift.leave)
    listen(rowEl, 'pointerdown', (event) => pressToDrag(event, pressRow))

    return {
      titleParts, filterContext, cardStyle, cardRoot, rowEl, childrenListEl, isParent, hasMilestone, onToggle,
      isInlineDetailHost, isPathLine, familyLit, lightMove, showChildren, growList, foldList, completionLayer,
      completionMedia, completionActive, tools, inlineTitleInput, title, onTitlePress, onMenuOpenChange, drag, childItems,
      lift, onAddStep, onRowClick, onRowContextMenu, onRowKeydown, onSearchOpen, subtasksToggle, onToggleSubtasks,
      cardClass, rowClass, listClass, listStyle,
    }
  })

  const { id, color, ghost, repeat, chain, parentId, progress, searchPeriod, searchOpen, contextLabel } = props
  const isInlineDetailHost = s.isInlineDetailHost.value
  const isDragSource = s.drag.isDragSource.value
  const isCombineTarget = s.drag.isCombineTarget.value
  const familyLit = s.familyLit.value
  const filterContext = s.filterContext.value
  const toggle = s.subtasksToggle.value
  const css = !familyMovingNow.value

  return (
    <>
      <KCard
        ref={bindRef(s.cardRoot)}
        dense
        className={s.cardClass.value}
        data-goal-id={id}
        inert={isPending(id) || undefined}
        data-row-key={[...chain, id].join('/') + (ghost ? '~' : '')}
        data-light={familyLit ?? undefined}
        data-light-move={s.lightMove.value ?? undefined}
        data-filter-context={filterContext ? 'true' : undefined}
        style={sx(s.cardStyle.value, s.lift.cardStyle.value)}
        data-parent-id={parentId ?? undefined}
        data-colored={color ? 'true' : 'false'}
        data-ghost={ghost ? 'true' : undefined}
      >
        <div
          ref={bindRef(s.rowEl)}
          className={s.rowClass.value}
          data-role="drop-target"
          data-cap="reorder"
          role="button"
          tabIndex={0}
          aria-hidden={isDragSource ? 'true' : undefined}
          data-dnd-combine-target={isCombineTarget ? '' : undefined}
          onClick={s.onRowClick}
          onContextMenu={s.onRowContextMenu}
          onKeyDown={s.onRowKeydown}
        >
          <span
            className="goal-card__affordance-slot"
            data-role="goal-affordance"
            data-affordance={s.isParent.value ? 'parent' : 'leaf'}
          >
            <GoalAffordance
              kind={s.hasMilestone.value ? 'ring' : 'square'}
              checked={props.done}
              done={progress?.done ?? 0}
              total={progress?.total ?? 0}
              color={color}
              onToggle={s.onToggle}
            />
          </span>
          <div className="goal-card__text">
            <GoalTitle
              parts={s.titleParts.value}
              repeat={!!repeat}
              context={filterContext}
              editable={isInlineDetailHost}
              editing={s.title.editing.value}
              draft={s.title.draft.value}
              input={s.inlineTitleInput}
              onPress={s.onTitlePress}
              onInput={s.title.onInput}
              onCommit={s.title.commit}
              onCancel={s.title.cancel}
            />
            {searchPeriod !== undefined ? (
              <p data-role="search-period" className="goal-card__meta">{searchPeriod}</p>
            ) : null}
            {searchOpen ? (
              <button type="button" data-role="search-open" className="goal-card__search-open" onClick={s.onSearchOpen}>Open</button>
            ) : null}
            {contextLabel ? <p className="goal-card__meta">{contextLabel}</p> : null}
            {toggle ? (
              <button
                type="button"
                className="goal-card__subtasks-toggle"
                data-role="subtasks-toggle"
                aria-expanded={!toggle.collapsed}
                onClick={s.onToggleSubtasks}
              >{toggle.label}</button>
            ) : null}
            <Transition name="goal-part" css={css}>{isInlineDetailHost ? <GoalFacts id={id} /> : null}</Transition>
          </div>
          <GoalCardTools
            expose={s.tools}
            id={id}
            vertical={props.vertical}
            repeat={repeat}
            open={isInlineDetailHost}
            onOpenChange={s.onMenuOpenChange}
          />
          {!ghost ? <SessionMark goalId={id} /> : null}
        </div>
      </KCard>
      {/* An open goal is one piece top to bottom: its title and facts (the card above), its steps, "Add…", then its
          notes. The notes live in this list, so they rise and colour with the rest. */}
      <Transition css={false} onEnter={s.growList} onLeave={s.foldList}>
        {s.showChildren.value ? (
          <div
            ref={bindRef(s.childrenListEl)}
            className={s.listClass.value}
            data-open-region={isInlineDetailHost ? '' : undefined}
            style={s.listStyle.value}
          >
            {s.completionActive.value ? <GoalCompletion layer={s.completionLayer} media={s.completionMedia} /> : null}
            {s.childItems.value.map((item) => (
              item.kind === 'slot'
                ? <DropSlot key={item.key} settling={item.settling} source={s.drag.sourceSlot.value} />
                : <GoalCard key={item.key} {...subgoalProps(item.goal, props)} />
            ))}
            {/* The open goal's own parts grow in and fold away together, in the opening's time and curve, so what is
                below slides instead of jumping. */}
            <Transition name="goal-part" css={css}>
              {isInlineDetailHost ? <SubgoalAddRow className="goal-card__add-step" commitOnEnter onCommit={s.onAddStep} /> : null}
            </Transition>
            <Transition name="goal-notes" css={css}>{isInlineDetailHost ? <GoalDetail /> : null}</Transition>
          </div>
        ) : null}
      </Transition>
    </>
  )
})
