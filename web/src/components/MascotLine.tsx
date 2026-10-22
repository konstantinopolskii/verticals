/* The mascot's line on its pivot: the field's (SearchBar), moved by lib/fieldMascot.ts, and a working task's (SessionMark),
   always turning. */
import type { Ref } from '../reactivity'
import { bindRef, cx, sx } from '../bind'
import { tracked } from '../tracked'

interface Props {
  pivot?: Ref<HTMLElement | null>
  line?: Ref<HTMLElement | null>
  turning?: boolean
  stopping?: boolean
  blinking?: boolean
  hidden?: boolean
  /** How far the pivot stands from the centre, in px. */
  shift?: number
}

export const MascotLine = tracked(function MascotLine({ pivot, line, turning, stopping, blinking, hidden, shift }: Props) {
  const translate = shift === undefined ? undefined : `${shift}px 0`
  return (
    <span
      ref={pivot ? bindRef(pivot) : undefined}
      className={cx('circle-field__pivot', { 'is-turning': turning, 'is-stopping': stopping })}
      style={sx({ translate })}
    >
      <span
        ref={line ? bindRef(line) : undefined}
        className={cx('circle-field__line', { 'is-blinking': blinking, 'is-hidden': hidden })}
        aria-hidden="true"
      ></span>
    </span>
  )
})
