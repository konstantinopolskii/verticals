// The windows lifted over the board (docs/design-handoff S3.P2, S3.P3) and the one "out of focus" flag the board's layer
// and every window read (S2.P6.012): the board is out of focus while the conversation or a window is open.
import { computed, reactive } from 'vue'
import { agentChat } from './agentChat'

export type WindowKind = 'goal' | 'doc' | 'page'
export interface VtWindow {
  key: string
  kind: WindowKind
  target: string
  title: string
}

export const windows = reactive({
  list: [] as VtWindow[],
  front: 0,
})

export const frontWindow = computed(() => windows.list[windows.front] ?? null)
export const outOfFocus = computed(() => agentChat.open || windows.list.length > 0)
