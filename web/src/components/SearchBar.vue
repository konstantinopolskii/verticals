<script setup lang="ts">
import AppIcon from './AppIcon.vue'
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { KCheckbox } from '@konstantinopolskii/vue'
import { type GoalCard } from '../lib/api'
import { store, todayIso } from '../store'
import { stateUrl } from '../lib/urlState'

const props = defineProps<{ agentAvailable: boolean }>()
const SEARCH_DEBOUNCE_MS = 300
const SEARCH_PATH_RE = /^\/search(?:\/(.*))?\/?$/
const inputValue = ref('')
const surfaceOpen = ref(false)
const pending = ref(false)
const activeIndex = ref(0)
const preSearchPath = ref('/')
const root = ref<HTMLElement | null>(null)
const input = ref<HTMLInputElement | null>(null)
let debounceTimer: number | undefined
let searchVersion = 0
let searchChain = Promise.resolve()
let skipNextFocusOpen = false

const query = computed(() => inputValue.value.trim())
const recognizedTag = computed(() => /^#(\S+)/.exec(query.value)?.[1] ?? null)
const values = computed(() => (store.state.board?.values ?? []).map(value => ({
  ...value,
  label: store.state.board?.short_labels?.[value.id] ?? value.title.split(/\s+/)[0] ?? value.title,
})))
const activeArea = computed(() => values.value.find(value => value.id === store.state.valueFilter))

interface SearchOption {
  key: string
  kind: 'area' | 'tag' | 'goal' | 'ask'
  label: string
  meta: string
  id?: string
  goal?: GoalCard
}
const options = computed<SearchOption[]>(() => {
  const rows: SearchOption[] = []
  if (!recognizedTag.value) {
    for (const value of values.value) {
      if (!query.value || value.label.toLocaleLowerCase().includes(query.value.toLocaleLowerCase())) {
        rows.push({ key: `area-${value.id}`, kind: 'area', label: value.label, meta: 'Filter area', id: value.id })
      }
    }
  }
  if (recognizedTag.value && store.state.searchTag !== recognizedTag.value) {
    rows.push({ key: 'tag', kind: 'tag', label: `#${recognizedTag.value}`, meta: 'Filter tag' })
  }
  const resultsMatchInput = recognizedTag.value
    ? store.state.searchTag === recognizedTag.value
    : (!query.value || (query.value.length >= 3 && store.state.searchQuery.trim() === query.value))
  if (!pending.value && resultsMatchInput) {
    for (const goal of store.state.searchResults) {
      rows.push({ key: `goal-${goal.id}`, kind: 'goal', label: goal.title, id: goal.id, goal,
        meta: goal.vertical && goal.anchor_date ? `${goal.vertical} · ${goal.anchor_date}` : 'Inbox' })
    }
  }
  if (query.value) {
    rows.push({ key: 'ask', kind: 'ask', label: `Ask agent: ${query.value}`,
      meta: props.agentAvailable ? 'Opens a draft' : 'Agent unavailable in this browser' })
  }
  return rows
})
const noMatches = computed(() => !pending.value && (query.value.length >= 3 || store.state.searchTag !== null)
  && !options.value.some(option => option.kind !== 'ask'))

function clearTimer() {
  if (debounceTimer !== undefined) window.clearTimeout(debounceTimer)
  debounceTimer = undefined
}
function underlyingUrl() {
  return stateUrl(store.state, todayIso, preSearchPath.value)
}
function replaceSearchUrl() {
  // Search still borrows the current history entry. Preserve its view/goal fragment and state.
  const hash = new URL(underlyingUrl(), location.origin).hash
  history.replaceState(history.state, '', `${query.value ? `/search/${encodeURIComponent(query.value)}` : '/search/'}${hash}`)
}
async function focusInput(openResults = true) {
  await nextTick()
  if (!openResults && document.activeElement !== input.value) skipNextFocusOpen = true
  input.value?.focus()
}
function onInputFocus() {
  if (skipNextFocusOpen) { skipNextFocusOpen = false; return }
  openSurface()
}
function runSearch(immediate = false, tag: string | null = null) {
  clearTimer()
  const version = ++searchVersion
  const text = query.value
  store.clearSearch()
  if ((recognizedTag.value && !tag) || (text.length > 0 && text.length < 3 && !tag)) {
    pending.value = false
    return
  }
  pending.value = true
  const start = () => {
    debounceTimer = undefined
    // Existing search actions share one result slice. Serialize them so an older response can
    // never paint over the latest query; obsolete queued requests never reach the API.
    searchChain = searchChain.then(async () => {
      if (version !== searchVersion) return
      try {
        if (tag) await store.filterByTag(tag)
        else if (text) await store.runSearch(text)
        else await store.loadRecentSearch()
      } finally {
        if (version === searchVersion) pending.value = false
      }
    }).catch(() => { if (version === searchVersion) pending.value = false })
  }
  if (immediate) start()
  else debounceTimer = window.setTimeout(start, SEARCH_DEBOUNCE_MS)
}
function openSurface() {
  if (surfaceOpen.value) return
  preSearchPath.value = location.pathname
  surfaceOpen.value = true
  activeIndex.value = 0
  replaceSearchUrl()
  runSearch()
  window.dispatchEvent(new CustomEvent('verticals:agent-close'))
}
function dismiss(restoreUrl = true) {
  clearTimer()
  searchVersion += 1
  pending.value = false
  surfaceOpen.value = false
  inputValue.value = ''
  store.clearSearch()
  if (restoreUrl && SEARCH_PATH_RE.test(location.pathname)) {
    history.replaceState(history.state, '', underlyingUrl())
  }
}
defineExpose({ dismiss })
function onInput(event: Event) {
  inputValue.value = (event.target as HTMLInputElement).value
  if (!surfaceOpen.value) openSurface()
  activeIndex.value = 0
  replaceSearchUrl()
  runSearch()
}
function pick(option: SearchOption) {
  if (option.kind === 'tag') {
    runSearch(true, recognizedTag.value)
    return
  }
  if (option.kind === 'ask') {
    if (!props.agentAvailable) return
    const text = query.value
    dismiss()
    input.value?.blur()
    window.dispatchEvent(new CustomEvent('verticals:agent-draft', { detail: { text } }))
    return
  }
  dismiss()
  input.value?.blur()
  if (option.kind === 'area') {
    store.closeGoal()
    store.setView('verticals')
    void store.setValueFilter(option.id!)
  } else if (option.id) {
    // Keep existing navigation, including its parked-goal limitation (issue 8c).
    void store.navigateToGoal(option.id)
  }
}
function onKeyDown(event: KeyboardEvent) {
  if (event.isComposing) return
  if (event.key === 'Escape') {
    event.preventDefault()
    event.stopPropagation()
    dismiss()
    void focusInput(false)
    return
  }
  if (event.key !== 'ArrowDown' && event.key !== 'ArrowUp' && event.key !== 'Enter') return
  if (!surfaceOpen.value) openSurface()
  if (!options.value.length) return
  // Native checkbox and button activation stays native; the field owns Enter selection.
  if (event.key === 'Enter' && event.target !== input.value) return
  event.preventDefault()
  if (event.key === 'Enter') pick(options.value[activeIndex.value]!)
  else {
    const direction = event.key === 'ArrowDown' ? 1 : -1
    activeIndex.value = (activeIndex.value + direction + options.value.length) % options.value.length
    input.value?.focus()
    void nextTick(() => root.value?.querySelector(`#command-option-${activeIndex.value}`)?.scrollIntoView({ block: 'nearest' }))
  }
}
function onShortcut(event: KeyboardEvent) {
  if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'k') {
    event.preventDefault()
    window.dispatchEvent(new CustomEvent('verticals:agent-close'))
    openSurface()
    void focusInput()
  }
}
function onCommandFocus() {
  // Chat closing returns focus without opening results over the conversation just dismissed.
  void focusInput(false)
}
function onOutsidePointer(event: PointerEvent) {
  if (surfaceOpen.value && event.target instanceof Node && !root.value?.contains(event.target)) dismiss()
}
function onFocusOut(event: FocusEvent) {
  if (event.relatedTarget instanceof Node && !root.value?.contains(event.relatedTarget)) dismiss()
}
function readSearchUrl() {
  const match = SEARCH_PATH_RE.exec(location.pathname)
  if (!match) { dismiss(false); return }
  let value = match[1] ?? ''
  try { value = decodeURIComponent(value) } catch { /* A malformed link remains editable. */ }
  preSearchPath.value = new URL(stateUrl(store.state, todayIso, '/'), location.origin).pathname
  inputValue.value = value
  surfaceOpen.value = true
  activeIndex.value = 0
  runSearch()
}
watch(options, rows => { activeIndex.value = Math.min(activeIndex.value, Math.max(0, rows.length - 1)) })
onMounted(() => {
  readSearchUrl()
  window.addEventListener('keydown', onShortcut)
  window.addEventListener('verticals:command-focus', onCommandFocus)
  window.addEventListener('popstate', readSearchUrl)
  document.addEventListener('pointerdown', onOutsidePointer)
})
onBeforeUnmount(() => {
  clearTimer()
  searchVersion += 1
  window.removeEventListener('keydown', onShortcut)
  window.removeEventListener('verticals:command-focus', onCommandFocus)
  window.removeEventListener('popstate', readSearchUrl)
  document.removeEventListener('pointerdown', onOutsidePointer)
})
</script>

<template>
  <div ref="root" class="search-bar" data-cap="search" @keydown="onKeyDown" @focusout="onFocusOut">
    <section v-if="surfaceOpen" class="search-modal" data-cap="search-modal" aria-label="Find or ask">
      <div id="command-results" class="search-modal__results" data-cap="search-results" role="grid" aria-label="Search results" :aria-busy="pending">
        <p v-if="pending" class="search-modal__status" role="status">Searching…</p>
        <p v-else-if="noMatches" class="search-modal__status" data-role="search-empty" role="status">{{ store.state.searchTag ? 'No goals with this tag.' : 'No matching goals or areas.' }}</p>
        <p v-else-if="query.length > 0 && query.length < 3 && !recognizedTag" class="search-modal__status">Type at least 3 characters to find goals.</p>
        <p v-else-if="!query" class="search-modal__status">Areas and recent goals</p>
        <p v-if="store.state.searchTruncated && !pending" class="search-modal__status">Showing the first results only.</p>
        <div
          v-for="(option, index) in options"
          :id="`command-option-${index}`"
          :key="option.key"
          class="search-result"
          :class="{ 'search-result--active': activeIndex === index, 'search-result--ask': option.kind === 'ask' }"
          role="row"
          :aria-selected="activeIndex === index"
          :data-goal-id="option.goal?.id"
          :data-value-id="option.kind === 'area' ? option.id : undefined"
          :data-role="option.kind === 'ask' ? 'ask-agent' : option.kind === 'area' ? 'area-option' : undefined"
          @pointermove="activeIndex = index"
          @focusin="activeIndex = index"
        >
          <div v-if="option.goal" class="search-result__check" role="gridcell">
            <KCheckbox size="xl" data-cap="complete" :model-value="option.goal.done_at !== null"
              @update:model-value="value => void store.completeGoal(option.id!, value)" />
          </div>
          <div class="search-result__cell" role="gridcell">
            <button type="button" class="search-result__open" :data-role="option.kind === 'goal' ? 'search-open' : undefined"
              :disabled="option.kind === 'ask' && !agentAvailable" @click="pick(option)">
              <span class="search-result__title" :class="{ 'search-result__title--done': option.goal?.done_at }">{{ option.label }}</span>
              <span class="search-result__meta" :data-role="option.kind === 'goal' ? 'search-period' : undefined">{{ option.meta }}</span>
            </button>
          </div>
        </div>
      </div>
    </section>
    <div class="search-modal__input" data-cap="search-input">
      <button type="button" class="search-bar__trigger" data-cap="search-trigger" aria-label="Search goals and areas" @click="openSurface(); focusInput()">
        <AppIcon name="search" :size="20" />
      </button>
      <button v-if="activeArea" type="button" class="search-bar__area" data-cap="value-filter" :aria-label="`Clear ${activeArea.label} area filter`" @click="store.setValueFilter(null)">{{ activeArea.label }} ×</button>
      <input ref="input" :value="inputValue" type="text" role="combobox" aria-label="Search goals, areas, or ask agent"
        placeholder="Search goals, areas, or ask agent" autocomplete="off" aria-autocomplete="list" aria-haspopup="grid"
        :aria-expanded="surfaceOpen" :aria-controls="surfaceOpen ? 'command-results' : undefined"
        :aria-activedescendant="surfaceOpen && options.length ? `command-option-${activeIndex}` : undefined"
        @focus="onInputFocus" @input="onInput">
      <span class="search-bar__shortcut" aria-hidden="true">⌘K</span>
    </div>
  </div>
</template>

<style>
.search-bar { position: relative; font-family: var(--font-body); }
.search-modal__input {
  display: flex;
  align-items: center;
  gap: 8px;
  box-sizing: border-box;
  height: 46px;
  padding: 0 10px 0 0;
  border: 1px solid #d4d4d4;
  border-radius: 8px;
  background: #fff;
}
.search-modal__input:focus-within { border-color: #2d3036; outline: 1px solid #2d3036; }
.search-modal__input input {
  display: block;
  min-width: 0;
  width: 100%;
  height: 100%;
  padding: 0;
  border: 0;
  outline: none;
  color: #2d3036;
  background: transparent;
  font: 400 15px/20px var(--font-body);
}
.search-modal__input input::placeholder { color: #626262; opacity: 1; }
.search-bar__trigger {
  flex: 0 0 44px;
  display: grid;
  place-items: center;
  width: 44px;
  height: 44px;
  padding: 0;
  border: 0;
  color: #626262;
  background: transparent;
  cursor: pointer;
}
.search-bar__shortcut { color: #626262; font: 400 13px/20px var(--font-body); white-space: nowrap; }
.search-bar__area {
  flex: 0 0 auto;
  min-width: 44px;
  height: 44px;
  padding: 0 8px;
  border: 0;
  border-radius: 6px;
  background: #f0f0f0;
  color: #2d3036;
  font: 400 13px/20px var(--font-body);
  cursor: pointer;
}
.search-modal {
  box-sizing: border-box;
  position: absolute;
  bottom: calc(100% + 8px);
  left: 0;
  width: 100%;
  overflow: hidden;
  border: 1px solid #dedede;
  border-radius: 8px;
  background: #fff;
  color: #2d3036;
  box-shadow: 0 8px 32px rgba(0, 0, 0, .12);
}
.search-modal__results { max-height: min(440px, calc(100dvh - var(--app-bar-height) - 32px)); overflow: auto; overscroll-behavior: contain; }
.search-modal__status { margin: 0; padding: 12px; color: #626262; font: 400 13px/20px var(--font-body); }
.search-result { display: flex; align-items: center; min-height: 44px; padding: 0 12px; gap: 10px; background: #fff; }
.search-result--active, .search-result:hover { background: #f0f0f0; }
.search-result--ask { position: sticky; bottom: 0; border-top: 1px solid #dedede; }
.search-result__check { flex: 0 0 auto; }
.search-result__cell { flex: 1 1 auto; min-width: 0; }
.search-result__open {
  display: flex;
  align-items: baseline;
  gap: 16px;
  width: 100%;
  min-height: 44px;
  padding: 10px 0;
  border: 0;
  background: transparent;
  color: #2d3036;
  font: 400 15px/22px var(--font-body);
  text-align: left;
  cursor: pointer;
}
.search-result__title { flex: 1 1 auto; min-width: 0; overflow-wrap: anywhere; }
.search-result__title--done { color: #626262; text-decoration: line-through; }
.search-result__meta { flex: 0 0 auto; color: #626262; font-size: 13px; line-height: 20px; }
.search-result__open:disabled { cursor: default; }
.search-result__open:focus-visible,
.search-bar__trigger:focus-visible,
.search-bar__area:focus-visible { outline: 2px solid #2d3036; outline-offset: 2px; }
@media (max-width: 900px) {
  .search-result__open { display: block; }
  .search-result__meta { display: block; }
  .search-bar__shortcut { display: none; }
}
</style>
