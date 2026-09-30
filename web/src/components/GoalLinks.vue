<script setup lang="ts">
// A goal's links (docs/design-handoff S3.P1.007, .008): one list, the conversation Discuss with agent continues first,
// then the rest by their latest change, three in view and "N more". Each row has one mark for its kind: the agent's own
// on a conversation, the file on a document, the globe on a web page.
import { computed, onMounted, ref, watch } from 'vue'
import AppIcon from './AppIcon.vue'
import { agentChat, agentOf, assetUrl } from '../lib/agentChat'
import { openWindow } from '../lib/windows'

export interface LinkedDoc { key: string; path: string; title: string; updated: string | null; open: () => void; from?: string }

const props = defineProps<{ goalId: string; goalTitle: string; body: string; docs: LinkedDoc[]; inWindow: boolean }>()

type Row = { key: string; kind: 'conversation' | 'doc' | 'page'; title: string; at: number; mark?: string; note?: string; doc?: string; inherited?: boolean; open: (from: Element) => void }

const conversations = ref<{ session: string; provider: string; title: string; at: number }[]>([])
async function loadConversations(): Promise<void> {
  const found = new Map<string, { session: string; provider: string; title: string; at: number }>()
  for (const thread of agentChat.threads) {
    if (thread.goal?.id === props.goalId) found.set(thread.id, { session: thread.id, provider: thread.provider, title: thread.title, at: thread.updatedAt })
  }
  if (agentChat.available) {
    try {
      const res = await fetch(`/__chat/goal?id=${encodeURIComponent(props.goalId)}`)
      const data = res.ok ? await res.json() as { conversations?: { session: string; provider: string; lastTurnAt: number }[] } : {}
      for (const c of data.conversations ?? []) {
        const known = found.get(c.session)
        found.set(c.session, { session: c.session, provider: c.provider, title: known?.title || props.goalTitle, at: Math.max(known?.at ?? 0, c.lastTurnAt * 1000) })
      }
    } catch { /* no gateway: the conversations kept here are all there is */ }
  }
  conversations.value = [...found.values()].sort((a, b) => b.at - a.at)
}
onMounted(loadConversations)
watch(() => [props.goalId, agentChat.available, agentChat.threads.length], loadConversations)

const pages = computed(() => {
  const seen = new Set<string>()
  const out: { url: string; title: string }[] = []
  for (const m of props.body.matchAll(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)|(?<![(\w])(https?:\/\/[^\s<)\]]+[^\s<).,;:!?'"\]])/g)) {
    const url = m[2] ?? m[3]!
    if (seen.has(url)) continue
    seen.add(url)
    out.push({ url, title: m[1] ?? new URL(url).hostname })
  }
  return out
})

const rows = computed<Row[]>(() => {
  const talk = conversations.value.map((c): Row => ({
    key: `c:${c.session}`, kind: 'conversation', title: c.title || props.goalTitle, at: c.at, mark: assetUrl(agentOf(c.provider).image),
    open: () => window.dispatchEvent(new CustomEvent('verticals:discuss-goal', { detail: { id: props.goalId, session: c.session } })),
  }))
  const docs = props.docs.map((d): Row => ({
    key: `d:${d.key}`, kind: 'doc', title: d.title, at: d.updated ? Date.parse(d.updated) : 0, note: d.from ? `from ${d.from}` : undefined,
    doc: d.path, inherited: !!d.from,
    open: (from) => {
      if (props.inWindow) openWindow({ kind: 'doc', target: d.key, title: d.title }, from)
      else d.open()
    },
  }))
  const web = pages.value.map((p): Row => ({
    key: `p:${p.url}`, kind: 'page', title: p.title, at: 0,
    open: (from) => {
      if (props.inWindow) openWindow({ kind: 'page', target: p.url, title: p.title }, from)
      else window.open(p.url, '_blank', 'noopener')
    },
  }))
  const [first, ...others] = talk
  return [...(first ? [first] : []), ...[...others, ...docs, ...web].sort((a, b) => b.at - a.at)]
})

const all = ref(false)
const shown = computed(() => (all.value ? rows.value : rows.value.slice(0, 3)))
function when(at: number): string {
  if (!at) return ''
  return new Date(at).toLocaleDateString('en-GB', { day: 'numeric', month: 'short' })
}
</script>

<template>
  <div v-if="rows.length" class="goal-links" data-role="goal-links">
    <ul class="goal-links__list">
      <li v-for="row in shown" :key="row.key">
        <button type="button" class="goal-links__row" :class="{ 'goal-links__row--inherited': row.inherited }" :data-link-kind="row.kind"
          :data-link="row.key" :data-doc="row.doc" :data-inherited="row.inherited ? 'true' : undefined" @click="row.open($event.currentTarget as Element)">
          <img v-if="row.mark" class="goal-links__mark" alt="" :src="row.mark">
          <AppIcon v-else-if="row.kind === 'doc'" class="goal-links__mark" name="file" :size="14" />
          <AppIcon v-else class="goal-links__mark" name="world" :size="14" />
          <span class="goal-links__title">{{ row.title }}</span>
          <span v-if="row.note" class="goal-links__note">{{ row.note }}</span>
          <span class="goal-links__date">{{ when(row.at) }}</span>
        </button>
      </li>
    </ul>
    <button v-if="rows.length > 3" type="button" class="goal-links__more" data-role="goal-links-more" @click="all = !all">
      {{ all ? 'Show fewer' : `${rows.length - 3} more` }}
    </button>
  </div>
</template>

<style>
.goal-links { order: 4; align-self: stretch; margin: 12px 0 0; }
.goal-links__list { margin: 0; padding: 0; list-style: none; }
.goal-links__row {
  display: flex;
  align-items: center;
  gap: 8px;
  max-width: 100%;
  padding: 2px 0;
  border: 0;
  background: none;
  color: #000;
  font: 400 13px/20px var(--font-body);
  text-align: left;
  cursor: pointer;
}
.goal-links__row--inherited { color: rgb(0 0 0 / 50%); }
.goal-links__mark { flex: none; width: 14px; height: 14px; color: rgb(0 0 0 / 55%); }
.goal-links__title { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; text-decoration: underline;
  text-decoration-thickness: 1px; text-underline-offset: .15em; text-decoration-color: rgb(0 0 0 / 20%); }
.goal-links__note, .goal-links__date { flex: none; color: rgb(0 0 0 / 45%); }
.goal-links__more { padding: 2px 0 0 22px; border: 0; background: none; color: rgb(0 0 0 / 45%); font: 400 13px/20px var(--font-body);
  cursor: pointer; }
</style>
