// The morning report (Inbox and Documents redesign, round 8; KK 7 Oct 2026: "Morning report should be agent based since it
// additionally should check integrations that user has"). At 07:00 by your clock, or when the app opens if it was closed
// then, the app asks the agent for the day's report once, in a conversation of its own. In the desktop app that one turn
// also reaches your own connected tools, read-only (desktop/chat/prompt-morning.md). The agent writes the report as one
// document and the blue "Morning report" task in Day, then answers in two lines with the document linked; the answer
// stands in the field with the report's page (SearchBar.vue). No rule writes a report: without an agent there is none.
import { agentChat, newThread, send } from './agentChat'
import { commandFilter } from './commandFilter'

/** The hour the report is asked for (KK's round 2 call "rule time": 07:00 until he names another). */
export const MORNING_HOUR = 7
export const MORNING_TITLE = 'Morning report'
export const MORNING_FOLDER = 'reports/morning'

const MONTHS = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December']
/** "7 October 2026", the report's title day. */
export function longDay(iso: string): string {
  const [y, m, d] = iso.split('-').map(Number)
  return `${d} ${MONTHS[(m ?? 1) - 1]} ${y}`
}

export function morningAsk(today: string): string {
  return `Make my morning report for ${today}, following the morning report guide in your instructions. Save it as the `
    + `document ${MORNING_FOLDER}/${today}.md titled "${MORNING_TITLE} — ${longDay(today)}", with its task "${MORNING_TITLE}" `
    + `for today linked to it, then answer in two short lines and link the document.`
}

const asked = (day: string) => `vt-morning:${day}`

/** Asked on start and every few minutes: once the hour has come and an agent is there, the day's report is asked for
 *  once. Not while you talk with the agent or type: then it waits for the next look. */
export function ensureMorning(today: string, now: Date = new Date()): boolean {
  if (now.getHours() < MORNING_HOUR || !agentChat.available || agentChat.running || agentChat.open || commandFilter.text) return false
  try {
    if (localStorage.getItem(asked(today))) return false
    localStorage.setItem(asked(today), String(Date.now()))
  } catch {
    return false
  }
  newThread()
  void send(morningAsk(today), { morning: true }, { sources: 'connected' })
  return true
}
