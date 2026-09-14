/** The board follows the calendar across midnight (D69).
 *
 *  Owner, 2026-08-10: "уверен, что завтра автоматически цель на завтра не перенесётся". Correct,
 *  and the cause is not the scheduling — a goal anchored on tomorrow is bucketed into tomorrow's
 *  day column by the server the moment the board is fetched with tomorrow's date. The cause is
 *  that the board is fetched with today's date exactly ONCE, at mount, and every write after that
 *  re-fetches the anchor the board already has (`store.ts::reloadBoard`). A tab left open across
 *  midnight — which is precisely how a planner gets used — therefore keeps naming yesterday
 *  "Today" forever, and tomorrow's goals never arrive.
 *
 *  Two triggers, because one is not enough: an interval catches a machine that stays awake, and
 *  visibility/focus catches a laptop that was asleep at midnight and fired no timer.
 *
 *  Lives here rather than in `store.ts` for ARCHITECTURE.md §2's 750-line module rule (S-90a);
 *  the store passes in the three things it owns, so this file holds the policy and no state that
 *  belongs to the board.
 */

export interface DayRolloverPorts {
  /** Today, as the client reads it — the store's own `todayIso`, so the pinned test clock and
   *  production read through the same one function. */
  today: () => string
  /** The anchor date the board is currently showing, or null when nothing is loaded. */
  anchorDate: () => string | null
  /** True while a drag is in flight or settling. */
  busy: () => boolean
  /** Re-anchor the board onto this date. */
  load: (date: string) => Promise<unknown>
}

export function createDayRollover(ports: DayRolloverPorts) {
  let clockToday = ports.today()

  /** The board is re-anchored only when it was sitting on the OLD today — a user who navigated to
   *  some other period is left exactly where they put themselves, with only the clock updated. A
   *  drag in flight defers the swap to the next tick rather than yanking the board out from under
   *  the pointer (D63's invariant: nothing moves that the pointer did not move). */
  async function check(): Promise<void> {
    const now = ports.today()
    if (now === clockToday) return
    if (ports.busy()) return
    const wasOnToday = ports.anchorDate() === clockToday
    clockToday = now
    if (wasOnToday) await ports.load(now)
  }

  /** Starts both triggers; returns the teardown. Called once by the app shell. */
  function start(): () => void {
    const wake = () => void check()
    const timer = window.setInterval(wake, 30_000)
    document.addEventListener('visibilitychange', wake)
    window.addEventListener('focus', wake)
    return () => {
      window.clearInterval(timer)
      document.removeEventListener('visibilitychange', wake)
      window.removeEventListener('focus', wake)
    }
  }

  return { check, start }
}
