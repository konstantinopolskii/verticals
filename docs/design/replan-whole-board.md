# Replan sorts the whole board with the owner, in about five minutes

The owner (21 Oct 2026): "I expect u take into account the whole board and replan not just one group of due task but refresh the whole due list." Before sorting, the agent should "first acknowledge the board and then ask me coaching questions on what's important right now, maybe check what I was doing recently to try predict that", simplifying the decisions so the whole batch takes "like 5 minutes max, saving as much energy and thinking as possible."

Today Replan sends only its own box's plans, one column, and the agent answers with a table to comment on row by row. A board that has stood for a few weeks carries dozens of plans across Week, Month and Quarter, so one box at a time is three conversations, and a row at a time is an hour.

## Behaviour

- **Replan in any box takes every carried plan on the board**, all columns. The message's context lists them by column, each with what it takes to judge it: title, id, its own scale and planned period, and what it belongs to (its parent's title). The owner's words stay one sentence: "Sort out every plan that carried over: what matters now, and where each goes."
- **The agent reads before it asks**: the board today; what the owner did lately (goals done, added or moved in the last two weeks; recent documents); and, in a conversation that reaches them, the calendar for the next two weeks and recent messages. From that it guesses what matters now and which streams went quiet.
- **Its first answer is the board in two lines, then at most three questions.** The two lines say what the board holds now (this week, this month), how many plans carried over and from which streams. The questions are about what matters now, each with two to four short options, the agent's guess first. Claude asks with its question tool (`AskUserQuestion`): the field shows each question as the ask it already has, the options as its buttons, the guess marked, one tap each. Words typed in the field while a question is open answer it. An agent without the tool (Codex) numbers its questions, letters the options and takes "go" as yes to all its guesses.
- **Then one document, sorted by decision**: path `replan/<date>.md`, titled "Replan — 21 October 2026". A section per decision, the count in its heading:
  - **Keep**: into the current period of the column it carried into (this week, this month, this quarter);
  - **To Inbox**: the date taken away, for "not now, not dead";
  - **Delete**: dead;
  - **Done**: it already happened, and the agent says by what evidence.
  Inside each section the plans are grouped by what they belong to, so a whole stream reads as one decision; each plan is linked, with a few words of why. The answer is the counts in one line and "Say go, or move a row in the document."
- **On go, the agent applies all of it** and says in one line what changed. A Replan conversation runs its board writes (schedule, delete, update, reparent) without asking for each: the owner said go to the whole document, and the answer's Undo takes all of it back (`agent-answer-undo.md`). Nothing moves before go.
- The box's "Replan" button stays where it is; only what it sends changes.

## Not in this piece

The three pills for sorting a carried plan by hand: `carried-pills.md`.

## Done when

Static gateway tests: the context lists every column's plans; an `AskUserQuestion` call becomes field asks, and the answers go back to Claude in the tool's answer shape; typed words answer an open question; a Replan conversation allows the board writes, and no other conversation does. A UI test: Replan in the Week box sends the Month and Quarter plans too. The owner runs it on their board.
