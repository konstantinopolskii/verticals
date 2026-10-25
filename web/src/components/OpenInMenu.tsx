/* "Open in ›" in the goal menu's Agent section: every session the task has, newest
   first, each with its agent's mark and "Claude · 5 min ago". Pointed at, the list opens beside the menu; a pick opens
   that session where it lives. With no session the item is pale, and there is no list. */
import { computed } from '../reactivity'
import { agentOf, assetUrl } from '../lib/agentChat'
import { agentName, ago, openSession, sessionsOf, taskSessions, type TaskSession } from '../lib/taskSessions'
import { fallthrough } from '../bind'
import { tracked } from '../tracked'
import { useSetup } from '../setup'
import { AppIcon } from './AppIcon'
import { PopoverEngine } from './PopoverEngine'
import { MenuKey } from './MenuKey'
import './openInMenu.css'

interface Props {
  id: string
  onDone?: () => void
}

const OFFSET: [number, number] = [3, -8]
const SURFACE_ATTRS = { 'data-role': 'session-menu' }

export const OpenInMenu = tracked(function OpenInMenu(raw: Props & Record<string, unknown>) {
  const { id, onDone, ...attrs } = raw
  const s = useSetup({ id, onDone }, (props) => {
    const sessions = computed(() => sessionsOf(props.id))
    function open(session: TaskSession): void {
      void openSession(session)
      props.onDone?.()
    }
    return { sessions, open }
  })

  const label = (
    <>
      <span>Open in</span><MenuKey label="O" /><span data-role="submenu-arrow" aria-hidden="true"><AppIcon name="chevron-right" size={14} /></span>
    </>
  )
  if (!s.sessions.value.length) {
    return (
      <button {...fallthrough({
        type: 'button',
        role: 'menuitem',
        className: 'dropdown__item goal-actions__item',
        'data-menu-item': 'open-in',
        title: 'Start work or Discuss begins a session',
        disabled: true,
      }, attrs)}>
        {label}
      </button>
    )
  }
  return (
    <PopoverEngine
      nested
      fixedWidth={220}
      offset={OFFSET}
      data-action="open-in"
      surfaceClass="goal-actions__submenu session-menu"
      surfaceAttrs={SURFACE_ATTRS}
      {...attrs}
      trigger={
        <button type="button" role="menuitem" className="dropdown__item goal-actions__item" data-menu-item="open-in" data-key="o">
          {label}
        </button>
      }
    >
      {s.sessions.value.map((session) => (
        <button
          key={session.session}
          type="button"
          role="menuitem"
          className="dropdown__item session-menu__item"
          data-role="session-item"
          data-session={session.session}
          data-provider={session.provider}
          onClick={() => s.open(session)}
        >
          <img className="session-menu__mark" src={assetUrl(agentOf(session.provider).image)} alt="" width="16" height="16" />
          <span className="session-menu__text">{agentName(session.provider)}<span className="session-menu__when">{` · ${ago(session.movedAt, taskSessions.now)}`}</span></span>
        </button>
      ))}
    </PopoverEngine>
  )
})
