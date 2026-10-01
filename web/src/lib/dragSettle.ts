// Where a released goal settles (split out of `lib/drag.ts`, docs/design-handoff S5.P1.038): the destination row box
// for a drop, a combine or a cancel, and how long the flight there takes. Pure reads over the DOM.
import type { DropTarget } from './drag'

export const SETTLE_MIN_MS = 330
export const SETTLE_MAX_MS = 550
export const SETTLE_DISTANCE_CAP_PX = 1500
export const SETTLE_FALLBACK_MS = 250
export const SETTLE_GRACE_MS = 50
export const SETTLE_EASING = 'cubic-bezier(.2,1,.1,1)'

function sourceRect(id: string): DOMRect | null {
  return document
    .querySelector(`[data-goal-id="${CSS.escape(id)}"] > .goal-card__row`)
    ?.getBoundingClientRect() ?? null
}

export function destinationRect(id: string, target: DropTarget): DOMRect | null {
  if (target?.kind === 'reorder') {
    // Source slot reserves the CARD while its nested target constructs the ROW. Destination slot
    // is already the ROW. Both paths return a rendered row box directly: no padding correction.
    const indicator = document.querySelector<HTMLElement>('[data-role="drop-indicator"]')
    if (!indicator) return sourceRect(id)
    const row = indicator.dataset.box === 'card'
      ? indicator.querySelector<HTMLElement>('[data-role="drop-row-target"]')
      : indicator
    return row?.getBoundingClientRect() ?? sourceRect(id)
  }
  if (target?.kind === 'combine') return combineDestinationRect(target.targetId) ?? sourceRect(id)
  return sourceRect(id)
}

function runningTranslateY(card: HTMLElement): number {
  const transform = getComputedStyle(card).transform
  return transform && transform !== 'none' ? new DOMMatrixReadOnly(transform).m42 : 0
}

function closingHeight(indicator: HTMLElement): number {
  const next = indicator.nextElementSibling as HTMLElement | null
  if (next) return next.offsetTop - indicator.offsetTop
  const gap = parseFloat(getComputedStyle(indicator.parentElement as HTMLElement).rowGap) || 0
  return indicator.offsetHeight + gap
}

/** Where the combine target's row ends up once the held placeholder unmounts. */
function combineDestinationRect(targetId: string): DOMRect | null {
  const row = document.querySelector<HTMLElement>(
    `[data-goal-id="${CSS.escape(targetId)}"] > .goal-card__row`,
  )
  if (!row) return null
  const rect = row.getBoundingClientRect()
  let top = rect.top - runningTranslateY(row.parentElement as HTMLElement)
  const indicator = document.querySelector<HTMLElement>('[data-role="drop-indicator"]')
  if (
    indicator
    && indicator.closest('[data-vertical]') === row.closest('[data-vertical]')
    && indicator.compareDocumentPosition(row) & Node.DOCUMENT_POSITION_FOLLOWING
  ) {
    top -= closingHeight(indicator)
  }
  return new DOMRect(rect.left, top, rect.width, rect.height)
}

export function settleDuration(distance: number | null): number {
  if (distance === null) return SETTLE_FALLBACK_MS
  const fraction = Math.min(Math.max(distance, 0), SETTLE_DISTANCE_CAP_PX) / SETTLE_DISTANCE_CAP_PX
  return SETTLE_MIN_MS + (SETTLE_MAX_MS - SETTLE_MIN_MS) * fraction
}
