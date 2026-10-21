/* The three pills beside a carried plan (docs/design/carried-pills.md): "This week" (the column's own period), "To Inbox"
   and "Delete", white on the box's lit colour, drawn in <body> over the next column. What they do, where they stand and
   when they show is `lib/carriedPills.ts`. They are the pointer's quick way; the card's menu does the same by keyboard. */
import type { MouseEvent as ReactMouseEvent } from 'react'
import { Teleport } from '../Teleport'
import type { CarriedPillsApi } from '../lib/carriedPills'
import { bindRef, cx, sx } from '../bind'
import { tracked } from '../tracked'
import { listen, useSetup } from '../setup'
import './carriedPills.css'

/** A press leaves the focus where it was: ⌘Z and the keys stay the board's. */
const keepFocus = (event: ReactMouseEvent): void => event.preventDefault()

export const CarriedPills = tracked(function CarriedPills({ api }: { api: CarriedPillsApi }) {
  useSetup({ api }, (props) => {
    listen(props.api.el, 'pointerenter', props.api.onEnter)
    listen(props.api.el, 'mouseenter', props.api.onMouseEnter)
    listen(props.api.el, 'pointerleave', props.api.onLeave)
    return {}
  })
  const on = api.shown.value
  const tone = api.tone.value
  return (
    <Teleport to="body">
      <div
        ref={bindRef(api.el)}
        className={cx('carried-pills', { 'carried-pills--on': on, 'carried-pills--lit': !!tone })}
        data-role="carried-pills"
        data-column={api.column()}
        data-for={on && !api.waiting.value ? api.target.value ?? undefined : undefined}
        aria-hidden={on ? undefined : 'true'}
        style={sx(tone ?? {})}
      >
        <div className="carried-pills__set" role="group" aria-label="Sort this plan">
          <button type="button" className="carried-pills__pill" data-pill="keep" tabIndex={-1} onMouseDown={keepFocus}
            onClick={api.keep}>{api.keepLabel.value}</button>
          <button type="button" className="carried-pills__pill" data-pill="inbox" tabIndex={-1} onMouseDown={keepFocus}
            onClick={api.inbox}>To Inbox</button>
          <button type="button" className="carried-pills__pill carried-pills__pill--danger" data-pill="delete" tabIndex={-1}
            onMouseDown={keepFocus} onClick={api.remove}>Delete</button>
        </div>
      </div>
    </Teleport>
  )
})
