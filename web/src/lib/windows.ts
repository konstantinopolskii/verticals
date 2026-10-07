// The windows lifted over the board (docs/design-handoff S3.P2, S3.P3) and the one "out of focus" flag the board's layer
// and every window read (S2.P6.012): the board is out of focus while the conversation or a window is open. Windows keep
// the order they opened in; one is in the centre, the others stand at the sides.
import { computed, reactive } from 'vue'
import { agentChat } from './agentChat'

export type WindowKind = 'goal' | 'doc' | 'page'
export interface VtWindow {
  key: string
  kind: WindowKind
  /** The goal's or the document's id, or the page's address. */
  target: string
  title: string
  /** Where a document or page opens: a heading's words or an anchor (S3.P4.003). */
  part?: string
  /** A document's head (round 2, frame f2b; round 5, m3–m5): its one line of facts, and its versions, which open
   *  history. Set by DocWindowBody.vue. */
  facts?: string[]
  versions?: number
  /** The document's own title has scrolled out of view, so the head says it; it never shows twice. */
  titled?: boolean
}

export const windows = reactive({
  list: [] as VtWindow[],
  front: 0,
  /** Where the window that is opening flies from: the row or link it was opened from. */
  origin: null as { key: string; rect: DOMRect } | null,
})

export const frontWindow = computed(() => windows.list[windows.front] ?? null)
export const outOfFocus = computed(() => agentChat.open || windows.list.length > 0)

/** Opens a window in the centre, or brings the one already showing that target there (S3.P3.022). */
export function openWindow(win: Omit<VtWindow, 'key'>, from?: Element | null): VtWindow {
  const key = `${win.kind}:${win.target}`
  const known = windows.list.findIndex((w) => w.key === key)
  if (known >= 0) {
    windows.list[known] = { ...windows.list[known]!, ...win, key }
    windows.front = known
    return windows.list[known]!
  }
  const opened = { ...win, key }
  windows.origin = from ? { key, rect: from.getBoundingClientRect() } : null
  windows.list.push(opened)
  windows.front = windows.list.length - 1
  return opened
}

/** A window's ×: the next one in the row takes the centre (S3.P3.021). */
export function closeWindow(key: string): void {
  const index = windows.list.findIndex((w) => w.key === key)
  if (index < 0) return
  windows.list.splice(index, 1)
  windows.front = Math.max(0, Math.min(index, windows.list.length - 1))
}

/** Esc or the goal's ×: every window goes and the board comes back into focus (S3.P2.011). */
export function closeWindows(): void {
  windows.list.splice(0)
  windows.front = 0
  agentChat.open = false
}

export function focusWindow(index: number): void {
  if (index >= 0 && index < windows.list.length) windows.front = index
}

/** ⌘[ and ⌘], or a swipe: one window over (S3.P3.010). */
export function stepWindow(direction: -1 | 1): void {
  focusWindow(windows.front + direction)
}
