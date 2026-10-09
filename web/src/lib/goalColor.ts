// Card colour wash/ink — docs/UI_MEASURED.md §5, verified 6/6 channels against the canon hexes:
//   wash = floor(255 - 0.2 * (255 - base))   per channel   (20% tint over white)
//   ink  = floor(0.4 * base)                 per channel   (40% shade of the hue)
// Deliberately a formula, not a lookup table, per ARCHITECTURE.md §6: "a seventh hue would need
// no design work." The neutral (no-colour) pair is the one exception — it is a stored literal,
// not the formula (floor(0.4 x 190) != 73) — UI_MEASURED.md §5 point 3.

const NEUTRAL_WASH: readonly [number, number, number] = [242, 242, 242]
const NEUTRAL_INK: readonly [number, number, number] = [73, 76, 84]
/** A colourless goal's highlight: at the hover tint (.7) it is the carried box's warm grey, #f5f5f1. */
export const NEUTRAL_LIGHT: readonly [number, number, number] = [241, 241, 235]

export interface WashInk {
  /** "r, g, b" — plug into `rgb(${washRgb})`. */
  washRgb: string
  inkRgb: string
}

function hexToRgb(hex: string): [number, number, number] {
  const n = Number.parseInt(hex.replace('#', ''), 16)
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255]
}

export function goalWashInk(colorHex: string | null | undefined): WashInk {
  if (!colorHex) {
    return { washRgb: NEUTRAL_WASH.join(', '), inkRgb: NEUTRAL_INK.join(', ') }
  }
  const [r, g, b] = hexToRgb(colorHex)
  const wash = [r, g, b].map((c) => Math.floor(255 - 0.2 * (255 - c)))
  const ink = [r, g, b].map((c) => Math.floor(0.4 * c))
  return { washRgb: wash.join(', '), inkRgb: ink.join(', ') }
}

/** Bright canon color rendered as the same 20% tint currently used by checkbox washes. */
export function goalWashAlpha(colorHex: string | null | undefined, opacity = 0.2): string | null {
  if (!colorHex) return null
  const [r, g, b] = hexToRgb(colorHex)
  return `rgba(${r}, ${g}, ${b}, ${opacity})`
}
