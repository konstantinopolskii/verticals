<script setup lang="ts">
// A document in a window (docs/design-handoff S3.P4): the document as the Docs view draws it, opened at the part the
// answer points to; a link to a deleted one says so in words. Its head is one line (round 2, frame f2b; round 5, m3–m5):
// the facts its page shows on the circle or the desk, its versions, and its title once the title has scrolled away.
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch, watchEffect } from 'vue'
import DocDetail from './DocDetail.vue'
import { ApiError, getDoc, type DocDetail as DocWire } from '../lib/api'
import { windows } from '../lib/windows'
import { waitingPages } from '../lib/waiting'
import { shortDay, stackGoalOf } from '../lib/docsDesk'

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

const win = computed(() => windows.list.find((w) => w.kind === 'doc' && w.target === props.id) ?? null)

/* The facts: a page waiting on the circle says when its rule made it ("Today · made 07:00"); any other document, the
   goal it lies under on the desk and when it was last edited. */
watchEffect(() => {
  const w = win.value
  const d = doc.value
  if (!w || !d) return
  const waiting = waitingPages.value.find((page) => page.docId === d.id)
  const place = waiting ? null : stackGoalOf(d.id)
  w.facts = waiting ? waiting.facts.split(' · ') : [...(place ? [place] : []), `edited ${shortDay(d.updated_at)}`]
  w.versions = d.revision
})

/* The title in the head once the document's own has scrolled out of the window's top. */
let titleWatch: IntersectionObserver | null = null
function watchTitle(): void {
  titleWatch?.disconnect()
  const title = root.value?.querySelector('[data-role="doc-title"]')
  const scroller = root.value?.closest('.vt-window__body')
  if (!title || !scroller || typeof IntersectionObserver === 'undefined') return
  titleWatch = new IntersectionObserver(([entry]) => {
    if (win.value && entry) win.value.titled = !entry.isIntersecting && entry.boundingClientRect.top < (entry.rootBounds?.top ?? 0)
  }, { root: scroller })
  titleWatch.observe(title)
}
watch(doc, () => void nextTick(watchTitle))
onBeforeUnmount(() => titleWatch?.disconnect())

/* A save of this document from this window (or anywhere): the window shows the saved copy, not the one it opened. */
function onEdited(event: Event): void {
  const detail = (event as CustomEvent<{ doc?: DocWire; linksFresh?: boolean }>).detail
  const fresh = detail?.doc
  if (!fresh || fresh.id !== props.id || !doc.value) return
  doc.value = detail.linksFresh ? fresh : { ...fresh, linked_goals: doc.value.linked_goals }
}

onMounted(() => {
  void load()
  window.addEventListener('verticals:doc-edited', onEdited)
})
onBeforeUnmount(() => window.removeEventListener('verticals:doc-edited', onEdited))
watch(() => props.id, load)
watch(() => props.part, () => void nextTick(showPart))
</script>

<template>
  <div ref="root" class="doc-window" data-role="doc-window">
    <DocDetail v-if="doc" :key="doc.id" :doc="doc" in-window />
    <p v-else-if="gone" class="doc-window__note" data-role="doc-gone">This document was deleted</p>
    <p v-else class="doc-window__note">Opening…</p>
  </div>
</template>

<style>
.doc-window { padding: 0 24px 24px; }
.doc-window__note { margin: 0; padding: 24px 0; color: rgb(0 0 0 / 55%); font: 400 16px/24px var(--font-body); }
</style>
