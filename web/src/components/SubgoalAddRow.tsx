/* "Add..." under an open goal's steps: a row that turns into a field, the checkbox
   staying while the step is typed. One root for both states, so the open goal's <Transition> plays the row coming and
   going, not the switch to typing. */
import { keyboardHelpOpen } from '../lib/keyboard'
import type { KeyboardEvent, Ref as ReactRef } from 'react'
import { nextTick, ref, type Ref } from '../reactivity'
import { fallthrough, model } from '../bind'
import { tracked } from '../tracked'
import { exposeTo, listen, useSetup, withDefaults } from '../setup'
import './subgoalAddRow.css'

export interface SubgoalAddRowApi {
  openEditor(): void
}

interface Props {
  commitOnEnter?: boolean
  showTrigger?: boolean
  onCommit?: (title: string) => void
  expose?: Ref<SubgoalAddRowApi | null>
  ref?: ReactRef<HTMLDivElement>
  className?: string
}
const DEFAULTS = { commitOnEnter: false, showTrigger: true }

export const SubgoalAddRow = tracked(function SubgoalAddRow(raw: Props) {
  const { commitOnEnter, showTrigger, onCommit, expose, ...attrs } = withDefaults(raw, DEFAULTS)
  const s = useSetup({ commitOnEnter, showTrigger, onCommit, expose }, (props) => {
    const editing = ref(false)
    const draft = ref('')
    const editor = ref<HTMLTextAreaElement | null>(null)

    function openEditor() {
      editing.value = true
      void nextTick(() => editor.value?.focus())
    }
    function cancelEditor() {
      draft.value = ''
      editing.value = false
    }
    function onBlur() {
      if (keyboardHelpOpen.value) return
      if (!draft.value.trim()) cancelEditor()
    }
    listen(editor, 'blur', onBlur)
    function onEnter() {
      if (!props.commitOnEnter) return
      const title = draft.value.trim()
      if (!title) return
      props.onCommit?.(title)
      cancelEditor()
    }
    exposeTo(props.expose, { openEditor })
    return { editing, draft, editor, openEditor, cancelEditor, onBlur, onEnter }
  })

  function onEditorKey(event: KeyboardEvent) {
    if (event.key === 'Enter') {
      event.preventDefault()
      s.onEnter()
    } else if (event.key === 'Escape') {
      event.stopPropagation()
      event.preventDefault()
      s.cancelEditor()
    }
  }
  function onTriggerKey(event: KeyboardEvent) {
    if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault()
      s.openEditor()
    }
  }
  const checkbox = (
    <label className="checkbox checkbox--size-s subgoal-add-row__checkbox" aria-hidden="true">
      <input className="checkbox__input" type="checkbox" disabled />
      <span className="checkbox__box"></span>
    </label>
  )
  return (
    <div {...fallthrough({ className: 'subgoal-add' }, attrs)}>
      {s.editing.value ? (
        <div className="subgoal-add-editor-shell">
          {checkbox}
          <textarea
            {...model(s.draft, s.editor)}
            data-role="subgoal-add-editor"
            className="subgoal-add-editor"
            rows={1}
            aria-label="Add subgoal"
            placeholder="Subtask"
            onKeyDown={onEditorKey}
          />
        </div>
      ) : showTrigger ? (
        <div data-role="subgoal-add" className="subgoal-add-row" role="button" tabIndex={0} onClick={s.openEditor} onKeyDown={onTriggerKey}>
          {checkbox}
          <span className="subgoal-add-row__text">Add...</span>
        </div>
      ) : null}
    </div>
  )
})
