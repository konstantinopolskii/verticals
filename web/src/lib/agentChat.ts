// The conversation with the agent (docs/design-handoff S2.P1): the client of the desktop gateway's /__chat/* routes,
// moved into the app from the script the gateway used to inject. The server and its event protocol stay as they are, and the
// conversations stored in localStorage (vt-chat:*) are read as they are, so none is lost. The web build has no gateway:
// the agent is unavailable there and the field only finds.
import { computed, reactive } from '../reactivity'
import { stepPhrase } from './agentSteps'
import { answersAvailable, refreshAnswers } from './answerUndo'
import { commandFilter } from './commandFilter'
import { goalChangesSince } from './goalChanges'

export interface AgentInfo {
  id: string
  label: string
  image: string
  available: boolean
  efforts: { value: string; label: string }[]
  defaultEffort: string
  fast: string
  permissions: { value: string; label: string; detail: string }[]
  defaultPermission: string
}
export interface ModelChoice { value: string; label: string; detail?: string; image?: string }
export interface Probe {
  available?: boolean
  models: ModelChoice[]
  modelsError?: string
  usage?: { state: string; message?: string; windows?: { label: string; remainingPercent: number }[] }
  loading?: boolean
  error?: boolean
}
export interface Selection { provider: string; model: string; effort: string; fast: boolean; permission: string }
export interface GoalRef { id: string; title: string }
export interface Thread {
  id: string
  title: string
  provider: string
  updatedAt: number
  status: 'idle' | 'working' | 'needs-you' | 'failed'
  goal?: GoalRef
  selection?: Selection
}
export type ChatEvent = { t: string; ts?: number; pending?: boolean; [key: string]: unknown }
export interface Ask {
  requestId: string
  title: string
  body: string
  options: { label: string; value: string }[]
  done: boolean
  chosen?: string
  /** The write the agent asks to make, as it calls it (the gateway sends it for a Claude ask): lib/askDetail.ts draws it. */
  tool?: string
  input?: Record<string, unknown>
}
export interface Balloon {
  key: string; who: 'you' | 'agent'; text: string; error?: boolean; ask?: Ask; pending?: boolean
  /** The answer the message belongs to: what its writes changed is kept under it (`lib/answerUndo.ts`). */
  answer?: string
}

const KEY = {
  threads: 'vt-chat:threads',
  current: 'vt-chat:current',
  events: (id: string) => `vt-chat:events:${id}`,
  cursor: (id: string) => `vt-chat:cursor:${id}`,
  lastSelection: 'vt-chat:last-model-selection',
  prefs: 'vt-chat:agent-prefs',
  lastAgent: 'vt-chat:last-agent',
}
const MAX_HISTORY = 1500

function load<T>(key: string, fallback: T): T {
  try {
    const value = localStorage.getItem(key)
    return value === null ? fallback : JSON.parse(value) as T
  } catch {
    return fallback
  }
}
function save(key: string, value: unknown): void {
  try { localStorage.setItem(key, JSON.stringify(value)) } catch { /* private mode: the conversation still runs */ }
}

export const agentChat = reactive({
  /** The gateway answered and at least one agent is installed. */
  available: false,
  checked: false,
  agents: [] as AgentInfo[],
  probes: {} as Record<string, Probe>,
  threads: load<Thread[]>(KEY.threads, []),
  current: load<string | null>(KEY.current, null),
  history: [] as ChatEvent[],
  cursor: { boot: null as string | null, seq: 0 },
  selection: null as Selection | null,
  running: false,
  /** The phrase of the step the agent is on while it works (S2.P3). */
  step: 'Thinking',
  /** The words of the last finished turn, for the circle while the conversation is hidden (S2.P4). */
  answer: null as { text: string; at: number; answer?: string } | null,
  /** The conversation shows over the board or the window (S2.P1). */
  open: false,
  /** You are talking with the agent: typing or a click on the field brings the conversation back; a second Esc leaves
   *  it, and the field finds again. */
  engaged: false,
})

export const currentThread = computed(() => agentChat.threads.find((thread) => thread.id === agentChat.current) ?? null)
export const agentOf = (id: string | undefined): AgentInfo => agentChat.agents.find((agent) => agent.id === id)
  ?? { id: id ?? 'claude', label: id === 'codex' ? 'Codex' : 'Claude Code', image: `${id ?? 'claude'}.svg`, available: false,
    efforts: [], fast: '', permissions: [], defaultEffort: 'medium', defaultPermission: '' }
export const assetUrl = (name: string) => `/__chat/assets/${name}`

/** The conversation as balloons: yours, and one of the agent's per turn, an ask inside it. */
export const balloons = computed<Balloon[]>(() => {
  const out: Balloon[] = []
  let turn: Balloon | null = null
  let brk = false
  let answer: string | undefined
  const agentBalloon = (index: number) => {
    if (!turn) {
      turn = { key: `a${index}`, who: 'agent', text: '', answer }
      out.push(turn)
    }
    return turn
  }
  agentChat.history.forEach((event, index) => {
    switch (event.t) {
      case 'user':
        turn = null
        // What the app asked on its own (the morning report, lib/morning.ts) is no balloon of yours.
        if (!event.app) out.push({ key: `u${index}`, who: 'you', text: String(event.text ?? ''), pending: !!event.pending })
        break
      case 'turn_start':
        turn = null
        answer = typeof event.answer === 'string' ? event.answer : undefined
        break
      case 'text_start':
        brk = !!turn?.text
        break
      case 'text': {
        const balloon = agentBalloon(index)
        if (brk) { balloon.text += '\n\n'; brk = false }
        balloon.text += String(event.text ?? '')
        break
      }
      case 'permission': {
        const balloon = agentBalloon(index)
        balloon.ask = {
          requestId: String(event.requestId), title: String(event.title ?? ''), body: String(event.body ?? ''),
          options: (event.options as Ask['options']) ?? [], done: false,
          ...(typeof event.tool === 'string' ? { tool: event.tool, input: (event.input as Ask['input']) ?? {} } : {}),
        }
        break
      }
      case 'permission_done': {
        const ask = out.map((balloon) => balloon.ask).find((a) => a?.requestId === String(event.requestId))
        if (ask) { ask.done = true; ask.chosen = event.value === undefined ? undefined : String(event.value) }
        break
      }
      case 'done':
        if (event.error && event.detail) out.push({ key: `e${index}`, who: 'agent', text: String(event.detail), error: true })
        turn = null
        break
      case 'exit':
        if (event.code) out.push({ key: `e${index}`, who: 'agent', text: `The agent stopped (exit ${event.code}). ${event.detail ?? ''}`.trim(), error: true })
        turn = null
        break
      case 'local_error':
        out.push({ key: `e${index}`, who: 'agent', text: String(event.text ?? ''), error: true })
        break
    }
  })
  return out.filter((balloon) => balloon.text || balloon.ask)
})

/** Claude's question tool: the gateway asks each of its questions as an ask with this `tool`, the options as its choices, and
 *  words you send while one waits are its answer (desktop/chat/chat.py's QUESTION_TOOL). */
export const QUESTION_TOOL = 'AskUserQuestion'

/** An ask the agent is waiting on, if any (S2.P1.014, .044). */
export const openAsk = computed<Ask | null>(() => {
  for (let i = balloons.value.length - 1; i >= 0; i--) {
    const ask = balloons.value[i]!.ask
    if (ask && !ask.done) return ask
  }
  return null
})

async function api<T>(path: string, body?: unknown): Promise<T> {
  const res = await fetch(`/__chat/${path}`, body === undefined ? {} : {
    method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(body),
  })
  const data = await res.json().catch(() => ({}))
  if (!res.ok) throw new Error((data as { error?: string }).error || `HTTP ${res.status}`)
  return data as T
}

// ---------------------------------------------------------------- the agent and its settings

function defaultSelection(provider: string): Selection {
  const agent = agentOf(provider)
  const saved = load<Record<string, { model?: string; reasoning?: string }>>(KEY.lastSelection, {})[provider] ?? {}
  const prefs = load<Record<string, { fast?: boolean; permission?: string }>>(KEY.prefs, {})[provider] ?? {}
  return {
    provider, model: saved.model || '', effort: saved.reasoning || agent.defaultEffort || 'medium',
    fast: !!prefs.fast, permission: prefs.permission || agent.defaultPermission,
  }
}
function saveSelection(): void {
  const selection = agentChat.selection
  if (!selection) return
  const all = load<Record<string, unknown>>(KEY.lastSelection, {})
  all[selection.provider] = { model: selection.model, reasoning: selection.effort }
  save(KEY.lastSelection, all)
  const prefs = load<Record<string, unknown>>(KEY.prefs, {})
  prefs[selection.provider] = { fast: selection.fast, permission: selection.permission }
  save(KEY.prefs, prefs)
  save(KEY.lastAgent, selection.provider)
  const thread = currentThread.value
  if (thread) { thread.selection = { ...selection }; saveThreads() }
}

export async function loadProbe(provider: string, force = false): Promise<void> {
  const known = agentChat.probes[provider]
  if (known && !force && !known.error) return
  agentChat.probes[provider] = { loading: true, models: known?.models ?? [] }
  try {
    agentChat.probes[provider] = await api<Probe>(`probe?provider=${encodeURIComponent(provider)}`)
  } catch (error) {
    agentChat.probes[provider] = { models: [], modelsError: 'Could not load models from this agent.',
      usage: { state: 'unavailable', message: (error as Error).message }, error: true }
  }
  const selection = agentChat.selection
  const models = agentChat.probes[provider]?.models ?? []
  if (selection?.provider === provider && !selection.model && models.length) {
    selection.model = models[0]!.value
    saveSelection()
  }
}

/** A choice in the agent tag's menu; it reaches the server with the next message (S2.P2.028). */
export function choose(change: Partial<Selection>): void {
  if (!agentChat.selection) return
  if (change.provider && change.provider !== agentChat.selection.provider) {
    agentChat.selection = { ...defaultSelection(change.provider), fast: false, permission: agentOf(change.provider).defaultPermission }
    void loadProbe(change.provider)
  }
  const { provider: _provider, ...rest } = change
  Object.assign(agentChat.selection, rest)
  saveSelection()
}

export async function refreshAgents(): Promise<void> {
  try {
    const { agents } = await api<{ agents?: unknown }>('agents')
    agentChat.agents = Array.isArray(agents) ? agents as AgentInfo[] : []
  } catch {
    agentChat.agents = []
  }
  agentChat.available = agentChat.agents.some((agent) => agent.available)
  agentChat.checked = true
}

// ---------------------------------------------------------------- conversations

function saveThreads(): void { save(KEY.threads, agentChat.threads.slice(0, 100)) }
function touchThread(patch: Partial<Thread>): void {
  const id = agentChat.current
  if (!id) return
  let thread = agentChat.threads.find((x) => x.id === id)
  if (!thread) {
    thread = { id, title: '', provider: agentChat.selection?.provider ?? 'claude', updatedAt: Date.now(), status: 'idle' }
    agentChat.threads.unshift(thread)
  }
  Object.assign(thread, patch, { updatedAt: Date.now() })
  agentChat.threads = [thread, ...agentChat.threads.filter((x) => x !== thread)]
  saveThreads()
}

let stream: EventSource | null = null
let pendingGoal: GoalRef | null = null
/** When the agent last answered in the goal conversation that is open: what changed after it goes with your next
 *  message (S3.P1.005). */
let goalSince: number | null = null

/** `provider`: the agent a session already has, when this browser has not talked in it: a session begun in Claude or Codex is
 *  resumed by its own agent, so what the agent knows is what the session holds (docs/design/task-sessions.md). */
export function openThread(id: string, goal: GoalRef | null = null, provider?: string): void {
  pendingGoal = goal
  agentChat.current = id
  save(KEY.current, id)
  agentChat.history = load<ChatEvent[]>(KEY.events(id), [])
  agentChat.cursor = load(KEY.cursor(id), { boot: null, seq: 0 })
  const thread = agentChat.threads.find((x) => x.id === id)
  let selection = thread?.selection ? { ...thread.selection } : defaultSelection(provider ?? load(KEY.lastAgent, 'claude'))
  if (agentChat.agents.length && !agentChat.agents.some((agent) => agent.id === selection.provider && agent.available)) {
    selection = defaultSelection(agentChat.agents.find((agent) => agent.available)?.id ?? 'claude')
  }
  agentChat.selection = selection
  agentChat.running = false
  agentChat.answer = null
  void loadProbe(selection.provider)
  connect()
}

export function newThread(goal: GoalRef | null = null): void {
  goalSince = null
  openThread(crypto.randomUUID(), goal)
}

/** A new conversation about a goal with the agent chosen for it, in the settings the chat has for that agent: Start work. */
export function newThreadWith(goal: GoalRef, provider: string): void {
  goalSince = null
  openThread(crypto.randomUUID(), goal, provider)
}

/** Discuss with agent: the goal's latest conversation, wherever it was started in Verticals, or a new one about it
 *  (S3.P1.002, .003). True when an earlier conversation goes on. */
export async function openForGoal(goal: GoalRef): Promise<boolean> {
  let latest: { session: string; lastTurnAt: number; provider?: string } | null = null
  try {
    const { conversations } = await api<{ conversations?: { session: string; lastTurnAt: number; provider?: string }[] }>(`goal?id=${encodeURIComponent(goal.id)}`)
    latest = conversations?.[0] ?? null
  } catch {
    latest = null
  }
  const local = agentChat.threads.filter((thread) => thread.goal?.id === goal.id).sort((a, b) => b.updatedAt - a.updatedAt)[0]
  const id = latest?.session ?? local?.id
  if (!id) { newThread(goal); return false }
  openThread(id, goal, latest?.provider)
  goalSince = latest?.lastTurnAt ? latest.lastTurnAt * 1000 : local?.updatedAt ?? null
  return true
}

function record(event: ChatEvent, live = true): void {
  event.ts = event.ts || Date.now()
  agentChat.history.push(event)
  if (agentChat.history.length > MAX_HISTORY) agentChat.history = agentChat.history.slice(-MAX_HISTORY)
  save(KEY.events(agentChat.current!), agentChat.history)
  if (live) follow(event)
}

let reply = ''
let brk = false
/* Only a turn you sent from here lands in the circle: the stream replays a conversation's past turns on connect. */
let awaitingReplies = 0
function follow(event: ChatEvent): void {
  switch (event.t) {
    case 'turn_start':
      agentChat.running = true
      // A turn that goes on with a morning report (the second agent's check, the fixing turn) keeps the step the gateway named.
      if (!event.stage) agentChat.step = 'Thinking'
      reply = ''
      break
    case 'activity':
      agentChat.running = true
      break
    case 'tool':
      // A tool that reads one of your sources names it (`step`, from the gateway); any other has its fixed phrase.
      agentChat.step = typeof event.step === 'string' && event.step ? event.step : stepPhrase(String(event.name ?? ''))
      break
    case 'step':
      // What the gateway itself is doing around a morning report: "Checking the report", "Fixing the report".
      agentChat.running = true
      if (typeof event.label === 'string' && event.label) agentChat.step = event.label
      break
    case 'text_start':
      brk = !!reply
      break
    case 'text':
      if (brk) { reply += '\n\n'; brk = false }
      reply += String(event.text ?? '')
      break
    case 'permission':
      touchThread({ status: 'needs-you' })
      break
    case 'permission_done':
      if (agentChat.running) touchThread({ status: 'working' })
      break
    case 'goal':
      // The gateway: the agent made a goal in a conversation about no goal, so the conversation is now that goal's
      // (docs/design/agent-chips.md). Discuss on the goal goes on with it, and your next words carry the goal.
      if (!currentThread.value?.goal && typeof event.id === 'string') touchThread({ goal: { id: event.id, title: String(event.title ?? '') } })
      break
    case 'done':
      // A morning report written but not yet checked: this turn ended, the answer is not told (`next` names what comes).
      if (event.next) { agentChat.running = true; break }
      agentChat.running = false
      // The server's clock, the one the goal's record keeps.
      if (currentThread.value?.goal) goalSince = typeof event.at === 'number' ? event.at * 1000 : Date.now()
      touchThread({ status: event.error ? 'failed' : 'idle' })
      // With the conversation open the answer is its balloon at once; only a hidden one lands in the circle (S2.P4.034),
      // and not while you type: then it waits in the conversation and your words stay (S2.P4.025).
      if (!event.error && reply.trim() && awaitingReplies > 0 && !agentChat.open && !commandFilter.text) {
        agentChat.answer = { text: reply, at: Date.now(), answer: typeof event.answer === 'string' ? event.answer : undefined }
      }
      awaitingReplies = Math.max(0, awaitingReplies - 1)
      reply = ''
      void refreshAnswers() // what the answer wrote is its Undo now (docs/design/agent-answer-undo.md)
      break
    case 'exit':
      agentChat.running = false
      touchThread({ status: 'failed' })
      void refreshAnswers()
      break
  }
}

function connect(): void {
  stream?.close()
  stream = null
  const session = agentChat.current
  if (!session || !agentChat.available || typeof EventSource === 'undefined') return
  const cursor = agentChat.cursor
  stream = new EventSource(`/__chat/events?session=${encodeURIComponent(session)}&since=${cursor.seq}&boot=${encodeURIComponent(cursor.boot ?? '')}`)
  stream.addEventListener('hello', (message) => {
    const { boot } = JSON.parse((message as MessageEvent).data)
    if (agentChat.cursor.boot !== boot) {
      agentChat.cursor = { boot, seq: 0 }
      save(KEY.cursor(session), agentChat.cursor)
      agentChat.running = false
    }
  })
  stream.onmessage = (message) => {
    if (session !== agentChat.current) return
    const { seq, event } = JSON.parse(message.data) as { seq: number; event: ChatEvent }
    if (seq <= agentChat.cursor.seq) return
    agentChat.cursor.seq = seq
    save(KEY.cursor(session), agentChat.cursor)
    const last = agentChat.history[agentChat.history.length - 1]
    if (event.t === 'user' && last?.t === 'user' && last.pending && last.text === event.text) {
      last.pending = false
      save(KEY.events(session), agentChat.history)
      return
    }
    record(event)
  }
}

function pageContext(goal: GoalRef | undefined) {
  return {
    today: new Date().toLocaleDateString('sv-SE'),
    // Your clock to the minute, "2026-10-12 07:00": the morning report reads each source up to it.
    now: new Date().toLocaleString('sv-SE').slice(0, 16),
    tz: Intl.DateTimeFormat().resolvedOptions().timeZone,
    url: location.pathname + location.search + location.hash,
    title: document.title,
    heading: (document.querySelector<HTMLElement>('.goal-card--detail-open .goal-card__title-text, main h1, h1')?.innerText ?? '').slice(0, 200),
    goal,
  }
}

/** Something wrong, or something that could be better: what a report is (docs/design/bug-reports.md). */
export type ReportKind = 'bug' | 'request'
/** What the agent tells of a report from the person's words: which kind it is, and the name of its task by its result ("A
 *  card dragged to Friday stays there"), or none, when the agent could not name it. */
export interface ReportVerdict {
  kind: ReportKind
  name: string | null
}
/** The longest the page waits for the agent to tell, a little over what the gateway waits for it (desktop/chat/report_kind.py). */
const REPORT_KIND_WAIT_MS = 30_000
/** A task's name the page takes from the gateway: one line, a few words (the gateway holds it to 8 words and 100 characters). */
const NAME_LIMIT = 100

/** Which kind of report these words are, and what to call its task, told by the agent from the words alone, so the person
 *  picks and names nothing. A request with no name when there is no agent, when it is slow or cannot tell: that shape loses
 *  nothing (the words, the pictures, the version), and the task takes the person's own words. */
export async function reportKind(words: string): Promise<ReportVerdict> {
  const unknown: ReportVerdict = { kind: 'request', name: null }
  if (!agentChat.available) return unknown
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), REPORT_KIND_WAIT_MS)
  try {
    const res = await fetch('/__chat/report-kind', {
      method: 'POST', headers: { 'content-type': 'application/json' }, signal: controller.signal,
      body: JSON.stringify({ words, settings: agentChat.selection ?? {} }),
    })
    const data = await res.json().catch(() => ({})) as { kind?: unknown; name?: unknown }
    if (!res.ok) return unknown
    const name = typeof data.name === 'string' ? data.name.replace(/\s+/g, ' ').trim() : ''
    return { kind: data.kind === 'bug' ? 'bug' : 'request', name: name && name.length <= NAME_LIMIT ? name : null }
  } catch {
    return unknown
  } finally {
    clearTimeout(timer)
  }
}

/** Your words, as your balloon at once; while the agent works they wait in the server's queue (S2.P1.015). `settings`
 *  adds to the agent's for this turn: the morning report's `{ sources: 'connected' }` (lib/morning.ts). */
export async function send(text: string, extra: Record<string, unknown> = {}, settings: Record<string, unknown> = {}): Promise<void> {
  const words = text.trim()
  if (!words || !agentChat.available) return
  if (!agentChat.current) newThread()
  const goal = currentThread.value?.goal ?? pendingGoal ?? undefined
  if (!currentThread.value) {
    touchThread({ title: goal ? goal.title : words.slice(0, 80), provider: agentChat.selection!.provider, goal })
    pendingGoal = null
  }
  touchThread({ provider: agentChat.selection!.provider, status: 'working' })
  agentChat.answer = null
  // Words sent while the agent's question waits answer it, in the turn that asked (the gateway's Chat._send): no reply of
  // their own comes (docs/design/replan-whole-board.md).
  if (openAsk.value?.tool !== QUESTION_TOOL) awaitingReplies += 1
  record({ t: 'user', text: words, pending: true, ...(settings.sources ? { app: true } : {}) }, false)
  const since: Record<string, unknown> = {}
  if (goal && goalSince !== null) {
    since.continuing = true
    since.changes = await goalChangesSince(goal.id, goalSince).catch(() => '')
  }
  try {
    await api('send', { session: agentChat.current, text: words, context: { ...pageContext(goal), ...since, ...extra },
      settings: { ...agentChat.selection, ...settings }, mode: agentChat.running ? 'queue' : 'send' })
  } catch (error) {
    record({ t: 'local_error', text: (error as Error).message }, false)
    touchThread({ status: agentChat.running ? 'working' : 'idle' })
  }
}

/** A turn nobody watches (the Inbox's warm-up): its own session, never a thread of yours, no balloon and nothing in the
 *  circle. Resolves with the agent's last words, or '' when it fails, stops or takes longer than `limit` ms. */
export async function quietTurn(text: string, extra: Record<string, unknown> = {}, limit = 180_000): Promise<string> {
  if (!agentChat.available || typeof EventSource === 'undefined') return ''
  const session = crypto.randomUUID()
  const settings = agentChat.selection ?? defaultSelection(load(KEY.lastAgent, 'claude'))
  return new Promise<string>((resolve) => {
    let words = ''
    let fresh = false
    const events = new EventSource(`/__chat/events?session=${encodeURIComponent(session)}&since=0&boot=`)
    const finish = (value: string) => { events.close(); clearTimeout(timer); resolve(value) }
    // Asked for a permission nobody will see, or too slow: stopped, so it never waits in the background.
    const abandon = () => { void api('stop', { session }).catch(() => undefined); finish('') }
    const timer = setTimeout(abandon, limit)
    events.onmessage = (message) => {
      const { event } = JSON.parse(message.data) as { event: ChatEvent }
      if (event.t === 'turn_start') words = ''
      else if (event.t === 'text_start') fresh = !!words
      else if (event.t === 'text') { words += (fresh ? '\n' : '') + String(event.text ?? ''); fresh = false }
      else if (event.t === 'done') { void refreshAnswers(); finish(event.error ? '' : words) }
      else if (event.t === 'exit') { void refreshAnswers(); finish('') }
      else if (event.t === 'permission') abandon()
    }
    events.onerror = () => { if (events.readyState === EventSource.CLOSED) finish('') }
    api('send', { session, text, context: { ...pageContext(undefined), ...extra }, settings, mode: 'send' })
      .catch(() => finish(''))
  })
}

export async function stop(): Promise<void> {
  if (!agentChat.current) return
  await api('stop', { session: agentChat.current }).catch(() => undefined)
}

export async function decide(requestId: string, value: string): Promise<void> {
  try {
    await api('permission', { session: agentChat.current, requestId, value })
  } catch (error) {
    record({ t: 'local_error', text: (error as Error).message }, false)
  }
}

/** Once, on start: is there an agent, and the conversation you had open. */
export async function startAgentChat(): Promise<void> {
  await refreshAgents()
  if (!agentChat.available) return
  // The gateway keeps what the agent's answers wrote, so one given while this window was closed has its Undo when it opens.
  answersAvailable(true)
  void refreshAnswers()
  openThread(agentChat.current ?? crypto.randomUUID())
}
