/* The Documents desk: every document as a page, in stacks by the goal it accumulates
   under, grouped by value in the board's order, and first the documents no goal holds, under "No goal" with the board's
   grey square, one stack for each age. A click on a stack lays its pages out over the desk; a click on a page opens it
   as a window; Esc puts them back (App.tsx, where Esc peels the layers in order). The field narrows the desk as it narrows the board.

   The stack opens in one movement per step: the desk dims first, in 150 ms; the laid-out pages grow from where the stack
   lies, 95 % to 100 % in 300 ms, fading in from 60 ms. Closing, the pages go first (120 ms) and the dim lifts last, by
   240 ms. The title and × stay at the top while the desk scrolls (DeskHead). */
import type { KeyboardEvent as ReactKeyboardEvent, MouseEvent as ReactMouseEvent } from 'react'
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from '../reactivity'
import { AppIcon } from './AppIcon'
import { DeskHead } from './DeskHead'
import { DocPage } from './DocPage'
import { store } from '../store'
import { count, desk, docMatches, groups, loadDesk, openStack, shortDay } from '../lib/docsDesk'
import { devPaletteFor, rgbaFromHex } from '../lib/devPalette'
import { goalWashInk } from '../lib/goalColor'
import { openWindow } from '../lib/windows'
import { Transition } from '../Transition'
import { cx, fallthrough, sx, valueOf } from '../bind'
import { tracked } from '../tracked'
import { listen, useSetup } from '../setup'
import './docsDesk.css'

export const DocsDesk = tracked(function DocsDesk(attrs: Record<string, unknown>) {
  const s = useSetup({}, () => {
    const data = computed(() => desk.data)

    function mark(color: string | null): string {
      if (!color) return '#e5e5e5'
      const box = devPaletteFor(color)?.box
      return box ? rgbaFromHex(box.color, box.opacity) : `rgb(${goalWashInk(color).washRgb})`
    }
    const behind = (n: number) => (n >= 6 ? 2 : n >= 2 ? 1 : 0)

    /* Where the clicked stack lies: the laid-out pages grow from its centre. */
    let from = { x: 0, y: 0 }
    function openStackAt(key: string, event: Pick<Event, 'currentTarget'>): void {
      const r = ((event.currentTarget as Element).querySelector('.doc-page') ?? (event.currentTarget as Element)).getBoundingClientRect()
      from = { x: r.left + r.width / 2, y: r.top + r.height / 2 }
      desk.open = key
    }
    function onOpenEnter(el: Element): void {
      const layer = el.querySelector<HTMLElement>('.docs-open__layer')
      if (!layer) return
      const r = layer.getBoundingClientRect()
      layer.style.transformOrigin = `${from.x - r.left}px ${from.y - r.top}px`
    }

    function openDoc(id: string, event: Pick<Event, 'currentTarget'>): void {
      const doc = data.value?.docs[id]
      openWindow({ kind: 'doc', target: id, title: doc?.title || doc?.path || 'Document' }, event.currentTarget as Element)
    }
    // A new document: its path, folders by "/", committed with ↵.
    const creating = ref(false)
    const draft = ref('')
    const draftInput = ref<HTMLInputElement | null>(null)
    function startCreate(): void {
      creating.value = true
      draft.value = ''
      void nextTick(() => draftInput.value?.focus())
    }
    listen(draftInput, 'blur', () => {
      if (!draft.value.trim()) creating.value = false
    })
    async function commitCreate(): Promise<void> {
      const path = draft.value.trim()
      if (!path) return
      if (await store.createDoc(path.endsWith('.md') ? path : `${path}.md`)) {
        // The new document opens as a window over the desk, as any page does; the desk shows it in its stack.
        const id = store.state.docs.currentId
        const title = store.state.docs.current?.title || store.state.docs.current?.path || 'Document'
        store.closeDoc()
        creating.value = false
        if (id) openWindow({ kind: 'doc', target: id, title }, draftInput.value)
        void loadDesk()
      }
    }

    onMounted(() => {
      void loadDesk()
    })
    onBeforeUnmount(() => {
      desk.open = null
    })
    return { data, mark, behind, openStackAt, onOpenEnter, openDoc, creating, draft, draftInput, startCreate, commitCreate }
  })

  function onDraftKey(event: ReactKeyboardEvent<HTMLInputElement>) {
    if (event.key === 'Enter') {
      event.preventDefault()
      void s.commitCreate()
    } else if (event.key === 'Escape') {
      event.stopPropagation()
      event.preventDefault()
      s.creating.value = false
    }
  }
  function closeOnSelf(event: ReactMouseEvent) {
    if (event.target !== event.currentTarget) return
    desk.open = null
  }

  const data = s.data.value
  const shown = openStack.value
  const all = groups.value
  return (
    <div {...fallthrough({ className: 'docs-desk', 'data-role': 'docs-desk' }, attrs)}>
      <DeskHead title="Documents">
        <button type="button" className="docs-desk__new" data-role="docs-new-trigger" aria-label="New document"
          onClick={() => (s.creating.value ? (s.creating.value = false) : s.startCreate())}>
          <AppIcon name="plus" size={16} />
        </button>
        {s.creating.value ? (
          <input
            className="docs-desk__new-input"
            data-role="docs-new-input"
            placeholder="folder/document-name"
            {...valueOf(s.draft.value, (event) => { s.draft.value = event.currentTarget.value }, s.draftInput)}
            onKeyDown={onDraftKey}
          />
        ) : null}
      </DeskHead>
      {all.map((group) => (
        <section key={group.key} className="docs-desk__group" data-group={group.key}>
          <h2 className="docs-desk__value"><i style={sx({ background: s.mark(group.color) })} aria-hidden="true"></i>{group.name}<span>{group.count}</span></h2>
          <div className="docs-desk__stacks">
            {group.stacks.map((stack) => {
              const n = s.behind(stack.docs.length)
              return (
                <button
                  key={stack.key}
                  type="button"
                  className={cx('docs-stack', { 'docs-stack--off': stack.matches === 0 })}
                  data-stack={stack.key}
                  onClick={(event) => s.openStackAt(stack.key, event)}
                >
                  <span className="docs-stack__pages" style={sx({ paddingTop: `${4 * n}px` })}>
                    {Array.from({ length: n }, (_, k) => k + 1).map((i) => (
                      <i key={i} className="docs-stack__behind" style={sx({ left: `${4 * i}px`, top: `${4 * (n - i)}px` })}></i>
                    ))}
                    {data ? <DocPage doc={data.docs[stack.docs.find(docMatches) ?? stack.docs[0]!]!} width={120} /> : null}
                  </span>
                  <span className="docs-stack__name">{stack.name}</span>
                  <span className="docs-stack__sub">{stack.matches !== null ? <><b>{stack.matches}</b>{` of ${stack.docs.length}`}</> : stack.sub}</span>
                </button>
              )
            })}
          </div>
        </section>
      ))}
      {desk.loaded && !all.length ? <p className="docs-desk__empty">No documents yet. The plus above makes one.</p> : null}

      <Transition name="docs-open" duration={{ enter: 300, leave: 240 }} onEnter={s.onOpenEnter}>
        {shown && data ? (
          <div className="docs-open" data-role="docs-open">
            <div className="docs-open__veil" aria-hidden="true"></div>
            <div className="docs-open__layer" onClick={closeOnSelf}>
              <h2 className="docs-open__head" onClick={closeOnSelf}>{shown.name}<span>{count(shown.docs.length)}</span></h2>
              <div className="docs-open__pages" onClick={closeOnSelf}>
                {shown.docs.map((id) => (
                  <button
                    key={id}
                    type="button"
                    className={cx('docs-open__page', { 'docs-open__page--off': !docMatches(id) })}
                    data-doc-id={id}
                    onClick={(event) => s.openDoc(id, event)}
                  >
                    <DocPage doc={data.docs[id]!} width={150} />
                    <span className="docs-stack__name">{data.docs[id]!.title || data.docs[id]!.path}</span>
                    <span className="docs-stack__sub">{shortDay(data.docs[id]!.updated_at)}</span>
                  </button>
                ))}
              </div>
            </div>
          </div>
        ) : null}
      </Transition>
    </div>
  )
})
