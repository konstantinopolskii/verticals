<script setup lang="ts">
import AppIcon from './AppIcon.vue'
import { computed, ref } from 'vue'
import { verticalRank, periodLabel, type VerticalScale } from '../lib/periods'
import { playSound } from '../lib/sound'
import { store } from '../store'
import PopoverEngine from './PopoverEngine.vue'
import RepeatPopover from './RepeatPopover.vue'
import type { RepeatRule } from '../lib/api'
import { CARRYOVER_ACTIONS, resolveCarryover, type CarryoverAction } from '../lib/carryover'

const props = defineProps<{
  id: string
  hasChildren: boolean
  isParent: boolean
  vertical?: string | null
  repeat?: RepeatRule | null
  foil?: boolean
  showIgnore?: boolean
  ghostUntil?: string | null
}>()
const emit = defineEmits<{
  details: []
  complete: []
  foil: []
  park: []
  'open-change': [open: boolean]
}>()

const trigger = ref<HTMLButtonElement | null>(null)
const open = ref(false)
const collapsed = computed(() => store.isCollapsed(props.id))
const targets = computed(() => store.reparentTargets(props.id))
const fixedSameVerticalParent = computed(() => store.sameVerticalParentId(props.id))
const grid = computed(() => store.scheduleGrid.value.props)
const scheduledParentVertical = computed(() => store.parentVertical(props.id))
function onOpen() {
  open.value = true
  emit('open-change', true)
}

function onClose() {
  open.value = false
  emit('open-change', false)
}

function openMenu() {
  if (!open.value) trigger.value?.click()
}

function closeMenu() {
  if (open.value) trigger.value?.click()
}

function act(name: 'details' | 'complete' | 'foil' | 'park') {
  if (name === 'details') emit('details')
  else if (name === 'complete') emit('complete')
  else if (name === 'foil') emit('foil')
  else if (name === 'park') emit('park')
}

function schedule(scale: VerticalScale, periodKey: string) {
  if (scheduleDisabled(scale)) return
  void store.scheduleGoalQuick(props.id, scale, periodKey)
  closeMenu()
}

function resolveCarriedOver(action: CarryoverAction) {
  void resolveCarryover(props, action)
}

function scheduleDisabled(scale: VerticalScale): boolean {
  const parent = scheduledParentVertical.value
  return parent !== undefined && verticalRank(scale) > verticalRank(parent)
}

function scheduleDisabledAttrs(scale: VerticalScale): Record<string, string | boolean> {
  return scheduleDisabled(scale)
    ? { disabled: true, 'data-disabled': 'true', 'aria-disabled': 'true' }
    : {}
}

function moveToInbox() {
  void store.moveGoalToInbox(props.id)
}

function toggleChildren() {
  playSound(collapsed.value ? 'vertical_expanded' : 'vertical_collapsed')
  store.toggleCollapsed(props.id)
}

function reparent(parentId: string | null) {
  void store.reparentQuick(props.id, parentId)
  closeMenu()
}

function remove() {
  playSound('goal_deleted')
  void store.removeGoal(props.id)
}

defineExpose({ openMenu })
</script>

<template>
  <PopoverEngine
    class="goal-card__tools"
    surface-class="goal-actions__menu"
    :surface-attrs="{ 'data-role': 'goal-context-menu' }"
    @open="onOpen"
    @close="onClose"
  >
    <template #trigger="{ open: engineOpen }">
      <button
        ref="trigger"
        type="button"
        class="goal-actions__trigger"
        data-role="goal-actions-trigger"
        data-cap="reparent"
        aria-label="Goal actions"
        aria-haspopup="menu"
        :aria-expanded="engineOpen"
      >
        <AppIcon name="dots" data-cap="delete" :size="24" />
      </button>
    </template>

    <template v-if="props.showIgnore">
      <div data-menu-section="carryover">
        <button
          v-for="option in CARRYOVER_ACTIONS.filter(item => item.action !== 'done')"
          :key="option.action"
          type="button"
          role="menuitem"
          class="dropdown__item goal-actions__item"
          :data-menu-item="`carryover-${option.action}`"
          :data-carryover-action="option.action"
          :data-cap="option.action === 'missed' ? 'due-ack' : undefined"
          :title="option.action === 'keep' && vertical ? `Keep in the current ${vertical}` : undefined"
          @click="resolveCarriedOver(option.action)"
        >{{ option.label }}</button>
      </div>
      <hr>
    </template>

    <div data-menu-section="actions">
      <button
        type="button"
        role="menuitem"
        class="dropdown__item goal-actions__item"
        data-menu-item="details"
        @click="act('details')"
      >Details</button>
      <button
        v-if="props.isParent && !props.showIgnore"
        type="button"
        role="menuitem"
        class="dropdown__item goal-actions__item"
        data-menu-item="complete"
        data-cap="complete"
        @click="act('complete')"
      >Complete</button>
      <button
        type="button"
        role="menuitem"
        class="dropdown__item goal-actions__item"
        data-menu-item="foil"
        data-cap="foil"
        :aria-pressed="props.foil"
        @click="act('foil')"
      >Foil</button>
      <button
        v-if="vertical"
        type="button"
        role="menuitem"
        class="dropdown__item goal-actions__item"
        data-menu-item="park"
        data-cap="park"
        @click="act('park')"
      >Remove from vertical</button>
    </div>

    <hr>

    <div
      class="goal-actions__legacy-content"
      data-role="goal-actions-menu"
      data-popover-surface
    >
    <!-- The colour swatch row left with D231 (KK, 2026-08-15): colour is derived from the value
         root everywhere the product renders it, so a per-card picker was a control whose effect
         nothing could see. Value colours are set over HTTP/MCP on the value root itself. -->
    <PopoverEngine
      v-if="!fixedSameVerticalParent"
      nested
      data-action="schedule"
      surface-class="goal-actions__submenu goal-actions__schedule"
      :surface-attrs="{ 'data-role': 'goal-actions-schedule' }"
      @open="store.resetScheduleView()"
    >
      <template #trigger>
        <button
          type="button"
          role="menuitem"
          class="dropdown__item goal-actions__item"
          data-cap="schedule"
        >
          <AppIcon name="calendar" data-icon="calendar" />
          <span>{{ vertical ? 'Reschedule' : 'Schedule' }}</span>
          <span data-role="submenu-arrow" aria-hidden="true"><AppIcon name="chevron-right" :size="14" /></span>
        </button>
      </template>

      <!-- The decade/year/month rows carry the same ‹/› steppers the detail popover has. Without
           them this surface could only ever offer the CURRENT decade, year and month: scheduling
           anything further out was unreachable from a card, and the calendar read as half-broken
           (owner, 2026-08-10). `store.navigateSchedule` is shared state, so both surfaces page
           together and `resetScheduleView` on open puts every fresh open back on today. -->
      <div data-scale="life"><button v-bind="scheduleDisabledAttrs('life')" class="dropdown__item" role="menuitem" type="button" data-period-key="life" @click="schedule('life', 'life')">Life</button></div>
      <div data-scale="decade" class="goal-actions__stepper">
        <button class="goal-actions__nav" type="button" aria-label="Previous 3-year window" @click.stop="store.navigateSchedule('decade', 'prev')"><AppIcon name="chevron-left" :size="14" /></button>
        <button v-bind="scheduleDisabledAttrs('decade')" class="dropdown__item" role="menuitem" type="button" :data-period-key="grid.decade" @click="schedule('decade', grid.decade)">{{ periodLabel('decade', grid.decade) }}</button>
        <button class="goal-actions__nav" type="button" aria-label="Next 3-year window" @click.stop="store.navigateSchedule('decade', 'next')"><AppIcon name="chevron-right" :size="14" /></button>
      </div>
      <div data-scale="year" class="goal-actions__stepper">
        <button class="goal-actions__nav" type="button" aria-label="Previous year" @click.stop="store.navigateSchedule('year', 'prev')"><AppIcon name="chevron-left" :size="14" /></button>
        <button v-bind="scheduleDisabledAttrs('year')" class="dropdown__item" role="menuitem" type="button" :data-period-key="grid.year" @click="schedule('year', grid.year)">{{ periodLabel('year', grid.year) }}</button>
        <button class="goal-actions__nav" type="button" aria-label="Next year" @click.stop="store.navigateSchedule('year', 'next')"><AppIcon name="chevron-right" :size="14" /></button>
      </div>
      <div data-scale="quarter"><button v-for="period in grid.quarters" :key="period" v-bind="scheduleDisabledAttrs('quarter')" class="dropdown__item" role="menuitem" type="button" :data-period-key="period" @click="schedule('quarter', period)">{{ periodLabel('quarter', period) }}</button></div>
      <div data-scale="month" class="goal-actions__stepper">
        <button class="goal-actions__nav" type="button" aria-label="Previous month" @click.stop="store.navigateSchedule('month', 'prev')"><AppIcon name="chevron-left" :size="14" /></button>
        <button v-bind="scheduleDisabledAttrs('month')" class="dropdown__item" role="menuitem" type="button" :data-period-key="grid.month" @click="schedule('month', grid.month)">{{ periodLabel('month', grid.month) }}</button>
        <button class="goal-actions__nav" type="button" aria-label="Next month" @click.stop="store.navigateSchedule('month', 'next')"><AppIcon name="chevron-right" :size="14" /></button>
      </div>
      <div data-scale="week"><button v-for="week in grid.weeks" :key="week.periodKey" v-bind="scheduleDisabledAttrs('week')" class="dropdown__item" role="menuitem" type="button" :data-period-key="week.periodKey" @click="schedule('week', week.periodKey)">{{ periodLabel('week', week.periodKey) }}</button></div>
      <div data-scale="day" class="goal-actions__days">
        <template v-for="week in grid.weeks" :key="week.periodKey">
          <button v-for="day in week.days.filter(Boolean)" :key="day?.periodKey" v-bind="scheduleDisabledAttrs('day')" class="dropdown__item" role="menuitem" type="button" :data-period-key="day?.periodKey" @click="schedule('day', day?.periodKey ?? '')">{{ periodLabel('day', day?.periodKey ?? '') }}</button>
        </template>
      </div>
      <!-- The same three shortcuts the detail popover ends with; a card had none of them, so the
           commonest action there is ("do this tomorrow") took a hunt through the day grid. -->
      <div data-role="schedule-footer" class="goal-actions__schedule-footer">
        <button v-bind="scheduleDisabledAttrs('day')" class="dropdown__item" role="menuitem" type="button" :data-period-key="grid.today" @click="schedule('day', grid.today)">Today</button>
        <button v-bind="scheduleDisabledAttrs('day')" class="dropdown__item" role="menuitem" type="button" :data-period-key="grid.tomorrow" @click="schedule('day', grid.tomorrow)">Tomorrow</button>
        <button v-bind="scheduleDisabledAttrs('week')" class="dropdown__item" role="menuitem" type="button" :data-period-key="grid.thisWeek" @click="schedule('week', grid.thisWeek)">This week</button>
      </div>
    </PopoverEngine>

    <button
      v-if="vertical && !fixedSameVerticalParent"
      type="button"
      role="menuitem"
      class="dropdown__item goal-actions__item"
      data-action="inbox"
      @click="moveToInbox"
    >
      <span data-role="icon-spacer" aria-hidden="true" />
      <span>Move to Inbox</span>
    </button>

    <button
      v-if="hasChildren"
      type="button"
      role="menuitem"
      class="dropdown__item goal-actions__item"
      data-action="expand"
      :data-sound-event="collapsed ? 'vertical_expanded' : 'vertical_collapsed'"
      @click="toggleChildren"
    >
      <AppIcon :name="collapsed ? 'chevron-right' : 'chevron-down'" data-icon="chevron" />
      <span>{{ collapsed ? 'Expand' : 'Collapse' }}</span>
    </button>

    <PopoverEngine
      v-if="!fixedSameVerticalParent"
      nested
      data-action="reparent"
      surface-class="goal-actions__submenu"
      :surface-attrs="{ 'data-role': 'goal-actions-reparent' }"
    >
      <template #trigger>
        <button
          type="button"
          role="menuitem"
          class="dropdown__item goal-actions__item"
        >
          <AppIcon name="hierarchy" data-icon="hierarchy" />
          <span>Move to…</span>
          <span data-role="submenu-arrow" aria-hidden="true"><AppIcon name="chevron-right" :size="14" /></span>
        </button>
      </template>

      <button v-if="!fixedSameVerticalParent" class="dropdown__item" role="menuitem" type="button" data-parent-id="" @click="reparent(null)">No parent</button>
      <button v-for="target in targets" :key="target.id" class="dropdown__item" role="menuitem" type="button" :data-parent-id="target.id" @click="reparent(target.id)">{{ target.title }}</button>
    </PopoverEngine>

    <RepeatPopover
      v-if="vertical && vertical !== 'life'"
      :id="id"
      :vertical="vertical"
      :repeat="repeat ?? null"
      :has-children="hasChildren"
    />

    <hr>

    <button
      type="button"
      role="menuitem"
      class="dropdown__item goal-actions__item goal-actions__item--danger"
      data-action="delete"
      data-cap="delete"
      @click="remove"
    >
      <AppIcon name="trash" data-icon="trash" />
      <span>Delete</span>
    </button>
    </div>
  </PopoverEngine>
</template>

<style>
.goal-card > .goal-card__row .goal-card__tools {
  position: absolute;
  top: 0;
  right: 0;
  display: block;
  width: 24px;
  height: 24px;
  opacity: 1;
  transition: opacity var(--motion-hover) cubic-bezier(.165, .84, .44, 1);
}
.goal-card:hover > .goal-card__row .goal-card__tools,
.goal-card--menu-open > .goal-card__row .goal-card__tools,
.goal-card--landed-hover > .goal-card__row .goal-card__tools,
.goal-card__tools:focus-within { transition: none; }
.goal-actions__trigger {
  position: absolute;
  z-index: 2;
  top: -1px;
  right: 0;
  display: grid;
  place-items: center;
  width: 24px;
  height: 24px;
  padding: 0;
  border: 0;
  border-radius: 50%;
  background: transparent;
  color: currentColor;
  cursor: pointer;
  opacity: 0;
  user-select: none;
  -webkit-touch-callout: none;
  transition: opacity var(--motion-hover) cubic-bezier(.165, .84, .44, 1);
}
.goal-actions__trigger svg { display: block; fill: currentColor; }
.goal-actions__trigger:focus { outline: none; }
.goal-card:hover > .goal-card__row .goal-actions__trigger,
.goal-card--menu-open > .goal-card__row .goal-actions__trigger,
.goal-card--landed-hover > .goal-card__row .goal-actions__trigger,
.goal-actions__trigger:focus-visible {
  opacity: 1;
  transition: none;
}

.goal-actions__menu > hr,
.goal-actions__legacy-content > hr {
  height: 1px;
  margin: 8px 0;
  border: 0;
  background: rgba(255, 255, 255, .14);
}
.goal-actions__legacy-content {
  display: flex;
  flex-direction: column;
}
.goal-actions__item.goal-actions__item,
.goal-actions__submenu.goal-actions__submenu button {
  box-sizing: border-box;
  display: flex;
  align-items: center;
  width: 100%;
  gap: 8px;
  padding: 4px 14px;
  border: 0;
  background: transparent;
  color: inherit;
  font: inherit;
  font-size: 14px;
  line-height: 24px;
  text-align: left;
  cursor: pointer;
}
.goal-actions__item:hover,
.goal-actions__item:focus,
.goal-actions__submenu button:hover,
.goal-actions__submenu button:focus {
  outline: none;
  background-color: rgba(255, 255, 255, .12);
}
.goal-actions__item[aria-disabled="true"],
.goal-actions__schedule button[aria-disabled="true"] { cursor: default; opacity: .5; }
.goal-actions__item > svg,
.goal-actions__item > [data-role="icon-spacer"] {
  width: 24px;
  height: 24px;
  flex: 0 0 24px;
}
.goal-actions__item > svg { fill: none; stroke: currentColor; stroke-width: 2.2; }
.goal-actions__item > [data-role="submenu-arrow"] { margin-left: auto; }
.goal-actions__item--danger { color: rgb(255, 130, 130); }
.goal-actions__submenu > div { display: flex; }
.goal-actions__submenu > div > button { white-space: nowrap; }
.goal-actions__days { display: grid !important; grid-template-columns: repeat(7, 1fr); }
/* Stepper rows: the pager arrows flank a label that stays a full-width menu item, so the row
   reads as one line rather than three buttons. Mirrors SchedulePopover's own stepper shape. */
.goal-actions__stepper {
  display: flex;
  align-items: center;
}
.goal-actions__stepper > .dropdown__item {
  flex: 1 1 auto;
  text-align: center;
}
.goal-actions__nav {
  flex: 0 0 auto;
  padding: 0 var(--space-2);
  border: 0;
  background: none;
  color: inherit;
  line-height: 1;
  cursor: pointer;
}
.goal-actions__schedule-footer {
  display: flex;
  gap: var(--space-1);
  border-top: 0.5px solid var(--color-border);
}
.goal-actions__schedule-footer > .dropdown__item {
  flex: 1 1 0;
  text-align: center;
}
.goal-actions__days button { justify-content: center; padding-inline: 6px; }
</style>
