# Under the pointer the field's circle widens; a click or a key opens it

Today pointing at the circle opens it from 84 to 201 px, saying "Find or ask". Passing over it shouldn't open anything.

## Behaviour

- Under the pointer the circle widens from 84 to 116 px and stays round-ended, its line grows from 24 to 46 px tall and from 3 to 5 px wide and stays upright, and the Documents and Inbox buttons above it grow from 28 to 38 px, centred over it.
- The field opens on a click, typing on the noninteractive background, `f` from a focused board goal or column, or ⌘K. It never opens on hover. Focused controls keep their own keys.
- The change comes at once under the pointer and settles back in 200 ms when it leaves; under reduced motion there is no animation.

## Done when

UI tests: hover widens without opening, the sizes above, a click and a key open the field. Before and after pictures.
