# Sort a carried plan by hand: three words over it

The owner (21 Oct 2026), going through the plans that carried over: some they close as dead, some they keep in the week, and for some the answer is "I don't know, don't bother me" (the Inbox). "Sorting out by hand via UI could be done as 3 pills that show up on the right on white background with light shadow with common actions, ideally background maybe not white but green." Today each of those takes the card's menu: open it, find the item, click, for every plan.

A first build put three white pills on a backing to the right of the box; the owner rejected the look and drew this one himself, the same day. His words for the three: "Keep meens it's ok", "If idk — move to inbox with note that we need to realign", "Fuck it means delete".

## Behaviour

- Point at a carried plan in a box and one capsule appears just above the plan's lit block: its left edge on the block's left edge, about 4 px of air under it. It may cover the box's line ("14 from earlier weeks · Replan") or the plan above while it shows. With no room above in the window, it stands just below the block. It moves with the box's lift and glides to the next plan the pointer takes.
- The capsule is the block's own colour: the box's ground under the plan's light, as the lit card shows it, so the card and the capsule read as one object; a plan with no colour has the card's own hover grey. No shadow, no pills inside, half its height (about 26 px) for its radius. In the dark appearance it follows the card's dark light and the card's dark text.
- Three words in the card title's own type, all one colour: **Keep** · **Idk** · **Fuck it**, spaced like a sentence with gaps. Each word is a button; pointing at one deepens the light behind that word only, and a press gives a little, as the app's other buttons do.
- **Keep** keeps the plan in the column where it sits: it moves into that column's current period, the way the menu's Reschedule items move a goal (`store.scheduleGoalQuick`), and its scale becomes the column's. **Idk** adds one line after the plan's notes, "Needs realigning. Moved from the week of 5 Oct on 21 Oct." (its planned period, and today), then moves it to the Inbox, as the menu's To Inbox does; both are one step. **Fuck it** is the menu's Delete, with its sound and Undo in the field (`store.removeGoal`). Each is one step of the board's history, so ⌘Z takes it back, the line in the notes included.
- While a plan is pointed at, 1 is Keep, 2 is Idk and 3 is Fuck it, with no hint on the screen; inside a text field the keys stay the field's.
- After a click or a key the card leaves the box as a moved card does, the next one rises under the pointer, and the capsule is there for it: going down a list is click, click, click.
- Pointer only (`(hover: hover) and (pointer: fine)`); on touch the card's menu stays the way. With reduced motion the capsule appears without its fade and doesn't glide.

## Done when

UI tests on the sample board: the capsule appears above a pointed carried plan, in the block's colour (light and dark), and on no other card; each word's result on the server and on the board (the new period; the Inbox and the line in the notes; the trash), and ⌘Z for each; the keys, and none while typing; after a click the next card under the pointer gets the capsule. Pictures: the Week box pointed, light and dark, a plan with no colour, and the capsule above a box's first plan.
