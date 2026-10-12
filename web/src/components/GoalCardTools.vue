<script setup lang="ts">
import AppIcon from './AppIcon.vue'
import { computed, ref } from 'vue'
import { KChip, KInlineAdd } from '@konstantinopolskii/vue'
import type { VerticalScale } from '../lib/periods'
import { isoDate, localDate, periodKeyFor } from '../lib/schedule'
import { playSound } from '../lib/sound'
import { store, todayIso } from '../store'
import { agentChat as agentChatState } from '../lib/agentChat'
import PopoverEngine from './PopoverEngine.vue'
import RepeatPopover from './RepeatPopover.vue'
import OpenInMenu from './OpenInMenu.vue'
import MoveStep, { type MoveStepName } from './MoveStep.vue'
import type { RepeatRule } from '../lib/api'
import './goalCardTools.css'

const props = defineProps<{
  id: string
  vertical?: string | null
  repeat?: RepeatRule | null
  /** The card is the open goal: its facts line already shows the date, the checkbox completes it and it is open, so
   *  the menu keeps only what the card doesn't show (KK, 27 Sep 2026, the cleaned-up card). */
  open?: boolean
}>()
const emit = defineEmits<{
  'open-change': [open: boolean]
}>()

const trigger = ref<HTMLButtonElement | null>(null)
const open = ref(false)
/* The Agent section: Discuss, Start work and Open in, only where an agent exists (docs/design-handoff S2.P1.023;
   docs/design/goal-menu.md, docs/design/task-sessions.md). The open card's facts line offers Discuss already, so that card's
   section holds the other two. */
const showAgent = computed(() => agentChatState.available)
function discuss() {
  window.dispatchEvent(new CustomEvent('verticals:discuss-goal', { detail: { id: props.id } }))
  closeMenu()
}
function startWork() {
  window.dispatchEvent(new CustomEvent('verticals:start-work', { detail: { id: props.id } }))
  closeMenu()
}
const fixedSameVerticalParent = computed(() => store.sameVerticalParentId(props.id))
const repeatVertical = computed(() => (props.vertical && props.vertical !== 'life' ? props.vertical : null))
/* A goal nested under a parent of its own vertical has no dates or parent of its own to change here (D179), so only its
   Repeat stays, under Reschedule, and the Move group is left out. */
const showReschedule = computed(() => !fixedSameVerticalParent.value || repeatVertical.value !== null)
function onOpen() {
  open.value = true
  emit('open-change', true)
}

function onClose() {
  open.value = false
  step.value = null
  emit('open-change', false)
}

function openMenu() {
  if (!open.value) trigger.value?.click()
}

function closeMenu() {
  if (open.value) trigger.value?.click()
}

/* Tomorrow and Next week move the goal at once; Date and Into a goal open a step in place (S5.P5.003, .008). */
const step = ref<MoveStepName | null>(null)
function day(offset: number): Date {
  const t = localDate(todayIso())
  return new Date(t.getFullYear(), t.getMonth(), t.getDate() + offset)
}
const tomorrow = computed(() => day(1))
const nextWeek = computed(() => { const t = day(0); return day(7 - ((t.getDay() + 6) % 7)) })
function moveToInbox() {
  void store.moveGoalToInbox(props.id)
  closeMenu()
}
function moveTo(scale: VerticalScale, date: Date) {
  void store.scheduleGoalQuick(props.id, scale, periodKeyFor(scale, date), isoDate(date))
  closeMenu()
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

    <!-- A step (Date and its levels, Into a goal) takes the menu's place, with ‹ back (docs/design-handoff S5.P5.008, .039).
         Otherwise the menu groups its actions by what they change: the agent's work, when, where, and the goal itself,
         each group under a small grey word and a line from the one before (docs/design/goal-menu.md). A goal completes by
         its box and comments live in documents, so neither is here. -->
    <MoveStep v-if="step" :id="id" :step="step" @go="(next) => step = next" @done="closeMenu" />
    <div v-else class="goal-actions__content" data-role="goal-actions-menu">
      <div v-if="showAgent" class="goal-actions__section" data-menu-section="agent" role="group" aria-label="Agent">
        <p class="goal-actions__heading" aria-hidden="true">Agent</p>
        <button
          v-if="!props.open"
          type="button"
          role="menuitem"
          class="dropdown__item goal-actions__item"
          data-menu-item="discuss"
          @click="discuss"
        >Discuss</button>
        <button
          type="button"
          role="menuitem"
          class="dropdown__item goal-actions__item"
          data-menu-item="start-work"
          @click="startWork"
        >Start work</button>
        <OpenInMenu :id="id" @done="closeMenu" />
      </div>

      <div v-if="showReschedule" class="goal-actions__section" data-menu-section="reschedule" role="group" aria-label="Reschedule">
        <p class="goal-actions__heading" aria-hidden="true">Reschedule</p>
        <template v-if="!fixedSameVerticalParent">
          <button type="button" role="menuitem" class="dropdown__item goal-actions__item" data-move="tomorrow" data-cap="schedule"
            @click="moveTo('day', tomorrow)">Tomorrow</button>
          <button type="button" role="menuitem" class="dropdown__item goal-actions__item" data-move="next-week"
            @click="moveTo('week', nextWeek)">Next week</button>
          <button type="button" role="menuitem" class="dropdown__item goal-actions__item" data-move="date" @click.stop="step = 'date'">
            <span>Date</span><span data-role="submenu-arrow" aria-hidden="true"><AppIcon name="chevron-right" :size="14" /></span>
          </button>
        </template>
        <RepeatPopover
          v-if="repeatVertical"
          :id="id"
          :vertical="repeatVertical"
          :repeat="repeat ?? null"
        />
      </div>

      <div v-if="!fixedSameVerticalParent" class="goal-actions__section" data-menu-section="move" role="group" aria-label="Move">
        <p class="goal-actions__heading" aria-hidden="true">Move</p>
        <button type="button" role="menuitem" class="dropdown__item goal-actions__item" data-move="under" @click.stop="step = 'under'">
          <span>Into a goal</span><span data-role="submenu-arrow" aria-hidden="true"><AppIcon name="chevron-right" :size="14" /></span>
        </button>
        <button
          v-if="vertical"
          type="button"
          role="menuitem"
          class="dropdown__item goal-actions__item"
          data-move="inbox"
          data-action="inbox"
          @click="moveToInbox"
        >To Inbox</button>
      </div>

      <div v-if="props.open" class="goal-actions__section" data-menu-section="tags">
        <PopoverEngine
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
      </div>

      <div class="goal-actions__section" data-menu-section="delete">
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
    </div>
  </PopoverEngine>
</template>
