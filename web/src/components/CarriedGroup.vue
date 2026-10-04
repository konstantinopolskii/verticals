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

const props = defineProps<{ vertical: string; goals: GoalCardData[] }>()
const emit = defineEmits<{ replan: [from: Element] }>()

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
        <button type="button" class="carried-group__replan" data-role="replan" @click="emit('replan', $event.currentTarget as Element)">
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

<style>
/* The place keeps its height while a goal under the box is pointed at (S4.P3.004), and the box fills it: what the filter
   leaves empty inside the box is the mascot's room, above "See all" at the very bottom (KK 2026-10-04: an empty white
   place under a box that got shorter looked broken). */
.carried-place {
  display: flex;
  flex-direction: column;
  /* 202 px, a goal's own highlight and one more pixel each side; the cards on it keep the column's x. */
  margin: 0 -1px 12px 3px;
}
.carried-group {
  box-sizing: border-box;
  flex: 1 1 auto;
  display: flex;
  flex-direction: column;
  padding: 8px 0 6px;
  border-radius: 8px;
  background: #f5f5f1;
  transition: background-color 200ms var(--vt-ease-large), transform var(--motion-lift-out) var(--vt-ease-medium);
}
.carried-group--lit { background: rgb(var(--vt-pale)); }
/* A box in a family's colour stands above the column's veil with that family (goalCard.css): under it, its colour washed
   out to a grey behind the family's bright plan (KK, 4 Oct 2026: "weird bug with the background of the due block"). */
.pattern-vertical-board--family .carried-group--lit { position: relative; z-index: 2; }
/* Out from under the veil, the box turns off what the veil would have: the steps of its plans that aren't in the family. */
.pattern-vertical-board--family .carried-group--lit .goal-card:not([data-light], [data-holding]) > .goal-card__row {
  opacity: var(--goal-off-opacity);
  filter: grayscale(var(--goal-off-grey));
}
/* Pointing into the box lifts it as one piece, the way a goal lifts (`lib/cardLift.ts`), by the same room: a tall box
   grows only as much as the margin under it allows. */
.carried-group--lifted {
  position: relative;
  z-index: 6;
  transform: translateY(-2px) scale(var(--carried-lift, 1.06));
  transition-duration: 200ms, var(--motion-lift-in);
}
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
.carried-group > * { flex: none; }
.carried-group > .carried-gap { flex: 1 1 0; }
/* In the bottom corner, the box's last line: it is the way out of a filter, and says so ("See all"). */
.carried-group__more { display: inline-flex; align-self: flex-start; align-items: center; gap: 2px; padding: 2px 0 0 11px; border: 0; background: none; text-align: left; cursor: pointer; }
.carried-group > [data-section='carried'] { margin: 0 1px 0 -3px; }
/* The cards stand on the ground itself: the kit paints a stack's cards, the first one too, in the page's colour. */
.carried-group > [data-section='carried'] { --color-bg: transparent; --color-surface-overlay: transparent; }
.carried-group__chevron--open { transform: rotate(180deg); }
.carried-group:not(.carried-group--open) .goal-card__row::before { opacity: 0 !important; }
/* A plan open (KK 2026-10-02): the box is only its header, a line on top like a level stepped through, and the opened plan
   stands under it on its own colour. Opening ends the box's lift at once: a lift easing out made the box a layer of its
   own for 220 ms, which kept the opened plan under the column's veil, pale, until it lit up in one frame (the motion
   review of 3 Oct 2026); the move that opens the plan read it lifted and lands it at rest (lib/familyMotion.ts). */
.carried-group--open {
  padding: 0;
  background: transparent;
  transform: none;
  transition: background-color 200ms var(--vt-ease-large);
}
.carried-group--open .carried-group__head {
  /* above the column's veil, like the column's name: it is not a goal, and it is the way back */
  position: relative;
  z-index: 2;
  margin: 0 0 8px;
  padding: 8px 10px 8px 11px;
  border-radius: 8px;
  background: #f5f5f1;
  cursor: pointer;
}
/* Copies of what leaves the box while it changes (lib/carriedMotion.ts): laid over it where the originals stood, drawn on
   the box's own ground like its plans, and never in the way of the pointer. */
.carried-ghosts {
  position: absolute;
  inset: 0;
  pointer-events: none;
  --color-bg: transparent;
  --color-surface-overlay: transparent;
}
.carried-ghosts > .carried-ghost { position: absolute; box-sizing: border-box; margin: 0; }
/* A plan under the pointer takes the goal's hover tint on the box's own colour, the way a subtask does. An open plan
   keeps its whole colour (KK, 27 Sep 2026): dimming only its row made a seam against its list, reported 4 Oct. */
.carried-group .goal-card:not(.goal-card--detail-open):hover > .goal-card__row::before { opacity: var(--goal-light-tint, .7) !important; }
</style>
