<script setup lang="ts">
// A web page in a window (docs/design-handoff S3.P4): framed only when the server found that it can be; otherwise the
// window says so and offers Chrome. A link clicked inside the page leaves for the browser (Verticals.swift).
import { onMounted, ref, watch } from 'vue'
import AppIcon from './AppIcon.vue'
import { framable } from '../lib/pages'

const props = defineProps<{ url: string }>()
const state = ref<'checking' | 'framed' | 'refused'>('checking')

async function check(): Promise<void> {
  state.value = 'checking'
  state.value = (await framable(props.url)) ? 'framed' : 'refused'
}
onMounted(check)
watch(() => props.url, check)
</script>

<template>
  <div class="page-window" :data-state="state" data-role="page-window">
    <iframe v-if="state === 'framed'" class="page-window__frame" :src="url" title="Web page" referrerpolicy="no-referrer"></iframe>
    <div v-else-if="state === 'refused'" class="page-window__refused" data-role="page-refused">
      <p>This page can't open here</p>
      <a :href="url" target="_blank" rel="noreferrer" data-role="open-in-chrome">Open in Chrome <AppIcon name="arrow-up-right" :size="16" /></a>
    </div>
    <p v-else class="page-window__checking">Opening…</p>
  </div>
</template>

<style>
.page-window { height: min(686px, calc(80vh - 52px)); }
.page-window__frame { display: block; width: 100%; height: 100%; border: 0; background: #fff; }
.page-window__refused, .page-window__checking { display: flex; flex-direction: column; align-items: flex-start; gap: 8px;
  margin: 0; padding: 24px; color: rgb(0 0 0 / 55%); font: 400 16px/24px var(--font-body); }
.page-window__refused p { margin: 0; color: #000; }
.page-window__refused a { display: inline-flex; align-items: center; gap: 2px; color: #000; font-weight: 500; }
</style>
