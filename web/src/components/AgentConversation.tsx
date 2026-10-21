/* The conversation (docs/design-handoff S2.P1): a column of balloons over the board or a window, the agent's on the left,
   yours on the right, rising out of the circle and sinking back into it. Its links move the app in place; an ask is a
   balloon with the choices as buttons; the goals and documents a message links stand under its words as chips. */
import { computed, nextTick, ref, watch } from '../reactivity'
import { AgentChips } from './AgentChips'
import { AnswerUndo } from './AnswerUndo'
import { chipLinks, withoutChipLines } from '../lib/chipLinks'
import { agentChat, agentOf, balloons, decide } from '../lib/agentChat'
import { askDetail } from '../lib/askDetail'
import { chatMarkdown } from '../lib/chatMarkdown'
import { scrollLook, useMessageScroll } from '../lib/messageScroll'
import { flight, land } from '../lib/chatFlight'
import { curve, reducedMotion } from '../lib/motion'
import { windows } from '../lib/windows'
import { bindRef, cx, fallthrough, sx } from '../bind'
import { tracked } from '../tracked'
import { useSetup } from '../setup'
import { Transition } from '../Transition'
import './agentConversation.css'

interface Props {
  onLink?: (url: string, web: boolean, from: Element | null) => void
}

export const AgentConversation = tracked(function AgentConversation({ onLink, ...attrs }: Props & Record<string, unknown>) {
  const s = useSetup({ onLink }, (props) => {
    const column = ref<HTMLElement | null>(null)
    const content = ref<HTMLElement | null>(null)
    /* The column runs the window's height and scrolls past its two lines, the top one 32 px down and the bottom one 12 px
       above the field, so a balloon less than half past a line shows whole instead of cut (S2.P5.009). */
    function lines() {
      const el = column.value
      const style = el ? getComputedStyle(el) : null
      return { top: parseFloat(style?.paddingTop ?? '32'), bottom: innerHeight - parseFloat(style?.paddingBottom ?? '0') }
    }
    const { toEnd } = useMessageScroll(column, content, lines, () => balloons.value.length)
    const agentName = computed(() => agentOf(agentChat.selection?.provider).label)
    const look = computed(() => scrollLook())
    /* What each ask will change: the goal and its date (lib/askDetail.ts; docs/design/agent-fixes.md, fix 6). */
    const changes = computed(() => Object.fromEntries(balloons.value.map((balloon) => [balloon.key, balloon.ask ? askDetail(balloon.ask) : null])))
    /* What each of the agent's messages made or changed, from the links in its words. */
    const chips = computed(() => Object.fromEntries(balloons.value.map((balloon) => [balloon.key, balloon.who === 'agent' ? chipLinks(balloon.text) : []])))

    watch(() => [agentChat.open, balloons.value.length, balloons.value[balloons.value.length - 1]?.text], async () => {
      if (!agentChat.open) return
      await nextTick()
      toEnd()
      arrive()
    }, { flush: 'post' })

    /* The answer going up from the circle opens the conversation with no reveal: the balloon itself is the movement. */
    const transitionName = computed(() => (flight.value?.kind === 'reply' ? 'agent-conversation-reply' : 'agent-conversation'))

    /* A balloon whose words flew in starts where they stood: yours from the field in 280 ms (S2.P3.019), the agent's from
       the circle in 300 ms after the press, the ones above it making room (S2.P4.016, .017). */
    function arrive(): void {
      const all = content.value?.querySelectorAll<HTMLElement>('[data-balloon]')
      const last = all?.[all.length - 1]
      if (!all || !last) return
      const f = land(last.dataset.who === 'you' ? 'you' : 'agent')
      if (!f || reducedMotion()) return
      const box = last.getBoundingClientRect()
      const style = getComputedStyle(last)
      const dx = f.left - (box.left + parseFloat(style.paddingLeft))
      const dy = f.top - (box.top + parseFloat(style.paddingTop))
      const from = `translate(${dx}px, ${dy}px)`
      if (f.kind === 'sent') {
        last.animate([{ transform: from, backgroundColor: 'rgb(43 43 43 / 0)' }, { transform: 'none', backgroundColor: '#2b2b2b' }],
          { duration: 280, easing: curve('large') })
        return
      }
      const timing = { duration: 300, delay: 90, easing: curve('large'), fill: 'backwards' as const }
      last.animate([{ transform: from }, { transform: 'none' }], timing)
      const room = `translateY(${box.height + 10}px)`
      for (const balloon of Array.from(all).slice(-12, -1)) balloon.animate([{ transform: room }, { transform: 'none' }], timing)
    }

    /* A click beside the balloons is a click on what lies under the conversation: it goes back into the circle (S2.P1.011). */
    function onColumnClick(event: MouseEvent): void {
      if (!(event.target as HTMLElement).closest('[data-balloon]')) agentChat.open = false
    }
    function onClick(event: MouseEvent): void {
      const link = (event.target as HTMLElement).closest<HTMLAnchorElement>('a[data-app-link], a[data-web-link]')
      if (!link) return
      event.preventDefault()
      props.onLink?.(link.dataset.appLink ?? link.dataset.webLink ?? link.href, !link.dataset.appLink, link)
    }

    return { column, content, agentName, look, changes, chips, transitionName, onColumnClick, onClick }
  })

  function conversation() {
    const name = s.agentName.value
    const own = {
      className: cx('agent-conversation', {
        'agent-conversation--working': agentChat.running,
        'agent-conversation--over-window': windows.list.length,
      }),
      'data-role': 'agent-conversation',
      style: sx(s.look.value),
    }
    return (
      <div {...fallthrough(own, attrs)}>
        <div ref={bindRef(s.column)} className="agent-conversation__column" role="log" onClick={(event) => s.onColumnClick(event.nativeEvent)}
          aria-live="polite" aria-label={`Conversation with ${name}`}>
          <div ref={bindRef(s.content)} className="agent-conversation__talk" onClick={(event) => s.onClick(event.nativeEvent)}>
            {balloons.value.map((balloon) => {
              const change = s.changes.value[balloon.key]
              const chips = s.chips.value[balloon.key]!
              const ask = balloon.ask
              return (
                <div
                  key={balloon.key}
                  className={cx('agent-balloon', [`agent-balloon--${balloon.who}`, { 'agent-balloon--error': balloon.error }])}
                  data-balloon=""
                  data-side="in"
                  data-who={balloon.who}
                  aria-label={balloon.who === 'you' ? 'You' : name}
                >
                  {balloon.who === 'you' ? (
                    <div className="agent-balloon__plain">{balloon.text}</div>
                  ) : withoutChipLines(balloon.text) ? (
                    // chatMarkdown escapes every byte of the source
                    <div className="agent-balloon__markdown" dangerouslySetInnerHTML={{ __html: chatMarkdown(withoutChipLines(balloon.text)) }}></div>
                  ) : null}
                  {chips.length ? <AgentChips className="agent-balloon__chips" links={chips} /> : null}
                  {/* At the answer's end, under what it made (docs/design/agent-answer-undo.md, agent-chips.md). */}
                  {balloon.who === 'agent' && balloon.answer ? <AnswerUndo answer={balloon.answer} stays /> : null}
                  {/* Only an ask still waiting: once answered it goes, as the earlier ones of the turn did. */}
                  {ask && !ask.done ? (
                    <div className="agent-balloon__ask" data-role="agent-ask">
                      <p className={cx('agent-balloon__ask-title', { 'agent-balloon__ask-title--changes': change || ask.note })}>{ask.title}</p>
                      {change ? (
                        <p className="agent-balloon__ask-changes" data-role="agent-ask-changes">
                          {change.goal}
                          {change.date ? (
                            <>
                              <span className="agent-balloon__ask-sep" aria-hidden="true">{' · '}</span>
                              {change.date}
                            </>
                          ) : null}
                        </p>
                      ) : ask.note ? <p className="agent-balloon__ask-changes" data-role="agent-ask-note">{ask.note}</p> : null}
                      {/* The sign-in waiting for the browser may have nothing to press (docs/design/agent-sign-in.md). */}
                      {ask.options.length ? <div className="agent-balloon__choices">
                        {ask.options.map((option) => (
                          <button
                            key={option.value}
                            type="button"
                            className="agent-balloon__choice"
                            onClick={() => void decide(ask.requestId, option.value)}
                          >
                            {option.label}
                          </button>
                        ))}
                      </div> : null}
                    </div>
                  ) : null}
                </div>
              )
            })}
          </div>
        </div>
      </div>
    )
  }

  return <Transition name={s.transitionName.value}>{agentChat.open ? conversation() : null}</Transition>
})
