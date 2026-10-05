// Words on their way into the conversation (docs/design-handoff S2.P3.019, S2.P4.016): where they stood in the field or
// in the circle, so their balloon comes in from there instead of appearing in place.
import { shallowRef } from 'vue'

export type Flight = { kind: 'sent' | 'reply'; left: number; top: number; at: number }

export const flight = shallowRef<Flight | null>(null)

export function launch(kind: Flight['kind'], left: number, top: number): void {
  flight.value = { kind, left, top, at: performance.now() }
}

/** The flight for this balloon, once; a stale one (the balloon never came) is dropped. */
export function land(who: 'you' | 'agent'): Flight | null {
  const f = flight.value
  if (!f || performance.now() - f.at > 1000) {
    flight.value = null
    return null
  }
  if ((f.kind === 'sent') !== (who === 'you')) return null
  flight.value = null
  return f
}
