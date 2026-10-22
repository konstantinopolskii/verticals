/* The words of the field: the textarea you type into, its mirror the caret is measured in, and the caption while it is
   empty, the one that was there blurring out as the new one comes in. */
import { useLayoutEffect } from 'react'
import { ref, watch, type Ref } from '../reactivity'
import { commandFilter } from '../lib/commandFilter'
import { circle, circleCaption } from '../lib/circle'
import { LINE } from '../lib/fieldSize'
import { bindRef, sx } from '../bind'
import { tracked } from '../tracked'
import { useSetup } from '../setup'

interface Props {
  input: Ref<HTMLTextAreaElement | null>
  mirror: Ref<HTMLElement | null>
  /** The lines shown, and whether the words run past them. */
  lines: number
  scrolls: boolean
  onMoved: () => void
  onScroll: () => void
}

export const FieldInput = tracked(function FieldInput({ input, mirror, lines, scrolls, onMoved, onScroll }: Props) {
  const s = useSetup({ onMoved }, (props) => {
    const leaving = ref<string | null>(null)
    watch(circleCaption, (_, old) => { leaving.value = old ?? null })
    watch(() => commandFilter.text, (words) => { if (words) leaving.value = null })

    function moved(): void { props.onMoved() }
    function onFocus(): void {
      circle.focused = true
      props.onMoved()
    }
    function onBlur(): void { circle.focused = false }
    function onLeft(): void { leaving.value = null }
    return { leaving, moved, onFocus, onBlur, onLeft }
  })

  const text = commandFilter.text
  // The field's value is the element's property, put back after each drawing where it differs. A controlled React
  // textarea would also write the words into its text content.
  useLayoutEffect(() => {
    const el = input.value
    if (el && el.value !== text) el.value = text
  })

  const caption = circleCaption.value
  const leaving = text ? null : s.leaving.value
  return (
    <div className="circle-field__words" data-cap="search-input">
      <textarea
        ref={bindRef(input)}
        rows={1}
        aria-label={caption}
        autoComplete="off"
        spellCheck="false"
        style={sx({ height: `${lines * LINE}px`, overflowY: scrolls ? 'auto' : 'hidden' })}
        onKeyUp={s.moved}
        onPointerUp={s.moved}
        onScroll={onScroll}
        onFocus={s.onFocus}
        onBlur={s.onBlur}
      ></textarea>
      <div ref={bindRef(mirror)} className="circle-field__mirror" aria-hidden="true"></div>
      {leaving ? (
        <span key={`out:${leaving}`} className="circle-field__caption circle-field__caption--out" aria-hidden="true"
          onAnimationEnd={s.onLeft}>{leaving}</span>
      ) : null}
      {!text ? <span key={caption} className="circle-field__caption" aria-hidden="true">{caption}</span> : null}
    </div>
  )
})
