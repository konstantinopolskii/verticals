/* The keys of the field (components/SearchBar.tsx): the field's own while it has the caret, and the board's that reach it
   from anywhere. */
import { boardKey, boardKeyTarget, keyboardHelpOpen } from './keyboard'
import type { Ref } from '../reactivity'
import { store } from '../store'
import { commandFilter } from './commandFilter'
import { historyKey } from './boardHistory'
import type { fieldUndo } from './fieldUndo'
import { circle, circleWords } from './circle'
import { agentChat, stop } from './agentChat'
import { closeWindows, windows } from './windows'
import { anyMenuOpen } from './cardLift'
import { backspace as pickBackspace, escape as movingEscape, tab as pickTab } from './moving'
import { picturesBackspace, picturesEscape } from './reportPictures'

const CARET_KEYS = ['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown', 'Home', 'End']

interface Field {
  input: Ref<HTMLTextAreaElement | null>
  words: ReturnType<typeof fieldUndo>
  send(): void
  clear(): void
  moved(): void
  focus(): void
  reply(): void
  sendBack(): void
}

export function fieldKeys(field: Field) {
  /** Esc steps back one thing at a time: the words, the pictures, what is being moved, the conversation, the windows,
   *  and then the field itself. */
  function escape(): void {
    if (commandFilter.text) field.clear()
    else if (picturesEscape()) return
    else if (movingEscape()) return
    else if (agentChat.open) agentChat.open = false
    else if (windows.list.length) closeWindows()
    else {
      agentChat.engaged = false
      field.input.value?.blur()
    }
  }

  /** On an empty field, Backspace and Tab pick what stands above it: the last picture, or what waits to be moved
   *  (docs/design/bug-reports.md; S5.P4.002, .003). */
  function picksAbove(event: KeyboardEvent): boolean {
    if (commandFilter.text) return false
    if (event.key === 'Backspace' && picturesBackspace()) return true
    return circle.moving && ((event.key === 'Backspace' && pickBackspace()) || (event.key === 'Tab' && pickTab()))
  }

  function onKeyDown(event: KeyboardEvent): void {
    if (event.isComposing) return
    const history = historyKey(event)
    if (history) {
      // Inside the field the key is the field's own, and never the board's (`lib/boardHistory.ts`).
      event.preventDefault()
      field.words.step(history)
      return
    }
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault()
      field.send()
      return
    }
    if (picksAbove(event)) {
      event.preventDefault()
      return
    }
    if (event.key === 'Escape') {
      event.preventDefault()
      event.stopPropagation()
      escape()
      return
    }
    if (event.key === 'Tab' && !event.shiftKey && !commandFilter.text) {
      // The tags are reached with Tab from the open field, in their order (S2.P2.020).
      const first = document.querySelector<HTMLElement>('.circle-tags .circle-tag')
      if (first) { event.preventDefault(); first.focus() }
      return
    }
    if (CARET_KEYS.includes(event.key)) field.moved()
  }

  /** A printable key pressed on the board, not in anything that takes keys of its own, and with nothing held. */
  function firstLetter(event: KeyboardEvent): boolean {
    if (event.metaKey || event.ctrlKey || event.altKey || event.key.length !== 1 || event.key === ' ') return false
    const target = event.target instanceof HTMLElement ? event.target : null
    if (boardKeyTarget(target)) return false
    if (target?.closest('a, input, textarea, select, button, [contenteditable="true"], [role="dialog"], [role="menu"]')) return false
    return !anyMenuOpen() && !store.state.drag.id && !store.state.drag.pending
  }

  /* Focused board surfaces own their keys; typing on the background starts the field. */
  function onWindowKeyDown(event: KeyboardEvent): void {
    if (keyboardHelpOpen.value) { event.stopImmediatePropagation(); return }
    if (event.defaultPrevented || event.isComposing || event.keyCode === 229) return
    if (!anyMenuOpen() && !store.state.drag.id && !store.state.drag.pending && !store.state.drag.settling
      && boardKey(event, field.focus)) return
    const command = event.metaKey || event.ctrlKey
    if (command && !event.altKey && event.key.toLowerCase() === 'k') {
      event.preventDefault()
      event.stopImmediatePropagation()
      field.focus()
      return
    }
    if (command && event.key === '.' && agentChat.running) {
      event.preventDefault()
      void stop()
      return
    }
    if (event.key === 'Escape' && circleWords.value?.kind === 'answer' && !anyMenuOpen()) {
      event.preventDefault() // one press does one thing: the answer goes back, and nothing under it closes with it
      field.sendBack()
      return
    }
    if (!firstLetter(event)) return
    event.preventDefault()
    if (circleWords.value?.kind === 'answer') field.reply()
    field.words.typing(commandFilter.text, 'insertText')
    commandFilter.text += event.key
    field.words.typed(commandFilter.text)
    field.focus()
  }

  return { onKeyDown, onWindowKeyDown }
}
