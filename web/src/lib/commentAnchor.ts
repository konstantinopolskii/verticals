/** Pure DOM helpers for anchored comments (docs/COMMENTS_SPEC.md WP-B) — no reactivity, no store, so
 *  these are trivially unit-exercisable and reusable between `GoalDetail.tsx`'s and
 *  `DocDetail.tsx`'s body (both render markdown into the same contenteditable-toggle node,
 *  `bodyMarkdown.ts`'s own convention).
 *
 *  Two jobs: capture a selection as `{quote, prefix, suffix}` — the quote plus ~20 characters of
 *  surrounding text each side — and
 *  re-find that triple inside freshly rendered markdown so it can be wrapped in a highlight —
 *  "first occurrence; prefix/suffix disambiguate ... a quote that no longer matches renders no
 *  highlight ... never crash, never guess" (COMMENTS_SPEC.md WP-B). This file owns both halves so
 *  the round trip (capture now, re-locate later against possibly-edited text) stays one algorithm
 *  read in one place rather than two components each reimplementing "how much context is enough". */

const CONTEXT_CHARS = 20
export const HIGHLIGHT_CLASS = 'comment-highlight'

export interface AnchorContext {
  quote: string
  prefix: string
  suffix: string
}

export interface AnchoredThread {
  id: string
  quote: string
  prefix: string
  suffix: string
  /** A document's resolved comment keeps its mark, so its words can still be gone to, but its words are plain text
   *  again (`data-resolved`, docs/design/doc-comments-inline.md). */
  resolved?: boolean
}

/** Captures `{quote, prefix, suffix}` from `selection`, scoped to `container` — null when there
 *  is no selection, the selection is empty/whitespace-only, or it does not land inside
 *  `container` at all (a stray selection elsewhere on the page must never be read as this body's
 *  own anchor). `prefix`/`suffix` are read via two throwaway Ranges spanning from the container's
 *  own start/end to the selection's boundary — `Range.toString()` already flattens across
 *  whatever inline elements (`<strong>`, links, list items) sit between them, so this needs no
 *  text-node bookkeeping of its own the way `locateAnchor`/`wrapRange` below do. */
export function captureSelectionAnchor(container: HTMLElement, selection: Selection): AnchorContext | null {
  if (selection.rangeCount === 0 || selection.isCollapsed) return null
  const range = selection.getRangeAt(0)
  if (!container.contains(range.commonAncestorContainer)) return null
  const quote = range.toString()
  if (!quote.trim()) return null

  const doc = container.ownerDocument
  const preRange = doc.createRange()
  preRange.selectNodeContents(container)
  preRange.setEnd(range.startContainer, range.startOffset)
  const before = preRange.toString()

  const postRange = doc.createRange()
  postRange.selectNodeContents(container)
  postRange.setStart(range.endContainer, range.endOffset)
  const after = postRange.toString()

  return { quote, prefix: before.slice(-CONTEXT_CHARS), suffix: after.slice(0, CONTEXT_CHARS) }
}

/** Every occurrence of `quote` in `text`, scored by how much of `prefix`'s tail / `suffix`'s head
 *  actually surrounds it, highest score first (ties keep the earlier occurrence — "first
 *  occurrence" per the spec). No fuzzy-match library: an exact anchor either occurs once, occurs
 *  several times (prefix/suffix breaks the tie), or no longer occurs at all (`null` — the caller's
 *  job is then to render no highlight, never to guess at a near match). Exported mainly so this
 *  scoring can be exercised directly without a live DOM. */
export function locateAnchor(text: string, quote: string, prefix: string, suffix: string): number | null {
  if (!quote) return null
  let best: { index: number; score: number } | null = null
  let from = 0
  for (;;) {
    const index = text.indexOf(quote, from)
    if (index === -1) break
    const before = text.slice(Math.max(0, index - prefix.length), index)
    const after = text.slice(index + quote.length, index + quote.length + suffix.length)
    let score = 0
    if (prefix && before.endsWith(prefix)) score += 2
    else if (prefix && before.length > 0 && prefix.endsWith(before)) score += 1
    if (suffix && after.startsWith(suffix)) score += 2
    else if (suffix && after.length > 0 && suffix.startsWith(after)) score += 1
    if (best === null || score > best.score) best = { index, score }
    from = index + 1
  }
  return best ? best.index : null
}

export interface FlatTextNode {
  node: Text
  start: number
  end: number
}

/** Every text node under `container`, in document order, alongside its offset range in the
 *  concatenation of all of them — the same "one string, one walk" shape `captureSelectionAnchor`
 *  gets for free from `Range.toString()`, built by hand here because `wrapRange` below needs the
 *  actual `Text` node objects to split and wrap, not just their combined content. */
function flattenTextNodes(container: HTMLElement): { text: string; nodes: FlatTextNode[] } {
  const walker = container.ownerDocument.createTreeWalker(container, NodeFilter.SHOW_TEXT)
  const nodes: FlatTextNode[] = []
  let text = ''
  let current = walker.nextNode()
  while (current) {
    const node = current as Text
    const start = text.length
    text += node.nodeValue ?? ''
    nodes.push({ node, start, end: text.length })
    current = walker.nextNode()
  }
  return { text, nodes }
}

/** Wraps the flattened-text range `[start, end)` in one mark (made by `make`) PER TEXT NODE it spans, rather than one
 *  `Range.surroundContents()` — one <span class="highlight"> per text node, never one span across
 *  block boundaries — and the only way to avoid `surroundContents`' own restriction against a range
 *  that partially contains a non-Text node (a quote spanning into/out of a `<strong>` would throw
 *  on the single-range approach). `node.splitText` inserts its return value as the next DOM
 *  sibling in place, so the two splits below (tail first, then head) leave the untouched-before
 *  and untouched-after portions of each node exactly where they were — only the matched slice
 *  gets pulled out and wrapped. Several ranges over one list of nodes are wrapped last range first: a split shortens
 *  its node to the part before it, so the offsets of the ranges before it hold (`docChanges.ts` does). */
export function wrapRange(nodes: FlatTextNode[], start: number, end: number, make: () => HTMLElement): void {
  for (const entry of nodes) {
    if (entry.end <= start || entry.start >= end) continue
    const localStart = Math.max(0, start - entry.start)
    const localEnd = Math.min(entry.node.length, end - entry.start)
    if (localStart >= localEnd) continue
    if (localEnd < entry.node.length) entry.node.splitText(localEnd) // leaves the tail as a sibling
    const target = localStart > 0 ? entry.node.splitText(localStart) : entry.node
    const mark = make()
    target.replaceWith(mark)
    mark.append(target)
  }
}

function commentMark(doc: Document, thread: AnchoredThread): HTMLElement {
  const mark = doc.createElement('mark')
  mark.className = HIGHLIGHT_CLASS
  mark.dataset.threadId = thread.id
  if (thread.resolved) mark.dataset.resolved = 'true'
  return mark
}

/** Removes every highlight mark this module has previously added, folding its text back into the
 *  surrounding node (`Node.normalize()` re-merges adjacent text nodes so a later `locateAnchor`
 *  walk sees plain, unfragmented text again — otherwise every re-render would leave the tree one
 *  text-node split deeper than the last). Safe to call on a container with no highlights at all. */
export function clearHighlights(container: HTMLElement): void {
  const marks = container.querySelectorAll<HTMLElement>(`mark.${HIGHLIGHT_CLASS}`)
  for (const mark of Array.from(marks)) {
    const parent = mark.parentNode
    if (!parent) continue
    while (mark.firstChild) parent.insertBefore(mark.firstChild, mark)
    parent.removeChild(mark)
  }
  container.normalize()
}

/** The whole highlight pass for one render: clears whatever marks are already there (a stale set
 *  from the previous paint — a thread may have resolved, a new one may have arrived, the body
 *  text itself may have changed), then re-locates and re-wraps each `thread`'s quote against the
 *  CURRENT text. A thread whose quote no longer occurs anywhere is silently skipped — it still
 *  shows in the panel by construction (the panel reads from `threads`, not from highlight state),
 *  it just paints no mark in the body (COMMENTS_SPEC.md WP-B: "never crash, never guess"). */
export function applyAnchorHighlights(container: HTMLElement, threads: AnchoredThread[]): void {
  clearHighlights(container)
  for (const thread of threads) {
    if (!thread.quote) continue
    const { text, nodes } = flattenTextNodes(container)
    const start = locateAnchor(text, thread.quote, thread.prefix, thread.suffix)
    if (start === null) continue
    wrapRange(nodes, start, start + thread.quote.length, () => commentMark(container.ownerDocument, thread))
  }
}
