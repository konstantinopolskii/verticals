/* A question's options as suggestions for your answer (docs/design/replan-whole-board.md, lib/answerSuggestions.ts): outlined
   pills in the field and in the conversation, the guess first; one whose words are in the field is filled. A click puts its
   words in the field or takes them out; nothing is sent until you press Enter. */
import type { MouseEvent } from 'react'
import { commandFilter } from '../lib/commandFilter'
import { inAnswer, suggestionWords, takeSuggestion } from '../lib/answerSuggestions'
import type { Ask } from '../lib/agentChat'
import { cx } from '../bind'
import { tracked } from '../tracked'
import './answerSuggestions.css'

export const AnswerSuggestions = tracked(function AnswerSuggestions({ options }: { options: Ask['options'] }) {
  const text = commandFilter.text
  return (
    <>
      {options.map((option) => {
        const picked = inAnswer(text, suggestionWords(option.label))
        return (
          <button key={option.value} type="button" className={cx('answer-suggestion', { 'answer-suggestion--picked': picked })}
            data-role="answer-suggestion" aria-pressed={picked}
            onClick={(event: MouseEvent) => { event.stopPropagation(); takeSuggestion(option.label) }}>
            {option.label}
          </button>
        )
      })}
    </>
  )
})
