/* Horizontal wheel routing for the column strip.
   The strip (.pattern-vertical-board) is the only horizontally scrollable box on the board, but
   the pointer almost never sits directly on it: every column is a .period-slide
   (overflow-y:auto / overflow-x:hidden) inside a .pattern-vertical-board__column (overflow:hidden).
   A box with overflow:hidden is still a scroll container, so the browser hands it the horizontal
   delta and stops there instead of chaining out to the strip. Result before this module: a
   horizontal wheel/trackpad swipe moved the strip only over the bottom navigation row, the one
   patch of board that is outside any column (owner report 2026-08-10).
   So we route it ourselves. Vertical deltas are left entirely alone — column vertical scrolling
   is native and must stay native. */

export type WheelIntent = { readonly scrollBy: number } | null

/** Horizontal-dominant deltas only, and only what the strip can still travel. */
export function wheelIntent(
  deltaX: number,
  deltaY: number,
  scrollLeft: number,
  scrollWidth: number,
  clientWidth: number,
): WheelIntent {
  if (Math.abs(deltaX) <= Math.abs(deltaY)) return null
  const max = scrollWidth - clientWidth
  if (max <= 0) return null
  const next = Math.min(Math.max(scrollLeft + deltaX, 0), max)
  const scrollBy = next - scrollLeft
  return scrollBy === 0 ? null : { scrollBy }
}
