import { reactive } from 'vue'
import { DEV_TUNING_ENABLED } from './devTuning'

export interface DeckTuning {
  use3D: boolean
  dayWidth: number
  activeGapLeft: number
  activeGapRight: number
  width: number
  perspective: number
  rotateY: number
  rotateX: number
  scale: number
  activeRotateY: number
  activeScale: number
  overlap: number
  offsetY: number
  activeOffsetY: number
}

export const DEFAULT_DECK_TUNING: DeckTuning = {
  /* Compact board (COMPACT_BOARD_HANDOFF.md, KK 2026-08-17): the flat layout is the product;
     the 3D deck stays a dev-panel experiment, opt-in only. */
  use3D: false,
  dayWidth: 0,
  activeGapLeft: 0,
  activeGapRight: 0,
  width: 19,
  perspective: 200,
  rotateY: 15,
  rotateX: 5,
  scale: 75,
  activeRotateY: 3,
  activeScale: 95,
  overlap: 17,
  offsetY: 0,
  activeOffsetY: 0,
}

const STORAGE_KEY = 'verticals-dev-deck-v1'

function loadDeckTuning(): DeckTuning {
  const result = { ...DEFAULT_DECK_TUNING }
  if (!DEV_TUNING_ENABLED) return result
  try {
    const stored = JSON.parse(localStorage.getItem(STORAGE_KEY) ?? '{}') as Partial<DeckTuning>
    for (const key of Object.keys(result) as Array<keyof DeckTuning>) {
      const value = stored[key]
      if (typeof value === 'number' && Number.isFinite(value)) result[key] = value as never
      if (key === 'use3D' && typeof value === 'boolean') result[key] = value as never
    }
  } catch {
    // Preview controls must never prevent the board from rendering.
  }
  return result
}

export const devDeck = reactive<DeckTuning>(loadDeckTuning())

export function saveDeckTuning(): void {
  if (!DEV_TUNING_ENABLED) return
  try { localStorage.setItem(STORAGE_KEY, JSON.stringify(devDeck)) } catch { /* optional */ }
}

export function resetDeckTuning(): void {
  Object.assign(devDeck, DEFAULT_DECK_TUNING)
  saveDeckTuning()
}
