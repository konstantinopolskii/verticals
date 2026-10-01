// The agent's markdown (the CommonMark subset agents write), ported from the chat script the desktop gateway used to inject. Every byte of the
// source is escaped; links into Verticals (#goal/<id>, #doc/<id>, /h/<date>) carry data-app-link and move the app in
// place, web links open outside, anything else stays text.

const esc = (s: unknown) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]!)

function linkAttrs(url: string): string | null {
  const u = String(url).trim()
  if (/^#(goal|doc)\/[^\s]+$/.test(u) || /^#(inbox|docs)$/.test(u) || /^\/h\/\d{4}-\d{2}-\d{2}\/?(#.*)?$/.test(u) || u === '/') {
    return `href="${esc(u)}" data-app-link="${esc(u)}"`
  }
  const bare = /^(goal|doc)[:/]([\w-]+)$/.exec(u)
  if (bare) return `href="#${bare[1]}/${esc(bare[2])}" data-app-link="#${bare[1]}/${esc(bare[2])}"`
  if (/^(https?:|mailto:)/i.test(u)) return `href="${esc(u)}" target="_blank" rel="noreferrer" data-web-link="${esc(u)}"`
  return null
}

function inline(src: string): string {
  const slots: string[] = []
  const keep = (html: string) => `\u0000${slots.push(html) - 1}\u0000`
  let t = String(src)
    .replace(/`([^`]+)`/g, (_, c) => keep(`<code>${esc(c)}</code>`))
    .replace(/!\[([^\]]*)\]\((https?:\/\/[^\s)]+)\)/g, (_, alt, url) => keep(`<img alt="${esc(alt)}" src="${esc(url)}">`))
    .replace(/\[([^\]]+)\]\(([^)\s]+)(?:\s+"[^"]*")?\)/g, (_, text, url) => {
      const attrs = linkAttrs(url)
      return attrs ? keep(`<a ${attrs}>${inline(text)}</a>`) : keep(esc(text))
    })
    .replace(/<(https?:\/\/[^>\s]+)>/g, (_, url) => keep(`<a ${linkAttrs(url)}>${esc(url)}</a>`))
    .replace(/(^|[\s(])(https?:\/\/[^\s<)]+[^\s<).,;:!?'"])/g, (_, pre, url) => pre + keep(`<a ${linkAttrs(url)}>${esc(url)}</a>`))
  t = esc(t)
    .replace(/\*\*([^*]+)\*\*|__([^_]+)__/g, (_, a, b) => `<strong>${a ?? b}</strong>`)
    .replace(/(^|[^\w*])\*([^*\s][^*]*?)\*(?!\w)/g, '$1<em>$2</em>')
    .replace(/(^|[^\w_])_([^_\s][^_]*?)_(?!\w)/g, '$1<em>$2</em>')
    .replace(/~~([^~]+)~~/g, '<del>$1</del>')
  return t.replace(/\u0000(\d+)\u0000/g, (_, n) => slots[Number(n)]!)
}

export function chatMarkdown(src: string): string {
  const lines = String(src).replace(/\r/g, '').split('\n')
  const out: string[] = []
  const isList = (l: string) => /^(\s*)([-*+•]|\d+[.)])\s+/.exec(l)
  const blockStart = (l: string) => /^(```|~~~|#{1,6}\s|>|\s*([-*+•]|\d+[.)])\s|\s*\|.*\|\s*$|\s*([-*_])(\s*\3){2,}\s*$)/.test(l)
  function list(start: number): [string, number] {
    let i = start
    const first = isList(lines[i]!)!
    const base = first[1]!.length
    const ordered = /\d/.test(first[2]!)
    const items: string[] = []
    while (i < lines.length) {
      const m = isList(lines[i]!)
      if (!m || m[1]!.length < base) break
      if (m[1]!.length > base) { const [html, next] = list(i); items[items.length - 1] += html; i = next; continue }
      if (/\d/.test(m[2]!) !== ordered) break
      let text = lines[i]!.slice(m[0].length)
      while (i + 1 < lines.length && lines[i + 1]!.trim() && !isList(lines[i + 1]!) && !blockStart(lines[i + 1]!.trim()) && /^\s+/.test(lines[i + 1]!)) {
        text += ' ' + lines[++i]!.trim()
      }
      const task = /^\[([ xX])\]\s+/.exec(text)
      items.push(task ? `<input type="checkbox" disabled ${task[1] !== ' ' ? 'checked' : ''}> ${inline(text.slice(task[0].length))}` : inline(text))
      i++
    }
    const tag = ordered ? 'ol' : 'ul'
    return [`<${tag}>${items.map((x) => `<li>${x}</li>`).join('')}</${tag}>`, i]
  }
  for (let i = 0; i < lines.length;) {
    const line = lines[i]!
    if (!line.trim()) { i++; continue }
    const fence = /^\s*(```|~~~)/.exec(line)
    if (fence) {
      const code: string[] = []
      while (++i < lines.length && !lines[i]!.trim().startsWith(fence[1]!)) code.push(lines[i]!)
      out.push(`<pre><code>${esc(code.join('\n'))}</code></pre>`)
      i++
      continue
    }
    const h = /^(#{1,6})\s+(.*)$/.exec(line)
    if (h) { out.push(`<p><strong>${inline(h[2]!.replace(/\s+#+\s*$/, ''))}</strong></p>`); i++; continue }
    if (/^\s*([-*_])(\s*\1){2,}\s*$/.test(line)) { out.push('<hr>'); i++; continue }
    if (/^\s*>/.test(line)) {
      const quote: string[] = []
      while (i < lines.length && /^\s*>/.test(lines[i]!)) quote.push(lines[i++]!.replace(/^\s*>\s?/, ''))
      out.push(`<blockquote>${chatMarkdown(quote.join('\n'))}</blockquote>`)
      continue
    }
    if (/^\s*\|.*\|\s*$/.test(line)) {
      const rows: string[][] = []
      while (i < lines.length && /^\s*\|.*\|\s*$/.test(lines[i]!)) rows.push(lines[i++]!.trim().slice(1, -1).split('|').map((c) => c.trim()))
      const sep = rows[1]?.every((c) => /^:?-{2,}:?$/.test(c))
      const align = sep ? rows[1]!.map((c) => (c.startsWith(':') && c.endsWith(':') ? 'center' : c.endsWith(':') ? 'right' : '')) : []
      const cell = (tag: string, c: string, k: number) => `<${tag}${align[k] ? ` style="text-align:${align[k]}"` : ''}>${inline(c)}</${tag}>`
      const body = sep ? rows.slice(2) : rows.slice(1)
      out.push(`<div class="chat-table"><table><thead><tr>${rows[0]!.map((c, k) => cell('th', c, k)).join('')}</tr></thead><tbody>${body.map((r) => `<tr>${r.map((c, k) => cell('td', c, k)).join('')}</tr>`).join('')}</tbody></table></div>`)
      continue
    }
    if (isList(line)) { const [html, next] = list(i); out.push(html); i = next; continue }
    const para = [line.trim()]
    while (i + 1 < lines.length && lines[i + 1]!.trim() && !blockStart(lines[i + 1]!)) para.push(lines[++i]!.trim())
    out.push(`<p>${para.map(inline).join('<br>')}</p>`)
    i++
  }
  return out.join('')
}

/** The answer's plain words, for the circle: markdown marks dropped, tables and lists as their text (S2.P4.024). */
export function plainWords(src: string): string {
  return String(src)
    .replace(/```[\s\S]*?```/g, '')
    .replace(/^\s*\|?\s*:?-{2,}.*$/gm, '')
    .replace(/\|/g, ' ')
    .replace(/!\[[^\]]*\]\([^)]*\)/g, '')
    .replace(/\[([^\]]+)\]\([^)]*\)/g, '$1')
    .replace(/[*_~`>#]+/g, '')
    .replace(/^\s*([-+•]|\d+[.)])\s+/gm, '')
    .replace(/[ \t]+/g, ' ')
    .replace(/\n{2,}/g, '\n')
    .trim()
}
