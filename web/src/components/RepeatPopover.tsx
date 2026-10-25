/* The Repeat submenu of a goal's menu and of the open goal's meta row: presets for the
   goal's vertical, a Custom step, the end date, and "Do not repeat". */
import { useLayoutEffect, type MouseEvent as ReactMouseEvent } from 'react'
import { computed, ref } from '../reactivity'
import { AppIcon } from './AppIcon'
import type { RepeatRule } from '../lib/api'
import { store } from '../store'
import { PopoverEngine } from './PopoverEngine'
import { MenuKey } from './MenuKey'
import { cx, fallthrough } from '../bind'
import { tracked } from '../tracked'
import { useSetup, withDefaults } from '../setup'
import './repeatPopover.css'

interface Props {
  id: string
  vertical: string
  repeat: RepeatRule | null
  compact?: boolean
}
const DEFAULTS = { compact: false }

const WEEKDAYS = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
const MONTHS = [
  'January', 'February', 'March', 'April', 'May', 'June',
  'July', 'August', 'September', 'October', 'November', 'December',
]
const TITLES: Record<string, string> = {
  day: 'Day', week: 'Week', month: 'Month', quarter: 'Quarter', year: 'Year', decade: '3 years',
}

const PRESETS: Record<string, Array<[string, RepeatRule]>> = {
  day: [
    ['Daily', { frequency: 'daily', interval: 1 }],
    ['Weekly', { frequency: 'weekly', interval: 1 }],
    ['Monthly', { frequency: 'monthly', interval: 1 }],
    ['Quarterly', { frequency: 'quarterly', interval: 1 }],
    ['Yearly', { frequency: 'yearly', interval: 1 }],
    ['Every decade', { frequency: 'every_decade', interval: 1 }],
  ],
  week: [
    ['Weekly', { frequency: 'weekly', interval: 1 }],
    ['Monthly', { frequency: 'monthly', interval: 1 }],
    ['Quarterly', { frequency: 'quarterly', interval: 1 }],
    ['Yearly', { frequency: 'yearly', interval: 1 }],
    ['Every decade', { frequency: 'every_decade', interval: 1 }],
  ],
  month: [
    ['Monthly', { frequency: 'monthly', interval: 1 }],
    ['Yearly', { frequency: 'yearly', interval: 1 }],
    ['Quarterly', { frequency: 'quarterly', interval: 1 }],
    ['Every decade', { frequency: 'every_decade', interval: 1 }],
  ],
  quarter: [
    ['Yearly', { frequency: 'yearly', interval: 1 }],
    ['Quarterly', { frequency: 'quarterly', interval: 1 }],
    ['Every decade', { frequency: 'every_decade', interval: 1 }],
  ],
  year: [
    ['Yearly', { frequency: 'yearly', interval: 1 }],
    ['Every decade', { frequency: 'every_decade', interval: 1 }],
  ],
  decade: [['Every decade', { frequency: 'every_decade', interval: 1 }]],
}

const OFFSET: [number, number] = [3, -8]
const MENU_ATTRS = { 'data-role': 'repeat-menu' }
const CUSTOM_ATTRS = { 'data-role': 'repeat-custom' }
const END_ATTRS = { 'data-role': 'repeat-end' }
const range = (n: number) => Array.from({ length: n }, (_, i) => i + 1)

export const RepeatPopover = tracked(function RepeatPopover(raw: Props & Record<string, unknown>) {
  const { id, vertical, repeat, compact, ...attrs } = withDefaults(raw, DEFAULTS)
  const s = useSetup({ id, vertical, repeat, compact }, (props) => {
    const dayMode = ref<'weekdays' | 'monthdays'>('weekdays')
    const presets = computed(() => PRESETS[props.vertical] ?? [])

    /** Field-by-field, NOT JSON.stringify: postgres hands jsonb back in its own key order
     *  (`{"interval":1,"frequency":"monthly"}`), the presets here are written frequency-first, and
     *  stringify equality made every preset compare unequal, so the active rule never got its mark.
     *  `end_date` is deliberately ignored: it is an end condition on a rule, not part of which rule it is. */
    function sameRule(rule: RepeatRule): boolean {
      const current = props.repeat
      if (!current) return false
      const fields = new Set([...Object.keys(current), ...Object.keys(rule)])
      fields.delete('end_date')
      for (const field of fields) {
        const mine = current[field as keyof RepeatRule]
        const theirs = rule[field as keyof RepeatRule]
        if (Array.isArray(mine) || Array.isArray(theirs)) {
          if (!Array.isArray(mine) || !Array.isArray(theirs)) return false
          if (mine.length !== theirs.length) return false
          if (mine.some((value, index) => value !== theirs[index])) return false
        } else if ((mine ?? null) !== (theirs ?? null)) return false
      }
      return true
    }

    function setRule(rule: RepeatRule | null) {
      void store.updateGoal(props.id, { repeat: rule })
    }

    function toggleSelection(field: 'weekdays' | 'month_days', value: number) {
      const current = props.repeat?.[field] ?? []
      const selected = current.includes(value)
        ? current.filter((item) => item !== value)
        : [...current, value].sort((left, right) => left - right)
      if (!selected.length) return
      setRule({
        frequency: field === 'weekdays' ? 'weekly' : 'monthly',
        interval: 1,
        [field]: selected,
      })
    }

    function setEnd(event: Event) {
      if (!props.repeat) return
      const value = (event.target as HTMLInputElement).value
      setRule({ ...props.repeat, end_date: value || null })
    }

    /* The date field's DOM value follows the rule after each drawing, and the native change event (not React's per-input
       onChange) sets the end. No `value` prop, so no value attribute. */
    let endInput: HTMLInputElement | null = null
    function syncEnd() {
      const value = props.repeat?.end_date ?? ''
      if (endInput && endInput.value !== value) endInput.value = value
    }
    function bindEnd(node: HTMLInputElement | null) {
      endInput?.removeEventListener('change', setEnd)
      endInput = node
      if (!node) return
      node.addEventListener('change', setEnd)
      syncEnd()
    }

    return { dayMode, presets, sameRule, setRule, toggleSelection, bindEnd, syncEnd }
  })
  useLayoutEffect(() => s.syncEnd())

  const stop = (fn: () => void) => (event: ReactMouseEvent) => {
    event.stopPropagation()
    fn()
  }
  const dayMode = s.dayMode.value

  return (
    <PopoverEngine
      nested
      fixedWidth={200}
      offset={OFFSET}
      surfaceClass="goal-actions__submenu repeat-menu"
      surfaceAttrs={MENU_ATTRS}
      {...fallthrough({ 'data-action': 'repeat' }, attrs)}
      trigger={
        <button
          type="button"
          role={compact ? undefined : 'menuitem'}
          className={compact ? 'goal-detail__meta-trigger' : 'dropdown__item goal-actions__item'}
          aria-label={compact ? 'Repeat' : undefined}
          data-key={compact ? undefined : 'r'}
        >
          <AppIcon name="repeat" size={compact ? 18 : 24} />
          {!compact ? <span>Repeat</span> : null}
          {!compact ? <MenuKey label="R" /> : null}
          {!compact ? <span data-role="submenu-arrow" aria-hidden="true"><AppIcon name="chevron-right" size={14} /></span> : null}
        </button>
      }
    >
      <p className="repeat-menu__heading">{TITLES[vertical]}</p>
      {s.presets.value.map(([label, rule]) => (
        <button
          key={label}
          type="button"
          role="menuitem"
          className={cx('dropdown__item repeat-menu__item', { _active: s.sameRule(rule) })}
          onClick={() => s.setRule(rule)}
        >{label}</button>
      ))}

      <PopoverEngine
        nested
        fixedWidth={200}
        surfaceClass="goal-actions__submenu repeat-menu repeat-custom"
        surfaceAttrs={CUSTOM_ATTRS}
        trigger={
          <button type="button" role="menuitem" className="dropdown__item repeat-menu__item">
            <span>Custom</span><span data-role="submenu-arrow" aria-hidden="true"><AppIcon name="chevron-right" size={14} /></span>
          </button>
        }
      >
        {vertical === 'day' ? (
          <>
            <div className="repeat-custom__segments">
              <button type="button" className={cx({ _active: dayMode === 'weekdays' })} onClick={stop(() => { s.dayMode.value = 'weekdays' })}>Weekdays</button>
              <button type="button" className={cx({ _active: dayMode === 'monthdays' })} onClick={stop(() => { s.dayMode.value = 'monthdays' })}>Monthdays</button>
            </div>
            {dayMode === 'weekdays' ? (
              <div className="repeat-custom__list">
                {WEEKDAYS.map((label, index) => (
                  <button
                    key={label}
                    type="button"
                    role="menuitem"
                    className={cx('dropdown__item', { _active: repeat?.weekdays?.includes(index + 1) })}
                    onClick={() => s.toggleSelection('weekdays', index + 1)}
                  >{label}</button>
                ))}
              </div>
            ) : (
              <div className="repeat-custom__days">
                {range(31).map((day) => (
                  <button
                    key={day}
                    type="button"
                    role="menuitem"
                    className={cx('dropdown__item', { _active: repeat?.month_days?.includes(day) })}
                    onClick={() => s.toggleSelection('month_days', day)}
                  >{day}</button>
                ))}
              </div>
            )}
          </>
        ) : vertical === 'week' ? (
          [2, 3, 4, 5].map((interval) => (
            <button key={interval} type="button" role="menuitem" className="dropdown__item" onClick={() => s.setRule({ frequency: 'weekly', interval })}>{`Every ${interval} weeks`}</button>
          ))
        ) : vertical === 'month' ? (
          MONTHS.map((label, index) => (
            <button key={label} type="button" role="menuitem" className="dropdown__item" onClick={() => s.setRule({ frequency: 'yearly', interval: 1, months: [index + 1] })}>{label}</button>
          ))
        ) : vertical === 'quarter' ? (
          range(4).map((quarter) => (
            <button key={quarter} type="button" role="menuitem" className="dropdown__item" onClick={() => s.setRule({ frequency: 'yearly', interval: 1, quarters: [quarter] })}>{`Q${quarter}`}</button>
          ))
        ) : vertical === 'year' ? (
          range(9).map((interval) => (
            <button key={interval} type="button" role="menuitem" className="dropdown__item" onClick={() => s.setRule({ frequency: 'yearly', interval: interval + 1 })}>{`Every ${interval + 1} years`}</button>
          ))
        ) : (
          range(9).map((interval) => (
            <button key={interval} type="button" role="menuitem" className="dropdown__item" onClick={() => s.setRule({ frequency: 'every_decade', interval: interval + 1 })}>{`Every ${interval + 1} decades`}</button>
          ))
        )}
      </PopoverEngine>

      <hr />
      {repeat ? (
        <PopoverEngine
          nested
          fixedWidth={200}
          surfaceClass="goal-actions__submenu repeat-menu repeat-end"
          surfaceAttrs={END_ATTRS}
          trigger={
            <button type="button" role="menuitem" className="dropdown__item repeat-menu__item">
              <span>End repeat</span><span data-role="submenu-arrow" aria-hidden="true"><AppIcon name="chevron-right" size={14} /></span>
            </button>
          }
        >
          <label className="repeat-end__field">
            <span>End date</span>
            <input ref={s.bindEnd} type="date" />
          </label>
        </PopoverEngine>
      ) : null}
      {repeat ? <hr /> : null}
      <button type="button" role="menuitem" className="dropdown__item repeat-menu__item" onClick={() => s.setRule(null)}>Do not repeat</button>
      {repeat ? (
        <>
          <hr />
          <button type="button" role="menuitem" className="dropdown__item repeat-menu__item" disabled>Saved as template</button>
          <p className="repeat-menu__copy">All repetitions will have the same notes until updated</p>
        </>
      ) : null}
    </PopoverEngine>
  )
})
