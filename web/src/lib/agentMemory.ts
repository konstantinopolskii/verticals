// The agent's instructions (docs/design/agent-memory.md): each layer's built-in text, which every release updates and nobody
// edits, and the memory over it, a document the owner and the agent both write and the gateway reads at every turn.
import { createDoc } from './api'
import { openWindow } from './windows'

export interface MemoryLayer {
  id: string
  title: string
  builtIn: string
  memory: { path: string; id: string | null; body?: string }
}

export const INSTRUCTIONS_KEY = 'instructions:agent'

export async function fetchInstructions(): Promise<MemoryLayer[]> {
  const res = await fetch('/__chat/instructions')
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  return ((await res.json()) as { layers?: MemoryLayer[] }).layers ?? []
}

export function openInstructions(from?: Element | null): void {
  openWindow({ kind: 'instructions', target: 'agent', title: 'Agent instructions' }, from)
}

/** A layer's memory in a window, the document made first when there is none yet. */
export async function openMemory(layer: MemoryLayer, from?: Element | null): Promise<void> {
  const title = `${layer.title}: memory`
  const id = layer.memory.id ?? (await createDoc({ path: layer.memory.path, title, body: '' })).id
  openWindow({ kind: 'doc', target: id, title }, from)
}
