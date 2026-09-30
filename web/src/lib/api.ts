// Typed HTTP client for /api/* (docs/ARCHITECTURE.md §1: FastAPI transport). Wire shapes below
// mirror verticals/api/schemas.py (WP-15) field-for-field — read, never imported, since Python and
// TypeScript cross no boundary here. Every path is relative ("/api/..."), never an absolute
// cross-origin URL: S-114/S-125 require the shipped app to issue zero cross-origin requests
// (verticals/api/app.py adds no CORSMiddleware, on purpose), so same-origin is not a convenience
// here, it is the one thing this file must never break.
//
// Auth, and a gap this file had to close on its own: every /api/* route requires
// `Authorization: Bearer <token>` (verticals/api/deps.py::verify_bearer_token), the token is
// env-injected server-side only (verticals/config.py — the process never generates one), and
// docs/ACCEPTANCE.md AC-192 forbids a login form, so nothing in the shipped documents states how
// a browser tab with no sign-in step is supposed to learn that value. Decision (none of the docs
// settle this, so it is recorded here rather than left implicit): the token is baked into the
// static build at `vite build` time via Vite's own `import.meta.env.VITE_*` convention and read
// once below. A deploy sets `VITE_VERTICALS_TOKEN` to the same value as the server's own
// `VERTICALS_TOKEN` before running `npm run build` — one secret, two env var names, because one
// crosses into a public JS bundle and the other must never leave the server process.
// `tests/ui/conftest.py` controls both halves for the suite and keeps them equal by construction.
// This is the plain consequence of "single owner, no login": whoever can load the page at all is
// already the one person this deployment serves.

import type { VerticalScale } from './periods'

const TOKEN = (import.meta.env.VITE_VERTICALS_TOKEN as string | undefined) ?? ''

// --- wire shapes, mirroring verticals/api/schemas.py exactly ------------------------------------

export interface RepeatRule {
  frequency: 'daily' | 'weekly' | 'monthly' | 'quarterly' | 'yearly' | 'every_decade'
  interval: number
  weekdays?: number[]
  month_days?: number[]
  months?: number[]
  quarters?: number[]
  end_date?: string | null
}

/** Every field `schemas.py::goal_to_card` puts on a board/search/bulk-result card. Never carries
 *  `body` — only a single-goal detail response does (S-33: "No card in the response carries
 *  body; each carries body_chars"). */
export interface GoalCard {
  id: string
  owner: string
  parent_id: string | null
  depth: number
  vertical: string | null
  anchor_date: string | null
  period_key: string | null
  title: string
  body_chars: number
  color: string | null
  tags: string[]
  done_at: string | null
  position: number
  origin: string
  created_at: string
  updated_at: string
  repeat: RepeatRule | null
  parked_from_vertical: string | null
  foil: boolean
  carryover_ignored_until: string | null
  size_expected: string[] | null
  size_actual: string[] | null
  /** Board-only decoration. Absent on detail/search cards. */
  ghost?: boolean
  /** End of the shown period; Ignore writes this exact date. */
  ghost_until?: string | null
}

export interface AncestorRef {
  id: string
  title: string
  vertical: string | null
}

/** `DocLink.inherited_from` (D251, KK 2026-08-20) — the ancestor goal whose own link a doc
 *  "ghosts" down from; `null` on `GoalDocLink` means the goal links it directly (own). */
export interface GoalDocInheritedFrom {
  id: string
  title: string
}

/** `schemas.py::goal_to_detail`'s `docs` field (D250, WP-1; D251) — every doc this goal links to
 *  or is linked from directly (own, `inherited_from: null`), PLUS every doc linked to any
 *  ancestor (inherited, `inherited_from` names the nearest one) — own entries sort first, so a
 *  renderer draws ghosted chips after the real ones without re-sorting itself. Never a doc's own
 *  body; a caller that wants the text follows up with `GET /api/docs/{id}` (`getDoc` below). */
export interface GoalDocLink {
  id: string
  path: string
  title: string | null
  source: 'doc' | 'goal'
  inherited_from: GoalDocInheritedFrom | null
}

export interface GoalDetail extends GoalCard {
  body: string
  ancestors: AncestorRef[]
  children: GoalCard[]
  ideas: GoalCard[]
  docs: GoalDocLink[]
}

/** `vertical`/`period_key` are both `null` for exactly one column: `core/board.py::_column_for`'s
 *  `MAYBE_KEY` branch returns `Column(vertical=None, period_key=None, label="Maybe", goals=goals)`
 *  — `schemas.py::board_to_json` serializes `col.vertical`/`col.period_key` verbatim, so this is a
 *  real wire nullable, not a defensive `| null` added out of caution. */
export interface BoardColumn {
  vertical: string | null
  period_key: string | null
  label: string
  goals: GoalCard[]
}

/** `GET /api/board` (`schemas.py::board_to_json`) — mirrors `models.Board` field for field;
 *  `progress`/`ancestors`/`children` are keyed by goal id and stay top-level, not folded into
 *  each card (that is `core/board.py`'s own choice, not this transport's). */
export interface BoardResponse {
  owner: string
  anchor_date: string
  columns: BoardColumn[]
  progress: Record<string, { done: number; total: number }>
  ancestors: Record<string, AncestorRef[]>
  children: Record<string, GoalCard[]>
  /** `SELECT count(*) FROM goals WHERE parent_id = id`, keyed over both levels the board draws —
   *  the cards *and* the children listed under them. `children` is keyed by cards alone, so a
   *  nested card's count cannot be read off it (`docs/PENDING_DOC_FIXES.md` rows 93, 116(a)). */
  child_counts: Record<string, number>
  /** D239: the value menu's one-word labels, keyed by value-root id, sparse — only values that
   *  actually carry one appear; the nav falls back to the title's first word for the rest. */
  short_labels: Record<string, string>
  /** D240: the menu's value list — every parentless life goal, life-column order, NEVER
   *  narrowed by the value filter. The life column itself narrows with the rest of the board,
   *  so the nav must read this list, not the column, or the active filter would eat its own
   *  escape hatch. */
  values: GoalCard[]
}

export interface SearchResponse {
  goals: GoalCard[]
  truncated: boolean
}

/** One goal of a match's chain, root first (`GET /api/search?with=parents`). */
export interface SearchParent {
  id: string
  parent_id: string | null
  title: string
  vertical: string | null
  anchor_date: string | null
  period_key: string | null
  done_at: string | null
  position: number
}

export interface FindResponse extends SearchResponse {
  parents: Record<string, SearchParent[]>
}

export interface TagMeta {
  tag: string
  project: boolean
}

export interface TagsResponse {
  tags: TagMeta[]
}

/** The body of `PATCH /api/goals/{id}` and the bulk form's `patch` field — every key optional,
 *  and only the keys actually present are sent (`buildPatch` below), matching `core.goals.
 *  update()`'s "omitted vs. sent as null" distinction (color's own null-clears-itself case). */
export interface UpdatePatch {
  /** Reorder within the current sibling group: place this goal immediately after `after_id`.
   *  `routes_goals.py::patch_goal` dispatches it to `core.moves.move_between` and refuses it in
   *  the same call as any content field, so `store.ts::reorderAfter` sends it alone. */
  after_id?: string
  /** The one ordering step `after_id` cannot name: `'first'` moves this goal to the top of its
   *  own sibling group (`docs/PENDING_DOC_FIXES.md` rows 109, 116(c)). Sent alone, same as
   *  `after_id`, and never together with it — the route refuses both in one call. */
  position?: 'first'
  title?: string
  body?: string
  color?: string | null
  tags?: string[]
  done?: boolean
  foil?: boolean
  carryover_ignored_until?: string | null
  repeat?: RepeatRule | null
  /** Compact notation (`2x45-120 1x10-15`), canonical token array, or null to clear. */
  size_expected?: string | string[] | null
}

export interface CreateGoalPayload {
  title: string
  vertical?: string | null
  anchor_date?: string | null
  parent_id?: string | null
  body?: string
  color?: string | null
  tags?: string[]
}

// --- errors --------------------------------------------------------------------------------
//
// api/errors.py sends three different body shapes depending on which layer refused the call:
// pydantic's own 422 (`{"detail": [{"loc": [...], "msg": ..., "type": ...}]}`), FastAPI's default
// HTTPException shape for the 401 bearer-token path (`{"detail": "<string>"}`), and the
// VerticalError table's 404/409/503/500 shape (`{"error": "<code>", "detail": ...}`, and 404
// omits `detail` entirely — S-41's byte-identical-404 rule). Callers of this module see one
// normalized shape regardless of which of the three produced it.

export class ApiError extends Error {
  readonly status: number
  readonly body: unknown
  constructor(status: number, message: string, body: unknown) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.body = body
  }
}

/** The one string this module shows when the server did not answer with something it can explain.
 *  Two callers: `messageFrom`'s fallback (an HTTP answer whose body carries neither `detail` nor
 *  `error` — a dead upstream behind the static server answers the proxied call with exactly that,
 *  a bare 502) and `request`'s network-failure branch (`fetch` rejecting with a `TypeError`, no
 *  status at all). Both are the same condition to a reader: the backend is not reachable.
 *  docs/E2E.md S-75 requires sentence case and a message naming the condition rather than a
 *  status code; the code is kept as a trailing parenthetical where there is one, because a
 *  number that helps whoever reads the console costs the reader nothing at the front of the
 *  sentence. Wording and tone are the owner's call — this is the plain, conventional version. */
const UNREACHABLE = 'Could not reach the server'

function messageFrom(status: number, body: unknown): string {
  if (body && typeof body === 'object') {
    const b = body as Record<string, unknown>
    if (Array.isArray(b.detail) && b.detail[0] && typeof b.detail[0] === 'object') {
      const first = b.detail[0] as Record<string, unknown>
      if (typeof first.msg === 'string') return first.msg
    }
    if (typeof b.detail === 'string') return b.detail
    if (typeof b.error === 'string') return b.error
  }
  return `${UNREACHABLE} (HTTP ${status}).`
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers)
  /* The bundle ships with an EMPTY token by design (Dockerfile: no secret in any layer) — the
     proxy in front injects the real bearer. Setting `Authorization: Bearer <empty>` anyway is
     not harmless: a fetch-supplied Authorization header REPLACES the basic-auth credentials the
     browser would otherwise attach, so behind an `auth_basic` gate (prod) every API call arrived
     credential-less and 401'd, re-prompting forever while `GET /` succeeded with the same
     password. Send the header only when a token actually exists. */
  if (TOKEN) headers.set('Authorization', `Bearer ${TOKEN}`)
  if (init.body !== undefined) headers.set('Content-Type', 'application/json')
  // `fetch` rejects with a `TypeError` — no status, no body — when the request never got an HTTP
  // answer at all (DNS, connection refused, the tab going offline). Left unhandled it escapes as
  // a bare "Failed to fetch" from the browser's own vocabulary; normalized here to the same
  // `ApiError` shape every other failure in this module produces, so `store.ts` has one branch,
  // not two. `status: 0` is the conventional "no HTTP response" marker (`XMLHttpRequest.status`
  // has used it for exactly this since forever) and is never a real HTTP status.
  let res: Response
  try {
    res = await fetch(path, { ...init, headers })
  } catch (err) {
    throw new ApiError(0, `${UNREACHABLE}.`, err)
  }
  // §4's bodies are always JSON, including every error shape above, so an empty body is the
  // only legal non-JSON case (204). Consume even that empty response before returning: resolving
  // from headers alone leaves Chromium's request lifecycle as `net::ERR_ABORTED`, despite the
  // successful 204, and makes the harness report a failed request after the optimistic delete.
  const text = await res.text()
  if (res.status === 204) return undefined as T
  // Anything else parses or the response is malformed enough that surfacing the raw parse error
  // is more honest than swallowing it.
  const body = text ? JSON.parse(text) : null
  if (!res.ok) throw new ApiError(res.status, messageFrom(res.status, body), body)
  return body as T
}

function qs(params: Record<string, string | number | boolean | undefined>): string {
  const search = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== '') search.set(key, String(value))
  }
  const s = search.toString()
  return s ? `?${s}` : ''
}

// --- routes (verticals/api/routes_board.py, routes_goals.py) ------------------------------------

/** `GET /api/board?date=...` — `date` is required, no client-invented default (routes_board.py's
 *  own docstring: guessing "today" is a product decision `core/` does not make, so a caller that
 *  means today sends today's date explicitly — see `todayIso()` in `store.ts`).
 *  `value` (D233) is the value filter: a parentless life-vertical goal's id; omitted = full
 *  board. `qs` drops null/undefined keys, so the unfiltered call's URL is byte-identical to
 *  what it was before the parameter existed. */
export function fetchBoard(date: string, value: string | null = null): Promise<BoardResponse> {
  return request<BoardResponse>(`/api/board${qs({ date, value: value ?? undefined })}`)
}

export function fetchTags(): Promise<TagsResponse> {
  return request<TagsResponse>('/api/tags')
}

/** `GET /api/search` — S-125's route. `core.search.search`'s own `ValidationError` fires
 *  ("needs at least one of q, tag or vertical") if every filter is omitted; this function does not
 *  pre-empt that, callers decide what "no filter" should mean to them. */
export function searchGoals(params: {
  q?: string
  tag?: string
  vertical?: string
  limit?: number
}): Promise<SearchResponse> {
  return request<SearchResponse>(`/api/search${qs(params)}`)
}

/** The board's finding: titles and notes, every period, each match's parents (docs/design-handoff S1.P3). */
export function findGoals(q: string): Promise<FindResponse> {
  return request<FindResponse>(`/api/search${qs({ q, with: 'parents', limit: 200 })}`)
}

export function createGoal(payload: CreateGoalPayload): Promise<GoalCard> {
  return request<GoalCard>('/api/goals', { method: 'POST', body: JSON.stringify(payload) })
}

/** `prefetch` marks the D226 cache-warming sweep's reads on the wire (`?prefetch=1`, ignored by
 *  the server). The sweep is best-effort by design, so its one benign failure mode — a goal
 *  deleted between queueing and fetching answers 404 — must be tellable apart from a real
 *  user-initiated open gone wrong, both in logs and in the ui harness's >=400 gate. */
export function getGoal(id: string, prefetch = false): Promise<GoalDetail> {
  return request<GoalDetail>(
    `/api/goals/${encodeURIComponent(id)}${qs({ prefetch: prefetch ? '1' : undefined })}`
  )
}

export function patchGoal(id: string, patch: UpdatePatch, keepalive = false): Promise<GoalCard> {
  return request<GoalCard>(`/api/goals/${encodeURIComponent(id)}`, {
    method: 'PATCH',
    body: JSON.stringify(patch),
    keepalive,
  })
}

/** `POST /api/goals/{id}/due_ack` (011). Acknowledge the goal's current dueness with a verdict;
 *  'done_on_time' also completes the goal server-side. Returns the stored acknowledgment row. */
export function dueAckGoal(
  id: string,
  verdict: 'overdue' | 'done_on_time',
  note: string | null = null,
): Promise<{
  goal_id: string
  vertical: string
  period_key: string
  verdict: string
  note: string | null
  acknowledged_at: string
}> {
  return request(`/api/goals/${encodeURIComponent(id)}/due_ack`, {
    method: 'POST',
    body: JSON.stringify({ verdict, note }),
  })
}

export function patchGoalsBulk(
  ids: string[],
  patch: UpdatePatch,
): Promise<{ updated: number; goals: GoalCard[] }> {
  return request(`/api/goals`, {
    method: 'PATCH',
    body: JSON.stringify({ ids, patch }),
  })
}

/** `PUT /api/goals/{id}/schedule`. Both fields together, or both `null` to clear (core.moves.
 *  schedule's own contract) — this function does not special-case `null`, it just forwards
 *  whatever the caller decided. */
/** The optional ordered slot inside the DESTINATION column. A drag names a column and a place in
 *  it in one gesture, so the wire takes both in one request — two requests would put a second
 *  round-trip inside the drop tail. Same two spellings, and the same one-of-two rule, as
 *  `UpdatePatch`. */
export interface ScheduleOrdering {
  after_id?: string
  position?: 'first'
}

export interface ScheduleResult extends GoalCard {
  descendants_clamped: number
}

export function scheduleGoal(
  id: string,
  vertical: VerticalScale | null,
  anchorDate: string | null,
  ordering?: ScheduleOrdering,
): Promise<ScheduleResult> {
  return request<ScheduleResult>(`/api/goals/${encodeURIComponent(id)}/schedule`, {
    method: 'PUT',
    body: JSON.stringify({ vertical, anchor_date: anchorDate, ...ordering }),
  })
}

/** `PUT /api/goals/{id}/parent`. `parentId: null` detaches to root. WP-22 does not call this
 *  itself (S-67 reparent is WP-23's scenario) — kept here, typed and tested by construction
 *  against the same wire contract as every other route, so WP-23 has no client-layer work left. */
export function reparentGoal(id: string, parentId: string | null): Promise<GoalCard> {
  return request<GoalCard>(`/api/goals/${encodeURIComponent(id)}/parent`, {
    method: 'PUT',
    body: JSON.stringify({ parent_id: parentId }),
    // Reparent paints optimistically before this promise resolves. Keep the already-started,
    // tiny write alive if its tab unloads in that interval; this does not delay local placement.
    keepalive: true,
  })
}

export function parkGoal(id: string): Promise<GoalCard> {
  return request<GoalCard>(`/api/goals/${encodeURIComponent(id)}/park`, { method: 'POST' })
}

/** `DELETE /api/goals/{id}?cascade=`. Without `cascade`, a non-empty subtree is `core.goals.
 *  delete`'s own `HasChildren` (409) — the caller decides whether to retry with cascade, this
 *  function never guesses. `store.ts::removeSample` is the one caller today. */
export function deleteGoal(id: string, cascade = false): Promise<void> {
  return request<void>(`/api/goals/${encodeURIComponent(id)}${qs({ cascade })}`, {
    method: 'DELETE',
  })
}

/** D237: open the SSE change feed. Raw `fetch`, not `request()` — the body is an endless
 *  event-stream, not JSON — and never `EventSource`, which cannot carry the Authorization
 *  header this house refuses to put in a URL. The caller owns parsing and reconnects
 *  (lib/liveUpdates.ts); this just applies the same auth rule as every other call here. */
export function openEventStream(signal: AbortSignal): Promise<Response> {
  const headers = new Headers()
  if (TOKEN) headers.set('Authorization', `Bearer ${TOKEN}`)
  return fetch('/api/events', { headers, signal })
}

// --- documents (verticals/api/routes_docs.py, schemas.py — D250, WP-1) --------------------------
//
// Wire shapes mirror `schemas.py`'s own doc functions field-for-field, same rule this whole file
// states once at the top. `linked_goals`/`GoalDocLink` above are two mirrored halves of the same
// link table (`core.docs.links_for_doc`/`links_for_goal`) — a doc names the goals that reference
// it or that it references, a goal names the docs the other way round.

/** `GET /api/docs` (the folder tree source) — `schemas.py::doc_to_summary`, never `body`. A
 *  client derives its own folder grouping from `path`'s own `/` separators (`lib/docsView.ts`'s
 *  `docTree` — `core/docs.py`'s own docstring: no folder table either side of the wire). */
export interface DocSummary {
  id: string
  path: string
  title: string | null
  updated_at: string
  revision: number
}

/** A doc's own view of one link — the goal id/title and which side's text declared it
 *  (`schemas.py::doc_to_detail`'s `linked_goals`, `core.docs.links_for_doc`'s own return). */
export interface LinkedGoal {
  goal_id: string
  title: string
  source: 'doc' | 'goal'
}

/** Every other doc route — the one shape that carries the real `body` (`schemas.py::doc_to_detail`).
 *  `POST`/`PATCH`/`POST .../restore` never populate `linked_goals` on their own response
 *  (`routes_docs.py` passes `links` only on `GET` one) — a caller that needs it fresh after a
 *  body-changing write re-reads with `getDoc` (`lib/docsView.ts::saveDoc`/`restoreDoc` both do). */
export interface DocDetail {
  id: string
  owner: string
  path: string
  title: string | null
  body: string
  revision: number
  created_at: string
  updated_at: string
  linked_goals: LinkedGoal[]
}

/** One row of `GET /api/docs/{id}/history` — never `body` (`schemas.py::doc_revision_to_json`:
 *  `body_length` is the picker's own field, not a text preview). */
export interface DocRevisionSummary {
  revision: number
  path: string
  title: string | null
  saved_at: string
  body_length: number
}

/** `GET /api/docs/{id}/history/{revision}` — the one history-shaped response that does carry
 *  `body` (`schemas.py::doc_revision_detail_to_json`). */
export interface DocRevisionDetail {
  doc_id: string
  revision: number
  path: string
  title: string | null
  body: string
  saved_at: string
}

export function fetchDocs(): Promise<{ docs: DocSummary[] }> {
  return request('/api/docs')
}

/** `POST /api/docs`. A duplicate `(owner, path)` is a 422 naming `path` (`core.docs.create()`'s
 *  own docstring) — this function does not pre-empt that, same "the caller decides" rule every
 *  other write in this file follows. */
export function createDoc(payload: { path: string; title?: string | null; body?: string }): Promise<DocDetail> {
  return request<DocDetail>('/api/docs', { method: 'POST', body: JSON.stringify(payload) })
}

export function getDoc(id: string): Promise<DocDetail> {
  return request<DocDetail>(`/api/docs/${encodeURIComponent(id)}`)
}

/** `PATCH /api/docs/{id}`. `expected_revision` is required — there is no way to save a doc
 *  without naming the revision being built on (`core.docs.save()`'s own optimistic-lock
 *  contract); a stale value is a 409 (`ApiError.status === 409`), which the caller (`lib/
 *  docsView.ts`) turns into a reload-or-lose-this-edit toast rather than a silent overwrite. */
export function saveDoc(
  id: string,
  patch: { expected_revision: number; title?: string | null; body?: string; path?: string },
): Promise<DocDetail> {
  return request<DocDetail>(`/api/docs/${encodeURIComponent(id)}`, {
    method: 'PATCH',
    body: JSON.stringify(patch),
  })
}

export function fetchDocHistory(id: string): Promise<{ revisions: DocRevisionSummary[] }> {
  return request(`/api/docs/${encodeURIComponent(id)}/history`)
}

export function fetchDocRevision(id: string, revision: number): Promise<DocRevisionDetail> {
  return request<DocRevisionDetail>(`/api/docs/${encodeURIComponent(id)}/history/${revision}`)
}

/** `POST /api/docs/{id}/restore`. Copies `revision`'s own text forward as a NEW revision
 *  (`core.docs.restore()`'s own docstring — never a rewind); same `expected_revision` optimistic
 *  lock as `saveDoc`. */
export function restoreDoc(id: string, revision: number, expectedRevision: number): Promise<DocDetail> {
  return request<DocDetail>(`/api/docs/${encodeURIComponent(id)}/restore`, {
    method: 'POST',
    body: JSON.stringify({ revision, expected_revision: expectedRevision }),
  })
}

/** `DELETE /api/docs/{id}`. Refused (422, `ApiError.message` already names every linked goal id
 *  — `core.docs.delete()`'s own docstring) while any `goal_doc_links` row references this doc;
 *  the caller removes the link(s) from the relevant body first, same shape `deleteGoal`'s 409
 *  leaves to its own caller one route family over. */
export function deleteDoc(id: string): Promise<void> {
  return request<void>(`/api/docs/${encodeURIComponent(id)}`, { method: 'DELETE' })
}

// --- comments (verticals/api/routes_comments.py, schemas.py — WP-A, docs/COMMENTS_SPEC.md) ------
//
// Wire shapes mirror `api/schemas.py::comment_thread_to_json`/`comment_message_to_json` field for
// field, same rule this whole file states once at the top. There is no `author` field on any
// write here — `CreateCommentRequest`/`AddCommentMessageRequest` carry none, `extra="forbid"`
// refuses one a caller tries to add, and the route always writes `author='human'`
// (docs/COMMENTS_SPEC.md decision 4) — this file has nothing to set and nothing to hide.

export interface CommentAnchor {
  quote: string
  prefix: string
  suffix: string
}

export interface CommentMessage {
  id: string
  author: 'human' | 'agent'
  body: string
  created_at: string
}

export interface CommentThread {
  id: string
  goal_id: string | null
  doc_id: string | null
  anchor: CommentAnchor | null
  resolved_at: string | null
  created_at: string
  messages: CommentMessage[]
}

export function fetchGoalComments(goalId: string): Promise<{ threads: CommentThread[] }> {
  return request(`/api/goals/${encodeURIComponent(goalId)}/comments`)
}

export function fetchDocComments(docId: string): Promise<{ threads: CommentThread[] }> {
  return request(`/api/docs/${encodeURIComponent(docId)}/comments`)
}

/** `POST /api/comments`. Exactly one of `goal_id`/`doc_id` — `core.comments.create_thread`'s own
 *  refusal (422, field `goal_id,doc_id`) covers zero or both, same "the caller decides, this
 *  function does not pre-empt it" stance every other write in this file takes. */
export function createComment(payload: {
  goal_id?: string
  doc_id?: string
  body: string
  anchor?: CommentAnchor
}): Promise<CommentThread> {
  return request<CommentThread>('/api/comments', { method: 'POST', body: JSON.stringify(payload) })
}

export function addCommentMessage(threadId: string, body: string): Promise<CommentMessage> {
  return request<CommentMessage>(`/api/comments/${encodeURIComponent(threadId)}/messages`, {
    method: 'POST',
    body: JSON.stringify({ body }),
  })
}

export function resolveComment(threadId: string, resolved: boolean): Promise<CommentThread> {
  return request<CommentThread>(`/api/comments/${encodeURIComponent(threadId)}/resolve`, {
    method: 'POST',
    body: JSON.stringify({ resolved }),
  })
}
