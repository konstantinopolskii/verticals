/* A goal on the board: its row (square or ring, title, facts, dots, session mark), and
   under it, as a sibling, the list of its subgoals that it draws again as GoalCards, then "Add…" and the notes of an open
   goal. The row arms the drag (lib/drag.ts through the store), the card and its list lift as one piece (lib/cardLift.ts)
   and carry the open goal's family light (lib/cardFamily.ts). Two roots, so nothing a parent passes falls through. */
import { Fragment, type MemoExoticComponent, type ReactNode } from 'react'
import { computed, nextTick, onBeforeUnmount, ref, watch } from '../reactivity'
import { pressToDrag } from './CardDnd'
import { KCard } from '../kit'
import { COMPLETION_LOTTIE, useCompletionCelebration } from '../lib/completionCelebration'
import { caretAt, useInlineTitleEdit } from '../lib/inlineTitleEdit'
import { anyMenuOpen, menuGoalId, pointerOver, useCardLift, whenMenuCloses } from '../lib/cardLift'
import { useGroupWash } from '../lib/goalWash'
import { playSound } from '../lib/sound'
import { RepeatMark } from './RepeatMark'
import { GoalCardTools, type GoalCardToolsApi } from './GoalCardTools'
import { SessionMark } from './SessionMark'
import { GoalDetail } from './GoalDetail'
import { GoalFacts } from './GoalFacts'
import { SubgoalAddRow } from './SubgoalAddRow'
import { GoalAffordance } from '../kit-ext/goal-affordance/GoalAffordance'
import { store } from '../store'
import { highlightTitle, isContextGoal } from '../lib/commandFilter'
import type { GoalCardData } from '../types'
import type { RepeatRule } from '../lib/api'
import { goalWashInk, NEUTRAL_LIGHT } from '../lib/goalColor'
import { devPaletteFor } from '../lib/devPalette'
import { goalHoverBackground } from '../lib/look'
import { isPending, subtreeIds } from '../lib/boardIndex'
import { levelTints } from '../lib/familyView'
import { useCardFamily } from '../lib/cardFamily'
import { familyMovingNow } from '../lib/familyMotion'
import { devGoalLayout } from '../lib/devGoalLayout'
import { isPrivate } from '../lib/privacy'
import { reducedMotion } from '../lib/motion'
import { bindRef, cx, sx, valueOf } from '../bind'
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

type ChildRenderItem =
  | { kind: 'goal'; key: string; goal: GoalCardData }
  | { kind: 'slot'; key: '__dnd-placeholder__' | '__dnd-destination__'; settling: boolean }

// Named apart from the export: in its body `GoalCard` is the tracked component its nested steps draw with.
export const GoalCard: MemoExoticComponent<(props: Props) => ReactNode> = tracked(function GoalCardView(raw: Props): ReactNode {
  const props = withDefaults(raw, DEFAULTS)
  const s = useSetup(props, (props) => {
    const checked = computed(() => props.done)
    const blurred = computed(() => props.searchPeriod === undefined && !props.searchOpen && isPrivate(props.id))
    const titleParts = computed(() => props.columnVertical === 'window'
      ? [{ text: props.title, match: false }] : highlightTitle(props.title))
    const filterContext = computed(() => props.columnVertical !== 'window' && isContextGoal(props.id))
    const cardStyle = computed(() => {
      const palette = devPaletteFor(props.color)
      // flow 4: the family's faint and farthest tints, found from this colour (lib/familyView.ts)
      const [rgb, alpha] = palette?.card
        ? [[1, 3, 5].map((i) => Number.parseInt(palette.card.color.slice(i, i + 2), 16)), palette.card.opacity]
        : [props.color ? goalWashInk(props.color).washRgb.split(',').map(Number) : NEUTRAL_LIGHT, 1]
      const tints = levelTints(rgb, alpha, Number(devGoalLayout['--kkov-light-tint']), Number(devGoalLayout['--kkov-far-tint']))
      return {
        '--goal-hover-background': goalHoverBackground(props.color),
        '--goal-faint-tint': String(tints.faint),
        '--goal-far-tint': String(tints.far),
      }
    })
    // KCard's root element itself.
    const cardRoot = ref<HTMLElement | null>(null)

    function rootElement(): HTMLElement | null {
      return cardRoot.value instanceof HTMLElement ? cardRoot.value : null
    }

    const isParent = computed(
      () => props.subgoalCount > 0 || (props.progress?.total ?? 0) > 0,
    )

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

    function onTitleClick(event: MouseEvent) {
      if (isInlineDetailHost.value) startInlineTitleEdit(caretAt(event))
      else onOpenDetail()
    }

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
    const { completionActive } = useCompletionCelebration(
      childrenAllDone,
      completionLayer,
      completionMedia,
    )

    const hasMilestone = computed(() => (props.progress?.total ?? 0) > 0)

    const menuOpen = ref(false)
    const tools = ref<GoalCardToolsApi | null>(null)

    const inlineTitleInput = ref<HTMLTextAreaElement | null>(null)
    const {
      editing: editingInlineTitle,
      draft: inlineTitleDraft,
      start: startInlineTitleEdit,
      onInput: onInlineTitleInput,
      commit: commitInlineTitle,
      cancel: cancelInlineTitleEdit,
    } = useInlineTitleEdit({
      title: () => props.title,
      commit: (next) => void store.updateGoal(props.id, { title: next }),
      input: inlineTitleInput,
    })
    listen(inlineTitleInput, 'blur', () => commitInlineTitle())

    function onMenuOpenChange(value: boolean) {
      menuOpen.value = value
      if (value) menuGoalId.value = props.id
      else {
        if (menuGoalId.value === props.id) menuGoalId.value = null
        if (!pointerOver(rootElement(), childrenListEl.value)) clearFamily()
      }
    }

    function openContextMenu(): void {
      tools.value?.openMenu()
    }

    function onCardContextMenu(event: MouseEvent): void {
      event.preventDefault()
      openContextMenu()
    }

    /* The row keeps its DOM identity while inline detail is open; drag state may hide that same row for a while. */
    const isDragSource = computed(
      () => store.state.drag.id === props.id || store.state.drag.settling?.id === props.id,
    )
    /* The flying copy was cloned hovered; the browser re-hovers the landed card only on the next pointer move, so hold
       the hover look until then. */
    const landedHover = ref(false)
    function releaseLandedHover(): void {
      landedHover.value = false
      window.removeEventListener('pointermove', releaseLandedHover)
    }
    watch(isDragSource, (now, was) => {
      if (now || !was) return
      const box = rootElement()?.getBoundingClientRect()
      const { x, y } = store.state.drag
      if (!box || x < box.left || x > box.right || y < box.top || y > box.bottom) return
      landedHover.value = true
      window.addEventListener('pointermove', releaseLandedHover)
    }, { flush: 'post' })
    onBeforeUnmount(releaseLandedHover)
    const isCombineTarget = computed(
      () => store.state.drag.id !== null
        && store.state.drag.target?.kind === 'combine'
        && store.state.drag.target.targetId === props.id,
    )
    /* Only a top-level source collapses: the column's own placeholder holds its box elsewhere. A nested one keeps its
       box (`isNestedDragHole`), or its parent would snap shut when the drag arms. */
    const closesSourceGap = computed(
      () => props.depth === 0 && !props.ghost && isDragSource.value && store.state.drag.settling?.cancelled !== true,
    )
    /* A nested source keeps the box measured at pointer-down; goalCard.css only takes it out of hit-testing, so
       `hitTest` falls through to what is under the pointer. */
    const isNestedDragHole = computed(() => (props.depth > 0 || props.ghost) && isDragSource.value)

    // This card's own nested reorder slot: Column's `isReorderHere`/`renderItems`/`insertionSlot`, scoped to the group
    // this card owns (`slot.parentId === props.id`), with the column's slot markup.
    const dragSlot = computed(() => store.state.drag.slot)
    /* No indicator where the slot is where the source already sits (its next sibling, or the end when it is last), the
       same no-op `reorderWrite` detects: a nested source never collapses, so an indicator there would add a row. */
    const isNestedReorderHere = computed(() => {
      const slot = dragSlot.value
      if (props.ghost || !slot || slot.parentId !== props.id) return false
      const sourceId = store.state.drag.id
      const ownIndex = listKids.value.findIndex((child) => child.id === sourceId)
      if (ownIndex === -1) return true
      const currentNextId = listKids.value[ownIndex + 1]?.id ?? null
      return slot.insertBeforeId !== currentNextId
    })
    /* The slot sits in the column the drag started in: sized off the vacated box (`slotHeight`), not a destination row. */
    const isNestedSourceSlot = computed(() => {
      const slot = dragSlot.value
      if (!isNestedReorderHere.value || !slot) return false
      return store.state.drag.sourceVertical === slot.vertical
        && (store.state.drag.sourcePeriodKey ?? null) === (slot.periodKey ?? null)
    })
    const nestedIndicatorStyle = computed(() => {
      const drag = store.state.drag
      if (isNestedSourceSlot.value) return { height: `${drag.slotHeight}px` }
      return {
        height: `${drag.previewHeight + drag.tailHeight}px`,
        marginLeft: `${drag.slotInsetLeft}px`,
        marginRight: `${drag.slotInsetRight}px`,
      }
    })
    const nestedSourceRowTargetStyle = computed(() => {
      const drag = store.state.drag
      return {
        top: `${drag.slotInsetTop}px`,
        right: `${drag.slotInsetRight}px`,
        bottom: `${drag.slotInsetBottom}px`,
        left: `${drag.slotInsetLeft}px`,
      }
    })

    /** Column's `renderItems`, over this card's own children (`insertBeforeId: null` appends). */
    function renderChildren(): ChildRenderItem[] {
      const items: ChildRenderItem[] = listKids.value.map((goal) => ({ kind: 'goal', key: goal.id, goal }))
      if (!isNestedReorderHere.value) return items
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

    const childrenListEl = ref<HTMLElement | null>(null)
    /* A goal in a window is the window: it doesn't lift, doesn't leave by drag, and lights nothing on the board behind
       it. Its steps carry the same column, so they open with a click and stay. */
    const inWindow = computed(() => props.columnVertical === 'window')
    /* Hover lift: a top-level goal and its subtasks rise as one piece, `lib/cardLift.ts`. */
    const {
      lifted,
      settling: liftSettling,
      cardStyle: liftCardStyle,
      listStyle: liftListStyle,
      enter: liftEnter,
      leave: liftLeave,
      drop: dropLift,
      atRest: liftAtRest,
    } = useCardLift({
      card: rootElement,
      list: childrenListEl,
      enabled: () => props.depth === 0 && !props.ghost && store.state.drag.id === null && !isPathLine.value && !inWindow.value, // a carried plan stays: its box lifts (CarriedGroup)
      // its own menu or a subgoal's hangs from it
      pinned: () => {
        const id = menuGoalId.value
        return id !== null && (id === props.id || (!!store.state.board && subtreeIds(store.state.board, props.id).has(id)))
      },
    })
    watch(() => store.state.drag.id, (id) => { if (id !== null) dropLift() })
    watch(isPathLine, (line) => { if (line) dropLift() }) // a line on top doesn't lift: the family under it would rise with it
    /* One highlight shape per goal: a top-level goal sizes its own and its subgoals' shapes, `lib/goalWash.ts`. */
    useGroupWash({
      card: () => (props.depth === 0 ? rootElement() : null),
      list: childrenListEl,
      layoutSources: [() => props.children, showChildren, () => store.state.openGoalId, () => store.state.openPath, familyKids],
    })

    /** "Add…" at the end of an open goal's steps: the new step lives where its parent does, so it shows at once. */
    function onAddStep(title: string): void {
      void store.addDetailChild(title)
    }
    function onCardEnter(): void {
      if (inWindow.value) return
      highlightFamily()
      liftEnter()
      void store.ensureDetail(props.id) // a click here moves the board from its detail (lib/familyMotion.ts): fetch it ahead
    }
    function onCardLeave(): void { clearFamily(); liftLeave() }
    const nestedInsertionSlot = computed(() => (
      isNestedReorderHere.value
        ? (dragSlot.value?.insertBeforeId ?? null)
        : undefined
    ))
    /* Column's FLIP for `insertionSlot`, over this card's own children, so a nested reorder's neighbours slide. */
    watch(nestedInsertionSlot, async () => {
      if (reducedMotion()) return // the gap simply opens (docs/design/column-bounce.md)
      const selector = ':scope > [data-goal-id]'
      const before = new Map(
        [...(childrenListEl.value?.querySelectorAll<HTMLElement>(selector) ?? [])]
          // A hidden card (a goal's subtasks flying with it) has no place to slide from.
          .filter((element) => element.getClientRects().length > 0)
          .map((element) => [element.dataset.goalId, element.getBoundingClientRect().top]),
      )
      await nextTick()
      for (const element of childrenListEl.value?.querySelectorAll<HTMLElement>(selector) ?? []) {
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

    /* The row is the drag's entry surface, a slot target and the home of every card control, so each pointer handler
       ignores what started on a control. The portalled menu stops its own events; this covers the affordance, title and
       schedule trigger. */
    function fromControl(event: Event): boolean {
      const el = event.target as HTMLElement | null
      return !!el?.closest(
        'button, input, textarea, label, a, [data-role="tag"], .chip, .goal-card__tools, .dropdown',
      )
    }

    /* A press on the row, handed to dnd-kit's sensor (CardDnd.tsx, lib/dndSensor.ts), which arms it: `pointerDownCard`
       remembers where it started and the row's rect. */
    function pressRow(event: PointerEvent): boolean {
      const row = rowEl.value
      if (!row || fromControl(event) || inWindow.value) return false
      row.focus({ preventScroll: true })
      // A drag starts from the board at rest, lifted or not: its row, the gap it leaves, the rows it may land on.
      liftAtRest(() => store.pointerDownCard(
        props.id, event.clientX, event.clientY, row.getBoundingClientRect(), event.pointerType, event.altKey,
      ))
      return true
    }

    /* An armed drag produces no `click`, so open and drop never both fire from one gesture. A plain click opens the
       goal; there is no selection. */
    function onRowClick(event: MouseEvent) {
      if (fromControl(event)) return
      onOpenDetail()
    }

    function onRowKeydown(event: KeyboardEvent) {
      if (!['/', 'Slash', 'Enter', ' '].includes(event.key)) return
      // Slash is the card-level options shortcut even when focus currently sits on a descendant.
      // Enter/Space remain owned by that descendant so native control activation is unchanged.
      if (!['/', 'Slash'].includes(event.key) && fromControl(event)) return
      event.preventDefault()
      if (event.key === 'Enter') startInlineTitleEdit()
      else if (event.key === ' ') onOpenDetail()
      else openContextMenu()
    }

    // Native listeners: a menu teleported out of the card is outside it and its list in the DOM, so its events don't reach
    // them.
    const rowEl = ref<HTMLElement | null>(null)
    listen(cardRoot, 'mouseenter', onCardEnter)
    listen(cardRoot, 'mouseleave', onCardLeave)
    listen(childrenListEl, 'mouseenter', liftEnter)
    listen(childrenListEl, 'mouseleave', liftLeave)
    listen(rowEl, 'pointerdown', (event) => pressToDrag(event, pressRow))

    return {
      checked, blurred, titleParts, filterContext, cardStyle, cardRoot, isParent, onToggle, isInlineDetailHost, isOpenRelated,
      isFocus, isInsideOpen, familyDepth, isPathLine, isDeepestStep, familyLit, lightMove, showChildren, onOpenDetail,
      growList, foldList, onTitleClick, isChainHovered, completionLayer, completionMedia, completionActive, hasMilestone,
      menuOpen, tools, inlineTitleInput, editingInlineTitle, inlineTitleDraft, onInlineTitleInput, commitInlineTitle,
      cancelInlineTitleEdit, onMenuOpenChange, onCardContextMenu, isDragSource, landedHover, isCombineTarget,
      closesSourceGap, isNestedDragHole, isNestedSourceSlot, nestedIndicatorStyle, nestedSourceRowTargetStyle,
      renderChildren, childrenListEl, lifted, liftSettling, liftCardStyle, liftListStyle, onAddStep, onRowClick,
      onRowKeydown, rowEl,
    }
  })

  const { id, color, ghost, depth, repeat, chain, parentId, progress, searchPeriod, searchOpen, contextLabel } = props
  const checked = s.checked.value
  const isInlineDetailHost = s.isInlineDetailHost.value
  const isDragSource = s.isDragSource.value
  const isCombineTarget = s.isCombineTarget.value
  const isPathLine = s.isPathLine.value
  const familyLit = s.familyLit.value
  const filterContext = s.filterContext.value
  const titleParts = s.titleParts.value
  const lifted = s.lifted.value
  const liftSettling = s.liftSettling.value
  const closesSourceGap = s.closesSourceGap.value
  const blurred = s.blurred.value
  const showChildren = s.showChildren.value
  const isNestedSourceSlot = s.isNestedSourceSlot.value
  const css = !familyMovingNow.value

  return (
    <>
      <KCard
        ref={bindRef(s.cardRoot)}
        dense
        className={cx('goal-card', {
          'goal-card--source-gap-closed': closesSourceGap,
          'goal-card--nested-drag-hole': s.isNestedDragHole.value,
          'goal-card--menu-open': s.menuOpen.value,
          'goal-card--landed-hover': s.landedHover.value,
          'goal-card--colored': color,
          'goal-card--done': checked,
          'goal-card--detail-open': isInlineDetailHost,
          'goal-card--open-related': !familyLit && s.isOpenRelated.value && !s.isInsideOpen.value,
          'goal-card--with-subgoals': depth === 0 && showChildren && !isInlineDetailHost,
          'goal-card--focus': s.isFocus.value && depth > 0,
          'goal-card--path-line': isPathLine,
          'goal-card--deepest-step': s.isDeepestStep.value,
          [`goal-card--lit-${familyLit}`]: !!familyLit,
          'goal-card--ancestor-hover': !familyLit && s.isChainHovered.value && !s.isInsideOpen.value,
          'goal-card--lifted': lifted,
          'goal-card--settling': liftSettling,
          'carryover-ghost': ghost,
          'goal-card--private': blurred,
        })}
        data-goal-id={id}
        inert={isPending(id) || undefined}
        data-row-key={[...chain, id].join('/') + (ghost ? '~' : '')}
        data-light={familyLit ?? undefined}
        data-light-move={s.lightMove.value ?? undefined}
        data-filter-context={filterContext ? 'true' : undefined}
        style={sx(s.cardStyle.value, s.liftCardStyle.value)}
        data-parent-id={parentId ?? undefined}
        data-colored={color ? 'true' : 'false'}
        data-ghost={ghost ? 'true' : undefined}
      >
        <div
          ref={bindRef(s.rowEl)}
          className={cx('goal-card__row', {
            'goal-card__row--detail-open': isInlineDetailHost,
            'goal-card__row--drag-source': isDragSource,
            'goal-card__row--combine-target': isCombineTarget,
            'goal-card__row--combine-target-colored': isCombineTarget && color,
          })}
          data-role="drop-target"
          data-cap="reorder"
          role="button"
          tabIndex={0}
          aria-hidden={isDragSource ? 'true' : undefined}
          data-dnd-combine-target={isCombineTarget ? '' : undefined}
          onClick={(event) => s.onRowClick(event.nativeEvent)}
          onContextMenu={(event) => {
            event.stopPropagation()
            s.onCardContextMenu(event.nativeEvent)
          }}
          onKeyDown={(event) => s.onRowKeydown(event.nativeEvent)}
        >
          <span
            className="goal-card__affordance-slot"
            data-role="goal-affordance"
            data-affordance={s.isParent.value ? 'parent' : 'leaf'}
          >
            <GoalAffordance
              kind={s.hasMilestone.value ? 'ring' : 'square'}
              checked={checked}
              done={progress?.done ?? 0}
              total={progress?.total ?? 0}
              color={color}
              onToggle={s.onToggle}
            />
          </span>
          <div className="goal-card__text">
            {!s.editingInlineTitle.value ? (
              <p
                className="goal-card__title"
                data-cap={isInlineDetailHost ? 'edit-title' : undefined}
                onClick={(event) => {
                  event.stopPropagation()
                  // caretAt reads `currentTarget`, the title: the React event has it, its nativeEvent does not.
                  s.onTitleClick(event as unknown as MouseEvent)
                }}
              >
                <span className={cx('goal-card__title-text', {
                  'goal-card__title-text--repeat': repeat,
                  'goal-card__title-text--context': filterContext,
                  'goal-card__title-text--finding': titleParts.some((part) => part.match) || filterContext,
                })}>
                  {repeat ? <RepeatMark /> : null}
                  {titleParts.map((part, index) => (
                    <Fragment key={index}>{part.match ? <strong>{part.text}</strong> : part.text}</Fragment>
                  ))}
                </span>
              </p>
            ) : (
              <textarea
                {...valueOf(s.inlineTitleDraft.value, (event) => s.onInlineTitleInput(event.nativeEvent), s.inlineTitleInput)}
                className="goal-card__title goal-card__title-input"
                data-cap={isInlineDetailHost ? 'edit-title' : undefined}
                rows={1}
                onClick={(event) => event.stopPropagation()}
                onPointerDown={(event) => event.stopPropagation()}
                onKeyDown={(event) => {
                  if (event.key === 'Enter') {
                    event.preventDefault()
                    event.stopPropagation()
                    s.commitInlineTitle()
                  } else if (event.key === 'Escape') {
                    event.preventDefault()
                    event.stopPropagation()
                    s.cancelInlineTitleEdit()
                  }
                }}
              />
            )}
            {searchPeriod !== undefined ? (
              <p data-role="search-period" className="goal-card__meta">{searchPeriod}</p>
            ) : null}
            {searchOpen ? (
              <button
                type="button"
                data-role="search-open"
                className="goal-card__search-open"
                onClick={(event) => {
                  event.stopPropagation()
                  s.onOpenDetail()
                }}
              >Open</button>
            ) : null}
            {contextLabel ? <p className="goal-card__meta">{contextLabel}</p> : null}
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
        {showChildren ? (
          <div
            ref={bindRef(s.childrenListEl)}
            className={cx('goal-card__children subgoal-recursive-list', {
              'goal-card__children--lifted': lifted,
              'goal-card__children--settling': liftSettling,
              'goal-card__children--drag-source': isDragSource,
              'goal-card__children--gap-closed': closesSourceGap,
              'goal-card__children--open': isInlineDetailHost,
              'goal-card__children--path': isPathLine && depth > 0,
              'goal-card__children--family': isPathLine || (isInlineDetailHost && s.familyDepth.value >= 0),
              'goal-card__children--private': blurred,
            })}
            data-open-region={isInlineDetailHost ? '' : undefined}
            style={sx(s.cardStyle.value, { '--subgoal-depth': String(depth) }, s.liftListStyle.value)}
          >
            {s.completionActive.value ? (
              <div
                ref={bindRef(s.completionLayer)}
                className="goal-card__completion"
                data-role="completion-animation"
              >
                <svg
                  ref={bindRef(s.completionMedia)}
                  viewBox={`0 0 ${COMPLETION_LOTTIE.width} ${COMPLETION_LOTTIE.height}`}
                  preserveAspectRatio="xMidYMid slice"
                  data-format="lottie"
                  data-width={COMPLETION_LOTTIE.width}
                  data-height={COMPLETION_LOTTIE.height}
                  data-frame-rate={COMPLETION_LOTTIE.frameRate}
                  data-first-frame={COMPLETION_LOTTIE.firstFrame}
                  data-last-frame={COMPLETION_LOTTIE.lastFrame}
                  data-loop="false"
                  data-autoplay="true"
                  aria-hidden="true"
                >
                  <g className="goal-card__completion-rays">
                    <path d="M1000 100 1000 500M1000 1500 1000 1900M100 1000 500 1000M1500 1000 1900 1000" />
                    <path d="m360 360 285 285m710 710 285 285m0-1280-285 285m-710 710-285 285" />
                  </g>
                  <circle cx="1000" cy="1000" r="270" />
                </svg>
              </div>
            ) : null}
            {s.renderChildren().map((item) => (
              item.kind === 'slot' ? (
                // The column's slot markup: a nested group's own reorder slot (append included) shows the same indicator.
                <div
                  key={item.key}
                  className="pattern-vertical-board__drop-indicator"
                  data-role={item.settling ? 'drop-destination' : 'drop-indicator'}
                  data-dnd-placeholder={item.settling ? undefined : ''}
                  data-dnd-destination={item.settling ? '' : undefined}
                  data-box={isNestedSourceSlot ? 'card' : 'row'}
                  data-tail={store.state.drag.tailHeight || undefined}
                  aria-hidden="true"
                  style={sx(s.nestedIndicatorStyle.value)}
                >
                  {isNestedSourceSlot ? (
                    <div
                      className="pattern-vertical-board__drop-row-target"
                      data-role="drop-row-target"
                      style={sx(s.nestedSourceRowTargetStyle.value)}
                    />
                  ) : null}
                </div>
              ) : (
                <GoalCard
                  key={item.key}
                  id={item.goal.id}
                  parentId={item.goal.parentId}
                  title={item.goal.title}
                  done={item.goal.done}
                  color={item.goal.color}
                  contextLabel={item.goal.contextLabel}
                  vertical={item.goal.vertical}
                  columnVertical={props.columnVertical}
                  foil={item.goal.foil}
                  ghost={item.goal.ghost}
                  progress={item.goal.progress}
                  subgoalCount={item.goal.subgoalCount}
                  children={item.goal.children}
                  depth={depth + 1}
                  chain={[...chain, id]}
                />
              )
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
