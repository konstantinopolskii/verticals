/* The drag's slot in a list of goals (lib/reorderSlot.ts): a row-sized gap where the goal will land, or, in the column
   the drag started in, the box the goal left with the row inside it it can land back on. */
import { computed } from '../reactivity'
import { store } from '../store'
import { sx } from '../bind'
import { tracked } from '../tracked'
import { useSetup } from '../setup'

interface Props {
  /** The goal has been let go and is landing here. */
  settling: boolean
  /** The slot is in the list the drag started from. */
  source: boolean
}

export const DropSlot = tracked(function DropSlot({ settling, source }: Props) {
  const s = useSetup({ source }, (props) => {
    const style = computed(() => {
      const drag = store.state.drag
      if (props.source) return { height: `${drag.slotHeight}px` }
      return {
        height: `${drag.previewHeight + drag.tailHeight}px`,
        marginLeft: `${drag.slotInsetLeft}px`,
        marginRight: `${drag.slotInsetRight}px`,
      }
    })
    const rowStyle = computed(() => {
      const drag = store.state.drag
      return {
        top: `${drag.slotInsetTop}px`,
        right: `${drag.slotInsetRight}px`,
        bottom: `${drag.slotInsetBottom}px`,
        left: `${drag.slotInsetLeft}px`,
      }
    })
    return { style, rowStyle }
  })
  return (
    <div
      className="pattern-vertical-board__drop-indicator"
      data-role={settling ? 'drop-destination' : 'drop-indicator'}
      data-dnd-placeholder={settling ? undefined : ''}
      data-dnd-destination={settling ? '' : undefined}
      data-box={source ? 'card' : 'row'}
      data-tail={store.state.drag.tailHeight || undefined}
      aria-hidden="true"
      style={sx(s.style.value)}
    >
      {source ? <div className="pattern-vertical-board__drop-row-target" data-role="drop-row-target" style={sx(s.rowStyle.value)} /> : null}
    </div>
  )
})
