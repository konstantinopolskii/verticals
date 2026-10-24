/* A goal card's title (components/GoalCard.tsx): its words with the filter's matches in bold and the repeat mark, or,
   while it is edited in place (lib/inlineTitleEdit.ts), the field they are edited in. */
import { Fragment, type FormEvent, type KeyboardEvent, type MouseEvent, type SyntheticEvent } from 'react'
import { computed, type Ref } from '../reactivity'
import { RepeatMark } from './RepeatMark'
import { cx, valueOf } from '../bind'
import { tracked } from '../tracked'
import { useSetup } from '../setup'

interface Props {
  parts: { text: string; match: boolean }[]
  repeat: boolean
  /** The goal stands in the filter's results for one of its steps. */
  context: boolean
  /** The goal is open, and its title is edited where it stands. */
  editable: boolean
  editing: boolean
  draft: string
  input: Ref<HTMLTextAreaElement | null>
  /** A click on the words: `caretAt` reads where it landed from the event's `currentTarget`, the title. */
  onPress: (event: globalThis.MouseEvent) => void
  onInput: (event: Event) => void
  onCommit: () => void
  onCancel: () => void
}

function stop(event: SyntheticEvent): void {
  event.stopPropagation()
}

export const GoalTitle = tracked(function GoalTitle(raw: Props) {
  const { parts, repeat, context, editable, editing, draft, input } = raw
  const s = useSetup(raw, (props) => {
    const finding = computed(() => props.context || props.parts.some((part) => part.match))

    function onPress(event: MouseEvent): void {
      event.stopPropagation()
      props.onPress(event as unknown as globalThis.MouseEvent)
    }
    function onInput(event: FormEvent): void {
      props.onInput(event.nativeEvent)
    }
    function onKeyDown(event: KeyboardEvent): void {
      if (event.nativeEvent.isComposing || event.nativeEvent.keyCode === 229) return
      if (event.key !== 'Enter' && event.key !== 'Escape') return
      event.preventDefault()
      event.stopPropagation()
      if (event.key === 'Enter') props.onCommit()
      else props.onCancel()
    }
    return { finding, onPress, onInput, onKeyDown }
  })

  const cap = editable ? 'edit-title' : undefined
  if (editing) {
    return (
      <textarea
        {...valueOf(draft, s.onInput, input)}
        className="goal-card__title goal-card__title-input"
        data-cap={cap}
        rows={1}
        onClick={stop}
        onPointerDown={stop}
        onKeyDown={s.onKeyDown}
      />
    )
  }
  return (
    <p className="goal-card__title" data-cap={cap} onClick={s.onPress}>
      <span className={cx('goal-card__title-text', {
        'goal-card__title-text--repeat': repeat,
        'goal-card__title-text--context': context,
        'goal-card__title-text--finding': s.finding.value,
      })}>
        {repeat ? <RepeatMark /> : null}
        {parts.map((part, index) => (
          <Fragment key={index}>{part.match ? <strong>{part.text}</strong> : part.text}</Fragment>
        ))}
      </span>
    </p>
  )
})
