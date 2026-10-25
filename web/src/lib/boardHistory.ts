// The board's history (docs/design/board-undo.md): one step for each change you made, in memory, from the moment the app
// opened. ⌘Z takes the last step back and ⇧⌘Z plays the last one taken back forward again; a new change empties what
// could still be played forward. A reload empties it all: "since the app opened".
//
// A step is made by `track` around a write the store makes (a tick, a patch, a move, a reparent), or by the delete in
// `lib/goalDelete.ts`; it holds the shots of the goals before and after (`lib/boardShots.ts`) and sets them back through
// `lib/boardRestore.ts`. Undo and redo write through the store's own verbs, never through `track`, so they record nothing.
//
// What a step says when its change leaves the view is `lib/historyWords.ts`; where it says it is `lib/fieldNotice.ts`.
import { nextTick } from '../reactivity'
import { toast } from '../kit'
import { findGoal } from './boardIndex'
import { currentShot, holdings, settleShots, type Applied, type Outcome, type RestorePorts, type Target } from './boardRestore'
import { changeBetween, changed, parentDiffers, placeDiffers, shotOf, shotsOf, slotDiffers, type Shot } from './boardShots'
import { ask, dismiss, say, type NoticeAction, type Segment } from './fieldNotice'
import { changeWords, keptWords, putBackWords } from './historyWords'
import { messageForError } from './scheduleFeedback'
import { glideThrough } from './undoGlide'

export interface Step {
  /** The goal the step is about. */
  id: string
  /** Its title as the step knows it, for the line that says what could not be done. */
  title?: string
  /** Whether everything the step changed is in view once it is applied. Without it, the goal the step is about (`id`) is the one
   *  looked for. */
  inView?(): boolean
  /** The words for a notice when the change leaves the view; `null` when there is nothing to say. `redo` is the change
   *  as it was first made, so it is also what is said when it was just made. */
  words(direction: 'undo' | 'redo'): Segment[] | null
  /** Whether goals move on the board when the step is applied, so the rows glide (`lib/undoGlide.ts`). */
  glides(direction: 'undo' | 'redo'): boolean
  /** Asks the server what the goals hold, as the step begins (`lib/boardRestore.ts`, `holdings`): nothing waits for the answer
   *  but a write, so the board moves in the same breath as the key. */
  prepare?(direction: 'undo' | 'redo'): void
  /** A step that holds goals against what they were left as (`lib/boardRestore.ts`) says what stayed; the others, how it went. */
  undo(): Promise<Outcome | Applied>
  redo(): Promise<Outcome | Applied>
}

export interface HistoryPorts extends RestorePorts {
  /** A goal in the hand: the keys wait for it to land. */
  busy: () => boolean
}

/** More than anyone goes back; the oldest steps go first. */
const LIMIT = 500

// --- whose change ⌘Z means (docs/design/agent-answer-undo.md) -----------------------------------------------------

/** The order in which the page learned of the person's changes and of the agent's answers (`lib/answerUndo.ts`), so that "after your
 *  own last change" is told without comparing two clocks. */
let sequence = 0
export const nextSeq = (): number => (sequence += 1)

const stamps = new WeakMap<Step, number>()

/** When the person last did something to their own history (a change, ⌘Z, ⇧⌘Z), by the clock the page shows. */
let touchedAt = 0

/** A change of the person's own that is this old is not obviously theirs any more, if an agent answered since. */
const CLEAR_MS = 5000

/** How long ⌘Z waits to hear of the answers that have ended: it is the app's own key and must not hang on a slow gateway. An answer
 *  not heard of in this time is left out of this press. */
const HEAR_MS = 700

/** What the page knows of the agent's answers, bound once by `lib/answerUndo.ts`. */
export interface AnswerSide {
  /** Reads the answers that have ended. */
  refresh(): Promise<void>
  /** The answers that stand, learned of after `seq`, in the order they were. */
  standingAfter(seq: number): { id: string; label: Segment[] }[]
  takeBack(id: string): Promise<void>
}
let answers: AnswerSide | null = null

export function bindAnswers(side: AnswerSide): void {
  answers = side
}

const done: Step[] = []
const undone: Step[] = []
let ports: HistoryPorts | null = null

/** The store binds its own verbs once, as `bindSpansDrag` does for the spans. */
export function bindBoardHistory(p: HistoryPorts): void {
  ports = p
}

/** The bound verbs, for the modules that make steps of their own (`lib/goalSteps.ts`). */
export function historyPorts(): HistoryPorts {
  if (!ports) throw new Error('the board history is not bound to the store')
  return ports
}

/** A goal the app took away itself (a request written in the Inbox that goes on as a conversation) has no step to take back. */
export function forgetStep(id: string): void {
  for (const list of [done, undone]) {
    for (let at = list.length - 1; at >= 0; at -= 1) if (list[at]!.id === id) list.splice(at, 1)
  }
}

// --- one at a time -----------------------------------------------------------------------------------------------

let chain: Promise<void> = Promise.resolve()
function enqueue(job: () => Promise<void>): Promise<void> {
  const next = chain.then(job, job)
  chain = next.catch(() => undefined)
  return next
}

/** Writes the person started that have not finished: a ⌘Z pressed in their wake waits for them to be steps. */
const writing = new Set<Promise<unknown>>()

// --- seeing --------------------------------------------------------------------------------------------------------

interface Box { left: number; top: number; right: number; bottom: number }

/** The classes `Transition.tsx` gives an element while it leaves. */
const LEAVING = '[class*="-leave-from"], [class*="-leave-active"], [class*="-leave-to"]'

/** Whether the middle of `el` is inside the window and inside every ancestor that clips it (a column that scrolls, a stack
 *  folded shut): what is cut off is not in your view. */
function inView(el: HTMLElement): boolean {
  const rect = el.getBoundingClientRect()
  if (!el.getClientRects().length) return false
  // What is leaving (a window closing over the goal deleted in it) is still drawn while it fades, but it is going.
  if (el.closest(LEAVING)) return false
  const x = rect.left + rect.width / 2
  const y = rect.top + rect.height / 2
  const clip: Box = { left: 0, top: 0, right: window.innerWidth, bottom: window.innerHeight }
  for (let up = el.parentElement; up && up !== document.body; up = up.parentElement) {
    const style = getComputedStyle(up)
    if (style.overflowX === 'visible' && style.overflowY === 'visible') continue
    const box = up.getBoundingClientRect()
    clip.left = Math.max(clip.left, box.left)
    clip.top = Math.max(clip.top, box.top)
    clip.right = Math.min(clip.right, box.right)
    clip.bottom = Math.min(clip.bottom, box.bottom)
  }
  return x >= clip.left && x <= clip.right && y >= clip.top && y <= clip.bottom
}

/** Whether the board (or the Inbox) shows the goal in view now. */
export function seen(id: string): boolean {
  const card = `.goal-card[data-goal-id="${CSS.escape(id)}"]:not([data-ghost]), :is(.inbox-card, .inbox-tile)[data-goal-id="${CSS.escape(id)}"]`
  return [...document.querySelectorAll<HTMLElement>(card)].some(inView)
}

const frame = (): Promise<void> => new Promise((resolve) => requestAnimationFrame(() => resolve()))

/** What the notice's button does: the history's own, or an answer's (`lib/answerUndo.ts`). `null` for an answer taken back from its
 *  message in the open conversation: the message's pill is the button then, and the notice says only what happened. */
export interface Again {
  undo(): void
  redo(): void
}
const OWN: Again = { undo: () => void undoOwn(), redo: () => void redo() }

/** A change that leaves your view is said in the field; one you can see is not. The board has drawn the change by the
 *  time this looks, and the check is what is on the screen, so it holds for every kind of change. What stayed because it was
 *  changed since is always said: the person is looking at a goal that did not move. */
export async function announce(step: Step, direction: 'undo' | 'redo', applied: Applied | null = null, again: Again | null = OWN): Promise<void> {
  await nextTick()
  await frame()
  if (typeof document === 'undefined') return
  const other: NoticeAction | null = !again ? null : direction === 'redo' ? { label: 'Undo', run: () => again.undo() } : { label: 'Redo', run: () => again.redo() }
  if (applied?.kept.length) {
    // With nothing set there is nothing to take back or play again from here: the line stands alone.
    const put = applied.put // a step of many goals names the first it put right and counts the rest
    say(keptWords(direction, put?.[0]?.title ?? step.title ?? applied.kept[0]!.title, applied.kept, applied.set, put ? Math.max(0, put.length - 1) : 0), applied.set ? other : null)
    return
  }
  if (step.inView ? step.inView() : seen(step.id)) return
  const words = step.words(direction)
  if (!words) return
  say(words, other)
}

// --- steps ---------------------------------------------------------------------------------------------------------

/** Puts a step on the history: what could be played forward is gone, and the change is said if it left the view. */
export function record(step: Step): void {
  dismiss() // a notice still up is about an older step, and its Undo would take this one back
  stamps.set(step, nextSeq())
  touchedAt = Date.now()
  done.push(step)
  if (done.length > LIMIT) done.shift()
  undone.length = 0
  void announce(step, 'redo')
}

function goalTitle(id: string): string {
  const board = ports?.board() ?? null
  const hit = findGoal(board, id)
  if (hit) return hit.title
  for (const chain of Object.values(board?.ancestors ?? {})) {
    const ancestor = chain.find((a) => a.id === id)
    if (ancestor) return ancestor.title
  }
  return 'a goal'
}

interface Pair {
  before: Shot
  after: Shot
}

/** The step for goals that went from `before` to `after`. `mainId` is the one the gesture was about. */
function editStep(pairs: Pair[], mainId: string): Step {
  const first = (targets: Target[]): Target[] => [...targets.filter((t) => t.shot.id === mainId), ...targets.filter((t) => t.shot.id !== mainId)]
  // Each goal is held against what the step left it as (undo) or what undo left it as (redo): what changed since stays.
  const befores = pairs.map((p) => ({ shot: p.before, change: changeBetween(p.before, p.after), expect: p.after }))
  const afters = pairs.map((p) => ({ shot: p.after, change: changeBetween(p.after, p.before), expect: p.before }))
  const main = pairs.find((p) => p.before.id === mainId) ?? pairs[0]!
  const structural = pairs.some(({ before, after }) => parentDiffers(before, after) || placeDiffers(before, after) || slotDiffers(before, after))
  let held: Map<string, Promise<Shot | null>> | undefined
  return {
    id: mainId,
    title: main.before.title,
    glides: () => structural,
    prepare: (direction) => {
      held = holdings(ports!, direction === 'undo' ? befores : afters)
    },
    words: (direction) => direction === 'undo'
      ? putBackWords(main.before.title)
      : changeWords(main.before, main.after, goalTitle),
    undo: () => settleShots(ports!, first(befores), 'back', held),
    redo: () => settleShots(ports!, first(afters), 'forward', held),
  }
}

/** Runs a write that makes its own step (a delete): the keys wait for it, as for any write, and the step it hands back
 *  goes on the history once the write has finished. `null`: it changed nothing, or failed. */
export function makeStep(run: () => Promise<Step | null>): Promise<void> {
  const job = run().then((step) => {
    if (step) record(step)
  })
  writing.add(job)
  const forget = (): void => void writing.delete(job)
  job.then(forget, forget)
  return job
}

/** The shots of `before`'s goals as the board holds them now. */
function readAfter(p: HistoryPorts, before: Shot[]): Map<string, Shot> {
  const board = p.board()
  const now = new Map<string, Shot>()
  for (const shot of before) {
    const hit = shotOf(board, shot.id)
    if (hit) now.set(shot.id, hit)
  }
  return now
}

/** Runs a write the person started (`run` is the store's own verb) and, once it has finished, records what it changed on
 *  `id`, and with `family` on everything under it that the board carries. A write that failed, or changed nothing, is not a
 *  step. `extend` adds to the step what only the write knows (the occurrence a tick made, `lib/repeatSteps.ts`). */
export function track(id: string, run: () => Promise<void>, family = false, extend?: (step: Step) => Step): Promise<void> {
  const p = ports
  if (!p) return run()
  return makeStep(async () => {
    const before = shotsOf(p.board(), id, family)
    await run()
    const head = before[0]
    if (!head || head.id !== id) return null // the goal was not on the board when the gesture began
    let after = readAfter(p, before)
    const seenNow = after.get(id)
    if (!seenNow || !changed(head, seenNow)) {
      // The goal left the board, or the board has not heard of the change (a move into a period it does not show waits for
      // the change feed): the server knows. The board is loaded again before the change is said, so that what is on the
      // screen when the line is chosen is what the change left.
      const now = await currentShot(p, id, true).catch(() => null)
      if (!now || !changed(head, now)) return null
      if (seenNow) {
        await p.reloadBoard()
        after = readAfter(p, before)
      }
      if (!after.has(id) || !changed(head, after.get(id)!)) after.set(id, now)
    }
    const pairs = before.flatMap((shot) => {
      const there = after.get(shot.id)
      return there && changed(shot, there) ? [{ before: shot, after: there }] : []
    })
    if (!pairs.some((pair) => pair.before.id === id)) return null
    const step = editStep(pairs, id)
    return extend ? extend(step) : step
  })
}

// --- undo and redo -------------------------------------------------------------------------------------------------

/** A step that could not be done is kept for another try, and given up on the second: the person has been told why, and the
 *  steps behind it should not wait on it for ever. */
const failures = new WeakMap<Step, number>()

export interface Ran {
  outcome: Outcome
  /** What stayed and whether anything was set, from a step that says (`lib/boardRestore.ts`). */
  applied: Applied | null
}

/** Runs one step in one direction: the server is asked what the goals hold, a change you can see glides, a step that fails is told
 *  once and kept for a second try. It touches no list: the history's own steps are put back by `apply`, and an agent's answer
 *  (`lib/answerUndo.ts`) never joins them. */
export async function runStep(step: Step, direction: 'undo' | 'redo'): Promise<Ran> {
  dismiss() // whatever a notice offered is being done now
  step.prepare?.(direction)
  const run = (): Promise<Outcome | Applied> => (direction === 'undo' ? step.undo() : step.redo())
  let outcome: Outcome
  let applied: Applied | null = null
  try {
    const result = step.glides(direction) ? await glideThrough(run, step.id) : await run()
    if (typeof result === 'string') outcome = result
    else [outcome, applied] = [result.outcome, result]
  } catch (err) {
    toast(messageForError(err))
    outcome = 'retry'
  }
  if (outcome === 'retry') {
    const tries = (failures.get(step) ?? 0) + 1
    failures.set(step, tries)
    if (tries >= 2) outcome = 'drop'
  }
  return { outcome, applied }
}

async function apply(direction: 'undo' | 'redo'): Promise<void> {
  await Promise.allSettled([...writing])
  const from = direction === 'undo' ? done : undone
  const to = direction === 'undo' ? undone : done
  const step = from.pop()
  if (!step) return
  touchedAt = Date.now()
  const { outcome, applied } = await runStep(step, direction)
  // Everything the step changed has been changed since: there is nothing to take back or play again, so the step is spent
  // and the line says so (the next ⌘Z goes on to the step before it).
  const spent = outcome === 'done' && !!applied?.kept.length && !applied.set
  if (outcome === 'done' && !spent) {
    to.push(step)
    if (direction === 'redo') stamps.set(step, nextSeq()) // played again, it is the person's latest change
  } else if (outcome === 'retry') from.push(step)
  if (outcome === 'done') await announce(step, direction, applied)
}

/** The person's own last change taken back, whatever else has happened: what the notice's Undo and a pick of the question do. */
export function undoOwn(): Promise<void> {
  return enqueue(() => apply('undo'))
}

/** What ⌘Z may take back, put to the person when it cannot tell: their own last change, or the agent's last answer. */
function askWhat(last: Step | undefined, answer: { id: string; label: Segment[] }): void {
  const mine = last && (last.words('redo') ?? [{ text: 'Changed ' }, { quote: last.title ?? 'a goal' }])
  ask([
    ...(mine ? [{ label: mine, run: () => void undoOwn() }] : []),
    { label: answer.label, run: () => void answers?.takeBack(answer.id) },
  ])
}

async function hearAnswers(): Promise<void> {
  if (!answers) return
  let timer: ReturnType<typeof setTimeout> | undefined
  await Promise.race([answers.refresh().catch(() => undefined), new Promise<void>((resolve) => { timer = setTimeout(resolve, HEAR_MS) })])
  clearTimeout(timer)
}

/** ⌘Z: the person's own last change, at once, unless it cannot be told whose change is meant. That is so when an agent's answer
 *  changed the board after the person's last change, and the person's own is 5 seconds old or more, or there is none: then the
 *  field asks which to take back, and a pick takes it (docs/design/agent-answer-undo.md). Inside text the key never gets here. */
export function undo(): Promise<void> {
  return enqueue(async () => {
    await Promise.allSettled([...writing])
    await hearAnswers() // an answer that has just ended counts
    const last = done[done.length - 1]
    const later = answers?.standingAfter(last ? stamps.get(last) ?? 0 : 0) ?? []
    if (!later.length || (last && Date.now() - touchedAt < CLEAR_MS)) return apply('undo')
    askWhat(last, later[later.length - 1]!)
  })
}

export function redo(): Promise<void> {
  return enqueue(() => apply('redo'))
}

// --- the keys ------------------------------------------------------------------------------------------------------

const APPLE = typeof navigator !== 'undefined' && /Mac|iPhone|iPad|iPod/.test(navigator.platform || navigator.userAgent)
const NOT_TEXT = new Set(['checkbox', 'radio', 'button', 'submit', 'reset', 'range', 'color', 'file', 'image'])

/** Where ⌘Z means the field's own undo: a text input, a text area, a select, anything editable. A checkbox you have just
 *  ticked keeps the focus and is not one of them. */
export function editsText(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false
  if (target instanceof HTMLInputElement) return !NOT_TEXT.has(target.type)
  if (target instanceof HTMLTextAreaElement || target instanceof HTMLSelectElement) return true
  return target.isContentEditable
}

/** ⌘Z / ⇧⌘Z on a Mac, Ctrl+Z / Ctrl+Shift+Z elsewhere, and there ⌘Z too: Linux on a Mac's keyboard (Asahi) sends its
 *  ⌘ key as Meta, and ⌘Z did nothing after a delete while the notice's Undo worked (the owner, 25 Oct 2026). The Z is the
 *  key's letter, so a layout that has it elsewhere (QWERTZ) still means its own Z; a layout with no Latin letter on the key
 *  (Cyrillic) is read by the key's place, as `privacy.ts` does. */
export function historyKey(event: KeyboardEvent): 'undo' | 'redo' | null {
  const isZ = /^[a-z]$/i.test(event.key) ? event.key.toLowerCase() === 'z' : event.code === 'KeyZ'
  if (event.altKey || !isZ) return null
  const modifier = APPLE ? event.metaKey && !event.ctrlKey : event.ctrlKey !== event.metaKey
  return modifier ? (event.shiftKey ? 'redo' : 'undo') : null
}

/** Listens on the window; returns the function that stops it. */
export function startHistoryKeys(): () => void {
  const onKeyDown = (event: KeyboardEvent): void => {
    const action = historyKey(event)
    if (!action || event.defaultPrevented || event.isComposing || event.repeat) return
    // Inside a text field the keys stay the field's own, and a goal in the hand waits to land.
    if (editsText(event.target) || ports?.busy()) return
    event.preventDefault()
    void (action === 'undo' ? undo() : redo())
  }
  window.addEventListener('keydown', onKeyDown)
  return () => window.removeEventListener('keydown', onKeyDown)
}
