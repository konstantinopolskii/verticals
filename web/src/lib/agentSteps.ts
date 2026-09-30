// What the step bubble says while the agent works (docs/design-handoff S2.P3): one fixed phrase per tool, so the same
// step always reads the same. Claude names Verticals' tools `mcp__verticals__<tool>` (the server shortens them), Codex
// `verticals.<tool>` or `<tool>`; anything else, its own commands and file edits included, reads "Thinking".
const PHRASES: Record<string, string> = {
  board: 'Reading your board',
  outline: 'Reading the plan',
  search: 'Looking for goals',
  goal: 'Reading the goal',
  doc_get: 'Reading the document',
  doc_tree: 'Reading the document',
  doc_history: 'Reading the document',
  doc_revision: 'Reading the document',
  create: 'Writing a new goal',
  update: 'Rewriting the goal',
  reparent: 'Moving the goal',
  schedule: 'Setting the date',
}

export function stepPhrase(tool: string): string {
  const name = tool.replace(/^mcp__verticals__/, '').replace(/^verticals[.:_]+/, '').trim()
  return PHRASES[name] ?? 'Thinking'
}
