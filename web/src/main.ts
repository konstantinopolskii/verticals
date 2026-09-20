// Entry point. WP-22: boots the real board through `store.ts` instead of the static
// `board.sample.json` fixture WP-12 mounted directly (that fixture's own header said as much:
// "Wiring a real fetch against core/board.py is WP-22/23"). `board.sample.json` itself is left in
// place — `tools/private/probe_column.ts` (a different, uidiff-adjacent tool) still reads it, and
// deleting a fixture outside this package's own remit is not this file's call to make.
//
// App shell (nav + content pane, `App.vue`) replaces the old hand-rolled
// `h('div.app-shell', [h(SearchBar), h(Board, ...)])` render function — now that there is a real
// root component with its own template, `createApp(App)` is the plain, standard call; `App.vue`
// owns the shell markup, the nav, and where `SearchBar`/`Board` each mount.
import { createApp } from 'vue'
import App from './App.vue'
import { store, todayIso } from './store'
import { createUrlSync } from './lib/urlState'
// Kit CSS first (tokens, then rules), app overrides last so --font-body wins by cascade order.
import '@konstantinopolskii/design-system/vars.css'
import '@konstantinopolskii/design-system/style.css'
import './style.css'

/* Routing lives in `lib/urlState.ts` — no router (`docs/DEPENDENCIES.md` caps the dependency list
   and none is needed for three regexes over `location`). Two calls wire it:

   - `startUrlSync()` installs the state→URL watcher and the `popstate` listener, so Back/Forward
     walk the app rather than only the address bar. Installed BEFORE the boot read: `applyUrl`
     holds the watcher quiet while it works, and anything the user manages to click during the
     first load is reconciled when it finishes.
   - `applyUrl()` is the boot read itself — the same one function every history entry goes through,
     so a typed URL, a reload and a Back are not three code paths. */
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

createApp(App).mount('#app')
