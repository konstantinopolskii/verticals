# The overview shows goals; an agent's checklist shows inside its task

The owner, on the Hide / Show subtasks toggle (`subtask-collapse.md`, PR #83): there are subtasks you don't need to see, used as checklists, "such really shouldn't be shown on the overview — they should be visible simply when the task is opened, automatically. But there are tasks that are sub-goals of a specific priority, and those I want to see on the overview always." Then: "agents sometimes cut checklists or spawn sub-agents: that is a checklist too, a task I don't care about. But if I created the goal, and there is a session and an agent, it must be visible." So the board decides by itself what is a checklist; there is no toggle to press.

A goal knows who made it (`goals.origin`: human, agent, import, app). Who made it is not enough alone: most goals under the owner's priorities were typed by an agent while they planned together (on the owner's board, 22 of the open goals shown under a priority, in Month, Quarter, Year and Life, are the agent's). An agent's own working steps sit under the tasks it works on, and tasks are the Day and Week columns.

## Behaviour

- **A checklist step** is a step an agent made (`origin` agent or app) under a task in the Day or Week column, in that task's own column. On the board it is not drawn under its task. It shows when the task is opened, with the task's other steps, as steps do now.
- **Everything else under a card stays on the board, always**: every step the owner made (`origin` human or import), in any column, with a session or without; and every step in Month, Quarter, Year, 3 years and Life, whoever typed it.
- A task whose steps are all a checklist shows as a task without steps on the board, except that its box keeps saying how many of its steps are done (the progress it shows today), so a checklist is never invisible altogether.
- The Hide / Show N subtasks toggle goes, with what it saved on the device (`subtask-collapse.md` is replaced by this document).
- Nothing in the data changes: no migration, no new field, nothing an agent must remember to set.

## Done when

UI tests on the sample board: an agent's step under a Week task is not on the board and shows when the task opens; an owner's step under the same task stays on the board; an agent's step under a Quarter goal stays on the board; the task's box still shows its steps' progress; no Hide / Show toggle anywhere. Before and after pictures.
