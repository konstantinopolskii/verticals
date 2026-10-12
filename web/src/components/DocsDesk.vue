<script setup lang="ts">
/* The Documents desk (Inbox and Documents redesign, rounds 2–7, KK 6–7 Oct 2026; .local-design/inbox-and-docs/round7,
   frame d1): every document as a page, in stacks by the goal it accumulates under, grouped by value in the board's order,
   and first the documents no goal holds, under "No goal" with the board's grey square, one stack for each age (KK,
   7 Oct: "at the beginning"). A click on a stack lays its pages out over the desk; a click on a page opens it as a
   window (S3.P4); Esc puts them back. The field narrows the desk as it narrows the board (S1.P3, frame f4b).

   The stack opens in one movement per step (round 9; .local-design/inbox-and-docs/final, section 3): the desk dims
   first, in 150 ms, so its pages and the stack's never show through each other; the laid-out pages grow from where the
   stack lies, 95 % to 100 % in 300 ms, fading in from 60 ms. Closing, the pages go first (120 ms) and the dim lifts last,
   by 240 ms. The title and × stay at the top while the desk scrolls (DeskHead.vue). */
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import AppIcon from './AppIcon.vue'
import DeskHead from './DeskHead.vue'
import DocPage from './DocPage.vue'
import { store } from '../store'
import { count, desk, docMatches, groups, loadDesk, openStack, shortDay } from '../lib/docsDesk'
import { devPaletteFor, rgbaFromHex } from '../lib/devPalette'
import { goalWashInk } from '../lib/goalColor'
import { openWindow, windows } from '../lib/windows'
import './docsDesk.css'

const data = computed(() => desk.data)

function mark(color: string | null): string {
  if (!color) return '#e5e5e5'
  const box = devPaletteFor(color)?.box
  return box ? rgbaFromHex(box.color, box.opacity) : `rgb(${goalWashInk(color).washRgb})`
}
const behind = (n: number) => (n >= 6 ? 2 : n >= 2 ? 1 : 0)

/* Where the clicked stack lies: the laid-out pages grow from its centre. */
let from = { x: 0, y: 0 }
function openStackAt(key: string, event: Event): void {
  const r = ((event.currentTarget as Element).querySelector('.doc-page') ?? (event.currentTarget as Element)).getBoundingClientRect()
  from = { x: r.left + r.width / 2, y: r.top + r.height / 2 }
  desk.open = key
}
function onOpenEnter(el: Element): void {
  const layer = el.querySelector<HTMLElement>('.docs-open__layer')
  if (!layer) return
  const r = layer.getBoundingClientRect()
  layer.style.transformOrigin = `${from.x - r.left}px ${from.y - r.top}px`
}

function openDoc(id: string, event: Event): void {
  const doc = data.value?.docs[id]
  openWindow({ kind: 'doc', target: id, title: doc?.title || doc?.path || 'Document' }, event.currentTarget as Element)
}
function onKey(event: KeyboardEvent): void {
  if (event.key === 'Escape' && desk.open && !windows.list.length && !event.defaultPrevented) {
    const target = event.target instanceof HTMLElement ? event.target : null
    if (target?.closest('input, textarea, [contenteditable="true"]')) return
    desk.open = null
  }
}

// A new document: its path, folders by "/", committed with ↵ (the tree's own way, kept for the desk).
const creating = ref(false)
const draft = ref('')
const draftInput = ref<HTMLInputElement | null>(null)
function startCreate(): void {
  creating.value = true
  draft.value = ''
  void nextTick(() => draftInput.value?.focus())
}
async function commitCreate(): Promise<void> {
  const path = draft.value.trim()
  if (!path) return
  if (await store.createDoc(path.endsWith('.md') ? path : `${path}.md`)) {
    // The new document opens as a window over the desk, as any page does; the desk shows it in its stack.
    const id = store.state.docs.currentId
    const title = store.state.docs.current?.title || store.state.docs.current?.path || 'Document'
    store.closeDoc()
    creating.value = false
    if (id) openWindow({ kind: 'doc', target: id, title }, draftInput.value)
    void loadDesk()
  }
}

onMounted(() => {
  void loadDesk()
  window.addEventListener('keydown', onKey)
})
onBeforeUnmount(() => {
  window.removeEventListener('keydown', onKey)
  desk.open = null
})
</script>

<template>
  <div class="docs-desk" data-role="docs-desk">
    <DeskHead title="Documents">
      <button type="button" class="docs-desk__new" data-role="docs-new-trigger" aria-label="New document" @click="creating ? (creating = false) : startCreate()">
        <AppIcon name="plus" :size="16" />
      </button>
      <input
        v-if="creating"
        ref="draftInput"
        class="docs-desk__new-input"
        data-role="docs-new-input"
        placeholder="folder/document-name"
        :value="draft"
        @input="draft = ($event.target as HTMLInputElement).value"
        @keydown.enter.prevent="commitCreate"
        @keydown.esc.stop.prevent="creating = false"
        @blur="() => { if (!draft.trim()) creating = false }"
      >
    </DeskHead>
    <section v-for="group in groups" :key="group.key" class="docs-desk__group" :data-group="group.key">
      <h2 class="docs-desk__value"><i :style="{ background: mark(group.color) }" aria-hidden="true"></i>{{ group.name }}<span>{{ group.count }}</span></h2>
      <div class="docs-desk__stacks">
        <button
          v-for="stack in group.stacks"
          :key="stack.key"
          type="button"
          class="docs-stack"
          :class="{ 'docs-stack--off': stack.matches === 0 }"
          :data-stack="stack.key"
          @click="openStackAt(stack.key, $event)"
        >
          <span class="docs-stack__pages" :style="{ paddingTop: `${4 * behind(stack.docs.length)}px` }">
            <i v-for="i in behind(stack.docs.length)" :key="i" class="docs-stack__behind" :style="{ left: `${4 * i}px`, top: `${4 * (behind(stack.docs.length) - i)}px` }"></i>
            <DocPage v-if="data" :doc="data.docs[stack.docs.find(docMatches) ?? stack.docs[0]!]!" :width="120" />
          </span>
          <span class="docs-stack__name">{{ stack.name }}</span>
          <span class="docs-stack__sub"><template v-if="stack.matches !== null"><b>{{ stack.matches }}</b> of {{ stack.docs.length }}</template><template v-else>{{ stack.sub }}</template></span>
        </button>
      </div>
    </section>
    <p v-if="desk.loaded && !groups.length" class="docs-desk__empty">No documents yet. The plus above makes one.</p>

    <Transition name="docs-open" :duration="{ enter: 300, leave: 240 }" @enter="onOpenEnter">
    <div v-if="openStack && data" class="docs-open" data-role="docs-open">
      <div class="docs-open__veil" aria-hidden="true"></div>
      <div class="docs-open__layer" @click.self="desk.open = null">
      <h2 class="docs-open__head" @click.self="desk.open = null">{{ openStack.name }}<span>{{ count(openStack.docs.length) }}</span></h2>
      <div class="docs-open__pages" @click.self="desk.open = null">
        <button
          v-for="id in openStack.docs"
          :key="id"
          type="button"
          class="docs-open__page"
          :class="{ 'docs-open__page--off': !docMatches(id) }"
          :data-doc-id="id"
          @click="openDoc(id, $event)"
        >
          <DocPage :doc="data.docs[id]!" :width="150" />
          <span class="docs-stack__name">{{ data.docs[id]!.title || data.docs[id]!.path }}</span>
          <span class="docs-stack__sub">{{ shortDay(data.docs[id]!.updated_at) }}</span>
        </button>
      </div>
      </div>
    </div>
    </Transition>
  </div>
</template>
