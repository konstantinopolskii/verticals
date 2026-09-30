<script setup lang="ts">
// A column's carried-over plans (docs/design-handoff S4.P2): one group on top, on a faint ground, one line of notice
// ("From earlier weeks"), "Replan" with its black circle, the newest three and "N more". Pointing at a goal whose family
// has plans here, the box takes that goal's colour and shows its family's plans, at about its size (S4.P3).
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { KCardStack } from '@konstantinopolskii/vue'
import GoalCard from './GoalCard.vue'
import AppIcon from './AppIcon.vue'
import { store, todayIso } from '../store'
import { MONTH_NAMES } from '../lib/periods'
import { goalLight } from '../lib/look'
import type { GoalCardData } from '../types'

const props = defineProps<{ vertical: string; goals: GoalCardData[] }>()
const emit = defineEmits<{ replan: [from: Element] }>()

const SHOWN = 3
const open = ref(false)

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

/** "From last week" when every plan is from the period just before, "From earlier weeks" otherwise (S4.P2.014–.018). */
const notice = computed(() => {
  const { from, to } = previous.value
  const one = props.goals.every((g) => (g.anchorDate ?? '') >= from && (g.anchorDate ?? '') < to)
  const last = new Date(`${from}T12:00:00`)
  const words: Record<string, [string, string]> = {
    day: ['From yesterday', 'From earlier days'],
    week: ['From last week', 'From earlier weeks'],
    month: [`From ${MONTH_NAMES[last.getMonth()]}`, 'From earlier months'],
    quarter: [`From Q${Math.floor(last.getMonth() / 3) + 1}`, 'From earlier quarters'],
    year: [`From ${last.getFullYear()}`, 'From earlier years'],
  }
  const [single, several] = words[props.vertical] ?? ['From earlier', 'From earlier']
  return one ? single : several
})

const newestFirst = computed(() => [...props.goals].sort((a, b) => (b.anchorDate ?? '').localeCompare(a.anchorDate ?? '')))

/* The family in the box (S4.P3): the goal under the pointer, when it stands outside the box and has plans in it. */
const root = ref<HTMLElement | null>(null)
const restHeight = ref(0)
const family = computed(() => {
  const chain = store.hoverChain.value
  if (!chain || newestFirst.value.some((g) => g.id === chain.id)) return null
  const plans = newestFirst.value.filter((g) => chain.set.has(g.id))
  return plans.length ? { id: chain.id, plans } : null
})
/* A family has one root, so one value colour: its plans carry it. */
const lit = computed(() => (family.value ? goalLight(family.value.plans[0]!.color) : null))
const list = computed(() => family.value?.plans ?? newestFirst.value)
const visible = computed(() => (open.value && !family.value ? list.value : list.value.slice(0, SHOWN)))
const more = computed(() => list.value.length - SHOWN)

let sizes: ResizeObserver | null = null
onMounted(() => {
  sizes = typeof ResizeObserver === 'undefined' ? null : new ResizeObserver(() => {
    if (!family.value && root.value) restHeight.value = root.value.offsetHeight
  })
  if (root.value) sizes?.observe(root.value)
})
onBeforeUnmount(() => sizes?.disconnect())

function cardProps(goal: GoalCardData) {
  return {
    id: goal.id, parentId: goal.parentId, title: goal.title, done: goal.done, color: goal.color, vertical: goal.vertical,
    columnVertical: props.vertical, ghost: true, children: goal.children, repeat: goal.repeat,
  }
}
</script>

<template>
  <section
    ref="root"
    class="carried-group"
    :class="{ 'carried-group--lit': !!lit }"
    data-role="carried-group"
    :data-count="goals.length"
    :style="{ ...(lit ?? {}), minHeight: family ? `${restHeight}px` : undefined }"
  >
    <div class="carried-group__head">
      <span class="carried-group__notice" data-role="carried-notice">{{ notice }}</span>
      <button type="button" class="carried-group__replan" data-role="replan" @click="emit('replan', $event.currentTarget as Element)">
        Replan<span class="carried-group__dot" aria-hidden="true"></span>
      </button>
    </div>
    <KCardStack dense data-section="carried">
      <GoalCard v-for="goal in visible" :key="goal.id" v-bind="cardProps(goal)" />
    </KCardStack>
    <button v-if="more > 0" type="button" class="carried-group__more" data-role="carried-more" @click="open = !open">
      {{ open && !family ? 'Show fewer' : `${more} more` }}<AppIcon name="chevron-down" :size="12" :class="{ 'carried-group__chevron--open': open && !family }" />
    </button>
  </section>
</template>

<style>
.carried-group {
  box-sizing: border-box;
  /* 202 px, a goal's own highlight and one more pixel each side; the cards on it keep the column's x. */
  margin: 0 -1px 12px 3px;
  padding: 8px 0 6px;
  border-radius: 8px;
  background: #f5f5f1;
  transition: background-color 200ms var(--vt-ease-large);
}
.carried-group--lit { background: rgb(var(--vt-pale)); }
.carried-group__head { display: flex; align-items: baseline; justify-content: space-between; padding: 0 10px 4px 11px; }
.carried-group__notice, .carried-group__replan, .carried-group__more {
  color: rgb(45 48 54 / 52%);
  font: 400 12px/16px var(--font-body);
}
.pattern-vertical-board__column--active .carried-group__notice,
.pattern-vertical-board__column--active .carried-group__replan,
.pattern-vertical-board__column--active .carried-group__more { font-size: 15px; line-height: 20px; }
.carried-group__replan { display: inline-flex; align-items: center; gap: 6px; padding: 0; border: 0; background: none; cursor: pointer; }
.carried-group__dot {
  display: block;
  width: 5px;
  height: 5px;
  border-radius: 50%;
  background: #000;
  transition: width 160ms var(--vt-ease-large), height 160ms var(--vt-ease-large);
}
.pattern-vertical-board__column--active .carried-group__dot { width: 6px; height: 6px; }
.carried-group__replan:hover .carried-group__dot { width: 7px; height: 7px; }
.carried-group__replan:active .carried-group__dot { width: 4.5px; height: 4.5px; transition-duration: 90ms; }
.carried-group__more { display: inline-flex; align-items: center; gap: 2px; padding: 2px 0 0 33px; border: 0; background: none; text-align: left; cursor: pointer; }
.carried-group > [data-section='carried'] { margin: 0 1px 0 -3px; }
/* The cards stand on the ground itself: the kit paints a stack's cards, the first one too, in the page's colour. */
.carried-group > [data-section='carried'] { --color-bg: transparent; --color-surface-overlay: transparent; }
.carried-group__chevron--open { transform: rotate(180deg); }
.carried-group .goal-card__row::before { opacity: 0 !important; }
</style>
