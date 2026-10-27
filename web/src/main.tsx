// Entry point: boots the store and draws the app with React.
// Stylesheets first, so the components' own (through App) come after the design system and the page.
import './design/index.css'
import './base.css'
import { flushSync } from 'react-dom'
import { createRoot } from 'react-dom/client'
import { App } from './App'
import { store, todayIso } from './store'
import { createUrlSync } from './lib/urlState'
import { startKeyboardInset } from './lib/keyboardInset'
import { flushNow } from './reactivity'

const urlSync = createUrlSync(store.state, todayIso, {
  loadBoard: store.loadBoard,
  setView: store.setView,
  navigateToGoal: store.navigateToGoal,
  openDoc: store.openDoc,
  closeGoal: store.closeGoal,
  closeDoc: store.closeDoc,
})

urlSync.startUrlSync()
void urlSync.applyUrl()
startKeyboardInset()

// Mounted at once, as Vue's mount is: every component's mounted hooks have run when this module ends.
const root = createRoot(document.getElementById('app')!)
flushSync(() => root.render(<App />))
flushNow()
