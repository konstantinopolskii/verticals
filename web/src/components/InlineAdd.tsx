/* The product's add row: at rest the board's disabled-checkbox row; activated, the row
   turns in place into the one-input create path. One input, no required selects, and a committed title goes up as `add`
   (the goal's real id comes back from the server, never from here). */
import { keyboardHelpOpen } from '../lib/keyboard'
import type { KeyboardEvent } from 'react'
import { nextTick, ref } from '../reactivity'
import { fallthrough, model } from '../bind'
import { tracked } from '../tracked'
import { listen, useSetup, withDefaults } from '../setup'
import './inlineAdd.css'

interface Props {
  placeholder?: string
  onAdd?: (title: string) => void
}
const DEFAULTS = { placeholder: 'Add…' }

export const InlineAdd = tracked(function InlineAdd(raw: Props & Record<string, unknown>) {
  const { placeholder, onAdd, ...attrs } = withDefaults(raw, DEFAULTS)
  const s = useSetup({ placeholder, onAdd }, (props) => {
    const editing = ref(false)
    const draft = ref('')
    const editor = ref<HTMLInputElement | null>(null)

    function openEditor() {
      editing.value = true
      void nextTick(() => editor.value?.focus())
    }
    function cancelEditor() {
      draft.value = ''
      editing.value = false
    }
    function commit() {
      const title = draft.value.trim()
      if (!title) return
      props.onAdd?.(title)
      cancelEditor()
    }
    function onBlur() {
      if (keyboardHelpOpen.value) return
      if (!draft.value.trim()) cancelEditor()
    }
    listen(editor, 'blur', onBlur)
    return { editing, draft, editor, openEditor, cancelEditor, commit, onBlur }
  })

  // Keys on the row itself open the field. An Enter that commits in the field stays there: the field closes, and ⌘Z
  // right after takes the new goal back instead of going to an empty field.
  function onRowKey(event: KeyboardEvent<HTMLDivElement>) {
    if (event.target !== event.currentTarget) return
    if (event.key !== 'Enter' && event.key !== ' ') return
    event.preventDefault()
    if (!s.editing.value) s.openEditor()
  }
  /* The keys come back to the Add row the field closes into, so Enter, N or an arrow carries on from there. */
  function backToRow(event: KeyboardEvent<HTMLInputElement>) {
    const input = event.currentTarget
    const row = input.closest<HTMLElement>('[data-role="column-add"]')
    void nextTick(() => {
      const now = document.activeElement
      if (!row?.isConnected || (now && now !== document.body && now !== input)) return
      row.tabIndex = 0 // the render that gives it back may come after this tick
      row.focus({ preventScroll: true })
    })
  }
  function onEditorKey(event: KeyboardEvent<HTMLInputElement>) {
    if (event.nativeEvent.isComposing || event.nativeEvent.keyCode === 229) return
    if (event.key === ' ') event.stopPropagation()
    else if (event.key === 'Enter') {
      event.preventDefault()
      if (s.draft.value.trim()) backToRow(event)
      s.commit()
    } else if (event.key === 'Escape') {
      event.stopPropagation()
      event.preventDefault()
      backToRow(event)
      s.cancelEditor()
    }
  }
  const editing = s.editing.value
  // `inheritAttrs: false` and `v-bind="attrs"` first: the parent's class comes before the row's, its listeners run first,
  // and the row's own attributes win.
  return (
    <div
      {...fallthrough(attrs as { className?: string }, {
        'data-role': 'column-add',
        className: 'column-add-row',
        role: editing ? undefined : 'button',
        tabIndex: editing ? undefined : 0,
        onClick: () => {
          if (!s.editing.value) s.openEditor()
        },
        onKeyDown: onRowKey,
      })}
    >
      <label className="checkbox checkbox--size-s column-add-row__checkbox" aria-hidden="true">
        <input className="checkbox__input" type="checkbox" disabled />
        <span className="checkbox__box" />
      </label>
      {editing ? (
        <input
          {...model(s.draft, s.editor)}
          data-role="column-add-editor"
          className="column-add-editor"
          type="text"
          placeholder={placeholder}
          aria-label="Add goal"
          onClick={(event) => event.stopPropagation()}
          onKeyDown={onEditorKey}
        />
      ) : (
        <span className="column-add-row__text">{placeholder}</span>
      )}
    </div>
  )
})
