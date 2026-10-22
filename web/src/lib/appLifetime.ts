/* What lives as long as the tab: the day rollover, the live board, ⌘Z, the agent and its sessions, the Inbox's first
   read, the morning report, and the goal windows an address opens. */
import { store, todayIso } from '../store'
import { startHistoryKeys } from './boardHistory'
import { agentChat, startAgentChat } from './agentChat'
import { loadInbox } from './inbox'
import { ensureMorning } from './morning'
import { startSessionWatch } from './taskSessions'
import { frontWindow, openWindow } from './windows'
import { onMounted, onUnmounted, watch } from '../reactivity'

export function useAppLifetime(): void {
  let stopDayRollover: (() => void) | null = null
  let stopLiveBoard: (() => void) | null = null
  let stopHistoryKeys: (() => void) | null = null // ⌘Z / ⇧⌘Z take the board's last change back (lib/boardHistory.ts)

  /* An address naming a goal with no date: its window over the Inbox, as a click there opens it. */
  function onOpenGoalWindow(event: Event): void {
    const { id, title } = ((event as CustomEvent).detail ?? {}) as { id?: string; title?: string }
    if (!id || (frontWindow.value?.kind === 'goal' && frontWindow.value.target === id)) return
    openWindow({ kind: 'goal', target: id, title: title || 'Goal' })
  }

  /* The morning report: looked for on start, once the agent has answered, and every five minutes. */
  let morningTimer: ReturnType<typeof setInterval> | null = null
  async function morningCheck(): Promise<void> {
    await ensureMorning(todayIso())
  }

  watch(() => agentChat.accessChosen, (chosen) => { if (chosen) void morningCheck() })

  onMounted(() => {
    stopDayRollover = store.startDayRollover()
    stopLiveBoard = store.startLiveBoard()
    stopHistoryKeys = startHistoryKeys()
    void startAgentChat().then(() => { startSessionWatch(); return morningCheck() })
    window.addEventListener('verticals:open-goal-window', onOpenGoalWindow)
    // The Inbox read once at start, so it opens with its rows; it reads again whenever it is opened.
    void loadInbox()
    morningTimer = setInterval(() => void morningCheck(), 5 * 60_000)
  })
  onUnmounted(() => {
    stopDayRollover?.()
    stopDayRollover = null
    stopLiveBoard?.()
    stopLiveBoard = null
    stopHistoryKeys?.()
    stopHistoryKeys = null
    if (morningTimer) clearInterval(morningTimer)
    window.removeEventListener('verticals:open-goal-window', onOpenGoalWindow)
  })
}
