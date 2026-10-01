// What changed on a goal since the agent's last turn in its conversation (docs/design-handoff S3.P1.005, .014): edits
// to the goal, new comments and changed documents, from the goal's own record, as a few plain lines the agent reads
// with the next message. Nothing of it is shown to you.
import { fetchDocs, fetchGoalComments, getGoal } from './api'

const MAX_COMMENT = 400

export async function goalChangesSince(goalId: string, sinceMs: number): Promise<string> {
  const [goal, comments, docs] = await Promise.all([
    getGoal(goalId),
    fetchGoalComments(goalId).catch(() => ({ threads: [] })),
    fetchDocs().catch(() => ({ docs: [] })),
  ])
  const after = (iso: string | null | undefined) => !!iso && Date.parse(iso) > sinceMs
  const lines: string[] = []
  if (after(goal.updated_at)) lines.push(`- The goal itself was edited (title, notes, dates or steps) at ${goal.updated_at}.`)
  for (const thread of comments.threads) {
    for (const message of thread.messages) {
      if (!after(message.created_at)) continue
      const who = message.author === 'agent' ? 'An agent' : 'The owner'
      lines.push(`- ${who} commented at ${message.created_at}: "${message.body.slice(0, MAX_COMMENT)}"`)
    }
  }
  const linked = new Map(goal.docs.map((doc) => [doc.id, doc]))
  for (const doc of docs.docs) {
    const link = linked.get(doc.id)
    if (link && after(doc.updated_at)) lines.push(`- The document "${doc.title ?? doc.path}" (#doc/${doc.id}) changed at ${doc.updated_at}.`)
  }
  return lines.join('\n')
}
