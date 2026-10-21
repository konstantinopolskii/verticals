# Sort a carried plan by hand: three pills beside it

The owner (21 Oct 2026), going through the plans that carried over: some they close as dead, some they keep in the week, and for some the answer is "I don't know, don't bother me" (the Inbox). "Sorting out by hand via UI could be done as 3 pills that show up on the right on white background with light shadow with common actions, ideally background maybe not white but green." Today each of those takes the card's menu: open it, find the item, click, for every plan.

## Behaviour

- Point at a carried plan in a box and three pills appear to the right of the box, level with the card, on one backing: **This week** (This month, This quarter in those columns) · **To Inbox** · **Delete**.
- The backing floats over the next column, so it carries a light shadow (about `0 2px 8px` at 8% black). Its colour is the box's own lit colour for that plan's family, the wash the box already puts on when you point at one of its plans, and white for a plan with no colour: the owner asked for green, and the family's colour is green on the board's green families while keeping one meaning for colour everywhere. The pills are white capsules on it, the text the size of the plan's own title, Delete in the menu's red (#c93a5b).
- **This week / month / quarter** keeps the plan in the column where it sits: it moves into that column's current period, the way the menu's Reschedule items move a goal (`store.scheduleGoalQuick`), and its scale becomes the column's. **To Inbox** is the menu's To Inbox (`store.moveGoalToInbox`). **Delete** is the menu's Delete, with its sound and Undo in the field (`store.removeGoal`). Each is one step of the board's history, so ⌘Z takes it back.
- After a click the card leaves the box as a moved card does, the next one rises under the pointer, and the pills are there for it: going down a list is click, click, click.
- The order puts the mild action nearest the card and the destructive one farthest, as Delete sits last in the menu.
- Pointer only (`(hover: hover) and (pointer: fine)`); on touch the card's menu stays the way. With reduced motion the pills appear without their fade.

## Done when

UI tests on the sample board: the pills appear when pointing at a carried plan and on no other card; each pill's result on the server and on the board (the new period, the Inbox, the trash), and ⌘Z for each; after a click the next card under the pointer gets the pills. Before and after pictures, with the backing over the next column.
