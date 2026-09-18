# Configure a morning report on another machine

The skill contains the method. The reader's private workspace instructions or local configuration supply the sources and destinations. Record concrete values for these fields before the first run; do not commit credentials or personal routes to this repository.

| Configure locally | What the agent needs to know | Adapted example from one actual run |
| --- | --- | --- |
| Reader, timezone, date | Whose decisions the report serves, local date, and how UTC times are converted. | The 17 September report used UTC+4 time; a 15:00 meeting was displayed in that timezone. This is an example, not another owner's default. |
| Report surface | Writable local or native destination, naming convention, and whether copies must be identical. | One dated Markdown report was also saved as a document on an existing Verticals coordination task. The morning review updated that same report rather than opening a second briefing. |
| Verticals scope | Connection and owner, relevant goal verticals, and where goal-linked documents/comments are read. | The report inspected Inbox, Today and Week for navigation, while broader goals supplied dependencies rather than another inventory table. |
| Owning work sessions | How to find the real execution/review session for a goal, including its current title and latest result. | A service-offer row linked to its actual economics session, not a generic coordination chat. |
| Meeting source | Connected summary index and method to read exact transcript passages or full records. | A meeting summary located an offer-package discussion; consequential claims were checked against the discussion and the economics document. |
| Messages and replies | Which authorized conversations matter, how to refresh both incoming and outgoing history, and the search window. | A collaborator's later replies confirmed skill use after a PR merge, replacing the earlier “waiting for review” state. |
| Calendar and artifacts | Available calendar, document, repository, payment, or other state systems; account and coverage limits. | A current calendar gave a meeting time; a document readback proved an updated brief; repository state proved a PR merge. None alone proved client acceptance. |
| Cadence and preferences | Manual run or existing scheduler; report target time; priority order, sections, comment cells, and treatment of completed work. | The report named a late collection time separately from its intended delivery time and kept the reader's priority order. The skill creates no timer. |

The owner may store this mapping in their private workspace instructions, a local project note, or an existing configuration mechanism. A relative layout such as `reports/YYYY-MM-DD/Morning report.md` is only an example under the owner's chosen workspace root; the skill must not presume a home directory or fixed drive. A native copy is optional unless the owner configures it. Do not invent a coordination task or document ID to create one.

Before relying on a connector, test read-only access to the intended account/board and an actual relevant item. Identify which mailbox, calendar, repository, meeting account, or message identity was checked; an empty search in the wrong account is not evidence that an event or reply does not exist. If the owner has only some sources, produce a narrower report with explicit gaps rather than silently swapping providers.

Example local instruction, to be filled with the new owner's own values:

> Prepare my morning report in my local timezone. The report destination, Verticals connection, owning-session index, meeting source, permitted conversations, calendar and artifact stores are configured here. Use summaries for discovery, inspect primary passages for consequential claims, and list any unavailable source with its last verified window. Do not create a new schedule or send anything.
