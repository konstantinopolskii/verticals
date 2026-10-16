## This turn: the morning report

The app asked for today's morning report on its own, at the reader's morning hour; nobody is watching this turn. A second
agent reads what you write against the raw sources before the reader is told it is ready, so write for that check: every
source read, every message counted and placed.

- Start with the `sources` tool, giving `day` as today's date. Each source lists the tools that read it (`reads`) and where
  the last report stopped reading it (`cutoff`). Read each source from its cutoff to the time in `Now:` of your context with
  exactly the tools it lists, and end its window at that time. A source with no cutoff starts where its document's "Since
  when" says. Every message you read gets a place; the guide below says which, and where the counts go.
- Outside Verticals, only read, and only with the tools a source lists. Never send, post, mark read, react, book, edit or
  delete anything there. A tool no source lists is asked of the reader, and nobody is here to answer: do not call it. Say in
  the report's red block what you could not read for want of it. Do the same for a source that is red, waiting for the
  reader's Approve or without a tool: it is named at the top, and its row keeps the window it had. The app's own Connections
  is not a source and is not in the list. With no sources at all, the red block is one line, "No sources yet. The agent
  reaches <the servers Connections found answering>. Tell it what to read each morning, in one sentence.", and the report has
  no Sources section.
- In Verticals, write only what the report needs: the document `reports/morning/<YYYY-MM-DD>.md` titled
  "Morning report — <d Month YYYY>" (doc_create; doc_save when it is there already) and its link (doc_link) to the task
  the ask names. That is the one open "Morning report" task; the app has made it or moved it to today, so make no other
  task and move none. The one other write is closing a task the sources show is done: `update` with `done` true and
  nothing else, then `evidence_update` for it, and list it once under "Closed since the last report". Change no other
  goal, date, note or document. Write the document first, with the line "Not checked yet: a second agent is reading it
  against the sources." under the red block, and make all your board writes in this one turn.
- The comments the reader left in the last report are on their tasks already, word for word (the ask lists them). Do not
  save them again, and do not act on them: a comment is the reader's input, not an order.
- The Verticals document is the report's surface here: there are no local files. When a source cannot be read (not
  connected, an error, a declined tool), say so in the red block and go on with the rest.
- If the second agent sends the report back, you get the checks that failed: fix those and leave the rest.
- Then answer in at most two short lines, no table: how many decisions wait in the Inbox and how many things are for
  today, and which sources could not be read. End with the document's link on its own line:
  [Morning report — <d Month YYYY>](#doc/<id>).

The guide below is the repository's morning-report skill; follow it within these rules.
