// Verticals → Morning Report (desktop/README.md): whether this device asks the agent for the day's report (`morning.ts`).
// On until switched off; the choice is kept on this device. In the desktop app the menu item switches it through
// `window.verticalsToggleMorningReport` and ticks itself by what the page reports (the `morningReport` message).
import { ref } from '../reactivity'

const KEY = 'verticals:morning-report'

interface Host {
  webkit?: { messageHandlers?: { morningReport?: { postMessage(on: boolean): void } } }
  verticalsToggleMorningReport?: () => void
}

function stored(): boolean {
  try { return localStorage.getItem(KEY) !== '0' } catch { return true }
}

export const morningReport = ref(stored())

function tellTheApp(): void {
  try { (window as Host).webkit?.messageHandlers?.morningReport?.postMessage(morningReport.value) } catch { /* a browser */ }
}

export function toggleMorningReport(): void {
  morningReport.value = !morningReport.value
  try { localStorage.setItem(KEY, morningReport.value ? '1' : '0') } catch { /* kept for this session only */ }
  tellTheApp()
}

if (typeof window !== 'undefined') {
  ;(window as Host).verticalsToggleMorningReport = toggleMorningReport
  tellTheApp()
}
