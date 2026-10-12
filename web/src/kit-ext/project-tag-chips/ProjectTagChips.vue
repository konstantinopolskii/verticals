<script setup lang="ts">
import { computed } from 'vue'
import { KChip } from '@konstantinopolskii/vue'
import './projectTagChips.css'

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
