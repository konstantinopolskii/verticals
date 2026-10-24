# The period bars, | ||| |, on a line pinned at the column's top

Vertical pages a column with vertical bars, its own sign, in place of ← • →. The middle bar opens the column's spans mode, the same one a dragged task opens when it rests on the column's corner; on a column paged away from today it first brings the board back to today.

## Behaviour

- At rest the line shows no bars. Under the pointer every column but Life shows its sign, three bars, |||, the middle one dark, as long as its own period holds today, with a bar at each side: | ||| |. The side bars step the column to the period before and after, as ← and → do today. The middle bar opens the column's spans mode (`lib/spans.ts`, `SpansBoard.tsx`): a week in each column for Week, a month in each for Month, and so on. The mode is built; only the click on the middle is new.
- When a column scrolls, the line holding the bars stays pinned at its top on white, and the goals fade out under it over 14 px. While the column is at its top the line shows the kind ("Week"); once the big name has scrolled under it, the line shows the period ("5–11 Oct").
- A column whose own period no longer holds today shows a single bar, |: the dark middle bar alone, its two light neighbours gone. The board pages as one, so each column judges its own period: with the board a day on, Day shows | while Week, whose week still holds today, shows |||. A click on the single bar brings the board back to today. The sign then turns back into |||, and the next click on it opens the mode. The middle bar and the two side bars keep exactly the same places in both looks; only the two light bars go and come, together, as one movement with the page's own change: opacity only, 150 ms, and nothing under reduced motion. The owner, 12 October 2026: "If u scrolled to the other bar, to the central one first becomes the single | instead of ||| meaning it will bring you center. Second click will open weeks mode or verticals mode idk how to call it."
- The bars are buttons with names for the keyboard and assistive tech, by what they do: "Previous week", "Weeks side by side", "Next week", by the column's kind, the middle one named by what the mode shows (Days, Weeks, Months, Quarters, Years, Three years). The single bar is "Today".
- The bars appear at once under the pointer and fade back in 200 ms; under reduced motion they simply appear and go. A keyboard's focus on a bar holds them all in view. On a touch screen, where nothing hovers, they are always there.

## Not in this piece

The names themselves (`column-names.md`).

## Done when

UI tests: no bars at rest, the whole sign under the pointer, paging by the side bars, a column paged away showing the single bar, its click bringing the board back to today and the next click opening the spans mode, the pinned line's two states while scrolling. Before and after pictures.
