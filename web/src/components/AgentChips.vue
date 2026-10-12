<script setup lang="ts">
// What an agent's message made or changed, one chip under another in the order the message links them
// (docs/design/agent-chips.md): a document by its first page, a goal by its square. The agent's balloon and the field's
// answer draw the same list, on the same black.
import DocChip from './DocChip.vue'
import GoalChip from './GoalChip.vue'
import type { ChipLink } from '../lib/chipLinks'
import './agentChips.css'

defineProps<{ links: ChipLink[] }>()
</script>

<template>
  <div class="agent-chips" data-role="agent-chips">
    <template v-for="link in links" :key="`${link.kind}:${link.id}`">
      <DocChip v-if="link.kind === 'doc'" :id="link.id" :label="link.label" dark />
      <GoalChip v-else :id="link.id" :label="link.label" />
    </template>
  </div>
</template>
