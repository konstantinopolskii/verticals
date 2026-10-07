// The documents an agent's message brings (Inbox and Documents redesign, rounds 9–11; .local-design/inbox-and-docs/final):
// the chat links a document as [title](#doc/<id>) (desktop/chat/prompt-intro.md). Under the message's words they are
// chips (DocChip.vue); in the field the message stands beside the first one's page (SearchBar.vue).

export interface DocLink { id: string; label: string }

const link = () => /\[([^\]]*)\]\(#doc\/([A-Za-z0-9_-]+)\)/g

/** The documents a message links, in order, each once. */
export function docLinks(text: string): DocLink[] {
  const seen = new Set<string>()
  const out: DocLink[] = []
  for (const match of String(text).matchAll(link())) {
    const id = match[2]!
    if (seen.has(id)) continue
    seen.add(id)
    out.push({ id, label: match[1]!.trim() })
  }
  return out
}

/** The message's words without the lines that only link documents: the chips say those. A link inside a sentence stays. */
export function withoutDocLines(text: string): string {
  return String(text)
    .split('\n')
    .filter((line) => !(link().test(line) && !line.replace(link(), '').replace(/[\s\-*•·,:;.()[\]]+/g, '')))
    .join('\n')
    .replace(/\n{3,}/g, '\n\n')
    .trim()
}
