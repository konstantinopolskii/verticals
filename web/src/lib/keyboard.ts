import { ref } from '../reactivity'
import { store } from '../store'
import { outOfFocus } from './windows'

export const keyboardHelpOpen = ref(false)
export const keyboardModifier = /Mac|iPhone|iPad|iPod/.test(navigator.platform) ? '⌘' : 'Ctrl'

export const keyboardGroups = [
  { name: 'Navigate', bindings: [
    { label: 'Change column', keys: ['←', '→'] },
    { label: 'Change goal', keys: ['↑', '↓'] },
    { label: 'Next control', keys: ['Tab'] },
    { label: 'Previous control', keys: ['Shift', 'Tab'] },
  ] },
  { name: 'History', bindings: [
    { label: 'Undo', keys: [keyboardModifier, 'Z'] },
    { label: 'Redo', keys: [keyboardModifier, 'Shift', 'Z'] },
  ] },
  { name: 'Goals', bindings: [
    { label: 'New goal in this column', keys: ['N'] },
    { label: 'Rename goal', keys: ['Enter'] },
    { label: 'Open details', keys: ['Space'] },
    { label: 'More actions', keys: ['/'] },
    { label: 'Find or ask', keys: ['F'] },
  ] },
]

export function boardKeyTarget(target: EventTarget | null): HTMLElement | null {
  if (!(target instanceof HTMLElement) || !target.matches('.goal-card__row, [data-keyboard-column]')) return null
  return target.closest('[data-role="column-strip"]') ? target : null
}

function rows(column: HTMLElement): HTMLElement[] {
  return [...column.querySelectorAll<HTMLElement>('.goal-card__row')].filter((row) =>
    !row.closest('[data-state="outgoing"], [data-ghost], [inert], [aria-hidden="true"]') && row.getClientRects().length > 0)
}

/* The goal or column the keys last stood on: an arrow pressed on the background comes back to it. */
let lastTarget: HTMLElement | null = null
/* A press of the pointer, not a key, moved the focus last. */
let pointed = false
window.addEventListener('pointerdown', () => { pointed = true }, true)
window.addEventListener('keydown', () => { pointed = false }, true)

/** A goal or column took the focus. A click on a column's empty space leaves the background its typing, so it gives the
 * focus back instead of keeping it. */
export function boardFocused(target: HTMLElement): void {
  if (pointed && target.matches('[data-keyboard-column]')) { target.blur(); return }
  lastTarget = target
}

function shown(target: HTMLElement | null): target is HTMLElement {
  if (!target?.isConnected || target.getClientRects().length === 0) return false
  return !target.closest('[data-state="outgoing"], [data-ghost], [inert], [aria-hidden="true"]')
}

/** Where the keys start on the board: the goal they last stood on, else the first goal of the leading column. */
function boardStart(): HTMLElement | null {
  if (shown(lastTarget) && boardKeyTarget(lastTarget)) return lastTarget
  const strip = document.querySelector<HTMLElement>('[data-role="column-strip"]')
  const lead = strip?.querySelector<HTMLElement>('.pattern-vertical-board__column--deck-main[data-keyboard-column]')
    ?? strip?.querySelector<HTMLElement>('[data-keyboard-column]')
  return lead ? rows(lead)[0] ?? lead : null
}

/** A key pressed with nothing in focus, or on the plain board, when the board is the view on show. */
function onBackground(event: KeyboardEvent): boolean {
  const target = event.target instanceof HTMLElement ? event.target : null
  if (target && target !== document.body && target.closest(
    'a, input, textarea, select, button, [tabindex], [contenteditable="true"], [role="dialog"], [role="menu"], dialog')) return false
  return store.state.activeView === 'verticals' && store.state.openGoalVertical !== 'search' && !outOfFocus.value
}

export function focusBoardTarget(target: HTMLElement): void {
  target.focus({ preventScroll: true })
  target.scrollIntoView({ block: 'nearest', inline: 'nearest', behavior: 'instant' })
}

/** Runs before background typing, only for the surface that owns focus. */
export function boardKey(event: KeyboardEvent, focusField: () => void): boolean {
  if (event.defaultPrevented || event.isComposing || event.keyCode === 229
    || event.metaKey || event.ctrlKey || event.altKey) return false
  const target = boardKeyTarget(event.target)
  if (!target) {
    // On the background an arrow picks up the board where the keys left it, and ? opens the guide; letters stay the field's.
    if (!onBackground(event)) return false
    if (event.key === '?') keyboardHelpOpen.value = true
    else if (['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown'].includes(event.key) && !event.shiftKey) {
      const start = boardStart()
      if (!start) return false
      focusBoardTarget(start)
    } else return false
    event.preventDefault()
    event.stopImmediatePropagation()
    return true
  }
  const column = target.closest<HTMLElement>('[data-keyboard-column]')
  if (!column) return false
  const arrow = ['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown'].includes(event.key)
  if (event.shiftKey && event.key !== '?') return false
  if (!arrow && !['n', 'f', '?'].includes(event.key)) return false
  event.preventDefault()
  event.stopImmediatePropagation()
  if (!arrow && event.repeat) return true
  if (event.key === '?') keyboardHelpOpen.value = true
  else if (event.key === 'f') focusField()
  else if (event.key === 'n') {
    const editor = column.querySelector<HTMLElement>('.period-slide:not([data-state="outgoing"]) [data-role="column-add-editor"]')
    if (editor) editor.focus()
    else column.querySelector<HTMLElement>('.period-slide:not([data-state="outgoing"]) [data-role="column-add"]')?.click()
  } else {
    const own = rows(column)
    const index = own.indexOf(target)
    let next: HTMLElement | undefined
    if (event.key === 'ArrowUp') next = own[index < 0 ? own.length - 1 : Math.max(0, index - 1)]
    else if (event.key === 'ArrowDown') next = own[Math.min(own.length - 1, index + 1)]
    else {
      const columns = [...column.parentElement!.querySelectorAll<HTMLElement>(':scope > [data-keyboard-column]')]
      const at = columns.indexOf(column) + (event.key === 'ArrowLeft' ? -1 : 1)
      const adjacent = columns[at]
      if (adjacent) {
        const visible = rows(adjacent)
        next = visible[Math.min(Math.max(index, 0), visible.length - 1)] ?? adjacent
      }
    }
    if (next) focusBoardTarget(next)
  }
  return true
}
