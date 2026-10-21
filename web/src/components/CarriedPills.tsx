/* The capsule over a carried plan (docs/design/carried-pills.md; the owner's sketch, 21 Oct 2026): "Keep · Idk · Fuck it",
   the owner's own words, in the plan's light and its title's type, drawn in <body> just above the plan. What each does,
   where it stands and when it shows is `lib/carriedPills.ts`. It is the pointer's quick way, with 1, 2 and 3; the card's
   menu does the same by keyboard. */
import type { MouseEvent as ReactMouseEvent } from 'react'
import { Teleport } from '../Teleport'
import type { CarriedPillsApi } from '../lib/carriedPills'
import { bindRef, cx } from '../bind'
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
  return (
    <Teleport to="body">
      <div
        ref={bindRef(api.el)}
        className={cx('carried-pills', { 'carried-pills--on': on })}
        data-role="carried-pills"
        data-column={api.column()}
        data-for={on && !api.waiting.value ? api.target.value ?? undefined : undefined}
        aria-hidden={on ? undefined : 'true'}
      >
        <div className="carried-pills__set" role="group" aria-label="Sort this plan">
          <button type="button" className="carried-pills__word" data-pill="keep" aria-label="Keep it in this period" tabIndex={-1}
            onMouseDown={keepFocus} onClick={api.keep}>Keep</button>
          <button type="button" className="carried-pills__word" data-pill="idk" aria-label="To the Inbox, to realign" tabIndex={-1}
            onMouseDown={keepFocus} onClick={api.idk}>Idk</button>
          <button type="button" className="carried-pills__word" data-pill="delete" aria-label="Delete" tabIndex={-1}
            onMouseDown={keepFocus} onClick={api.remove}>Fuck it</button>
        </div>
      </div>
    </Teleport>
  )
})
