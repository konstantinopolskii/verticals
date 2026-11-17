/* Hide Completed Goals (docs/design/hide-completed.md): the board leaves done goals out of its columns, steps under a goal
   too; a goal's own window and search still show them. ⇧⌘H or Ctrl+Shift+H, and View › Hide Completed Goals in the desktop
   app, whose item asks the page to switch and ticks itself by what the page tells it. Remembered on this device. */
import { ref } from '../reactivity'

const KEY = 'verticals:hide-done'

interface Host {
  webkit?: { messageHandlers?: { hideDone?: { postMessage(on: boolean): void } } }
  verticalsToggleHideDone?: () => void
}

function stored(): boolean {
  try { return localStorage.getItem(KEY) === '1' } catch { return false }
}

export const hideDone = ref(stored())

/** ⇧⌘H or Ctrl+Shift+H, read by the key's place so it works on any layout. */
export function isHideDoneToggle(event: KeyboardEvent): boolean {
  return (event.metaKey || event.ctrlKey) && event.shiftKey && !event.altKey && event.code === 'KeyH'
}

/** The desktop app ticks its View menu item by this; a browser has nobody to tell. */
function tellTheApp(): void {
  try { (window as Host).webkit?.messageHandlers?.hideDone?.postMessage(hideDone.value) } catch { /* a browser */ }
}

export function toggleHideDone(): void {
  hideDone.value = !hideDone.value
  try { localStorage.setItem(KEY, hideDone.value ? '1' : '0') } catch { /* optional */ }
  tellTheApp()
}

if (typeof window !== 'undefined') {
  ;(window as Host).verticalsToggleHideDone = toggleHideDone
  tellTheApp()
}
