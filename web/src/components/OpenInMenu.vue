<script setup lang="ts">
/* "Open in ›" in the goal menu's Agent section (docs/design-handoff S5.P5; docs/design/task-sessions.md): every session the task
   has, newest first, each with its agent's own mark and "Claude · 5 min ago", "Codex · 2 days ago". Pointed at, the list opens
   beside the menu as Repeat's does; a pick opens that session where it lives, a Codex thread in the Codex app, a Claude session
   in Terminal. With no session the item is pale, and there is no list. */
import { computed } from 'vue'
import AppIcon from './AppIcon.vue'
import PopoverEngine from './PopoverEngine.vue'
import { agentOf, assetUrl } from '../lib/agentChat'
import { agentName, ago, openSession, sessionsOf, taskSessions, type TaskSession } from '../lib/taskSessions'
import './openInMenu.css'

const props = defineProps<{ id: string }>()
const emit = defineEmits<{ done: [] }>()

const sessions = computed(() => sessionsOf(props.id))
function open(session: TaskSession): void {
  void openSession(session)
  emit('done')
}
</script>

<template>
  <button
    v-if="!sessions.length"
    type="button"
    role="menuitem"
    class="dropdown__item goal-actions__item"
    data-menu-item="open-in"
    title="Start work or Discuss begins a session"
    disabled
  >
    <span>Open in</span><span data-role="submenu-arrow" aria-hidden="true"><AppIcon name="chevron-right" :size="14" /></span>
  </button>
  <PopoverEngine
    v-else
    nested
    :fixed-width="220"
    :offset="[3, -8]"
    data-action="open-in"
    surface-class="goal-actions__submenu session-menu"
    :surface-attrs="{ 'data-role': 'session-menu' }"
  >
    <template #trigger>
      <button type="button" role="menuitem" class="dropdown__item goal-actions__item" data-menu-item="open-in">
        <span>Open in</span><span data-role="submenu-arrow" aria-hidden="true"><AppIcon name="chevron-right" :size="14" /></span>
      </button>
    </template>
    <button
      v-for="session in sessions"
      :key="session.session"
      type="button"
      role="menuitem"
      class="dropdown__item session-menu__item"
      data-role="session-item"
      :data-session="session.session"
      :data-provider="session.provider"
      @click="open(session)"
    >
      <img class="session-menu__mark" :src="assetUrl(agentOf(session.provider).image)" alt="" width="16" height="16">
      <span class="session-menu__text">{{ agentName(session.provider) }}<span class="session-menu__when"> · {{ ago(session.movedAt, taskSessions.now) }}</span></span>
    </button>
  </PopoverEngine>
</template>
