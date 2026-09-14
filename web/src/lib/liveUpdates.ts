// D237 (KK, 2026-08-15): live board. An agent working over MCP writes through the same Postgres
// this API serves; migration 012's trigger rings pg_notify, GET /api/events forwards it as SSE,
// and this module turns those doorbells into silent board reloads — no page refresh, ever.
//
// Deliberately dumb: the stream carries no data (see routes_events.py), so the only action is
// "refetch through the ordinary authenticated route". Frames arriving in a burst collapse into
// one reload via a trailing debounce. The loop reconnects forever with capped exponential
// backoff — a sleeping laptop, a restarted server, a dropped proxy all land in the same branch
// and heal on their own.

import { openEventStream } from './api'

const DEBOUNCE_MS = 200
const BACKOFF_MIN_MS = 1000
const BACKOFF_MAX_MS = 15000

/** Starts the feed; returns a stop function. `onChange` fires debounced, outside any frame
 *  burst — the store decides what a reload means while a drag is in flight (D237's gesture
 *  rule lives there, not here). */
export function startLiveUpdates(onChange: () => void): () => void {
  let stopped = false
  let controller: AbortController | null = null
  let debounce: ReturnType<typeof setTimeout> | null = null

  function ring(): void {
    if (debounce) clearTimeout(debounce)
    debounce = setTimeout(() => {
      debounce = null
      if (!stopped) onChange()
    }, DEBOUNCE_MS)
  }

  async function loop(): Promise<void> {
    let backoff = BACKOFF_MIN_MS
    while (!stopped) {
      try {
        controller = new AbortController()
        const res = await openEventStream(controller.signal)
        if (!res.ok || !res.body) throw new Error(`events: ${res.status}`)
        backoff = BACKOFF_MIN_MS
        const reader = res.body.getReader()
        const decoder = new TextDecoder()
        let buffer = ''
        for (;;) {
          const { done, value } = await reader.read()
          if (done) break
          buffer += decoder.decode(value, { stream: true })
          let cut
          while ((cut = buffer.indexOf('\n\n')) >= 0) {
            const frame = buffer.slice(0, cut)
            buffer = buffer.slice(cut + 2)
            // Data frames only; ": ping" comments and "retry:" hints fall through by spec.
            if (frame.split('\n').some((line) => line.startsWith('data:'))) ring()
          }
        }
      } catch {
        // AbortError on stop lands here too; the while condition is the real exit.
      }
      if (stopped) break
      await new Promise((resolve) => setTimeout(resolve, backoff))
      backoff = Math.min(backoff * 2, BACKOFF_MAX_MS)
    }
  }

  void loop()
  return () => {
    stopped = true
    if (debounce) clearTimeout(debounce)
    controller?.abort()
  }
}
