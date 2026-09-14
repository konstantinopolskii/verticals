<script setup lang="ts">
import { computed } from 'vue'
import { KChip } from '@konstantinopolskii/vue'

const props = defineProps<{ tags: string[]; projectTags: string[] }>()
const projectSet = computed(() => new Set(props.projectTags))
</script>

<template>
  <div v-if="tags.length" class="project-tag-chips" data-role="tag-chips">
    <KChip
      v-for="tag in tags"
      :key="tag"
      class="project-tag-chip"
      :class="{ 'project-tag-chip--project': projectSet.has(tag) }"
      :data-tag="tag"
      :data-project="projectSet.has(tag) ? 'true' : 'false'"
      :data-role="projectSet.has(tag) ? 'project-tag-chip' : 'tag-chip'"
    >{{ tag }}</KChip>
  </div>
</template>

<style>
.project-tag-chips {
  display: flex;
  flex-wrap: wrap;
  min-width: 0;
  max-width: 100%;
  gap: var(--space-1);
  margin-top: var(--space-1);
}
.project-tag-chip.project-tag-chip {
  min-width: 0;
  max-width: 100%;
  min-height: var(--space-4);
  padding-inline: var(--space-2);
  overflow-wrap: anywhere;
  color: var(--color-text-muted);
  border-color: var(--color-border);
  font-size: var(--fs-micro);
}
.project-tag-chip--project.project-tag-chip--project {
  color: var(--color-text);
  border-color: var(--color-border-strong);
  background: var(--color-surface-strong);
  font-weight: var(--fw-bold);
}
</style>
