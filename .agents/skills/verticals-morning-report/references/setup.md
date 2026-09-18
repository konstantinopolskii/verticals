# Set up a morning report on a new machine

This repository supplies the method, not the owner's accounts or filesystem layout. Before the first report, agree and record the following in that owner's private workspace instructions or local configuration (not in the shared skill):

| Setting | Decide locally |
| --- | --- |
| Reader and timezone | Who reviews the report, their local date, and the cutoff convention. |
| Destination | A writable report directory or existing document; optionally a linked native Verticals document. Decide whether both copies must match. |
| Review surface | The existing coordination goal or session, if any, and how the reader leaves comments and decisions. |
| Sources | The Verticals connection and only the relevant, authorized work sessions, messages, meeting records, calendar, files, or repositories actually available. |
| Cadence | Manual invocation or an existing scheduler. A skill does not create a timer, notification, or background process. |
| Presentation | Which sections and comment column the reader wants, and how completed work should be displayed. |

For a local Markdown destination, a date-named file such as `reports/YYYY-MM-DD/Morning report.md` is an example relative to the chosen workspace, not a required absolute path. Keep a single report for that date and edit it after review. A native copy is optional; do not invent a document ID or create a coordination task merely to mirror the file.

Connect Verticals through the runtime's own MCP configuration and credentials, following the repository's deployment instructions. Verify read-only access to the intended board and owner before reporting. Configure other connectors separately in the owner's environment. If a source is unavailable, record its exact coverage gap; do not silently substitute another person's account or a different service. Never copy bearer tokens, private conversations, account addresses, or local paths into repository-owned skill files.

An initial invocation can say: “Use `$verticals-morning-report` for today's pre-meeting report. Timezone and report destination are in my local workspace instructions; use only connected sources and disclose gaps.” The report can be produced manually without any automation.
