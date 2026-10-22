// Entry point of the React build: the same boot as web/src/main.ts, on the same store, with React drawing it.
// Stylesheets in the same order as there: the components' own (through App), then the kit, then the app's overrides.
import { flushSync } from 'react-dom'
import { createRoot } from 'react-dom/client'
import { App } from './App'
import { store, todayIso } from './store'
import { createUrlSync } from './lib/urlState'
import { startKeyboardInset } from './lib/keyboardInset'
import { flushNow } from './reactivity'
import '@konstantinopolskii/design-system/vars.css'
import '@konstantinopolskii/design-system/style.css'
import './tokens.css'
import './base.css'

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
