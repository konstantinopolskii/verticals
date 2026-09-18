// The Docs view's whole state slice (D250, WP-3) — list, current doc, history/revision browsing,
// and every doc write (create/save/rename/restore/delete) — lifted out of `store.ts` from the
// start, same factory seam `createDetailSurface`/`createSearchActions` already use there: this
// closes over a slice of the store's shared reactive state and its error reporter, owns no
// transport policy of its own, and `store.ts` re-exports its actions unchanged.
//
// The folder tree is NOT stored state: `docTree()` below derives it fresh from `list` on every
// call — `core/docs.py`'s own module docstring states the rule once ("the folder tree is just
// paths... no folder table") and this is the client-side half of it. `collapsedFolders` is the
// one piece of view state this file owns that has no server counterpart at all, session-only,
// the same shape as `store.ts`'s own board `collapsed` id list.

import { toast } from '@konstantinopolskii/vue'
import type { InternalLink } from './bodyMarkdown'
import {
  ApiError,
  createDoc as apiCreateDoc,
  deleteDoc as apiDeleteDoc,
  fetchDocHistory,
  fetchDocRevision,
  fetchDocs,
  getDoc,
  restoreDoc as apiRestoreDoc,
  saveDoc as apiSaveDoc,
  type DocDetail,
  type DocRevisionDetail,
  type DocRevisionSummary,
  type DocSummary,
} from './api'

// --- folder tree (pure, no I/O) -----------------------------------------------------------------

export interface DocTreeFolder {
  /** This folder's own path segment, e.g. `"ai-native"` for `strategy/ai-native`. Empty at root. */
  name: string
  /** Full path from the root, e.g. `"strategy/ai-native"`. Empty at root — the collapse-state key. */
  path: string
  folders: DocTreeFolder[]
  docs: DocSummary[]
}

/** Groups the flat, path-ordered list `GET /api/docs` returns into a tree on `/`. A doc's path
 *  IS the hierarchy (`core/docs.py`'s own rule) — this is the one place that reads it as one. */
export function docTree(list: DocSummary[]): DocTreeFolder {
  const root: DocTreeFolder = { name: '', path: '', folders: [], docs: [] }
  for (const doc of list) {
    const segments = doc.path.split('/')
    segments.pop() // the filename itself; what remains are folder segments, possibly none
    let node = root
    let prefix = ''
    for (const segment of segments) {
      prefix = prefix ? `${prefix}/${segment}` : segment
      let child = node.folders.find((f) => f.name === segment)
      if (!child) {
        child = { name: segment, path: prefix, folders: [], docs: [] }
        node.folders.push(child)
      }
      node = child
    }
    node.docs.push(doc)
  }
  return root
}

// --- reactive slice ------------------------------------------------------------------------------

export interface DocsState {
  list: DocSummary[]
  listLoading: boolean
  currentId: string | null
  current: DocDetail | null
  currentLoading: boolean
  /** Folder paths currently folded shut. A folder not in this list renders expanded — the same
   *  "expanded by default" default `store.ts`'s own `collapsed` (subtask lists) uses. */
  collapsedFolders: string[]
  historyOpen: boolean
  history: DocRevisionSummary[] | null
  historyLoading: boolean
  /** A single old revision's full text, read-only, shown while `historyOpen`. Null = the history
   *  list itself is showing, not one revision's text. */
  viewingRevision: DocRevisionDetail | null
}

export function createInitialDocsState(): DocsState {
  return {
    list: [],
    listLoading: false,
    currentId: null,
    current: null,
    currentLoading: false,
    collapsedFolders: [],
    historyOpen: false,
    history: null,
    historyLoading: false,
    viewingRevision: null,
  }
}

interface Deps {
  reportError: (err: unknown) => void
  /** `store.ts`'s own `navigateToGoal` (D248 WP-D) — a doc's linked-goal chip reuses the exact
   *  navigation goals already use everywhere else; this module never resolves a board host
   *  itself, the "one navigation path" rule the task brief states explicitly. */
  navigateToGoal: (id: string) => Promise<void>
  /** `store.ts::setView` — switches the app shell to the Docs view before opening a doc reached
   *  from a goal's own doc chip (`openDocFromGoal` below). */
  setView: (view: 'verticals' | 'inbox' | 'docs') => void
}

export function createDocsView(state: { docs: DocsState }, deps: Deps) {
  async function loadDocs(): Promise<void> {
    state.docs.listLoading = true
    try {
      const res = await fetchDocs()
      state.docs.list = res.docs
    } catch (err) {
      deps.reportError(err)
    } finally {
      state.docs.listLoading = false
    }
  }

  /** Keeps `list` (the tree's own data) in sync with whatever a write just returned, without a
   *  full `loadDocs()` round trip — same "reconcile from the write's own response" shape
   *  `store.ts`'s goal writes use throughout. */
  function patchListEntry(doc: DocDetail): void {
    const summary: DocSummary = {
      id: doc.id, path: doc.path, title: doc.title, updated_at: doc.updated_at, revision: doc.revision,
    }
    const at = state.docs.list.findIndex((d) => d.id === doc.id)
    const next = at === -1 ? [...state.docs.list, summary] : state.docs.list.map((d, i) => (i === at ? summary : d))
    next.sort((a, b) => a.path.localeCompare(b.path))
    state.docs.list = next
  }

  /** Opens `id` in the right pane — the tree click, the goal-chip jump, and the `#doc/<id>` boot
   *  fragment (`main.ts`) all land here. A cached detail is not kept (unlike goals' `detailCache`
   *  — the doc list is small and always freshly fetched, S-104's staleness concern does not
   *  apply at this scale), so every open shows a loading state unless it is already the open doc. */
  async function openDoc(id: string): Promise<void> {
    const alreadyOpen = state.docs.currentId === id && state.docs.current !== null
    state.docs.currentId = id
    state.docs.historyOpen = false
    state.docs.history = null
    state.docs.viewingRevision = null
    state.docs.currentLoading = !alreadyOpen
    if (!alreadyOpen) state.docs.current = null
    history.pushState(null, '', `#doc/${id}`)
    try {
      const doc = await getDoc(id)
      if (state.docs.currentId === id) state.docs.current = doc
    } catch (err) {
      deps.reportError(err)
    } finally {
      if (state.docs.currentId === id) state.docs.currentLoading = false
    }
  }

  function closeDoc(): void {
    state.docs.currentId = null
    state.docs.current = null
    state.docs.historyOpen = false
    state.docs.history = null
    state.docs.viewingRevision = null
    history.pushState(null, '', location.pathname + location.search)
  }

  /** Reached from a goal detail's own doc chip (`GoalDetail.vue`) — switches the shell to Docs
   *  and opens the target in one call, the doc-side mirror of `navigateToGoal`. */
  function openDocFromGoal(id: string): void {
    deps.setView('docs')
    void openDoc(id)
  }

  /** A body names a doc by PATH (`core/docs.py::extract_links`), so the tree list resolves it —
   *  refetched first: the target may postdate the last load, or nothing has loaded the list yet. */
  async function openDocByPath(path: string): Promise<void> {
    await loadDocs()
    const found = state.docs.list.find((d) => d.path === path)
    if (!found) {
      toast(`No document at ${path}.`)
      return
    }
    deps.setView('docs')
    await openDoc(found.id)
  }

  /** One dispatch for an in-app link clicked in any rendered body (`bodyMarkdown.ts::internalLinkOf`). */
  function followBodyLink(link: InternalLink): Promise<void> {
    return link.kind === 'goal' ? deps.navigateToGoal(link.target) : openDocByPath(link.target)
  }

  /** `path` alone creates at the root; a path containing `/` creates (and, on the client, renders)
   *  every intermediate folder — `docTree` above has no folder table to pre-populate, so nothing
   *  extra needs to happen here beyond the one `POST`. */
  async function createDoc(path: string, title: string | null = null): Promise<boolean> {
    try {
      const created = await apiCreateDoc({ path, title: title ?? undefined, body: '' })
      patchListEntry(created)
      state.docs.currentId = created.id
      state.docs.current = created
      state.docs.currentLoading = false
      state.docs.historyOpen = false
      history.pushState(null, '', `#doc/${created.id}`)
      return true
    } catch (err) {
      deps.reportError(err)
      return false
    }
  }

  /** One save call for title/body/path — `core.docs.save()`'s own "only the given fields land"
   *  contract, unchanged here. `id`/`expectedRevision` are explicit, never read off `state.docs.
   *  current` implicitly: `DocDetail.vue`'s body editor debounces saves and is keyed/remounted
   *  per doc, so a save queued before a doc switch must still land on the RIGHT doc with the
   *  RIGHT revision even after the component that queued it has unmounted — the same reason
   *  `store.ts::updateGoal(id, patch)` takes an explicit id rather than "whichever goal is open".
   *  The write-back to shared state is still guarded (`state.docs.currentId === id`), same shape
   *  `detailSurface.ts::openGoal`'s own stale-response guard uses, so a late response for a doc
   *  the user has since navigated away from never repaints the wrong panel.
   *
   *  A stale `expected_revision` (another tab, or an agent write, saved first) is a 409: never
   *  silently overwritten — a toast names the conflict and offers Reload, the house pattern
   *  `store.ts::removeGoal`'s own 409 branch already uses for the same reason. Returns the fresh
   *  doc on success (callers track their own revision forward from it) or null on failure. */
  async function saveDoc(
    id: string,
    expectedRevision: number,
    patch: { title?: string | null; body?: string; path?: string },
  ): Promise<DocDetail | null> {
    try {
      const updated = await apiSaveDoc(id, { expected_revision: expectedRevision, ...patch })
      // `routes_docs.py::save_doc` never recomputes `linked_goals` on its own response (only a
      // fresh `GET` passes `links`) — re-read whenever the body actually changed, since that is
      // the only edit that can move the link table; a title/path-only save keeps whatever list
      // is currently shown (falling back to empty only if this doc is not even the open one).
      const fresh = patch.body !== undefined
        ? await getDoc(id)
        : { ...updated, linked_goals: state.docs.currentId === id ? (state.docs.current?.linked_goals ?? []) : [] }
      if (state.docs.currentId === id) state.docs.current = fresh
      patchListEntry(fresh)
      return fresh
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) {
        toast('This document changed elsewhere — your edit was not saved.', {
          action: 'Reload', onAction: () => void openDoc(id),
        })
        return null
      }
      deps.reportError(err)
      return null
    }
  }

  /** Refused (422) while any `goal_doc_links` row still references this doc — `ApiError.message`
   *  already names every linked goal id (`core.docs.delete()`'s own docstring), so surfacing it
   *  verbatim is the whole job; nothing here re-derives or re-words the server's own refusal. */
  async function deleteCurrentDoc(): Promise<boolean> {
    const current = state.docs.current
    if (!current) return false
    try {
      await apiDeleteDoc(current.id)
      state.docs.list = state.docs.list.filter((d) => d.id !== current.id)
      closeDoc()
      return true
    } catch (err) {
      deps.reportError(err)
      return false
    }
  }

  async function loadHistory(): Promise<void> {
    const current = state.docs.current
    if (!current) return
    state.docs.historyOpen = true
    state.docs.viewingRevision = null
    state.docs.historyLoading = true
    try {
      state.docs.history = (await fetchDocHistory(current.id)).revisions
    } catch (err) {
      deps.reportError(err)
    } finally {
      state.docs.historyLoading = false
    }
  }

  function closeHistory(): void {
    state.docs.historyOpen = false
    state.docs.history = null
    state.docs.viewingRevision = null
  }

  async function viewRevision(revision: number): Promise<void> {
    const current = state.docs.current
    if (!current) return
    try {
      state.docs.viewingRevision = await fetchDocRevision(current.id, revision)
    } catch (err) {
      deps.reportError(err)
    }
  }

  /** Back from a read-only revision to the history list itself (not to the live doc). */
  function backToHistoryList(): void {
    state.docs.viewingRevision = null
  }

  /** Restoring copies the old text forward as a NEW revision — `core.docs.restore()`'s own
   *  docstring, "never a rewind" — so the toast says exactly that rather than implying the old
   *  revision number came back. Same 409 conflict handling as `saveDoc`. */
  async function restoreRevision(revision: number): Promise<boolean> {
    const current = state.docs.current
    if (!current) return false
    try {
      const restored = await apiRestoreDoc(current.id, revision, current.revision)
      state.docs.current = await getDoc(restored.id)
      patchListEntry(state.docs.current)
      closeHistory()
      toast(`Restored revision ${revision}'s text as a new revision.`)
      return true
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) {
        toast('This document changed elsewhere — restore it again after reloading.', {
          action: 'Reload', onAction: () => void openDoc(current.id),
        })
        return false
      }
      deps.reportError(err)
      return false
    }
  }

  function toggleFolder(path: string): void {
    const at = state.docs.collapsedFolders.indexOf(path)
    if (at === -1) state.docs.collapsedFolders.push(path)
    else state.docs.collapsedFolders.splice(at, 1)
  }

  function isFolderCollapsed(path: string): boolean {
    return state.docs.collapsedFolders.includes(path)
  }

  return {
    loadDocs, openDoc, closeDoc, openDocFromGoal, openDocByPath, followBodyLink, createDoc, saveDoc,
    deleteCurrentDoc,
    loadHistory, closeHistory, viewRevision, backToHistoryList, restoreRevision,
    toggleFolder, isFolderCollapsed,
  }
}
