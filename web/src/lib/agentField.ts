/* The field and the agent's conversation: what the field's words do, the links in the conversation, and the goal
   conversations Discuss and Replan open. */
import type { SearchBarApi } from '../components/SearchBar'
import { store } from '../store'
import { commandFilter } from './commandFilter'
import { agentChat, currentThread, newThread, openForGoal, openThread, send } from './agentChat'
import { circle, inboxWriting } from './circle'
import { inbox, writeDown } from './inbox'
import { endMove, moveContext } from './moving'
import { findGoal } from './boardIndex'
import { spanGoal } from './spans'
import { REPLAN_ASK, replanPlans } from './replan'
import { closeWindows, frontWindow, openWindow } from './windows'
import { takeSelection } from './pageSelection'
import { makeReport } from './report'
import { pictures, reporting } from './reportPictures'
import { nextTick, onMounted, onUnmounted, type Ref } from '../reactivity'

export function useAgentField(searchBar: Ref<SearchBarApi | null>) {
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
  /* "Replan" in any box: a conversation of its own over the board, your words in it, every carried plan of the board with
     them, not only the box's (docs/design/replan-whole-board.md). */
  async function onReplan(): Promise<void> {
    if (!agentChat.available) return
    const plans = await replanPlans()
    if (!plans.length) return
    newThread()
    agentChat.open = true
    agentChat.engaged = true
    void send(REPLAN_ASK, { replan: { plans } })
  }
  onMounted(() => {
    window.addEventListener('verticals:discuss-goal', onDiscussGoal)
    window.addEventListener('verticals:replan', onReplan)
  })
  onUnmounted(() => {
    window.removeEventListener('verticals:discuss-goal', onDiscussGoal)
    window.removeEventListener('verticals:replan', onReplan)
  })
  return { onSubmit, onVeilClick, onConversationLink }
}
