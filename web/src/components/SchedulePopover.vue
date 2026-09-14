<script setup lang="ts">
/* docs/IMPLEMENTATION.md WP-17: all seven vertical_scale values in one surface, one click to
   schedule, no modal. Layout follows RESEARCH.md "The Schedule picker is the vertical picker"
   (decade row; year + four quarters; month row; ISO-week column beside a day grid; a
   today/tomorrow/this-week footer) plus `life`, which that ASCII sketch and ARCHITECTURE.md §6
   both omit but E2E.md S-66 requires: life is a real schedulable vertical (`vertical_scale` enum,
   ARCHITECTURE.md §3) and leaving it out would ship the one-sided capability AC-195 forbids.

   Purely presentational and controlled: every label is a prop (nothing here calls `Date` or
   does period-key arithmetic — that is the whole point of periods.ts's header comment), and
   `select`/`navigate` are the only two things this component decides for itself. The caller
   (WP-22) owns real dates, the store, and the API call.

   Built on the shared PopoverEngine: it gives portal placement, Escape/outside-pointer dismissal,
   root arbitration, focus return, and a `role="menu"` surface. Every clickable target
   here carries the kit's own `.dropdown__item` class (not a local
   invention) so it also inherits hover/focus-visible styling and — because the popover's ARIA
   role is `menu` — the roving arrow-key/Home/End navigation wires against any
   `.dropdown__item` it finds, which is the standards-correct keyboard behaviour for that role.
   The four ‹/› steppers are deliberately NOT `.dropdown__item`: they page what the decade/year/
   month row is currently *showing*, they do not themselves assign anything, so they sit outside
   the roving set the same way a menu's non-item chrome would. Plain buttons stay Tab-reachable
   regardless. */
import AppIcon from './AppIcon.vue'
import PopoverEngine from './PopoverEngine.vue'
import { periodLabel, type VerticalScale, type WeekRow } from '../lib/periods'

defineProps<{
  life: string
  decade: string
  year: string
  /** Exactly four period keys, Q1..Q4, for the year currently shown. */
  quarters: string[]
  month: string
  /** ISO-week rows, each carrying its own seven day cells (Monday first, §"periods.ts"). */
  weeks: WeekRow[]
  /** Day-scale period key for the "Today" shortcut. */
  today: string
  /** Day-scale period key for the "Tomorrow" shortcut. */
  tomorrow: string
  /** Week-scale period key for the "This week" shortcut. */
  thisWeek: string
}>()

const emit = defineEmits<{
  /** The user picked an assignable target. The caller schedules `periodKey` at `scale`. */
  select: [scale: VerticalScale, periodKey: string]
  /** The user paged a stepper. Purely an intent — this component holds no date state of its
   *  own to update, so nothing renders differently until the caller sends new props back down. */
  navigate: [scale: 'decade' | 'year' | 'month', direction: 'prev' | 'next']
  /** Forwarded from the engine so the caller can put the browsed month back on today for every
   *  fresh open — the view state lives in the store, not here (this component stays stateless). */
  open: []
}>()

const WEEKDAY_LABELS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']

// Selection stays a consumer action. Engine closes locally on the menuitem click and never waits
// for the request started by the caller.
function pick(scale: VerticalScale, periodKey: string) {
  emit('select', scale, periodKey)
}
function step(scale: 'decade' | 'year' | 'month', direction: 'prev' | 'next') {
  emit('navigate', scale, direction)
}

</script>

<template>
  <div class="schedule-popover-anchor">
  <PopoverEngine class="schedule-popover" @open="emit('open')">
    <template #trigger="{ open, toggle }">
      <!-- PopoverEngine decorates an arbitrary target with its marker/focus classes. -->
      <slot name="trigger" :open="open" :toggle="toggle">
        <button
          class="button t-subtitle dropdown__trigger"
          type="button"
          data-cap="schedule"
          aria-haspopup="menu"
          :aria-expanded="open"
        >
          Schedule
        </button>
      </slot>
    </template>

    <div class="schedule-popover__row" data-scale="life">
      <button
        class="dropdown__item"
        role="menuitem"
        type="button"
        data-period-key="life"
        @click="pick('life', 'life')"
      >
        Life
      </button>
    </div>

    <div class="schedule-popover__row schedule-popover__stepper" data-scale="decade">
      <button class="schedule-popover__nav" type="button" aria-label="Previous 3-year window" @click="step('decade', 'prev')"><AppIcon name="chevron-left" :size="14" /></button>
      <button
        class="dropdown__item schedule-popover__stepper-label"
        role="menuitem"
        type="button"
        :data-period-key="decade"
        @click="pick('decade', decade)"
      >
        3 years {{ periodLabel('decade', decade) }}
      </button>
      <button class="schedule-popover__nav" type="button" aria-label="Next 3-year window" @click="step('decade', 'next')"><AppIcon name="chevron-right" :size="14" /></button>
    </div>

    <div class="schedule-popover__row schedule-popover__stepper" data-scale="year">
      <button class="schedule-popover__nav" type="button" aria-label="Previous year" @click="step('year', 'prev')"><AppIcon name="chevron-left" :size="14" /></button>
      <button
        class="dropdown__item schedule-popover__stepper-label"
        role="menuitem"
        type="button"
        :data-period-key="year"
        @click="pick('year', year)"
      >
        {{ periodLabel('year', year) }}
      </button>
      <button
        v-for="q in quarters"
        :key="q"
        class="dropdown__item schedule-popover__quarter"
        role="menuitem"
        type="button"
        data-scale="quarter"
        :data-period-key="q"
        @click="pick('quarter', q)"
      >
        {{ periodLabel('quarter', q) }}
      </button>
      <button class="schedule-popover__nav" type="button" aria-label="Next year" @click="step('year', 'next')"><AppIcon name="chevron-right" :size="14" /></button>
    </div>

    <div class="schedule-popover__row schedule-popover__stepper" data-scale="month">
      <button class="schedule-popover__nav" type="button" aria-label="Previous month" @click="step('month', 'prev')"><AppIcon name="chevron-left" :size="14" /></button>
      <button
        class="dropdown__item schedule-popover__stepper-label"
        role="menuitem"
        type="button"
        :data-period-key="month"
        @click="pick('month', month)"
      >
        {{ periodLabel('month', month) }}
      </button>
      <button class="schedule-popover__nav" type="button" aria-label="Next month" @click="step('month', 'next')"><AppIcon name="chevron-right" :size="14" /></button>
    </div>

    <div class="schedule-popover__weekday">
      <div class="schedule-popover__weekday-col schedule-popover__weekday-col--weeks">
        <p class="schedule-popover__weekday-caption" aria-hidden="true">Weeks</p>
        <div data-scale="week" class="schedule-popover__weeks">
          <button
            v-for="week in weeks"
            :key="week.periodKey"
            class="dropdown__item schedule-popover__week"
            role="menuitem"
            type="button"
            :data-period-key="week.periodKey"
            @click="pick('week', week.periodKey)"
          >
            {{ periodLabel('week', week.periodKey) }}
          </button>
        </div>
      </div>
      <div class="schedule-popover__weekday-col schedule-popover__weekday-col--days">
        <div class="schedule-popover__weekday-caption schedule-popover__weekday-dow" aria-hidden="true">
          <span v-for="label in WEEKDAY_LABELS" :key="label">{{ label }}</span>
        </div>
        <div data-scale="day" class="schedule-popover__days">
          <template v-for="week in weeks" :key="week.periodKey">
            <template v-for="(cell, i) in week.days" :key="week.periodKey + '-' + i">
              <span v-if="cell === null" class="schedule-popover__day schedule-popover__day--blank" aria-hidden="true"></span>
              <button
                v-else
                class="dropdown__item schedule-popover__day"
                :class="{ 'schedule-popover__day--today': cell.isToday }"
                role="menuitem"
                type="button"
                :data-period-key="cell.periodKey"
                :aria-current="cell.isToday ? 'date' : undefined"
                @click="pick('day', cell.periodKey)"
              >
                {{ periodLabel('day', cell.periodKey) }}
              </button>
            </template>
          </template>
        </div>
      </div>
    </div>

    <div class="schedule-popover__row schedule-popover__footer" data-role="schedule-footer">
      <button class="dropdown__item" role="menuitem" type="button" :data-period-key="today" @click="pick('day', today)">
        Today
      </button>
      <button class="dropdown__item" role="menuitem" type="button" :data-period-key="tomorrow" @click="pick('day', tomorrow)">
        Tomorrow
      </button>
      <button class="dropdown__item" role="menuitem" type="button" :data-period-key="thisWeek" @click="pick('week', thisWeek)">
        This week
      </button>
    </div>
  </PopoverEngine>
  </div>
</template>

<style>
/* Global schedule-grid layout only. PopoverEngine owns portal placement, collision size, and
   overflow; no consumer positioning rule remains here. */
.schedule-popover__row {
  display: flex;
  align-items: center;
  padding: var(--space-2) var(--space-2);
}

.schedule-popover__row + .schedule-popover__row,
.schedule-popover__weekday {
  border-top: 0.5px solid var(--color-border);
}

/* Kit `.dropdown__item`s default to `width: 100%` (a vertical menu-list assumption) — wrong here,
   where several items sit side by side on one row. Doubled classes are cascade weight, matching
   GoalCard.vue's own `.goal-card.goal-card` precedent for a deliberate, one-off product-side
   override of a kit default, without depending on stylesheet order. */
.schedule-popover__stepper-label.schedule-popover__stepper-label {
  width: auto;
  flex: 1 1 auto;
  text-align: center;
}

.schedule-popover__quarter.schedule-popover__quarter {
  width: auto;
  flex: 0 0 auto;
}

.schedule-popover__nav {
  flex: 0 0 auto;
  width: var(--space-6);
  height: var(--space-6);
  padding: 0;
  border: 0;
  border-radius: var(--radius-sm);
  background: transparent;
  color: var(--color-text-muted);
  font-size: var(--fs-caption);
  cursor: pointer;
}
.schedule-popover__nav:hover { background: var(--color-surface-overlay); color: var(--color-text); }
.schedule-popover__nav:focus-visible { outline: none; background: var(--color-surface-overlay); }

.schedule-popover__weekday {
  display: flex;
  gap: var(--space-2);
  padding: var(--space-2);
}

.schedule-popover__weekday-col--weeks { flex: 0 0 auto; }
.schedule-popover__weekday-col--days { flex: 1 1 auto; }

.schedule-popover__weekday-caption {
  margin: 0 0 var(--space-1);
  padding: 0 var(--space-2);
  color: var(--color-text-subtle);
  font-size: var(--fs-micro);
  line-height: var(--lh-micro);
}
.schedule-popover__weekday-dow {
  display: grid;
  grid-template-columns: repeat(7, var(--space-8));
  gap: var(--space-1);
  padding: 0;
  text-align: center;
}

.schedule-popover__weeks {
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
}
.schedule-popover__week.schedule-popover__week {
  width: auto;
  height: var(--space-8);
  display: flex;
  align-items: center;
  justify-content: center;
}

.schedule-popover__days {
  display: grid;
  grid-template-columns: repeat(7, var(--space-8));
  grid-auto-rows: var(--space-8);
  gap: var(--space-1);
}
.schedule-popover__day.schedule-popover__day {
  width: var(--space-8);
  height: var(--space-8);
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 0;
  border-radius: var(--radius-full);
}
.schedule-popover__day--blank { pointer-events: none; }
/* Doubled: `.dropdown__item`'s own `border: 0` / `font-weight: var(--fw-regular)` tie this at
   (0,1,0) — measured live, the tie lost and "today" rendered plain until this was doubled. */
.schedule-popover__day--today.schedule-popover__day--today {
  border: 0.5px solid var(--color-border-strong);
  font-weight: var(--fw-bold);
}

.schedule-popover__footer {
  gap: var(--space-1);
}
.schedule-popover__footer .dropdown__item {
  width: auto;
  flex: 1 1 auto;
  text-align: center;
}
</style>
