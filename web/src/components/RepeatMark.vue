<script setup lang="ts">
import AppIcon from './AppIcon.vue'

/* The recurrence mark glued to the last word of a card's title. Measured on the reference
   (P-29, 2026-08-10): 15 x 14 px, 8 px gap, `rgba(45,48,54,.3)`.

   Its own file rather than eleven more lines inside `GoalCard.vue`, which sits against
   ARCHITECTURE.md §2's 750-line module rule (S-90a) — a self-contained mark with no props and no
   state was the cleanest thing to lift out. */
</script>

<template>
  <AppIcon
    name="repeat"
    class="goal-card__repeat"
    data-role="repeat-indicator"
    label="Repeating goal"
  />
</template>

<style>
.goal-card__title-text--repeat {
  position: relative;
  padding-right: 24px;
}
.goal-card__repeat {
  position: absolute;
  right: 0;
  bottom: calc(.46em - 8px);
  width: 15px;
  height: 14px;
  fill: none;
  stroke: rgba(45, 48, 54, .3);
  stroke-width: 2.2;
}
.goal-card--detail-open .goal-card__repeat {
  visibility: hidden;
}
</style>
