# The agent's memory after its instructions

The agent's instructions are built into the app: every release updates them, and nobody edits them. The owner's settings, and what the agent learns from them, go in a memory after them, which wins.

## Behaviour

- **Two layers, built-in and memory.** The built-in text stays in the app and is never a document, so it cannot be edited and a new release still reaches the owner. The memory is added after it, under "Memory", which says it wins where the two differ.
- **A document per layer.** `memory/AGENTS.md` is the memory of every conversation, the morning report's included. `memory/morning-report.md` is the morning report's turns' own, the writer's and the second agent's. They are ordinary documents, with their history and their comments. The gateway makes a missing one empty when it starts and at every turn, so both are there before anything is written.
- **The agent writes it.** When the owner corrects the agent or says how something should be done from now on, the agent adds a line to the fitting document and says so. Making or editing those two documents is the one Verticals write it makes without asking (`Chat.memory_write`), so a correction in any chat is kept; the history shows every line it added. The morning report's turns read mail and other sources, so there a write to the memory is put to the owner (`Chat.touches_memory`): a line in a letter must not become an instruction. The second agent writes nothing. The owner edits the documents like any other.
- **Read at every turn.** The gateway reads the documents when a turn starts, so a line works from the next message or the next morning. An agent whose memory changed is started again, and a Claude conversation resumed with a new memory has its prompt rendered again (`--system-prompt-snapshot off`), since Claude otherwise keeps the prompt it recorded first. When the documents cannot be read, the turn goes on with the built-in text.
- **On the desk.** Documents shows the memory last, as a group of its own, Agent memory, and never in a goal's stack (`core/docs_desk.py`). A click lays its pages out, and a page opens as any document does.

## Done when

Static tests for the order of the layers and which turn reads which document, for the prompt rendered again on a resume with a new memory, and for which writes run without asking. A core test for the memory's own group on the desk. A UI test: the group is last on the desk with both pages before anything is written, its page opens, and what the document says ends the next turn's prompt.
