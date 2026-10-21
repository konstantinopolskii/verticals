# A step's date decides where it shows

The owner, on the Hide / Show subtasks toggle (PR #83, which this document replaces): some steps are a checklist he doesn't need to see on the board, and some are sub-goals he wants to see always; agents cut checklists and tasks for sub-agents that he doesn't care about. Who made a step doesn't decide it. Its date does. In his words (21 Oct 2026):

> If the task is a subtask but has NO date, it should be sitting inside it's parent and visible when it's open. If it has SAME date as it's parent scheduled, it should be visible on horizon. Basically if u select the date specifically, it means that u want to CONTROL it and see in vertical. And if no date is selected, it's more of untracked task let's say, u don't need to control, it can stay inside, but hidden from vertical. And u can remove the date same way from the scheduled task and it will get to inbox. It should be clear from the MCP and it should be written in the agent's mc that vertical uses, so NOBODY will do same mistake again.

So there is nothing to press: a date puts a step on the board, no date keeps it inside its parent.

## Behaviour

- **A step with a date** stands on the board in its column, as every goal does: with its parent's date, under its parent; with a date in another column, on its own there.
- **A step with no date** (vertical and anchor date empty) is not on the board. When its parent is opened in place, it shows in the parent's list of steps, after the dated ones, drawn as they are: its box and title; it completes and opens as a step does. The Inbox lists it with its parent, as it does today.
- **A step added inside an open goal** ("Add…") has no date: it shows in the open goal and stays inside it. Giving it a date is the menu's Reschedule.
- **Taking a date away** (Reschedule, "To Inbox") keeps a step inside its parent and puts a parentless goal in the Inbox, as today.
- A Life value is the one goal that doesn't list its goals with no date when opened: under a value they are its ideas, which its detail keeps apart and the Inbox shelves, as today.
- The parent's box keeps counting all its steps, dated or not.
- The Hide / Show N subtasks toggle goes, with what it saved on the device.
- The rule is written where agents read it: the `create` and `schedule` tools of the MCP server and the operator, planning and morning-report skills say, in the same words: "A step gets a date only when the owner wants to track it on the board; a date the same as its parent's puts it on the board under the parent. An agent's checklist, its working steps and tasks for sub-agents are created without a date (vertical and anchor_date null): they live inside the parent, show when it is opened, and in the Inbox. Removing a goal's date puts a parentless goal in the Inbox and keeps a step inside its parent."
- Nothing in the data changes: no migration, no new field.

The open goal's undated steps come from what is loaded already: the board carries every direct child of the goals it draws, and an opened goal's detail its own (`web/src/lib/stepDates.ts`, listed by `web/src/lib/cardFamily.ts`). The words agents read live once, in `verticals/mcp/tool_schemas.py` (`STEP_DATES`).

## Done when

UI tests on the sample board, light and dark: an undated step is not on the board, shows when its parent opens, after the dated steps, and completes from there; a dated step under the same task shows on the board; a step added inside an open task has no date and shows in the open task, not on the board once it closes; no Hide / Show toggle anywhere. MCP and static tests: the `create` and `schedule` descriptions and the skills carry the rule. Before and after pictures: a Week task closed and opened.
