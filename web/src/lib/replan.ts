// Replan (Inbox and Documents redesign, round 8; KK 7 Oct 2026: "determenistic replan automatic one not needed. I didn't
// ask for this automatisation"): nothing is made until you click Replan in a carried box. The click asks the agent, in a
// conversation of its own, to sort those plans out; it answers with the table as a document attached (goal, summary, next
// step, your comment: flow 1's table; desktop/chat/chat.py's REPLAN_ASK_RULES). You comment in the table, the field asks
// "Ready?", and the agent moves them.

export interface CarriedPlan { id: string; title: string }

/** Your words, as your balloon: one sentence; the plans themselves go with it in the message's context. */
export const REPLAN_ASK = 'Sort out the plans carried over: where each goes, based on when I planned it and what it belongs to.'
