// The look's values as hidden settings (R.073), and a goal's light (S0.P1.004–.009, .034).
import { defineKnobs, type Knob } from './tuning'
import { devPaletteFor, rgbaFromHex } from './devPalette'
import { goalWashAlpha, goalWashInk, NEUTRAL_LIGHT } from './goalColor'

const ms = (key: string, label: string, value: number, max = 1000): Knob =>
  ({ key, label, value, min: 0, max, step: 10, unit: 'ms' })
const px = (key: string, label: string, value: number, max: number): Knob =>
  ({ key, label, value, min: 0, max, step: 0.5, unit: 'px' })
const share = (key: string, label: string, value: number, max = 1): Knob =>
  ({ key, label, value, min: 0, max, step: 0.005 })
const text = (key: string, label: string, value: string): Knob => ({ key, label, value })

defineKnobs('Look · shadows and light', [
  share('--vt-shadow-grey-near', 'Grey near pool', 0.12),
  share('--vt-shadow-grey-far', 'Grey halo', 0.07),
  share('--vt-light-near', 'Light near pool', 0.325),
  share('--vt-light-far', 'Light halo', 0.2),
  share('--vt-light-black-near', 'Black under light, near', 0.08),
  share('--vt-light-black-far', 'Black under light, halo', 0.04),
  share('--vt-side-grey', 'Side window grey strength', 0.65),
  share('--vt-side-light-near', 'Side window light, near', 0.21),
  share('--vt-side-light-far', 'Side window light, halo', 0.15),
  text('--vt-near-small', 'Small: near pool', '0 18px 45px -6px'),
  text('--vt-far-small', 'Small: halo', '0 0 120px 12px'),
  text('--vt-near-medium', 'Medium: near pool', '0 36px 90px -12px'),
  text('--vt-far-medium', 'Medium: halo', '0 0 240px 24px'),
  text('--vt-near-big', 'Big: near pool', '0 72px 180px -24px'),
  text('--vt-far-big', 'Big: halo', '0 0 480px 48px'),
  text('--vt-near-back', 'Under the conversation: near pool', '0 72px 180px -24px'),
  text('--vt-far-back', 'Under the conversation: halo', '0 0 480px 48px'),
])

defineKnobs('Look · out of focus', [
  px('--vt-focus-blur', 'Board blur', 64, 120),
  share('--vt-focus-saturate', 'Board saturate', 1.4, 3),
  text('--vt-focus-veil', 'Board veil', 'rgba(245, 245, 247, .9)'),
  px('--vt-blur-0', 'Window blur, itself', 1, 10),
  px('--vt-blur-1', 'Window blur, copy 1', 3, 30),
  px('--vt-blur-2', 'Window blur, copy 2', 6, 30),
  px('--vt-blur-3', 'Window blur, copy 3', 10, 40),
  px('--vt-blur-4', 'Window blur, copy 4', 15, 60),
  share('--vt-step-back', 'Step back under the conversation', 0.985),
  share('--vt-step-side', 'Step back at the side', 0.94),
])

defineKnobs('Look · curves and durations', [
  text('--vt-ease-small', 'Curve: small', 'cubic-bezier(.165, .84, .44, 1)'),
  text('--vt-ease-medium', 'Curve: medium', 'cubic-bezier(.2, 0, 0, 1)'),
  text('--vt-ease-large', 'Curve: large', 'cubic-bezier(.22, 1, .36, 1)'),
  text('--vt-ease-play', 'Curve: the mascot plays', 'cubic-bezier(.77, 0, .175, 1)'),
  text('--vt-ease-breath', 'Curve: the mascot breathes', 'cubic-bezier(.37, 0, .63, 1)'),
  text('--vt-ease-fall', 'Curve: falling', 'cubic-bezier(.55, 0, 1, .45)'),
  text('--vt-ease-sway', 'Curve: stepping aside', 'cubic-bezier(.45, 0, .55, 1)'),
  ms('--vt-dur-open', 'Open', 140),
  ms('--vt-dur-close', 'Close', 160),
  ms('--vt-dur-fade', 'Fade', 120),
  ms('--vt-dur-rise', 'Rise', 150),
  ms('--vt-dur-step', 'Step back', 80),
  ms('--vt-dur-board', 'Board to board', 260),
  ms('--vt-dur-sent', 'Sent', 280),
  ms('--vt-dur-shape', 'Shape', 300),
  ms('--vt-dur-back', 'Back', 320),
  ms('--vt-dur-pop', 'Pop out', 400),
  ms('--vt-crossfade', 'Crossfade (reduced motion)', 120),
])

function rgb(hex: string): [number, number, number] {
  const n = Number.parseInt(hex.slice(1), 16)
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255]
}
function overWhite([r, g, b]: [number, number, number], alpha: number): [number, number, number] {
  return [r, g, b].map((c) => Math.round(255 - (255 - c) * alpha)) as [number, number, number]
}

/** A goal's light: its box colour as the tint, and its pale colour for veils; null for a goal with no colour. */
export function goalLight(color: string | null | undefined): { '--vt-tint': string; '--vt-pale': string } | null {
  const box = devPaletteFor(color)?.box
  if (!box) return null
  const tint = overWhite(rgb(box.color), box.opacity)
  return { '--vt-tint': tint.join(', '), '--vt-pale': overWhite(tint, 0.3).join(', ') }
}

/** The colour a goal's row lights in (`--goal-hover-background`). */
export function goalHoverBackground(color: string | null | undefined): string {
  const card = devPaletteFor(color)?.card
  if (card) return rgbaFromHex(card.color, card.opacity)
  return color ? `rgb(${goalWashInk(color).washRgb})` : `rgb(${NEUTRAL_LIGHT.join(', ')})`
}

/** A goal's checkbox square and its tick. A colourless square reads a shade darker than the add row's (D225). */
export function goalSquare(color: string | null | undefined): { box: string; check: string } {
  const palette = devPaletteFor(color)
  const wash = goalWashInk(color)
  return {
    box: palette?.box ? rgbaFromHex(palette.box.color, palette.box.opacity) : color ? `rgb(${wash.washRgb})` : '#e5e5e5',
    check: palette?.tick
      ? rgbaFromHex(palette.tick.color, palette.tick.opacity)
      : goalWashAlpha(color, 0.65) ?? `rgba(${wash.inkRgb}, 0.65)`,
  }
}
