// WP-C (KK, 2026-08-25 — "the Inbox opens on today's day-log document"): pure path/title math
// for the one convention `docs/COMMENTS_SPEC.md` already states ("Daily free-text notes live as
// documents at inbox/YYYY-MM-DD.md. No new tables, no new MCP tools — the docs system (migration
// 014) is the storage"). No I/O here and no clock read — the ISO date always comes in as a string
// from the caller (`store.ts::todayIso()`), the same "reads, never derives keys off a live clock"
// discipline `lib/periods.ts`'s own header states for period labels.

import { MONTH_NAMES } from './periods'
import { localDate } from './schedule'

/** `inbox/YYYY-MM-DD.md` — the whole convention, verbatim. */
export function dayDocPath(iso: string): string {
  return `inbox/${iso}.md`
}

/** "25 August 2026" — the exact style of prod's first hand-created day doc (this task's own
 *  brief). Built from the same `MONTH_NAMES` table `lib/periods.ts` already exports rather than
 *  `toLocaleDateString` (locale-dependent; no other date in this app is locale-formatted). */
export function dayDocTitle(iso: string): string {
  const d = localDate(iso)
  return `${d.getDate()} ${MONTH_NAMES[d.getMonth()]} ${d.getFullYear()}`
}
