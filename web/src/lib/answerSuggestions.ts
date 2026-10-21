// A question of the agent's (Claude's question tool) offers its options as suggestions, not answers (docs/design/
// replan-whole-board.md; KK 21 Oct 2026: "Let them simply add text to my field, as autocomplete. Answers for autocomplete."):
// a click puts the option's words in the field, a second click takes them out, several can be picked, and only Enter sends
// the field's words, the answer to the question (the gateway's Chat._send). The agent's mark on its guess stays on the pill
// and never goes into the field.
import { agentChat } from './agentChat'
import { commandFilter } from './commandFilter'

const MARK = /\s*\((?:my guess|recommended)\)\s*$/i
const escape = (words: string) => words.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')

/** The words an option puts in the field: its label without the guess's mark. */
export function suggestionWords(label: string): string {
  return label.replace(MARK, '').trim()
}

/** Whether `words` stand in the field's text as one of its items (the text's own commas part them). */
export function inAnswer(text: string, words: string): boolean {
  return !!words && new RegExp(`(?:^|,)\\s*${escape(words)}\\s*(?:,|$)`).test(text)
}

/** The field's text with `words` added after ", ", or taken out with their comma when they are there already. */
export function toggleAnswer(text: string, words: string): string {
  if (inAnswer(text, words)) {
    return text.replace(new RegExp(`(^|,)\\s*${escape(words)}\\s*(?=,|$)`), '$1')
      .split(',').map((part) => part.trim()).filter(Boolean).join(', ')
  }
  const kept = text.trim().replace(/,$/, '').trim()
  return kept ? `${kept}, ${words}` : words
}

/** A suggestion clicked, in the field or in the conversation: its words go in or out, the conversation shows, and the field
 *  takes the focus with the caret at the end (SearchBar listens for `verticals:focus-field`). */
export function takeSuggestion(label: string): void {
  commandFilter.text = toggleAnswer(commandFilter.text, suggestionWords(label))
  agentChat.engaged = true
  agentChat.open = true
  window.dispatchEvent(new CustomEvent('verticals:focus-field'))
}
