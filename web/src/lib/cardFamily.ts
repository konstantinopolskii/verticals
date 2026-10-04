// A goal card's place in the open goal's family: whether it is the open goal here, a level stepped through, a step or a
// relative lit further off; which steps it lists; what a click on it opens; how its list grows and folds. The card side
// of flow 4 (going deeper) and of the opened goal it builds on; the board side is `familyView.ts`. Lifted out of
// `GoalCard.vue` when flow 4 took it past the 750-line module cap (ARCHITECTURE.md S-90a), in the shape of
// `inlineTitleEdit.ts`: the component keeps its template bindings, this module owns the logic behind them.

import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { store } from '../store'
import type { GoalCardData } from '../types'
import { DEEPEST } from './familyView'
import { familyMoving } from './familyMotion'
import { curve, reducedMotion } from './motion'
import { finishLightMove } from './lightMotion'

export function useCardFamily(props: {
  readonly id: string
  readonly parentId: string | null
  readonly depth: number
  readonly columnVertical: string | null
  readonly chain: string[]
  readonly children: GoalCardData[]
}, rootElement: () => HTMLElement | null) {
  onBeforeUnmount(() => {
    // Scheduling, parking, or moving an expanded card may remove this rendered host before its
    // inline close animation can run. Never leave the board pinned to an owner that no longer exists.
    if (isInlineDetailHost.value) store.closeGoal()
  })

  const detailHostKey = computed(() => [
    props.columnVertical ?? 'global', props.parentId ?? 'root', props.depth, props.id,
  ].join(':'))
  const isInlineDetailHost = computed(() => (
    (store.state.activeView === 'verticals' || store.state.activeView === 'inbox')
    && store.state.openGoalHostKey === detailHostKey.value
    && store.state.openGoalVertical === props.columnVertical
  ))
  const isOpenRelated = computed(() => {
    const related = store.openRelatives.value
    return !!related && (related.ancestors.has(props.id) || related.subtree.has(props.id))
  })
  /* The wide column shows two levels, and opening goes down in place (KK, 27 Sep 2026, the cleaned-up card: "I love
     it. Let's implement"; he had called hiding the siblings mind-blowing). An opened subgoal takes the top-level size
     where it stands, its siblings stay, and its own subgoals show inside its card. One level deeper works the same:
     every card on the way down to the open goal keeps its subgoals in view, and a list below the first level steps in
     by one checkbox (round two's pick, option A). Narrow columns keep KK's earlier rule (overriding D253): two levels,
     and an opened goal's relatives in full. */
  const inWideColumn = computed(() => (
    store.state.activeView === 'verticals' && !!props.columnVertical && store.state.expandedVertical === props.columnVertical
  ))
  const openInColumn = computed(() => (
    inWideColumn.value && store.state.openGoalVertical === props.columnVertical ? store.state.openGoalId : null
  ))
  const isFocus = computed(() => openInColumn.value === props.id && isInlineDetailHost.value)
  /** The open goal's own subgoals here in its column: they sit inside its card, on its colour, so they take no colour
   *  of their own as its relatives. */
  const isInsideOpen = computed(() => {
    const related = store.openRelatives.value
    return !!related && related.id !== props.id && store.state.openGoalVertical === props.columnVertical
      && related.subtree.has(props.id)
  })
  /* Flow 4, one edge in the wide column: the levels stepped through are step-size lines on top, the open goal is the one
     big card, its siblings stand under it and the siblings of the level above under them (`lib/familyView.ts`). A goal
     drawn there knows its level by the chain it is drawn under: the open path's first levels. */
  const familyDepth = computed(() => {
    const path = store.state.openPath
    if (!inWideColumn.value || !path.length || store.state.openGoalVertical !== props.columnVertical) return -1
    const d = props.chain.length
    if (d > path.length || props.chain.some((id, i) => id !== path[i])) return -1
    return d === 0 && path[0] !== props.id ? -1 : d
  })
  /** A level stepped through: a line on top, its steps under it with the next level first. */
  const isPathLine = computed(() => (
    familyDepth.value >= 0 && familyDepth.value < store.state.openPath.length - 1
    && store.state.openPath[familyDepth.value] === props.id
  ))
  /** A step of the deepest card: two levels in is the deepest, so it doesn't open (KK, 28 Sep 2026). */
  const isDeepestStep = computed(() => familyDepth.value >= DEEPEST)
  /** The steps a line on top or the open card lists are the ones in this column, as the column lists them (KK, 29 Sep
   *  2026: "We show inside only those who are on the same vertical column"); the others light up where they are. A line
   *  on top lists the next level first. */
  const familyKids = computed<GoalCardData[] | null>(() => {
    if (!isPathLine.value) return null
    const next = store.state.openPath[familyDepth.value + 1]
    return [...props.children.filter((k) => k.id === next), ...props.children.filter((k) => k.id !== next)]
  })
  const listKids = computed(() => familyKids.value ?? props.children)
  /** The open family's light on this goal (`lib/familyView.ts`); null while nothing is open, and for a goal turned off,
   *  which the board's veil covers: opening a goal re-renders its family, not the whole board. */
  const familyLit = computed(() => store.familyLight.value?.get(props.id) ?? null)
  /* The light swapping under the pointer (a goal open, the hand resting on one outside its family, and back) moves this
     goal in or out of it through the veil's own look, in the swap's time, instead of across the veil in one frame (KK,
     4 Oct 2026, a recording: the board flipped from one family to the other and back on every hover). Only the goals
     that change move: the veil itself, which the opening fades as one layer, stays one layer (goalCard.css). */
  const lightMove = ref<'in' | 'out' | null>(null)
  let lightMoveToken = 0
  watch(familyLit, (now, was) => {
    if (!store.state.lightFast || !now === !was) return
    lightMove.value = now ? 'in' : 'out'
    const token = ++lightMoveToken
    finishLightMove(rootElement(), () => { if (token === lightMoveToken) lightMove.value = null })
  })
  onBeforeUnmount(() => { lightMoveToken++ })
  /* An open goal always has a list: its steps end with "Add…", and its notes follow them inside the same piece. */
  const showChildren = computed(() => isInlineDetailHost.value || isPathLine.value || (listKids.value.length > 0 && (
    inWideColumn.value
      ? (props.depth < 1 && familyDepth.value < 0) || isFocus.value
      : props.depth < 1 || isOpenRelated.value
  )))

  function onOpenDetail() {
    // Board cards route through `openBoardGoal`, which expands the card's column first (KK ruling
    // 2026-08-17: card click = expand + open in one gesture). Non-board contexts (search results,
    // inbox) keep the direct open unchanged.
    if (props.columnVertical && props.columnVertical !== 'maybe' && store.state.activeView === 'verticals') {
      // Flow 4: a click opens the chain the goal is drawn under plus itself: a step in the card goes one level in, a
      // sibling sideways, a line on top back to its level. Inside the family the lines stay where they are, so only a
      // goal opened afresh holds its place while its column widens.
      if (isDeepestStep.value) return
      const hold = inWideColumn.value ? null : holdPlace()
      void store.openFamily([...props.chain, props.id], props.columnVertical)
      if (hold) void nextTick(hold)
      return
    }
    void store.openGoal(props.id, props.columnVertical, detailHostKey.value)
  }

  /** Opening a goal starts from where it was clicked: a goal open above it closes, or its column widens and the cards
   *  above it grow, and either would throw it away from under the pointer in one frame (404 px down, low in Week). Returns
   *  the step to run once it has opened; from there `GoalDetail.vue` scrolls it into view. */
  function holdPlace(): (() => void) | null {
    const card = rootElement()
    let scroller = card?.parentElement ?? null
    while (scroller && !/auto|scroll/.test(getComputedStyle(scroller).overflowY)) scroller = scroller.parentElement
    if (!card || !scroller) return null
    const before = card.getBoundingClientRect().top
    return () => {
      if (familyMoving()) return // the move that opens it holds it, inside its own movement (lib/familyMotion.ts)
      const now = rootElement()
      if (now && scroller) scroller.scrollTop += now.getBoundingClientRect().top - before
    }
  }

  /* A list that comes or goes with an opening (an opened subgoal's steps, the way down to a deeper open goal, the steps of
     a goal that had none) grows from nothing and folds away in the opening's time and curve, so the goals below slide
     rather than leap: closing an opened subgoal used to drop its steps and notes in one frame, 460 px (the motion
     trace, 27 Sep 2026). Growing, it aims at its height once its notes have opened too. */
  const opening = () => ({ duration: 360, easing: curve('large') })
  const stillMotion = () => reducedMotion() || familyMoving()
  function growList(el: Element, done: () => void): void {
    const list = el as HTMLElement
    if (stillMotion()) { done(); return }
    // Shut for one frame, until the notes are written into it: then its full height is known.
    list.style.height = '0px'
    list.style.overflow = 'hidden'
    requestAnimationFrame(() => {
      const clip = list.querySelector<HTMLElement>('.goal-detail-inline__clip')
      const notes = clip ? Math.max(0, clip.scrollHeight - clip.getBoundingClientRect().height) : 0
      const to = list.scrollHeight + notes
      list.style.height = ''
      list.animate([{ height: '0px', opacity: 0 }, { height: `${to}px`, opacity: 1 }], opening()).onfinish = () => {
        list.style.overflow = ''
        done()
      }
    })
  }
  function foldList(el: Element, done: () => void): void {
    const list = el as HTMLElement
    if (stillMotion()) { done(); return }
    list.style.overflow = 'hidden'
    list.animate([{ height: `${list.getBoundingClientRect().height}px`, opacity: 1 }, { height: '0px', opacity: 0 }], opening()).onfinish = done
  }

  return {
    isInlineDetailHost, isOpenRelated, inWideColumn, isFocus, isInsideOpen, familyDepth, isPathLine, isDeepestStep,
    familyKids, listKids, familyLit, lightMove, showChildren, onOpenDetail, growList, foldList,
  }
}
