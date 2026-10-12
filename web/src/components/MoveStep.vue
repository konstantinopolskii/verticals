<script setup lang="ts">
// A step of the goal's menu (docs/design-handoff S5.P5): it takes the menu's place, with ‹ and its name at the top, and is
// never a window of its own. Date lists its levels; each level is a plain list forward of its periods' starts; a specific
// date opens the most basic calendar; Into a goal finds the goal to sit under and makes this one its last step.
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import AppIcon from './AppIcon.vue'
import { store, todayIso } from '../store'
import { findGoals, type GoalCard } from '../lib/api'
import { findGoal } from '../lib/boardIndex'
import { VERTICAL_SCALES, MONTH_NAMES, verticalRank, type VerticalScale } from '../lib/periods'
import { isoDate, localDate, periodKeyFor } from '../lib/schedule'
import './moveStep.css'

export type MoveStepName = 'date' | 'week' | 'month' | 'quarter' | 'year' | 'calendar' | 'under'

const props = defineProps<{ id: string; step: MoveStepName }>()
const emit = defineEmits<{ go: [step: MoveStepName | null]; done: [] }>()

const root = ref<HTMLElement | null>(null)
const goal = computed(() => findGoal(store.state.board, props.id) ?? null)
const today = computed(() => localDate(todayIso()))
const TITLES: Record<MoveStepName, string> = {
  date: 'Move to a date', week: 'Week', month: 'Month', quarter: 'Quarter', year: 'Year', calendar: 'Date', under: 'Into a goal',
}

function back(): void {
  emit('go', props.step === 'date' || props.step === 'under' ? null : 'date')
}
function schedule(scale: VerticalScale, day: Date): void {
  void store.scheduleGoalQuick(props.id, scale, periodKeyFor(scale, day), isoDate(day))
  emit('done')
}

/* The levels: only the starts of their periods, forward from this one (S5.P5.013, .014). */
interface Row { key: string; how: string; day: string; month: string; date: Date; own: boolean; newMonth: boolean }
function starts(scale: VerticalScale, count: number): Date[] {
  const t = today.value
  const first = scale === 'week' ? new Date(t.getFullYear(), t.getMonth(), t.getDate() - ((t.getDay() + 6) % 7))
    : scale === 'month' ? new Date(t.getFullYear(), t.getMonth(), 1)
      : scale === 'quarter' ? new Date(t.getFullYear(), Math.floor(t.getMonth() / 3) * 3, 1)
        : new Date(t.getFullYear(), 0, 1)
  return Array.from({ length: count }, (_, i) => {
    if (scale === 'week') return new Date(first.getFullYear(), first.getMonth(), first.getDate() + 7 * i)
    if (scale === 'month') return new Date(first.getFullYear(), first.getMonth() + i, 1)
    if (scale === 'quarter') return new Date(first.getFullYear(), first.getMonth() + 3 * i, 1)
    return new Date(first.getFullYear() + i, 0, 1)
  })
}
const rows = computed<Row[]>(() => {
  const scale = props.step
  if (scale !== 'week' && scale !== 'month' && scale !== 'quarter' && scale !== 'year') return []
  const own = goal.value?.vertical === scale ? goal.value.period_key : null
  let lastMonth = -1
  return starts(scale, scale === 'week' ? 13 : scale === 'year' ? 5 : 8).map((d, i) => {
    const how = i === 0 ? 'This' : i === 1 ? 'Next' : String(i)
    const key = periodKeyFor(scale, d)
    if (scale === 'week') {
      // The month in full, once: on the first week that starts in it (S5.P5.015).
      const month = d.getMonth() !== lastMonth ? MONTH_NAMES[d.getMonth()]! : ''
      // A small gap before each month after the first (S5.P5.F04).
      const newMonth = i > 0 && !!month
      lastMonth = d.getMonth()
      return { key, how, day: String(d.getDate()), month, date: d, own: key === own, newMonth }
    }
    const label = scale === 'month' ? `${MONTH_NAMES[d.getMonth()]}${d.getFullYear() !== today.value.getFullYear() ? ` ${d.getFullYear()}` : ''}`
      : scale === 'quarter' ? `Q${Math.floor(d.getMonth() / 3) + 1} ${d.getFullYear()}` : String(d.getFullYear())
    return { key, how, day: '', month: label, date: d, own: key === own, newMonth: false }
  })
})

/* The calendar: its month on the left of the arrows, Monday first; today black, the goal's own day on its green, past days
   grey and still yours (S5.P5.017, .038, .040). */
const shown = ref(new Date(today.value.getFullYear(), today.value.getMonth(), 1))
const monthLabel = computed(() => `${MONTH_NAMES[shown.value.getMonth()]!.slice(0, 3)} ’${String(shown.value.getFullYear()).slice(2)}`)
const days = computed(() => {
  const first = shown.value
  const lead = (first.getDay() + 6) % 7
  const count = new Date(first.getFullYear(), first.getMonth() + 1, 0).getDate()
  const own = goal.value?.vertical === 'day' ? goal.value.anchor_date : null
  const todayKey = isoDate(today.value)
  return [
    ...Array.from({ length: lead }, () => null),
    ...Array.from({ length: count }, (_, i) => {
      const date = new Date(first.getFullYear(), first.getMonth(), i + 1)
      const key = isoDate(date)
      return { date, key, today: key === todayKey, own: key === own, past: key < todayKey }
    }),
  ]
})
function stepMonth(n: number): void {
  shown.value = new Date(shown.value.getFullYear(), shown.value.getMonth() + n, 1)
}

/* Under: the goal it sits under now first, then the goals of each vertical from the nearest; typing narrows it to the
   names that match, each with its vertical (S5.P5.010-.012, .027). */
const query = ref('')
const found = ref<GoalCard[] | null>(null)
let findVersion = 0
watch(query, async (q) => {
  const version = ++findVersion
  // The search starts at three letters; before that the board's own goals are narrowed here.
  if (q.trim().length < 3) { found.value = null; return }
  const result = await findGoals(q.trim()).catch(() => null)
  if (version === findVersion) found.value = result ? result.goals : []
})
function subtree(): Set<string> {
  const out = new Set<string>([props.id])
  const board = store.state.board
  const walk = (id: string) => {
    for (const kid of board?.children[id] ?? []) { out.add(kid.id); walk(kid.id) }
  }
  walk(props.id)
  return out
}
const candidates = computed(() => {
  const own = goal.value
  const skip = subtree()
  const pool = found.value ?? (store.state.board?.columns.flatMap((c) => c.goals) ?? [])
  const seen = new Set<string>()
  const q = query.value.trim().toLowerCase()
  const list = pool.filter((g) => {
    if (skip.has(g.id) || g.id === own?.parent_id || seen.has(g.id) || g.done_at) return false
    if (q && !found.value && !g.title.toLowerCase().includes(q)) return false
    seen.add(g.id)
    return true
  })
  const rank = (g: GoalCard) => (g.vertical ? VERTICAL_SCALES.indexOf(g.vertical as VerticalScale) : 99)
  const from = own?.vertical ? verticalRank(own.vertical as VerticalScale) : 0
  return found.value ? list : [...list].sort((a, b) => Math.abs(rank(a) - from) - Math.abs(rank(b) - from))
})
const nowUnder = computed(() => {
  const parentId = goal.value?.parent_id
  return parentId ? findGoal(store.state.board, parentId) ?? null : null
})
function parts(title: string): Array<{ text: string; match: boolean }> {
  const q = query.value.trim()
  if (!q) return [{ text: title, match: false }]
  const at = title.toLowerCase().indexOf(q.toLowerCase())
  if (at < 0) return [{ text: title, match: false }]
  return [
    { text: title.slice(0, at), match: false },
    { text: title.slice(at, at + q.length), match: true },
    { text: title.slice(at + q.length), match: false },
  ].filter((p) => p.text)
}
function under(target: GoalCard): void {
  // Under a smaller vertical's goal it takes that goal's period first (S5.P6.002); otherwise it keeps its own dates.
  const own = goal.value?.vertical
  const smaller = !!own && !!target.vertical && verticalRank(own as VerticalScale) > verticalRank(target.vertical as VerticalScale)
  void (smaller ? store.combineInto(props.id, target.id) : store.reparentQuick(props.id, target.id))
  emit('done')
}
function out(): void {
  void store.reparentQuick(props.id, null)
  emit('done')
}
function verticalName(h: string | null): string {
  return h ? h === 'decade' ? '3 years' : h[0]!.toUpperCase() + h.slice(1) : 'Inbox'
}
function onSearchKey(event: KeyboardEvent): void {
  if (event.key === 'Enter' && candidates.value[0]) {
    event.preventDefault()
    under(candidates.value[0])
  }
}
function onKey(event: KeyboardEvent): void {
  const inField = (event.target as HTMLElement).matches('input')
  if (event.key === 'ArrowLeft' && !inField) {
    event.preventDefault()
    back()
  }
}

/* Each step takes the focus, so ↑ ↓ ↵ and ← work at once (S5.P5.021). */
async function focusFirst(): Promise<void> {
  await nextTick()
  root.value?.querySelector<HTMLElement>('input, [role="menuitem"]:not([data-back])')?.focus()
}
onMounted(focusFirst)
watch(() => props.step, focusFirst)
</script>

<template>
  <div ref="root" class="move-step" :data-step="step" data-role="move-step" @keydown="onKey">
    <div class="move-step__head">
      <button type="button" class="move-step__back" data-back role="menuitem" :aria-label="`Back from ${TITLES[step]}`" @click.stop="back">
        <AppIcon name="chevron-left" :size="14" /><span class="move-step__title">{{ TITLES[step] }}</span>
      </button>
      <span v-if="step === 'calendar'" class="move-step__month">
        {{ monthLabel }}
        <button type="button" class="move-step__arrow" aria-label="Previous month" @click.stop="stepMonth(-1)"><AppIcon name="chevron-left" :size="14" /></button>
        <button type="button" class="move-step__arrow" aria-label="Next month" @click.stop="stepMonth(1)"><AppIcon name="chevron-right" :size="14" /></button>
      </span>
    </div>

    <template v-if="step === 'date'">
      <button v-for="level in (['week', 'month', 'quarter', 'year'] as const)" :key="level" type="button" role="menuitem"
        class="dropdown__item goal-actions__item" :data-level="level" @click.stop="emit('go', level)">
        <span>{{ TITLES[level] }}</span><span data-role="submenu-arrow" aria-hidden="true"><AppIcon name="chevron-right" :size="14" /></span>
      </button>
      <hr>
      <button type="button" role="menuitem" class="dropdown__item goal-actions__item" data-level="calendar" @click.stop="emit('go', 'calendar')">
        <span>Specific date</span><span data-role="submenu-arrow" aria-hidden="true"><AppIcon name="chevron-right" :size="14" /></span>
      </button>
    </template>

    <template v-else-if="rows.length">
      <button v-for="row in rows" :key="row.key" type="button" role="menuitem" class="move-step__row"
        :class="{ 'move-step__row--own': row.own, 'move-step__row--table': step === 'week', 'move-step__row--month': row.newMonth }" :data-period-key="row.key"
        @click.stop="schedule(step as VerticalScale, row.date)">
        <span class="move-step__how" :class="{ 'move-step__how--word': !/^\d+$/.test(row.how) }">{{ row.how }}</span>
        <span v-if="step === 'week'" class="move-step__day">{{ row.day }}</span>
        <span class="move-step__name">{{ row.month }}</span>
      </button>
    </template>

    <div v-else-if="step === 'calendar'" class="move-step__calendar">
      <span v-for="d in ['M', 'T', 'W', 'T', 'F', 'S', 'S']" :key="d + Math.random()" class="move-step__weekday" aria-hidden="true">{{ d }}</span>
      <template v-for="(cell, i) in days" :key="i">
        <span v-if="!cell" aria-hidden="true"></span>
        <button v-else type="button" role="menuitem" class="move-step__date"
          :class="{ 'is-today': cell.today, 'is-own': cell.own, 'is-past': cell.past }" :data-date="cell.key"
          @click.stop="schedule('day', cell.date)">{{ cell.date.getDate() }}</button>
      </template>
    </div>

    <template v-else-if="step === 'under'">
      <label class="move-step__search">
        <AppIcon name="search" :size="16" />
        <input v-model="query" type="text" placeholder="Find a goal" aria-label="Find the goal to move under" data-role="move-under-search" @keydown="onSearchKey" />
        <button v-if="query" type="button" class="move-step__clear" aria-label="Clear" @click.stop="query = ''"><AppIcon name="x-circle" :size="16" /></button>
      </label>
      <template v-if="nowUnder && !query">
        <p class="move-step__label">Now under</p>
        <div class="move-step__goal move-step__goal--now" :data-color="nowUnder.color ?? undefined">
          <span class="move-step__square" :style="{ background: nowUnder.color ?? '#d9d9dc' }"></span>
          <span class="move-step__goal-title">{{ nowUnder.title }}</span>
          <span class="move-step__vertical">{{ verticalName(nowUnder.vertical) }}</span>
        </div>
        <button type="button" role="menuitem" class="move-step__goal move-step__goal--out" data-parent-id="" @click.stop="out">
          <span></span><span class="move-step__goal-title">Not under any goal</span><span></span>
        </button>
        <hr>
      </template>
      <div class="move-step__list">
        <button v-for="target in candidates.slice(0, 60)" :key="target.id" type="button" role="menuitem" class="move-step__goal"
          :data-parent-id="target.id" @click.stop="under(target)">
          <span class="move-step__square" :style="{ background: target.color ?? '#d9d9dc' }"></span>
          <span class="move-step__goal-title"><template v-for="(part, i) in parts(target.title)" :key="i"><strong v-if="part.match">{{ part.text }}</strong><template v-else>{{ part.text }}</template></template></span>
          <span class="move-step__vertical">{{ verticalName(target.vertical) }}</span>
        </button>
      </div>
    </template>
  </div>
</template>
