/* The shell: navigation, search, areas and the agent on one solid bottom surface. It owns what lives
   as long as the tab: the day rollover, the live board, ⌘Z, the drag's window listeners (a card arms a drag in any
   view, so arm and release live in the one lifetime that spans them all), the windows' keys and the morning report. */
import { Board } from './components/Board'
import { GoalCard } from './components/GoalCard'
import { InboxView } from './components/InboxView'
import { DocsView } from './components/DocsView'
import { SearchBar, type SearchBarApi } from './components/SearchBar'
import { DocCheck } from './components/DocCheck'
import { FieldNotice } from './components/FieldNotice'
import { CommentsPanel } from './components/CommentsPanel'
import { DevColorPanel } from './components/DevColorPanel'
import { DevDeckPanel } from './components/DevDeckPanel'
import { DevIconPanel } from './components/DevIconPanel'
import { DevGoalLayoutPanel } from './components/DevGoalLayoutPanel'
import { DevTuningPanel } from './components/DevTuningPanel'
import { DevZoomPanel } from './components/DevZoomPanel'
import './lib/look'
import { DEV_TUNING_ENABLED } from './lib/devTuning'
import { isPrivacyHotkey, togglePrivacy } from './lib/privacy'
import { startHistoryKeys } from './lib/boardHistory'
import { store, todayIso } from './store'
import { commandFilter } from './lib/commandFilter'
import { agentChat, currentThread, newThread, openForGoal, openThread, send, startAgentChat } from './lib/agentChat'
import { circle, inboxWriting } from './lib/circle'
import { inbox, loadInbox, writeDown } from './lib/inbox'
import { endMove, escape as letGoOfMove, moveContext, moving } from './lib/moving'
import { findGoal } from './lib/boardIndex'
import { spanGoal } from './lib/spans'
import { REPLAN_ASK, type CarriedPlan } from './lib/replan'
import { closeWindows, frontWindow, openWindow, outOfFocus, stepWindow, windows } from './lib/windows'
import { desk } from './lib/docsDesk'
import { WindowStack } from './components/WindowStack'
import { AgentConversation } from './components/AgentConversation'
import { AgentTag } from './components/AgentTag'
import { ensureMorning } from './lib/morning'
import { startSessionWatch } from './lib/taskSessions'
import { takeSelection } from './lib/pageSelection'
import { makeReport } from './lib/report'
import { pictures, reporting } from './lib/reportPictures'
import { nextTick, onMounted, onUnmounted, ref } from './reactivity'
import { cx } from './bind'
import { tracked } from './tracked'
import { useSetup } from './setup'
import { CardDnd } from './components/CardDnd'
import './app.css'

export const App = tracked(function App() {
  const s = useSetup({}, () => {
    let stopDayRollover: (() => void) | null = null
    let stopLiveBoard: (() => void) | null = null
    let stopHistoryKeys: (() => void) | null = null // ⌘Z / ⇧⌘Z take the board's last change back (lib/boardHistory.ts)
    const devPanelsVisible = ref(false)
    const searchBar = ref<SearchBarApi | null>(null)

    function onWindowKeyDown(event: KeyboardEvent) {
      const target = event.target instanceof HTMLElement ? event.target : null
      const editing = target?.closest('input, textarea, select, [contenteditable="true"]') !== null
      if (DEV_TUNING_ENABLED && !editing && !event.repeat && !event.altKey && !event.ctrlKey && !event.metaKey
        && (event.code === 'Backslash' || event.key === '\\' || event.key === 'Backslash')) {
        devPanelsVisible.value = !devPanelsVisible.value
        event.preventDefault()
        return
      }
      if (isPrivacyHotkey(event) && !event.repeat) {
        event.preventDefault()
        void togglePrivacy()
        return
      }
      if (event.key === 'Alt' && (store.state.drag.pending || store.state.drag.id)) {
        store.setDragCombineMode(true)
        event.preventDefault()
      }
    }
    function onWindowKeyUp(event: KeyboardEvent) {
      if (event.key === 'Alt' && (store.state.drag.pending || store.state.drag.id)) {
        store.setDragCombineMode(false)
        event.preventDefault()
      }
    }
    onMounted(() => {
      stopDayRollover = store.startDayRollover()
      stopLiveBoard = store.startLiveBoard()
      stopHistoryKeys = startHistoryKeys()
      window.addEventListener('keydown', onWindowKeyDown)
      window.addEventListener('keyup', onWindowKeyUp)
    })
    onUnmounted(() => {
      stopDayRollover?.()
      stopDayRollover = null
      stopLiveBoard?.()
      stopLiveBoard = null
      stopHistoryKeys?.()
      stopHistoryKeys = null
      window.removeEventListener('keydown', onWindowKeyDown)
      window.removeEventListener('keyup', onWindowKeyUp)
    })

    /* The goal conversation Discuss is opening; a message sent meanwhile waits for it. */
    let goalOpening: Promise<void> | null = null
    /* The field's words: with pictures waiting they are a report; in the Inbox they are written down; otherwise they go
       to the agent, with what is selected on the page, and while moving a goal they start a task about the move. */
    async function onSubmit(text: string): Promise<void> {
      if (reporting.value) {
        if (pictures.sending) return
        commandFilter.text = ''
        void makeReport(text)
        return
      }
      if (inboxWriting.value) {
        commandFilter.text = ''
        void writeDown(text)
        return
      }
      if (!agentChat.available) return
      const selection = takeSelection()
      if (circle.moving) {
        const move = moveContext((id) => (findGoal(store.state.board, id) ?? spanGoal(id))?.title
          ?? inbox.goals.find((g) => g.id === id)?.title ?? null)
        endMove()
        newThread()
        agentChat.open = true
        agentChat.engaged = true
        commandFilter.text = ''
        void send(text, { move })
        return
      }
      agentChat.open = true
      agentChat.engaged = true
      commandFilter.text = ''
      ;(document.activeElement as HTMLElement | null)?.blur()
      if (goalOpening) await goalOpening
      const front = frontWindow.value
      if (front?.kind === 'goal' && currentThread.value?.goal?.id !== front.target) await openForGoal({ id: front.target, title: front.title })
      void send(text, selection ? { selection } : {})
    }
    function onVeilClick(): void {
      agentChat.open = false
    }
    /* A document or a web page in the conversation opens as a window at the part the link names; a goal or a board date
       moves the board in place. */
    function onConversationLink(url: string, web: boolean, from: Element | null): void {
      if (web) {
        openWindow({ kind: 'page', target: url, title: new URL(url).hostname }, from)
        agentChat.open = false
        return
      }
      const doc = /^#doc\/([^#]+)(?:#(.+))?$/.exec(url)
      if (doc) {
        openWindow({ kind: 'doc', target: decodeURIComponent(doc[1]!), title: from?.textContent?.trim() || 'Document',
          part: doc[2] ? decodeURIComponent(doc[2]) : undefined }, from)
        agentChat.open = false
        return
      }
      agentChat.open = false
      closeWindows()
      if (url.startsWith('#')) { location.hash = url; return }
      history.pushState(history.state, '', url)
      window.dispatchEvent(new PopStateEvent('popstate', { state: history.state }))
    }
    /* Discuss with agent: the goal pops out of its row into a window, the board goes out of focus, and the goal's latest
       conversation rises over the card. */
    function onDiscussGoal(event: Event): void {
      const { id, session, provider } = ((event as CustomEvent).detail ?? {}) as { id?: string; session?: string; provider?: string }
      if (!id || !agentChat.available) return
      const row = document.querySelector<HTMLElement>(`.goal-card[data-goal-id="${CSS.escape(id)}"] > .goal-card__row`)
      const title = row?.querySelector<HTMLElement>('.goal-card__title-text')?.innerText.trim() || 'Goal'
      openWindow({ kind: 'goal', target: id, title }, row)
      if (session) openThread(session, { id, title }, provider)
      else goalOpening = openForGoal({ id, title }).then(() => undefined).finally(() => { goalOpening = null })
      agentChat.open = true
      agentChat.engaged = true
      // The menu that asked gives its focus back on its next tick; the field takes it after that.
      void nextTick(() => nextTick(() => searchBar.value?.focusField()))
    }
    /* "Replan": a conversation of its own over the board, your words in it, the carried plans with them. */
    function onReplan(event: Event): void {
      const detail = ((event as CustomEvent).detail ?? {}) as { plans?: CarriedPlan[]; column?: string }
      if (!agentChat.available || !detail.plans?.length) return
      newThread()
      agentChat.open = true
      agentChat.engaged = true
      void send(REPLAN_ASK, { replan: { plans: detail.plans, column: detail.column ?? '' } })
    }
    /* An address naming a goal with no date: its window over the Inbox, as a click there opens it. */
    function onOpenGoalWindow(event: Event): void {
      const { id, title } = ((event as CustomEvent).detail ?? {}) as { id?: string; title?: string }
      if (!id || (frontWindow.value?.kind === 'goal' && frontWindow.value.target === id)) return
      openWindow({ kind: 'goal', target: id, title: title || 'Goal' })
    }
    /* Esc, when nothing smaller takes it, peels one layer a press: the agent's conversation, the windows, then on a desk
       a goal held on the field, on Documents a document's history, the document itself and a laid-out stack, and last the
       desk, Inbox or Documents, back to the board. What has its own Esc keeps it: the text being typed, a menu, a dialog,
       a goal in the hand, and on the board a goal open in place (GoalDetail) and the moving mode (SpansBoard). ⌘[ and ⌘]
       move one window. */
    function escapeStep(): (() => void) | null {
      if (agentChat.open) return () => { agentChat.open = false }
      if (windows.list.length) return closeWindows
      const view = store.state.activeView
      if (view === 'verticals') return null
      if (moving.picked || circle.moving) return () => void letGoOfMove()
      if (view === 'docs') {
        const docs = store.state.docs
        if (docs.historyOpen && docs.current) return store.closeHistory
        if (docs.historyOpen || docs.currentId || docs.currentLoading) return store.closeDoc
        if (desk.open) return () => { desk.open = null }
      }
      return () => store.setView('verticals')
    }
    function onShellKey(event: KeyboardEvent): void {
      if (event.defaultPrevented) return
      if (windows.list.length && (event.metaKey || event.ctrlKey) && (event.key === '[' || event.key === ']')) {
        event.preventDefault()
        stepWindow(event.key === '[' ? -1 : 1)
        return
      }
      if (event.key !== 'Escape' || event.isComposing || event.repeat) return
      const target = event.target instanceof HTMLElement ? event.target : null
      if (target?.closest('input, textarea, select, [contenteditable="true"], [role="dialog"], [role="menu"]')) return
      if (store.state.drag.id || store.state.drag.pending || store.state.drag.settling) return
      const step = escapeStep()
      if (!step) return
      event.preventDefault()
      step()
    }
    /* The morning report: looked for on start, once the agent has answered, and every five minutes. */
    let morningTimer: ReturnType<typeof setInterval> | null = null
    async function morningCheck(): Promise<void> {
      await ensureMorning(todayIso())
    }
    onMounted(() => {
      void startAgentChat().then(() => { startSessionWatch(); return morningCheck() })
      window.addEventListener('verticals:discuss-goal', onDiscussGoal)
      window.addEventListener('verticals:replan', onReplan)
      window.addEventListener('verticals:open-goal-window', onOpenGoalWindow)
      window.addEventListener('keydown', onShellKey)
      // The Inbox read once at start, so it opens with its rows; it reads again whenever it is opened.
      void loadInbox()
      morningTimer = setInterval(() => void morningCheck(), 5 * 60_000)
    })
    onUnmounted(() => {
      if (morningTimer) clearInterval(morningTimer)
      window.removeEventListener('verticals:discuss-goal', onDiscussGoal)
      window.removeEventListener('verticals:replan', onReplan)
      window.removeEventListener('verticals:open-goal-window', onOpenGoalWindow)
      window.removeEventListener('keydown', onShellKey)
    })
    return { devPanelsVisible, searchBar, onSubmit, onVeilClick, onConversationLink }
  })

  const unfocused = outOfFocus.value
  const windowOpen = windows.list.length > 0
  const detail = store.state.goalDetail
  return (
    <CardDnd>
      <div className="app-shell">
        {store.state.activeView === 'verticals' && store.state.openGoalVertical !== 'search' && !unfocused
          ? <div className="board-top-fade" aria-hidden="true"></div> : null}
        <div className={cx('app-veil', { 'is-shown': unfocused, 'app-veil--window': windowOpen })} data-role="out-of-focus"
          aria-hidden="true" onClick={s.onVeilClick}></div>
        <WindowStack />
        <AgentConversation onLink={s.onConversationLink} />
        <FieldNotice />
        <SearchBar id="verticals-command-bar" expose={s.searchBar} agentAvailable={agentChat.available} onSubmit={s.onSubmit}
          agentTag={<AgentTag />} />
        {/* Over the field while a document is in front: the count of its open comments, and Check again. */}
        <DocCheck />
        <div className={cx('app-content', { 'app-content--out-of-focus': unfocused, 'app-content--window': windowOpen })}>
          {store.state.openGoalVertical === 'search' && store.state.openGoalId ? (
            <div className="search-goal-surface">
              <GoalCard id={store.state.openGoalId} title={detail?.title ?? 'Loading…'} done={!!detail?.done_at} color={detail?.color}
                vertical={detail?.vertical} columnVertical="search" />
            </div>
          ) : store.state.activeView === 'inbox' ? <InboxView />
            : store.state.activeView === 'docs' ? <DocsView />
            : <Board columns={store.columns.value} showSampleBanner={store.hasSampleData.value} onRemoveSample={() => void store.removeSample()} />}
        </div>
      </div>
      <div id="dropdownPortal" aria-live="off"></div>
      {/* One comments panel for the whole app, docked against the window; a document's comments stand on its words. */}
      <CommentsPanel />
      {DEV_TUNING_ENABLED && s.devPanelsVisible.value ? (
        <>
          <DevColorPanel />
          <DevDeckPanel />
          <DevIconPanel />
          <DevGoalLayoutPanel />
          <DevTuningPanel />
          <DevZoomPanel />
        </>
      ) : null}
    </CardDnd>
  )
})
