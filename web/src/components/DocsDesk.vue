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

<style>
/* The desk: the window's grey, the board's column head for its title, content 46 px in (as the Inbox). */
.docs-desk { position: relative; box-sizing: border-box; height: 100%; min-width: 0; overflow-y: auto; padding: 0 46px 168px; scroll-padding-top: 96px;
  background: #f5f5f7; color: #000; }
.docs-desk__new { display: grid; place-items: center; width: 28px; height: 28px; margin-top: 6px; border: 0; border-radius: 8px; background: transparent;
  color: rgb(45 48 54 / 45%); cursor: pointer; }
.docs-desk__new:hover { background: rgb(45 48 54 / 7%); color: #000; }
.docs-desk__new-input { box-sizing: border-box; width: 260px; height: 30px; margin-top: 5px; padding: 0 10px; border: 0; border-radius: 8px; background: #fff;
  box-shadow: 0 0 0 .5px rgba(16, 18, 32, .12); font: 400 14px/20px var(--font-body, Commissioner, system-ui, sans-serif); }
.docs-desk__group { padding-top: 34px; }
.desk-head + .docs-desk__group { padding-top: 0; }
.docs-desk__value { display: flex; align-items: center; gap: 9px; margin: 0; font: 500 15px/20px var(--font-body, Commissioner, system-ui, sans-serif); }
.docs-desk__value i { flex: none; width: 14px; height: 14px; border-radius: 3px; }
.docs-desk__value span { color: rgb(45 48 54 / 52%); font-weight: 400; }
/* Stacks on a 196 px pitch: the page centred over a name of two lines at most and a grey line under it. */
.docs-desk__stacks { display: grid; grid-template-columns: repeat(auto-fill, 170px); gap: 28px 26px; margin-top: 20px; }
.docs-stack { display: flex; flex-direction: column; align-items: center; padding: 0; border: 0; background: none; color: inherit; cursor: default;
  text-align: center; font: inherit; transition: opacity 120ms ease; }
.docs-stack--off { opacity: .25; }
.docs-stack__pages { position: relative; display: block; padding-right: 8px; transition: transform 160ms var(--vt-ease-medium); }
.docs-stack:hover .docs-stack__pages, .docs-stack:focus-visible .docs-stack__pages { transform: translateY(-2px) scale(1.03); }
.docs-stack__behind { position: absolute; width: 120px; height: 160px; border-radius: 5px; background: #fff;
  box-shadow: 0 0 0 .5px rgba(16, 18, 32, .08), 0 1px 2px rgba(16, 18, 32, .05); }
.docs-stack__pages > .doc-page { position: relative; }
.docs-stack__name { display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; width: 100%; margin-top: 10px;
  font: 500 13px/17px var(--font-body, Commissioner, system-ui, sans-serif); }
.docs-stack__sub { display: block; margin-top: 2px; font: 400 12px/16px var(--font-body, Commissioner, system-ui, sans-serif); color: rgb(45 48 54 / 52%); }
.docs-stack__sub b { font-weight: 500; color: #000; }
.docs-desk__empty { margin: 32px 0 0; font: 400 15px/22px var(--font-body, Commissioner, system-ui, sans-serif); color: rgb(45 48 54 / 52%); }
/* A stack laid out: the desk steps back behind a veil, the pages over it, six to a line (flow 4, frame f4c). */
.docs-open { position: fixed; inset: var(--titlebar-height, 0px) 0 0; z-index: 250; overflow-y: auto; isolation: isolate; }
.docs-open__veil { position: fixed; inset: var(--titlebar-height, 0px) 0 0; z-index: -1; background: rgba(245, 245, 247, .9);
  -webkit-backdrop-filter: blur(10px); backdrop-filter: blur(10px); }
.docs-open__layer { box-sizing: border-box; min-height: 100%; padding: 120px 70px 168px; }
/* Open: the dim first (150 ms); the pages grow from the stack (300 ms) and fade in from 60 ms. Close: the pages go in
   120 ms, the dim lifts from 80 ms to 240 ms. One curve, the window row's. */
.docs-open-enter-active .docs-open__veil { transition: opacity 150ms var(--vt-ease-large); }
.docs-open-enter-active .docs-open__layer { transition: opacity 240ms var(--vt-ease-large) 60ms, transform 300ms var(--vt-ease-large); }
.docs-open-leave-active .docs-open__layer { transition: opacity 120ms var(--vt-ease-large), transform 120ms var(--vt-ease-large); }
.docs-open-leave-active .docs-open__veil { transition: opacity 160ms var(--vt-ease-large) 80ms; }
.docs-open-enter-from .docs-open__veil, .docs-open-leave-to .docs-open__veil { opacity: 0; }
.docs-open-enter-from .docs-open__layer, .docs-open-leave-to .docs-open__layer { opacity: 0; transform: scale(.95); }
.docs-open__head { display: flex; align-items: baseline; gap: 8px; margin: 0; font: 500 15px/20px var(--font-body, Commissioner, system-ui, sans-serif); }
.docs-open__head span { color: rgb(45 48 54 / 52%); font-weight: 400; }
.docs-open__pages { display: grid; grid-template-columns: repeat(auto-fill, 190px); gap: 32px 24px; margin-top: 26px; }
.docs-open__page { display: flex; flex-direction: column; align-items: center; padding: 0; border: 0; background: none; color: inherit; cursor: default;
  text-align: center; font: inherit; }
.docs-open__page > .doc-page { transition: transform 160ms var(--vt-ease-medium); }
.docs-open__page:hover > .doc-page, .docs-open__page:focus-visible > .doc-page { transform: translateY(-2px) scale(1.03); }
.docs-open__page--off { opacity: .25; }
@media (prefers-reduced-motion: reduce) {
  .docs-open-enter-active .docs-open__layer, .docs-open-leave-active .docs-open__layer { transform: none; transition: opacity 120ms ease; }
  .docs-open-enter-active .docs-open__veil, .docs-open-leave-active .docs-open__veil { transition: opacity 120ms ease; }
  .docs-stack__pages, .docs-open__page > .doc-page { transition: none; }
}
</style>
