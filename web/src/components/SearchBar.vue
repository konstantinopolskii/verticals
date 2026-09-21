<script setup lang="ts">
import AppIcon from './AppIcon.vue'
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import { KCheckbox } from '@konstantinopolskii/vue'
import TagChip from './TagChip.vue'
import { store, todayIso } from '../store'
import { stateUrl } from '../lib/urlState'

const SEARCH_DEBOUNCE_MS = 300
const SEARCH_PATH_RE = /^\/search(?:\/(.*))?\/?$/

const inputValue = ref('')
const surfaceOpen = ref(false)
const showRecent = ref(false)
const pending = ref(false)
const preSearchPath = ref('/')
const trigger = ref<HTMLButtonElement | null>(null)
const input = ref<HTMLInputElement | null>(null)

let debounceTimer: number | undefined
let previousBodyOverflow: string | null = null

function clearTimer() {
  if (debounceTimer !== undefined) window.clearTimeout(debounceTimer)
  debounceTimer = undefined
}

/** What the address bar should say with the search surface shut — read off the state, not off a
 *  URL snapshot taken when the surface opened: Back/Forward can move the app underneath an open
 *  surface, and a stale snapshot would put the wrong page back. Only the path is remembered, so a
 *  hand-typed `/h/<today>` comes back spelled the way it was. */
function underlyingUrl(): string {
  return stateUrl(store.state, todayIso, preSearchPath.value)
}

function replaceSearchUrl(query: string) {
  // Keep whatever `lib/urlState.ts` stored on this entry: the search surface borrows the address
  // bar, it does not replace the entry the app is standing on.
  history.replaceState(history.state, '', query ? `/search/${encodeURIComponent(query)}` : '/search/')
}

function schedule(search: () => void) {
  clearTimer()
  debounceTimer = window.setTimeout(() => {
    debounceTimer = undefined
    search()
  }, SEARCH_DEBOUNCE_MS)
}

function lockPageScroll() {
  if (previousBodyOverflow !== null) return
  previousBodyOverflow = document.body.style.overflow
  document.body.style.overflow = 'hidden'
}

function unlockPageScroll() {
  if (previousBodyOverflow === null) return
  document.body.style.overflow = previousBodyOverflow
  previousBodyOverflow = null
}

async function focusInput() {
  await nextTick()
  input.value?.focus()
}

async function loadRecent() {
  try {
    await store.loadRecentSearch()
  } finally {
    pending.value = false
  }
}

function scheduleRecent() {
  pending.value = true
  schedule(() => {
    if (surfaceOpen.value && inputValue.value.trim() === '' && store.state.searchTag === null) {
      void loadRecent()
    } else {
      pending.value = false
    }
  })
}

function openSurface() {
  if (surfaceOpen.value) return
  preSearchPath.value = location.pathname
  surfaceOpen.value = true
  showRecent.value = inputValue.value.trim() === ''
  replaceSearchUrl(inputValue.value.trim())
  lockPageScroll()
  if (showRecent.value) scheduleRecent()
  void focusInput()
}

async function closeSurface(restoreFocus = true) {
  clearTimer()
  pending.value = false
  inputValue.value = ''
  surfaceOpen.value = false
  showRecent.value = false
  store.clearSearch()
  history.replaceState(history.state, '', underlyingUrl())
  unlockPageScroll()
  await nextTick()
  if (restoreFocus) trigger.value?.focus()
}

const recognizedTag = computed(() => {
  const match = /^#(\S+)/.exec(inputValue.value.trim())
  return match ? match[1] : null
})

async function runTextSearch(query: string) {
  try {
    await store.runSearch(query)
  } finally {
    pending.value = false
  }
}

function onInput(event: Event) {
  clearTimer()
  const value = (event.target as HTMLInputElement).value
  inputValue.value = value
  replaceSearchUrl(value.trim())

  if (recognizedTag.value) {
    pending.value = false
    showRecent.value = false
    store.clearSearch()
    return
  }

  const trimmed = value.trim()
  if (trimmed.length < 3) {
    pending.value = false
    store.clearSearch()
    showRecent.value = trimmed.length === 0
    if (showRecent.value) scheduleRecent()
    return
  }

  showRecent.value = false
  pending.value = true
  store.clearSearch()
  schedule(() => void runTextSearch(trimmed))
}

async function onPickTag(tag: string) {
  clearTimer()
  pending.value = true
  try {
    await store.filterByTag(tag)
  } finally {
    pending.value = false
  }
}

function searchPeriod(goal: { vertical: string | null; anchor_date: string | null }): string {
  return goal.vertical && goal.anchor_date ? `${goal.vertical} · ${goal.anchor_date}` : ''
}

function onToggle(id: string, value: boolean) {
  void store.completeGoal(id, value)
}

function openGoal(id: string) {
  void closeSurface(false).then(() => store.navigateToGoal(id))
}

const hasQuery = computed(() => store.state.searchQuery.trim().length >= 3)
const showResults = computed(
  () => showRecent.value || store.state.searchTag !== null || (!recognizedTag.value && hasQuery.value),
)
const noMatches = computed(
  () => showResults.value && !pending.value && store.state.searchResults.length === 0,
)

onMounted(() => {
  const match = SEARCH_PATH_RE.exec(location.pathname)
  if (!match) return

  let query = ''
  try {
    query = decodeURIComponent(match[1] ?? '')
  } catch {
    query = match[1] ?? ''
  }

  surfaceOpen.value = true
  inputValue.value = query
  lockPageScroll()
  void focusInput()

  if (query.trim().length >= 3 && !/^#\S+/.test(query.trim())) {
    pending.value = true
    schedule(() => void runTextSearch(query.trim()))
  } else if (query.trim() === '') {
    showRecent.value = true
    scheduleRecent()
  }
})

onBeforeUnmount(() => {
  clearTimer()
  unlockPageScroll()
})
</script>

<template>
  <div class="search-bar" data-cap="search">
    <button
      ref="trigger"
      type="button"
      class="search-bar__trigger"
      data-cap="search-trigger"
      aria-label="Search"
      @click="openSurface"
    >
      <AppIcon
        name="search"
        class="search-bar__trigger-icon"
        :class="{ 'search-bar__trigger-icon--return': surfaceOpen }"
        data-role="search-icon"
      />
    </button>

    <Teleport to="body">
      <div
        v-if="surfaceOpen"
        class="search-backdrop"
        data-cap="search-backdrop"
        @pointerup.self="() => void closeSurface()"
      >
        <section class="search-modal" data-cap="search-modal">
          <div class="search-modal__input" data-cap="search-input">
            <span class="search-modal__input-slot" aria-hidden="true">
              <svg
                v-if="pending"
                class="search-modal__spinner"
                data-role="search-spinner"
                viewBox="0 0 20 20"
              >
                <circle cx="10" cy="10" r="8" />
              </svg>
              <AppIcon
                v-else
                name="search"
                class="search-modal__input-icon"
                data-role="search-input-icon"
              />
            </span>
            <input
              ref="input"
              :value="inputValue"
              type="text"
              placeholder="Search"
              autocomplete="off"
              @input="onInput"
              @keydown.esc="() => void closeSurface()"
            >
          </div>

          <div class="search-modal__results" data-cap="search-results">
            <div v-if="recognizedTag" class="search-modal__tag">
              <TagChip
                :tag="recognizedTag"
                :pressed="store.state.searchTag === recognizedTag"
                @select="onPickTag"
              />
            </div>
            <p v-if="store.state.searchTruncated" class="search-modal__truncated">
              Showing the first results only.
            </p>
            <p v-if="noMatches" class="search-modal__empty" data-role="search-empty">
              No results matched your search
            </p>
            <ul v-else-if="showResults && store.state.searchResults.length" class="search-modal__list">
              <li
                v-for="goal in store.state.searchResults"
                :key="goal.id"
                class="search-result"
                :data-goal-id="goal.id"
                @click="openGoal(goal.id)"
              >
                <KCheckbox
                  size="xl"
                  data-cap="complete"
                  :model-value="goal.done_at !== null"
                  @click.stop
                  @update:model-value="value => onToggle(goal.id, value)"
                />
                <div class="search-result__content">
                  <p
                    class="goal-card__title"
                    :class="{ 'search-result__title--done': goal.done_at !== null }"
                  >{{ goal.title }}</p>
                  <p data-role="search-period">{{ searchPeriod(goal) }}</p>
                </div>
                <button
                  type="button"
                  class="search-result__open"
                  data-role="search-open"
                  :aria-label="`Open ${goal.title}`"
                  @click.stop="openGoal(goal.id)"
                >
                  <AppIcon name="chevron-right" :size="16" />
                </button>
              </li>
            </ul>
          </div>
        </section>
      </div>
    </Teleport>
  </div>
</template>

<style>
.search-bar {
  position: relative;
}

.search-bar__trigger {
  display: grid;
  place-items: center;
  width: 24px;
  height: 25px;
  margin: 0;
  padding: 0;
  border: 0;
  background: transparent;
  color: rgb(45, 48, 54);
  cursor: pointer;
}
.search-bar__trigger:focus-visible {
  outline: 2px solid rgba(45, 48, 54, 0.3);
  outline-offset: 2px;
}
.search-bar__trigger-icon {
  position: relative;
  top: -4px;
  display: block;
  width: 24px;
  height: 25px;
  opacity: 0.3;
  transition: opacity 250ms cubic-bezier(0.165, 0.84, 0.44, 1);
}
.search-bar__trigger:hover .search-bar__trigger-icon,
.search-bar__trigger:active .search-bar__trigger-icon {
  opacity: 1;
}
.search-bar__trigger-icon--return {
  animation: search-trigger-icon-return 250ms cubic-bezier(0.165, 0.84, 0.44, 1);
}
@keyframes search-trigger-icon-return {
  from { opacity: 1; }
  to { opacity: 0.3; }
}
@media (prefers-reduced-motion: reduce) {
  .search-bar__trigger-icon--return { animation: none; }
}

.search-backdrop {
  position: fixed;
  inset: 0;
  z-index: 300;
  overflow: scroll;
  background: rgba(0, 0, 0, 0.6);
  backdrop-filter: none;
}
.search-modal {
  box-sizing: border-box;
  width: min(100vw, 824px);
  max-width: 824px;
  margin: 50px auto 0;
  padding: 0;
  overflow: hidden;
  background: #ffffff;
  border: 0;
  border-radius: 12px;
  box-shadow: none;
  font-family: 'Inter', sans-serif;
  opacity: 1;
  transform: none;
}
.search-modal__input {
  position: relative;
  width: 100%;
}
.search-modal__input input {
  box-sizing: border-box;
  display: block;
  width: 100%;
  height: 65.891px;
  margin: 0;
  padding: 16px 16px 16px 44px;
  color: rgb(45, 48, 54);
  background: #ffffff;
  border: 2px solid rgb(255, 255, 255);
  border-radius: 8px;
  outline: none;
  font-family: 'Inter', sans-serif;
  font-size: 26px;
  font-weight: 400;
  line-height: 29.9px;
}
.search-modal__input-slot {
  box-sizing: border-box;
  position: absolute;
  inset: 0 auto 0 0;
  z-index: 1;
  display: flex;
  width: 48px;
  padding: 0 14px;
  align-items: center;
  justify-content: center;
  pointer-events: none;
}
.search-modal__spinner,
.search-modal__input-icon {
  display: block;
  flex: 0 0 20px;
  width: 20px;
  height: 20px;
}
.search-modal__input-icon {
  opacity: 0.6;
  cursor: default;
}
.search-modal__spinner {
  fill: none;
  stroke: currentColor;
  stroke-width: 2px;
  stroke-linecap: round;
  stroke-dasharray: 36 16;
  animation: search-spinner-rotation 700ms linear infinite;
}
@keyframes search-spinner-rotation {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}

.search-modal__results {
  box-sizing: border-box;
  width: 100%;
  max-height: 450px;
  padding: 0 0 15px;
  overflow: scroll;
}
.search-modal__list {
  display: block;
  margin: 0;
  padding: 0;
  list-style: none;
}
.search-result {
  box-sizing: border-box;
  display: flex;
  min-height: 37px;
  padding: 8px 18px;
  align-items: center;
  gap: 14px;
  background: transparent;
  border-bottom: 1px solid rgba(45, 48, 54, 0.1);
  cursor: pointer;
  transition: background-color 300ms cubic-bezier(0.165, 0.84, 0.44, 1);
}
.search-result:hover {
  background: #ecedef;
}
.search-result__content {
  display: flex;
  flex: 1 1 auto;
  min-width: 0;
  align-items: baseline;
  gap: 8px;
}
.search-result .goal-card__title {
  flex: 1 1 auto;
  min-width: 0;
  margin: 0;
  color: rgb(45, 48, 54);
  font-family: 'Inter', sans-serif;
  font-size: 15px;
  font-weight: 400;
  line-height: 20px;
  cursor: pointer;
}
.search-result .search-result__title--done {
  color: rgba(45, 48, 54, 0.3);
}
.search-result [data-role='search-period'] {
  flex: 0 0 auto;
  margin: 0;
  font-size: 14px;
  font-weight: 400;
  line-height: 20px;
  opacity: 0.5;
  white-space: nowrap;
}
.search-result__open {
  box-sizing: border-box;
  display: block;
  flex: 0 0 16px;
  width: 16px;
  height: 16px;
  margin: 0;
  padding: 0;
  border: 0;
  background: transparent;
  color: rgb(45, 48, 54);
  opacity: 0.5;
  cursor: pointer;
}
.search-result__open svg {
  display: block;
  width: 16px;
  height: 16px;
  fill: none;
  stroke: currentColor;
  stroke-width: 2.2;
  stroke-linecap: round;
  stroke-linejoin: round;
}
.search-modal__empty {
  margin: 30px 0;
  text-align: center;
  font-family: 'Inter', sans-serif;
  font-size: 16px;
  font-weight: 400;
  line-height: 18.4px;
}
.search-modal__tag {
  padding: 8px 18px;
}
.search-modal__truncated {
  margin: 8px 18px;
  font-size: 14px;
  line-height: 20px;
}
</style>
