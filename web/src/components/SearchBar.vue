<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { getGoal, searchGoals, type GoalCard } from '../lib/api'
import { store } from '../store'
import type { GoalCardData } from '../types'
import { boardMatches, commandFilter, commandSuggestions, effectiveTokens, filterActive, queryTerms, recognizeCommand, remoteMatchesFilter, type CommandToken } from '../lib/commandFilter'

const props = defineProps<{ agentAvailable: boolean }>()
const root = ref<HTMLElement | null>(null)
const input = ref<HTMLInputElement | null>(null)
const focused = ref(false)
const activeIndex = ref(-1)
const remoteResults = ref<GoalCard[]>([])
const remoteTruncated = ref(false)
const remoteError = ref(false)
const remotePending = ref(false)
let requestVersion = 0
let remoteInventory: Promise<{ goals: GoalCard[]; truncated: boolean; verticalsComplete: boolean }> | null = null
const remoteAncestors = new Map<string, Promise<string[]>>()
watch(() => store.state.board, () => { remoteInventory = null; remoteAncestors.clear() })
function allRemoteCandidates() {
  if (!remoteInventory) remoteInventory = Promise.all([
    searchGoals({ limit: 200 }),
    ...['day', 'week', 'month', 'quarter', 'year', 'decade', 'life'].map(vertical => searchGoals({ vertical, limit: 200 })),
  ]).then(async responses => {
    const goals = new Map(responses.flatMap(response => response.goals).map(goal => [goal.id, goal]))
    for (const column of store.state.board?.columns ?? []) for (const goal of column.goals) goals.set(goal.id, goal)
    for (const children of Object.values(store.state.board?.children ?? {})) for (const goal of children) goals.set(goal.id, goal)
    // Existing detail reads expose the complete child/idea graph of each known root,
    // including parked descendants omitted from both dated search and the current board.
    const queue = [...goals.values()]
    const visited = new Set<string>()
    const worker = async () => {
      while (queue.length) {
        const goal = queue.shift()!
        if (visited.has(goal.id)) continue
        visited.add(goal.id)
        const detail = await getGoal(goal.id)
        remoteAncestors.set(goal.id, Promise.resolve(detail.ancestors.map(parent => parent.id)))
        for (const child of [...detail.children, ...detail.ideas]) {
          if (!goals.has(child.id)) { goals.set(child.id, child); queue.push(child) }
        }
      }
    }
    await Promise.all(Array.from({ length: 8 }, worker))
    // The Maybe board contains undone parentless null-vertical goals, including parked
    // roots. Older parentless DONE null-vertical goals can remain outside recent200.
    // Area subtrees are complete once every dated vertical root and its graph was read.
    return { goals: [...goals.values()], truncated: responses.some(response => response.truncated), verticalsComplete: responses.slice(1).every(response => !response.truncated) }
  }).catch(error => { remoteInventory = null; throw error })
  return remoteInventory
}
const suggestions = computed(() => commandSuggestions.value.filter(item => !commandFilter.tokens.some(token => token.key === item.key)))
const showSuggestions = computed(() => focused.value && !commandFilter.text && !commandFilter.chatOpen)
const label = computed(() => [...commandFilter.tokens.map(token => token.label), commandFilter.text.trim()].filter(Boolean).join(' '))
const noMatches = computed(() => queryTerms.value.length > 0 && filterActive.value && !remotePending.value && !boardMatches.value.length && !remoteResults.value.length)
const hint = computed(() => commandFilter.chatOpen ? '⌘↵ send' : label.value ? '⌘↵ ask agent' : '⌘K')

function addToken(token: CommandToken) {
  if (token.kind === 'view') commandFilter.tokens = commandFilter.tokens.filter(item => item.kind !== 'view')
  if (!commandFilter.tokens.some(item => item.key === token.key)) commandFilter.tokens.push(token)
  activeIndex.value = -1
  void focusInput()
}
function removeToken(index: number) { commandFilter.tokens.splice(index, 1); void focusInput() }
function onInput(event: Event) {
  const value = (event.target as HTMLInputElement).value
  if (commandFilter.chatOpen) { commandFilter.text = value; return }
  // Space accepts a command. Bare area/vertical/state keywords filter; bare view names stay inert.
  commandFilter.text = value.replace(/(^|\s)(\S+)(?=\s)/g, (whole, leading: string, word: string) => {
    const token = recognizeCommand(word)
    if (!token) return whole
    addToken(token)
    return leading
  }).replace(/^\s+/, '')
  activeIndex.value = -1
}
function clear() { commandFilter.text = ''; commandFilter.tokens = []; remoteResults.value = [] }
function dismiss() { clear(); input.value?.blur() }
defineExpose({ dismiss })
async function focusInput() { await nextTick(); input.value?.focus({ preventScroll: true }) }

watch(() => commandFilter.tokens.find(token => token.kind === 'view')?.value, async (view, previous) => {
  if (commandFilter.chatOpen) return
  if (view === 'inbox' || view === 'docs') { store.closeGoal(); store.setView(view) }
  else if (previous) { store.closeGoal(); store.setView('verticals') }
  // Navigation is part of editing the field. Keep the caret after its tokens.
  await focusInput()
})

watch([queryTerms, effectiveTokens, () => store.state.board], async () => {
  const version = ++requestVersion
  remoteResults.value = []
  remoteTruncated.value = false
  remoteError.value = false
  remotePending.value = false
  if (!filterActive.value) return
  // The existing endpoint has a three-character floor and returns at most 200 records.
  // Use one title term as the server candidate query; apply ALL terms and tokens locally.
  const term = [...queryTerms.value].sort((a, b) => b.length - a.length)[0]
  const vertical = effectiveTokens.value.find(token => token.kind === 'vertical')?.value
  remotePending.value = true
  try {
    const response = term && term.length < 3
      ? await allRemoteCandidates()
      : term || vertical
        ? await searchGoals({ q: term?.slice(0, 200), vertical, limit: 200 })
        : await allRemoteCandidates()
    if (version !== requestVersion) return
    const shown = new Set<string>()
    const collect = (goals: GoalCardData[]) => { for (const goal of goals) { shown.add(goal.id); collect(goal.children ?? []) } }
    for (const column of store.columns.value) if (column.vertical !== 'maybe') collect(column.goals)
    const area = effectiveTokens.value.some(token => token.kind === 'area')
    const candidates = response.goals.filter(goal => !shown.has(goal.id))
    const matches: GoalCard[] = []
    // Keep requests bounded and interrupt obsolete queries between batches.
    for (let offset = 0; offset < candidates.length; offset += 8) {
      if (version !== requestVersion) return
      const batch = await Promise.all(candidates.slice(offset, offset + 8).map(async goal => {
        let ancestors = store.state.board?.ancestors[goal.id]?.map(parent => parent.id) ?? []
        if (area && !ancestors.length) {
          let request = remoteAncestors.get(goal.id)
          if (!request) { request = getGoal(goal.id).then(detail => detail.ancestors.map(parent => parent.id)); remoteAncestors.set(goal.id, request) }
          ancestors = await request
        }
        return remoteMatchesFilter(goal, ancestors) ? goal : null
      }))
      matches.push(...batch.filter((goal): goal is GoalCard => !!goal))
    }
    if (version !== requestVersion) return
    remoteResults.value = matches
    remoteTruncated.value = area && !term && 'verticalsComplete' in response && response.verticalsComplete ? false : response.truncated
  } catch { if (version === requestVersion) remoteError.value = true }
  finally { if (version === requestVersion) remotePending.value = false }
}, { flush: 'post' })

function where(goal: GoalCard) {
  const date = goal.anchor_date ? new Date(`${goal.anchor_date}T12:00:00`).toLocaleDateString('en-GB', { day: 'numeric', month: 'short' }) : ''
  const state = goal.parked_from_vertical ? 'parked' : goal.done_at ? 'done' : goal.vertical ?? 'Inbox'
  return [state, date].filter(Boolean).join(' · ')
}
async function openRemote(goal: GoalCard) { dismiss(); await store.navigateToGoal(goal.id) }
async function openOnlyMatch() {
  if (remotePending.value) return
  const matches = [...new Map(boardMatches.value.map(goal => [goal.id, goal])).values()]
  if (matches.length + remoteResults.value.length !== 1) return
  if (remoteResults.value.length === 1) { await openRemote(remoteResults.value[0]!); return }
  input.value?.blur()
  await store.openBoardGoal(matches[0]!.id)
}
function askAgent() {
  if (!props.agentAvailable || !label.value) return
  const text = label.value
  // Cancelable bridge supports a draft-only proof: preventDefault preserves the handoff without submitting.
  const event = new CustomEvent('verticals:agent-draft', { cancelable: true, detail: { text, submit: true } })
  commandFilter.chatOpen = true
  commandFilter.tokens = []
  commandFilter.text = text
  const send = window.dispatchEvent(event)
  if (send) commandFilter.text = ''
  void focusInput()
}
function onKeyDown(event: KeyboardEvent) {
  if (event.isComposing) return
  if ((event.metaKey || event.ctrlKey) && event.key === 'Enter') { event.preventDefault(); event.stopPropagation(); askAgent(); return }
  if (event.key === 'Escape') {
    event.preventDefault(); event.stopPropagation()
    if (commandFilter.chatOpen) { window.dispatchEvent(new CustomEvent('verticals:agent-close')); commandFilter.chatOpen = false; clear() }
    else if (commandFilter.text) commandFilter.text = ''
    else if (commandFilter.tokens.length) removeToken(commandFilter.tokens.length - 1)
    else input.value?.blur()
    return
  }
  if (event.key === 'Backspace' && input.value?.selectionStart === 0 && input.value.selectionEnd === 0 && commandFilter.tokens.length) {
    event.preventDefault(); removeToken(commandFilter.tokens.length - 1); return
  }
  if (showSuggestions.value && ['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown'].includes(event.key)) {
    event.preventDefault()
    const direction = ['ArrowLeft', 'ArrowUp'].includes(event.key) ? -1 : 1
    activeIndex.value = (activeIndex.value + direction + suggestions.value.length) % suggestions.value.length
    void nextTick(() => root.value?.querySelector(`#command-suggestion-${activeIndex.value}`)?.scrollIntoView({ block: 'nearest', inline: 'nearest' }))
    return
  }
  if (event.key === 'Enter') {
    event.preventDefault()
    const viewCommand = !commandFilter.chatOpen ? recognizeCommand(commandFilter.text.trim()) : undefined
    if (viewCommand?.kind === 'view') { commandFilter.text = ''; addToken(viewCommand) }
    else if (showSuggestions.value && activeIndex.value >= 0) addToken(suggestions.value[activeIndex.value]!)
    else if (!commandFilter.chatOpen && filterActive.value) void openOnlyMatch()
  }
}
function onShortcut(event: KeyboardEvent) {
  if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'k') { event.preventDefault(); event.stopImmediatePropagation(); void focusInput() }
}
function onAgentState(event: Event) { commandFilter.chatOpen = !!(event as CustomEvent).detail?.expanded }
function onCommandFocus() { commandFilter.chatOpen = false; clear(); void focusInput() }
function onComposerDraft(event: Event) { commandFilter.text = (event as CustomEvent).detail?.text ?? ''; void focusInput() }
function onFocusOut(event: FocusEvent) { if (!(event.relatedTarget instanceof Node) || !root.value?.contains(event.relatedTarget)) focused.value = false }
onMounted(() => {
  const match = /^\/search\/(.*)/.exec(location.pathname)
  if (match?.[1]) { try { commandFilter.text = decodeURIComponent(match[1]) } catch { commandFilter.text = match[1] } }
  window.addEventListener('keydown', onShortcut, true)
  window.addEventListener('verticals:agent-state', onAgentState)
  window.addEventListener('verticals:command-focus', onCommandFocus)
  window.addEventListener('verticals:composer-draft', onComposerDraft)
})
onBeforeUnmount(() => {
  requestVersion++
  window.removeEventListener('keydown', onShortcut, true)
  window.removeEventListener('verticals:agent-state', onAgentState)
  window.removeEventListener('verticals:command-focus', onCommandFocus)
  window.removeEventListener('verticals:composer-draft', onComposerDraft)
})
</script>

<template>
  <div ref="root" class="command-field" data-cap="search" :data-mode="commandFilter.chatOpen ? 'chat' : 'find'" @keydown="onKeyDown" @focusout="onFocusOut">
    <div class="command-field__surface" aria-hidden="true"></div>
    <div v-if="showSuggestions" class="command-field__line command-field__suggestions" aria-label="Find, filter or switch view">
      <template v-for="(item, index) in suggestions" :key="item.key">
        <span v-if="index" class="command-field__separator" aria-hidden="true">·</span>
        <button :id="`command-suggestion-${index}`" type="button" :class="{ 'is-active': index === activeIndex }" :data-token="item.key" @mousedown.prevent @click="addToken(item)">{{ item.label }}</button>
      </template>
    </div>
    <div v-else-if="!commandFilter.chatOpen && queryTerms.length && remoteResults.length" class="command-field__line command-field__remote" data-role="offboard-matches">
      <span class="command-field__muted">Maybe this?</span>
      <button v-for="goal in remoteResults.slice(0, 3)" :key="goal.id" type="button" :data-goal-id="goal.id" @click="openRemote(goal)"><span>{{ goal.title }}</span> <small>{{ where(goal) }}</small></button>
      <span v-if="remoteResults.length > 3 || remoteTruncated" class="command-field__muted">+{{ Math.max(0, remoteResults.length - 3) }}{{ remoteTruncated ? '+' : '' }}</span>
    </div>
    <div v-else-if="!commandFilter.chatOpen && noMatches" class="command-field__line command-field__muted" data-role="search-empty">Nothing matches ‘{{ label }}’ · ⌘↵ asks the agent<span v-if="remoteError"> · Other goals unavailable</span><span v-else-if="remoteTruncated"> · Other goals limited</span></div>
    <div class="command-field__input" data-cap="search-input">
      <div v-if="commandFilter.tokens.length && !commandFilter.chatOpen" class="command-field__tokens">
        <button v-for="(token, index) in commandFilter.tokens" :key="token.key" type="button" class="command-field__token" :aria-label="`Remove ${token.label} filter`" @click="removeToken(index)">{{ token.label }} <span aria-hidden="true">×</span></button>
      </div>
      <input ref="input" :value="commandFilter.text" type="text" :aria-label="commandFilter.chatOpen ? 'Message agent' : 'Find, filter or ask'" placeholder="Find, filter or ask" autocomplete="off" :aria-activedescendant="showSuggestions && activeIndex >= 0 ? `command-suggestion-${activeIndex}` : undefined" @focus="focused = true" @input="onInput">
      <span class="command-field__hint" :title="!agentAvailable ? 'Agent unavailable in this browser' : undefined">{{ hint }}</span>
    </div>
  </div>
</template>

<style>
.command-field { position: fixed; bottom: 16px; left: 50%; transform: translateX(-50%); z-index: 300; width: min(720px, calc(100vw - 32px)); background: #fff; border: 0; border-radius: var(--radius, 12px); box-shadow: none; color: #242424; font-family: var(--font-body); }
/* Toasts stand just above the field: the field's 16 px, its 48 px, then the kit's 8 px between toasts. At the kit's 24 px
   they sat under the field, 8 px of black showing, and no one could read one or press its Undo (test_s77, 29 Sep 2026).
   The kit's attribute outranks its own rule, which the build puts after this one. */
.toast-stack[data-toast-stack] { bottom: calc(16px + 48px + 8px); }
.command-field__surface { position: absolute; inset: calc(-1 * var(--conversation-height, 0px)) 0 0; z-index: -1; pointer-events: none; border-radius: var(--radius, 12px); background: #fff; box-shadow: var(--shadow-float); }
.command-field__input { display: flex; align-items: center; gap: 12px; height: 48px; padding: 0 16px; box-sizing: border-box; }
.command-field__input input { flex: 1; min-width: 40px; width: 100%; height: 100%; padding: 0; border: 0; outline: none; background: transparent; color: #242424; font: 400 16px/24px var(--font-body); }
.command-field__input input::placeholder { color: #686868; opacity: 1; }
.command-field__hint, .command-field__muted, .command-field__separator, .command-field__remote small { color: #686868; font: 400 12px/18px var(--font-body); }
.command-field__hint { flex: 0 0 auto; white-space: nowrap; }
.command-field__line { display: flex; align-items: baseline; gap: 5px; padding: 12px 16px 0; overflow-x: auto; white-space: nowrap; scrollbar-width: none; }
.command-field__line::-webkit-scrollbar { display: none; }
.command-field__line button { padding: 0; border: 0; background: transparent; color: #242424; font: 400 12px/18px var(--font-body); cursor: pointer; }
.command-field__line button.is-active, .command-field__line button:hover { text-decoration: underline; }
.command-field__tokens { display: flex; gap: 8px; min-width: 0; max-width: 65%; overflow: auto; scrollbar-width: none; flex-shrink: 0; }
.command-field__token { flex-shrink: 0; border: 0; padding: 4px 0; background: none; color: #242424; font: 400 13px/20px var(--font-body); cursor: pointer; white-space: nowrap; }
.command-field__token span { color: #686868; }
.command-field__remote { gap: 10px; }
.command-field__remote button { min-width: 0; flex: 0 1 auto; display: flex; gap: 4px; }
.command-field__remote button > span { max-width: 145px; overflow: hidden; text-overflow: ellipsis; }
.command-field button:focus-visible { outline: 1px solid #242424; outline-offset: 3px; }
</style>
