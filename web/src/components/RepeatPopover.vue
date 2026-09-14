<script setup lang="ts">
import { computed, ref } from 'vue'
import AppIcon from './AppIcon.vue'
import type { RepeatRule } from '../lib/api'
import { store } from '../store'
import PopoverEngine from './PopoverEngine.vue'

const props = defineProps<{
  id: string
  vertical: string
  repeat: RepeatRule | null
  hasChildren: boolean
  compact?: boolean
}>()

const dayMode = ref<'weekdays' | 'monthdays'>('weekdays')
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

const presets = computed(() => PRESETS[props.vertical] ?? [])

/** Field-by-field, NOT JSON.stringify: postgres hands jsonb back in its own key order
 *  (`{"interval":1,"frequency":"monthly"}`), the presets here are written frequency-first, and
 *  stringify equality made every preset compare unequal — so the active rule never got its mark
 *  (D89, caught live 2026-08-11). `end_date` is deliberately ignored: it is an end condition on a
 *  rule, not part of which rule it is. */
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
</script>

<template>
  <template v-if="hasChildren">
    <button
      type="button"
      :role="props.compact ? undefined : 'menuitem'"
      :class="props.compact ? 'goal-detail__meta-trigger' : 'dropdown__item goal-actions__item'"
      data-action="repeat"
      :aria-label="props.compact ? 'Repeat' : undefined"
      disabled
      title="Goals with subgoals cannot be recurrent. Tip: use notes with checkboxes."
    >
      <AppIcon name="repeat" :size="props.compact ? 18 : 24" />
      <span v-if="!props.compact">Repeat</span>
    </button>
  </template>
  <PopoverEngine
    v-else
    nested
    :fixed-width="200"
    :offset="[3, -8]"
    data-action="repeat"
    surface-class="goal-actions__submenu repeat-menu"
    :surface-attrs="{ 'data-role': 'repeat-menu' }"
  >
    <template #trigger>
      <button
        type="button"
        :role="props.compact ? undefined : 'menuitem'"
        :class="props.compact ? 'goal-detail__meta-trigger' : 'dropdown__item goal-actions__item'"
        :aria-label="props.compact ? 'Repeat' : undefined"
      >
        <AppIcon name="repeat" :size="props.compact ? 18 : 24" />
        <span v-if="!props.compact">Repeat</span>
        <span v-if="!props.compact" data-role="submenu-arrow" aria-hidden="true"><AppIcon name="chevron-right" :size="14" /></span>
      </button>
    </template>

    <p class="repeat-menu__heading">{{ TITLES[vertical] }}</p>
    <button
      v-for="([label, rule]) in presets"
      :key="label"
      type="button"
      role="menuitem"
      class="dropdown__item repeat-menu__item"
      :class="{ '_active': sameRule(rule) }"
      @click="setRule(rule)"
    >{{ label }}</button>

    <PopoverEngine
      nested
      :fixed-width="200"
      surface-class="goal-actions__submenu repeat-menu repeat-custom"
      :surface-attrs="{ 'data-role': 'repeat-custom' }"
    >
      <template #trigger>
        <button type="button" role="menuitem" class="dropdown__item repeat-menu__item">
          <span>Custom</span><span data-role="submenu-arrow" aria-hidden="true"><AppIcon name="chevron-right" :size="14" /></span>
        </button>
      </template>

      <template v-if="vertical === 'day'">
        <div class="repeat-custom__segments">
          <button type="button" :class="{ '_active': dayMode === 'weekdays' }" @click.stop="dayMode = 'weekdays'">Weekdays</button>
          <button type="button" :class="{ '_active': dayMode === 'monthdays' }" @click.stop="dayMode = 'monthdays'">Monthdays</button>
        </div>
        <div v-if="dayMode === 'weekdays'" class="repeat-custom__list">
          <button
            v-for="(label, index) in WEEKDAYS"
            :key="label"
            type="button"
            role="menuitem"
            class="dropdown__item"
            :class="{ '_active': repeat?.weekdays?.includes(index + 1) }"
            @click="toggleSelection('weekdays', index + 1)"
          >{{ label }}</button>
        </div>
        <div v-else class="repeat-custom__days">
          <button
            v-for="day in 31"
            :key="day"
            type="button"
            role="menuitem"
            class="dropdown__item"
            :class="{ '_active': repeat?.month_days?.includes(day) }"
            @click="toggleSelection('month_days', day)"
          >{{ day }}</button>
        </div>
      </template>
      <template v-else-if="vertical === 'week'">
        <button v-for="interval in [2, 3, 4, 5]" :key="interval" type="button" role="menuitem" class="dropdown__item" @click="setRule({ frequency: 'weekly', interval })">Every {{ interval }} weeks</button>
      </template>
      <template v-else-if="vertical === 'month'">
        <button v-for="(label, index) in MONTHS" :key="label" type="button" role="menuitem" class="dropdown__item" @click="setRule({ frequency: 'yearly', interval: 1, months: [index + 1] })">{{ label }}</button>
      </template>
      <template v-else-if="vertical === 'quarter'">
        <button v-for="quarter in 4" :key="quarter" type="button" role="menuitem" class="dropdown__item" @click="setRule({ frequency: 'yearly', interval: 1, quarters: [quarter] })">Q{{ quarter }}</button>
      </template>
      <template v-else-if="vertical === 'year'">
        <button v-for="interval in 9" :key="interval" type="button" role="menuitem" class="dropdown__item" @click="setRule({ frequency: 'yearly', interval: interval + 1 })">Every {{ interval + 1 }} years</button>
      </template>
      <template v-else>
        <button v-for="interval in 9" :key="interval" type="button" role="menuitem" class="dropdown__item" @click="setRule({ frequency: 'every_decade', interval: interval + 1 })">Every {{ interval + 1 }} decades</button>
      </template>
    </PopoverEngine>

    <hr>
    <PopoverEngine
      v-if="repeat"
      nested
      :fixed-width="200"
      surface-class="goal-actions__submenu repeat-menu repeat-end"
      :surface-attrs="{ 'data-role': 'repeat-end' }"
    >
      <template #trigger>
        <button type="button" role="menuitem" class="dropdown__item repeat-menu__item">
          <span>End repeat</span><span data-role="submenu-arrow" aria-hidden="true"><AppIcon name="chevron-right" :size="14" /></span>
        </button>
      </template>
      <label class="repeat-end__field">
        <span>End date</span>
        <input type="date" :value="repeat.end_date ?? ''" @change="setEnd">
      </label>
    </PopoverEngine>
    <hr v-if="repeat">
    <button type="button" role="menuitem" class="dropdown__item repeat-menu__item" @click="setRule(null)">Do not repeat</button>
    <template v-if="repeat">
      <hr>
      <button type="button" role="menuitem" class="dropdown__item repeat-menu__item" disabled>Saved as template</button>
      <p class="repeat-menu__copy">All repetitions will have the same notes until updated</p>
    </template>
  </PopoverEngine>
</template>

<style>
.repeat-menu { padding-block: 8px; }
.repeat-menu > hr { height: 1px; margin: 8px 0; border: 0; background: rgba(255, 255, 255, .14); }
.repeat-menu__heading,
.repeat-menu__copy { margin: 0; padding: 4px 14px; color: rgba(255, 255, 255, .55); font-size: 12px; line-height: 18px; }
.repeat-menu__item.repeat-menu__item { display: flex; justify-content: space-between; width: 100%; padding: 4px 14px; }
.repeat-menu ._active { background: rgba(255, 255, 255, .12); }
.repeat-custom__segments { display: grid !important; grid-template-columns: 1fr 1fr; padding: 0 8px 8px; }
.repeat-custom__segments button { justify-content: center; padding: 4px; border-bottom: 1px solid transparent; }
.repeat-custom__segments button._active { border-bottom-color: currentColor; }
.repeat-custom__list { display: block !important; }
.repeat-custom__days { display: grid !important; grid-template-columns: repeat(7, 1fr); padding: 0 8px; }
.repeat-custom__days .dropdown__item { justify-content: center; padding: 4px; }
.repeat-end__field { display: grid; gap: 8px; padding: 12px 14px; font-size: 13px; }
.repeat-end__field input { box-sizing: border-box; width: 100%; padding: 6px; border: 1px solid rgba(255, 255, 255, .2); border-radius: 4px; background: transparent; color: inherit; }
</style>
