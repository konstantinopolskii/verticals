import { reactive } from 'vue'
import { fetchPrivacy, putPrivacy, type PrivacyView } from './api'

const state = reactive({ mode: false, hidden: new Set<string>() })

function apply(view: PrivacyView): void {
  state.mode = view.mode
  state.hidden = new Set(view.hidden)
}

export async function refreshPrivacy(): Promise<void> {
  try {
    apply(await fetchPrivacy())
  } catch {
    // The next board load asks again.
  }
}

export async function togglePrivacy(): Promise<void> {
  const next = !state.mode
  state.mode = next
  try {
    apply(await putPrivacy(next))
  } catch {
    state.mode = !next
  }
}

export function isPrivate(id: string): boolean {
  return state.mode && state.hidden.has(id)
}

export function isPrivacyHotkey(event: KeyboardEvent): boolean {
  return (event.metaKey || event.ctrlKey) && event.shiftKey && !event.altKey && event.code === 'KeyP'
}
