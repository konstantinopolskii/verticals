// The morning report's rule on the app's side (`core/morning.py`): once the morning hour has come in your own clock, the
// app asks the server for the day's report; the first ask of the day makes it, the rest return it. Asked on start, when
// the day turns, and every few minutes, so a window left open overnight gets it at the hour.
import { runMorning } from './api'

/** The hour the report is made (KK's round 2 call "rule time": 07:00 until he names another). */
export const MORNING_HOUR = 7

let madeOn: string | null = null
export async function ensureMorning(today: string, now: Date = new Date()): Promise<boolean> {
  if (madeOn === today || now.getHours() < MORNING_HOUR) return false
  madeOn = today
  try {
    return !!(await runMorning(today)).task_id
  } catch {
    madeOn = null
    return false
  }
}
