import { ref } from '../reactivity'
import { store } from '../store'
import { outOfFocus } from './windows'
import { releaseLifts, whenHandMoves } from './cardLift'

export const keyboardHelpOpen = ref(false)
export const keyboardModifier = /Mac|iPhone|iPad|iPod/.test(navigator.platform) ? '⌘' : 'Ctrl'

export const keyboardGroups = [
  { name: 'Navigate', bindings: [
    { label: 'Change column', keys: ['←', '→'] },
    { label: 'Change goal', keys: ['↑', '↓'] },
    { label: 'Previous or next period', keys: ['Shift', '←', '→'] },
    { label: 'Widen or narrow the column', keys: ['Shift', '↓', '↑'] },
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
    { label: 'Open or close details', keys: ['Space'] },
    { label: 'Mark done', keys: ['E'] },
    { label: 'More actions', keys: ['/'] },
    { label: 'Find or ask', keys: ['F'] },
    { label: 'Hide or show the field', keys: [keyboardModifier, '\\'] },
  ] },
]

/* The places the keys stand on: a goal, a column's Add row, and a column with neither. */
const PLACES = '.goal-card__row, [data-role="column-add"], [data-keyboard-column]'

export function boardKeyTarget(target: EventTarget | null): HTMLElement | null {
  if (!(target instanceof HTMLElement) || !target.matches(PLACES)) return null
  return target.closest('[data-role="column-strip"]') ? target : null
}

/** Where an arrow starts from: the place itself, or the goal or column whose own control (a checkbox, the actions
 * button, the period bars) has the focus. Fields keep their arrows for the caret. */
function arrowPlace(target: EventTarget | null): HTMLElement | null {
  // An Add field with nothing typed is its Add row: the arrows go on from it.
  if (target instanceof HTMLInputElement && target.matches('[data-role="column-add-editor"]') && !target.value) {
    return boardKeyTarget(target.closest('[data-role="column-add"]'))
  }
  if (!(target instanceof HTMLElement) || target.matches('input:not([type="checkbox"]), textarea, select, [contenteditable="true"]')) return null
  const place = boardKeyTarget(target) ?? target.closest<HTMLElement>('.goal-card__row')
    ?? (target.closest('.column-bars') ? target.closest<HTMLElement>('[data-keyboard-column]') : null)
  return boardKeyTarget(place)
}

/* A goal just created waits, inert, for the server under a `pending:` id; the keys may land on it, and take it when it
   comes back as the real goal. */
const PENDING = '[data-goal-id^="pending:"]'

/** The goals of a column in the order they show, then its Add row, open or not. */
function rows(column: HTMLElement, pending = false): HTMLElement[] {
  return [...column.querySelectorAll<HTMLElement>('.goal-card__row, [data-role="column-add"]')].filter((row) =>
    !row.closest(`[data-state="outgoing"], [aria-hidden="true"], ${pending ? `[inert]:not(${PENDING})` : '[inert]'}`)
    && row.getClientRects().length > 0)
}

/* A key on the board takes over from the pointer: the goal under a still pointer drops its lift and its family's light
   until the hand moves, so the board shows one goal, the keys' (a goal opened with Space stayed grey while the one
   under the pointer lit). */
window.addEventListener('keydown', (event) => {
  if (['Shift', 'Control', 'Alt', 'Meta'].includes(event.key) || !boardKeyTarget(event.target)) return
  releaseLifts(null, true)
  store.dropHoverChain()
  whenHandMoves(handBack)
}, true)
/* When the hand moves again, the goal under it answers as if the pointer had just come onto it. */
function handBack(): void {
  document.querySelectorAll('.goal-card:hover, .goal-card__children:hover')
    .forEach((el) => el.dispatchEvent(new MouseEvent('mouseenter')))
}

/* The goal or column the keys last stood on: an arrow pressed on the background comes back to it. */
let lastTarget: HTMLElement | null = null
let lastPlace: Place | null = null
/* A press of the pointer, not a key, moved the focus last. */
let pointed = false
window.addEventListener('pointerdown', () => { pointed = true }, true)
window.addEventListener('keydown', () => { pointed = false }, true)

/** A goal or column took the focus. A click on a column's empty space leaves the background its typing, so it gives the
 * focus back instead of keeping it. */
export function boardFocused(target: HTMLElement): void {
  if (pointed && target.matches('[data-keyboard-column]')) { target.blur(); return }
  lastTarget = target
  lastPlace = placeOf(target)
}

/* Keeps the keys' place when the board redraws it: a focused goal or column whose element is replaced takes the focus
   back on its new element, instead of leaving it on the page. A blur the person made (the element stays) drops it. Its
   column and goal are read while it is still on the board: a removed row has no column around it any more. */
type Place = { element: HTMLElement; column?: string; goal?: string; add?: boolean }
let held: Place | null = null
function placeOf(target: HTMLElement): Place {
  return { element: target, column: target.closest<HTMLElement>('[data-keyboard-column]')?.dataset.vertical,
    goal: target.closest<HTMLElement>('[data-goal-id]')?.dataset.goalId, add: target.matches('[data-role="column-add"]') }
}
/* The same goal or column drawn anew: a goal's row is replaced when the server confirms it or its period redraws. */
function redrawn({ column, goal, add }: Place): HTMLElement | null {
  const home = column ? document.querySelector<HTMLElement>(`[data-role="column-strip"] > [data-keyboard-column][data-vertical="${column}"]`) : null
  if (!home) return null
  if (add) return rows(home).find((row) => row.matches('[data-role="column-add"]')) ?? home
  if (!goal) return home
  return [...home.querySelectorAll<HTMLElement>(`[data-goal-id="${CSS.escape(goal)}"] > .goal-card__row`)].find(shown) ?? null
}
document.addEventListener('focusin', (event) => {
  const target = boardKeyTarget(event.target)
  held = target ? placeOf(target) : null
})
document.addEventListener('focusout', (event) => {
  const left = event.target
  queueMicrotask(() => { if (held?.element === left && left instanceof Node && left.isConnected) held = null })
})
/* The keys moved onto a goal still waiting for the server: its column and place, to focus when it arrives. */
let awaiting: { column: HTMLElement; index: number } | null = null
document.addEventListener('focusin', (event) => { if (awaiting && event.target !== awaiting.column) awaiting = null })
new MutationObserver(() => {
  if (awaiting) {
    const { column, index } = awaiting
    const row = column.isConnected && document.activeElement === column ? rows(column, true)[index] : undefined
    if (!column.isConnected || document.activeElement !== column) awaiting = null
    else if (row && !row.closest(PENDING)) { awaiting = null; focusBoardTarget(row) }
  }
  if (!held || held.element.isConnected || (document.activeElement && document.activeElement !== document.body)) return
  const again = redrawn(held)
  held = null
  if (again) focusBoardTarget(again, false)
}).observe(document.body, { childList: true, subtree: true })

function shown(target: HTMLElement | null): target is HTMLElement {
  if (!target?.isConnected || target.getClientRects().length === 0) return false
  return !target.closest('[data-state="outgoing"], [inert], [aria-hidden="true"]')
}

/** Where the keys start on the board: the goal they last stood on, else the first goal of the leading column. */
function boardStart(): HTMLElement | null {
  if (shown(lastTarget) && boardKeyTarget(lastTarget)) return lastTarget
  const again = lastPlace && redrawn(lastPlace)
  if (again) return again
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

/** Puts the keys on a place. An Add row the keys reach opens its field at once: it is there to type in. A place given
 * back after a redraw stays as it was. */
export function focusBoardTarget(target: HTMLElement, open = true): void {
  if (open && target.matches('[data-role="column-add"]')) {
    target.click()
    target.scrollIntoView({ block: 'nearest', inline: 'nearest', behavior: 'instant' })
    return
  }
  target.focus({ preventScroll: true })
  target.scrollIntoView({ block: 'nearest', inline: 'nearest', behavior: 'instant' })
}

/** Shift with ← or → pages the column as its side bars do, and the columns under it follow; Shift with ↓ widens it as
 * a click on its name does, and Shift with ↑ makes it narrow again. The column keeps the keys: the goal they stood on
 * may leave with its period. */
function shiftArrow(key: string, column: HTMLElement): void {
  const vertical = column.dataset.vertical
  if (!vertical) return
  if (key === 'ArrowLeft' || key === 'ArrowRight') {
    const bar = column.querySelector<HTMLElement>(`:scope > .column-bars [data-cap="${key === 'ArrowLeft' ? 'period-prev' : 'period-next'}"]`)
    if (!bar) return
    focusBoardTarget(column)
    bar.click()
  } else if ((key === 'ArrowDown') !== (store.state.expandedVertical === vertical)
    && !(key === 'ArrowUp' && store.state.openGoalVertical === vertical)) {
    store.toggleExpandedColumn(vertical)
  }
}

/* The board's letters by where they are on the keys. */
const LETTERS: Record<string, string> = { KeyN: 'n', KeyF: 'f', KeyE: 'e' }

/** Runs before background typing, only for the surface that owns focus. */
export function boardKey(event: KeyboardEvent, focusField: () => void): boolean {
  if (event.defaultPrevented || event.isComposing || event.keyCode === 229
    || event.metaKey || event.ctrlKey || event.altKey) return false
  const arrow = ['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown'].includes(event.key)
  const target = arrow ? arrowPlace(event.target) : boardKeyTarget(event.target)
  if (!target) {
    // On the background an arrow picks up the board where the keys left it, and ? opens the guide; letters stay the field's.
    if (!onBackground(event)) return false
    if (event.key === '?') keyboardHelpOpen.value = true
    else if (arrow && !event.shiftKey) {
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
  if (event.shiftKey && arrow) {
    event.preventDefault()
    event.stopImmediatePropagation()
    if (!event.repeat) shiftArrow(event.key, column)
    return true
  }
  if (event.shiftKey && event.key !== '?') return false
  // Enter on a column, not a goal, creates there as N does; on a goal it stays the goal's own (rename).
  const enter = event.key === 'Enter' && target === column
  // A layout without Latin letters (Russian) takes the letter in the same place on the keys.
  const letter = /^[a-z]$/.test(event.key) ? event.key : LETTERS[event.code] ?? event.key
  const done = letter === 'e' && target.matches('.goal-card__row') && !target.closest(PENDING)
  if (!arrow && !enter && !done && !['n', 'f', '?'].includes(letter)) return false
  event.preventDefault()
  event.stopImmediatePropagation()
  if (!arrow && event.repeat) return true
  if (event.key === '?') keyboardHelpOpen.value = true
  else if (letter === 'f') focusField()
  // E does what the goal's checkbox does, without opening the goal; again, it takes it back.
  else if (done) target.querySelector<HTMLInputElement>(':scope > .goal-card__affordance-slot input[type="checkbox"]')?.click()
  else if (letter === 'n' || enter) {
    const editor = column.querySelector<HTMLElement>('.period-slide:not([data-state="outgoing"]) [data-role="column-add-editor"]')
    if (editor) editor.focus()
    else column.querySelector<HTMLElement>('.period-slide:not([data-state="outgoing"]) [data-role="column-add"]')?.click()
  } else {
    const own = rows(column, true)
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
    if (next?.closest(PENDING)) {
      // The column keeps the keys until the goal comes back real, then hands them to it.
      focusBoardTarget(column)
      awaiting = { column, index: own.indexOf(next) }
    } else if (next) focusBoardTarget(next)
  }
  return true
}
