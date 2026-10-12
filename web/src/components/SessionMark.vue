<script setup lang="ts">
/* The end of a task's card says what its sessions are doing (docs/design/task-sessions.md). While one works on the task, the
   field's own turning line, in a small black disc as the circle is; when one went on in Claude or Codex without a word to
   Verticals, that agent's own mark. Nothing in it comes from a model: the gateway sees a file's size and time on disk. The dots
   take the place when the card is pointed at, as they do from the date or the repeat mark. */
import { computed } from 'vue'
import { agentChat, agentOf, assetUrl, currentThread } from '../lib/agentChat'
import { agentName, ago, taskSessions } from '../lib/taskSessions'
import './sessionMark.css'

const props = defineProps<{ goalId: string }>()

const known = computed(() => taskSessions.goals[props.goalId])
/* Verticals' own agent answering in a conversation about this task is known at once, before the gateway's next answer. */
const working = computed(() => !!known.value?.working || (agentChat.running && currentThread.value?.goal?.id === props.goalId))
const outside = computed(() => known.value?.outside ?? null)
const label = computed(() => {
  if (working.value) {
    const who = known.value?.sessions.find((session) => session.working)?.provider ?? currentThread.value?.provider
    return `${agentName(who ?? 'claude')} is working on this`
  }
  return outside.value ? `Continued in ${agentName(outside.value.provider)} · ${ago(outside.value.at, taskSessions.now)}` : ''
})
</script>

<template>
  <span
    v-if="working || outside"
    class="session-mark"
    data-role="session-mark"
    :data-state="working ? 'working' : 'outside'"
    :data-provider="working ? undefined : outside?.provider"
    role="img"
    :aria-label="label"
    :title="label"
  >
    <span v-if="working" class="session-mark__disc">
      <span class="circle-field__pivot is-turning"><span class="circle-field__line"></span></span>
    </span>
    <img v-else class="session-mark__agent" :src="assetUrl(agentOf(outside!.provider).image)" alt="">
  </span>
</template>
