# The agent's eight fixes

Eight fixes with one right answer, found while shaping how the agent works. They go first, since the agent's other pieces build on them.

## What changes

1. **The morning rules reach the agent.** The chat's settings pass `sources` on instead of dropping it, so the morning guide applies to the morning turn, and the morning-report skill ships with the app beside the operator skill.
2. **One open "Morning report" task.** A new morning reuses the open task and moves it to today instead of making another. Each morning's report is still a new document linked to that task; earlier reports stay as they are.
3. **One morning report a day per board,** decided by the server, not by a flag in each browser, so a second window or a cleared cache never makes a second report.
4. **Outside Vertical the morning turn only reads,** whatever mode the chat is in. In Vertical it writes only the report, its task and what the owner allowed. An ask the owner leaves unanswered for ten minutes is declined, and the report goes on without it.
5. **The agent's instructions agree with themselves.** In every turn: one or two short paragraphs, and a document for anything longer. "Report exact IDs" goes, since it fights "refer to goals by title, not by ID". The selected text the prompt promises is sent, or the promise goes. The board has seven columns, not "five rungs".
6. **A permission card says what will change:** the goal and its new date. The app already receives this and draws it nowhere.
7. **The agent's gateway keeps a log,** a small rotating file in the app's data folder, so a bug report can carry the agent's side.
8. **An answer waiting in the field can be brushed away:** a sideways swipe or a drag down sends it back into the circle, where the conversation keeps it. Esc keeps doing the same.

## Not in this piece

What the agent makes as chips under its words (`agent-chips.md`), sources (`sources.md`) and how the morning report reads them (`morning-quality.md`).

## Done when

Each fix has a test that fails before it and passes after. The visible ones (6 and 8) have before and after pictures from a sample board.
