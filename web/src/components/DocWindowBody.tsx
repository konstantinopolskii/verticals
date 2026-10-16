/* A document in a window: the document as the Docs view draws it, opened at the
   part the answer points to; a link to a deleted one says so in words. It fills the window's one-line head: the facts
   its page shows on the desk, its versions, and its title once the title has scrolled away. A source carries its state
   over its title (SourceStrip). */
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch, watchEffect } from '../reactivity'
import { DocDetail } from './DocDetail'
import { SourceStrip } from './SourceStrip'
import { ApiError, getDoc, type DocDetail as DocWire } from '../lib/api'
import { windows } from '../lib/windows'
import { shortDay, stackGoalOf } from '../lib/docsDesk'
import { isSource } from '../lib/sources'
import { bindRef, fallthrough } from '../bind'
import { tracked } from '../tracked'
import { useSetup } from '../setup'
import './docWindowBody.css'

interface Props {
  id: string
  part?: string
}

export const DocWindowBody = tracked(function DocWindowBody({ id, part, ...attrs }: Props & Record<string, unknown>) {
  const s = useSetup({ id, part }, (props) => {
    const root = ref<HTMLElement | null>(null)
    const doc = ref<DocWire | null>(null)
    const gone = ref(false)

    async function load(): Promise<void> {
      gone.value = false
      try {
        doc.value = await getDoc(props.id)
        const win = windows.list.find((w) => w.kind === 'doc' && w.target === props.id)
        if (win) win.title = doc.value.title || doc.value.path
      } catch (error) {
        doc.value = null
        gone.value = error instanceof ApiError && error.status === 404
      }
      await nextTick()
      showPart()
    }

    /** The part the answer used: the first heading or line holding its words, scrolled to the window's top. */
    function showPart(): void {
      const words = props.part?.trim().toLocaleLowerCase()
      if (!words || !root.value) return
      const found = [...root.value.querySelectorAll<HTMLElement>('h1, h2, h3, h4, p, li, td')]
        .find((el) => el.textContent?.toLocaleLowerCase().includes(words))
      found?.scrollIntoView({ block: 'start' })
    }

    const win = computed(() => windows.list.find((w) => w.kind === 'doc' && w.target === props.id) ?? null)

    /* The facts: the goal it lies under on the desk and when it was last edited. */
    watchEffect(() => {
      const w = win.value
      const d = doc.value
      if (!w || !d) return
      const place = stackGoalOf(d.id)
      w.facts = [...(place ? [place] : []), `edited ${shortDay(d.updated_at)}`]
      w.versions = d.revision
    })

    /* The title in the head once the document's own has scrolled out of the window's top. */
    let titleWatch: IntersectionObserver | null = null
    function watchTitle(): void {
      titleWatch?.disconnect()
      const title = root.value?.querySelector('[data-role="doc-title"]')
      const scroller = root.value?.closest('.vt-window__body')
      if (!title || !scroller || typeof IntersectionObserver === 'undefined') return
      titleWatch = new IntersectionObserver(([entry]) => {
        if (win.value && entry) win.value.titled = !entry.isIntersecting && entry.boundingClientRect.top < (entry.rootBounds?.top ?? 0)
      }, { root: scroller })
      titleWatch.observe(title)
    }
    watch(doc, () => void nextTick(watchTitle))
    onBeforeUnmount(() => titleWatch?.disconnect())

    /* A save of this document from this window (or anywhere): the window shows the saved copy, not the one it opened. */
    function onEdited(event: Event): void {
      const detail = (event as CustomEvent<{ doc?: DocWire; linksFresh?: boolean }>).detail
      const fresh = detail?.doc
      if (!fresh || fresh.id !== props.id || !doc.value) return
      doc.value = detail.linksFresh ? fresh : { ...fresh, linked_goals: doc.value.linked_goals }
    }

    onMounted(() => {
      void load()
      window.addEventListener('verticals:doc-edited', onEdited)
    })
    onBeforeUnmount(() => window.removeEventListener('verticals:doc-edited', onEdited))
    watch(() => props.id, load)
    watch(() => props.part, () => void nextTick(showPart))
    return { root, doc, gone }
  })
  const doc = s.doc.value
  return (
    <div {...fallthrough({ ref: bindRef(s.root), className: 'doc-window', 'data-role': 'doc-window' }, attrs)}>
      {doc && isSource(doc.id) ? <SourceStrip id={doc.id} /> : null}
      {doc ? (
        <DocDetail key={doc.id} doc={doc} inWindow />
      ) : s.gone.value ? (
        <p className="doc-window__note" data-role="doc-gone">This document was deleted</p>
      ) : (
        <p className="doc-window__note">Opening…</p>
      )}
    </div>
  )
})
