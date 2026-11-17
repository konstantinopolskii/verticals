/* The shell's window keys: privacy, Hide Completed Goals, Alt while dragging (the drag's listeners live here because a card arms a drag in any
   view, so arm and release live in the one lifetime that spans them all), Esc and ⌘[ / ⌘]. */
import { store } from '../store'
import { isPrivacyHotkey, togglePrivacy } from './privacy'
import { isHideDoneToggle, toggleHideDone } from './hideDone'
import { agentChat } from './agentChat'
import { circle } from './circle'
import { escape as letGoOfMove, moving } from './moving'
import { closeWindows, stepWindow, windows } from './windows'
import { desk } from './docsDesk'
import { onMounted, onUnmounted } from '../reactivity'

/* Esc, when nothing smaller takes it, peels one layer a press: the agent's conversation, the windows, then on a desk
   a goal held on the field, on Documents a document's history, the document itself and a laid-out stack, and last the
   desk, Inbox or Documents, back to the board. What has its own Esc keeps it: the text being typed, a menu, a dialog,
   a goal in the hand, and on the board a goal open in place (GoalDetail) and the moving mode (SpansBoard). ⌘[ and ⌘]
   move one window. */
function escapeStep(): (() => void) | null {
  if (agentChat.open) return () => { agentChat.open = false }
  if (windows.list.length) return closeWindows
  const view = store.state.activeView
  if (view === 'verticals') return null
  if (moving.picked || circle.moving) return () => void letGoOfMove()
  if (view === 'docs') {
    const docs = store.state.docs
    if (docs.historyOpen && docs.current) return store.closeHistory
    if (docs.historyOpen || docs.currentId || docs.currentLoading) return store.closeDoc
    if (desk.open) return () => { desk.open = null }
  }
  return () => store.setView('verticals')
}

function onWindowKeyDown(event: KeyboardEvent): void {
  if (isPrivacyHotkey(event) && !event.repeat) {
    event.preventDefault()
    void togglePrivacy()
    return
  }
  // Handled here, the keys never reach the desktop app's View menu, so the item can't switch it a second time.
  if (isHideDoneToggle(event)) {
    event.preventDefault()
    if (!event.repeat) toggleHideDone()
    return
  }
  if (event.key === 'Alt' && (store.state.drag.pending || store.state.drag.id)) {
    store.setDragCombineMode(true)
    event.preventDefault()
  }
}

function onWindowKeyUp(event: KeyboardEvent): void {
  if (event.key === 'Alt' && (store.state.drag.pending || store.state.drag.id)) {
    store.setDragCombineMode(false)
    event.preventDefault()
  }
}

function onShellKey(event: KeyboardEvent): void {
  if (event.defaultPrevented) return
  if (windows.list.length && (event.metaKey || event.ctrlKey) && (event.key === '[' || event.key === ']')) {
    event.preventDefault()
    stepWindow(event.key === '[' ? -1 : 1)
    return
  }
  if (event.key !== 'Escape' || event.isComposing || event.repeat) return
  const target = event.target instanceof HTMLElement ? event.target : null
  if (target?.closest('input, textarea, select, [contenteditable="true"], [role="dialog"], [role="menu"]')) return
  if (store.state.drag.id || store.state.drag.pending || store.state.drag.settling) return
  const step = escapeStep()
  if (!step) return
  event.preventDefault()
  step()
}

export function useShellKeys(): void {
  onMounted(() => {
    window.addEventListener('keydown', onWindowKeyDown)
    window.addEventListener('keyup', onWindowKeyUp)
    window.addEventListener('keydown', onShellKey)
  })
  onUnmounted(() => {
    window.removeEventListener('keydown', onWindowKeyDown)
    window.removeEventListener('keyup', onWindowKeyUp)
    window.removeEventListener('keydown', onShellKey)
  })
}
