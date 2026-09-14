// The card row's inline title editor (D186/D187): one cohesive edit lifecycle — start, autosize,
// draft, commit-once, cancel — extracted from `GoalCard.vue` when it neared the 750-line module
// cap (ARCHITECTURE.md S-90a). Same composable shape as `lib/completionCelebration.ts`: the
// component keeps its template bindings, this module owns the state machine.

import { nextTick, ref, type Ref } from 'vue'

export function useInlineTitleEdit(options: {
  /** The live committed title (a getter so the composable always compares against fresh props). */
  title: () => string
  /** Called once per edit with the trimmed, changed title. Never called for empty or unchanged. */
  commit: (next: string) => void
  /** The textarea's template ref — declared by the component, like `completionCelebration`'s
   *  layer/media refs, so the SFC keeps ownership of everything its template binds to. */
  input: Ref<HTMLTextAreaElement | null>
}) {
  const editing = ref(false)
  const draft = ref(options.title())
  const input = options.input
  /** Enter commits and blurs; the blur must not commit a second time. */
  let committed = false

  function autosize(): void {
    const el = input.value
    if (!el) return
    el.style.height = '0'
    el.style.height = `${el.scrollHeight}px`
  }

  function start(): void {
    committed = false
    draft.value = options.title()
    editing.value = true
    void nextTick(() => {
      autosize()
      input.value?.select()
    })
  }

  function onInput(event: Event): void {
    draft.value = (event.target as HTMLTextAreaElement).value
    autosize()
  }

  function commit(): void {
    if (committed) return
    committed = true
    editing.value = false
    const next = draft.value.trim()
    if (next && next !== options.title()) options.commit(next)
    else draft.value = options.title()
  }

  function cancel(): void {
    committed = true
    draft.value = options.title()
    editing.value = false
  }

  return { editing, draft, start, onInput, commit, cancel }
}
