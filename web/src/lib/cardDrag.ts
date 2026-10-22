/* A goal card in the drag (components/GoalCard.tsx): the card in the hand, the card it may join, and the slot among
   its own subgoals (lib/reorderSlot.ts). */
import { computed, onBeforeUnmount, ref, watch, type ComputedRef, type Ref } from '../reactivity'
import { store } from '../store'
import type { GoalCardData } from '../types'
import { slideGoals } from './reorderSlot'

interface Card {
  id: string
  depth: number
  ghost: boolean
}

/** Inside useSetup. `kids` are the subgoals the card lists, `list` the element it lists them in. */
export function useCardDrag(card: Card, root: () => HTMLElement | null, kids: ComputedRef<GoalCardData[]>, list: Ref<HTMLElement | null>) {
  /* The row keeps its DOM identity while inline detail is open; drag state may hide that same row for a while. */
  const isDragSource = computed(() => store.state.drag.id === card.id || store.state.drag.settling?.id === card.id)
  /* The flying copy was cloned hovered; the browser re-hovers the landed card only on the next pointer move, so hold
     the hover look until then. */
  const landedHover = ref(false)
  function releaseLandedHover(): void {
    landedHover.value = false
    window.removeEventListener('pointermove', releaseLandedHover)
  }
  watch(isDragSource, (now, was) => {
    if (now || !was) return
    const box = root()?.getBoundingClientRect()
    const { x, y } = store.state.drag
    if (!box || x < box.left || x > box.right || y < box.top || y > box.bottom) return
    landedHover.value = true
    window.addEventListener('pointermove', releaseLandedHover)
  }, { flush: 'post' })
  onBeforeUnmount(releaseLandedHover)

  const isCombineTarget = computed(() => store.state.drag.id !== null
    && store.state.drag.target?.kind === 'combine'
    && store.state.drag.target.targetId === card.id)
  /* Only a top-level source collapses: the column's own placeholder holds its box elsewhere. A nested one keeps its
     box (`isNestedDragHole`), or its parent would snap shut when the drag arms. */
  const closesSourceGap = computed(() => card.depth === 0 && !card.ghost && isDragSource.value
    && store.state.drag.settling?.cancelled !== true)
  /* A nested source keeps the box measured at pointer-down; goalCard.css only takes it out of hit-testing, so
     `hitTest` falls through to what is under the pointer. */
  const isNestedDragHole = computed(() => (card.depth > 0 || card.ghost) && isDragSource.value)

  /* The slot among this card's own subgoals (`slot.parentId === card.id`). No slot where the source already sits (its
     next sibling, or the end when it is last), the same no-op `reorderWrite` detects: a nested source never collapses,
     so a slot there would add a row. */
  const slotHere = computed(() => {
    const slot = store.state.drag.slot
    if (card.ghost || !slot || slot.parentId !== card.id) return false
    const ownIndex = kids.value.findIndex((child) => child.id === store.state.drag.id)
    if (ownIndex === -1) return true
    return slot.insertBeforeId !== (kids.value[ownIndex + 1]?.id ?? null)
  })
  /* The slot sits in the column the drag started in: sized off the vacated box (`slotHeight`), not a destination row. */
  const sourceSlot = computed(() => {
    const slot = store.state.drag.slot
    return slotHere.value && !!slot && store.state.drag.sourceVertical === slot.vertical
      && (store.state.drag.sourcePeriodKey ?? null) === (slot.periodKey ?? null)
  })
  /* The subgoals slide as the slot moves among them. */
  const insertionSlot = computed(() => (slotHere.value ? (store.state.drag.slot?.insertBeforeId ?? null) : undefined))
  watch(insertionSlot, () => slideGoals(() => list.value, ':scope > [data-goal-id]'))

  return { isDragSource, landedHover, isCombineTarget, closesSourceGap, isNestedDragHole, slotHere, sourceSlot }
}
