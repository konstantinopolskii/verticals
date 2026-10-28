# Continue from the morning report in the same chat

The owner reads a morning report, leaves decisions in its cells and comments, and says "доделай". The agent reads the latest
report and the comments already transferred onto its tasks, applies clear decisions to those tasks and carries out work
assigned to it. It verifies the changes and deliverables and states what remains blocked. The owner repeats no instructions
and opens no new conversation.

Unattended report collection, its second check and automatic fixes keep their existing restrictions. Comments and Check again
still preserve input without executing it. A later direct owner command is ordinary user-directed work, under the selected
permission mode; it does not inherit report-only instructions from the earlier turn.

When a Codex turn changes between automatic collection, checking and ordinary work, the gateway resumes the same agent thread
with the new instructions and available tools, and appends the current developer instructions to its model-visible history.
Changing thread configuration alone leaves the original morning message in a resumed rollout. If refreshing the instructions
fails, the work does not start under stale rules. Model and effort changes do not restart it. Claude rebuilds the current system
prompt on every resume, including after the gateway restarts, so an old morning snapshot never governs ordinary work.

The agent normally does small tasks itself. Another existing or new work session is optional when useful and supported; its
task, context and expected result travel with it and its result stays on the task. No new dispatcher or mandatory session is
introduced.

Verification: real gateway/CLI subprocess regression tests in both mode directions and after restart, followed by a real-agent
continuation using only sample data, checking actual task changes and a delivered artifact. User data is not test input.
