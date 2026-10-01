<script setup lang="ts">
// A document in a window (docs/design-handoff S3.P4): the document as the Docs view draws it, opened at the part the
// answer points to; a link to a deleted one says so in words.
import { nextTick, onMounted, ref, watch } from 'vue'
import DocDetail from './DocDetail.vue'
import { ApiError, getDoc, type DocDetail as DocWire } from '../lib/api'
import { windows } from '../lib/windows'

const props = defineProps<{ id: string; part?: string }>()
const root = ref<HTMLElement | null>(null)
const doc = ref<DocWire | null>(null)
const gone = ref(false)

async function load(): Promise<void> {
  gone.value = false
  try {
    doc.value = await getDoc(props.id)
    const win = windows.list.find((w) => w.kind === 'doc' && w.target === props.id)
    if (win) win.title = doc.value.title || doc.value.path
  } catch (error) {
    doc.value = null
    gone.value = error instanceof ApiError && error.status === 404
  }
  await nextTick()
  showPart()
}

/** The part the answer used: the first heading or line holding its words, scrolled to the window's top. */
function showPart(): void {
  const words = props.part?.trim().toLocaleLowerCase()
  if (!words || !root.value) return
  const found = [...root.value.querySelectorAll<HTMLElement>('h1, h2, h3, h4, p, li, td')]
    .find((el) => el.textContent?.toLocaleLowerCase().includes(words))
  found?.scrollIntoView({ block: 'start' })
}

onMounted(load)
watch(() => props.id, load)
watch(() => props.part, () => void nextTick(showPart))
</script>

<template>
  <div ref="root" class="doc-window" data-role="doc-window">
    <DocDetail v-if="doc" :key="doc.id" :doc="doc" />
    <p v-else-if="gone" class="doc-window__note" data-role="doc-gone">This document was deleted</p>
    <p v-else class="doc-window__note">Opening…</p>
  </div>
</template>

<style>
.doc-window { padding: 0 24px 24px; }
.doc-window__note { margin: 0; padding: 24px 0; color: rgb(0 0 0 / 55%); font: 400 16px/24px var(--font-body); }
</style>
