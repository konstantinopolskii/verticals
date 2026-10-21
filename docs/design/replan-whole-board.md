# Replan sorts the whole board with the owner, in about five minutes

The owner (21 Oct 2026): "I expect u take into account the whole board and replan not just one group of due task but refresh the whole due list." Before sorting, the agent should "first acknowledge the board and then ask me coaching questions on what's important right now, maybe check what I was doing recently to try predict that", simplifying the decisions so the whole batch takes "like 5 minutes max, saving as much energy and thinking as possible."

Today Replan sends only its own box's plans, one column, and the agent answers with a table to comment on row by row. A board that has stood for a few weeks carries dozens of plans across Week, Month and Quarter, so one box at a time is three conversations, and a row at a time is an hour.

## Behaviour

- **Replan in any box takes every carried plan on the board**, all columns. The message's context lists them by column, each with what it takes to judge it: title, id, its own scale and planned period, and what it belongs to (its parent's title). The owner's words stay one sentence: "Sort out every plan that carried over: what matters now, and where each goes."
- **The agent reads before it asks**: the board today; what the owner did lately (goals done, added or moved in the last two weeks; recent documents); and, in a conversation that reaches them, the calendar for the next two weeks and recent messages. From that it guesses what matters now and which streams went quiet.
- **Its first answer is the board in two lines, then at most three questions.** The two lines say what the board holds now (this week, this month), how many plans carried over and from which streams. The questions are about what matters now, each with two to four short options, the agent's guess first. Claude asks with its question tool (`AskUserQuestion`): the field shows each question in turn as the ask it already has, in the field and in the conversation.
- **The options are suggestions, not answers.** The owner, after trying the first version (21 Oct 2026): "Why there's no button add my answer? What if I want to answer both, not just one button? Let them simply add text to my field, as autocomplete. Answers for autocomplete." So they stand as outlined pills, the guess first. A click puts the option's words in the field (after ", " when it already has words) and gives the field the caret; a second click takes them out again; a pill whose words are in the field is filled, so several can be picked. The guess's mark, "(my guess)", stays on the pill and never goes into the field. Nothing is sent but by the owner: Enter sends the field's words as the answer, and the next question shows; an empty field sends nothing. While a question waits the field says "Your answer". The asks to use a tool, and the sign-in's, keep their buttons. An agent without the tool (Codex) numbers its questions, letters the options and takes "go" as yes to all its guesses.
- **Then one document, sorted by decision**: path `replan/<date>.md`, or `replan/<date>-2.md` (then -3 …) when an earlier Replan that day took it, never written over; titled "Replan — 21 October 2026". A section per decision, the count in its heading ("Keep · 6"). The decisions carry the names the owner chose for sorting a carried plan by hand (`carried-pills.md`), so one action has one name:
  - **Keep**: it's fine; into the current period of the column it carried into (this week, this month, this quarter);
  - **Idk**: not now, not dead; the date taken away, to the Inbox, and one line added to the plan's notes, under what they said: "Needs realigning. Moved from the week of 5 Oct on 21 Oct." (its planned period, then today);
  - **Fuck it**: dead; deleted;
  - **Done**: it already happened, and the agent says by what evidence.
  Inside each section the plans are grouped by what they belong to, so a whole stream reads as one decision; each plan is linked, with a few words of why. The answer is the counts in one line and "Say go, or move a row in the document."
- **On go, the agent applies all of it** and says in one line what changed. A Replan conversation runs its board writes (schedule, delete, update, reparent) without asking for each: the owner said go to the whole document, and the answer's Undo takes all of it back (`agent-answer-undo.md`). Nothing moves before go.
- The box's "Replan" button stays where it is; only what it sends changes.

## Not in this piece

The three pills for sorting a carried plan by hand: `carried-pills.md`.

## Done when

Static gateway tests: the context lists every column's plans; an `AskUserQuestion` call becomes field asks, and the answers go back to Claude in the tool's answer shape; typed words answer an open question; a Replan conversation allows the board writes, and no other conversation does. UI tests: Replan in the Week box sends the other boxes' plans too; a question's suggestions put their words in the field and take them out, several at once, Enter answers with the field's words and the next question shows, and a permission ask keeps its buttons. The owner runs it on their board.
