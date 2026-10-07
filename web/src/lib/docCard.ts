// A document as its page needs it (DocPage.vue): title, path, the top of the body and when it was edited. Read once per
// document for the chips of messages and of the field (DocChip.vue), and read again when the document changes.
import { reactive } from 'vue'
import { getDoc, type DeskDoc } from './api'

export type DocCard = Pick<DeskDoc, 'id' | 'title' | 'path' | 'excerpt' | 'created_at' | 'updated_at'>

const cards = reactive(new Map<string, DocCard | null>())

/** The document's card, or null while it is read (or when it is gone). */
export function docCard(id: string): DocCard | null {
  if (!cards.has(id)) {
    cards.set(id, null)
    void getDoc(id)
      .then((doc) => cards.set(id, { id: doc.id, title: doc.title, path: doc.path, excerpt: doc.body.slice(0, 1500),
        created_at: doc.created_at, updated_at: doc.updated_at }))
      .catch(() => undefined)
  }
  return cards.get(id) ?? null
}

/** A card already read elsewhere (the Documents desk): no second read. */
export function knowDocCard(card: DocCard): void {
  cards.set(card.id, card)
}

if (typeof window !== 'undefined') {
  window.addEventListener('verticals:doc-edited', (event) => {
    const id = (event as CustomEvent<{ id?: string }>).detail?.id
    if (id && cards.has(id)) { cards.delete(id); void docCard(id) }
  })
}
