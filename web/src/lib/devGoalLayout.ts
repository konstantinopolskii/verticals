import { reactive } from 'vue'
import { DEV_TUNING_ENABLED } from './devTuning'

export type GoalLayoutControl = {
  variable: `--kkov-${string}`
  label: string
  kind: 'text' | 'slider' | 'select'
  default: string | number
  min?: number
  max?: number
  step?: number
  unit?: string
  options?: Array<{ label: string; value: number }>
}

export type GoalLayoutSection = {
  title: string
  open: boolean
  controls: GoalLayoutControl[]
}

const slider = (
  variable: GoalLayoutControl['variable'], label: string, value: number,
  min: number, max: number, unit = 'px', step = 1,
): GoalLayoutControl => ({ variable, label, kind: 'slider', default: value, min, max, step, unit })

const text = (
  variable: GoalLayoutControl['variable'], label: string, value: string,
): GoalLayoutControl => ({ variable, label, kind: 'text', default: value })

export const GOAL_LAYOUT_SECTIONS: GoalLayoutSection[] = [
  {
    title: 'Collapsed goals', open: true, controls: [
      text('--kkov-collapsed-goal-font-family', 'Font', 'Commissioner, system-ui, sans-serif'),
      slider('--kkov-collapsed-goal-font-weight', 'Font weight', 500, 100, 900, '', 100),
      slider('--kkov-collapsed-goal-font-size', 'Font size', 12, 8, 32),
      slider('--kkov-collapsed-goal-line-height', 'Line height', 19, 8, 40),
      slider('--kkov-collapsed-goal-checkbox-size', 'Checkbox size', 14, 8, 32),
      slider('--kkov-collapsed-goal-checkbox-radius', 'Checkbox rounding', 3, 0, 20),
      slider('--kkov-collapsed-goal-checkbox-top', 'Checkbox vertical position', -1, -12, 12),
      slider('--kkov-collapsed-goal-checkbox-text-gap', 'Checkbox-to-text gap', 8, 0, 32),
      slider('--kkov-collapsed-goal-padding-right', 'Right padding', 14, 0, 64),
      slider('--kkov-collapsed-goal-actions-icon-size', 'Dots icon size', 10, 8, 24),
      slider('--kkov-collapsed-goal-actions-top', 'Dots vertical position', -2, -12, 12),
    ],
  },
  {
    title: 'Expanded column', open: false, controls: [
      text('--kkov-expanded-goal-font-family', 'Font', 'Commissioner, system-ui, sans-serif'),
      slider('--kkov-expanded-goal-font-weight', 'Font weight', 500, 100, 900, '', 100),
      slider('--kkov-expanded-goal-font-size', 'Font size', 24, 10, 48),
      slider('--kkov-expanded-goal-line-height', 'Line height', 32, 10, 56),
      slider('--kkov-expanded-goal-spacing', 'Spacing between tasks', 8, -10, 60),
      slider('--kkov-expanded-goal-checkbox-size', 'Checkbox size', 22, 10, 40),
      slider('--kkov-expanded-goal-checkbox-radius', 'Checkbox rounding', 6, 0, 20),
      slider('--kkov-expanded-goal-checkbox-top', 'Checkbox vertical position', 2, -12, 12),
      slider('--kkov-expanded-goal-checkbox-text-gap', 'Checkbox-to-text gap', 12, 0, 32),
      slider('--kkov-expanded-goal-padding-right', 'Right padding', 19, 0, 80),
      slider('--kkov-expanded-goal-actions-icon-size', 'Dots icon size', 16, 8, 24),
      slider('--kkov-expanded-goal-actions-top', 'Dots vertical position', 4, -12, 12),
    ],
  },
  {
    title: 'Collapsed subtasks', open: false, controls: [
      slider('--kkov-collapsed-subtask-font-size', 'Font size', 10, 3, 32),
      slider('--kkov-collapsed-subtask-font-weight', 'Font weight', 400, 100, 900, '', 100),
      slider('--kkov-collapsed-subtask-line-height', 'Line height', 16, 3, 40),
      slider('--kkov-collapsed-subtask-spacing', 'Spacing between subtasks', -10, -10, 40),
      slider('--kkov-collapsed-subtask-padding-block', 'Subtask vertical padding', 3, 0, 12),
      slider('--kkov-collapsed-subtask-card-radius', 'Subtask card rounding', 8, 0, 24),
      slider('--kkov-collapsed-subtask-checkbox-size', 'Checkbox size', 10, 3, 32),
      slider('--kkov-collapsed-subtask-checkbox-radius', 'Checkbox rounding', 2, 0, 20),
      slider('--kkov-collapsed-subtask-checkbox-top', 'Checkbox vertical position', 0, -12, 12),
      slider('--kkov-collapsed-subtask-checkbox-text-gap', 'Checkbox-to-text gap', 8, 0, 32),
      slider('--kkov-collapsed-subtask-group-margin-left', 'Group left margin', 4, 0, 80),
      slider('--kkov-collapsed-subtask-group-margin-right', 'Group right margin', 0, 0, 80),
      slider('--kkov-collapsed-subtask-group-margin-bottom', 'Group bottom margin', 0, -20, 60),
    ],
  },
  {
    title: 'Expanded subtasks', open: false, controls: [
      slider('--kkov-expanded-subtask-font-size', 'Font size', 15, 3, 48),
      slider('--kkov-expanded-subtask-font-weight', 'Font weight', 500, 100, 900, '', 100),
      slider('--kkov-expanded-subtask-line-height', 'Line height', 19, 3, 56),
      slider('--kkov-expanded-subtask-spacing', 'Spacing between subtasks', -5, -10, 40),
      slider('--kkov-expanded-subtask-padding-block', 'Subtask vertical padding', 4, 0, 12),
      slider('--kkov-expanded-subtask-card-radius', 'Subtask card rounding', 8, 0, 24),
      slider('--kkov-expanded-subtask-checkbox-size', 'Checkbox size', 16, 3, 40),
      slider('--kkov-expanded-subtask-checkbox-radius', 'Checkbox rounding', 3, 0, 20),
      slider('--kkov-expanded-subtask-checkbox-top', 'Checkbox vertical position', -2, -12, 12),
      slider('--kkov-expanded-subtask-checkbox-text-gap', 'Checkbox-to-text gap', 12, 0, 32),
      slider('--kkov-expanded-subtask-group-margin-left', 'Group left margin', 6, 0, 80),
      slider('--kkov-expanded-subtask-group-margin-right', 'Group right margin', 0, 0, 80),
      slider('--kkov-expanded-subtask-group-margin-bottom', 'Group bottom margin', 0, -20, 60),
    ],
  },
  {
    title: 'Highlight', open: false, controls: [
      slider('--kkov-light-tint', 'Lighter tint (hover, family)', 0.7, 0, 1, '', 0.01),
      // flow 4: how far from white an open goal's farthest relatives stay (faint falls halfway), and the rest of the
      // board, turned off
      slider('--kkov-far-tint', 'Farthest tint (distance from white)', 3, 0, 8, '', 0.1),
      slider('--kkov-off-opacity', 'Turned off (not related)', 0.32, 0, 1, '', 0.01),
      slider('--kkov-off-grey', 'Turned off: grey', 0.5, 0, 1, '', 0.05),
    ],
  },
  {
    title: 'New task row', open: false, controls: [
      slider('--kkov-collapsed-new-task-font-weight', 'Collapsed font weight', 400, 100, 900, '', 100),
      slider('--kkov-collapsed-new-task-checkbox-top', 'Collapsed checkbox vertical position', 3, -12, 12),
      slider('--kkov-collapsed-new-task-checkbox-text-gap', 'Collapsed checkbox-to-text gap', 5, 0, 32),
      slider('--kkov-collapsed-new-task-checkbox-radius', 'Collapsed checkbox rounding', 3, 0, 20),
      slider('--kkov-expanded-new-task-font-weight', 'Expanded font weight', 400, 100, 900, '', 100),
      slider('--kkov-expanded-new-task-checkbox-top', 'Expanded checkbox vertical position', 6, -12, 12),
      slider('--kkov-expanded-new-task-checkbox-text-gap', 'Expanded checkbox-to-text gap', 12, 0, 32),
      slider('--kkov-expanded-new-task-checkbox-radius', 'Expanded checkbox rounding', 4, 0, 20),
    ],
  },
]

export type GoalLayoutState = Record<string, string | number>
const STORAGE_KEY = 'verticals-dev-goal-layout-v1'
const controls = GOAL_LAYOUT_SECTIONS.flatMap((section) => section.controls)

function defaultGoalLayout(): GoalLayoutState {
  return Object.fromEntries(controls.map((control) => [control.variable, control.default]))
}

function loadGoalLayout(): GoalLayoutState {
  const result = defaultGoalLayout()
  if (!DEV_TUNING_ENABLED) return result
  try {
    const saved = JSON.parse(localStorage.getItem(STORAGE_KEY) ?? '{}') as GoalLayoutState
    for (const control of controls) {
      const value = saved[control.variable]
      if (control.kind === 'text' && typeof value === 'string' && value.trim()) result[control.variable] = value
      if (control.kind !== 'text' && typeof value === 'number' && Number.isFinite(value)) result[control.variable] = value
    }
  } catch {
    // Browser-local tuning is optional. Invalid storage must not stop the board.
  }
  return result
}

export const devGoalLayout = reactive<GoalLayoutState>(loadGoalLayout())

export function applyGoalLayout(): void {
  if (typeof document === 'undefined') return
  for (const control of controls) {
    const value = devGoalLayout[control.variable]
    const unit = control.kind === 'slider' ? (control.unit ?? '') : ''
    document.documentElement.style.setProperty(control.variable, `${value}${unit}`)
  }
}

export function saveGoalLayout(): void {
  applyGoalLayout()
  if (!DEV_TUNING_ENABLED) return
  try { localStorage.setItem(STORAGE_KEY, JSON.stringify(devGoalLayout)) } catch { /* optional */ }
}

export function resetGoalLayout(): void {
  Object.assign(devGoalLayout, defaultGoalLayout())
  saveGoalLayout()
}

applyGoalLayout()
