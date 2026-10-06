// "Go" (Inbox and Documents redesign, round 5, frames m4–m5; KK 6 Oct 2026: "When commenting or editing document, I
// believe we should have some sort of a button black that will prompt agent to acknowledge edits … Like we have this
// circle, which could me morphed in the wider shape black … But it should be elegant"): after a comment or an edit in a
// document open as a window, the circle widens into a black pill that says "Go", grey until pointed at. A click hands the
// edits to the agent in one message; its answer lands in the field (S2.P4). Ignored, Go goes when the document closes.
// After Go on a morning report nothing waits any more: its task is done and its page leaves the circle.
import { computed, reactive, watch } from 'vue'
import { getDoc } from './api'
import { agentChat, newThread, send } from './agentChat'
import { commandFilter } from './commandFilter'
import { windows } from './windows'
import { waitingPages } from './waiting'
import { store } from '../store'

export const go = reactive({ docs: [] as string[] })

if (typeof window !== 'undefined') {
  window.addEventListener('verticals:doc-edited', (event) => {
    const id = (event as CustomEvent<{ id?: string }>).detail?.id
    if (id && !go.docs.includes(id)) go.docs.push(id)
  })
}

const openDocs = computed(() => new Set(windows.list.filter((w) => w.kind === 'doc').map((w) => w.target)))
// A document closed with its edits unsaid: Go goes with it.
watch(openDocs, (open) => { go.docs = go.docs.filter((id) => open.has(id)) })

/** Go stands in the circle: there are edits in an open document, an agent to hand them to, and the field is free. */
export const goShown = computed(() => agentChat.available && go.docs.length > 0 && !commandFilter.text && !agentChat.running
  && !agentChat.open)

export async function sayGo(): Promise<void> {
  const ids = [...go.docs]
  if (!ids.length) return
  go.docs = []
  const docs = await Promise.all(ids.map((id) => getDoc(id).catch(() => null)))
  const named = docs.filter((d): d is NonNullable<typeof d> => !!d)
  if (!named.length) return
  const links = named.map((d) => `[${(d.title || d.path).replace(/[[\]]/g, '')}](doc:${d.path})`).join(', ')
  newThread()
  agentChat.engaged = false
  void send(`Go. I commented on or edited ${links}. Read what I wrote there and act on it: a comment in a report's "Your comment" goes on its goal, verbatim, and its cell is cleared.`)
  // A morning report gone through has nothing left to wait for.
  for (const page of waitingPages.value) {
    if (page.kind === 'morning' && named.some((d) => d.id === page.docId)) void store.completeGoal(page.taskId, true)
  }
}
