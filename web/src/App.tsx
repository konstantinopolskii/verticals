import { Board } from './components/Board'
import { AgentAccess } from './components/AgentAccess'
import { GoalCard } from './components/GoalCard'
import { InboxView } from './components/InboxView'
import { DocsView } from './components/DocsView'
import { SearchBar, type SearchBarApi } from './components/SearchBar'
import { DocCheck } from './components/DocCheck'
import { FieldNotice } from './components/FieldNotice'
import { CommentsPanel } from './components/CommentsPanel'
import { DevPanelContainer } from './components/DevPanelContainer'
import { WindowStack } from './components/WindowStack'
import { AgentConversation } from './components/AgentConversation'
import { AgentTag } from './components/AgentTag'
import { CardDnd } from './components/CardDnd'
import './lib/look'
import { store } from './store'
import { agentChat } from './lib/agentChat'
import { useAppLifetime } from './lib/appLifetime'
import { useShellKeys } from './lib/shellKeys'
import { useAgentField } from './lib/agentField'
import { outOfFocus, windows } from './lib/windows'
import { ref } from './reactivity'
import { cx } from './bind'
import { tracked } from './tracked'
import { useSetup } from './setup'
import './app.css'

/** What fills the app: a goal opened from search, the Inbox, Documents or the board. */
const MainView = tracked(function MainView() {
  const { activeView, openGoalVertical, openGoalId, goalDetail: detail } = store.state
  if (openGoalVertical === 'search' && openGoalId) {
    return (
      <div className="search-goal-surface">
        <GoalCard id={openGoalId} title={detail?.title ?? 'Loading…'} done={!!detail?.done_at} color={detail?.color}
          vertical={detail?.vertical} columnVertical="search" />
      </div>
    )
  }
  if (activeView === 'inbox') return <InboxView />
  if (activeView === 'docs') return <DocsView />
  return <Board columns={store.columns.value} showSampleBanner={store.hasSampleData.value} onRemoveSample={() => void store.removeSample()} />
})

export const App = tracked(function App() {
  const s = useSetup({}, () => {
    useAppLifetime()
    useShellKeys()
    const searchBar = ref<SearchBarApi | null>(null)
    return { searchBar, ...useAgentField(searchBar) }
  })

  const unfocused = outOfFocus.value
  const windowOpen = windows.list.length > 0
  const boardInFocus = store.state.activeView === 'verticals' && store.state.openGoalVertical !== 'search' && !unfocused
  return (
    <CardDnd>
      <div className="app-shell">
        <AgentAccess />
        {boardInFocus ? <div className="board-top-fade" aria-hidden="true"></div> : null}
        <div className={cx('app-veil', { 'is-shown': unfocused, 'app-veil--window': windowOpen })} data-role="out-of-focus"
          aria-hidden="true" onClick={s.onVeilClick}></div>
        <WindowStack />
        <AgentConversation onLink={s.onConversationLink} />
        <FieldNotice />
        <SearchBar id="verticals-command-bar" expose={s.searchBar} agentAvailable={agentChat.available} onSubmit={s.onSubmit}
          agentTag={<AgentTag />} />
        <DocCheck />
        <div className={cx('app-content', { 'app-content--out-of-focus': unfocused, 'app-content--window': windowOpen })}>
          <MainView />
        </div>
      </div>
      <div id="dropdownPortal" aria-live="off"></div>
      <CommentsPanel />
      <DevPanelContainer />
    </CardDnd>
  )
})
