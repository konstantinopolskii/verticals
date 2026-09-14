import { reactive } from 'vue'
import { DEV_TUNING_ENABLED } from './devTuning'

export const DEV_PALETTE = [
  { key: 'yellow', label: 'Yellow', source: '#ecce32' },
  { key: 'rose', label: 'Rose', source: '#df496d' },
  { key: 'lime', label: 'Lime', source: '#92ce14' },
  { key: 'blue', label: 'Blue', source: '#278dea' },
  { key: 'violet', label: 'Violet', source: '#955be0' },
  { key: 'orange', label: 'Orange', source: '#f2713a' },
] as const

export type DevPaletteRole = 'card' | 'box' | 'tick'
export interface DevPaletteValue {
  color: string
  opacity: number
}
type DevPaletteEntry = Record<DevPaletteRole, DevPaletteValue>
export type DevPaletteState = Record<(typeof DEV_PALETTE)[number]['key'], DevPaletteEntry>

const STORAGE_KEY = 'verticals-dev-palette-v1'

// D184 (KK, 2026-08-13): shipped defaults are the owner's Colors-panel export, verbatim —
// not derived from goalWashInk. The panel stays the tuning surface; this table is its output.
const TUNED_DEFAULTS: DevPaletteState = {
  yellow: {
    card: { color: '#ffd500', opacity: 0.3 },
    box: { color: '#ffe45c', opacity: 1 },
    tick: { color: '#ffffff', opacity: 1 },
  },
  rose: {
    card: { color: '#ff003c', opacity: 0.15 },
    box: { color: '#ff003c', opacity: 0.5 },
    tick: { color: '#ffffff', opacity: 1 },
  },
  lime: {
    card: { color: '#a5e619', opacity: 0.3 },
    box: { color: '#c3ec69', opacity: 1 },
    tick: { color: '#ffffff', opacity: 1 },
  },
  blue: {
    card: { color: '#0088ff', opacity: 0.15 },
    box: { color: '#b5d6f2', opacity: 1 },
    tick: { color: '#ffffff', opacity: 1 },
  },
  violet: {
    card: { color: '#6a00ff', opacity: 0.15 },
    box: { color: '#cfadff', opacity: 1 },
    tick: { color: '#955be0', opacity: 0.65 },
  },
  orange: {
    card: { color: '#fce2d7', opacity: 1 },
    box: { color: '#fce2d7', opacity: 1 },
    tick: { color: '#f2713a', opacity: 0.65 },
  },
}

export function defaultDevPalette(): DevPaletteState {
  return structuredClone(TUNED_DEFAULTS)
}

function loadDevPalette(): DevPaletteState {
  const defaults = defaultDevPalette()
  if (!DEV_TUNING_ENABLED) return defaults
  try {
    const saved = JSON.parse(localStorage.getItem(STORAGE_KEY) ?? '{}') as Partial<DevPaletteState>
    for (const { key } of DEV_PALETTE) {
      for (const role of ['card', 'box', 'tick'] as const) {
        const value = saved[key]?.[role]
        if (typeof value === 'string' && /^#[0-9a-f]{6}$/i.test(value)) {
          defaults[key][role].color = value
        } else if (value && typeof value === 'object') {
          if (typeof value.color === 'string' && /^#[0-9a-f]{6}$/i.test(value.color)) defaults[key][role].color = value.color
          if (typeof value.opacity === 'number' && value.opacity >= 0 && value.opacity <= 1) defaults[key][role].opacity = value.opacity
        }
      }
    }
  } catch {
    // Local preview should keep working if storage is disabled or contains bad JSON.
  }
  return defaults
}

export const devPalette = reactive<DevPaletteState>(loadDevPalette())

export function devPaletteFor(color: string | null | undefined): DevPaletteEntry | null {
  if (!color) return null
  const found = DEV_PALETTE.find(({ source }) => source.toLowerCase() === color.toLowerCase())
  return found ? devPalette[found.key] : null
}

export function saveDevPalette(): void {
  if (!DEV_TUNING_ENABLED) return
  try { localStorage.setItem(STORAGE_KEY, JSON.stringify(devPalette)) } catch { /* optional */ }
}

export function resetDevPalette(): void {
  Object.assign(devPalette, defaultDevPalette())
  saveDevPalette()
}

export function rgbaFromHex(hex: string, opacity: number): string {
  const n = Number.parseInt(hex.slice(1), 16)
  const r = (n >> 16) & 255
  const g = (n >> 8) & 255
  const b = n & 255
  return `rgba(${r}, ${g}, ${b}, ${opacity})`
}
