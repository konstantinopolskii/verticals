// URL ↔ state. Still no router (`detailSurface.ts`'s dependency note stands): the URL is a
// projection of the reactive state, written by one watcher here, and `popstate` applies it back.
// This replaces the six scattered `pushState` calls (`main.ts` read the URL once at boot and
// nothing read it again, so Back/Forward moved the address bar and nothing else).
//
// Grammar:
//   `/` | `/h/<YYYY-MM-DD>`    board anchor — `/` means today
//   `?view=inbox` | `?view=docs`  active view — `verticals` emits nothing, so old URLs are unchanged
//   `#goal/<id>` | `#doc/<id>`    the open overlay
//
// One watcher rather than per-action writes: several mutations in a tick (`App.vue`'s nav fires
// `closeGoal` + `setView` + `setValueFilter`) collapse into a single history entry, and a write
// that lands on the URL already showing is skipped instead of stacking a duplicate.

import { watch } from 'vue'

export type AppView = 'verticals' | 'inbox' | 'docs'

export interface UrlState {
  view: AppView
  /** null = today, rendered as `/`. */
  anchor: string | null
  overlay: { kind: 'goal' | 'doc'; id: string } | null
}

/** The state fields the URL projects, structurally — same shape-not-import convention as
 *  `DetailState` in `lib/detailSurface.ts`. */
export interface UrlSyncState {
  board: { anchor_date: string } | null
  activeView: AppView
  openGoalId: string | null
  docs: { currentId: string | null }
}

const ANCHOR_PATH_RE = /^\/h\/(\d{4}-\d{2}-\d{2})\/?$/
const GOAL_FRAGMENT_RE = /^#goal\/(.+)$/
const DOC_FRAGMENT_RE = /^#doc\/(.+)$/
const VIEWS: readonly string[] = ['verticals', 'inbox', 'docs']

/** A history entry we pushed carries the URL it was pushed *from*, so `closeGoal`/`closeDoc` can
 *  tell "Back lands exactly where this close wants to go" from "it does not" (a deep-linked
 *  `#goal/<id>` boot, or a breadcrumb chain whose previous entry is another open goal). */
interface PushedEntry {
  vtPrev: string
}

function decodeId(raw: string): string {
  try {
    return decodeURIComponent(raw)
  } catch {
    return raw
  }
}

/** A path that is not `/h/<date>` falls back to today rather than erroring — a static host answers
 *  every path with the same `index.html`, so an unknown path is a typo, and a typo showing today's
 *  board is the honest outcome. The date is matched, never parsed: `GET /api/board` validates it
 *  server-side, so there is no second client-side calendar to disagree with the server's. */
export function parseUrl(loc: Location | URL = window.location): UrlState {
  const pathMatch = ANCHOR_PATH_RE.exec(loc.pathname)
  const goalMatch = GOAL_FRAGMENT_RE.exec(loc.hash)
  const docMatch = DOC_FRAGMENT_RE.exec(loc.hash)
  const overlay: UrlState['overlay'] = goalMatch
    ? { kind: 'goal', id: decodeId(goalMatch[1]) }
    : docMatch
      ? { kind: 'doc', id: decodeId(docMatch[1]) }
      : null
  // `#doc/<id>` implies the Docs view on its own — that is how the fragment shipped before
  // `?view=` existed, and links already in the wild carry no param.
  const param = new URLSearchParams(loc.search).get('view')
  const view: AppView = VIEWS.includes(param ?? '')
    ? (param as AppView)
    : overlay?.kind === 'doc'
      ? 'docs'
      : 'verticals'
  return { view, anchor: pathMatch ? pathMatch[1] : null, overlay }
}

export function formatUrl(url: UrlState): string {
  const path = url.anchor === null ? '/' : `/h/${url.anchor}`
  const search = url.view === 'verticals' ? '' : `?view=${url.view}`
  const hash = url.overlay === null ? '' : `#${url.overlay.kind}/${encodeURIComponent(url.overlay.id)}`
  return `${path}${search}${hash}`
}

/** The URL the state is currently worth. The overlay follows the active view: a doc left open
 *  behind the board is state the Docs view restores on its own, not something the board's URL
 *  should claim. `SearchBar.vue` reads this too — the search surface replaces the address while
 *  it is open and has to put back whatever the app is actually showing underneath. */
export function urlOfState(state: UrlSyncState, todayIso: () => string): UrlState {
  const anchor = state.board?.anchor_date ?? null
  const overlay: UrlState['overlay'] =
    state.activeView === 'docs'
      ? state.docs.currentId
        ? { kind: 'doc', id: state.docs.currentId }
        : null
      : state.openGoalId
        ? { kind: 'goal', id: state.openGoalId }
        : null
  return { view: state.activeView, anchor: anchor === todayIso() ? null : anchor, overlay }
}

export function createUrlSync(
  state: UrlSyncState,
  todayIso: () => string,
  deps: {
    loadBoard: (date: string) => Promise<boolean>
    setView: (view: AppView) => void
    navigateToGoal: (id: string) => Promise<void>
    openDoc: (id: string) => Promise<void>
    closeGoal: () => void
    closeDoc: () => void
  },
) {
  // Set while `applyUrl` walks the state to a URL the browser has already navigated to. The
  // intermediate states it passes through (board loaded, view switched, goal not open yet) are
  // not entries anyone asked for, so the watcher stays quiet until the walk finishes.
  let applying = false

  function currentUrl(): string {
    return `${location.pathname}${location.search}${location.hash}`
  }

  function write(next: string): void {
    if (applying) return
    const current = currentUrl()
    if (next === current) return
    const entry = history.state as Partial<PushedEntry> | null
    // Closing what this session opened rewinds instead of stacking a third entry, so Forward
    // re-opens it and one Back leaves the board the way the user arrived.
    if (entry?.vtPrev === next) {
      history.back()
      return
    }
    history.pushState({ vtPrev: current } satisfies PushedEntry, '', next)
  }

  /** Walks the state to whatever the address bar now says — the boot read and every Back/Forward
   *  both land here. Each step is conditional, so re-applying the URL the state already matches
   *  costs nothing and nothing re-fetches. */
  async function applyUrl(): Promise<void> {
    const target = parseUrl()
    applying = true
    try {
      const anchor = target.anchor ?? todayIso()
      if ((state.board?.anchor_date ?? null) !== anchor) await deps.loadBoard(anchor)
      deps.setView(target.view)
      if (target.overlay?.kind === 'goal') {
        // `navigateToGoal` owns the whole ladder (board host, Inbox bucket, reload at the goal's
        // own anchor date) and sets `activeView` itself where it has to.
        if (state.openGoalId !== target.overlay.id) await deps.navigateToGoal(target.overlay.id)
      } else if (target.overlay?.kind === 'doc') {
        deps.setView('docs')
        if (state.docs.currentId !== target.overlay.id) await deps.openDoc(target.overlay.id)
      } else {
        deps.closeGoal()
        deps.closeDoc()
      }
    } finally {
      applying = false
      // A goal that no longer exists (deleted since the entry was pushed) leaves the state without
      // the overlay the URL names; replace rather than push, so the correction is not a new entry.
      const settled = formatUrl(urlOfState(state, todayIso))
      if (settled !== currentUrl()) history.replaceState(history.state, '', settled)
    }
  }

  function startUrlSync(): void {
    watch(() => formatUrl(urlOfState(state, todayIso)), write, { flush: 'post' })
    window.addEventListener('popstate', () => void applyUrl())
  }

  return { applyUrl, startUrlSync, currentUrl }
}
