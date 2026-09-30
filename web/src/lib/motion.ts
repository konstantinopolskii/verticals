// Motion run from scripts reads the look's tokens (style.css, S0.P1): the curve for the size and physics of what moves,
// the duration by name, and whether motion is reduced, asked in one place.

export type Curve = 'small' | 'medium' | 'large' | 'play' | 'breath' | 'fall' | 'sway'
export type Pace = 'open' | 'close' | 'fade' | 'rise' | 'step' | 'board' | 'sent' | 'shape' | 'back' | 'pop'

const CURVES: Record<Curve, string> = {
  small: 'cubic-bezier(.165, .84, .44, 1)',
  medium: 'cubic-bezier(.2, 0, 0, 1)',
  large: 'cubic-bezier(.22, 1, .36, 1)',
  play: 'cubic-bezier(.77, 0, .175, 1)',
  breath: 'cubic-bezier(.37, 0, .63, 1)',
  fall: 'cubic-bezier(.55, 0, 1, .45)',
  sway: 'cubic-bezier(.45, 0, .55, 1)',
}
const PACES: Record<Pace, number> = {
  open: 140, close: 160, fade: 120, rise: 150, step: 80, board: 260, sent: 280, shape: 300, back: 320, pop: 400,
}

const reducedQuery = typeof window !== 'undefined' && window.matchMedia
  ? window.matchMedia('(prefers-reduced-motion: reduce)')
  : null

export function reducedMotion(): boolean {
  return reducedQuery?.matches ?? false
}

function token(name: string): string {
  if (typeof document === 'undefined') return ''
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim()
}

function ms(value: string): number | null {
  const n = Number.parseFloat(value)
  if (!Number.isFinite(n)) return null
  return value.endsWith('ms') ? n : value.endsWith('s') ? n * 1000 : n
}

export function curve(name: Curve): string {
  return token(`--vt-ease-${name}`) || CURVES[name]
}

export function duration(name: Pace): number {
  return ms(token(`--vt-dur-${name}`)) ?? PACES[name]
}

export function crossfade(): number {
  return ms(token('--vt-crossfade')) ?? 120
}

/** Timing for element.animate(): the named pace on its curve, or the crossfade's when motion is reduced. */
export function timing(
  pace: Pace | number, name: Curve, options: { delay?: number; fill?: FillMode } = {},
): KeyframeAnimationOptions {
  if (reducedMotion()) return { duration: crossfade(), easing: 'linear', fill: options.fill }
  return {
    duration: typeof pace === 'number' ? pace : duration(pace),
    easing: curve(name),
    delay: options.delay ?? 0,
    fill: options.fill,
  }
}
