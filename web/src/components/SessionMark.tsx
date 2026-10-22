/* The end of a task's card says what its sessions are doing (web/src/components/SessionMark.tsx,
   docs/design/task-sessions.md): while one works on the task, the field's own turning line in a small black disc; when one
   went on in Claude or Codex without a word to Verticals, that agent's own mark. The gateway sees only a file's size and
   time on disk. The dots take the place when the card is pointed at. */
import { computed } from '../reactivity'
import { agentChat, agentOf, assetUrl, currentThread } from '../lib/agentChat'
import { agentName, ago, taskSessions } from '../lib/taskSessions'
import { fallthrough } from '../bind'
import { tracked } from '../tracked'
import { useSetup } from '../setup'
import { MascotLine } from './MascotLine'
import './sessionMark.css'

interface Props {
  goalId: string
}

export const SessionMark = tracked(function SessionMark(raw: Props & Record<string, unknown>) {
  const { goalId, ...attrs } = raw
  const s = useSetup({ goalId }, (props) => {
    const known = computed(() => taskSessions.goals[props.goalId])
    /* Verticals' own agent answering in a conversation about this task is known at once, before the gateway's next answer. */
    const working = computed(() => !!known.value?.working || (agentChat.running && currentThread.value?.goal?.id === props.goalId))
    const outside = computed(() => known.value?.outside ?? null)
    const label = computed(() => {
      if (working.value) {
        const who = known.value?.sessions.find((session) => session.working)?.provider ?? currentThread.value?.provider
        return `${agentName(who ?? 'claude')} is working on this`
      }
      return outside.value ? `Continued in ${agentName(outside.value.provider)} · ${ago(outside.value.at, taskSessions.now)}` : ''
    })
    return { working, outside, label }
  })
  const working = s.working.value
  const outside = s.outside.value
  if (!working && !outside) return null
  const label = s.label.value
  return (
    <span
      {...fallthrough({
        className: 'session-mark',
        'data-role': 'session-mark',
        'data-state': working ? 'working' : 'outside',
        'data-provider': working ? undefined : outside?.provider,
        role: 'img',
        'aria-label': label,
        title: label,
      }, attrs)}
    >
      {working ? (
        <span className="session-mark__disc">
          <MascotLine turning />
        </span>
      ) : (
        <img className="session-mark__agent" src={assetUrl(agentOf(outside!.provider).image)} alt="" />
      )}
    </span>
  )
})
