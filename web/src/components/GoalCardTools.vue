<script setup lang="ts">
import AppIcon from './AppIcon.vue'
import { computed, ref } from 'vue'
import { KChip, KInlineAdd } from '@konstantinopolskii/vue'
import { verticalRank, periodLabel, type VerticalScale } from '../lib/periods'
import { playSound } from '../lib/sound'
import { store } from '../store'
import PopoverEngine from './PopoverEngine.vue'
import RepeatPopover from './RepeatPopover.vue'
import type { RepeatRule } from '../lib/api'

const props = defineProps<{
  id: string
  hasChildren: boolean
  isParent: boolean
  vertical?: string | null
  repeat?: RepeatRule | null
  /** The card is the open goal: its facts line already shows the date, the checkbox completes it and it is open, so
   *  the menu keeps only what the card doesn't show (KK, 27 Sep 2026, the cleaned-up card). */
  open?: boolean
  showIgnore?: boolean
}>()
const emit = defineEmits<{
  details: []
  complete: []
  park: []
  ignore: []
  'ack-due': []
  'ack-done': []
  'open-change': [open: boolean]
}>()

const trigger = ref<HTMLButtonElement | null>(null)
const open = ref(false)
/* The desktop chat (desktop/chat/ui/chat.js) loads after the board, so ask at open whether it is there. It used to put
   its own button on every card's row, over the title (KK, 27 Sep 2026: "shitty"); discussing a goal is one of the
   card's actions, so it lives here. */
const agentChat = ref(false)
function discuss() {
  window.dispatchEvent(new CustomEvent('verticals:discuss-goal', { detail: { id: props.id } }))
  closeMenu()
}
const targets = computed(() => store.reparentTargets(props.id))
const fixedSameVerticalParent = computed(() => store.sameVerticalParentId(props.id))
const grid = computed(() => store.scheduleGrid.value.props)
const scheduledParentVertical = computed(() => store.parentVertical(props.id))
function onOpen() {
  agentChat.value = (window as { __vtChat?: boolean }).__vtChat === true
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

function act(name: 'details' | 'complete' | 'park' | 'ignore' | 'ack-due' | 'ack-done') {
  if (name === 'details') emit('details')
  else if (name === 'complete') emit('complete')
  else if (name === 'park') emit('park')
  else if (name === 'ack-due') emit('ack-due')
  else if (name === 'ack-done') emit('ack-done')
  else emit('ignore')
}

function schedule(scale: VerticalScale, periodKey: string) {
  if (scheduleDisabled(scale)) return
  void store.scheduleGoalQuick(props.id, scale, periodKey)
  closeMenu()
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

/* Tags moved here from the open card's icon row. They are the open goal's, read off its loaded detail. */
const tags = computed(() => (store.state.goalDetail?.id === props.id ? store.state.goalDetail.tags : []))
function addTag(tag: string) {
  if (tags.value.includes(tag)) return
  void store.updateGoal(props.id, { tags: [...tags.value, tag] })
}
function removeTag(tag: string) {
  void store.updateGoal(props.id, { tags: tags.value.filter((t) => t !== tag) })
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
  <!-- One place for the menu (KK, 27 Sep 2026: "it jumps here and there if i click on menu icon"): it hangs below the
       dots, starting at them, as a pull-down menu does on the Mac; it goes above only when there's no room below, and
       ends at the dots only in the last column. "Auto" picked whichever side had the most room, a different one per
       card, and picked again as the card under it moved. -->
  <PopoverEngine
    class="goal-card__tools"
    placement="bottom-start"
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

    <!-- An open card shows its details, completes by its checkbox and offers the agent in its facts line, so those three
         and Reschedule (its date) leave its menu. -->
    <div v-if="!props.open || props.showIgnore" data-menu-section="actions">
      <button
        v-if="!props.open"
        type="button"
        role="menuitem"
        class="dropdown__item goal-actions__item"
        data-menu-item="details"
        @click="act('details')"
      >Details</button>
      <button
        v-if="agentChat && !props.open"
        type="button"
        role="menuitem"
        class="dropdown__item goal-actions__item"
        data-menu-item="discuss"
        @click="discuss"
      >Discuss with agent</button>
      <button
        v-if="props.isParent && !props.open"
        type="button"
        role="menuitem"
        class="dropdown__item goal-actions__item"
        data-menu-item="complete"
        data-cap="complete"
        @click="act('complete')"
      >Complete</button>
      <button
        v-if="props.showIgnore"
        type="button"
        role="menuitem"
        class="dropdown__item goal-actions__item"
        data-menu-item="ignore"
        @click="act('ignore')"
      >Ignore</button>
      <button
        v-if="props.showIgnore"
        type="button"
        role="menuitem"
        class="dropdown__item goal-actions__item"
        data-menu-item="due-ack"
        data-cap="due-ack"
        @click="act('ack-due')"
      >Acknowledge due</button>
      <button
        v-if="props.showIgnore"
        type="button"
        role="menuitem"
        class="dropdown__item goal-actions__item"
        data-menu-item="due-done"
        @click="act('ack-done')"
      >Was done on time</button>
    </div>

    <hr v-if="!props.open || props.showIgnore">

    <div
      class="goal-actions__legacy-content"
      data-role="goal-actions-menu"
      data-popover-surface
    >
    <!-- The colour swatch row left with D231 (KK, 2026-08-15): colour is derived from the value
         root everywhere the product renders it, so a per-card picker was a control whose effect
         nothing could see. Value colours are set over HTTP/MCP on the value root itself. -->
    <PopoverEngine
      v-if="!fixedSameVerticalParent && !props.open"
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

    <!-- The three ways to move a goal sit together. "Collapse" left: it changed nothing on screen. -->
    <button
      v-if="vertical"
      type="button"
      role="menuitem"
      class="dropdown__item goal-actions__item"
      data-menu-item="park"
      data-cap="park"
      @click="act('park')"
    >Remove from vertical</button>

    <hr>

    <PopoverEngine
      v-if="props.open"
      nested
      data-action="tags"
      surface-class="goal-actions__submenu goal-actions__tags"
      :surface-attrs="{ 'data-role': 'tag-chips' }"
    >
      <template #trigger>
        <button type="button" role="menuitem" class="dropdown__item goal-actions__item">
          <span>Tags…</span>
          <span data-role="submenu-arrow" aria-hidden="true"><AppIcon name="chevron-right" :size="14" /></span>
        </button>
      </template>
      <div class="goal-actions__tags-panel">
        <div v-if="tags.length" class="chip-wrap">
          <KChip
            v-for="tag in tags"
            :key="tag"
            data-cap="set-tags"
            :aria-label="`Remove ${tag}`"
            @click="removeTag(tag)"
          >{{ tag }} <AppIcon name="x" :size="12" /></KChip>
        </div>
        <KInlineAdd data-cap="set-tags" placeholder="Add tag…" @add="addTag" />
      </div>
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
  /* The dots end 14 px from the colour's right edge, as the checkbox starts 14 px from its left (KK, 27 Sep 2026: the
     right padding was too small). The row ends 6 px inside the card and the dots 3 px inside this button. */
  right: 5px;
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
  background: rgba(0, 0, 0, .08);
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
  background-color: rgba(0, 0, 0, .05);
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
/* One text edge (KK, 27 Sep 2026, the cleaned-up card's menu): words only, so every item starts on one line; the arrow
   that opens a submenu stays at the right. */
.goal-actions__menu .goal-actions__item > svg,
.goal-actions__menu .goal-actions__item > [data-role="icon-spacer"] { display: none; }
.goal-actions__item.goal-actions__item--why { flex-direction: column; align-items: flex-start; gap: 0; }
.goal-actions__why { font-size: 12px; line-height: 16px; }
.goal-actions__tags-panel { display: flex; flex-direction: column; gap: var(--space-2); padding: var(--space-2); min-width: 180px; }
/* An open card shows its dots all the time: they are the way to its rarer actions. */
.goal-card--detail-open > .goal-card__row .goal-actions__trigger { opacity: 1; }
.goal-actions__item--danger { color: #c93a5b; }
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
/* The submenu's full-width item rule caught the arrows too: each "‹" took the whole row and pushed the year or month
   and its "›" out of sight (KK's Reschedule screenshot, 27 Sep 2026). The arrows keep their own size; the label between
   them is centred. */
.goal-actions__submenu.goal-actions__submenu .goal-actions__nav {
  width: auto;
  padding: 4px 10px;
  justify-content: center;
}
.goal-actions__submenu.goal-actions__submenu .goal-actions__stepper > .dropdown__item { justify-content: center; }
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
