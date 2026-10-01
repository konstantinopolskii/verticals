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

  /** `caret`: the character a click landed on, so the caret goes there (D67); none, from the keyboard, selects all. */
  function start(caret: number | null = null): void {
    committed = false
    draft.value = options.title()
    editing.value = true
    void nextTick(() => {
      autosize()
      const el = input.value
      if (!el) return
      el.focus()
      if (caret === null) el.select()
      else el.setSelectionRange(Math.min(caret, el.value.length), Math.min(caret, el.value.length))
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

/** Where in the title a click landed, as a character offset, so editing starts with the caret there (D67, KK
 *  2026-08-10: "он весь выделяется вместо того чтобы поставить курсор ровно туда куда ты нажал"; it had come back
 *  as select-all). `null` for a keyboard click, which has no point: then the whole title is selected. */
export function caretAt(event: MouseEvent): number | null {
  if (event.detail === 0) return null
  const root = (event.currentTarget as HTMLElement).querySelector('.goal-card__title-text')
  const doc = document as Document & {
    caretPositionFromPoint?: (x: number, y: number) => { offsetNode: Node; offset: number } | null
    caretRangeFromPoint?: (x: number, y: number) => Range | null
  }
  const position = doc.caretPositionFromPoint?.(event.clientX, event.clientY)
  const range = position ? null : doc.caretRangeFromPoint?.(event.clientX, event.clientY)
  const node = position?.offsetNode ?? range?.startContainer ?? null
  const offset = position?.offset ?? range?.startOffset ?? 0
  if (!root || !node || !root.contains(node)) return null
  const before = document.createRange()
  before.selectNodeContents(root)
  before.setEnd(node, offset)
  return before.toString().length
}
