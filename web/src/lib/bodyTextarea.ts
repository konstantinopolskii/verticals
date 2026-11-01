import { renderBodyElement, serializeBodyElement } from './bodyMarkdown'

const HISTORY_DELAY_MS = 1000
const HISTORY_LIMIT = 100

type Snapshot = { body: string; start: number; end: number }
type History = {
  undo: Snapshot[]
  redo: Snapshot[]
  lastRecordedAt: number
  forceBoundary: boolean
  skipBeforeInput: boolean
}

const histories = new WeakMap<HTMLElement, History>()

function historyFor(element: HTMLElement): History {
  let history = histories.get(element)
  if (!history) {
    history = {
      undo: [], redo: [], lastRecordedAt: -Infinity, forceBoundary: false, skipBeforeInput: false,
    }
    histories.set(element, history)
  }
  return history
}

function textOffset(root: HTMLElement, container: Node, offset: number): number {
  const range = root.ownerDocument.createRange()
  range.selectNodeContents(root)
  try {
    range.setEnd(container, offset)
  } catch {
    return root.textContent?.length ?? 0
  }
  return range.cloneContents().textContent?.length ?? 0
}

function selectionOffsets(root: HTMLElement): { start: number; end: number } {
  const selection = root.ownerDocument.getSelection()
  if (!selection?.rangeCount) {
    const end = root.textContent?.length ?? 0
    return { start: end, end }
  }
  const range = selection.getRangeAt(0)
  if (!root.contains(range.startContainer) || !root.contains(range.endContainer)) {
    const end = root.textContent?.length ?? 0
    return { start: end, end }
  }
  return {
    start: textOffset(root, range.startContainer, range.startOffset),
    end: textOffset(root, range.endContainer, range.endOffset),
  }
}

function snapshot(root: HTMLElement): Snapshot {
  return { body: serializeBodyElement(root), ...selectionOffsets(root) }
}

function pointAtOffset(root: HTMLElement, wanted: number): { node: Node; offset: number } {
  const walker = root.ownerDocument.createTreeWalker(root, NodeFilter.SHOW_TEXT)
  let remaining = Math.max(0, wanted)
  let last: Text | null = null
  while (walker.nextNode()) {
    const text = walker.currentNode as Text
    last = text
    if (remaining <= text.data.length) return { node: text, offset: remaining }
    remaining -= text.data.length
  }
  if (last) return { node: last, offset: last.data.length }
  const target = root.querySelector('h1, h2, h3, h4, h5, h6, p, li, th, td') ?? root
  return { node: target, offset: 0 }
}

function restoreSelection(root: HTMLElement, start: number, end: number): void {
  const selection = root.ownerDocument.getSelection()
  if (!selection) return
  const first = pointAtOffset(root, start)
  const last = pointAtOffset(root, end)
  const range = root.ownerDocument.createRange()
  range.setStart(first.node, first.offset)
  range.setEnd(last.node, last.offset)
  selection.removeAllRanges()
  selection.addRange(range)
}

function emitInput(root: HTMLElement, inputType: string): void {
  root.dispatchEvent(new InputEvent('input', { bubbles: true, inputType }))
}

function restore(root: HTMLElement, state: Snapshot, inputType: 'historyUndo' | 'historyRedo'): void {
  renderBodyElement(root, state.body)
  restoreSelection(root, state.start, state.end)
  emitInput(root, inputType)
}

function recordBeforeInput(root: HTMLElement, inputType: string): void {
  const history = historyFor(root)
  const now = performance.now()
  const mergeable = /^(insertText|insertCompositionText|deleteContent)/.test(inputType)
  if (history.forceBoundary || !mergeable || now - history.lastRecordedAt > HISTORY_DELAY_MS) {
    history.undo.push(snapshot(root))
    if (history.undo.length > HISTORY_LIMIT) history.undo.shift()
    history.lastRecordedAt = now
  }
  history.forceBoundary = false
  history.redo.length = 0
}

/**
 * Contenteditable still receives programmatic list/format/paste rewrites. Keep explicit history:
 * deterministic 1000ms/100-group coalescing survives those rewrites; native history does not.
 */
export function resetBodyHistory(root: HTMLElement): void {
  histories.delete(root)
}

export function handleBodyBeforeInput(event: InputEvent): void {
  const root = event.currentTarget as HTMLElement
  const history = historyFor(root)
  if (history.skipBeforeInput) {
    history.skipBeforeInput = false
    return
  }
  recordBeforeInput(root, event.inputType)
}

function handleHistoryShortcut(event: KeyboardEvent, root: HTMLElement): boolean {
  const mod = event.metaKey || event.ctrlKey
  const undo = mod && event.key.toLowerCase() === 'z' && !event.shiftKey
  const redo = mod && ((event.key.toLowerCase() === 'z' && event.shiftKey) || event.key.toLowerCase() === 'y')
  if (!undo && !redo) return false
  event.preventDefault()
  const history = historyFor(root)
  const source = undo ? history.undo : history.redo
  const target = undo ? history.redo : history.undo
  const state = source.pop()
  if (state) {
    target.push(snapshot(root))
    restore(root, state, undo ? 'historyUndo' : 'historyRedo')
  }
  history.forceBoundary = true
  history.lastRecordedAt = -Infinity
  return true
}

function runProgrammaticEdit(root: HTMLElement, inputType: string, edit: () => void): void {
  const history = historyFor(root)
  history.forceBoundary = true
  recordBeforeInput(root, inputType)
  history.skipBeforeInput = true
  edit()
  history.skipBeforeInput = false
  history.forceBoundary = true
  emitInput(root, inputType)
}

function handleChecklistEnter(root: HTMLElement): boolean {
  const selection = root.ownerDocument.getSelection()
  if (!selection?.isCollapsed || !selection.anchorNode) return false
  const anchor = selection.anchorNode instanceof Element
    ? selection.anchorNode
    : selection.anchorNode.parentElement
  const block = anchor?.closest('p, div')
  if (!block || block.parentElement !== root || block !== root.lastElementChild) return false
  const afterCaret = root.ownerDocument.createRange()
  afterCaret.selectNodeContents(block)
  afterCaret.setStart(selection.anchorNode, selection.anchorOffset)
  if (afterCaret.toString()) return false
  const line = serializeBodyElement(root).split('\n').at(-1) ?? ''
  const match = /^(\s*)(?:\[ ?\]|\[x\])\s+(.*)$/.exec(line)
  if (!match) return false
  const [, indent, content] = match
  runProgrammaticEdit(root, 'insertParagraph', () => {
    if (!content) {
      const breaks = block.querySelectorAll('br')
      const lastBreak = breaks.item(breaks.length - 1)
      if (lastBreak) {
        let node = lastBreak.nextSibling
        while (node) {
          const next = node.nextSibling
          node.remove()
          node = next
        }
        setCaretAfter(lastBreak)
      } else {
        block.replaceChildren()
        const range = root.ownerDocument.createRange()
        range.setStart(block, 0)
        range.collapse(true)
        selection.removeAllRanges()
        selection.addRange(range)
      }
      return
    }
    const range = selection.getRangeAt(0)
    const fragment = root.ownerDocument.createDocumentFragment()
    fragment.append(root.ownerDocument.createElement('br'))
    const marker = root.ownerDocument.createTextNode(`${indent}[ ] `)
    fragment.append(marker)
    range.insertNode(fragment)
    setCaretAfter(marker)
  })
  return true
}

function handleTab(root: HTMLElement, outdent: boolean): void {
  const selection = root.ownerDocument.getSelection()
  const anchor = selection?.anchorNode instanceof Element
    ? selection.anchorNode
    : selection?.anchorNode?.parentElement
  const item = anchor?.closest('li')
  if (item && root.contains(item)) {
    runProgrammaticEdit(root, outdent ? 'formatOutdent' : 'formatIndent', () => {
      const current = Number.parseInt(item.dataset.mdIndent ?? '0', 10) || 0
      const next = outdent ? Math.max(0, current - 2) : current + 2
      if (next) item.dataset.mdIndent = String(next)
      else delete item.dataset.mdIndent
    })
    return
  }
  if (!outdent) {
    runProgrammaticEdit(root, 'insertText', () => insertPlainText(root, '\t'))
  }
}

function insertLineBreak(root: HTMLElement): void {
  const selection = root.ownerDocument.getSelection()
  if (!selection?.rangeCount) return
  root.querySelectorAll('br[data-body-caret]').forEach((node) => node.remove())
  const range = selection.getRangeAt(0)
  range.deleteContents()
  const lineBreak = root.ownerDocument.createElement('br')
  const caretBreak = root.ownerDocument.createElement('br')
  caretBreak.dataset.bodyCaret = ''
  range.insertNode(caretBreak)
  range.insertNode(lineBreak)
  range.setStartAfter(lineBreak)
  range.collapse(true)
  selection.removeAllRanges()
  selection.addRange(range)
}

export function handleBodyKeydown(event: KeyboardEvent): void {
  const root = event.currentTarget as HTMLElement
  if (handleHistoryShortcut(event, root)) return
  if (event.key === 'Enter') {
    if (handleChecklistEnter(root)) {
      event.preventDefault()
      return
    }
    const selection = root.ownerDocument.getSelection()
    const anchor = selection?.anchorNode instanceof Element
      ? selection.anchorNode
      : selection?.anchorNode?.parentElement
    const item = anchor?.closest('li')
    if (selection?.isCollapsed && item && root.contains(item)) {
      const afterCaret = root.ownerDocument.createRange()
      afterCaret.selectNodeContents(item)
      afterCaret.setStart(selection.anchorNode as Node, selection.anchorOffset)
      if (!afterCaret.toString()) {
        // Chromium exits an empty item and continues a non-empty item. execCommand keeps that
        // native list topology while making Shift-Enter follow the textarea's same path.
        event.preventDefault()
        runProgrammaticEdit(root, 'insertParagraph', () => {
          document.execCommand('insertParagraph')
        })
        return
      }
    }
    if (item && root.contains(item)) return
    event.preventDefault()
    runProgrammaticEdit(root, 'insertParagraph', () => insertLineBreak(root))
    return
  }
  if (event.key === 'Tab') {
    event.preventDefault()
    handleTab(root, event.shiftKey)
    return
  }
  const mod = event.metaKey || event.ctrlKey
  const key = event.key.toLowerCase()
  if (!mod || (key !== 'b' && key !== 'i')) return
  event.preventDefault()
  runProgrammaticEdit(root, key === 'b' ? 'formatBold' : 'formatItalic', () => {
    document.execCommand(key === 'b' ? 'bold' : 'italic')
  })
}

function setCaretAfter(node: Node): void {
  const document = node.ownerDocument
  const selection = document?.getSelection()
  if (!document || !selection) return
  const range = document.createRange()
  range.setStartAfter(node)
  range.collapse(true)
  selection.removeAllRanges()
  selection.addRange(range)
}

function setCaretIn(node: Node): void {
  node.ownerDocument?.getSelection()?.collapse(node, 0)
}

const isBlock = (node: Node): boolean => node instanceof HTMLElement && /^(P|DIV|UL|OL|H[1-6]|PRE|TABLE)$/.test(node.tagName)
const endsLine = (node: Node): boolean => isBlock(node)
  || (node instanceof HTMLBRElement && !node.hasAttribute('data-body-caret'))

/** The caret's line: the nodes between the line breaks around it, in its paragraph or right in the root. */
function caretLine(root: HTMLElement): { text: string; replaceWith: (block: HTMLElement) => void } | null {
  const selection = root.ownerDocument.getSelection()
  if (!selection?.isCollapsed || !selection.anchorNode) return null
  const anchor = selection.anchorNode instanceof Element ? selection.anchorNode : selection.anchorNode.parentElement
  const paragraph = anchor?.closest('p, div')
  const container = paragraph?.parentElement === root ? paragraph : root
  let node: Node | null = selection.anchorNode
  while (node && node.parentNode !== container) node = node.parentNode
  if (!node || isBlock(node)) return null
  let first = node
  while (first.previousSibling && !endsLine(first.previousSibling)) first = first.previousSibling
  let last = node
  while (last.nextSibling && !endsLine(last.nextSibling)) last = last.nextSibling
  const line = root.ownerDocument.createRange()
  line.setStartBefore(first)
  line.setEndAfter(last)
  return {
    text: line.toString().replace(/\u00a0/g, ' '),
    replaceWith(block) {
      const before = first.previousSibling
      const after = last.nextSibling
      const rest = root.ownerDocument.createElement('p')
      rest.className = 't-body'
      if (after && !isBlock(after)) {
        while (after.nextSibling && !isBlock(after.nextSibling)) rest.append(after.nextSibling)
        after.remove()
      }
      if (before && !isBlock(before)) before.remove()
      line.deleteContents()
      if (container === root) line.insertNode(block)
      else if (container.hasChildNodes()) container.after(block)
      else container.replaceWith(block)
      if (rest.hasChildNodes()) block.after(rest)
    },
  }
}

function applyListShortcut(root: HTMLElement): boolean {
  const line = caretLine(root)
  const ordered = line?.text === '1. '
  if (!line || (!ordered && line.text !== '- ' && line.text !== '* ')) return false
  const list = root.ownerDocument.createElement(ordered ? 'ol' : 'ul')
  list.className = 't-list'
  const item = root.ownerDocument.createElement('li')
  item.append(root.ownerDocument.createElement('br'))
  list.append(item)
  line.replaceWith(list)
  setCaretIn(item)
  return true
}

function applyHeadingShortcut(root: HTMLElement): boolean {
  const line = caretLine(root)
  const match = line && /^(#{1,6}) $/.exec(line.text)
  if (!line || !match) return false
  const heading = root.ownerDocument.createElement(`h${match[1].length}`)
  heading.className = 'goal-detail__body-heading'
  heading.append(root.ownerDocument.createElement('br'))
  line.replaceWith(heading)
  setCaretIn(heading)
  return true
}

function applyInlineShortcut(root: HTMLElement): boolean {
  const selection = root.ownerDocument.getSelection()
  if (!selection?.isCollapsed || !(selection.anchorNode instanceof Text)) return false
  const textNode = selection.anchorNode
  const offset = selection.anchorOffset
  const before = textNode.data.slice(0, offset)
  const strong = /\*\*([^*\n]+)\*\*$/.exec(before)
  const code = /`([^`\n]+)`$/.exec(before)
  const emphasisMatch = /([*_])([^*_\n]+)\1$/.exec(before)
  const emphasis = emphasisMatch
    && !(emphasisMatch.index > 0 && before[emphasisMatch.index - 1] === emphasisMatch[1])
    ? emphasisMatch
    : null
  const match = strong ?? code ?? emphasis
  if (!match) return false
  const tag = strong ? 'strong' : code ? 'code' : 'em'
  const content = strong ? strong[1] : code ? code[1] : emphasis?.[2] ?? ''
  const start = offset - match[0].length
  const range = root.ownerDocument.createRange()
  range.setStart(textNode, start)
  range.setEnd(textNode, offset)
  range.deleteContents()
  const element = root.ownerDocument.createElement(tag)
  if (tag === 'code') element.className = 't-code'
  element.textContent = content
  range.insertNode(element)
  setCaretAfter(element)
  return true
}

/** Apply Markdown shortcuts after browser inserted closing delimiter/line-start space. */
export function normalizeBodyInput(event: InputEvent): void {
  const root = event.currentTarget as HTMLElement
  if (event.inputType !== 'insertText') return
  if (event.data === ' ') {
    if (!applyHeadingShortcut(root)) applyListShortcut(root)
  }
  else if (event.data === '*' || event.data === '_' || event.data === '`') applyInlineShortcut(root)
}

function insertPlainText(root: HTMLElement, text: string): void {
  if (document.execCommand('insertText', false, text)) return
  const selection = root.ownerDocument.getSelection()
  if (!selection?.rangeCount) return
  const range = selection.getRangeAt(0)
  range.deleteContents()
  const node = root.ownerDocument.createTextNode(text)
  range.insertNode(node)
  setCaretAfter(node)
}

/** Plain-text clipboard only. Re-rendering lets Markdown-looking text enter supported WYSIWYG. */
export function handleBodyPaste(event: ClipboardEvent): void {
  const text = event.clipboardData?.getData('text/plain')
  if (text === undefined) return
  event.preventDefault()
  const root = event.currentTarget as HTMLElement
  const before = selectionOffsets(root).start
  runProgrammaticEdit(root, 'insertFromPaste', () => {
    insertPlainText(root, text)
    const body = serializeBodyElement(root)
    renderBodyElement(root, body)
    restoreSelection(root, before + text.length, before + text.length)
  })
}
