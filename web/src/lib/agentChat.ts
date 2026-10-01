// The conversation with the agent (docs/design-handoff S2.P1): the client of the desktop gateway's /__chat/* routes,
// moved into the app from the script the gateway used to inject. The server and its event protocol stay as they are, and the
// conversations stored in localStorage (vt-chat:*) are read as they are, so none is lost. The web build has no gateway:
// the agent is unavailable there and the field only finds.
import { computed, reactive } from 'vue'
import { stepPhrase } from './agentSteps'
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
}
export interface Balloon { key: string; who: 'you' | 'agent'; text: string; error?: boolean; ask?: Ask; pending?: boolean }

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
  answer: null as { text: string; at: number } | null,
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
  const agentBalloon = (index: number) => {
    if (!turn) {
      turn = { key: `a${index}`, who: 'agent', text: '' }
      out.push(turn)
    }
    return turn
  }
  agentChat.history.forEach((event, index) => {
    switch (event.t) {
      case 'user':
        turn = null
        out.push({ key: `u${index}`, who: 'you', text: String(event.text ?? ''), pending: !!event.pending })
        break
      case 'turn_start':
        turn = null
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

export function openThread(id: string, goal: GoalRef | null = null): void {
  pendingGoal = goal
  agentChat.current = id
  save(KEY.current, id)
  agentChat.history = load<ChatEvent[]>(KEY.events(id), [])
  agentChat.cursor = load(KEY.cursor(id), { boot: null, seq: 0 })
  const thread = agentChat.threads.find((x) => x.id === id)
  let selection = thread?.selection ? { ...thread.selection } : defaultSelection(load(KEY.lastAgent, 'claude'))
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

/** Discuss with agent: the goal's latest conversation, wherever it was started in Verticals, or a new one about it
 *  (S3.P1.002, .003). True when an earlier conversation goes on. */
export async function openForGoal(goal: GoalRef): Promise<boolean> {
  let latest: { session: string; lastTurnAt: number } | null = null
  try {
    const { conversations } = await api<{ conversations?: { session: string; lastTurnAt: number }[] }>(`goal?id=${encodeURIComponent(goal.id)}`)
    latest = conversations?.[0] ?? null
  } catch {
    latest = null
  }
  const local = agentChat.threads.filter((thread) => thread.goal?.id === goal.id).sort((a, b) => b.updatedAt - a.updatedAt)[0]
  const id = latest?.session ?? local?.id
  if (!id) { newThread(goal); return false }
  openThread(id, goal)
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
      agentChat.step = 'Thinking'
      reply = ''
      break
    case 'activity':
      agentChat.running = true
      break
    case 'tool':
      agentChat.step = stepPhrase(String(event.name ?? ''))
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
    case 'done':
      agentChat.running = false
      // The server's clock, the one the goal's record keeps.
      if (currentThread.value?.goal) goalSince = typeof event.at === 'number' ? event.at * 1000 : Date.now()
      touchThread({ status: event.error ? 'failed' : 'idle' })
      // With the conversation open the answer is its balloon at once; only a hidden one lands in the circle (S2.P4.034).
      if (!event.error && reply.trim() && awaitingReplies > 0 && !agentChat.open) agentChat.answer = { text: reply, at: Date.now() }
      awaitingReplies = Math.max(0, awaitingReplies - 1)
      reply = ''
      break
    case 'exit':
      agentChat.running = false
      touchThread({ status: 'failed' })
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
    tz: Intl.DateTimeFormat().resolvedOptions().timeZone,
    url: location.pathname + location.search + location.hash,
    title: document.title,
    heading: (document.querySelector<HTMLElement>('.goal-card--detail-open .goal-card__title-text, main h1, h1')?.innerText ?? '').slice(0, 200),
    goal,
  }
}

/** Your words, as your balloon at once; while the agent works they wait in the server's queue (S2.P1.015). */
export async function send(text: string, extra: Record<string, unknown> = {}): Promise<void> {
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
  awaitingReplies += 1
  record({ t: 'user', text: words, pending: true }, false)
  const since: Record<string, unknown> = {}
  if (goal && goalSince !== null) {
    since.continuing = true
    since.changes = await goalChangesSince(goal.id, goalSince).catch(() => '')
  }
  try {
    await api('send', { session: agentChat.current, text: words, context: { ...pageContext(goal), ...since, ...extra },
      settings: agentChat.selection, mode: agentChat.running ? 'queue' : 'send' })
  } catch (error) {
    record({ t: 'local_error', text: (error as Error).message }, false)
    touchThread({ status: agentChat.running ? 'working' : 'idle' })
  }
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
  openThread(agentChat.current ?? crypto.randomUUID())
}
