/* The circle and its field put away: ⌘\ or Ctrl+\ hides them and only the same keys bring them back, so nothing
   typed on the board starts the field meanwhile and the agent's answers wait in it. Remembered on this device. */
import { ref } from '../reactivity'

const KEY = 'verticals:field-hidden'

function stored(): boolean {
  try { return localStorage.getItem(KEY) === '1' } catch { return false }
}

export const fieldHidden = ref(stored())

/** ⌘\ or Ctrl+\, read by the key's place so it works on any layout. */
export function isFieldToggle(event: KeyboardEvent): boolean {
  return (event.metaKey || event.ctrlKey) && !event.altKey && !event.shiftKey && event.code === 'Backslash'
}

export function toggleField(): void {
  fieldHidden.value = !fieldHidden.value
  try { localStorage.setItem(KEY, fieldHidden.value ? '1' : '0') } catch { /* optional */ }
  // The caret can't stay in a field nobody sees.
  if (fieldHidden.value && document.activeElement?.closest('.circle-field')) (document.activeElement as HTMLElement).blur()
}
