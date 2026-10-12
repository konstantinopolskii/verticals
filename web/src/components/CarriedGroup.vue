<script setup lang="ts">
// A column's carried-over plans (docs/design-handoff S4.P2): one group on top, on a faint ground, one line of notice
// ("8 from Sep"), "Replan" with its black circle, the newest three and "N more". Pointing at a goal whose family has
// plans here, the box takes that goal's colour and shows its family's plans, and its height follows them (S4.P3); what
// it shows, how long it keeps it and where its height goes is `lib/carriedFilter.ts`.
import { computed, ref } from 'vue'
import { KCardStack } from '@konstantinopolskii/vue'
import GoalCard from './GoalCard.vue'
import AppIcon from './AppIcon.vue'
import CarriedMascot from './CarriedMascot.vue'
import { store, todayIso } from '../store'
import { MONTH_NAMES } from '../lib/periods'
import { useCarriedFilter } from '../lib/carriedFilter'
import type { GoalCardData } from '../types'
import './carriedGroup.css'

const props = defineProps<{ vertical: string; goals: GoalCardData[] }>()
const emit = defineEmits<{ replan: [from: Element, plans: { id: string; title: string }[]] }>()

function isoDay(d: Date): string {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}
/** The start of the period before the current one, for the column's scale. */
const previous = computed(() => {
  const today = new Date(`${todayIso()}T12:00:00`)
  const d = new Date(today)
  switch (props.vertical) {
    case 'day': d.setDate(d.getDate() - 1); return { from: isoDay(d), to: isoDay(today) }
    case 'week': {
      const monday = new Date(today); monday.setDate(today.getDate() - ((today.getDay() + 6) % 7))
      const before = new Date(monday); before.setDate(monday.getDate() - 7)
      return { from: isoDay(before), to: isoDay(monday) }
    }
    case 'month': {
      const first = new Date(today.getFullYear(), today.getMonth(), 1, 12)
      return { from: isoDay(new Date(today.getFullYear(), today.getMonth() - 1, 1, 12)), to: isoDay(first) }
    }
    case 'quarter': {
      const q = Math.floor(today.getMonth() / 3)
      return { from: isoDay(new Date(today.getFullYear(), (q - 1) * 3, 1, 12)), to: isoDay(new Date(today.getFullYear(), q * 3, 1, 12)) }
    }
    default:
      return { from: `${today.getFullYear() - 1}-01-01`, to: `${today.getFullYear()}-01-01` }
  }
})

/** "8 from Sep": how many, and from when. "From last week" when every plan is from the period just before, "From earlier
 *  weeks" otherwise (S4.P2.014–.018); the month is three letters so the line fits a narrow column (KK 2026-10-02). */
const notice = computed(() => {
  const { from, to } = previous.value
  const one = props.goals.every((g) => (g.anchorDate ?? '') >= from && (g.anchorDate ?? '') < to)
  const last = new Date(`${from}T12:00:00`)
  const words: Record<string, [string, string]> = {
    day: ['yesterday', 'earlier days'],
    week: ['last week', 'earlier weeks'],
    month: [MONTH_NAMES[last.getMonth()]!.slice(0, 3), 'earlier months'],
    quarter: [`Q${Math.floor(last.getMonth() / 3) + 1}`, 'earlier quarters'],
    year: [`${last.getFullYear()}`, 'earlier years'],
  }
  const [single, several] = words[props.vertical] ?? ['earlier', 'earlier']
  return `${props.goals.length} from ${one ? single : several}`
})

const newestFirst = computed(() => [...props.goals].sort((a, b) => (b.anchorDate ?? '').localeCompare(a.anchorDate ?? '')))

/* What the box shows and where its height goes (S4.P3): `lib/carriedFilter.ts`. The box is the tinted piece. While a goal
   under it is pointed at, the place around it keeps its height and the box fills it; the room the filter leaves inside
   the box is the mascot's (KK 2026-10-04: the white place under a box that got shorter looked broken). */
const root = ref<HTMLElement | null>(null)
const place = ref<HTMLElement | null>(null)
const mascot = ref<InstanceType<typeof CarriedMascot> | null>(null)
const { hold, pinned, gap, circle, lift, lit, visible, family, button, opened, more: onMore, openPlan, enter, leave } = useCarriedFilter({
  vertical: () => props.vertical,
  plans: () => newestFirst.value,
  box: root,
  place,
  room: () => {
    const m = mascot.value
    const el = m?.$el as HTMLElement | undefined
    return m && el ? { el, need: m.need() } : null
  },
})

/** What the mascot says: why the box is emptier than it was (KK 2026-10-04: its shy jokes didn't say). The count line
 *  above it already says where the plans come from. It speaks only when that is all of the story: the goal has nothing
 *  here, or the box shows everything it has. */
const words = computed(() => {
  const plans = family.value
  if (!plans) return null
  if (!plans.length) return 'No due plans for this goal'
  return visible.value.length === plans.length ? "That's all for this goal" : null
})

/** A plan is open: the header line is the way back, anywhere on it but "Replan". */
function onHeadClick(event: MouseEvent): void {
  if (openPlan.value && !(event.target as Element).closest('[data-role="replan"]')) store.closeGoal()
}

function cardProps(goal: GoalCardData) {
  return {
    id: goal.id, parentId: goal.parentId, title: goal.title, done: goal.done, color: goal.color, vertical: goal.vertical,
    columnVertical: props.vertical, ghost: true, children: goal.children, repeat: goal.repeat,
  }
}
</script>

<template>
  <div ref="place" class="carried-place" data-role="carried-place" :style="{ minHeight: hold && !openPlan ? `${hold}px` : undefined }">
    <section
      ref="root"
      class="carried-group"
      :class="{ 'carried-group--lit': !!lit, 'carried-group--lifted': pinned && !openPlan, 'carried-group--open': !!openPlan }"
      data-role="carried-group"
      :data-count="goals.length"
      :style="{ ...(lit ?? {}), '--carried-lift': lift ?? undefined }"
      @pointerenter="enter"
      @pointerleave="leave"
    >
      <div class="carried-group__head" @click="onHeadClick">
        <span class="carried-group__notice" data-role="carried-notice">{{ notice }}</span>
        <button type="button" class="carried-group__replan" data-role="replan" @click="emit('replan', $event.currentTarget as Element, goals.map((g) => ({ id: g.id, title: g.title })))">
          Replan<span class="carried-group__dot" aria-hidden="true"></span>
        </button>
      </div>
      <KCardStack dense data-section="carried">
        <GoalCard v-for="goal in visible" :key="goal.id" v-bind="cardProps(goal)" />
      </KCardStack>
      <CarriedMascot ref="mascot" :on="gap && !openPlan && words !== null" :words="words" :circle="circle" />
      <button v-if="button" type="button" class="carried-group__more" data-role="carried-more" @click="onMore">
        {{ button }}<AppIcon name="chevron-down" :size="12" :class="{ 'carried-group__chevron--open': opened }" />
      </button>
    </section>
  </div>
</template>
