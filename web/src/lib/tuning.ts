// Hidden settings for every animation and effect (docs/design-handoff R.073): to play with, to tune later, and for the
// end-to-end tests, which set `verticals-tuning-v1` in localStorage before the page loads. A key that starts with `--` is
// a custom property on :root; any other key is read by a script through knob().
import { reactive } from 'vue'
import { DEV_TUNING_ENABLED } from './devTuning'

export type Knob = {
  key: string
  label: string
  value: number | string
  min?: number
  max?: number
  step?: number
  unit?: string
}
export type KnobSection = { title: string; knobs: Knob[] }

const STORAGE_KEY = 'verticals-tuning-v1'

function load(): Record<string, number | string> {
  if (!DEV_TUNING_ENABLED) return {}
  try {
    const saved = JSON.parse(localStorage.getItem(STORAGE_KEY) ?? '{}')
    return saved && typeof saved === 'object' ? saved : {}
  } catch {
    return {}
  }
}

const saved = load()
const defaults = new Map<string, Knob>()
export const knobSections = reactive<KnobSection[]>([])
export const tuning = reactive<Record<string, number | string>>({})

function cssValue(knob: Knob, value: number | string): string {
  return typeof value === 'number' && knob.unit ? `${value}${knob.unit}` : String(value)
}

function apply(key: string): void {
  if (!key.startsWith('--') || typeof document === 'undefined') return
  const knob = defaults.get(key)!
  const value = tuning[key]
  // Only what differs from the stylesheet goes inline, so its media queries (reduced motion) keep working.
  if (value === knob.value) document.documentElement.style.removeProperty(key)
  else document.documentElement.style.setProperty(key, cssValue(knob, value))
}

export function defineKnobs(title: string, knobs: Knob[]): void {
  if (knobSections.some((section) => section.title === title)) return
  knobSections.push({ title, knobs })
  for (const knob of knobs) {
    defaults.set(knob.key, knob)
    const stored = saved[knob.key]
    tuning[knob.key] = typeof stored === typeof knob.value ? stored : knob.value
    apply(knob.key)
  }
}

export function knob(key: string): number {
  const value = tuning[key]
  if (typeof value !== 'number') throw new Error(`no numeric knob ${key}`)
  return value
}

export function setKnob(key: string, value: number | string): void {
  if (!defaults.has(key)) return
  tuning[key] = value
  apply(key)
  save()
}

function save(): void {
  if (!DEV_TUNING_ENABLED) return
  const changed: Record<string, number | string> = {}
  for (const [key, knob] of defaults) if (tuning[key] !== knob.value) changed[key] = tuning[key]
  try { localStorage.setItem(STORAGE_KEY, JSON.stringify(changed)) } catch { /* optional */ }
}

export function resetKnobs(): void {
  for (const [key, knob] of defaults) {
    tuning[key] = knob.value
    apply(key)
  }
  save()
}
