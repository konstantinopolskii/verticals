/** IR-09's deliberately bounded Markdown model. Unsupported syntax stays ordinary text.
 *  A link is external (`http(s):`/`mailto:`, the S-72 allowlist; the browser follows it) or
 *  in-app (`goal:<id>`/`doc:<path>`; `lib/docsView.ts::followBodyLink` follows it). */
export type Run =
  | { kind: 'text' | 'strong' | 'em' | 'code'; text: string }
  | { kind: 'link'; text: string; href: string }
  | { kind: 'break' }

export type ListItem = { runs: Run[]; indent: number }
export type Block =
  | { tag: 'p'; runs: Run[] }
  | { tag: 'heading'; level: number; runs: Run[] }
  | { tag: 'ul' | 'ol'; items: ListItem[] }
  | { tag: 'table'; rows: Run[][][] }

const CONTROL_OR_SPACE_RE = /[\s\x00-\x1f\x7f-\x9f]/g
const ALLOWED_SCHEME_RE = /^(https?:|mailto:)/
/** Mirrors `core/docs.py::_LINK_DEST_RE` (`(goal|doc):([^)\s]+)`, lower-case only): what the
 *  server would index as a link is what renders as one, nothing more and nothing less. */
const INTERNAL_LINK_RE = /^(goal|doc):([^\s)]+)$/

export type InternalLink = { kind: 'goal' | 'doc'; target: string }

export function internalLinkTarget(href: string): InternalLink | null {
  const match = INTERNAL_LINK_RE.exec(href)
  if (!match) return null
  return { kind: match[1] as InternalLink['kind'], target: match[2] }
}
/** Underscore emphasis is fenced off from INTRAWORD underscores, the way CommonMark fences it.
 *  Without the fence `_(…)_` happily spans `window.__pwned=1"> … window.__` and eats the two
 *  underscores out of an identifier — S-72's payload is exactly that string, and the scenario
 *  caught it: the body rendered `window._pwned=1`. Code is not the only thing people write with
 *  underscores in it, so the rule is the general one, not a patch for that one payload: an
 *  underscore that touches a word character on the outside opens nothing, and a run of them
 *  (`__`) is not an opener either. Asterisk emphasis keeps the simple form — `*` does not appear
 *  inside identifiers. */
const INLINE_RE =
  /\*\*([^*]+)\*\*|\*([^*]+)\*|(?<![\w_])_([^_\s][^_]*?)_(?![\w_])|`([^`]+)`|\[([^\]]+)\]\(([^)\s]+)\)/
const LIST_ITEM_RE = /^(\s*)(?:[-*+]|\d+\.)\s+(.*)$/
const ORDERED_ITEM_RE = /^\s*\d+\./
const HEADING_RE = /^(#{1,6})\s+(.*)$/
const TABLE_DIVIDER_CELL_RE = /^:?-{3,}:?$/

function splitTableRow(line: string): string[] {
  const trimmed = line.trim().replace(/^\|/, '').replace(/\|$/, '')
  const cells: string[] = []
  let cell = ''
  let escaped = false
  for (const character of trimmed) {
    if (escaped) {
      cell += character
      escaped = false
    } else if (character === '\\') {
      escaped = true
    } else if (character === '|') {
      cells.push(cell.trim())
      cell = ''
    } else {
      cell += character
    }
  }
  if (escaped) cell += '\\'
  cells.push(cell.trim())
  return cells
}

function isTableStart(lines: string[], index: number): boolean {
  if (index + 1 >= lines.length || !lines[index].includes('|')) return false
  const divider = splitTableRow(lines[index + 1])
  return divider.length > 0 && divider.every((cell) => TABLE_DIVIDER_CELL_RE.test(cell))
}

export function cleanHref(raw: string): string {
  return raw.replace(CONTROL_OR_SPACE_RE, '')
}

export function isAllowedHref(cleaned: string): boolean {
  return ALLOWED_SCHEME_RE.test(cleaned.toLowerCase())
    || internalLinkTarget(cleaned) !== null
    || cleaned.startsWith('/')
    || cleaned.startsWith('#')
}

/** Null for no anchor or an external one — the browser follows those itself (S-72). */
export function internalLinkOf(anchor: HTMLAnchorElement | null): InternalLink | null {
  return anchor ? internalLinkTarget(cleanHref(anchor.getAttribute('href') ?? '')) : null
}

export function tokenizeInline(text: string): Run[] {
  const runs: Run[] = []
  let rest = text
  while (rest.length) {
    const match = INLINE_RE.exec(rest)
    if (!match) {
      runs.push({ kind: 'text', text: rest })
      break
    }
    if (match.index > 0) runs.push({ kind: 'text', text: rest.slice(0, match.index) })
    if (match[1] !== undefined) runs.push({ kind: 'strong', text: match[1] })
    else if (match[2] !== undefined) runs.push({ kind: 'em', text: match[2] })
    else if (match[3] !== undefined) runs.push({ kind: 'em', text: match[3] })
    else if (match[4] !== undefined) runs.push({ kind: 'code', text: match[4] })
    else if (match[5] !== undefined && match[6] !== undefined) {
      const href = cleanHref(match[6])
      // AC-116: rejected links remain complete literal `[label](href)` text.
      if (isAllowedHref(href)) runs.push({ kind: 'link', text: match[5], href })
      else runs.push({ kind: 'text', text: match[0] })
    }
    rest = rest.slice(match.index + match[0].length)
  }
  return runs
}

export function parseBody(body: string): Block[] {
  const lines = body.replace(/\r\n?/g, '\n').split('\n')
  const blocks: Block[] = []
  let index = 0
  while (index < lines.length) {
    if (!lines[index].trim()) {
      index++
      continue
    }
    const heading = HEADING_RE.exec(lines[index])
    if (heading) {
      blocks.push({ tag: 'heading', level: heading[1].length, runs: tokenizeInline(heading[2]) })
      index++
      continue
    }
    if (isTableStart(lines, index)) {
      const rows: Run[][][] = [splitTableRow(lines[index]).map(tokenizeInline)]
      index += 2
      while (index < lines.length && lines[index].trim() && lines[index].includes('|')) {
        rows.push(splitTableRow(lines[index]).map(tokenizeInline))
        index++
      }
      blocks.push({ tag: 'table', rows })
      continue
    }
    if (LIST_ITEM_RE.test(lines[index])) {
      const ordered = ORDERED_ITEM_RE.test(lines[index])
      const items: ListItem[] = []
      while (index < lines.length && LIST_ITEM_RE.test(lines[index])) {
        const match = LIST_ITEM_RE.exec(lines[index])
        const leading = (match?.[1] ?? '').replace(/\t/g, '  ')
        items.push({ runs: tokenizeInline(match?.[2] ?? ''), indent: leading.length })
        index++
      }
      blocks.push({ tag: ordered ? 'ol' : 'ul', items })
      continue
    }
    const runs: Run[] = []
    while (
      index < lines.length
      && lines[index].trim()
      && !HEADING_RE.test(lines[index])
      && !isTableStart(lines, index)
      && !LIST_ITEM_RE.test(lines[index])
    ) {
      if (runs.length) runs.push({ kind: 'break' })
      runs.push(...tokenizeInline(lines[index]))
      index++
    }
    blocks.push({ tag: 'p', runs })
  }
  return blocks
}

function serializeRuns(runs: Run[]): string {
  return runs.map((run) => {
    if (run.kind === 'break') return '\n'
    if (run.kind === 'strong') return `**${run.text}**`
    if (run.kind === 'em') return `*${run.text}*`
    if (run.kind === 'code') return `\`${run.text}\``
    if (run.kind === 'link') return `[${run.text}](${run.href})`
    return run.text
  }).join('')
}

function serializeTableCell(runs: Run[]): string {
  return serializeRuns(runs).replace(/\|/g, '\\|').replace(/\n/g, ' ')
}

export function serializeBlocks(blocks: Block[]): string {
  return blocks.map((block) => {
    if (block.tag === 'p') return serializeRuns(block.runs)
    if (block.tag === 'heading') return `${'#'.repeat(block.level)} ${serializeRuns(block.runs)}`
    if (block.tag === 'table') {
      const width = Math.max(1, ...block.rows.map((row) => row.length))
      const renderRow = (row: Run[][]) => {
        const cells = Array.from({ length: width }, (_, index) => (
          serializeTableCell(row[index] ?? [])
        ))
        return `| ${cells.join(' | ')} |`
      }
      const [header = [], ...rows] = block.rows
      return [renderRow(header), `| ${Array(width).fill('---').join(' | ')} |`, ...rows.map(renderRow)]
        .join('\n')
    }
    return block.items.map((item, index) => {
      const marker = block.tag === 'ol' ? `${index + 1}.` : '-'
      return `${' '.repeat(item.indent)}${marker} ${serializeRuns(item.runs)}`
    }).join('\n')
  }).join('\n\n')
}

/**
 * Canonical storage form after a render/edit cycle. Normalisations are intentional: CRLF -> LF,
 * blank runs -> one blank line, paragraph soft-breaks stay line breaks, list markers -> `-`/`1..n`,
 * underscore emphasis -> asterisks, editor NBSP -> spaces, and allowed href whitespace/control
 * bytes -> removed.
 */
export function normalizeBodyMarkdown(body: string): string {
  return serializeBlocks(parseBody(body.replace(/\u00a0/g, ' ')))
}

function appendRun(parent: HTMLElement, run: Run): void {
  const document = parent.ownerDocument
  if (run.kind === 'break') {
    parent.append(document.createElement('br'))
    return
  }
  if (run.kind === 'text') {
    parent.append(document.createTextNode(run.text))
    return
  }
  const tag = run.kind === 'link' ? 'a' : run.kind
  const element = document.createElement(tag)
  element.textContent = run.text
  if (run.kind === 'code') element.className = 't-code'
  if (run.kind === 'link') {
    // Both kinds keep the literal destination in `href`: `serializeInlineNode` reads it back on edit.
    element.setAttribute('href', run.href)
    const internal = internalLinkTarget(run.href)
    if (internal) {
      element.dataset.linkKind = internal.kind
      element.dataset.linkTarget = internal.target
    } else {
      element.setAttribute('target', '_blank')
      element.setAttribute('rel', 'noopener noreferrer')
    }
  }
  parent.append(element)
}

/** Safe DOM renderer shared by Vue entry and programmatic history restores. Never uses innerHTML. */
export function renderBodyElement(root: HTMLElement, body: string): void {
  const document = root.ownerDocument
  const fragment = document.createDocumentFragment()
  for (const block of parseBody(body)) {
    if (block.tag === 'heading') {
      const heading = document.createElement(`h${block.level}`)
      heading.className = 'goal-detail__body-heading'
      for (const run of block.runs) appendRun(heading, run)
      fragment.append(heading)
      continue
    }
    if (block.tag === 'table') {
      const table = document.createElement('table')
      table.className = 'goal-detail__body-table'
      const [header = [], ...rows] = block.rows
      const thead = document.createElement('thead')
      const headerRow = document.createElement('tr')
      for (const cell of header) {
        const th = document.createElement('th')
        for (const run of cell) appendRun(th, run)
        headerRow.append(th)
      }
      thead.append(headerRow)
      table.append(thead)
      if (rows.length) {
        const tbody = document.createElement('tbody')
        for (const row of rows) {
          const tr = document.createElement('tr')
          for (const cell of row) {
            const td = document.createElement('td')
            for (const run of cell) appendRun(td, run)
            tr.append(td)
          }
          tbody.append(tr)
        }
        table.append(tbody)
      }
      fragment.append(table)
      continue
    }
    const element = document.createElement(block.tag)
    if (block.tag === 'p') {
      element.className = 't-body'
      for (const run of block.runs) appendRun(element, run)
    } else {
      element.className = 't-list'
      for (const item of block.items) {
        const li = document.createElement('li')
        if (item.indent) li.dataset.mdIndent = String(item.indent)
        for (const run of item.runs) appendRun(li, run)
        element.append(li)
      }
    }
    fragment.append(element)
  }
  hideRepeatedTitle(root, fragment)
  root.replaceChildren(fragment)
}

/** A leading `# X` that repeats the root's `data-hide-title` is hidden, not dropped:
 *  `serializeBodyElement` still writes it back on save. */
function hideRepeatedTitle(root: HTMLElement, fragment: DocumentFragment): void {
  const normalize = (text: string) => text.replace(/\s+/g, ' ').trim()
  const title = normalize(root.dataset.hideTitle ?? '')
  const first = fragment.firstElementChild
  if (title && first instanceof HTMLHeadingElement && first.tagName === 'H1' && normalize(first.textContent ?? '') === title) {
    first.hidden = true
  }
}

function serializeInlineNode(node: Node): string {
  if (node.nodeType === Node.TEXT_NODE) return (node.nodeValue ?? '').replace(/\u00a0/g, ' ')
  if (!(node instanceof HTMLElement)) return ''
  const tag = node.tagName.toLowerCase()
  if (tag === 'br') return node.hasAttribute('data-body-caret') ? '' : '\n'
  const content = [...node.childNodes].map(serializeInlineNode).join('')
  if (tag === 'strong' || tag === 'b') return `**${content}**`
  if (tag === 'em' || tag === 'i') return `*${content}*`
  if (tag === 'code') return `\`${(node.textContent ?? '').replace(/\u00a0/g, ' ')}\``
  if (tag === 'a') {
    const href = cleanHref(node.getAttribute('href') ?? '')
    const label = (node.textContent ?? '').replace(/\u00a0/g, ' ')
    return isAllowedHref(href) ? `[${label}](${href})` : label
  }
  return content
}

function serializeInline(element: Element): string {
  return [...element.childNodes].map(serializeInlineNode).join('')
}

function serializeTableElement(table: HTMLElement): string {
  const rows = [...table.querySelectorAll('tr')].map((row) => (
    [...row.children].map((cell) => (
      serializeInline(cell).replace(/\|/g, '\\|').replace(/\n/g, ' ')
    ))
  ))
  if (!rows.length) return ''
  const width = Math.max(1, ...rows.map((row) => row.length))
  const renderRow = (row: string[]) => (
    `| ${Array.from({ length: width }, (_, index) => row[index] ?? '').join(' | ')} |`
  )
  return [renderRow(rows[0]), `| ${Array(width).fill('---').join(' | ')} |`, ...rows.slice(1).map(renderRow)]
    .join('\n')
}

/** Exact inverse of renderBodyElement for IR-09's supported DOM subset. */
export function serializeBodyElement(root: HTMLElement): string {
  const blocks: string[] = []
  let inline = ''
  let terminalLineBreak = false
  const flushInline = () => {
    if (!inline) return
    blocks.push(inline)
    inline = ''
  }
  for (const node of root.childNodes) {
    if (node.nodeType === Node.TEXT_NODE) {
      inline += serializeInlineNode(node)
      continue
    }
    if (!(node instanceof HTMLElement)) continue
    const tag = node.tagName.toLowerCase()
    if (/^h[1-6]$/.test(tag)) {
      flushInline()
      blocks.push(`${'#'.repeat(Number(tag[1]))} ${serializeInline(node)}`)
    } else if (tag === 'table') {
      flushInline()
      const table = serializeTableElement(node)
      if (table) blocks.push(table)
    } else if (tag === 'ul' || tag === 'ol') {
      flushInline()
      const items = [...node.children].filter((child) => child.tagName.toLowerCase() === 'li')
      blocks.push(items.map((item, index) => {
        const marker = tag === 'ol' ? `${index + 1}.` : '-'
        const rawIndent = Number.parseInt((item as HTMLElement).dataset.mdIndent ?? '0', 10)
        const indent = Number.isFinite(rawIndent) && rawIndent > 0 ? rawIndent : 0
        // Chromium keeps a caret in a new empty contenteditable list item with a terminal BR.
        // It is editing scaffolding, not a body newline after the list marker.
        const content = serializeInline(item).replace(/\n$/, '')
        return `${' '.repeat(indent)}${marker} ${content}`
      }).join('\n'))
    } else if (tag === 'p' || tag === 'div') {
      flushInline()
      const content = serializeInline(node)
      if (node === root.lastElementChild && blocks.length > 0 && (content === '' || content === '\n')) {
        // Exiting a list leaves Chromium's terminal empty DIV/BR as caret scaffolding. Textarea
        // behavior stores one final newline here, not a second blank Markdown paragraph.
        terminalLineBreak = true
      } else {
        blocks.push(content)
      }
    } else {
      inline += serializeInlineNode(node)
    }
  }
  flushInline()
  return blocks.join('\n\n') + (terminalLineBreak ? '\n' : '')
}
