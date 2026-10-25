# Agents

Pull requests here follow [.agents/skills/verticals-pr](.agents/skills/verticals-pr/SKILL.md). Read it before you open or rework one: one task, one PR, and a title and text in the shape it gives. Push the branch, then open the PR with

```sh
python3 tools/pr.py --title "type(scope): what changes" --body-file /path/to/pr.md
```

It checks the PR against the skill and opens it only when it holds; otherwise it says what to fix. It needs Claude Code; without it, open the PR with `gh pr create`, and GitHub checks its form.

The other skills are in `.agents/skills/`, and the README says where code, schema and UI live.

## Optimistic writes and board reads

The board shows a write at once and sends it to the server. Other reads of the board run at the same time, for
example the change feed's reload. A read is the board at the moment the server read it. If it lands after a later
write, it puts back a state that the board already left: the goal jumps back and then forward again.

- Before you apply a read to the board, make sure that no write went out or came back while the read was on its way.
  If one did, drop the read. The feed rings again after the write, and the next read is correct.
  `lib/liveBoard.ts` counts the writes with `onApiWrite` (`lib/api.ts`). A placement change also bumps the board
  epoch (`lib/boardEpoch.ts`).
- What the board shows moves only forward. An older read never undoes an optimistic change.
- Test this with a slow server: in Playwright, take the answer with `route.fetch()` and give it late with
  `route.fulfill(response=...)`. Do the action twice, fast. Record each state the goal takes, and assert that no state
  comes back (`tests/ui/test_feed_reload_order.py`). A local server answers too fast to show the problem.
