// Sources (docs/design/sources.md; the app's side of core/sources.py): the documents the morning report reads from, each
// with the state its check last left. The app checks every source every hour with no model; here the Inbox's third row
// draws them as document chips, and a source's window carries its state, the exact check, Approve for a check that waits
// (every check reaches something, so each waits for you first, once), and Fix on a red one.
//
// What a state says (the words are the design's): "checked 07:00"; in red "not answering since 06:00", only after two
// failures at least five minutes apart; and grey, which is never red, when the answer cannot be trusted now: "waiting for
// your approval", "not checked yet", "not checked since 23:10" (the Mac was asleep for over two hours).
//
// Fix is the smallest first look: one click opens a conversation about the source with the failure in its first sentence.
// The agent never comes by itself; an automatic first look would send this same message from the one place the app
// already starts a turn on its own (lib/morning.ts), once per incident (`SourceView.since` names it).
import { computed, reactive } from '../reactivity'
import { agentChat, newThread, send } from './agentChat'
import { ApiError, approveSource, fetchSources, type DeskDoc, type SourceView } from './api'
import { shortDay } from './docsDesk'
import { isoDate } from './schedule'

/** A source is a document under this path (`core/source_checks.py::PREFIX`). */
export const SOURCES_PATH = 'sources/'
export const isSourcePath = (path: string): boolean => path.startsWith(SOURCES_PATH)

export const sources = reactive({ list: [] as SourceView[], loaded: false })

let epoch = 0
/** Read again whenever the board changes: every answer the timer keeps rings the same bell as a goal's change. */
export async function loadSources(): Promise<void> {
  const mine = ++epoch
  try {
    const { sources: list } = await fetchSources()
    if (mine !== epoch) return
    sources.list = list
    sources.loaded = true
  } catch {
    // The next change asks again.
  }
}

export const sourceOf = (id: string): SourceView | null => sources.list.find((s) => s.id === id) ?? null

/** A source is a document under `sources/` with a check (`core/sources.py::sources`): the list is the judge, not the path.
 *  A document there with no check is a plain document, and stands in Documents. */
export const isSource = (id: string): boolean => sourceOf(id) !== null

/** The app's own check of the agent's servers (`kind` connections) is nothing to read: not a source the report counts. */
export const realSources = computed(() => sources.list.filter((s) => s.kind !== 'connections'))

/** The servers the Connections check found answering, from its one line ("all 3 answer: chat, mail, calendar"). */
export function serversOf(connections: SourceView | null): string[] {
  const head = (connections?.detail ?? '').split(';')[0] ?? ''
  const at = head.indexOf(': ')
  return at < 0 ? [] : head.slice(at + 2).split(',').map((name) => name.trim()).filter(Boolean)
}

const named = (names: string[]): string => (names.length === 1 ? names[0]! : `${names.slice(0, -1).join(', ')} and ${names[names.length - 1]}`)

/** The one line the row says while there is no source yet: where sources come from, and what to do. The morning report says
 *  the same line in its red block. */
export function noSourcesLine(): string {
  const servers = serversOf(sources.list.find((s) => s.kind === 'connections') ?? null)
  return servers.length
    ? `No sources yet. The agent reaches ${named(servers)}. Tell it what to read each morning, in one sentence.`
    : 'No sources yet. Tell the agent what to read each morning, in one sentence.'
}

const two = (n: number) => String(n).padStart(2, '0')

/** A moment as a state says it: the time today, the day and the time before that ("1 Oct, 23:10"). */
export function clockOf(iso: string): string {
  const d = new Date(iso)
  const time = `${two(d.getHours())}:${two(d.getMinutes())}`
  return isoDate(d) === isoDate(new Date()) ? time : `${shortDay(iso)}, ${time}`
}

export interface SourceNote { text: string; tone: 'ok' | 'grey' | 'red' }

/** The line under a source's name. */
export function noteOf(s: SourceView): SourceNote {
  if (s.status === 'red') return { text: `not answering since ${clockOf(s.since ?? s.checked_at ?? s.updated_at)}`, tone: 'red' }
  if (s.status === 'ok') return { text: `checked ${clockOf(s.checked_at ?? s.updated_at)}`, tone: 'ok' }
  switch (s.why) {
    case 'waiting': return { text: 'waiting for your approval', tone: 'grey' }
    case 'stale': return { text: `not checked since ${clockOf(s.checked_at ?? s.updated_at)}`, tone: 'grey' }
    case 'new': return { text: 'not checked yet', tone: 'grey' }
    case 'unreadable': return { text: 'check can’t be read', tone: 'grey' }
    default: return { text: 'no check yet', tone: 'grey' }
  }
}

/** A source as the document chip needs it. The chip draws the page from the top of the text the list already carries. */
export function cardOf(s: SourceView): Pick<DeskDoc, 'id' | 'title' | 'path' | 'excerpt' | 'created_at' | 'updated_at'> {
  return { id: s.id, title: s.title, path: s.path, excerpt: s.excerpt ?? '', created_at: s.updated_at, updated_at: s.updated_at }
}

/** The window's line under the state: what the last answer said when that is news. A pass says nothing the check in words
 *  does not ("HTTP 200"), unless it read a number ("71 from '71% of'"); a first failure says what failed and when the app
 *  looks again; a red source says what failed; grey has no answer to read, but a check nobody can read says why. */
export function detailOf(s: SourceView): string {
  if (s.status === 'grey') return s.why === 'unreadable' ? (s.error ?? '') : ''
  if (s.status === 'red') return s.detail
  if (s.failures > 0) return s.next_check_at ? `${s.detail}; looking again at ${clockOf(s.next_check_at)}` : s.detail
  return s.value === null ? '' : s.detail
}

/** Approve: the owner approves the exact check they were shown. A check edited since is refused by the server (409): the
 *  list is read again, so the new text is what they see next, and the word says why. */
export async function approve(s: SourceView): Promise<'approved' | 'changed' | 'failed'> {
  if (!s.check_hash) return 'failed'
  try {
    const view = await approveSource(s.id, s.check_hash)
    const at = sources.list.findIndex((x) => x.id === s.id)
    if (at >= 0) sources.list[at] = { ...sources.list[at]!, ...view }
    return 'approved'
  } catch (error) {
    await loadSources()
    return error instanceof ApiError && error.status === 409 ? 'changed' : 'failed'
  }
}

/** Fix: the first sentence is the failure; the document holds what may be fixed. */
export const fixAsk = (s: SourceView): string =>
  `Fix the source “${s.title || s.path}”: not answering since ${clockOf(s.since ?? s.checked_at ?? s.updated_at)}, ${s.detail}. `
  + `Read its document (${s.path}), say what the failure means, and make only the fixes it allows.`

export function fixSource(s: SourceView): void {
  if (!agentChat.available || s.status !== 'red') return
  newThread()
  agentChat.open = true
  agentChat.engaged = true
  void send(fixAsk(s))
}
