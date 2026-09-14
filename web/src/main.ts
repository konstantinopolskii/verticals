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
// Kit CSS first (tokens, then rules), app overrides last so --font-body wins by cascade order.
import '@konstantinopolskii/design-system/vars.css'
import '@konstantinopolskii/design-system/style.css'
import './style.css'

/* Two URLs the app reads at boot, and nothing else — no router (docs/DEPENDENCIES.md caps the
   dependency list and none is needed for two regexes over `location`).

   1. `/h/<YYYY-MM-DD>` — the anchor-date board (AC-114, S-69's stale-board captures). `/` keeps
      meaning today. A path that is not this shape falls back to today rather than erroring: a
      static host serving this SPA answers every path with the same `index.html`, so an unknown
      path is a typo, and a typo showing today's board is the honest, boring outcome. The date is
      matched, never parsed — `GET /api/board` validates it server-side and a rejected value
      surfaces through the store's own error path, so there is no second, client-side calendar
      here to disagree with the server's.
   2. `#goal/<id>` — after the board resolves, `store.navigateToGoal` (D248 WP-D) resolves the
      goal against the rendered Verticals projection and opens its inline host. A goal absent from
      that projection navigates instead: a board reload at the goal's own anchor date for a dated
      goal, or the Inbox view for a Maybe-bucket goal — never the retired board modal.
   3. `#doc/<id>` (D250, WP-3) — mirrors `#goal/<id>`: switches the shell to the Docs view and
      opens the doc there (`store.openDoc`). No board resolution needed (docs are not placed on
      the board at all), so this branch does not wait on anything `navigateToGoal` waits on — it
      still runs after `loadBoard` resolves purely to keep one boot sequence, not two races.

   `history.pushState` (openGoal's/openDoc's own mechanism) never re-runs this file, and neither
   does a fragment change — a URL typed into the bar or a reload is what boots the app, which is
   exactly the case this covers. Back/forward through pushState entries is a separate behaviour
   nobody has specified; adding a `popstate` listener would be inventing it. */
const ANCHOR_PATH_RE = /^\/h\/(\d{4}-\d{2}-\d{2})\/?$/
const GOAL_FRAGMENT_RE = /^#goal\/(.+)$/
const DOC_FRAGMENT_RE = /^#doc\/(.+)$/

const pathMatch = ANCHOR_PATH_RE.exec(window.location.pathname)
const fragmentMatch = GOAL_FRAGMENT_RE.exec(window.location.hash)
const docFragmentMatch = DOC_FRAGMENT_RE.exec(window.location.hash)

void store.loadBoard(pathMatch ? pathMatch[1] : todayIso()).then(() => {
  if (fragmentMatch) {
    const id = decodeURIComponent(fragmentMatch[1])
    void store.navigateToGoal(id)
  } else if (docFragmentMatch) {
    const id = decodeURIComponent(docFragmentMatch[1])
    store.setView('docs')
    void store.openDoc(id)
  }
})

createApp(App).mount('#app')
