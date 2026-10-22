/* The agent's answer or ask inside the field (lib/circleAnswer.ts): the agent's last words on top of an ask, the words,
   what an ask will change, the chips of what an answer made, its Undo and an ask's choices; and, unseen, the words set
   once more for the field to measure. */
import type { MouseEvent } from 'react'
import { computed, type Ref } from '../reactivity'
import { circleState, circleWords } from '../lib/circle'
import { decide, openAsk } from '../lib/agentChat'
import {
  answerChips, answerSays, answerText, changesText, choices, leadText, moreChips, shownChips, undoable,
} from '../lib/circleAnswer'
import { AgentChips } from './AgentChips'
import { AnswerUndo } from './AnswerUndo'
import { bindRef, cx } from '../bind'
import { tracked } from '../tracked'
import { useSetup } from '../setup'

interface Props {
  answerMeasure: Ref<HTMLElement | null>
  leadMeasure: Ref<HTMLElement | null>
  chipsBox: Ref<HTMLElement | null>
}

export const FieldAnswer = tracked(function FieldAnswer({ answerMeasure, leadMeasure, chipsBox }: Props) {
  const s = useSetup({}, () => {
    const answer = computed(() => (circleWords.value?.kind === 'answer' ? circleWords.value : null))
    const shown = computed(() => circleState.value === 'answer' && !!circleWords.value)
    /* An answer made only of chips has no line of words. */
    const wordsShown = computed(() => !!answerText.value || !answerChips.value.length)
    const label = computed(() => (answer.value ? `${answerSays.value}. Press any key to reply` : undefined))

    function onChoice(event: MouseEvent<HTMLButtonElement>): void {
      event.stopPropagation()
      const ask = openAsk.value
      if (ask) void decide(ask.requestId, event.currentTarget.value)
    }
    return { answer, shown, wordsShown, label, onChoice }
  })

  const words = circleWords.value
  const answer = s.answer.value
  const lead = leadText.value
  const text = answerText.value
  const changes = changesText.value
  const chips = answerChips.value.length
  const more = moreChips.value
  return (
    <>
      {s.shown.value && words ? (
        <div
          className={cx('circle-field__answer', [`circle-field__answer--${words.kind}`, { 'circle-field__answer--chips': chips }])}
          data-role="circle-answer"
          aria-label={s.label.value}
        >
          {lead ? <p className="circle-field__answer-lead">{lead}</p> : null}
          {s.wordsShown.value ? (
            <p className="circle-field__answer-words">
              {text}{answer ? <span className="circle-field__answer-caret" aria-hidden="true"></span> : null}
            </p>
          ) : null}
          {changes ? <p className="circle-field__answer-changes" data-role="circle-ask-changes">{changes}</p> : null}
          {chips ? (
            <div ref={bindRef(chipsBox)} className="circle-field__answer-chips">
              <AgentChips links={shownChips.value} />
              {more ? <p className="circle-field__answer-more" data-role="circle-answer-more">{`${more} more`}</p> : null}
            </div>
          ) : null}
          {answer && undoable.value ? <AnswerUndo answer={answer.answer} className="circle-field__answer-undo" /> : null}
          {choices.value.length ? (
            <div className="circle-field__answer-choices">
              {choices.value.map((option) => (
                <button key={option.value} type="button" className="circle-field__answer-choice" value={option.value}
                  onClick={s.onChoice}>{option.label}</button>
              ))}
            </div>
          ) : null}
        </div>
      ) : null}
      <p ref={bindRef(answerMeasure)} className="circle-field__answer-measure" aria-hidden="true">
        {text}{changes ? <><br />{changes}</> : null}
      </p>
      <p ref={bindRef(leadMeasure)} className="circle-field__answer-measure circle-field__answer-measure--lead" aria-hidden="true">{lead}</p>
    </>
  )
})
