<script setup lang="ts">
// The period bars, | ||| | (docs/design/column-bars.md): Verticals pages a column with vertical bars, its own sign, in place of
// ← • →. The three in the middle are one button, the middle bar dark: the mode a dragged goal opens on the column's
// corner (`lib/spansDrag.ts`), a week in each column for Week. Under the pointer a bar comes at each side and steps the
// column to the period before and after.
//
// A column whose period no longer holds today (the board is paged away) shows the middle bar alone, `|`, its two light
// neighbours gone: the owner's rule, "the central one first becomes the single | instead of |||, meaning it will bring you
// center". That click goes back to today, as the `t` key does, and the sign turns back into three bars; the next click
// opens the mode. Everything else stands where it did: the two light bars only fade (opacity), so the middle bar, the two
// side bars and the three boxes keep their places and the hand finds them there.
//
// All three are buttons, named for the keyboard and assistive tech by what they do: "Previous week", "Weeks side by
// side" (or "Today", for the single bar), "Next week".
import { computed } from 'vue'
import './columnBars.css'

const props = withDefaults(defineProps<{
  /** The column's kind, "Week": names the side bars. */
  kind: string
  /** What the mode shows, "Weeks": names the three bars. */
  plural: string
  /** The column's period no longer holds today: the sign is the single bar that goes back to it. */
  away?: boolean
  /** Where the words on the line end, in px from the column's left (`ColumnLine.vue`): the left box grows no further. */
  wordsEnd?: number
}>(), { away: false, wordsEnd: 0 })
const emit = defineEmits<{ step: [direction: -1 | 1]; mode: []; today: [] }>()
const noun = computed(() => props.kind.toLowerCase())
function onMiddle(): void {
  if (props.away) emit('today')
  else emit('mode')
}
</script>

<template>
  <!-- The sign's middle stands where it does with or without its sides, and in either look; each button's own box reaches
       outward from its bars, so the three never overlap. -->
  <div
    class="column-bars"
    :class="{ 'column-bars--away': away }"
    :style="{ '--words-end': `${wordsEnd}px` }"
    data-cap="period-nav"
  >
    <button
      class="column-bars__button column-bars__button--prev column-bars__button--side"
      type="button"
      :aria-label="`Previous ${noun}`"
      data-cap="period-prev"
      @click="emit('step', -1)"
    ><span class="column-bars__mark"><i class="column-bars__bar"></i></span></button>
    <button
      class="column-bars__button column-bars__button--mode"
      type="button"
      :aria-label="away ? 'Today' : `${plural} side by side`"
      :data-cap="away ? 'period-today' : 'period-mode'"
      @click="onMiddle"
    ><span class="column-bars__mark"><i class="column-bars__bar column-bars__bar--outer"></i><i class="column-bars__bar column-bars__bar--ink"></i><i class="column-bars__bar column-bars__bar--outer"></i></span></button>
    <button
      class="column-bars__button column-bars__button--next column-bars__button--side"
      type="button"
      :aria-label="`Next ${noun}`"
      data-cap="period-next"
      @click="emit('step', 1)"
    ><span class="column-bars__mark"><i class="column-bars__bar"></i></span></button>
  </div>
</template>
