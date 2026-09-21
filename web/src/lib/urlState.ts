// URL ↔ state. Still no router (`detailSurface.ts`'s dependency note stands): the URL is a
// projection of the reactive state, written by one watcher here, and `popstate` applies it back.
// This replaces the six scattered `pushState` calls (`main.ts` read the URL once at boot and
// nothing read it again, so Back/Forward moved the address bar and nothing else).
//
// Grammar — the path carries the board date, the fragment carries everything else:
//   `/` | `/h/<YYYY-MM-DD>`   board anchor — `/` means today
//   (none) | `#inbox` | `#docs`   the active view when nothing is open
//   `#goal/<id>` | `#doc/<id>`    the open overlay; it implies the view
//
// A goal names no view of its own: `navigateToGoal` places it (board host, or Inbox for a Maybe
// goal). A doc is always the Docs view. So one fragment slot is enough and the query stays empty.
//
// One watcher rather than per-action writes: several mutations in a tick (`App.vue`'s nav fires
// `closeGoal` + `setView` + `setValueFilter`) collapse into a single history entry.

import { watch } from 'vue'

export type AppView = 'verticals' | 'inbox' | 'docs'

interface UrlState {
  /** null = no date in the path (`/`, or any path that is not `/h/<date>`) — today. */
  anchor: string | null
  target: { kind: 'view'; view: AppView } | { kind: 'goal'; id: string } | { kind: 'doc'; id: string }
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

/** A history entry we pushed carries the URL it was pushed *from*, so a close can tell "Back lands
 *  exactly where this close wants to go" from "it does not" (a deep-linked `#goal/<id>` boot, or a
 *  breadcrumb chain whose previous entry is another open goal). */
interface PushedEntry {
  vtPrev: string
}

// A multi-step navigation (`navigateToGoal` reloading the board at the goal's own date, then
// opening it) passes through states nobody asked to come back to — "the doc, but over another
// week's board". Writes wait until it settles, so the whole jump is one history entry.
let heldSteps = 0
let flushHeldWrite: (() => void) | null = null

export async function asOneHistoryStep<T>(navigate: () => Promise<T>): Promise<T> {
  heldSteps += 1
  try {
    return await navigate()
  } finally {
    heldSteps -= 1
    if (heldSteps === 0) flushHeldWrite?.()
  }
}

function decodeId(raw: string): string {
  try {
    return decodeURIComponent(raw)
  } catch {
    return raw
  }
}

/** A path that is not `/h/<date>` means today rather than an error — a static host answers every
 *  path with the same `index.html`, so an unknown path is a typo. The date is matched, never
 *  parsed: `GET /api/board` validates it server-side. */
function parseUrl(loc: { pathname: string; hash: string } = window.location): UrlState {
  const pathMatch = ANCHOR_PATH_RE.exec(loc.pathname)
  const anchor = pathMatch ? pathMatch[1] : null
  const goal = GOAL_FRAGMENT_RE.exec(loc.hash)
  if (goal) return { anchor, target: { kind: 'goal', id: decodeId(goal[1]) } }
  const doc = DOC_FRAGMENT_RE.exec(loc.hash)
  if (doc) return { anchor, target: { kind: 'doc', id: decodeId(doc[1]) } }
  const view: AppView = loc.hash === '#inbox' ? 'inbox' : loc.hash === '#docs' ? 'docs' : 'verticals'
  return { anchor, target: { kind: 'view', view } }
}

function fragmentOf(target: UrlState['target']): string {
  if (target.kind === 'view') return target.view === 'verticals' ? '' : `#${target.view}`
  return `#${target.kind}/${encodeURIComponent(target.id)}`
}

/** The overlay follows the active view: a doc left open behind the board is state the Docs view
 *  restores on its own, not something the board's URL should claim. */
function targetOfState(state: UrlSyncState): UrlState['target'] {
  if (state.activeView === 'docs') {
    return state.docs.currentId ? { kind: 'doc', id: state.docs.currentId } : { kind: 'view', view: 'docs' }
  }
  return state.openGoalId ? { kind: 'goal', id: state.openGoalId } : { kind: 'view', view: state.activeView }
}

/** What an address means, with "no date" resolved to today. Comparing meanings rather than
 *  strings is what lets `/`, a hand-typed `/h/<today>` and `/search/<q>` all stand for the same
 *  today board, so none of them gets rewritten just for being spelled differently. */
function meaningOfUrl(url: UrlState, todayIso: () => string): string {
  return `${url.anchor ?? todayIso()}${fragmentOf(url.target)}`
}

function meaningOfState(state: UrlSyncState, todayIso: () => string): string {
  return `${state.board?.anchor_date ?? todayIso()}${fragmentOf(targetOfState(state))}`
}

/** The address to write for the state. `keepPath` — the path currently showing — survives when it
 *  already names the state's date, so a hand-typed `/h/<today>` is not collapsed to `/`. Any other
 *  path (`/search/…`, a typo) is replaced by the canonical one. `SearchBar.vue` reads this too: the
 *  search surface borrows the address bar and has to put back what the app shows underneath. */
export function stateUrl(state: UrlSyncState, todayIso: () => string, keepPath: string): string {
  const anchor = state.board?.anchor_date ?? todayIso()
  const keptDate = keepPath === '/' ? todayIso() : ANCHOR_PATH_RE.exec(keepPath)?.[1]
  const path = keptDate === anchor ? keepPath : anchor === todayIso() ? '/' : `/h/${anchor}`
  return `${path}${fragmentOf(targetOfState(state))}`
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
  // Walks in flight: while `applyUrl` moves the state to a URL the browser already shows, the
  // states it passes through are not entries anyone asked for, so the watcher stays quiet. A
  // count, not a flag — a fast double Back starts a second walk while the first still awaits its
  // board, and a flag cleared by the first walk would let the watcher push the second one's
  // half-applied state, dropping every Forward entry.
  let applying = 0
  let latestWalk = 0

  function currentUrl(): string {
    return `${location.pathname}${location.search}${location.hash}`
  }

  function urlMatchesState(): boolean {
    return meaningOfUrl(parseUrl(), todayIso) === meaningOfState(state, todayIso)
  }

  function write(): void {
    if (applying > 0 || heldSteps > 0) return
    const wanted = meaningOfState(state, todayIso)
    if (meaningOfUrl(parseUrl(), todayIso) === wanted) return
    const entry = history.state as Partial<PushedEntry> | null
    // Closing what this session opened rewinds instead of stacking a third entry, so Forward
    // re-opens it and one Back leaves the board the way the user arrived.
    if (entry?.vtPrev !== undefined && meaningOfUrl(parseUrl(new URL(entry.vtPrev, location.origin)), todayIso) === wanted) {
      history.back()
      return
    }
    history.pushState({ vtPrev: currentUrl() } satisfies PushedEntry, '', stateUrl(state, todayIso, location.pathname))
  }

  /** Walks the state to whatever the address bar now says — the boot read and every Back/Forward
   *  both land here. Each step is conditional, so re-applying the URL the state already matches
   *  costs nothing and nothing re-fetches. */
  async function applyUrl(): Promise<void> {
    const url = parseUrl()
    const walk = ++latestWalk
    applying += 1
    let boardLoaded = true
    try {
      const anchor = url.anchor ?? todayIso()
      if (state.board?.anchor_date !== anchor) boardLoaded = await deps.loadBoard(anchor)
      // A newer Back/Forward already owns the state; finishing this walk would undo it.
      if (walk !== latestWalk) return
      const target = url.target
      if (target.kind === 'goal') {
        // "Showing", not merely open: Back from a goal to a doc leaves the goal open behind Docs,
        // and skipping here would keep Docs on screen under a `#goal/<id>` address.
        const shown = targetOfState(state)
        if (shown.kind !== 'goal' || shown.id !== target.id) await deps.navigateToGoal(target.id)
      } else if (target.kind === 'doc') {
        deps.setView('docs')
        if (state.docs.currentId !== target.id) await deps.openDoc(target.id)
      } else {
        deps.closeGoal()
        // Only the bare Docs view closes the doc: one left open behind the board is kept for the
        // next visit to Docs, the same as clicking away through the nav keeps it.
        if (target.view === 'docs') deps.closeDoc()
        deps.setView(target.view)
      }
    } finally {
      applying -= 1
      // A goal deleted since its entry was pushed leaves the state without the overlay the URL
      // names; replace rather than push, so the correction is not a new entry. A board that failed
      // to load is not corrected: the address keeps what was asked for, so a retry can get it.
      if (applying === 0 && boardLoaded && !urlMatchesState()) {
        history.replaceState(history.state, '', stateUrl(state, todayIso, location.pathname))
      }
    }
  }

  function startUrlSync(): void {
    flushHeldWrite = write
    watch(() => meaningOfState(state, todayIso), write, { flush: 'post' })
    window.addEventListener('popstate', () => void applyUrl())
  }

  return { applyUrl, startUrlSync }
}
