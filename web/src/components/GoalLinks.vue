<script setup lang="ts">
// A goal's links (docs/design-handoff S3.P1.007, .008): one list, the conversation Discuss with agent continues first,
// then the rest by their latest change, three in view and "N more". Each row has one mark for its kind: the agent's own
// on a conversation, the file on a document, the globe on a web page. A conversation is a session of the task
// (docs/design/task-sessions.md): its row says when it last moved, or that it went on in Claude or Codex without Verticals,
// and the arrow at its end opens it where it lives.
import { computed, ref } from 'vue'
import AppIcon from './AppIcon.vue'
import { agentChat, agentOf, assetUrl } from '../lib/agentChat'
import { agentName, ago, openSession, sessionsOf, sessionWhen, taskSessions, type TaskSession } from '../lib/taskSessions'
import { openWindow } from '../lib/windows'
import './goalLinks.css'

export interface LinkedDoc { key: string; path: string; title: string; updated: string | null; open: () => void; from?: string }

const props = defineProps<{ goalId: string; goalTitle: string; body: string; docs: LinkedDoc[]; inWindow: boolean }>()

type Row = {
  key: string; kind: 'conversation' | 'doc' | 'page'; title: string; at: number; mark?: string; note?: string; doc?: string
  inherited?: boolean; open: (from: Element) => void
  /** A session's row: when it last moved, in words, and the way to open it where it lives. */
  when?: string; where?: { label: string; open: () => void }
}

/* The task's sessions: what the gateway knows (read every couple of seconds, so a session that goes on outside shows up here
   while the list is in sight), with the conversations this browser has kept for it, newest first. */
const conversations = computed(() => {
  const found = new Map<string, TaskSession & { listed: boolean }>()
  for (const thread of agentChat.threads) {
    if (thread.goal?.id === props.goalId) {
      found.set(thread.id, { session: thread.id, provider: thread.provider, title: thread.title, movedAt: thread.updatedAt, outside: false, working: false, listed: false })
    }
  }
  for (const session of agentChat.available ? sessionsOf(props.goalId) : []) {
    const known = found.get(session.session)
    found.set(session.session, { ...session, title: known?.title || session.title || props.goalTitle, movedAt: Math.max(known?.movedAt ?? 0, session.movedAt), listed: true })
  }
  return [...found.values()].sort((a, b) => b.movedAt - a.movedAt)
})

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
    key: `c:${c.session}`, kind: 'conversation', title: c.title || props.goalTitle, at: c.movedAt, mark: assetUrl(agentOf(c.provider).image),
    when: c.listed ? sessionWhen(c) : ago(c.movedAt, taskSessions.now),
    open: () => window.dispatchEvent(new CustomEvent('verticals:discuss-goal', { detail: { id: props.goalId, session: c.session, provider: c.provider } })),
    where: c.listed ? { label: `Open in ${agentName(c.provider)}`, open: () => void openSession(c) } : undefined,
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
      <li v-for="row in shown" :key="row.key" class="goal-links__item">
        <button type="button" class="goal-links__row" :class="{ 'goal-links__row--inherited': row.inherited }" :data-link-kind="row.kind"
          :data-link="row.key" :data-doc="row.doc" :data-inherited="row.inherited ? 'true' : undefined" @click="row.open($event.currentTarget as Element)">
          <img v-if="row.mark" class="goal-links__mark" alt="" :src="row.mark">
          <AppIcon v-else-if="row.kind === 'doc'" class="goal-links__mark" name="file" :size="14" />
          <AppIcon v-else class="goal-links__mark" name="world" :size="14" />
          <span class="goal-links__title">{{ row.title }}</span>
          <span v-if="row.note" class="goal-links__note">{{ row.note }}</span>
          <span class="goal-links__date" :data-role="row.when ? 'session-when' : undefined">{{ row.when ?? when(row.at) }}</span>
        </button>
        <button v-if="row.where" type="button" class="goal-links__open" data-role="open-session" :aria-label="row.where.label" :title="row.where.label"
          @click="row.where.open()"><AppIcon name="arrow-up-right" :size="16" /></button>
      </li>
    </ul>
    <button v-if="rows.length > 3" type="button" class="goal-links__more" data-role="goal-links-more" @click="all = !all">
      {{ all ? 'Show fewer' : `${rows.length - 3} more` }}
    </button>
  </div>
</template>
