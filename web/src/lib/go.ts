// "Ready?" (Inbox and Documents redesign, round 5, frames m4–m5, and round 8; KK 6–7 Oct 2026: "When commenting or editing
// document, I believe we should have some sort of a button black that will prompt agent to acknowledge edits … Not GO, but
// Go? It should question user, if he edited … Ready?"): after a comment or an edit in a document open as a window, the
// circle widens into a black pill that asks "Ready?", grey until pointed at. A click is your yes: the edits go to the agent
// in one message, and its answer lands in the field (S2.P4). Ignored, the question goes when the document closes. After
// "Ready?" on a morning report, its task is done.
import { computed, reactive, watch } from 'vue'
import { getDoc } from './api'
import { agentChat, newThread, send } from './agentChat'
import { commandFilter } from './commandFilter'
import { windows } from './windows'
import { MORNING_TITLE, MORNING_FOLDER } from './morning'
import { store } from '../store'

export const go = reactive({ docs: [] as string[] })

if (typeof window !== 'undefined') {
  window.addEventListener('verticals:doc-edited', (event) => {
    const id = (event as CustomEvent<{ id?: string }>).detail?.id
    if (id && !go.docs.includes(id)) go.docs.push(id)
  })
}

const openDocs = computed(() => new Set(windows.list.filter((w) => w.kind === 'doc').map((w) => w.target)))
// A document closed with its edits unsaid: the question goes with it.
watch(openDocs, (open) => { go.docs = go.docs.filter((id) => open.has(id)) })

/** "Ready?" stands in the circle: there are edits in an open document, an agent to hand them to, and the field is free. */
export const goShown = computed(() => agentChat.available && go.docs.length > 0 && !commandFilter.text && !agentChat.running
  && !agentChat.open)

export async function sayGo(): Promise<void> {
  const ids = [...go.docs]
  if (!ids.length) return
  go.docs = []
  const docs = await Promise.all(ids.map((id) => getDoc(id).catch(() => null)))
  const named = docs.filter((d): d is NonNullable<typeof d> => !!d)
  if (!named.length) return
  const links = named.map((d) => `[${(d.title || d.path).replace(/[[\]]/g, '')}](#doc/${d.id})`).join(', ')
  newThread()
  agentChat.engaged = false
  void send(`Ready. I commented on or edited ${links}. Read what I wrote there and act on it: a comment in a report's "Your comment" goes on its goal, verbatim, and its cell is cleared.`)
  // A morning report gone through has nothing left to wait for: its open task is done.
  for (const doc of named) {
    if (!doc.path.startsWith(`${MORNING_FOLDER}/`)) continue
    for (const link of doc.linked_goals) {
      const goal = store.state.board?.columns.flatMap((c) => c.goals).find((g) => g.id === link.goal_id)
      if (goal && goal.title === MORNING_TITLE && goal.done_at === null) void store.completeGoal(goal.id, true)
    }
  }
}
