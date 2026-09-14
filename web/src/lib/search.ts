import { searchGoals, type GoalCard } from './api'

/** The search-owned fields in the app's reactive state. Keeping this structural lets the store
 *  retain the one state tree while this module owns the actions that mutate its search slice. */
interface SearchState {
  searchQuery: string
  searchTag: string | null
  searchResults: GoalCard[]
  searchTruncated: boolean
}

/** Search actions share the store's reactive state and error reporter; no second state container
 *  or transport policy is introduced by extracting this coherent slice from `store.ts`. */
export function createSearchActions(state: SearchState, reportError: (err: unknown) => void) {
  /** `IR-12`/S-26: the 3-character floor is enforced here too, not only server-side — "every
   *  keystroke is a sequential scan at scale" is the shipped reasoning (`docs/E2E.md` S-125).
   *  Below 3 characters this clears previous results rather than leaving them on screen. */
  async function runSearch(query: string): Promise<void> {
    state.searchQuery = query
    state.searchTag = null
    const trimmed = query.trim()
    if (trimmed.length < 3) {
      state.searchResults = []
      state.searchTruncated = false
      return
    }
    try {
      const res = await searchGoals({ q: trimmed })
      state.searchResults = res.goals
      state.searchTruncated = res.truncated
    } catch (err) {
      reportError(err)
    }
  }

  /** P-01: opening the empty search surface shows a bounded recent list. Separate from
   *  `runSearch` so typing one or two characters still performs no request. */
  async function loadRecentSearch(): Promise<void> {
    state.searchQuery = ''
    state.searchTag = null
    try {
      const res = await searchGoals({ limit: 10 })
      state.searchResults = res.goals
      state.searchTruncated = res.truncated
    } catch (err) {
      reportError(err)
    }
  }

  /** The `#retro`-chip half of S-125. Deliberately a *second* entry point from `runSearch`, not a
   *  fallthrough of it: `GET /api/search?tag=` and `?q=` are different queries over different
   *  columns (`core/search.py`), and `SYNRET01`/`SYNRET02` are off the visible board on purpose
   *  (`tests/fixtures/f2_synth.sql`'s own comment) — proving this needs its own route, not a
   *  client-side filter over whatever `runSearch` already fetched. */
  async function filterByTag(tag: string): Promise<void> {
    state.searchTag = tag
    state.searchQuery = ''
    try {
      const res = await searchGoals({ tag })
      state.searchResults = res.goals
      state.searchTruncated = res.truncated
    } catch (err) {
      reportError(err)
    }
  }

  function clearSearch(): void {
    state.searchQuery = ''
    state.searchTag = null
    state.searchResults = []
    state.searchTruncated = false
  }

  return { runSearch, loadRecentSearch, filterByTag, clearSearch }
}
