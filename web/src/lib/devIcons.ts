import { reactive } from 'vue'
import { DEV_TUNING_ENABLED } from './devTuning'

export interface IconTuning {
  base: number
  arrows: number
  search: number
  menu: number
  menuStroke: number
}

export const DEFAULT_ICON_TUNING: IconTuning = {
  base: 16,
  arrows: 14,
  search: 32,
  menu: 16,
  menuStroke: 2.2,
}

const STORAGE_KEY = 'verticals-dev-icons-v1'
const CSS_VARIABLES: Record<keyof IconTuning, string> = {
  base: '--app-icon-size-base',
  arrows: '--app-icon-size-arrows',
  search: '--app-icon-size-search',
  menu: '--app-icon-size-menu',
  menuStroke: '--app-icon-stroke-menu',
}

function loadIconTuning(): IconTuning {
  const result = { ...DEFAULT_ICON_TUNING }
  if (!DEV_TUNING_ENABLED) return result
  try {
    const stored = JSON.parse(localStorage.getItem(STORAGE_KEY) ?? '{}') as Partial<IconTuning>
    for (const key of Object.keys(result) as Array<keyof IconTuning>) {
      const value = stored[key]
      if (typeof value === 'number' && Number.isFinite(value)) result[key] = value
    }
  } catch {
    // Optional preview state must never block the app.
  }
  return result
}

export const devIcons = reactive<IconTuning>(loadIconTuning())

export function applyIconTuning(): void {
  if (typeof document === 'undefined') return
  for (const key of Object.keys(CSS_VARIABLES) as Array<keyof IconTuning>) {
    const unit = key === 'menuStroke' ? '' : 'px'
    document.documentElement.style.setProperty(CSS_VARIABLES[key], `${devIcons[key]}${unit}`)
  }
}

export function saveIconTuning(): void {
  applyIconTuning()
  if (!DEV_TUNING_ENABLED) return
  try { localStorage.setItem(STORAGE_KEY, JSON.stringify(devIcons)) } catch { /* optional */ }
}

export function resetIconTuning(): void {
  Object.assign(devIcons, DEFAULT_ICON_TUNING)
  saveIconTuning()
}

applyIconTuning()
